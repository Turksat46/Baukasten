"""Hintergrunddienst („Aufseher“): startet, überwacht und stoppt die Skripte der Automatisierungen.

Läuft als eigener, dauerhafter Prozess (Kubernetes: Deployment baukasten-worker mit genau einem
Pod; lokal: python manage.py hintergrund --dauerhaft). Erledigt nebenbei die bisherigen
Hintergrundarbeiten (zeitgesteuerte Skripte normaler Apps, Abgleiche mit Datenquellen).

- Jeder Lauf ist ein eigener Kindprozess (automation.py), mehrere laufen gleichzeitig.
- Kein Überholen: Ein Skript läuft nie zweimal gleichzeitig. Dafür sorgt eine Sperre in der
  Datenbank (Script.running_since mit Lebenszeichen heartbeat_at), auch über Pods hinweg.
- „Läuft ständig“: startet nach dem Ende neu, nach Fehlern mit wachsender Wartezeit.
- Beim Beenden (SIGTERM, z. B. Deploy) werden laufende Skripte gestoppt und als „abgebrochen“
  vermerkt; Dauerläufer starten mit dem nächsten Dienst von selbst wieder.
"""
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, connection
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from ..models import App, Script, ScriptRun
from . import automation, schedule

log = logging.getLogger(__name__)

TICK = 2.0               # Sekunden zwischen zwei Prüfungen
STALE = timedelta(seconds=90)   # ohne Lebenszeichen gilt ein Lauf als verwaist
LEGACY_EVERY = 30        # Sekunden: Skripte normaler Apps, Abgleiche
LIVE_FLUSH = 2.0         # Sekunden: Live-Protokoll in die Datenbank schreiben
MAX_LOG = 50000          # Zeichen Protokoll je Lauf (das Ende bleibt)
KEEP_RUNS = 30
BACKOFF = (10, 30, 120, 300, 600)  # Sekunden Wartezeit vor dem Neustart eines Dauerläufers
HEALTHY_AFTER = timedelta(minutes=10)  # so lange gelaufen: Fehlerzähler zurücksetzen


