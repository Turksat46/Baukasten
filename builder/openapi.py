"""OpenAPI-Beschreibung (Swagger) der API einer App.

Die Beschreibung entsteht bei jedem Aufruf aus den freigeschalteten Tabellen und
ihren Feldern. Ändert jemand im Designer ein Feld, ist die Doku sofort aktuell.
"""
from django.urls import reverse
from django.utils.translation import gettext as _

from . import hooks
from .models import Field

TYPE_SCHEMAS = {
    Field.TEXT: {"type": "string", "maxLength": 500},
    Field.LONGTEXT: {"type": "string"},
    Field.NUMBER: {"type": "integer"},
    Field.DECIMAL: {"type": "number"},
    Field.DATE: {"type": "string", "format": "date", "example": "2026-11-16"},
    Field.BOOL: {"type": "boolean"},
    Field.CHOICE: {"type": "string"},
    Field.EMAIL: {"type": "string", "format": "email"},
    Field.URL: {"type": "string", "format": "uri"},
    Field.REFERENCE: {"type": "integer"},
}


def _schema_name(entity):
    return "".join(part.capitalize() for part in entity.slug.replace("_", "-").split("-")) or "Tabelle"


def _field_schema(field):
    schema = dict(TYPE_SCHEMAS.get(field.type, {"type": "string"}))
    description = field.label
    if field.type == Field.CHOICE:
        schema["enum"] = field.choice_list()
    if field.type == Field.REFERENCE and field.reference:
        description += " – " + _("Nummer (id) eines Eintrags aus „%(table)s“") % {"table": field.reference.name}
    schema["description"] = description
    schema["nullable"] = True
    return schema


def _params(entity, fields):
    params = [
        {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1},
         "description": _("Seite der Ergebnisliste")},
        {"name": "page_size", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
         "description": _("Einträge pro Seite, höchstens 200")},
        {"name": "q", "in": "query", "schema": {"type": "string"}, "description": _("Volltextsuche in allen Feldern")},
    ]
    for f in fields:
        schema = {k: v for k, v in _field_schema(f).items() if k not in ("nullable", "description")}
        params.append({"name": f.key, "in": "query", "schema": schema,
                       "description": _("Filter: nur Einträge, bei denen „%(label)s“ genau diesen Wert hat") % {"label": f.label}})
    return params


def _json(ref):
    return {"application/json": {"schema": {"$ref": ref}}}


def _error_responses(*codes):
    texts = {
        "400": _("Ungültige Daten. „fields“ nennt die Fehler je Feld."),
        "401": _("Schlüssel fehlt, ist falsch oder gehört zu einer anderen App."),
        "403": _("Schlüssel darf nur lesen, oder die Tabelle erlaubt diese Aktion nicht."),
        "404": _("Tabelle nicht freigeschaltet oder Eintrag nicht vorhanden."),
    }
    out = {}
    for code in codes:
        ref = "#/components/schemas/ValidationError" if code == "400" else "#/components/schemas/Error"
        out[code] = {"description": texts[code], "content": _json(ref)}
    return out


