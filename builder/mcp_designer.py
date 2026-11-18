"""MCP-Server für den Designer: /mcp/designer/

Eine KI nach Wahl (Claude Desktop, Claude Code, Cursor, n8n …) baut damit Apps: anlegen,
lesen, prüfen, ändern, Versionen zurückholen. Anmeldung mit einem persönlichen Schlüssel
(„Authorization: Bearer bkd_…“, erzeugt auf der Profilseite). Die KI hat genau die Rechte
der Person im Designer. Die eigentliche Arbeit steckt in ai_designer.py.
"""
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import ai_designer, versions
from .api import unauthorized
from .blocks import WIDTHS, all_types
from .mcp import ToolError, _object, dispatch, serve
from .models import App, AppVersion, DesignerToken, Field, Script, can_automate, can_design

INSTRUCTIONS = (
    "Designer des Baukastens: Apps aus Tabellen (entities) mit Feldern und Seiten (pages) aus Bausteinen. "
    "Vorgehen: 1. guide lesen (Format, Feldtypen, Bausteine mit Einstellungen, Beispiel). "
    "2. Für Änderungen get_app holen, anpassen und vollständig an update_app geben. "
    "3. validate_app prüft ohne zu speichern. Fehler nennen den Pfad, z. B. pages[0].layout[2].props.entity. "
    "Neue Apps sind Entwürfe; Veröffentlichen, öffentliche Seiten, API-Freigaben und das Einschalten von "
    "Skripten macht ein Mensch im Designer. Vor jeder Änderung wird eine Version gesichert (restore_version)."
)


def _text(value):
    return str(value) if value is not None else None


def guide():
    """Alles, was eine KI über das Format wissen muss, aus dem laufenden System erzeugt."""
    blocks = []
    for t in all_types().values():
        props = []
        for spec in t.fields:
            item = {"key": spec["key"], "type": spec["type"], "label": _text(spec.get("label"))}
            if "default" in spec:
                item["default"] = spec["default"] if isinstance(spec["default"], (bool, int)) else _text(spec["default"])
            if spec.get("options"):
                item["options"] = [str(option[0]) for option in spec["options"]]
            props.append(item)
        blocks.append({"type": t.key, "label": _text(t.label), "category": _text(t.category),
                       "hint": _text(t.hint), "props": props})
    return {
        "format": {
            "name": "Name der App (Pflicht)", "description": "kurze Beschreibung", "icon": "ein Emoji",
            "kind": "app (Standard) oder automation (nur Python-Skripte im Hintergrund, keine Seiten)",
            "entities": "Tabellen: [{name, slug?, allow_create?, allow_edit?, allow_delete?, fields: [...]}]",
            "fields": "Felder: [{label, key?, type, required?, choices? (Liste, nur choice), "
                      "reference? (slug der Zieltabelle, nur reference), show_in_list?, show_in_form?}]",
            "pages": "Seiten: [{title, slug?, show_in_nav?, layout: [Bausteine]}]",
            "block": "Baustein: {type, width? (3, 4, 6, 8 oder 12 von 12 Spalten), name? (für Skripte), "
                     "props: {Einstellungen}}",
            "scripts": "optional: [{name, language (python/javascript), trigger, code, page?, entity?, "
                       "interval_minutes?, daily_time? (HH:MM), weekdays_only?, timeout_minutes?}]",
            "slugs": "Kurznamen (slug, key) dürfen fehlen und entstehen aus dem Namen: klein, ohne Umlaute "
                     "(„Geräte“ wird „gerate“, „Ausleihe von“ wird „ausleihe_von“). Wer auf eine Tabelle "
                     "verweist, gibt den slug lieber selbst an.",
        },
        "field_types": [{"type": key, "label": str(label)} for key, label in Field.TYPES],
        "blocks": blocks,
        "widths": list(WIDTHS),
        "references_in_blocks": "Einstellungen vom Typ entity nennen den slug einer Tabelle, vom Typ field den "
                                "key eines Feldes dieser Tabelle, vom Typ page den slug einer Seite.",
        "script_triggers": {"app": list(Script.APP_TRIGGERS), "automation": list(Script.AUTOMATION_TRIGGERS)},
        "script_commands": ("Python: app.table('slug').filter(feld=wert) / .create(feld=wert) / .update(id, …) / "
                            ".count(); ui.set('name', value=…); message('…'); print(); in Automatisierungen echtes "
                            "Python mit requests und secret('NAME'). JavaScript: dieselben Befehle mit await."),
        "rules": [
            "Neue Apps sind Entwürfe. Veröffentlichen und Nutzergruppen stellt ein Mensch im Designer ein.",
            "Öffentliche Seiten und API-Freigaben kann die KI nicht setzen; bestehende bleiben erhalten.",
            "Neue oder geänderte Skripte sind ausgeschaltet, bis ein Mensch sie im Designer einschaltet.",
            "update_app ersetzt Tabellen, Seiten und (falls angegeben) Skripte durch die Definition. Fehlt "
            "entities, pages oder scripts, bleibt dieser Teil unverändert.",
            "Tabellen werden nie gelöscht, auch wenn sie in der Definition fehlen (ihre Daten bleiben).",
            "Vor jeder Änderung entsteht eine Version; restore_version holt sie zurück.",
            "Datenquellen und Übersetzungen pflegt nur der Designer.",
        ],
        "example": EXAMPLE,
    }


