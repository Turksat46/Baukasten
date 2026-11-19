"""Änderungsprotokoll: wer hat wann was geändert und auf welchem Weg.

Erfasst wird zentral über Django-Signale. So sind alle Wege abgedeckt, über die Daten und der
Aufbau einer App geändert werden: Formulare, Designer, API, MCP, KI-Zugang, Skripte,
Automatisierungen, Verwaltung (/admin/).

Wer und worüber kommt aus einem Kontext, den jeder Eingang setzt (Middleware, API, MCP,
Skripte, Worker). Ohne Kontext gilt „system“ (z. B. Verwaltungsbefehle).

Massenvorgänge (App oder Tabelle löschen, Version wiederherstellen, KI-Änderung, Abgleich mit
einer Datenquelle) erzeugen einen zusammenfassenden Eintrag statt tausender einzelner:
Der Aufrufer schaltet die Einzelerfassung mit quiet() ab und protokolliert selbst.

Nicht erfasst: Änderungen per QuerySet.update()/bulk_*() außerhalb der genannten Stellen und
direkt in der Datenbank. Der Zustand laufender Skripte (Sperren, Lebenszeichen) ist keine
Änderung im Sinne des Protokolls.
"""
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Wege, auf denen etwas geändert wurde
VIA_LABELS = {
    "ui": _("Oberfläche"), "designer": _("Designer"), "api": _("API"), "mcp": _("MCP"), "ki": _("KI-Zugang"),
    "script": _("Skript"), "automation": _("Automatisierung"), "sync": _("Abgleich"), "admin": _("Verwaltung"),
    "system": _("System"),
}
ACTION_LABELS = {
    "create": _("angelegt"), "update": _("geändert"), "delete": _("gelöscht"), "restore": _("wiederhergestellt"),
    "import": _("importiert"), "sync": _("abgeglichen"), "share": _("Freigabe"), "start": _("gestartet"),
    "stop": _("gestoppt"),
}


@dataclass(frozen=True)
class Context:
    user: object = None
    actor: str = ""
    via: str = "system"
    quiet: bool = False


_context = ContextVar("baukasten_audit", default=Context())
# Was gerade gelöscht wird (App, Tabelle): deren Kinder nicht einzeln protokollieren
_deleting = threading.local()


def current():
    return _context.get()


@contextmanager
def context(**values):
    token = _context.set(replace(_context.get(), **values))
    try:
        yield
    finally:
        _context.reset(token)


def quiet():
    """Einzelerfassung aus; der Aufrufer protokolliert selbst eine Zusammenfassung."""
    return context(quiet=True)


def via_for_path(path):
    if path.startswith("/api/"):
        return "api"
    if path.startswith("/mcp/designer/"):
        return "ki"
    if path.startswith("/mcp/"):
        return "mcp"
    if path.startswith("/designer/"):
        return "designer"
    if path.startswith("/admin/"):
        return "admin"
    return "ui"


class AuditMiddleware:
    """Setzt den Kontext für jede Anfrage: angemeldete Person (oder Gast) und Weg."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        authenticated = bool(user and user.is_authenticated)
        with context(user=user if authenticated else None, actor="" if authenticated else "Gast",
                     via=via_for_path(request.path), quiet=False):
            return self.get_response(request)


def _plain(value):
    """Für JSON: Datum, Uhrzeit, Dezimalzahl als Text."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def log(action, target_type, *, app=None, target_id="", label="", scope="", changes=None, note="",
        force=False, **override):
    """Einen Eintrag schreiben. Gibt ihn zurück (oder None, wenn gerade quiet() gilt und nicht force)."""
    from .models import AuditEntry

    ctx = replace(current(), **override) if override else current()
    if ctx.quiet and not force:
        return None
    user = ctx.user if ctx.user is not None and getattr(ctx.user, "is_authenticated", False) else None
    return AuditEntry.objects.create(
        app=app if app is not None and app.pk else None, app_slug=app.slug if app else "",
        app_name=app.name[:80] if app else "", user=user, username=user.get_username() if user else "",
        actor=ctx.actor[:120], via=ctx.via, action=action, target_type=target_type,
        target_id=str(target_id or "")[:40], target_label=str(label or "")[:200], scope=scope[:50],
        changes=changes or {}, note=str(note or "")[:300],
    )


# ---------- Einträge der Apps ----------

def _record_app(record):
    entity = record.entity
    return entity.app, entity


def _record_pre_save(sender, instance, **kwargs):
    instance._audit_old = (sender.objects.filter(pk=instance.pk).values_list("data", flat=True).first()
                           if instance.pk else None)


