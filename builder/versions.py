"""Versionen einer App: Stand speichern, wiederherstellen, als Datei weitergeben.

Ein Stand enthält den Aufbau der App (Einstellungen, Tabellen, Felder, Seiten),
nicht die erfassten Daten. Beim Wiederherstellen gehen deshalb keine Einträge
verloren: Tabellen, die es im alten Stand noch nicht gab, bleiben bestehen.
"""
from datetime import time

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from .blocks import clean_layout
from .models import App, AppVersion, DataQuery, Entity, Field, Page, Script

FORMAT = "baukasten-app/1"
FIELD_TYPES = {key for key, label in Field.TYPES}


def snapshot(app):
    return {
        "format": FORMAT,
        "app": {"name": app.name, "description": app.description, "icon": app.icon,
                "translations": app.translations or {}, "kind": app.kind},
        "entities": [
            {
                "slug": e.slug, "name": e.name, "allow_create": e.allow_create,
                "allow_edit": e.allow_edit, "allow_delete": e.allow_delete, "api_enabled": e.api_enabled,
                "fields": [
                    {"key": f.key, "label": f.label, "type": f.type, "required": f.required,
                     "choices": f.choices, "reference": f.reference.slug if f.reference else None,
                     "show_in_list": f.show_in_list, "show_in_form": f.show_in_form, "order": f.order}
                    for f in e.fields.select_related("reference")
                ],
            }
            for e in app.entities.all()
        ],
        "pages": [
            {"slug": p.slug, "title": p.title, "show_in_nav": p.show_in_nav, "public": p.public,
             "order": p.order, "layout": p.layout}
            for p in app.pages.all()
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


class AutomationNotAllowed(InvalidSnapshot):
    """Datei enthält eine Automatisierung, die Person gehört nicht zu den Automatisierern."""


def _text(value, limit):
    return str(value or "")[:limit]


@transaction.atomic
def apply(app, data):
    """Bringt die App auf den Stand „data“. Gibt die Namen der Tabellen zurück, die
    es im Stand nicht gibt und die wegen ihrer Daten trotzdem erhalten bleiben."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise InvalidSnapshot("Unbekanntes Format.")
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
            wanted[slug] = (entity, item.get("fields") or [])

        # Felder erst anlegen, wenn alle Tabellen existieren (Verweise zeigen auf Tabellen).
        for slug, (entity, fields) in wanted.items():
            existing = {f.key: f for f in entity.fields.all()}
            keep = set()
            for position, item in enumerate(fields, start=1):
                key = _text(item["key"], 50)
                if item.get("type") not in FIELD_TYPES:
                    raise InvalidSnapshot("Unbekannter Feldtyp.")
                field = existing.get(key) or Field(entity=entity, key=key)
                field.label = _text(item.get("label"), 80) or key
                field.type = item["type"]
                field.required = bool(item.get("required"))
                field.choices = _text(item.get("choices"), 5000)
                target = wanted.get(item.get("reference")) or (by_slug.get(item.get("reference")), None)
                field.reference = target[0] if item.get("reference") else None
                field.show_in_list = bool(item.get("show_in_list", True))
                field.show_in_form = bool(item.get("show_in_form", True))
                field.order = int(item.get("order") or position)
                field.save()
                keep.add(key)
            entity.fields.exclude(key__in=keep).delete()

        app.pages.all().delete()
        for position, item in enumerate(pages, start=1):
            Page.objects.create(
                app=app, slug=_text(item["slug"], 50), title=_text(item.get("title"), 80) or "Seite",
                show_in_nav=bool(item.get("show_in_nav", True)), public=bool(item.get("public", False)),
                order=int(item.get("order") or position),
                layout=clean_layout(item.get("layout") or []),
            )
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
    return apply(version.app, version.snapshot)


@transaction.atomic
def import_app(data, user=None):
    """Legt aus einer exportierten Datei eine neue App an (als Entwurf)."""
    from .models import can_automate

    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("app"), dict):
        raise InvalidSnapshot("Unbekanntes Format.")
    kind = App.AUTOMATION if data["app"].get("kind") == App.AUTOMATION else App.APP
    if kind == App.AUTOMATION and not (user and can_automate(user)):
        raise AutomationNotAllowed(_("Die Datei enthält eine Automatisierung. Importieren dürfen das nur Mitglieder der Gruppe „Automatisierer“."))
    app = App.objects.create(name=_text(data["app"].get("name"), 80) or "Importierte App", kind=kind,
                             created_by=user if user and user.is_authenticated else None)
    apply(app, data)
    return app