EXAMPLE = {
    "name": "Geräteverleih", "icon": "🔧", "description": "Wer hat welches Gerät ausgeliehen?",
    "entities": [
        {"name": "Geräte", "slug": "geraete", "fields": [
            {"label": "Bezeichnung", "type": "text", "required": True},
            {"label": "Kategorie", "type": "choice", "choices": ["Werkzeug", "Messgerät", "IT"]},
            {"label": "Verfügbar", "type": "bool"},
        ]},
        {"name": "Ausleihen", "slug": "ausleihen", "fields": [
            {"label": "Gerät", "key": "geraet", "type": "reference", "reference": "geraete", "required": True},
            {"label": "Person", "type": "text", "required": True},
            {"label": "Von", "type": "date"},
            {"label": "Bis", "type": "date"},
        ]},
    ],
    "pages": [
        {"title": "Übersicht", "slug": "uebersicht", "layout": [
            {"type": "heading", "props": {"text": "Geräteverleih", "level": "1"}},
            {"type": "stat", "width": 4, "props": {"label": "Geräte", "entity": "geraete"}},
            {"type": "stat", "width": 4, "props": {"label": "Ausleihen", "entity": "ausleihen"}},
            {"type": "chart", "width": 4, "props": {"label": "Nach Kategorie", "entity": "geraete", "field": "kategorie"}},
            {"type": "table", "props": {"entity": "geraete"}},
        ]},
        {"title": "Ausleihen", "slug": "ausleihen", "layout": [
            {"type": "form", "width": 6, "props": {"entity": "ausleihen", "submit_label": "Ausleihen"}},
            {"type": "table", "width": 6, "props": {"entity": "ausleihen"}},
        ]},
    ],
}


def _app(user, slug):
    app = App.editable_by(user).filter(slug=str(slug or "")).first()
    if app is None:
        raise ToolError(f"Die App „{slug}“ gibt es nicht oder du darfst sie nicht bearbeiten. Siehe list_apps.")
    return app


def _invalid(exc):
    return ToolError("Die Definition ist nicht gültig:\n- " + "\n- ".join(exc.errors)
                     + ("\nHinweise:\n- " + "\n- ".join(exc.warnings) if exc.warnings else ""))