def _record_post_save(sender, instance, created, **kwargs):
    if current().quiet or _being_deleted(instance):
        return
    app, entity = _record_app(instance)
    new = instance.data or {}
    if created:
        changes = {k: [None, _plain(v)] for k, v in new.items() if v not in (None, "")}
    else:
        old = getattr(instance, "_audit_old", None) or {}
        changes = {k: [_plain(old.get(k)), _plain(new.get(k))] for k in sorted(set(old) | set(new))
                   if old.get(k) != new.get(k)}
        if not changes:
            return
    log("create" if created else "update", "record", app=app, target_id=instance.pk,
        label=f"{entity.name} #{instance.pk}", scope=entity.slug, changes=changes)


def _record_post_delete(sender, instance, **kwargs):
    if current().quiet or _being_deleted(instance):
        return
    app, entity = _record_app(instance)
    changes = {k: [_plain(v), None] for k, v in (instance.data or {}).items() if v not in (None, "")}
    log("delete", "record", app=app, target_id=instance.pk, label=f"{entity.name} #{instance.pk}",
        scope=entity.slug, changes=changes)


# ---------- Aufbau der Apps ----------

def _summary_code(value):
    lines = len((value or "").splitlines())
    return f"{lines} Zeilen"


def _summary_layout(value):
    return f"{len(value or [])} Bausteine"


# Modell -> (verfolgte Felder, Typ im Protokoll, Bezeichnung, App, Tabelle für „scope“)
def _tracked():
    from .models import ApiKey, App, DataQuery, DesignerToken, Entity, Field, Page, PlatformSettings, Script

    return {
        App: (["name", "description", "icon", "published", "kind"], "app",
              lambda o: o.name, lambda o: o, lambda o: ""),
        Entity: (["name", "allow_create", "allow_edit", "allow_delete", "api_enabled"], "entity",
                 lambda o: o.name, lambda o: o.app, lambda o: o.slug),
        Field: (["label", "type", "required", "choices", "reference_id", "show_in_list", "show_in_form"], "field",
                lambda o: f"{o.entity.name}: {o.label}", lambda o: o.entity.app, lambda o: o.entity.slug),
        Page: (["title", "show_in_nav", "public", "layout"], "page", lambda o: o.title, lambda o: o.app,
               lambda o: ""),
        Script: (["name", "language", "trigger", "enabled", "code", "page_id", "entity_id", "interval_minutes",
                  "daily_time", "weekdays_only", "timeout_minutes"], "script", lambda o: o.name, lambda o: o.app,
                 lambda o: ""),
        DataQuery: (["name", "source", "sql", "cache_seconds", "sync_entity_id", "key_column", "sync_interval"],
                    "query", lambda o: o.name, lambda o: o.app, lambda o: ""),
        ApiKey: (["name", "can_write"], "key", lambda o: f"{o.name} ({o.prefix}…)", lambda o: o.app, lambda o: ""),
        DesignerToken: (["name"], "token", lambda o: f"{o.name} ({o.prefix}…)", lambda o: None, lambda o: ""),
        PlatformSettings: (["public_rate", "ai_writes", "audit_retention_days", "script_timeout",
                            "script_max_calls", "automation_max_timeout_minutes"], "settings",
                           lambda o: "Einstellungen des Baukastens", lambda o: None, lambda o: ""),
    }


SUMMARIZED = {"code": _summary_code, "layout": _summary_layout}


def _value(field, value):
    if field in SUMMARIZED:
        return SUMMARIZED[field](value)
    return _plain(value)


def _structure_pre_save(sender, instance, update_fields=None, **kwargs):
    fields = _tracked()[sender][0]
    if update_fields is not None and not set(update_fields) & set(fields):
        instance._audit_skip = True
        return
    instance._audit_skip = False
    instance._audit_old = sender.objects.filter(pk=instance.pk).values(*fields).first() if instance.pk else None


def _structure_post_save(sender, instance, created, **kwargs):
    if current().quiet or getattr(instance, "_audit_skip", False) or _being_deleted(instance):
        return
    fields, kind, label, app_of, scope_of = _tracked()[sender]
    if created:
        changes = {}
    else:
        old = getattr(instance, "_audit_old", None) or {}
        changes = {}
        for f in fields:
            before, after = old.get(f), getattr(instance, f)
            if before != after:
                pair = [_value(f, before), _value(f, after)]
                if pair[0] == pair[1]:  # gleiche Zusammenfassung, anderer Inhalt
                    pair = ["…", "Inhalt geändert"]
                changes[f.removesuffix("_id")] = pair
        if not changes:
            return
    log("create" if created else "update", kind, app=app_of(instance), target_id=instance.pk,
        label=label(instance), scope=scope_of(instance), changes=changes)