def harden():
    """Unter Linux: Prozess „nicht auslesbar“ machen. Dann gehören /proc/<pid>/environ und mem
    root, und Skripte (gleicher Benutzer) kommen nicht an die Zugangsdaten des Dienstes."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(4, 0, 0, 0, 0) == 0  # PR_SET_DUMPABLE = 4
    except (OSError, AttributeError):
        return False


ALIVE_FILE = os.path.join(tempfile.gettempdir(), "baukasten-worker-alive")


def alive():
    """Lebenszeichen für die livenessProbe in k8s/worker.yaml und für /metrics (baukasten_worker_up)."""
    from ..metrics import worker_heartbeat

    worker_heartbeat()
    try:
        with open(ALIVE_FILE, "a", encoding="utf-8"):
            pass
        os.utime(ALIVE_FILE, None)
    except OSError:
        pass


def background_once(out=None):
    """Bisherige Hintergrundarbeiten einmal: fällige Skripte normaler Apps und Abgleiche."""
    from ..datasources import sync_and_record
    from ..models import DataQuery
    from .triggers import run_due

    now = timezone.now()
    scripts = run_due(now)
    syncs = failed = 0
    for query in DataQuery.objects.filter(sync_interval__gt=0).select_related("app", "sync_entity"):
        if query.last_sync_at and query.last_sync_at + timedelta(minutes=query.sync_interval) > now:
            continue
        syncs += 1
        if not sync_and_record(query):
            failed += 1
            log.warning("Abgleich %s/%s: %s", query.app.slug, query.slug, query.last_sync_message)
    return scripts, syncs, failed


class LiveLog:
    """Sammelt Ausgabezeilen eines Laufs und schreibt sie alle paar Sekunden in die Datenbank."""

    def __init__(self, run):
        self.run_id = run.pk
        self.lines = deque()
        self.size = 0
        self.dirty = False
        self.flushed = time.monotonic()

    def add(self, line):
        self.lines.append(line)
        self.size += len(line) + 1
        while self.size > MAX_LOG and len(self.lines) > 1:
            self.size -= len(self.lines.popleft()) + 1
        self.dirty = True
        if time.monotonic() - self.flushed > LIVE_FLUSH:
            self.flush()

    def text(self):
        return "\n".join(self.lines)[-MAX_LOG:]

    def flush(self):
        if self.dirty:
            ScriptRun.objects.filter(pk=self.run_id).update(log=self.text())
            self.dirty = False
        self.flushed = time.monotonic()


def execute(script, trigger, event, control):
    """Ein vollständiger Lauf mit Protokoll. Die Sperre (running_since) muss schon gesetzt sein."""
    started = timezone.now()
    run = ScriptRun.objects.create(script=script, trigger=trigger, status=ScriptRun.RUNNING)
    live = LiveLog(run)
    outcome = None
    try:
        outcome = automation.run(script, event, control, live.add)
    except Exception as exc:  # noqa: BLE001 - der Dienst darf nicht mit abstürzen
        log.exception("Automatisierung %s/%s", script.app.slug, script.slug)
        outcome = automation.Outcome(ScriptRun.ERROR, f"{type(exc).__name__}: {exc}")
    finished = timezone.now()
    error = outcome.error
    if outcome.line and error:
        error = _("Zeile %(line)s: %(error)s") % {"line": outcome.line, "error": error}
    ScriptRun.objects.filter(pk=run.pk).update(
        status=outcome.status, ok=outcome.ok, error=error[:20000], log=live.text(), finished_at=finished,
        duration_ms=min(int((finished - started).total_seconds() * 1000), 2**31 - 1),
    )
    _release(script, started, finished, outcome, trigger)
    old = list(script.runs.values_list("pk", flat=True)[KEEP_RUNS:])
    if old:
        ScriptRun.objects.filter(pk__in=old).delete()
    if not outcome.ok and outcome.status != ScriptRun.STOPPED:
        log.warning("Automatisierung %s/%s: %s %s", script.app.slug, script.slug, outcome.status, error)
    return outcome


def _release(script, started, finished, outcome, trigger):
    """Sperre lösen und den nächsten Termin festlegen."""
    current = Script.objects.filter(pk=script.pk).values("next_run_at", "failures", "trigger", "enabled").first()
    if current is None:  # inzwischen gelöscht
        return
    script.trigger = current["trigger"]
    updates = {"running_since": None, "heartbeat_at": None, "stop_requested": False}
    if script.trigger in schedule.TIMED:
        nxt, missed = schedule.catch_up(script, current["next_run_at"], finished)
        updates["next_run_at"] = nxt
        if missed:
            ScriptRun.objects.create(
                script=script, trigger=script.trigger, status=ScriptRun.SKIPPED, ok=True, finished_at=finished,
                log=ngettext("%(n)s Termin entfallen, weil dieser Lauf noch lief.",
                             "%(n)s Termine entfallen, weil dieser Lauf noch lief.", missed) % {"n": missed},
            )
    elif script.trigger == Script.CONTINUOUS and trigger == Script.CONTINUOUS:
        if outcome.status == ScriptRun.ABORTED:
            updates["next_run_at"] = None  # beim nächsten Start des Dienstes sofort wieder
        else:
            failures = current["failures"]
            if outcome.ok or finished - started > HEALTHY_AFTER:
                failures = 0
            else:
                failures += 1
            delay = BACKOFF[min(max(failures - 1, 0), len(BACKOFF) - 1)]
            updates.update(failures=failures, next_run_at=finished + timedelta(seconds=delay))
    Script.objects.filter(pk=script.pk).update(**updates)


class Job:
    def __init__(self, worker, script, trigger, event):
        self.worker = worker
        self.script = script
        self.trigger = trigger
        self.event = event
        self.control = automation.Control()
        self.continuous = trigger == Script.CONTINUOUS
        self.thread = threading.Thread(target=self._run, name=f"skript-{script.pk}", daemon=True)

    def _run(self):
        try:
            execute(self.script, self.trigger, self.event, self.control)
        finally:
            connection.close()
            self.worker.finished(self)


class Worker:
    def __init__(self, parallel=None, out=None):
        self.parallel = parallel or settings.BAUKASTEN_AUTOMATION_PARALLEL
        self.out = out or sys.stdout
        self.jobs = {}
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.legacy_at = 0.0

    def say(self, text):
        stamp = timezone.localtime().strftime("%H:%M:%S")
        try:
            self.out.write(f"{stamp} {text}\n")
            self.out.flush()
        except (OSError, ValueError):
            pass

    # ---- Ablauf ----

    def serve(self):
        if harden():
            self.say("Prozess gegen Auslesen durch Skripte geschützt.")
        for name in ("SIGTERM", "SIGINT"):
            try:
                signal.signal(getattr(signal, name), lambda *_args: self.stopping.set())
            except (AttributeError, ValueError):
                pass
        self.say(f"Hintergrunddienst läuft (bis zu {self.parallel} Läufe gleichzeitig, Dauerläufer zusätzlich).")
        while not self.stopping.is_set():
            try:
                close_old_connections()
                self.tick()
                alive()
                if time.monotonic() - self.legacy_at > LEGACY_EVERY:
                    self.legacy_at = time.monotonic()
                    self.start_legacy()
            except Exception:  # noqa: BLE001 - weiterlaufen, beim nächsten Mal erneut versuchen
                log.exception("Hintergrunddienst")
            self.stopping.wait(TICK)
        self.shutdown()

    def start_legacy(self):
        """Bisherige Hintergrundarbeiten in einem eigenen Thread, damit sie den Aufseher nicht aufhalten."""
        if getattr(self, "_legacy", None) and self._legacy.is_alive():
            return

        def work():
            try:
                scripts, syncs, failed = background_once()
                if scripts or syncs:
                    self.say(f"{scripts} Skripte normaler Apps, {syncs} Abgleiche ({failed} fehlgeschlagen).")
            except Exception:  # noqa: BLE001
                log.exception("Hintergrundarbeiten")
            finally:
                connection.close()

        self._legacy = threading.Thread(target=work, name="hintergrund", daemon=True)
        self._legacy.start()

    def tick(self, now=None):
        now = now or timezone.now()
        with self.lock:
            active = dict(self.jobs)
        if active:
            Script.objects.filter(pk__in=active).update(heartbeat_at=now)
            rows = {row["pk"]: row for row in Script.objects.filter(pk__in=active).values("pk", "stop_requested", "enabled")}
            for pk, job in active.items():
                row = rows.get(pk)
                # Stoppen: Knopf, Skript gelöscht, Dauerläufer ausgeschaltet
                if row is None or row["stop_requested"] or (job.continuous and not row["enabled"]):
                    job.control.request(ScriptRun.STOPPED)
        self.recover(now)
        self.plan(now)
        started = []
        for script in self.due(now, exclude=active):
            job = self.claim(script, now)
            if job:
                started.append(job)
        return started

    def recover(self, now):
        """Läufe ohne Lebenszeichen (Dienst abgestürzt oder hart beendet) freigeben."""
        with self.lock:
            mine = set(self.jobs)
        stale = Script.objects.filter(running_since__isnull=False).filter(
            Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=now - STALE)).exclude(pk__in=mine)
        for pk in stale.values_list("pk", flat=True):
            abandon(pk, now)

    def plan(self, now):
        """Zeitgesteuerten Skripten ohne Termin (neu, umgestellt) den ersten Termin geben."""
        for script in Script.objects.filter(app__kind=App.AUTOMATION, enabled=True, trigger__in=schedule.TIMED,
                                            next_run_at__isnull=True):
            Script.objects.filter(pk=script.pk).update(next_run_at=schedule.first_run(script, now))

    def due(self, now, exclude=()):
        base = Script.objects.filter(app__kind=App.AUTOMATION, language=Script.PYTHON,
                                     running_since__isnull=True).exclude(pk__in=list(exclude))
        wanted = (Q(run_requested=True)
                  | Q(enabled=True, trigger__in=schedule.TIMED, next_run_at__lte=now)
                  | (Q(enabled=True, trigger=Script.CONTINUOUS) & (Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))))
        return list(base.filter(wanted).select_related("app").order_by("next_run_at", "pk"))

    def busy(self):
        with self.lock:
            return sum(1 for job in self.jobs.values() if not job.continuous)

    def claim(self, script, now):
        requested = script.run_requested
        continuous = script.trigger == Script.CONTINUOUS and not requested
        if not continuous and self.busy() >= self.parallel:
            return None
        event = dict(script.request_event or {}) if requested else {}
        trigger = str(event.pop("trigger", Script.MANUAL))[:10] if requested else script.trigger
        updates = {"running_since": now, "heartbeat_at": now, "last_run_at": now, "stop_requested": False}
        if requested:
            updates.update(run_requested=False, request_event=None)
        elif script.trigger in schedule.TIMED:
            updates["next_run_at"] = schedule.next_after_start(script, script.next_run_at, now)
        claimed = Script.objects.filter(pk=script.pk, running_since__isnull=True,
                                        run_requested=requested).update(**updates)
        if not claimed:
            return None
        for key, value in updates.items():
            setattr(script, key, value)
        event.update(trigger=trigger, time=now.isoformat())
        job = Job(self, script, trigger, event)
        with self.lock:
            self.jobs[script.pk] = job
        self.say(f"Start: {script.app.slug}/{script.slug} ({trigger})")
        job.thread.start()
        return job

    def finished(self, job):
        with self.lock:
            self.jobs.pop(job.script.pk, None)
        self.say(f"Ende: {job.script.app.slug}/{job.script.slug}")

    def shutdown(self, wait=20):
        with self.lock:
            jobs = list(self.jobs.values())
        if jobs:
            self.say(f"Beende {len(jobs)} laufende Skripte …")
        for job in jobs:
            job.control.request(ScriptRun.ABORTED)
        deadline = time.monotonic() + wait
        for job in jobs:
            job.thread.join(max(deadline - time.monotonic(), 0.1))
        now = timezone.now()
        for job in jobs:
            if job.thread.is_alive():
                abandon(job.script.pk, now)
        self.say("Hintergrunddienst beendet.")


def abandon(pk, now=None):
    """Sperre eines Skripts lösen, dessen Lauf nicht mehr überwacht wird."""
    now = now or timezone.now()
    ScriptRun.objects.filter(script_id=pk, status=ScriptRun.RUNNING).update(
        status=ScriptRun.ABORTED, ok=False, finished_at=now,
        error=_("Der Hintergrunddienst wurde während des Laufs beendet."))
    Script.objects.filter(pk=pk).update(running_since=None, heartbeat_at=None, stop_requested=False)


def request_run(script, trigger=Script.MANUAL, **event):
    """Lauf anfordern (Knopf, Webhook, MCP). False, wenn schon einer wartet."""
    payload = {"trigger": trigger, "requested_at": timezone.now().isoformat(), **event}
    return bool(Script.objects.filter(pk=script.pk, run_requested=False).update(
        run_requested=True, request_event=payload))


def status(script):
    """Zustand für die Oberfläche: running / requested / off / error / waiting."""
    if script.running_since:
        return "running"
    if script.run_requested:
        return "requested"
    if not script.enabled:
        return "off"
    if script.trigger == Script.CONTINUOUS and script.failures:
        return "error"
    return "waiting"
