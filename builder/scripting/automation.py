"""Führt Skripte von Automatisierungen aus: echtes Python, nur im Hintergrunddienst (worker.py).

Unterschiede zu den Skripten normaler Apps (python.py):
- kein RestrictedPython: alle installierten Bibliotheken (requirements-automation.in), Dateien
  im eigenen Arbeitsordner, Threads, Unterprozesse
- Zeitlimit in Minuten statt Sekunden, „läuft ständig“ ganz ohne Zeitlimit
- Ausgaben kommen laufend an (Live-Protokoll), Stoppen per SIGTERM

Was gleich bleibt: Der Prozess startet mit leerer Umgebung (keine Zugangsdaten). Tabellen,
Abfragen und Geheimnisse erfragt er beim Elternprozess, der sie auf die eigene App begrenzt.
Unter Linux laufen die Prozesse in einer eigenen Sitzung mit Speichergrenze; läuft der Dienst
als root, zusätzlich als Benutzer „nobody“. Der Dienst selbst macht sich „nicht auslesbar“
(siehe worker.harden), damit ein Skript nicht über /proc an dessen Zugangsdaten kommt.
"""
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

from django.conf import settings
from django.utils.translation import gettext as _

from .. import app_i18n, datasources
from ..models import Script, ScriptRun
from ..services import HttpNotAllowed
from . import python
from .ops import OpsError

NOBODY = 65534
STOP_GRACE = 10  # Sekunden zwischen SIGTERM und SIGKILL
PASS_THROUGH = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
                "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "LANG", "LC_ALL")


class Control:
    """Steuerung eines laufenden Skripts von außen: stoppen (Knopf) oder abbrechen (Dienst endet)."""

    def __init__(self):
        self.reason = None
        self.changed = threading.Event()

    def request(self, reason):
        if self.reason is None:
            self.reason = reason
        self.changed.set()


@dataclass
class Outcome:
    status: str
    error: str = ""
    line: int = None

    @property
    def ok(self):
        return self.status == ScriptRun.OK


def _site_dirs():
    dirs = [python._restricted_python_dir()]
    dirs += [p for p in sys.path if p and ("site-packages" in p or "dist-packages" in p) and p not in dirs]
    return dirs


def _environment(workdir):
    env = python._environment()
    env.update(HOME=workdir, TMPDIR=workdir, TEMP=workdir, TMP=workdir, PYTHONUNBUFFERED="1")
    for name in PASS_THROUGH:
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def _limits(cpu_seconds, memory_mb):
    def apply():
        import resource

        if cpu_seconds:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))
        if memory_mb:
            memory = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()
        if os.getuid() == 0:
            os.setgroups([])
            os.setgid(NOBODY)
            os.setuid(NOBODY)

    return apply


def _signal(proc, kill=False):
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL if kill else signal.SIGTERM)
        elif kill:
            proc.kill()
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def timeout_seconds(script):
    if script.trigger == Script.CONTINUOUS:
        return None
    from .. import platform

    limit = platform.value("automation_max_timeout_minutes")
    return max(1, min(script.timeout_minutes or 30, limit)) * 60


