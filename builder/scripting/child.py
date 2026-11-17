"""Führt ein Python-Skript des Baukastens in einem eigenen Prozess aus.

Diese Datei wird nicht importiert, sondern als eigener Prozess gestartet
(siehe python.py). Sie importiert bewusst nichts aus Django: Der Prozess hat
weder Zugangsdaten noch eine Datenbankverbindung. Alles, was das Skript
braucht (Tabellen, Abfragen, Web-Requests), erfragt er beim Elternprozess über
JSON-Zeilen auf stdin/stdout. Der Elternprozess prüft und begrenzt jede Anfrage.

Das Skript selbst wird mit RestrictedPython übersetzt: kein Dateizugriff, kein
import außer einer Liste harmloser Module, kein Zugriff auf Namen mit
Unterstrich.

Ausnahme: Automatisierungen (Modus „full“, nur im Hintergrunddienst). Dort läuft
echtes Python mit allen installierten Bibliotheken. Ausgaben (print, Fehler)
gehen laufend als Protokollzeilen an den Elternprozess.
"""
import json
import operator
import os
import re
import secrets
import signal
import sys
import threading
import traceback
import types
import warnings

# Der Prozess startet isoliert (python -I) und sieht dann z. B. keine mit „pip install --user“
# installierten Pakete. Der Elternprozess übergibt deshalb den Ordner, in dem RestrictedPython liegt.
# Automatisierungen bekommen zusätzlich die Paketordner des Dienstes (gemeinsame Umgebung).
for _extra in sys.argv[1:]:
    if _extra not in sys.path:
        sys.path.append(_extra)

from RestrictedPython import compile_restricted, limited_builtins, safe_builtins, utility_builtins
from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
from RestrictedPython.Guards import (full_write_guard, guarded_iter_unpack_sequence,
                                     guarded_unpack_sequence, safer_getattr)

FILENAME = "<skript>"
ALLOWED_MODULES = ("math", "statistics", "datetime", "json", "re", "random", "string",
                   "decimal", "collections", "itertools", "functools", "time")
MAX_LOG_LINES = 500

_in = sys.stdin
_out = sys.stdout
_state = {"calls": 0, "max_calls": 1000, "log": [], "ui": {}, "messages": [], "session": {}}
_lock = threading.RLock()  # Skripte im Modus „full“ dürfen Threads nutzen


class ScriptError(Exception):
    """Fehler, den der Baukasten an das Skript meldet (z. B. ungültige Daten)."""


class Stopped(BaseException):
    """Lauf wurde gestoppt (Knopf „Stoppen“ oder Neustart des Dienstes). Kein Exception,
    damit „except Exception“ im Skript das Stoppen nicht verschluckt."""


def _call(op, **args):
    with _lock:
        _state["calls"] += 1
        if _state["max_calls"] and _state["calls"] > _state["max_calls"]:
            raise ScriptError(f"Zu viele Zugriffe (höchstens {_state['max_calls']} pro Lauf).")
        _out.write(json.dumps({"call": op, "args": args}, default=str) + "\n")
        _out.flush()
        line = _in.readline()
    if not line:
        raise SystemExit(1)
    answer = json.loads(line)
    if "error" in answer:
        raise ScriptError(answer["error"])
    return answer.get("result")


def _data(data, fields):
    merged = dict(data or {})
    merged.update(fields)
    return merged


class Table:
    """Eine Tabelle der App. Erhältlich über app.table("kurzname")."""

    def __init__(self, slug):
        self.slug = slug

    def __repr__(self):
        return f"<Tabelle {self.slug}>"

    def all(self, limit=1000):
        return _call("table.filter", table=self.slug, where={}, limit=limit)

    def filter(self, limit=1000, **where):
        return _call("table.filter", table=self.slug, where=where, limit=limit)

    def first(self, **where):
        rows = _call("table.filter", table=self.slug, where=where, limit=1)
        return rows[0] if rows else None

    def get(self, id):
        return _call("table.get", table=self.slug, id=id)

    def count(self, **where):
        return _call("table.count", table=self.slug, where=where)

    def sum(self, field, **where):
        return _call("table.aggregate", table=self.slug, func="sum", field=field, where=where)

    def avg(self, field, **where):
        return _call("table.aggregate", table=self.slug, func="avg", field=field, where=where)

    def create(self, data=None, **fields):
        return _call("table.create", table=self.slug, data=_data(data, fields))

    def update(self, id, data=None, **fields):
        return _call("table.update", table=self.slug, id=id, data=_data(data, fields))

    def delete(self, id):
        return _call("table.delete", table=self.slug, id=id)


