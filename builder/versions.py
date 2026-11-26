"""Versionen einer App: Stand speichern, wiederherstellen, als Datei weitergeben.

Ein Stand enthält den Aufbau der App (Einstellungen, Tabellen, Felder, Seiten),
nicht die erfassten Daten. Beim Wiederherstellen gehen deshalb keine Einträge
verloren: Tabellen, die es im alten Stand noch nicht gab, bleiben bestehen.
"""
from datetime import time

from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from .blocks import clean_layout
from .models import App, AppVersion, DataQuery, Entity, Field, Page, Script

FORMAT_PREFIX = "baukasten-app/"
FORMAT_VERSION = 2
FORMAT = f"{FORMAT_PREFIX}{FORMAT_VERSION}"
# Geschichte des Formats (bei jeder inkompatiblen Änderung: FORMAT_VERSION erhöhen und unten in
# UPGRADES eine Funktion ergänzen, die den Vorgänger umwandelt; alte Beispieldatei in die Tests):
#   1  erste Fassung
#   2  app.kind (App oder Automatisierung) ist Pflicht; Skripte mit Zeitplan-Angaben;
#      „baukasten_version“ nennt die Baukasten-Version, aus der die Datei stammt
FIELD_TYPES = {key for key, label in Field.TYPES}


def snapshot(app):
    from django.conf import settings

    return {
        "format": FORMAT,
        "baukasten_version": settings.BAUKASTEN_VERSION,
        "app": {"name": app.name, "description": app.description, "icon": app.icon,
                "translations": app.translations or {}, "kind": app.kind},
        "entities": [
            {
                "slug": e.slug, "name": e.name, "allow_create": e.allow_create,
                "allow_edit": e.allow_edit, "allow_delete": e.allow_delete, "api_enabled": e.api_enabled,
                "read_groups": sorted(g.name for g in e.read_groups.all()),
                "write_groups": sorted(g.name for g in e.write_groups.all()),
                "fields": [
                    {"key": f.key, "label": f.label, "type": f.type, "required": f.required,
                     "choices": f.choices, "reference": f.reference.slug if f.reference else None,
                     "show_in_list": f.show_in_list, "show_in_form": f.show_in_form,
                     "formula": f.formula, "order": f.order}
                    for f in e.fields.select_related("reference")
                ],
            }
            for e in app.entities.prefetch_related("read_groups", "write_groups")
        ],
        "pages": [
            {"slug": p.slug, "title": p.title, "show_in_nav": p.show_in_nav, "public": p.public,
             "order": p.order, "layout": p.layout,
             "groups": sorted(g.name for g in p.groups.all())}
            for p in app.pages.prefetch_related("groups")
        ],
        "scripts": [
            {"slug": sc.slug, "name": sc.name, "language": sc.language, "trigger": sc.trigger,
             "page": sc.page.slug if sc.page else None, "entity": sc.entity.slug if sc.entity else None,
             "interval_minutes": sc.interval_minutes, "enabled": sc.enabled, "code": sc.code,
             "daily_time": sc.daily_time.strftime("%H:%M") if sc.daily_time else None,
             "weekdays_only": sc.weekdays_only, "timeout_minutes": sc.timeout_minutes}
            for sc in app.scripts.select_related("page", "entity")
        ],
        "queries": [
            {"slug": q.slug, "name": q.name, "source": q.source, "sql": q.sql, "cache_seconds": q.cache_seconds,
             "sync_entity": q.sync_entity.slug if q.sync_entity else None, "key_column": q.key_column,
             "sync_interval": q.sync_interval}
            for q in app.queries.select_related("sync_entity")
        ],
    }


def create_version(app, user=None, note="", automatic=False):
    last = app.versions.first()
    return AppVersion.objects.create(
        app=app, number=(last.number + 1) if last else 1, note=note[:200], automatic=automatic,
        snapshot=snapshot(app), created_by=user if user and user.is_authenticated else None,
    )


class InvalidSnapshot(ValueError):
    pass


# ---------- Alte Formate anheben ----------

