"""MCP-Server (Model Context Protocol) je App: /mcp/<app>/

Damit können KI-Agenten und Automatisierungen wie n8n („MCP Client Tool“), Claude
oder Cursor die Tabellen einer App lesen und – mit passendem Schlüssel – ändern.

- Transport: „Streamable HTTP“ ohne Streaming. Jede Anfrage ist ein POST mit einer
  JSON-RPC-Nachricht, die Antwort kommt als JSON. Kein Sitzungszustand.
- Anmeldung: derselbe Schlüssel wie für die API („Authorization: Bearer bk_…“).
- Tools entstehen automatisch aus den Tabellen, die im Designer für die API
  freigeschaltet sind, und aus eigenen Endpunkten (hooks.api). Ändert jemand ein
  Feld, sind die Tools beim nächsten Abruf aktuell.
- Ein Schlüssel ohne Schreibrecht bekommt nur die lesenden Tools. Anlegen,
  Ändern und Löschen gibt es nur, wo die Tabelle es erlaubt.
"""
import json
import logging
import re

from django.http import HttpResponse, JsonResponse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt

from . import hooks
from .api import authenticate, find_records, start_automation, unauthorized
from .models import Field, Record, Script, ScriptRun
from .openapi import TYPE_SCHEMAS
from .scripting.ops import OpsError, save_record, serialize

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_VERSION = "1.0"

# JSON-RPC-Fehlercodes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


class ToolError(Exception):
    """Fehler bei der Ausführung eines Tools: geht als isError an das Modell zurück."""


def _tool_name(*parts):
    return re.sub(r"[^A-Za-z0-9_-]", "_", "_".join(parts))[:64]


def _field_schema(field, for_filter=False):
    schema = dict(TYPE_SCHEMAS.get(field.type, {"type": "string"}))
    schema.pop("example", None)
    description = field.label
    if field.type == Field.CHOICE:
        schema["enum"] = field.choice_list()
    if field.type == Field.REFERENCE and field.reference:
        description += f" (Nummer eines Eintrags aus „{field.reference.name}“)"
    if field.type == Field.DATE:
        description += " (Format JJJJ-MM-TT)"
    if field.type == Field.HTML and not for_filter:
        description += (" (HTML oder Markdown; Bilder als <img src=\"data:image/png;base64,…\"> werden gespeichert,"
                        " Skripte entfernt)")
    if for_filter:
        description = f"Nur Einträge, bei denen „{field.label}“ genau diesen Wert hat"
    elif field.required:
        description += " – Pflichtfeld"
    schema["description"] = description
    return schema


def _object(properties, required=()):
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return schema


ID = {"type": "integer", "description": "Nummer (id) des Eintrags"}