def build(request, app):
    base = reverse("api_describe", args=[app.slug])  # /api/v1/<app>/
    entities = list(app.entities.filter(api_enabled=True).prefetch_related("fields", "fields__reference"))
    paths, schemas, tags = {}, {}, []

    schemas["Error"] = {"type": "object", "properties": {"error": {"type": "string"}}, "required": ["error"]}
    schemas["ValidationError"] = {
        "type": "object",
        "properties": {
            "error": {"type": "string"},
            "fields": {"type": "object", "additionalProperties": {"type": "array", "items": {
                "type": "object", "properties": {"message": {"type": "string"}, "code": {"type": "string"}}}}},
        },
    }

    paths[base] = {"get": {
        "tags": [_("Überblick")], "operationId": "beschreibung",
        "summary": _("Tabellen, Felder und eigene Endpunkte dieser App"),
        "responses": {"200": {"description": _("Beschreibung der App"), "content": {"application/json": {"schema": {"type": "object"}}}},
                      **_error_responses("401")},
    }}
    tags.append({"name": _("Überblick")})

    for entity in entities:
        fields = list(entity.fields.all())
        name = _schema_name(entity)
        properties = {f.key: _field_schema(f) for f in fields}
        schemas[f"{name}Eingabe"] = {
            "type": "object", "properties": properties,
            "required": [f.key for f in fields if f.required and f.type != Field.BOOL],
            "description": _("Felder zum Anlegen oder Ändern eines Eintrags in „%(table)s“") % {"table": entity.name},
        }
        schemas[name] = {"allOf": [
            {"type": "object", "properties": {
                "id": {"type": "integer", "description": _("Nummer des Eintrags")},
                "created_at": {"type": "string", "format": "date-time"},
                "updated_at": {"type": "string", "format": "date-time"},
            }},
            {"type": "object", "properties": properties},
        ], "description": _("Ein Eintrag in „%(table)s“") % {"table": entity.name}}
        schemas[f"{name}Liste"] = {"type": "object", "properties": {
            "count": {"type": "integer", "description": _("Anzahl aller Treffer")},
            "page": {"type": "integer"}, "pages": {"type": "integer"}, "page_size": {"type": "integer"},
            "results": {"type": "array", "items": {"$ref": f"#/components/schemas/{name}"}},
        }}
        tag = entity.name
        flags = []
        if not entity.allow_create:
            flags.append(_("Anlegen ist abgeschaltet."))
        if not entity.allow_edit:
            flags.append(_("Bearbeiten ist abgeschaltet."))
        if not entity.allow_delete:
            flags.append(_("Löschen ist abgeschaltet."))
        tags.append({"name": tag, "description": " ".join([_("Kurzname: %(slug)s.") % {"slug": entity.slug}] + flags)})

        collection = {"get": {
            "tags": [tag], "operationId": f"{entity.slug}_liste", "summary": _("Einträge auflisten"),
            "parameters": _params(entity, fields),
            "responses": {"200": {"description": _("Eine Seite der Einträge"), "content": _json(f"#/components/schemas/{name}Liste")},
                          **_error_responses("401", "404")},
        }}
        if entity.allow_create:
            collection["post"] = {
                "tags": [tag], "operationId": f"{entity.slug}_anlegen", "summary": _("Eintrag anlegen"),
                "description": _("Braucht einen Schlüssel mit Schreibrecht. Es gelten dieselben Prüfungen wie im Formular."),
                "requestBody": {"required": True, "content": _json(f"#/components/schemas/{name}Eingabe")},
                "responses": {"201": {"description": _("Angelegt"), "content": _json(f"#/components/schemas/{name}")},
                              **_error_responses("400", "401", "403", "404")},
            }
        paths[f"{base}{entity.slug}/"] = collection

        id_param = [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"},
                     "description": _("Nummer des Eintrags")}]
        item = {"parameters": id_param, "get": {
            "tags": [tag], "operationId": f"{entity.slug}_lesen", "summary": _("Eintrag lesen"),
            "responses": {"200": {"description": _("Der Eintrag"), "content": _json(f"#/components/schemas/{name}")},
                          **_error_responses("401", "404")},
        }}
        if entity.allow_edit:
            item["put"] = {
                "tags": [tag], "operationId": f"{entity.slug}_ersetzen", "summary": _("Eintrag vollständig ersetzen"),
                "description": _("Nicht übergebene Felder werden geleert."),
                "requestBody": {"required": True, "content": _json(f"#/components/schemas/{name}Eingabe")},
                "responses": {"200": {"description": _("Gespeichert"), "content": _json(f"#/components/schemas/{name}")},
                              **_error_responses("400", "401", "403", "404")},
            }
            item["patch"] = {
                "tags": [tag], "operationId": f"{entity.slug}_aendern", "summary": _("Einzelne Felder ändern"),
                "description": _("Nur die übergebenen Felder ändern sich."),
                "requestBody": {"required": True, "content": {"application/json": {"schema": {
                    "type": "object", "properties": properties}}}},
                "responses": {"200": {"description": _("Gespeichert"), "content": _json(f"#/components/schemas/{name}")},
                              **_error_responses("400", "401", "403", "404")},
            }
        if entity.allow_delete:
            item["delete"] = {
                "tags": [tag], "operationId": f"{entity.slug}_loeschen", "summary": _("Eintrag löschen"),
                "responses": {"204": {"description": _("Gelöscht")}, **_error_responses("401", "403", "404")},
            }
        paths[f"{base}{entity.slug}/{{id}}/"] = item

    if hooks.API_ENDPOINTS:
        tags.append({"name": _("Eigene Endpunkte"), "description": _("Aus Python-Erweiterungen im Ordner extensions.")})
    for endpoint, spec in sorted(hooks.API_ENDPOINTS.items()):
        operations = {}
        for method in spec["methods"]:
            operation = {
                "tags": [_("Eigene Endpunkte")], "operationId": f"x_{endpoint}_{method.lower()}",
                "summary": (spec["fn"].__doc__ or endpoint).strip().splitlines()[0],
                "responses": {"200": {"description": _("Antwort des Endpunkts"),
                                      "content": {"application/json": {"schema": {}}}},
                              **_error_responses("401", "403")},
            }
            if spec["write"]:
                operation["description"] = _("Braucht einen Schlüssel mit Schreibrecht.")
            if method in ("POST", "PUT", "PATCH"):
                operation["requestBody"] = {"content": {"application/json": {"schema": {"type": "object"}}}}
            operations[method.lower()] = operation
        paths[f"{base}x/{endpoint}/"] = operations

    return {
        "openapi": "3.0.3",
        "info": {
            "title": _("%(app)s – API") % {"app": app.name},
            "version": "v1",
            "description": _(
                "Schnittstelle der App „%(app)s“. Jede Anfrage braucht einen API-Schlüssel dieser App "
                "im Kopf „Authorization: Bearer …“. Schlüssel erzeugt ein Designer in der App unter "
                "„Schnittstelle (API)“; dort wird auch festgelegt, welche Tabellen erreichbar sind."
            ) % {"app": app.name},
        },
        "servers": [{"url": request.build_absolute_uri("/").rstrip("/")}],
        "security": [{"schluessel": []}],
        "tags": tags,
        "paths": paths,
        "components": {
            "securitySchemes": {"schluessel": {"type": "http", "scheme": "bearer",
                                               "description": _("API-Schlüssel der App, beginnt mit bk_")}},
            "schemas": schemas,
        },
    }
