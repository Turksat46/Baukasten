"""Startet Python-Skripte in einem eigenen Prozess und beantwortet dessen Anfragen.

Schutzmaßnahmen:
- eigener Prozess mit leerer Umgebung: keine Zugangsdaten, keine Datenbankverbindung
- RestrictedPython im Kindprozess (siehe child.py)
- Zeitlimit; unter Linux zusätzlich Grenzen für Rechenzeit, Speicher und Dateien
- jede Anfrage (Tabellen, Abfragen, Web-Requests) prüft dieser Prozess
"""
import functools
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.utils.translation import gettext as _

from .. import app_i18n, datasources
from ..services import HttpNotAllowed, http_json, http_request
from .ops import OpsError, TableOps

CHILD = Path(__file__).with_name("child.py")


def _restricted_python_dir():
    """Ordner, aus dem RestrictedPython geladen wird (für den isoliert gestarteten Kindprozess)."""
    import RestrictedPython

    return str(Path(RestrictedPython.__file__).resolve().parent.parent)
MAX_LINE = 2_000_000
running = ContextVar("baukasten_script_running", default=False)


@dataclass
class Result:
    ok: bool
    log: list = field(default_factory=list)
    ui: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    record: dict = None
    session: dict = None
    error: str = ""
    line: int = None
    duration_ms: int = 0

    def error_text(self):
        if not self.error:
            return ""
        return _("Zeile %(line)s: %(error)s") % {"line": self.line, "error": self.error} if self.line else self.error


def _limits(cpu_seconds):
    def apply():
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        memory = settings.BAUKASTEN_SCRIPT_MEMORY_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        os.setsid()

    return apply


@functools.lru_cache(maxsize=4)
def posix_timezone(name):
    """Zeitzonen-Regel im POSIX-Format (z. B. "CET-1CEST,M3.5.0,M10.5.0/3") für die Umgebungsvariable TZ.

    Steht am Ende jeder TZif-Datei. So stimmt datetime.now() in Skripten mit der Zeitzone des
    Baukastens überein, auch in schlanken Containern ohne /usr/share/zoneinfo.
    """
    data = None
    try:
        from importlib import resources
        data = resources.files("tzdata.zoneinfo").joinpath(*name.split("/")).read_bytes()
    except Exception:  # noqa: BLE001 - Paket tzdata fehlt: Systemdateien versuchen
        try:
            with open(os.path.join("/usr/share/zoneinfo", *name.split("/")), "rb") as handle:
                data = handle.read()
        except OSError:
            return ""
    if not data.startswith(b"TZif"):
        return ""
    footer = data.rstrip(b"\n").rsplit(b"\n", 1)[-1]
    return footer.decode("ascii", "ignore") if footer and not footer.startswith(b"TZif") else ""


def _environment():
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    else:
        rule = posix_timezone(settings.TIME_ZONE)
        if rule:
            env["TZ"] = rule
    return env


class Handler:
    """Beantwortet die Anfragen des Skripts. Alles bleibt auf die eigene App begrenzt."""

    def __init__(self, app, user=None, secrets=False):
        self.app = app
        self.tables = TableOps(app, user=user, enforce_flags=False)
        self.secrets = secrets  # nur Automatisierungen (Hintergrunddienst)

    def __call__(self, op, args):
        if op == "secret" and self.secrets:
            return script_secret(args.get("name"))
        if op.startswith("table."):
            method = op.split(".", 1)[1]
            if method not in ("filter", "get", "count", "aggregate", "create", "update", "delete"):
                raise OpsError(_("Unbekannte Anfrage."))
            return getattr(self.tables, method)(**args)
        if op == "http.get_json":
            return http_json(str(args.get("url", "")), params=args.get("params") or None)
        if op == "http.post_json":
            response = http_request("POST", str(args.get("url", "")), json=args.get("data"))
            response.raise_for_status()
            return response.json() if response.content else None
        if op == "db.query":
            return datasources.run(args.get("source"), str(args.get("sql", "")), args.get("params") or {},
                                   limit=args.get("limit") or 1000)["rows"]
        if op == "db.saved":
            query = self.app.queries.filter(slug=str(args.get("slug"))).first()
            if query is None:
                raise OpsError(_("Die Abfrage „%(name)s“ gibt es in dieser App nicht.") % {"name": args.get("slug")})
            return datasources.run_saved(query)["rows"]
        raise OpsError(_("Unbekannte Anfrage."))


