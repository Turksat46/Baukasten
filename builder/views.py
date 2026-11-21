"""Laufzeit: das, was Nutzer einer fertigen App sehen."""
import csv
import json
import secrets
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from . import datasources, hooks, openapi, platform
from . import app_i18n
from .blocks import all_types, display_value, reference_labels, render_block, render_layout
from .forms import RecordForm
from .models import App, HomeWidget, Page, Record, Script
from .scripting import python as python_scripts
from .scripting.ops import OpsError, TableOps
from .scripting.triggers import execute, page_scripts, run_page

def get_app(request, slug):
    app = get_object_or_404(App, slug=slug, kind=App.APP)  # Automatisierungen haben keine Seiten
    if not app.user_can_use(request.user):
        raise PermissionDenied
    app_i18n.activate(app)  # Texte der App in der Sprache der Person anzeigen
    return app


def deny(request):
    """Ohne Anmeldung zur Anmeldung, sonst 403."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    raise PermissionDenied


def runtime_access(request, slug):
    """App für die Laufzeit: (app, guest) oder eine Antwort (Anmeldung, zu viele Anfragen).

    guest=True heißt: Die Person darf die App nicht regulär benutzen (nicht angemeldet oder
    nicht in den Gruppen) und bekommt nur öffentliche Seiten und was auf ihnen steht."""
    app = get_object_or_404(App, slug=slug, kind=App.APP)
    if request.user.is_authenticated and app.user_can_use(request.user):
        app_i18n.activate(app)
        return app, False
    if not app.published or not app.pages.filter(public=True).exists():
        return deny(request)
    if not guest_allowed(request):
        return HttpResponse(_("Zu viele Anfragen. Bitte versuche es gleich noch einmal."), status=429,
                            headers={"Retry-After": "60"})
    app_i18n.activate(app)
    return app, True


def guest_allowed(request):
    """Anfragebegrenzung für Gäste je Adresse und Minute (PUBLIC_RATE, änderbar unter /admin/)."""
    from . import platform

    limit = platform.value("public_rate")
    if not limit:
        return True
    key = f"oeffentlich:{request.META.get('REMOTE_ADDR', '')}:{int(time.time() // 60)}"
    cache.add(key, 0, 90)
    try:
        return cache.incr(key) <= limit
    except ValueError:
        cache.set(key, 1, 90)
        return True


def safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


PINNABLE_WIDGET_TYPES = {
    "stat", "progress", "chart", "donut", "line", "timeline", "notice",
    "table", "cards", "checklist", "query", "output",
    "scatter", "boxplot", "heatmap", "spec_chart",
}


def _is_pinnable(block):
    btype = block.get("type") or ""
    return btype in PINNABLE_WIDGET_TYPES or btype.startswith(("c-", "x-"))


def _block_label(block, types_map):
    props = block.get("props") or {}
    btype = types_map.get(block.get("type"))
    fallback = str(btype.label) if btype else str(block.get("type") or "")
    return str(props.get("title") or props.get("label") or props.get("text") or fallback).strip()[:80]


@login_required
def home(request):
    apps = [a for a in App.objects.prefetch_related("pages", "scripts", "queries") if a.user_can_use(request.user)]
    app_ids = {a.pk for a in apps}
    types_map = all_types()
    for app in apps:
        pages = list(app.pages.all())
        app.page_count = sum(1 for p in pages if p.show_in_nav)
        app.tone = sum(map(ord, app.slug)) % 5 + 1  # feste Farbe je App für die Kachel
        notices = []
        for p in pages:
            for b in p.layout or []:
                if b.get("type") == "notice":
                    props = b.get("props") or {}
                    text = str(props.get("text") or props.get("title") or "").strip()
                    if text:
                        notices.append({"page": p.title, "text": text[:100]})
                        if len(notices) >= 2:
                            break
            if len(notices) >= 2:
                break
        app.page_notices = notices
        if app.user_can_edit(request.user):
            script_errors = sum(1 for s in app.scripts.all() if s.failures > 0)
            query_errors = sum(1 for q in app.queries.all() if q.last_sync_at and not q.last_sync_ok)
            app.error_count = script_errors + query_errors
        else:
            app.error_count = 0

    widgets = []
    pinned_keys = set()
    for w in HomeWidget.objects.filter(user=request.user).select_related("page", "page__app"):
        if w.page.app_id not in app_ids:
            continue
        block = next((b for b in (w.page.layout or []) if b.get("id") == w.block_id), None)
        if block is None:
            continue
        pinned_keys.add((w.page_id, w.block_id))
        w.display_title = w.title or _block_label(block, types_map)
        w.col_width = w.width if w.width in (4, 6, 12) else 4
        widgets.append(w)

    # Widget-Auswahl wie unter Android: je App eine Gruppe mit allen anpinnbaren Bausteinen.
    widget_groups = []
    for app in apps:
        items = []
        for p in app.pages.all():
            for b in p.layout or []:
                bid = b.get("id")
                if not bid or not _is_pinnable(b) or (p.pk, bid) in pinned_keys:
                    continue
                btype = types_map.get(b.get("type"))
                items.append({
                    "value": f"{p.pk}:{bid}",
                    "label": _block_label(b, types_map),
                    "page": p.title,
                    "kind": str(btype.label) if btype else str(b.get("type") or ""),
                    "preview_url": reverse("page_block", args=[app.slug, p.slug, bid]),
                })
        if items:
            widget_groups.append({"app": app, "items": items})

    hour = timezone.localtime().hour
    greeting = _("Guten Morgen") if 5 <= hour < 11 else _("Guten Tag") if hour < 18 else _("Guten Abend")
    return render(request, "builder/home.html", {
        "apps": apps, "greeting": greeting, "today": timezone.localdate(),
        "drafts": sum(1 for a in apps if not a.published), "show_search": len(apps) > 6,
        "widgets": widgets, "widget_groups": widget_groups,
    })


@login_required
@require_POST
def home_widget_add(request):
    target = str(request.POST.get("target") or "").strip()
    page_id, sep, block_id = target.partition(":")
    if not sep or not page_id.isdigit() or not block_id:
        messages.error(request, _("Bitte einen gültigen Baustein auswählen."))
        return redirect("home")
    page = get_object_or_404(Page.objects.select_related("app"), pk=int(page_id))
    if not page.app.user_can_use(request.user):
        raise PermissionDenied
    block = next((b for b in (page.layout or []) if b.get("id") == block_id), None)
    if block is None or not _is_pinnable(block):
        messages.error(request, _("Dieser Baustein kann nicht als Widget angepinnt werden."))
        return redirect("home")
    width = int(block.get("width") or 4)
    if width not in (4, 6, 12):
        width = 6 if width >= 6 else 4
    HomeWidget.objects.get_or_create(
        user=request.user, page=page, block_id=block_id,
        defaults={"title": _block_label(block, all_types()), "width": width},
    )
    return redirect("home")


@login_required
@require_POST
def home_widget_remove(request, pk):
    get_object_or_404(HomeWidget, pk=pk, user=request.user).delete()
    return redirect("home")


def runtime_config(request, app, page, blocks):
    """Was der Browser für JavaScript-Skripte und automatische Aktualisierung braucht."""
    js_page = [{"slug": sc.slug, "name": sc.name, "code": sc.code}
               for sc in page_scripts(app, page, language=Script.JAVASCRIPT)]
    used = {b.get("props", {}).get("script") for b in (page.layout if page else [])
            if b.get("type") == "button" and b.get("props", {}).get("target") == "script"}
    js_buttons = {sc.slug: {"slug": sc.slug, "name": sc.name, "code": sc.code}
                  for sc in app.scripts.filter(language=Script.JAVASCRIPT, trigger=Script.BUTTON, enabled=True, slug__in=used)}
    refresh = any(b["refresh"] or b.get("lazy") for b in blocks)
    if not (js_page or js_buttons or refresh):
        return None
    return {
        "sandbox": reverse("script_sandbox"), "bridge": reverse("script_bridge", args=[app.slug]),
        "block_url": reverse("page_block", args=[app.slug, page.slug, "BLOCK"]) if page else "",
        "csrf": get_token(request), "scripts": js_page, "buttons": js_buttons,
        "timeout": int(platform.value("script_timeout") * 1000), "page": page.slug if page else "",
        "user": python_scripts.user_info(request.user), "show_errors": app.user_can_edit(request.user),
    }


def _interactive(blocks):
    """Braucht die Seite die Skripte für interaktive Bausteine (Drag-and-drop, Checkliste …)?"""
    types = all_types()
    return any(getattr(types.get(b.get("type")), "action", None) for b in blocks)


def nav_pages(app, guest):
    pages = app.pages.filter(show_in_nav=True)
    return pages.filter(public=True) if guest else pages


def page(request, app, page=None):
    access = runtime_access(request, app)
    if isinstance(access, HttpResponse):
        return access
    app, guest = access
    current = get_object_or_404(app.pages, slug=page) if page else app.home_page
    if guest and not (current and current.public):
        return deny(request)
    overrides, notes, errors = run_page(request, app, current) if current else ({}, [], [])
    blocks = render_layout(request, app, current, overrides=overrides,
                           lazy=settings.BAUKASTEN_LAZY_QUERIES) if current else []
    return render(request, "builder/page.html", {
        "app": app,
        "page": current,
        "nav_pages": nav_pages(app, guest),
        "blocks": blocks,
        "script_notes": notes,
        "script_errors": errors if app.user_can_edit(request.user) else [],
        "runtime": runtime_config(request, app, current, blocks) if current else None,
        "interactive": _interactive(blocks),
    })


def page_block(request, app, page, block):
    """Ein einzelner Baustein, für die automatische Aktualisierung."""
    access = runtime_access(request, app)
    if isinstance(access, HttpResponse):
        return access
    app, guest = access
    current = get_object_or_404(app.pages, slug=page)
    if guest and not current.public:
        return deny(request)
    found = next((b for b in current.layout if b.get("id") == block), None)
    if found is None:
        return HttpResponse(status=404)
    overrides = run_page(request, app, current)[0] if found.get("name") else {}
    html = render_block(request, app, found, all_types(), overrides)
    response = HttpResponse(html or "", content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def block_action(request, app, page, block):
    """Aktionen interaktiver Bausteine (Einsatzplanung, Kanban, Checkliste, Schieberegler).

    Was erlaubt ist, steht in den Einstellungen des Bausteins auf der gespeicherten Seite, nie in der
    Anfrage. Gespeichert wird mit den Rechten der Person (Tabellen-Schalter, Pflichtfelder, Protokoll).
    Antwort 409 mit confirm=true: Warnung (z. B. Überplanung), mit force=true trotzdem ausführen."""
    from . import planning

    app = get_app(request, app)
    current = get_object_or_404(app.pages, slug=page)
    found = next((b for b in current.layout or [] if b.get("id") == block), None)
    if found is None:
        return JsonResponse({"error": _("Diesen Baustein gibt es auf der Seite nicht (mehr).")}, status=404)
    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": _("Ungültige Daten.")}, status=400)
    block_type = all_types().get(found.get("type"))
    if not block_type or not block_type.action:
        return JsonResponse({"error": _("Dieser Baustein hat keine Aktionen.")}, status=400)
    try:
        return JsonResponse(block_type.action(app, found, payload, request.user))
    except planning.Refused as exc:
        return JsonResponse(exc.payload(), status=409)
    except OpsError as exc:
        return JsonResponse({"error": str(exc), "fields": exc.fields}, status=400)


@require_POST
def run_script(request, app, name):
    """Python-Skript per Button. Gäste nur für Buttons auf öffentlichen Seiten."""
    access = runtime_access(request, app)
    if isinstance(access, HttpResponse):
        return access
    app, guest = access
    if guest and name not in app.public_reach()[0]:
        return deny(request)
    script = get_object_or_404(app.scripts, slug=name, language=Script.PYTHON, trigger=Script.BUTTON, enabled=True)
    # Parameter der Seite (aus der Adresse) und des Formulars; das Formular hat Vorrang.
    params = {**request.GET.dict(), **request.POST.dict()}
    params.pop("csrfmiddlewaretoken", None)
    result = execute(script, Script.BUTTON, user=request.user, params=params, request=request)
    for text in result.messages:
        messages.success(request, text)
    if not result.ok:
        messages.error(request, _("Das Skript „%(name)s“ ist fehlgeschlagen.") % {"name": script.name}
                       + (" " + result.error_text() if app.user_can_edit(request.user) else ""))
    elif not result.messages:
        messages.success(request, _("Erledigt."))
    return redirect(safe_next(request, reverse("page", args=[app.slug])))


@login_required
@require_POST
def script_bridge(request, app):
    """Brücke für JavaScript-Skripte: Tabellen mit den Rechten der angemeldeten Person, gespeicherte Abfragen."""
    app = get_app(request, app)
    try:
        payload = json.loads(request.body)
        op, args = str(payload.get("op", "")), payload.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError
    except (ValueError, AttributeError):
        return JsonResponse({"error": _("Ungültige Daten.")}, status=400)
    try:
        if op.startswith("table.") and op[6:] in ("filter", "get", "count", "aggregate", "create", "update", "delete"):
            ops = TableOps(app, user=request.user, enforce_flags=True)
            return JsonResponse({"result": getattr(ops, op[6:])(**args)})
        if op == "query.run":
            query = app.queries.filter(slug=str(args.get("slug"))).first()
            if query is None:
                return JsonResponse({"error": _("Die Abfrage „%(name)s“ gibt es in dieser App nicht.") % {"name": args.get("slug")}}, status=404)
            return JsonResponse({"result": datasources.run_saved(query)["rows"]})
    except OpsError as exc:
        return JsonResponse({"error": str(exc), "fields": exc.fields}, status=400)
    except datasources.QueryBusy as exc:
        response = JsonResponse({"error": str(exc), "busy": True}, status=503)
        response["Retry-After"] = "3"
        return response
    except datasources.QueryError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except TypeError:
        return JsonResponse({"error": _("Ungültige Daten.")}, status=400)
    return JsonResponse({"error": _("Unbekannte Anfrage.")}, status=400)


@xframe_options_sameorigin
def script_sandbox(request):
    """Abgeschottete Umgebung für JavaScript-Skripte: eigener Ursprung (sandbox), kein Netz, keine Cookies."""
    nonce = secrets.token_urlsafe(16)
    response = render(request, "builder/sandbox.html", {"nonce": nonce})
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; worker-src blob:; connect-src 'none'; "
        "img-src 'none'; style-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'"
    )
    response["Cache-Control"] = "no-store"
    return response


def _record_form(request, app, entity, record=None, guest=False):
    home_url = reverse("page", args=[app.slug])
    # Formular-Bausteine senden ihre Felder mit Präfix; das eigenständige Formular ohne.
    prefix = request.POST.get("form_prefix") or None
    initial = None
    if record is None and request.method == "GET":
        # Vorbelegung über die Adresse, z. B. …/neu/?datum=2026-11-19 aus dem Kalender
        keys = {f.key for f in entity.fields.all() if f.show_in_form}
        initial = {k: v[:500] for k, v in request.GET.items() if k in keys} or None
    form = RecordForm(entity, request.POST or None, record=record, prefix=prefix,
                      **({"initial": initial} if initial else {}))
    if request.method == "POST" and form.is_valid():
        form.save(request.user)
        messages.success(request, _("Gespeichert."))
        return redirect(safe_next(request, home_url))
    history = []
    if record and request.user.is_authenticated and app.user_can_edit(request.user):
        from .designer import _audit_labels
        from .models import AuditEntry

        history = [_audit_labels(e) for e in AuditEntry.objects.filter(
            app=app, target_type="record", target_id=str(record.pk)).select_related("user")[:10]]
    return render(request, "builder/record_form.html", {
        "app": app, "entity": entity, "form": form, "record": record, "history": history,
        "nav_pages": nav_pages(app, guest),
        "next": safe_next(request, home_url), "form_prefix": prefix or "",
    })


def record_create(request, app, entity):
    """Eintrag anlegen. Gäste nur in Tabellen, deren Formular auf einer öffentlichen Seite steht."""
    access = runtime_access(request, app)
    if isinstance(access, HttpResponse):
        return access
    app, guest = access
    if guest and entity not in app.public_reach()[1]:
        return deny(request)
    entity = get_object_or_404(app.entities, slug=entity)
    if not entity.allow_create:
        raise PermissionDenied
    return _record_form(request, app, entity, guest=guest)


@login_required
def record_edit(request, app, entity, pk):
    app = get_app(request, app)
    entity = get_object_or_404(app.entities, slug=entity)
    if not entity.allow_edit:
        raise PermissionDenied
    return _record_form(request, app, entity, get_object_or_404(Record, pk=pk, entity=entity))


@login_required
@require_POST
def record_delete(request, app, entity, pk):
    app = get_app(request, app)
    entity = get_object_or_404(app.entities, slug=entity)
    if not entity.allow_delete:
        raise PermissionDenied
    get_object_or_404(Record, pk=pk, entity=entity).delete()
    messages.success(request, _("Gelöscht."))
    return redirect(safe_next(request, reverse("page", args=[app.slug])))


@login_required
@require_POST
def run_action(request, app, name):
    app = get_app(request, app)
    registered = hooks.ACTIONS.get(name)
    if not registered:
        raise PermissionDenied
    result = registered["fn"](request, app)
    if isinstance(result, HttpResponse):
        return result
    if result:
        messages.success(request, str(result))
    return redirect(safe_next(request, reverse("page", args=[app.slug])))


class _Echo:
    def write(self, value):
        return value


def _csv_cell(value):
    """Verhindert, dass Excel einen Zellinhalt als Formel ausführt."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@login_required