def _structure_pre_delete(sender, instance, **kwargs):
    from .models import App, Entity

    if sender is App:
        _deleting_set("apps").add(instance.pk)
        # Auch die Tabellen merken: Einträge prüfen dann ohne weitere Abfrage
        instance._audit_entities = set(instance.entities.values_list("pk", flat=True))
        _deleting_set("entities").update(instance._audit_entities)
    elif sender is Entity:
        _deleting_set("entities").add(instance.pk)
        instance._audit_records = instance.records.count()


def _structure_post_delete(sender, instance, **kwargs):
    from .models import App, Entity

    if sender is App:
        _deleting_set("apps").discard(instance.pk)
        _deleting_set("entities").difference_update(getattr(instance, "_audit_entities", set()))
    elif sender is Entity:
        if instance.app_id not in _deleting_set("apps"):  # sonst räumt das Löschen der App auf
            _deleting_set("entities").discard(instance.pk)
    if current().quiet or (sender is not App and _being_deleted(instance)):
        return
    fields, kind, label, app_of, scope_of = _tracked()[sender]
    note = ""
    if sender is Entity:
        note = f"mit {getattr(instance, '_audit_records', 0)} Einträgen"
    try:
        app = None if sender is App else app_of(instance)
    except Exception:  # noqa: BLE001 - Eltern schon weg
        app = None
    entry = log("delete", kind, app=app, target_id=instance.pk, label=label(instance), scope=scope_of(instance),
                note=note)
    if entry is not None and sender is App:
        # Die App selbst ist gelöscht: Name und Kurzname für die Nachwelt festhalten
        entry.app_slug, entry.app_name = instance.slug, instance.name[:80]
        entry.save(update_fields=["app_slug", "app_name"])


def _deleting_set(name):
    if not hasattr(_deleting, name):
        setattr(_deleting, name, set())
    return getattr(_deleting, name)


def _being_deleted(instance):
    """Gehört das Objekt zu einer App oder Tabelle, die gerade gelöscht wird?"""
    apps, entities = _deleting_set("apps"), _deleting_set("entities")
    if not apps and not entities:
        return False
    entity_id = getattr(instance, "entity_id", None)
    if entity_id in entities:
        return True
    app_id = getattr(instance, "app_id", None)
    if app_id is None and entity_id is not None:
        from .models import Entity

        app_id = Entity.objects.filter(pk=entity_id).values_list("app_id", flat=True).first()
    return app_id in apps


def connect():
    from .models import Record

    pre_save.connect(_record_pre_save, sender=Record, dispatch_uid="audit-record-pre")
    post_save.connect(_record_post_save, sender=Record, dispatch_uid="audit-record-post")
    post_delete.connect(_record_post_delete, sender=Record, dispatch_uid="audit-record-delete")
    for model in _tracked():
        uid = f"audit-{model.__name__}"
        pre_save.connect(_structure_pre_save, sender=model, dispatch_uid=uid + "-pre")
        post_save.connect(_structure_post_save, sender=model, dispatch_uid=uid + "-post")
        pre_delete.connect(_structure_pre_delete, sender=model, dispatch_uid=uid + "-predel")
        post_delete.connect(_structure_post_delete, sender=model, dispatch_uid=uid + "-del")


# ---------- Aufbewahrung ----------

def cleanup(now=None):
    """Einträge löschen, die älter als AUDIT_RETENTION_DAYS sind (0 = nie). Gibt die Anzahl zurück."""
    from .models import AuditEntry

    from . import platform

    days = platform.value("audit_retention_days")
    if not days:
        return 0
    limit = (now or timezone.now()) - timedelta(days=days)
    deleted, _detail = AuditEntry.objects.filter(created_at__lt=limit).delete()
    return deleted


def describe(entry):
    """Kurztext einer Änderung für Listen, z. B. „status: offen → genehmigt“."""
    parts = []
    for key, pair in list((entry.changes or {}).items())[:6]:
        old, new = (pair + [None, None])[:2] if isinstance(pair, list) else (None, pair)
        if entry.action == "create":
            parts.append(f"{key}: {_short(new)}")
        elif entry.action == "delete":
            parts.append(f"{key}: {_short(old)}")
        else:
            parts.append(f"{key}: {_short(old)} → {_short(new)}")
    more = len(entry.changes or {}) - 6
    if more > 0:
        parts.append(f"… und {more} weitere")
    return "; ".join(parts)


def _short(value):
    if value is None or value == "":
        return "–"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "…"
