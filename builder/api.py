"""JSON-API für die Tabellen einer App.

Tabellen werden im Designer einzeln freigeschaltet. Jede Anfrage braucht einen
Schlüssel der App im Kopf „Authorization: Bearer <Schlüssel>“.

    GET    /api/v1/<app>/                     Beschreibung: Tabellen, Felder, Adressen
    GET    /api/v1/<app>/<tabelle>/           Liste (page, page_size, q, <feld>=<wert>)
    POST   /api/v1/<app>/<tabelle>/           Eintrag anlegen
    GET    /api/v1/<app>/<tabelle>/<id>/      Eintrag lesen
    PUT    /api/v1/<app>/<tabelle>/<id>/      Eintrag ersetzen
    PATCH  /api/v1/<app>/<tabelle>/<id>/      einzelne Felder ändern
    DELETE /api/v1/<app>/<tabelle>/<id>/      Eintrag löschen
    *      /api/v1/<app>/x/<name>/            eigener Endpunkt aus extensions (hooks.api)
"""
import json
import logging
from functools import wraps

from django.core.paginator import Paginator
from django.db.models import TextField
from django.db.models.functions import Cast
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from . import hooks, openapi
from .models import ApiKey, App, Field, Record
from .scripting.ops import OpsError, coerce, save_record, serialize

log = logging.getLogger(__name__)


def error(status, message, **extra):
    return JsonResponse({"error": message, **extra}, status=status)


def authenticate(request, app_slug):
    """Schlüssel aus „Authorization: Bearer …“ für diese App, sonst None. Merkt sich die letzte Nutzung."""
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    key = ApiKey.objects.filter(key_hash=ApiKey.hash(token), app__slug=app_slug).select_related("app").first() if token else None
    if key is not None:
        now = timezone.now()
        if not key.last_used or (now - key.last_used).total_seconds() > 60:
            ApiKey.objects.filter(pk=key.pk).update(last_used=now)
    return key


def unauthorized():
    response = error(401, _("Gültiger API-Schlüssel fehlt (Authorization: Bearer …)."))
    response["WWW-Authenticate"] = "Bearer"
    return response


def find_records(entity, fields, params):
    """Liste wie GET /<tabelle>/: Volltextsuche „q“, Filter je Feld, Seiten. Gibt die Antwort als Dictionary."""
    records = entity.records.all()
    query = str(params.get("q") or "").strip()
    if query:
        records = records.annotate(_text=Cast("data", TextField())).filter(_text__icontains=query)
    for f in fields:
        if params.get(f.key) is not None:
            records = records.filter(**{f"data__{f.key}": coerce(f, params[f.key])})
    try:
        size = min(max(int(params.get("page_size", 50)), 1), 200)
    except (TypeError, ValueError):
        size = 50
    page = Paginator(records.order_by("id"), size).get_page(params.get("page"))
    return {
        "count": page.paginator.count, "page": page.number, "pages": page.paginator.num_pages,
        "page_size": size, "results": [serialize(r, fields) for r in page.object_list],
    }


def api_view(view):
    """Prüft App und Schlüssel und liest den JSON-Inhalt. Die Ansicht bekommt (request, app, key, payload, …)."""

    @csrf_exempt
    @wraps(view)
    def wrapper(request, app, *args, **kwargs):
        key = authenticate(request, app)
        if key is None:
            return unauthorized()
        payload = {}
        if request.method in ("POST", "PUT", "PATCH") and request.body:
            try:
                payload = json.loads(request.body)
            except ValueError:
                return error(400, _("Der Inhalt der Anfrage ist kein gültiges JSON."))
            if not isinstance(payload, dict):
                return error(400, _("Erwartet wird ein JSON-Objekt."))
        # Eigene Endpunkte prüfen das Schreibrecht selbst (hooks.api(write=True)).
        if request.method not in ("GET", "HEAD", "OPTIONS") and not key.can_write and view.__name__ != "custom":
            return error(403, _("Dieser Schlüssel darf nur lesen."))
        return view(request, key.app, key, payload, *args, **kwargs)

    return wrapper


def get_entity(app, slug):
    return app.entities.filter(slug=slug, api_enabled=True).first()