def entity_export(request, app, entity):
    app = get_app(request, app)
    entity = get_object_or_404(app.entities, slug=entity)
    fields = list(entity.fields.all())
    writer = csv.writer(_Echo(), delimiter=";")

    def rows():
        yield "\ufeff" + writer.writerow([f.label for f in fields])
        batch = []
        for record in entity.records.order_by("id").iterator(chunk_size=500):
            batch.append(record)
            if len(batch) == 500:
                yield from write(batch)
                batch = []
        yield from write(batch)

    def write(batch):
        refs = reference_labels(fields, batch)
        for record in batch:
            yield writer.writerow([_csv_cell(display_value(f, record.data.get(f.key), refs)) for f in fields])

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{entity.slug}.csv"'
    return response


@login_required
def entity_import(request, app, entity):
    """Zweistufiger CSV-Import für eine Tabelle: Datei hochladen, Spalten zuordnen, importieren."""
    from . import csv_import

    app = get_app(request, app)
    entity = get_object_or_404(app.entities, slug=entity)
    if not entity.allow_create:
        raise PermissionDenied
    fields = list(entity.fields.all())
    session_key = f"csv_import:{app.slug}:{entity.slug}"
    back = safe_next(request, reverse("page", args=[app.slug]))
    errors = []

    if request.method == "POST":
        step = request.POST.get("step", "upload")
        if step == "reset":
            request.session.pop(session_key, None)
            return redirect(request.path + (f"?next={request.GET.get('next', '')}" if request.GET.get("next") else ""))
        if step == "upload":
            upload = request.FILES.get("file")
            if not upload:
                messages.error(request, _("Bitte eine CSV-Datei auswählen."))
            else:
                try:
                    headers, rows = csv_import.parse_csv(upload.read())
                    request.session[session_key] = {"headers": headers, "rows": rows}
                except csv_import.CsvImportError as exc:
                    messages.error(request, str(exc))
        elif step == "import":
            staged = request.session.get(session_key)
            if not staged:
                messages.error(request, _("Bitte zuerst eine CSV-Datei hochladen."))
            else:
                headers, rows = staged["headers"], staged["rows"]
                mapping = [request.POST.get(f"col_{i}", "") for i in range(len(headers))]
                skip_errors = bool(request.POST.get("skip_errors"))
                try:
                    created, errors = csv_import.run_import(
                        app, entity, rows, mapping, request.user, skip_errors=skip_errors,
                    )
                    if created and not errors:
                        request.session.pop(session_key, None)
                        messages.success(request, _("%(n)s Einträge importiert.") % {"n": created})
                        return redirect(back)
                    if created and errors:
                        request.session.pop(session_key, None)
                        messages.warning(
                            request,
                            _("%(n)s Einträge importiert, %(err)s Zeilen übersprungen.") % {"n": created, "err": len(errors)},
                        )
                    elif errors:
                        messages.error(request, _("Import abgebrochen: %(err)s fehlerhafte Zeilen.") % {"err": len(errors)})
                except csv_import.CsvImportError as exc:
                    messages.error(request, str(exc))

    staged = request.session.get(session_key)
    columns = []
    preview = []
    if staged:
        guessed = csv_import.guess_mapping(staged["headers"], fields)
        columns = [{"index": i, "header": h, "guess": guessed[i]} for i, h in enumerate(staged["headers"])]
        preview = staged["rows"][:5]

    return render(request, "builder/entity_import.html", {
        "app": app,
        "entity": entity,
        "fields": fields,
        "staged": staged,
        "columns": columns,
        "preview": preview,
        "row_count": len(staged["rows"]) if staged else 0,
        "errors": errors[:20],
        "more_errors": max(len(errors) - 20, 0),
        "back": back,
    })



