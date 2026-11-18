"""Apps mit einer KI nach Wahl bauen: Designer-Werkzeuge für den MCP-Server /mcp/designer/.

Eine KI (Claude, Cursor, n8n …) bekommt mit einem persönlichen Schlüssel (DesignerToken)
dieselben Rechte wie die Person im Designer und kann damit Apps anlegen und ändern.

Das Format ist das Versionsformat (versions.py), nur freundlicher: Kurznamen dürfen fehlen,
Auswahlwerte dürfen eine Liste sein, die App-Angaben stehen oben statt unter "app".
Jeder Fehler kommt mit Pfad und Erklärung zurück, damit die KI ihn selbst beheben kann.

Schutz:
- Neue Apps sind Entwürfe; veröffentlichen, Gruppen, öffentliche Seiten und API-Freigaben
  bleiben Sache eines Menschen im Designer (bestehende Einstellungen bleiben erhalten).
- Neue oder geänderte Skripte sind ausgeschaltet, bis jemand sie im Designer prüft.
- Vor jeder Änderung sichert der Baukasten eine Version; restore_version macht sie rückgängig.
- Automatisierungen nur mit dem Recht dafür; Schreibvorgänge je Schlüssel begrenzt.
"""
import copy
from datetime import time

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.urls import reverse
from django.utils.text import slugify

from . import audit, versions
from .blocks import WIDTHS, all_types
from .models import App, Field, Script, can_automate

LIMITS = {"entities": 30, "fields": 60, "pages": 30, "blocks": 100, "scripts": 30, "code": 100_000}
FIELD_TYPES = [key for key, _label in Field.TYPES]


class Invalid(Exception):
    """Die Definition ist ungültig; errors ist eine Liste von „Pfad: Erklärung“."""

    def __init__(self, errors, warnings=()):
        super().__init__("; ".join(errors))
        self.errors = list(errors)
        self.warnings = list(warnings)


# ---------- Lesen ----------

def export(app):
    """Eine App im Format der Werkzeuge (wie create_app/update_app es erwarten)."""
    data = versions.snapshot(app)
    meta = data.pop("app")
    data.pop("format", None)
    data.pop("queries", None)  # Abfragen pflegt nur der Designer (Datenquellen richtet der Betrieb ein)
    meta.pop("translations", None)
    for entity in data["entities"]:
        for f in entity["fields"]:
            if f["type"] == Field.CHOICE:
                f["choices"] = [c.strip() for c in (f["choices"] or "").splitlines() if c.strip()]
            else:
                f.pop("choices", None)
            if f["type"] != Field.REFERENCE:
                f.pop("reference", None)
    return {"slug": app.slug, **meta, "published": app.published, **data}


def summary(app):
    return {"slug": app.slug, "name": app.name, "icon": app.icon, "kind": app.kind,
            "published": app.published, "tables": app.entities.count(), "pages": app.pages.count(),
            "scripts": app.scripts.count()}


# ---------- Prüfen und umwandeln ----------

def _unique(base, taken, sep):
    base = base or "x"
    slug, i = base, 2
    while slug in taken:
        slug = f"{base}{sep}{i}"
        i += 1
    taken.add(slug)
    return slug


def _bool(value, default):
    return default if value is None else bool(value)


def normalize(definition, app=None, kind=App.APP):
    """Prüft eine Definition und macht daraus einen Versionsstand. Gibt (stand, warnungen) zurück
    oder wirft Invalid mit allen Fehlern auf einmal."""
    errors, warnings = [], []
    if not isinstance(definition, dict):
        raise Invalid(["definition: erwartet wird ein JSON-Objekt."])
    data = copy.deepcopy(definition)
    if isinstance(data.get("app"), dict):  # Versionsformat (Download aus dem Designer) annehmen
        data = {**data["app"], **{k: v for k, v in data.items() if k not in ("app", "format")}}
    current = versions.snapshot(app) if app else None

    name = str(data.get("name") or (app.name if app else "")).strip()
    if not name:
        errors.append("name: Die App braucht einen Namen.")
    meta = {"name": name[:80], "description": str(data.get("description") or "")[:200],
            "icon": str(data.get("icon") or (app.icon if app else "📦"))[:8], "kind": kind}

    # Tabellen: fehlen sie, bleibt es beim jetzigen Stand
    if "entities" not in data and current:
        entities = current["entities"]
    else:
        entities = _entities(data.get("entities", []), errors, warnings)
    entity_fields = {e["slug"]: {f["key"] for f in e["fields"]} for e in entities}
    _check_references(entities, errors)

    if kind == App.AUTOMATION and data.get("pages"):
        errors.append("pages: Automatisierungen haben keine Seiten.")
    if "pages" not in data and current:
        pages = current["pages"]
    else:
        pages = [] if kind == App.AUTOMATION else _pages(data.get("pages", []), entity_fields, errors, warnings)

    if kind == App.APP and not pages:
        warnings.append("pages: Die App hat keine Seiten; Nutzer sehen dann nichts. Tipp: eine Seite mit einem "
                        "Baustein „table“ je Tabelle.")
    snapshot = {"format": versions.FORMAT, "app": meta, "entities": entities, "pages": pages}
    if "scripts" in data:
        snapshot["scripts"] = _scripts(data["scripts"], kind, {p["slug"] for p in pages}, entity_fields,
                                       errors, warnings)
    if errors:
        raise Invalid(errors, warnings)
    return snapshot, warnings