def save(entity, payload, user, record=None, partial=False):
    try:
        return save_record(entity, payload, user, record, partial), None
    except OpsError as exc:
        return None, error(400, str(exc), fields=exc.fields)


@api_view
def describe(request, app, key, payload):
    if request.method != "GET":
        return error(405, _("Methode nicht erlaubt."))
    tables = []
    for entity in app.entities.filter(api_enabled=True).prefetch_related("fields"):
        tables.append({
            "name": entity.name, "slug": entity.slug,
            "url": request.build_absolute_uri(reverse("api_collection", args=[app.slug, entity.slug])),
            "fields": [
                {"key": f.key, "label": f.label, "type": f.type, "required": f.required,
                 **({"choices": f.choice_list()} if f.type == Field.CHOICE else {}),
                 **({"references": f.reference.slug} if f.type == Field.REFERENCE and f.reference else {})}
                for f in entity.fields.all()
            ],
        })
    return JsonResponse({
        "app": app.name, "slug": app.slug, "write": key.can_write, "tables": tables,
        "endpoints": [{"name": n, "methods": list(e["methods"]),
                       "url": request.build_absolute_uri(reverse("api_custom", args=[app.slug, n]))}
                      for n, e in hooks.API_ENDPOINTS.items()],
    })


@api_view
def collection(request, app, key, payload, entity):
    entity = get_entity(app, entity)
    if entity is None:
        return error(404, _("Diese Tabelle gibt es nicht oder sie ist nicht für die API freigeschaltet."))
    fields = list(entity.fields.all())
    if request.method == "GET":
        return JsonResponse(find_records(entity, fields, request.GET.dict()))
    if request.method == "POST":
        if not entity.allow_create:
            return error(403, _("In dieser Tabelle ist das Anlegen nicht erlaubt."))
        record, failure = save(entity, payload, request.user)
        return failure or JsonResponse(serialize(record, fields), status=201)
    return error(405, _("Methode nicht erlaubt."))


@api_view
def item(request, app, key, payload, entity, pk):
    entity = get_entity(app, entity)
    if entity is None:
        return error(404, _("Diese Tabelle gibt es nicht oder sie ist nicht für die API freigeschaltet."))
    record = Record.objects.filter(pk=pk, entity=entity).first()
    if record is None:
        return error(404, _("Diesen Eintrag gibt es nicht."))
    fields = list(entity.fields.all())
    if request.method == "GET":
        return JsonResponse(serialize(record, fields))
    if request.method in ("PUT", "PATCH"):
        if not entity.allow_edit:
            return error(403, _("In dieser Tabelle ist das Bearbeiten nicht erlaubt."))
        record, failure = save(entity, payload, request.user, record, partial=request.method == "PATCH")
        return failure or JsonResponse(serialize(record, fields))
    if request.method == "DELETE":
        if not entity.allow_delete:
            return error(403, _("In dieser Tabelle ist das Löschen nicht erlaubt."))
        record.delete()
        return HttpResponse(status=204)
    return error(405, _("Methode nicht erlaubt."))


@api_view
def custom(request, app, key, payload, name):
    endpoint = hooks.API_ENDPOINTS.get(name)
    if endpoint is None:
        return error(404, _("Diesen Endpunkt gibt es nicht."))
    if request.method not in endpoint["methods"]:
        return error(405, _("Methode nicht erlaubt."))
    if endpoint["write"] and not key.can_write:
        return error(403, _("Dieser Schlüssel darf nur lesen."))
    data = payload if request.method != "GET" else request.GET.dict()
    try:
        result = endpoint["fn"](request, app, data)
    except Exception:
        log.exception("Fehler im API-Endpunkt %s", name)
        return error(500, _("Der Endpunkt ist auf einen Fehler gelaufen."))
    return JsonResponse(result, safe=False)


@api_view
def openapi_spec(request, app, key, payload):
    """OpenAPI-Beschreibung für Werkzeuge (Postman, Code-Generatoren), mit Schlüssel abrufbar."""
    if request.method != "GET":
        return error(405, _("Methode nicht erlaubt."))
    return JsonResponse(openapi.build(request, app), json_dumps_params={"ensure_ascii": False})