SECRET_PREFIX = "SCRIPT_SECRET_"


def script_secret(name):
    """Wert der Umgebungsvariable SCRIPT_SECRET_<NAME> (nur Großbuchstaben, Ziffern, _)."""
    import re

    key = str(name or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9_]{1,64}", key):
        raise OpsError(_("Ungültiger Name für ein Geheimnis: nur Buchstaben, Ziffern und _."))
    value = os.environ.get(SECRET_PREFIX + key)
    if value is None:
        raise OpsError(_("Das Geheimnis „%(name)s“ ist nicht eingerichtet (Umgebungsvariable %(var)s im Hintergrunddienst).")
                       % {"name": key, "var": SECRET_PREFIX + key})
    return value


def user_info(user):
    if user is None or not user.is_authenticated:
        return None
    return {
        "username": user.get_username(), "name": user.get_full_name() or user.get_username(),
        "email": user.email, "groups": sorted(user.groups.values_list("name", flat=True)),
        "language": app_i18n.current_language(),  # z. B. "de" oder "en", für eigene Meldungen in Skripten
    }


def run(code, app, user=None, event=None, record=None, params=None, timeout=None, session=None):
    """Führt Python-Code aus und gibt ein Result zurück. Wirft keine Ausnahmen für Fehler im Skript."""
    timeout = timeout or settings.BAUKASTEN_SCRIPT_TIMEOUT
    started = time.monotonic()
    handler = Handler(app, user)
    context = {
        "code": code, "app": {"name": app.name, "slug": app.slug, "translations": app_i18n.mapping(app)},
        "user": user_info(user),
        "event": event or {}, "record": record, "params": params or {}, "session": session or {},
        "max_calls": settings.BAUKASTEN_SCRIPT_MAX_CALLS,
    }
    errors = tempfile.TemporaryFile()
    kwargs = {}
    if os.name == "posix":
        kwargs["preexec_fn"] = _limits(int(timeout) + 1)
    elif os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", str(CHILD), _restricted_python_dir()], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=errors, env=_environment(), cwd=tempfile.gettempdir(), **kwargs,
        )
    except OSError as exc:
        return Result(ok=False, error=_("Skript konnte nicht gestartet werden: %(error)s") % {"error": exc})

    lines = queue.Queue()

    def reader():
        for raw in iter(lambda: proc.stdout.readline(MAX_LINE), b""):
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    token = running.set(True)
    try:
        proc.stdin.write((json.dumps(context, default=str) + "\n").encode())
        proc.stdin.flush()
        deadline = started + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return Result(ok=False, error=_("Zeitlimit von %(seconds)s Sekunden überschritten.") % {"seconds": timeout})
            try:
                raw = lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if raw is None:
                errors.seek(0)
                detail = errors.read().decode("utf-8", "replace").strip().splitlines()
                hint = detail[-1][:300] if detail else _("ohne Meldung")
                return Result(ok=False, error=_("Das Skript wurde abgebrochen (%(detail)s).") % {"detail": hint})
            try:
                message = json.loads(raw)
            except ValueError:
                return Result(ok=False, error=_("Ungültige Antwort des Skripts."))
            if message.get("done"):
                return Result(
                    ok=bool(message.get("ok")), log=message.get("log") or [], ui=message.get("ui") or {},
                    messages=message.get("messages") or [], record=message.get("record"),
                    session=message.get("session") if isinstance(message.get("session"), dict) else None,
                    error=message.get("error") or "", line=message.get("line"),
                )
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
                continue
    finally:
        running.reset(token)
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        errors.close()
        # Dauer wird vom Aufrufer gesetzt, siehe triggers.execute