def build_tools(token, request):
    user = token.user
    tools = {}

    def add(name, title, description, schema, run, read_only=True, destructive=False):
        tools[name] = ({
            "name": name, "title": title, "description": description, "inputSchema": schema,
            "annotations": {"title": title, "readOnlyHint": read_only, "destructiveHint": destructive,
                            "idempotentHint": read_only, "openWorldHint": False},
        }, run)

    def write(fn):
        def run(args, request):
            if not ai_designer.check_rate(token):
                raise ToolError("Zu viele Änderungen in kurzer Zeit. Bitte in ein paar Minuten erneut versuchen.")
            return fn(args, request)
        return run

    definition = {"type": "object", "additionalProperties": True,
                  "description": "App-Definition wie in guide beschrieben (name, entities, pages, optional scripts)"}
    app_arg = {"type": "string", "description": "Kurzname (slug) der App, siehe list_apps"}

    add("guide", "Anleitung und Format",
        "Format der App-Definition: Feldtypen, alle Bausteine mit ihren Einstellungen, Regeln und ein "
        "vollständiges Beispiel. Vor dem ersten Anlegen oder Ändern lesen.", _object({}), lambda a, r: guide())

    def run_list(args, request):
        return {"apps": [ai_designer.summary(a) for a in App.editable_by(user).order_by("name")],
                "may_create_automations": can_automate(user)}

    add("list_apps", "Apps auflisten", "Alle Apps und Automatisierungen, die du im Designer bearbeiten darfst.",
        _object({}), run_list)

    def run_get(args, request):
        app = _app(user, args.get("app"))
        return {**ai_designer.export(app), "designer_url": ai_designer.designer_url(request, app)}

    add("get_app", "App lesen",
        "Die vollständige Definition einer App (Tabellen, Felder, Seiten mit Bausteinen, Skripte). "
        "Für Änderungen holen, anpassen und an update_app geben.", _object({"app": app_arg}, ["app"]), run_get)

    def run_validate(args, request):
        slug = args.get("app")
        app = _app(user, slug) if slug else None
        data = args.get("definition")
        kind = app.kind if app else (App.AUTOMATION if isinstance(data, dict) and data.get("kind") == App.AUTOMATION
                                     else App.APP)
        try:
            ai_designer.normalize(data, app=app, kind=kind)
        except ai_designer.Invalid as exc:
            return {"valid": False, "errors": exc.errors, "warnings": exc.warnings}
        _snapshot, warnings = ai_designer.normalize(data, app=app, kind=kind)
        return {"valid": True, "errors": [], "warnings": warnings}

    add("validate_app", "Definition prüfen",
        "Prüft eine Definition, ohne etwas zu speichern. Mit app: als Änderung dieser App.",
        _object({"definition": definition, "app": app_arg}, ["definition"]), run_validate)

    def run_create(args, request):
        try:
            app, warnings = ai_designer.create(user, args.get("definition"), token.name)
        except ai_designer.Invalid as exc:
            raise _invalid(exc) from exc
        return {"created": True, "app": ai_designer.summary(app), "warnings": warnings,
                "designer_url": ai_designer.designer_url(request, app),
                "next": "Die App ist ein Entwurf. Ansehen, Skripte prüfen und veröffentlichen im Designer."}

    add("create_app", "App anlegen",
        "Legt eine neue App als Entwurf an. Ein Kurzname für die App entsteht aus dem Namen.",
        _object({"definition": definition}, ["definition"]), write(run_create), read_only=False)

    def run_update(args, request):
        app = _app(user, args.get("app"))
        try:
            before, kept, warnings = ai_designer.update(user, app, args.get("definition"), token.name)
        except ai_designer.Invalid as exc:
            raise _invalid(exc) from exc
        result = {"updated": True, "app": ai_designer.summary(app), "warnings": warnings,
                  "backup_version": before.number, "designer_url": ai_designer.designer_url(request, app),
                  "undo": f"restore_version mit app={app.slug} und number={before.number}"}
        if kept:
            result["kept_tables"] = kept
        return result

    add("update_app", "App ändern",
        "Bringt eine App auf den Stand der Definition. Vorher wird automatisch eine Version gesichert.",
        _object({"app": app_arg, "definition": definition}, ["app", "definition"]), write(run_update),
        read_only=False, destructive=True)

    def run_versions(args, request):
        app = _app(user, args.get("app"))
        return {"versions": [{"number": v.number, "note": v.note, "automatic": v.automatic,
                              "created_at": v.created_at.isoformat()} for v in app.versions.all()[:30]]}

    add("list_versions", "Versionen auflisten", "Gespeicherte Versionen einer App, neueste zuerst.",
        _object({"app": app_arg}, ["app"]), run_versions)

    def run_restore(args, request):
        app = _app(user, args.get("app"))
        version = AppVersion.objects.filter(app=app, number=args.get("number")).first()
        if version is None:
            raise ToolError("Diese Version gibt es nicht. Siehe list_versions.")
        kept = versions.restore(version, user)
        return {"restored": version.number, "app": ai_designer.summary(app), "kept_tables": kept}

    add("restore_version", "Version wiederherstellen",
        "Holt einen gespeicherten Stand zurück. Der jetzige Stand wird vorher selbst als Version gesichert.",
        _object({"app": app_arg, "number": {"type": "integer", "description": "Nummer der Version"}},
                ["app", "number"]), write(run_restore), read_only=False, destructive=True)
    return tools


def login(request):
    header = request.headers.get("Authorization", "")
    token = DesignerToken.find(header[7:].strip() if header.lower().startswith("bearer ") else "")
    if token is None:
        return unauthorized()
    if not token.user.is_active or not can_design(token.user):
        return JsonResponse({"error": "Dieses Konto hat kein Designer-Recht (mehr)."}, status=403)
    now = timezone.now()
    if not token.last_used or (now - token.last_used).total_seconds() > 60:
        DesignerToken.objects.filter(pk=token.pk).update(last_used=now)
    return token


def answer(request, token, message):
    from . import audit

    info = {"name": "baukasten-designer", "title": "Baukasten: Designer", "instructions": INSTRUCTIONS}
    with audit.context(user=token.user, actor=f"KI-Zugang {token.name}", via="ki"):
        return dispatch(request, message, info, lambda: build_tools(token, request))


@csrf_exempt
def endpoint(request):
    return serve(request, login, answer)