def _upgrade_1_to_2(data):
    data["app"].setdefault("kind", "app")
    for item in data.get("scripts") or []:
        item.setdefault("daily_time", None)
        item.setdefault("weekdays_only", False)
        item.setdefault("timeout_minutes", 30)
    data.setdefault("baukasten_version", "vor 1.1")
    return data


UPGRADES = {1: _upgrade_1_to_2}  # Format n -> n + 1


def format_version(data):
    text = str(data.get("format", "")) if isinstance(data, dict) else ""
    if not text.startswith(FORMAT_PREFIX):
        return None
    try:
        return int(text[len(FORMAT_PREFIX):])
    except ValueError:
        return None


def upgrade(data):
    """Hebt einen Stand älteren Formats auf das aktuelle. Gibt (stand, hinweise) zurück.

    Ältere Dateien und alte, gespeicherte Versionen bleiben so einspielbar. Eine Datei aus einem
    neueren Baukasten wird abgelehnt, weil sie Angaben enthalten kann, die dieser nicht kennt."""
    import copy

    number = format_version(data)
    if number is None or not isinstance(data.get("app"), dict):
        raise InvalidSnapshot(_("Unbekanntes Format: Das ist keine exportierte App des Baukastens."))
    if number > FORMAT_VERSION:
        raise InvalidSnapshot(_("Die Datei stammt aus einer neueren Version des Baukastens (Format %(new)s, "
                                "dieser Baukasten kennt bis %(current)s). Bitte zuerst den Baukasten "
                                "aktualisieren.") % {"new": number, "current": FORMAT_VERSION})
    notes = []
    data = copy.deepcopy(data)
    if number < FORMAT_VERSION:
        notes.append(_("Die Datei hatte ein älteres Format (%(old)s) und wurde automatisch auf das aktuelle "
                       "(%(new)s) umgestellt.") % {"old": number, "new": FORMAT_VERSION})
    while number < FORMAT_VERSION:
        data = UPGRADES[number](data)
        number += 1
    data["format"] = FORMAT
    notes.extend(_missing_blocks(data))
    return data, notes


def _missing_blocks(data):
    """Bausteine, die es in diesem Baukasten nicht (mehr) gibt: bleiben gespeichert, werden aber nicht angezeigt."""
    from .blocks import all_types

    known, notes = all_types(), []
    for page in data.get("pages") or []:
        missing = sorted({str(b.get("type")) for b in page.get("layout") or []
                          if isinstance(b, dict) and b.get("type") not in known})
        if missing:
            notes.append(_("Seite „%(page)s“: Diese Bausteine gibt es in dieser Version nicht. Sie bleiben "
                           "gespeichert, werden aber erst nach einem passenden Update angezeigt: %(types)s.") % {"page": page.get("title") or page.get("slug"), "types": ", ".join(missing)})
    return notes


class AutomationNotAllowed(InvalidSnapshot):
    """Datei enthält eine Automatisierung, die Person gehört nicht zu den Automatisierern."""


def _text(value, limit):
    return str(value or "")[:limit]


def apply(app, data):
    """Bringt die App auf den Stand „data“ (ohne Einzelprotokoll; der Aufrufer fasst zusammen)."""
    from . import audit

    with audit.quiet():
        return _apply_snapshot(app, data)


