"""Wann Skripte laufen: beim Öffnen einer Seite, per Button, nach dem Speichern, zeitgesteuert."""
import json
import logging
import time
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from ..models import App, Script, ScriptRun
from . import python
from .ops import serialize

log = logging.getLogger(__name__)
KEEP_RUNS = 20
MAX_TEXT = 20000


def execute(script, trigger, user=None, event=None, record=None, params=None, store="always", request=None):
    """Führt ein Python-Skript aus und protokolliert den Lauf.

    store: "always" oder "errors" (Seitenaufrufe: nur Fehler speichern, sonst entstünde pro Aufruf ein Eintrag).
    """
    started = time.monotonic()
    event = {"trigger": trigger, **(event or {})}
    session = load_session(request, script.app) if request is not None else None
    result = python.run(script.code, script.app, user=user, event=event, record=record, params=params,
                        session=session)
    if request is not None and result.ok and result.session is not None and result.session != session:
        save_session(request, script.app, result.session)
    result.duration_ms = int((time.monotonic() - started) * 1000)
    now = timezone.now()
    Script.objects.filter(pk=script.pk).update(last_run_at=now)
    script.last_run_at = now
    if store == "always" or not result.ok:
        ScriptRun.objects.create(
            script=script, trigger=trigger, duration_ms=result.duration_ms, ok=result.ok,
            log="\n".join(result.log)[:MAX_TEXT], error=result.error_text()[:MAX_TEXT],
        )
        old = list(script.runs.values_list("pk", flat=True)[KEEP_RUNS:])
        if old:
            ScriptRun.objects.filter(pk__in=old).delete()
    if not result.ok:
        log.warning("Skript %s/%s fehlgeschlagen: %s", script.app.slug, script.slug, result.error_text())
    return result


SESSION_MAX_BYTES = 4096


def _session_key(app):
    return f"baukasten-skript:{app.slug}"


def load_session(request, app):
    """Merkzettel der Skripte für diesen Besucher (Django-Sitzung, Cookie) und diese App."""
    value = request.session.get(_session_key(app)) if hasattr(request, "session") else None
    return dict(value) if isinstance(value, dict) else {}


def save_session(request, app, value):
    """Speichert den Merkzettel, wenn er JSON ist und höchstens 4 KB groß; sonst bleibt der alte."""
    if not hasattr(request, "session"):
        return
    try:
        size = len(json.dumps(value))
    except (TypeError, ValueError):
        return
    if size <= SESSION_MAX_BYTES:
        request.session[_session_key(app)] = value


def page_scripts(app, page, language=Script.PYTHON):
    scripts = app.scripts.filter(enabled=True, trigger=Script.PAGE, language=language)
    return scripts.filter(Q(page__isnull=True) | Q(page=page)) if page else scripts.filter(page__isnull=True)


def run_page(request, app, page):
    """Python-Skripte einer Seite. Gibt (Änderungen je Baustein, Meldungen, Fehler) zurück."""
    ui, messages, errors = {}, [], []
    for script in page_scripts(app, page):
        result = execute(script, Script.PAGE, user=request.user,
                         event={"page": page.slug if page else ""}, params=request.GET.dict(), store="errors",
                         request=request)
        for name, values in result.ui.items():
            ui.setdefault(name, {}).update(values)
        messages.extend(result.messages)
        if not result.ok:
            errors.append((script, result.error_text()))
    return ui, messages, errors


def on_save(record, created, user):
    """Nach dem Speichern eines Eintrags. Läuft nicht, wenn ein Skript selbst gespeichert hat (keine Schleifen)."""
    if python.running.get():
        return
    entity = record.entity
    scripts = entity.app.scripts.filter(enabled=True, trigger=Script.SAVE, language=Script.PYTHON).filter(
        Q(entity__isnull=True) | Q(entity=entity))
    for script in scripts:
        fields = list(entity.fields.all())
        before = serialize(record, fields)
        result = execute(script, Script.SAVE, user=user, record=dict(before),
                         event={"table": entity.slug, "created": created, "id": record.pk})
        changed = {}
        if result.ok and isinstance(result.record, dict):
            keys = {f.key for f in fields}
            changed = {k: v for k, v in result.record.items() if k in keys and before.get(k) != v}
        if changed:
            # Direkt speichern: kein erneutes Auslösen der Skripte, Werte so wie vom Skript gesetzt.
            record.data = {**record.data, **changed}
            record.save(update_fields=["data", "updated_at"])


def run_due(now=None):
    """Zeitgesteuerte Skripte, deren Intervall abgelaufen ist. Gibt die Anzahl der Läufe zurück."""
    now = now or timezone.now()
    count = 0
    # Automatisierungen übernimmt der Hintergrunddienst selbst (worker.py).
    scripts = Script.objects.filter(enabled=True, trigger=Script.SCHEDULE, language=Script.PYTHON,
                                    app__kind=App.APP).select_related("app")
    for script in scripts:
        if script.last_run_at and script.last_run_at + timedelta(minutes=max(script.interval_minutes, 1)) > now:
            continue
        execute(script, Script.SCHEDULE, event={"time": now.isoformat()})
        count += 1
    return count
