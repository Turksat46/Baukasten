"""Kennzahlen für die Überwachung: GET /metrics im Textformat von Prometheus.

Nur mit Schlüssel: Umgebungsvariable METRICS_TOKEN setzen und beim Abruf
„Authorization: Bearer <METRICS_TOKEN>“ mitschicken. Ohne METRICS_TOKEN gibt es /metrics nicht.
Beantwortet wird vor der Host-Prüfung (wie /healthz), damit Prometheus die Pods direkt
abfragen kann. Beispiel-Alarme stehen in docs/BETRIEB.md.
"""
import hmac
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone

WORKER_KEY = "baukasten-worker-heartbeat"
WORKER_STALE = 120  # Sekunden ohne Lebenszeichen: Worker gilt als ausgefallen


def worker_heartbeat():
    """Vom Hintergrunddienst bei jeder Runde aufgerufen. Braucht einen gemeinsamen Cache
    (Redis oder Datenbank); mit CACHE_BACKEND=memory sieht der Web-Pod es nicht."""
    try:
        cache.set(WORKER_KEY, time.time(), 600)
    except Exception:  # noqa: BLE001 - Überwachung darf den Dienst nie stören
        pass


def _line(name, value, help_text, labels, out, typed, kind="gauge"):
    if name not in typed:
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} {kind}")
        typed.add(name)
    label = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
    out.append(f"{name}{label} {value}")


def collect():
    from .models import App, DataQuery, Record, Script, ScriptRun

    now = timezone.now()
    out, typed = [], set()

    def gauge(name, value, help_text, labels=None):
        _line(name, value, help_text, labels, out, typed)

    gauge("baukasten_info", 1, "Version des Baukastens", {"version": settings.BAUKASTEN_VERSION})
    kinds = dict(App.objects.values_list("kind").annotate(n=Count("id")))
    for kind in (App.APP, App.AUTOMATION):
        gauge("baukasten_apps", kinds.get(kind, 0), "Anzahl Apps je Art", {"kind": kind})
    gauge("baukasten_records", Record.objects.count(), "Anzahl Einträge in allen Tabellen")

    seen = cache.get(WORKER_KEY)
    age = round(time.time() - seen, 1) if seen else -1
    gauge("baukasten_worker_up", 1 if seen and age < WORKER_STALE else 0,
          f"1, wenn der Hintergrunddienst in den letzten {WORKER_STALE} s ein Lebenszeichen gab")
    gauge("baukasten_worker_heartbeat_age_seconds", age, "Sekunden seit dem letzten Lebenszeichen (-1 = keins)")

    automations = Script.objects.filter(app__kind=App.AUTOMATION)
    gauge("baukasten_automation_running", automations.filter(running_since__isnull=False).count(),
          "Laufende Skripte von Automatisierungen")
    gauge("baukasten_automation_stale_locks",
          automations.filter(running_since__isnull=False).filter(
              Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=now - timedelta(seconds=90))).count(),
          "Läufe ohne Lebenszeichen (Worker ausgefallen?)")
    gauge("baukasten_automation_waiting_requests",
          sum(1 for e in automations.filter(run_requested=True).values_list("request_event", flat=True)
              if _older_than((e or {}).get("requested_at"), now, 60)),
          "Angeforderte Starts, die seit über 60 s warten")
    gauge("baukasten_automation_continuous_failing",
          automations.filter(trigger=Script.CONTINUOUS, enabled=True, failures__gt=0).count(),
          "Dauerläufer, die nach Fehlern auf einen Neustart warten")

    since = now - timedelta(hours=24)
    failed = dict(ScriptRun.objects.filter(started_at__gte=since, ok=False).exclude(status=ScriptRun.STOPPED)
                  .values_list("script__app__kind").annotate(n=Count("id")))
    for kind in (App.APP, App.AUTOMATION):
        gauge("baukasten_script_runs_failed_24h", failed.get(kind, 0),
              "Fehlgeschlagene Skriptläufe der letzten 24 Stunden", {"kind": kind})
    gauge("baukasten_datasource_sync_failed",
          DataQuery.objects.filter(sync_interval__gt=0, last_sync_ok=False).count(),
          "Abfragen, deren letzter Abgleich fehlschlug")
    return "\n".join(out) + "\n"


def _older_than(iso, now, seconds):
    try:
        from datetime import datetime

        return (now - datetime.fromisoformat(iso)).total_seconds() > seconds
    except (TypeError, ValueError):
        return False


def response(request):
    token = settings.BAUKASTEN_METRICS_TOKEN
    if not token:
        return HttpResponse(status=404)
    header = request.headers.get("Authorization", "")
    given = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(given.encode(), token.encode()):
        reply = HttpResponse("Bearer-Token fehlt oder ist falsch.", status=401, content_type="text/plain")
        reply["WWW-Authenticate"] = "Bearer"
        return reply
    return HttpResponse(collect(), content_type="text/plain; version=0.0.4; charset=utf-8")