@transaction.atomic
def _apply_snapshot(app, data):
    """Bringt die App auf den Stand „data“. Gibt die Namen der Tabellen zurück, die
    es im Stand nicht gibt und die wegen ihrer Daten trotzdem erhalten bleiben."""
    data, _notes = upgrade(data)
    try:
        meta, entities, pages = data["app"], data["entities"], data["pages"]
        app.name = _text(meta.get("name"), 80) or app.name
        app.description = _text(meta.get("description"), 200)
        app.icon = _text(meta.get("icon"), 8)
        if "translations" in meta:  # ältere Versionen ohne Übersetzungen lassen die vorhandenen stehen
            from .app_i18n import clean

            app.translations = clean(meta.get("translations"))
        app.save()

        by_slug = {e.slug: e for e in app.entities.all()}
        wanted = {}
        for item in entities:
            slug = _text(item["slug"], 50)
            entity = by_slug.get(slug) or Entity(app=app, slug=slug)
            entity.name = _text(item.get("name"), 80) or slug
            for flag in ("allow_create", "allow_edit", "allow_delete", "api_enabled"):
                setattr(entity, flag, bool(item.get(flag, flag != "api_enabled")))
            entity.save()
            # Gruppen über den Namen; Gruppen, die es hier nicht gibt, fallen weg
            for relation in ("read_groups", "write_groups"):
                if relation not in item:  # ältere Versionen ohne Tabellenrechte: nichts ändern
                    continue
                names = [str(n) for n in item.get(relation) or [] if isinstance(n, str)]
                getattr(entity, relation).set(Group.objects.filter(name__in=names))
            wanted[slug] = (entity, item.get("fields") or [])

        # Felder erst anlegen, wenn alle Tabellen existieren (Verweise zeigen auf Tabellen).
        for entity, fields in wanted.values():
            existing = {f.key: f for f in entity.fields.all()}
            keep = set()
            for position, item in enumerate(fields, start=1):
                key = _text(item["key"], 50)
                if item.get("type") not in FIELD_TYPES:
                    raise InvalidSnapshot(_("Unbekannter Feldtyp „%(type)s“ im Feld „%(field)s“.")
                                          % {"type": item.get("type"), "field": item.get("label") or key})
                field = existing.get(key) or Field(entity=entity, key=key)
                field.label = _text(item.get("label"), 80) or key
                field.type = item["type"]
                field.required = bool(item.get("required"))
                field.choices = _text(item.get("choices"), 5000)
                target = wanted.get(item.get("reference")) or (by_slug.get(item.get("reference")), None)
                field.reference = target[0] if item.get("reference") else None
                field.show_in_list = bool(item.get("show_in_list", True))
                field.show_in_form = bool(item.get("show_in_form", True))
                field.formula = _text(item.get("formula"), 200)
                field.order = int(item.get("order") or position)
                field.save()
                keep.add(key)
            entity.fields.exclude(key__in=keep).delete()

        app.pages.all().delete()
        for position, item in enumerate(pages, start=1):
            page = Page.objects.create(
                app=app, slug=_text(item["slug"], 50), title=_text(item.get("title"), 80) or "Seite",
                show_in_nav=bool(item.get("show_in_nav", True)), public=bool(item.get("public", False)),
                order=int(item.get("order") or position),
                layout=clean_layout(item.get("layout") or [], keep_unknown=True),
            )
            # Gruppen über den Namen; Gruppen, die es hier nicht gibt, fallen weg
            names = [str(n) for n in item.get("groups") or [] if isinstance(n, str)]
            if names:
                page.groups.set(Group.objects.filter(name__in=names))
        _apply_logic(app, data)
    except (KeyError, TypeError, ValueError, IntegrityError) as exc:
        if isinstance(exc, InvalidSnapshot):
            raise
        raise InvalidSnapshot("Die Datei ist unvollständig oder beschädigt.") from exc
    return sorted(e.name for slug, e in by_slug.items() if slug not in wanted)


def _apply_logic(app, data):
    """Skripte und Abfragen (ab Format mit diesen Schlüsseln; ältere Stände lassen sie unverändert)."""
    entities = {e.slug: e for e in app.entities.all()}
    pages = {p.slug: p for p in app.pages.all()}
    if "scripts" in data:
        app.scripts.all().delete()
        # Automatisierungen: nur Python und ihre eigenen Auslöser; normale Apps umgekehrt.
        languages = {Script.PYTHON} if app.is_automation else {key for key, label in Script.LANGUAGES}
        triggers = set(Script.AUTOMATION_TRIGGERS if app.is_automation else Script.APP_TRIGGERS)
        for item in data["scripts"]:
            if item.get("language") not in languages or item.get("trigger") not in triggers:
                raise InvalidSnapshot(_("Die Skripte passen nicht zu dieser Art von App."))
            Script.objects.create(
                app=app, slug=_text(item["slug"], 50), name=_text(item.get("name"), 80) or item["slug"],
                language=item["language"], trigger=item["trigger"], page=pages.get(item.get("page")),
                entity=entities.get(item.get("entity")), interval_minutes=int(item.get("interval_minutes") or 60),
                enabled=bool(item.get("enabled", True)), code=_text(item.get("code"), 200000),
                daily_time=time.fromisoformat(item["daily_time"]) if item.get("daily_time") else None,
                weekdays_only=bool(item.get("weekdays_only")), timeout_minutes=int(item.get("timeout_minutes") or 30),
            )
    if "queries" in data:
        app.queries.all().delete()
        for item in data["queries"]:
            DataQuery.objects.create(
                app=app, slug=_text(item["slug"], 50), name=_text(item.get("name"), 80) or item["slug"],
                source=_text(item.get("source"), 40), sql=_text(item.get("sql"), 50000),
                cache_seconds=int(item.get("cache_seconds") or 0), sync_entity=entities.get(item.get("sync_entity")),
                key_column=_text(item.get("key_column"), 80), sync_interval=int(item.get("sync_interval") or 0),
            )