class App:
    def __init__(self, name, slug, translations=None):
        self.name = name
        self.slug = slug
        self._translations = translations or {}

    def table(self, slug):
        return Table(slug)

    def t(self, text):
        """Text in der Sprache der Person, aus den Übersetzungen der App (sonst unverändert)."""
        return self._translations.get(text) or text


class UI:
    """Füllt Bausteine der Seite. Der Baustein braucht im Seiten-Designer einen Namen."""

    def set(self, name, **values):
        _state["ui"].setdefault(str(name), {}).update(values)

    def hide(self, name):
        self.set(name, hidden=True)


class Http:
    """Web-Requests an freigegebene Adressen (Einstellung HTTP_ALLOWED_HOSTS)."""

    def get_json(self, url, **params):
        return _call("http.get_json", url=url, params=params)

    def post_json(self, url, data=None):
        return _call("http.post_json", url=url, data=data)


class Db:
    """Lesende Abfragen an externe Datenbanken (z. B. Databricks)."""

    def query(self, source, sql, params=None, limit=1000):
        return _call("db.query", source=source, sql=sql, params=params or {}, limit=limit)

    def saved(self, slug):
        """Ergebnis einer im Designer angelegten Abfrage."""
        return _call("db.saved", slug=slug)


def message(text):
    """Zeigt nach einem Button-Klick eine Meldung an."""
    _state["messages"].append(str(text))


def token(length=16):
    """Zufälliger, nicht erratbarer Code für geheime Links (Buchstaben, Ziffern, - und _)."""
    return secrets.token_urlsafe(max(8, min(int(length), 64)))


def secret(name):
    """Geheimnis für Automatisierungen (Umgebungsvariable SCRIPT_SECRET_<NAME> des Hintergrunddienstes)."""
    return _call("secret", name=str(name))


class _Printer:
    def __init__(self, _getattr_=None):
        pass

    def _call_print(self, *objects, **kwargs):
        if len(_state["log"]) < MAX_LOG_LINES:
            _state["log"].append(kwargs.get("sep", " ").join(str(o) for o in objects))


def _safe_module(module):
    """Nur öffentliche Funktionen, Klassen und Werte eines Moduls, keine Untermodule."""
    attrs = {name: value for name, value in vars(module).items()
             if not name.startswith("_") and not isinstance(value, types.ModuleType)}
    return types.SimpleNamespace(**attrs)


_SAFE_MODULES = {}


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0 or name not in ALLOWED_MODULES:
        raise ImportError(f"Das Modul „{name}“ ist in Skripten nicht verfügbar. Erlaubt: {', '.join(ALLOWED_MODULES)}.")
    if name not in _SAFE_MODULES:
        _SAFE_MODULES[name] = _safe_module(__import__(name))
    return _SAFE_MODULES[name]


_INPLACE = {"+=": operator.iadd, "-=": operator.isub, "*=": operator.imul, "/=": operator.itruediv,
            "//=": operator.ifloordiv, "%=": operator.imod, "**=": operator.ipow,
            "|=": operator.ior, "&=": operator.iand, "^=": operator.ixor}


def _inplacevar(op, x, y):
    if op not in _INPLACE:
        raise SyntaxError(f"Operator {op} ist nicht erlaubt.")
    return _INPLACE[op](x, y)


def _apply(func, *args, **kwargs):
    return func(*args, **kwargs)


def _globals(context):
    builtins = dict(safe_builtins)
    builtins.update(limited_builtins)
    builtins.update(utility_builtins)
    for name in ("sorted", "min", "max", "sum", "any", "all", "enumerate", "zip", "map", "filter",
                 "list", "dict", "tuple", "reversed", "round", "abs", "isinstance", "len", "range"):
        builtins[name] = __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    builtins["__import__"] = _import
    app = context.get("app") or {}
    return {
        "__builtins__": builtins,
        "__name__": "skript",
        "__metaclass__": type,
        "_getattr_": safer_getattr,
        "_getitem_": default_guarded_getitem,
        "_getiter_": default_guarded_getiter,
        "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
        "_unpack_sequence_": guarded_unpack_sequence,
        "_write_": full_write_guard,
        "_inplacevar_": _inplacevar,
        "_apply_": _apply,
        "_print_": _Printer,
        "app": App(app.get("name", ""), app.get("slug", ""), app.get("translations")),
        "ui": UI(),
        "http": Http(),
        "db": Db(),
        "message": message,
        "token": token,
        "user": context.get("user"),
        "event": context.get("event") or {},
        "record": context.get("record"),
        "params": context.get("params") or {},
        # Merkzettel je Besucher (Browser) und App, bleibt über Seitenaufrufe erhalten.
        "session": _state["session"],
        "ScriptError": ScriptError,
    }


def _line_of(exc):
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if frame.filename == FILENAME:
            return frame.lineno
    return getattr(exc, "lineno", None)