def run(script, event, control, on_log):
    """Führt das Skript aus, bis es fertig ist, gestoppt wird oder das Zeitlimit erreicht. Gibt ein Outcome zurück.

    on_log(zeile) wird für jede Ausgabezeile aufgerufen, sobald sie kommt.
    """
    app = script.app
    timeout = timeout_seconds(script)
    handler = python.Handler(app, secrets=True)
    context = {
        "mode": "full", "code": script.code,
        "app": {"name": app.name, "slug": app.slug, "translations": app_i18n.mapping(app)},
        "event": event or {}, "params": (event or {}).get("daten") if isinstance((event or {}).get("daten"), dict) else {},
        "max_calls": settings.BAUKASTEN_AUTOMATION_MAX_CALLS,
    }
    workdir = tempfile.mkdtemp(prefix=f"automation-{app.slug}-")
    errors = tempfile.TemporaryFile()
    kwargs = {}
    if os.name == "posix":
        kwargs["preexec_fn"] = _limits(timeout + 30 if timeout else 0, settings.BAUKASTEN_AUTOMATION_MEMORY_MB)
        if os.getuid() == 0:
            os.chown(workdir, NOBODY, NOBODY)
    elif os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", str(python.CHILD), *_site_dirs()], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errors, env=_environment(workdir), cwd=workdir, **kwargs,
        )
    except OSError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        errors.close()
        return Outcome(ScriptRun.ERROR, _("Skript konnte nicht gestartet werden: %(error)s") % {"error": exc})

    lines = queue.Queue()

    def reader():
        for raw in iter(lambda: proc.stdout.readline(python.MAX_LINE), b""):
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    started = time.monotonic()
    terminating_since = None
    timed_out = False
    outcome = None
    try:
        proc.stdin.write((json.dumps(context, default=str) + "\n").encode())
        proc.stdin.flush()
        while outcome is None:
            now = time.monotonic()
            if terminating_since is None:
                if control.reason:
                    terminating_since = now
                    _signal(proc)
                elif timeout and now - started > timeout:
                    timed_out = True
                    terminating_since = now
                    _signal(proc)
            elif now - terminating_since > STOP_GRACE:
                _signal(proc, kill=True)
            try:
                raw = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if raw is None:
                outcome = _ended_without_answer(errors, control, timed_out, timeout)
                break
            try:
                message = json.loads(raw)
            except ValueError:
                on_log(raw.decode("utf-8", "replace").rstrip())
                continue
            if message.get("done"):
                outcome = _finished(message, control, timed_out, timeout)
                break
            if "log" in message:
                on_log(str(message["log"]))
                continue
            _answer(proc, handler, message)
    finally:
        if outcome is not None and proc.poll() is None:
            try:
                proc.wait(timeout=5)  # Skript ist fertig, eigene Threads dürfen noch kurz aufräumen
            except subprocess.TimeoutExpired:
                pass
        _signal(proc, kill=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        errors.seek(0)
        rest = errors.read()[-4000:].decode("utf-8", "replace").strip()
        if rest:
            for line in rest.splitlines():
                on_log(line)
        errors.close()
        shutil.rmtree(workdir, ignore_errors=True)
    return outcome


def _timeout_text(timeout):
    return _("Zeitlimit von %(minutes)s Minuten überschritten.") % {"minutes": int(timeout // 60)}


def _finished(message, control, timed_out, timeout):
    if timed_out:
        return Outcome(ScriptRun.ERROR, _timeout_text(timeout))
    if message.get("stopped"):
        return Outcome(control.reason or ScriptRun.STOPPED, _("Gestoppt."))
    if message.get("ok"):
        return Outcome(ScriptRun.OK)
    return Outcome(ScriptRun.ERROR, message.get("error") or "", message.get("line"))


def _ended_without_answer(errors, control, timed_out, timeout):
    if timed_out:
        return Outcome(ScriptRun.ERROR, _timeout_text(timeout))
    if control.reason:
        return Outcome(control.reason, _("Gestoppt."))
    errors.seek(0)
    detail = errors.read().decode("utf-8", "replace").strip().splitlines()
    hint = detail[-1][:300] if detail else _("ohne Meldung, z. B. Speichergrenze erreicht")
    return Outcome(ScriptRun.ERROR, _("Das Skript wurde abgebrochen (%(detail)s).") % {"detail": hint})


def _answer(proc, handler, message):
    try:
        answer = {"result": handler(str(message.get("call")), message.get("args") or {})}
    except OpsError as exc:
        details = "; ".join(f"{key}: {' '.join(e['message'] for e in errs)}" for key, errs in exc.fields.items())
        answer = {"error": f"{exc} {details}".strip()}
    except (datasources.QueryError, HttpNotAllowed) as exc:
        answer = {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - Fehler der Gegenstelle an das Skript melden
        answer = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    try:
        proc.stdin.write((json.dumps(answer, default=str) + "\n").encode())
        proc.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