# ---------- API-Dokumentation ----------

@login_required
def api_index(request):
    """Alle Apps, deren API die angemeldete Person einsehen darf."""
    apps = [a for a in App.objects.prefetch_related("entities", "groups") if a.user_can_use(request.user)]
    rows = [{"app": a, "tables": [e for e in a.entities.all() if e.api_enabled]} for a in apps]
    return render(request, "builder/api_index.html", {"rows": rows, "custom_endpoints": sorted(hooks.API_ENDPOINTS)})


@login_required
def api_docs(request, app):
    app = get_app(request, app)
    spec = openapi.build(request, app)
    operations = []
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method == "parameters":
                continue
            operations.append({"method": method.upper(), "path": path, "summary": operation["summary"],
                               "tag": operation["tags"][0]})
    return render(request, "builder/api_docs.html", {
        "app": app, "operations": operations,
        "tables": app.entities.filter(api_enabled=True).prefetch_related("fields"),
        "base": request.build_absolute_uri(reverse("api_describe", args=[app.slug])),
        "spec_url": reverse("api_docs_spec", args=[app.slug]),
        "public_spec_url": request.build_absolute_uri(reverse("api_openapi", args=[app.slug])),
        "nav_pages": app.pages.filter(show_in_nav=True),
    })


@login_required
def api_docs_spec(request, app):
    app = get_app(request, app)
    return JsonResponse(openapi.build(request, app), json_dumps_params={"ensure_ascii": False})


@login_required
@xframe_options_sameorigin
def api_docs_ui(request, app):
    """Swagger UI ohne die Stile der Oberfläche, eingebettet in api_docs."""
    app = get_app(request, app)
    return render(request, "builder/api_swagger.html", {"app": app, "spec_url": reverse("api_docs_spec", args=[app.slug])})