def restore(version, user=None):
    """Stellt einen Stand wieder her und sichert vorher den aktuellen, damit sich das rückgängig machen lässt."""
    create_version(version.app, user,
                   _("Automatisch gesichert vor Rückkehr zu Version %(number)s") % {"number": version.number},
                   automatic=True)
    from . import audit

    kept = apply(version.app, version.snapshot)
    audit.log("restore", "version", app=version.app, target_id=version.number, label=f"Version {version.number}",
              note=version.note)
    return kept


@transaction.atomic
def import_app(data, user=None, name_override=None):
    """Legt aus einer exportierten Datei eine neue App an (als Entwurf)."""
    from .models import can_automate

    data, notes = upgrade(data)
    if name_override:
        data["app"]["name"] = _text(name_override, 80)
    kind = App.AUTOMATION if data["app"].get("kind") == App.AUTOMATION else App.APP
    if kind == App.AUTOMATION and not (user and can_automate(user)):
        raise AutomationNotAllowed(_("Die Datei enthält eine Automatisierung. Importieren dürfen das nur Mitglieder der Gruppe „Automatisierer“."))
    from . import audit

    with audit.quiet():  # eine Zusammenfassung „importiert“ statt Einzeleinträgen
        app = App.objects.create(name=_text(data["app"].get("name"), 80) or "Importierte App", kind=kind,
                                 created_by=user if user and user.is_authenticated else None)
    apply(app, data)
    from . import audit

    audit.log("import", "app", app=app, target_id=app.pk, label=app.name,
              note=f"{app.entities.count()} Tabellen, {app.pages.count()} Seiten")
    app.import_notes = notes
    return app