def _finish(**payload):
    payload.update(done=True, log=_state["log"], ui=_state["ui"], messages=_state["messages"],
                   session=_state["session"])
    with _lock:
        _out.write(json.dumps(payload, default=str) + "\n")
        _out.flush()


class _LogStream:
    """Ersetzt sys.stdout/sys.stderr im Modus „full“: jede Zeile geht sofort als Protokoll an den Elternprozess."""

    encoding = "utf-8"

    def __init__(self):
        self._buffer = ""

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        with _lock:
            self._buffer += text
            *lines, self._buffer = self._buffer.split("\n")
            for line in lines:
                _send({"log": line[:5000]})
        return len(text)

    def flush(self):
        with _lock:
            if self._buffer:
                _send({"log": self._buffer[:5000]})
                self._buffer = ""

    def isatty(self):
        return False

    def writable(self):
        return True


def _send(payload):
    with _lock:
        _out.write(json.dumps(payload, default=str) + "\n")
        _out.flush()


def _full_globals(context):
    app = context.get("app") or {}
    return {
        "__name__": "__main__",
        "__builtins__": __builtins__,
        "app": App(app.get("name", ""), app.get("slug", ""), app.get("translations")),
        "http": Http(),
        "db": Db(),
        "message": message,
        "token": token,
        "secret": secret,
        "event": context.get("event") or {},
        "params": context.get("params") or {},
        "ScriptError": ScriptError,
        "Stopped": Stopped,
    }


def _stop(signum, frame):
    raise Stopped()


def main_full(context):
    """Echtes Python. Der Kanal zum Elternprozess bekommt eigene Dateideskriptoren; was das Skript
    (oder eine Bibliothek) auf stdout/stderr schreibt, landet im Protokoll, stdin ist leer."""
    global _in, _out
    _in = os.fdopen(os.dup(0), "r", encoding="utf-8")
    _out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.dup2(2, 1)  # Ausgaben auf Ebene des Betriebssystems (z. B. Unterprozesse) gehen nach stderr
    sys.stdin = open(os.devnull, encoding="utf-8")
    sys.stdout = sys.stderr = _LogStream()
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (ValueError, OSError, AttributeError):
        pass
    _state["max_calls"] = int(context.get("max_calls") or 0)
    glob = _full_globals(context)
    try:
        code = compile(context["code"], FILENAME, "exec")
    except SyntaxError as exc:
        _finish(ok=False, error=f"SyntaxError: {exc.msg}", line=exc.lineno)
        return
    try:
        exec(code, glob)
    except Stopped:
        sys.stdout.flush()
        _finish(ok=False, stopped=True, error="Gestoppt.")
        return
    except SystemExit as exc:
        sys.stdout.flush()
        if exc.code in (None, 0):
            _finish(ok=True)
        else:
            _finish(ok=False, error=f"SystemExit: {exc.code}")
        return
    except BaseException as exc:  # noqa: BLE001 - jeder Fehler des Skripts wird gemeldet
        sys.stdout.flush()
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-6:])
        _send({"log": detail.rstrip()[:5000]})
        _finish(ok=False, error=f"{type(exc).__name__}: {exc}", line=_line_of(exc))
        return
    sys.stdout.flush()
    _finish(ok=True)


def main():
    context = json.loads(_in.readline())
    if context.get("mode") == "full":
        main_full(context)
        return
    _state["max_calls"] = int(context.get("max_calls", 1000))
    if isinstance(context.get("session"), dict):
        _state["session"].update(context["session"])
    warnings.simplefilter("ignore")
    try:
        code = compile_restricted(context["code"], filename=FILENAME, mode="exec")
    except SyntaxError as exc:
        # RestrictedPython meldet mehrere Fehler als Tupel „Line N: Text“.
        messages = exc.args[0] if exc.args and isinstance(exc.args[0], tuple) else (exc.msg or str(exc),)
        match = re.match(r"Line (\d+): (.*)", str(messages[0]), re.S)
        if match:
            _finish(ok=False, error=match.group(2), line=int(match.group(1)))
        else:
            _finish(ok=False, error=str(messages[0]), line=exc.lineno)
        return
    glob = _globals(context)
    try:
        exec(code, glob)
    except ScriptError as exc:
        _finish(ok=False, error=str(exc), line=_line_of(exc), record=glob.get("record"))
        return
    except Exception as exc:  # noqa: BLE001 - jeder Fehler des Skripts wird gemeldet
        _finish(ok=False, error=f"{type(exc).__name__}: {exc}", line=_line_of(exc), record=glob.get("record"))
        return
    _finish(ok=True, record=glob.get("record"))


if __name__ == "__main__":
    main()