def _entities(raw, errors, warnings):
    if not isinstance(raw, list):
        errors.append("entities: erwartet wird eine Liste von Tabellen.")
        return []
    if len(raw) > LIMITS["entities"]:
        errors.append(f"entities: höchstens {LIMITS['entities']} Tabellen.")
    result, slugs = [], set()
    for i, item in enumerate(raw[:LIMITS["entities"]]):
        path = f"entities[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: erwartet wird ein Objekt mit name und fields.")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            errors.append(f"{path}.name: Jede Tabelle braucht einen Namen.")
        slug = _unique(slugify(str(item.get("slug") or name))[:50] or "tabelle", slugs, "-")
        fields_raw = item.get("fields")
        if not isinstance(fields_raw, list) or not fields_raw:
            errors.append(f"{path}.fields: Jede Tabelle braucht mindestens ein Feld.")
            fields_raw = []
        if len(fields_raw) > LIMITS["fields"]:
            errors.append(f"{path}.fields: höchstens {LIMITS['fields']} Felder je Tabelle.")
        fields, keys = [], set()
        for j, f in enumerate(fields_raw[:LIMITS["fields"]]):
            fpath = f"{path}.fields[{j}]"
            if not isinstance(f, dict):
                errors.append(f"{fpath}: erwartet wird ein Objekt mit label und type.")
                continue
            label = str(f.get("label") or "").strip()
            if not label:
                errors.append(f"{fpath}.label: Jedes Feld braucht eine Bezeichnung.")
            ftype = str(f.get("type") or Field.TEXT).strip().lower()
            if ftype not in FIELD_TYPES:
                errors.append(f"{fpath}.type: „{ftype}“ gibt es nicht. Erlaubt: {', '.join(FIELD_TYPES)}.")
            key = _unique(slugify(str(f.get("key") or label)).replace("-", "_")[:50] or "feld", keys, "_")
            choices = f.get("choices") or ""
            if isinstance(choices, list):
                choices = "\n".join(str(c).strip() for c in choices if str(c).strip())
            choices = str(choices)
            if ftype == Field.CHOICE and not choices.strip():
                errors.append(f"{fpath}.choices: Ein Auswahlfeld braucht Auswahlwerte (Liste von Texten).")
            reference = f.get("reference") if ftype == Field.REFERENCE else None
            if ftype == Field.REFERENCE and not reference:
                errors.append(f"{fpath}.reference: Ein Verweis braucht den Kurznamen (slug) der Zieltabelle.")
            fields.append({"key": key, "label": label[:80] or key, "type": ftype, "required": bool(f.get("required")),
                           "choices": choices[:5000], "reference": str(reference)[:50] if reference else None,
                           "show_in_list": _bool(f.get("show_in_list"), True),
                           "show_in_form": _bool(f.get("show_in_form"), True), "order": j + 1})
        result.append({"slug": slug, "name": name[:80] or slug,
                       "allow_create": _bool(item.get("allow_create"), True),
                       "allow_edit": _bool(item.get("allow_edit"), True),
                       "allow_delete": _bool(item.get("allow_delete"), True),
                       "api_enabled": False, "fields": fields})
    return result


def _check_references(entities, errors):
    slugs = {e["slug"] for e in entities}
    for i, e in enumerate(entities):
        for j, f in enumerate(e["fields"]):
            if f["type"] == Field.REFERENCE and f["reference"] and f["reference"] not in slugs:
                errors.append(f"entities[{i}].fields[{j}].reference: Eine Tabelle „{f['reference']}“ gibt es nicht. "
                              f"Vorhanden: {', '.join(sorted(slugs)) or 'keine'}.")