def diff(current, target):
    """Vergleicht den aktuellen Stand (current) mit einer gespeicherten Version (target).

    Gibt eine Liste menschenlesbarer Unterschiede aus Sicht von „Was ändert sich beim Wiederherstellen auf target?“ zurück.
    """
    if not isinstance(current, dict) or not isinstance(target, dict):
        return []
    changes = []

    c_app, t_app = current.get("app") or {}, target.get("app") or {}
    if (c_app.get("name"), c_app.get("description"), c_app.get("icon")) != (
        t_app.get("name"), t_app.get("description"), t_app.get("icon")
    ):
        changes.append(_("~ App-Einstellungen (Name, Symbol oder Beschreibung) geändert"))

    def _compare_items(key, label_field, noun_added, noun_removed, noun_changed, detail_fn=None):
        c_map = {str(item.get("slug")): item for item in (current.get(key) or []) if isinstance(item, dict) and item.get("slug")}
        t_map = {str(item.get("slug")): item for item in (target.get(key) or []) if isinstance(item, dict) and item.get("slug")}
        for slug, item in t_map.items():
            name = item.get(label_field) or slug
            if slug not in c_map:
                changes.append(noun_added % {"name": name})
            else:
                c_item = c_map[slug]
                if detail_fn:
                    diff_note = detail_fn(c_item, item)
                else:
                    diff_note = c_item != item
                if diff_note:
                    changes.append(noun_changed % {"name": name})
        for slug, item in c_map.items():
            if slug not in t_map:
                name = item.get(label_field) or slug
                changes.append(noun_removed % {"name": name})

    def _entity_changed(c_ent, t_ent):
        c_fields = [(f.get("key"), f.get("label"), f.get("type"), f.get("required"), f.get("formula", ""))
                    for f in (c_ent.get("fields") or [])]
        t_fields = [(f.get("key"), f.get("label"), f.get("type"), f.get("required"), f.get("formula", ""))
                    for f in (t_ent.get("fields") or [])]
        c_rights = [sorted(c_ent.get(k) or []) for k in ("read_groups", "write_groups")]
        t_rights = [sorted(t_ent.get(k) or []) for k in ("read_groups", "write_groups")]
        return c_ent.get("name") != t_ent.get("name") or c_fields != t_fields or c_rights != t_rights

    def _page_changed(c_pg, t_pg):
        return (c_pg.get("title") != t_pg.get("title")
                or c_pg.get("layout") != t_pg.get("layout")
                or bool(c_pg.get("public")) != bool(t_pg.get("public"))
                or sorted(c_pg.get("groups") or []) != sorted(t_pg.get("groups") or []))

    def _script_changed(c_sc, t_sc):
        return (c_sc.get("name") != t_sc.get("name")
                or c_sc.get("code") != t_sc.get("code")
                or c_sc.get("trigger") != t_sc.get("trigger")
                or bool(c_sc.get("enabled", True)) != bool(t_sc.get("enabled", True)))

    def _query_changed(c_q, t_q):
        return (c_q.get("name") != t_q.get("name")
                or c_q.get("sql") != t_q.get("sql")
                or c_q.get("source") != t_q.get("source"))

    _compare_items(
        "entities", "name",
        _("+ Tabelle „%(name)s“ (in Version enthalten)"),
        _("− Tabelle „%(name)s“ (erst nach dieser Version angelegt; Daten bleiben erhalten)"),
        _("~ Tabelle „%(name)s“ (Felder oder Einstellungen weichen ab)"),
        _entity_changed,
    )
    _compare_items(
        "pages", "title",
        _("+ Seite „%(name)s“ wird wiederhergestellt"),
        _("− Seite „%(name)s“ entfällt"),
        _("~ Seite „%(name)s“ (Bausteine oder Titel geändert)"),
        _page_changed,
    )
    if "scripts" in target or "scripts" in current:
        _compare_items(
            "scripts", "name",
            _("+ Skript „%(name)s“ wird wiederhergestellt"),
            _("− Skript „%(name)s“ entfällt"),
            _("~ Skript „%(name)s“ (Code oder Auslöser geändert)"),
            _script_changed,
        )
    if "queries" in target or "queries" in current:
        _compare_items(
            "queries", "name",
            _("+ Abfrage „%(name)s“ wird wiederhergestellt"),
            _("− Abfrage „%(name)s“ entfällt"),
            _("~ Abfrage „%(name)s“ (SQL oder Quelle geändert)"),
            _query_changed,
        )
    return changes


def restore_from_file(app, data, user=None, filename=""):
    """Eine heruntergeladene Datei in eine bestehende App einspielen. Vorher wird der jetzige
    Stand als Version gesichert. Gibt (gesicherte Version, erhaltene Tabellen, Hinweise) zurück."""
    from . import audit

    data, notes = upgrade(data)
    kind = data["app"].get("kind", App.APP)
    if kind != app.kind:
        raise InvalidSnapshot(_("Die Datei enthält eine Automatisierung, diese App ist aber keine.")
                              if kind == App.AUTOMATION else
                              _("Die Datei enthält eine normale App, diese App ist aber eine Automatisierung."))
    backup = create_version(app, user, _("Automatisch gesichert vor dem Einspielen der Datei %(name)s")
                            % {"name": filename or "?"}, automatic=True)
    kept = apply(app, data)
    audit.log("restore", "version", app=app, target_id=backup.number, label=_("aus Datei %(name)s") % {"name": filename},
              note=_("Datei aus Baukasten %(version)s; vorher gesichert als Version %(number)s")
              % {"version": data.get("baukasten_version", "?"), "number": backup.number})
    return backup, kept, notes