def build_tools(app, key):
    """Alle Tools für diese App und diesen Schlüssel: {name: (Beschreibung für tools/list, Ausführung)}."""
    tools = {}

    def add(name, title, description, schema, run, read_only=True, destructive=False):
        tools[name] = ({
            "name": name, "title": title, "description": description, "inputSchema": schema,
            "annotations": {"title": title, "readOnlyHint": read_only, "destructiveHint": destructive,
                            "idempotentHint": read_only, "openWorldHint": False},
        }, run)

    for entity in app.entities.filter(api_enabled=True).prefetch_related("fields", "fields__reference"):
        fields = list(entity.fields.all())
        names = ", ".join(f"{f.key} ({f.label})" for f in fields)

        def run_list(args, request, entity=entity, fields=fields):
            return find_records(entity, fields, args)

        def run_get(args, request, entity=entity, fields=fields):
            record = Record.objects.filter(pk=args.get("id"), entity=entity).first()
            if record is None:
                raise ToolError("Diesen Eintrag gibt es nicht.")
            return serialize(record, fields)

        add(_tool_name("list", entity.slug), f"{entity.name} suchen",
            f"Sucht Einträge in der Tabelle „{entity.name}“ der App „{app.name}“. Felder: {names}. "
            "Ohne Parameter kommen die ersten 50 Einträge. Antwort: count, page, pages, results.",
            _object({
                "q": {"type": "string", "description": "Volltextsuche in allen Feldern"},
                "page": {"type": "integer", "minimum": 1, "description": "Seite der Ergebnisliste (ab 1)"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Einträge pro Seite, höchstens 200"},
                **{f.key: _field_schema(f, for_filter=True) for f in fields},
            }), run_list)
        add(_tool_name("get", entity.slug), f"{entity.name} lesen",
            f"Liest einen Eintrag aus „{entity.name}“ anhand seiner Nummer (id).",
            _object({"id": ID}, ["id"]), run_get)

        if not key.can_write:
            continue
        if entity.allow_create:
            def run_create(args, request, entity=entity, fields=fields):
                return serialize(save_record(entity, args), fields)

            add(_tool_name("create", entity.slug), f"{entity.name} anlegen",
                f"Legt einen Eintrag in „{entity.name}“ an. Es gelten dieselben Prüfungen wie im Formular.",
                _object({f.key: _field_schema(f) for f in fields}, [f.key for f in fields if f.required]),
                run_create, read_only=False)
        if entity.allow_edit:
            def run_update(args, request, entity=entity, fields=fields):
                args = dict(args)
                record = Record.objects.filter(pk=args.pop("id", None), entity=entity).first()
                if record is None:
                    raise ToolError("Diesen Eintrag gibt es nicht.")
                return serialize(save_record(entity, args, record=record, partial=True), fields)

            add(_tool_name("update", entity.slug), f"{entity.name} ändern",
                f"Ändert einzelne Felder eines Eintrags in „{entity.name}“. Nicht genannte Felder bleiben, wie sie sind.",
                _object({"id": ID, **{f.key: _field_schema(f) for f in fields}}, ["id"]),
                run_update, read_only=False)
        if entity.allow_delete:
            def run_delete(args, request, entity=entity):
                deleted, _detail = Record.objects.filter(pk=args.get("id"), entity=entity).delete()
                if not deleted:
                    raise ToolError("Diesen Eintrag gibt es nicht.")
                return {"deleted": True, "id": args.get("id")}

            add(_tool_name("delete", entity.slug), f"{entity.name} löschen",
                f"Löscht einen Eintrag aus „{entity.name}“ endgültig.",
                _object({"id": ID}, ["id"]), run_delete, read_only=False, destructive=True)

    if app.is_automation:
        _automation_tools(app, key, add)

    for name, endpoint in hooks.API_ENDPOINTS.items():
        if endpoint["write"] and not key.can_write:
            continue

        def run_custom(args, request, endpoint=endpoint):
            return endpoint["fn"](request, app, args)

        doc = (endpoint["fn"].__doc__ or "").strip().splitlines()
        add(_tool_name("x", name), name,
            (doc[0] if doc else f"Eigener Endpunkt „{name}“.") + " Parameter frei als Objekt.",
            {"type": "object", "additionalProperties": True}, run_custom,
            read_only=not endpoint["write"])
    return tools


def _automation_tools(app, key, add):
    """Automatisierungen: Zustand lesen und (mit Schreibrecht) Skripte starten."""
    scripts = list(app.scripts.all())

    def run_status(args, request):
        from .scripting.schedule import describe
        from .scripting.worker import status

        rows = []
        for sc in scripts:
            sc.refresh_from_db()
            last = sc.runs.exclude(status=ScriptRun.SKIPPED).first()
            rows.append({
                "script": sc.slug, "name": sc.name, "plan": describe(sc), "state": status(sc),
                "next_run_at": sc.next_run_at.isoformat() if sc.next_run_at and sc.enabled else None,
                "last_run": {"status": last.state, "started_at": last.started_at.isoformat(),
                             "duration_ms": last.duration_ms, "error": last.error[:500]} if last else None,
            })
        return {"scripts": rows}

    add("automation_status", "Zustand der Skripte",
        f"Zeigt für jedes Skript der Automatisierung „{app.name}“, ob es läuft, wann es als Nächstes läuft "
        "und wie der letzte Lauf ausging.", _object({}), run_status)
    if not key.can_write:
        return
    for sc in scripts:
        if sc.trigger == Script.CONTINUOUS:
            continue

        def run_start(args, request, slug=sc.slug):
            data = args.get("daten")
            status_code, body = start_automation(app, slug, "mcp", data if isinstance(data, dict) else {}, key.name)
            if status_code != 202:
                raise ToolError(body["error"])
            return body

        add(_tool_name("start", sc.slug), f"{sc.name} starten",
            f"Startet das Skript „{sc.name}“ der Automatisierung „{app.name}“ im Hintergrund. Die Antwort kommt "
            "sofort; das Ergebnis zeigt automation_status. Optionale Daten stehen im Skript in event[\"daten\"].",
            _object({"daten": {"type": "object", "additionalProperties": True,
                               "description": "Beliebige Daten für das Skript (JSON-Objekt)"}}),
            run_start, read_only=False)


def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(request, key, message):
    """Eine JSON-RPC-Nachricht an den Server einer App."""
    app = key.app
    info = {"name": f"baukasten-{app.slug}", "title": f"Baukasten: {app.name}",
            "instructions": (f"Zugriff auf die App „{app.name}“ im Baukasten. "
                             + ("Dieser Schlüssel darf lesen und schreiben." if key.can_write else "Dieser Schlüssel darf nur lesen.")
                             + " Verweise und Einträge werden über ihre Nummer (id) angesprochen.")}
    from . import audit

    with audit.context(actor=f"API-Schlüssel {key.name}"):
        return dispatch(request, message, info, lambda: build_tools(app, key))


def dispatch(request, message, info, build):
    """Eine JSON-RPC-Nachricht. Gibt die Antwort zurück, bei Benachrichtigungen None.

    info: name, title, instructions des Servers; build(): {Tool-Name: (Beschreibung, Ausführung)}."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "Ungültige Anfrage.")
    method, msg_id, params = message["method"], message.get("id"), message.get("params") or {}
    if "id" not in message:  # Benachrichtigung, z. B. notifications/initialized
        return None
    if method == "initialize":
        wanted = params.get("protocolVersion")
        return _result(msg_id, {
            "protocolVersion": wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": info["name"], "title": info["title"], "version": SERVER_VERSION},
            "instructions": info["instructions"],
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": [spec for spec, _run in build().values()]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        tool = build().get(name)
        if tool is None:
            return _error(msg_id, INVALID_PARAMS, f"Das Tool „{name}“ gibt es nicht.")
        if not isinstance(args, dict):
            return _error(msg_id, INVALID_PARAMS, "„arguments“ muss ein Objekt sein.")
        run = tool[1]
        try:
            data = run(args, request)
        except ToolError as exc:
            return _result(msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except OpsError as exc:
            text = str(exc) + (" " + json.dumps(exc.fields, ensure_ascii=False) if exc.fields else "")
            return _result(msg_id, {"content": [{"type": "text", "text": text}], "isError": True})
        except Exception:
            log.exception("Fehler im MCP-Tool %s", name)
            return _result(msg_id, {"content": [{"type": "text", "text": "Das Tool ist auf einen Fehler gelaufen."}],
                                    "isError": True})
        result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}],
                  "isError": False}
        if isinstance(data, dict):
            result["structuredContent"] = data
        return _result(msg_id, result)
    return _error(msg_id, METHOD_NOT_FOUND, f"Unbekannte Methode „{method}“.")


def serve(request, login, answer_one):
    """HTTP-Teil: Ursprung, Methode, Anmeldung, JSON. login(request) gibt den Zugang oder eine
    Antwort (z. B. 401) zurück; answer_one(request, zugang, nachricht) beantwortet eine Nachricht."""
    # Schutz gegen DNS-Rebinding: Aufrufe aus dem Browser nur von derselben Adresse.
    origin = request.headers.get("Origin")
    if origin and not url_has_allowed_host_and_scheme(origin, allowed_hosts={request.get_host()}):
        return JsonResponse(_error(None, INVALID_REQUEST, "Ursprung nicht erlaubt."), status=403)
    if request.method != "POST":
        response = HttpResponse(status=405)  # kein Server-Sent-Events-Strom, nur POST
        response["Allow"] = "POST"
        return response
    access = login(request)
    if isinstance(access, HttpResponse):
        return access
    try:
        body = json.loads(request.body)
    except ValueError:
        return JsonResponse(_error(None, PARSE_ERROR, "Der Inhalt ist kein gültiges JSON."), status=400)
    if isinstance(body, list):  # Stapel älterer Protokollversionen
        answers = [a for a in (answer_one(request, access, m) for m in body) if a is not None]
        return JsonResponse(answers, safe=False) if answers else HttpResponse(status=202)
    answer = answer_one(request, access, body)
    if answer is None:
        return HttpResponse(status=202)
    return JsonResponse(answer, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
def endpoint(request, app):
    return serve(request, lambda req: authenticate(req, app) or unauthorized(), handle)