def _pages(raw, entity_fields, errors, warnings):
    if not isinstance(raw, list):
        errors.append("pages: erwartet wird eine Liste von Seiten.")
        return []
    if len(raw) > LIMITS["pages"]:
        errors.append(f"pages: höchstens {LIMITS['pages']} Seiten.")
    types = all_types()
    result, slugs = [], set()
    for i, page in enumerate(raw[:LIMITS["pages"]]):
        path = f"pages[{i}]"
        if not isinstance(page, dict):
            errors.append(f"{path}: erwartet wird ein Objekt mit title und layout.")
            continue
        title = str(page.get("title") or "").strip()
        if not title:
            errors.append(f"{path}.title: Jede Seite braucht einen Titel.")
        slug = _unique(slugify(str(page.get("slug") or title))[:50] or "seite", slugs, "-")
        layout = page.get("layout") or []
        if not isinstance(layout, list):
            errors.append(f"{path}.layout: erwartet wird eine Liste von Bausteinen.")
            layout = []
        if len(layout) > LIMITS["blocks"]:
            errors.append(f"{path}.layout: höchstens {LIMITS['blocks']} Bausteine je Seite.")
        for j, block in enumerate(layout[:LIMITS["blocks"]]):
            _check_block(block, f"{path}.layout[{j}]", types, entity_fields, errors, warnings)
        result.append({"slug": slug, "title": title[:80] or slug, "show_in_nav": _bool(page.get("show_in_nav"), True),
                       "public": False, "order": i + 1, "layout": layout[:LIMITS["blocks"]]})
    # Verweise auf Seiten (Button „Seite öffnen“) erst prüfen, wenn alle Kurznamen feststehen
    for i, page in enumerate(result):
        for j, block in enumerate(page["layout"]):
            target = (block.get("props") or {}).get("page") if isinstance(block, dict) else None
            if target and target not in slugs:
                errors.append(f"pages[{i}].layout[{j}].props.page: Eine Seite „{target}“ gibt es nicht. "
                              f"Vorhanden: {', '.join(sorted(slugs))}.")
    return result


def _check_block(block, path, types, entity_fields, errors, warnings):
    if not isinstance(block, dict) or block.get("type") not in types:
        found = block.get("type") if isinstance(block, dict) else block
        errors.append(f"{path}.type: Den Baustein „{found}“ gibt es nicht. Erlaubt: {', '.join(types)}.")
        return
    if block.get("width") not in (None, *WIDTHS):
        errors.append(f"{path}.width: erlaubt sind {', '.join(map(str, WIDTHS))} (Spalten von 12).")
    props = block.get("props") if isinstance(block.get("props"), dict) else {}
    specs = {spec["key"]: spec for spec in types[block["type"]].fields}
    for key in props:
        if key not in specs:
            warnings.append(f"{path}.props.{key}: Diese Einstellung kennt der Baustein „{block['type']}“ nicht; "
                            f"sie wird ignoriert. Bekannt: {', '.join(specs) or 'keine'}.")
    entity = props.get("entity")
    for key, spec in specs.items():
        value = props.get(key)
        if value in (None, ""):
            continue
        if spec["type"] == "entity" and value not in entity_fields:
            errors.append(f"{path}.props.{key}: Eine Tabelle „{value}“ gibt es nicht. "
                          f"Vorhanden: {', '.join(sorted(entity_fields)) or 'keine'}.")
        elif spec["type"] == "field" and entity in entity_fields and value not in entity_fields[entity]:
            errors.append(f"{path}.props.{key}: Die Tabelle „{entity}“ hat kein Feld „{value}“. "
                          f"Vorhanden: {', '.join(sorted(entity_fields[entity]))}.")
        elif spec["type"] == "select":
            allowed = [str(option[0]) for option in spec.get("options", [])]
            if allowed and str(value) not in allowed:
                errors.append(f"{path}.props.{key}: „{value}“ ist nicht erlaubt. Erlaubt: {', '.join(allowed)}.")


def _scripts(raw, kind, pages, entity_fields, errors, warnings):
    if not isinstance(raw, list):
        errors.append("scripts: erwartet wird eine Liste von Skripten.")
        return []
    triggers = Script.AUTOMATION_TRIGGERS if kind == App.AUTOMATION else Script.APP_TRIGGERS
    languages = (Script.PYTHON,) if kind == App.AUTOMATION else (Script.PYTHON, Script.JAVASCRIPT)
    result, slugs = [], set()
    for i, item in enumerate(raw[:LIMITS["scripts"]]):
        path = f"scripts[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: erwartet wird ein Objekt mit name, trigger und code.")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            errors.append(f"{path}.name: Jedes Skript braucht einen Namen.")
        language = str(item.get("language") or Script.PYTHON)
        trigger = str(item.get("trigger") or triggers[0])
        if language not in languages:
            errors.append(f"{path}.language: erlaubt: {', '.join(languages)}.")
        if trigger not in triggers:
            errors.append(f"{path}.trigger: „{trigger}“ ist hier nicht erlaubt. Erlaubt: {', '.join(triggers)}.")
        if language == Script.JAVASCRIPT and trigger in Script.PYTHON_ONLY:
            errors.append(f"{path}.trigger: JavaScript läuft nur beim Öffnen einer Seite (page) oder per Button.")
        code = str(item.get("code") or "")
        if len(code) > LIMITS["code"]:
            errors.append(f"{path}.code: höchstens {LIMITS['code']} Zeichen.")
        page, entity = item.get("page"), item.get("entity")
        if page and page not in pages:
            errors.append(f"{path}.page: Eine Seite „{page}“ gibt es nicht.")
        if entity and entity not in entity_fields:
            errors.append(f"{path}.entity: Eine Tabelle „{entity}“ gibt es nicht.")
        daily = item.get("daily_time")
        if trigger == Script.DAILY:
            try:
                time.fromisoformat(str(daily))
            except ValueError:
                errors.append(f"{path}.daily_time: Uhrzeit als „HH:MM“ angeben.")
        result.append({
            "slug": _unique(slugify(str(item.get("slug") or name))[:50] or "skript", slugs, "-"),
            "name": name[:80], "language": language, "trigger": trigger, "page": page or None,
            "entity": entity or None, "interval_minutes": int(item.get("interval_minutes") or 60),
            "enabled": False, "code": code, "daily_time": str(daily) if daily else None,
            "weekdays_only": bool(item.get("weekdays_only")), "timeout_minutes": int(item.get("timeout_minutes") or 30),
        })
    return result


def protect(snapshot, app):
    """Was nur Menschen freigeben: öffentliche Seiten, API-Freigaben und geprüfte Skripte bleiben,
    wie sie im Designer eingestellt sind; alles Neue ist aus."""
    if app is None:
        return snapshot
    public = set(app.pages.filter(public=True).values_list("slug", flat=True))
    for page in snapshot["pages"]:
        page["public"] = page["slug"] in public
    api = set(app.entities.filter(api_enabled=True).values_list("slug", flat=True))
    for entity in snapshot["entities"]:
        entity["api_enabled"] = entity["slug"] in api
    if "scripts" in snapshot:
        approved = {sc.slug: sc for sc in app.scripts.all()}
        for item in snapshot["scripts"]:
            old = approved.get(item["slug"])
            unchanged = old and old.code == item["code"] and old.trigger == item["trigger"] \
                and old.language == item["language"]
            item["enabled"] = bool(unchanged and old.enabled)
    return snapshot


# ---------- Schreiben ----------

def check_rate(token):
    """Höchstens BAUKASTEN_AI_WRITES Änderungen je Schlüssel in 10 Minuten."""
    from . import platform

    limit = platform.value("ai_writes")
    if not limit:
        return True
    key = f"baukasten-ki:{token.pk}"
    cache.add(key, 0, 600)
    try:
        return cache.incr(key) <= limit
    except ValueError:
        cache.set(key, 1, 600)
        return True


@transaction.atomic
def create(user, definition, label):
    kind = App.AUTOMATION if (definition or {}).get("kind") == App.AUTOMATION else App.APP
    if kind == App.AUTOMATION and not can_automate(user):
        raise Invalid(["kind: Automatisierungen darf nur die Gruppe „Automatisierer“ anlegen."])
    snapshot, warnings = normalize(definition, kind=kind)
    with audit.quiet():  # eine Zusammenfassung unten statt Einzeleinträgen
        app = App.objects.create(name=snapshot["app"]["name"], kind=kind, created_by=user)
    try:
        versions.apply(app, snapshot)
    except versions.InvalidSnapshot as exc:
        raise Invalid([f"definition: {exc}"], warnings) from exc
    versions.create_version(app, user, f"Angelegt über den KI-Zugang „{label}“"[:200], automatic=True)
    audit.log("create", "app", app=app, target_id=app.pk, label=app.name,
              note=f"{app.entities.count()} Tabellen, {app.pages.count()} Seiten, {app.scripts.count()} Skripte")
    return app, warnings


@transaction.atomic
def update(user, app, definition, label):
    snapshot, warnings = normalize(definition, app=app, kind=app.kind)
    protect(snapshot, app)
    snapshot["app"].pop("translations", None)
    before = versions.create_version(app, user, f"Vor Änderung über den KI-Zugang „{label}“"[:200], automatic=True)
    try:
        kept = versions.apply(app, snapshot)
    except versions.InvalidSnapshot as exc:
        raise Invalid([f"definition: {exc}"], warnings) from exc
    audit.log("update", "app", app=app, target_id=app.pk, label=app.name,
              note=f"Ganze App neu gesetzt; vorher gesichert als Version {before.number}")
    return before, kept, warnings


def designer_url(request, app):
    return request.build_absolute_uri(reverse("designer_app", args=[app.slug]))
