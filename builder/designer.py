"""Designer: Apps, Tabellen, Felder, Seiten, eigene Bausteine und API-Zugänge bearbeiten."""
import csv
import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import app_i18n, hooks
from .blocks import (BUILTIN_PLACEHOLDERS, all_types, clean_layout, designer_config, make_block,
                     render_custom, render_layout)
from . import datasources
from .forms import (ApiKeyForm, AppForm, CustomBlockForm, EntityForm, FieldForm, NewAppForm, NewPageForm,
                    QueryForm, ScriptForm)
from . import versions
from .models import ApiKey, App, AppVersion, CustomBlock, DataQuery, Entity, Field, Page, Script, can_design
from .scripting import python as python_scripts
from .scripting.triggers import execute


def designer_required(view):
    """Designer-Recht; bei Adressen einer App zusätzlich Bearbeitungsrecht für genau diese App."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not can_design(request.user):
            raise PermissionDenied
        if "app" in kwargs:
            app = get_object_or_404(App, slug=kwargs["app"])
            if not app.user_can_edit(request.user):
                raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _share(request, app):
    """Mitbearbeiter hinzufügen oder entfernen, App übernehmen."""
    action = request.POST.get("action")
    if action == "claim":
        if app.created_by_id is not None:
            raise PermissionDenied
        app.created_by = request.user
        app.save(update_fields=["created_by"])
        messages.success(request, _("Du bist jetzt Eigentümer/in der App. Andere Designer brauchen ab sofort eine Einladung."))
        return
    if not app.user_can_manage(request.user):
        raise PermissionDenied
    if action == "add_user":
        name = request.POST.get("username", "").strip()
        user = get_user_model().objects.filter(username__iexact=name).first() if name else None
        if user is None:
            messages.error(request, _("Es gibt kein Konto mit dem Benutzernamen „%(name)s“.") % {"name": name})
        elif user.pk == app.created_by_id:
            messages.error(request, _("%(name)s ist schon Eigentümer/in der App.") % {"name": user.get_username()})
        elif not can_design(user):
            messages.error(request, _("%(name)s hat kein Designer-Recht und könnte die App nicht bearbeiten.")
                           % {"name": user.get_username()})
        else:
            app.editors.add(user)
            messages.success(request, _("%(name)s darf die App jetzt bearbeiten.") % {"name": user.get_username()})
    elif action == "remove_user":
        app.editors.remove(*app.editors.filter(pk=request.POST.get("user")))
        messages.success(request, _("Mitbearbeiter entfernt."))
    elif action == "add_group":
        group = Group.objects.filter(pk=request.POST.get("group")).first()
        if group:
            app.editor_groups.add(group)
            messages.success(request, _("Designer in der Gruppe „%(name)s“ dürfen die App jetzt bearbeiten.") % {"name": group.name})
    elif action == "remove_group":
        app.editor_groups.remove(*app.editor_groups.filter(pk=request.POST.get("group")))
        messages.success(request, _("Gruppe entfernt."))


def entity_page(entity):
    """Erzeugt aus einer Tabelle eine fertige Seite mit Liste."""
    return Page.objects.create(
        app=entity.app,
        title=entity.name,
        layout=[
            make_block("heading", text=entity.name, level="1"),
            make_block("table", entity=entity.slug),
        ],
    )


@designer_required
def home(request):
    form = NewAppForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        app = form.save(commit=False)
        app.created_by = request.user
        app.save()
        Page.objects.create(app=app, title=_("Start"), layout=[
            make_block("heading", text=app.name, level="1"),
            make_block("text", text=_("Willkommen. Diese Seite lässt sich im Designer frei gestalten.")),
        ])
        return redirect("designer_app", app.slug)
    apps = list(App.editable_by(request.user).select_related("created_by"))
    for item in apps:
        item.can_manage = item.user_can_manage(request.user)
    return render(request, "designer/home.html", {
        "apps": apps, "form": form, "custom_count": CustomBlock.objects.count(),
    })


@designer_required
@require_POST
def app_import(request):
    """Legt eine App aus einer zuvor exportierten Datei an."""
    upload = request.FILES.get("file")
    if not upload or upload.size > 5 * 1024 * 1024:
        messages.error(request, _("Bitte eine exportierte App-Datei auswählen (höchstens 5 MB)."))
        return redirect("designer_home")
    try:
        app = versions.import_app(json.loads(upload.read().decode("utf-8")), request.user)
    except (ValueError, UnicodeDecodeError):
        messages.error(request, _("Die Datei ist keine gültige App-Datei."))
        return redirect("designer_home")
    messages.success(request, _("App „%(name)s“ importiert. Sie ist noch ein Entwurf.") % {"name": app.name})
    return redirect("designer_app", app.slug)


@designer_required
def app_detail(request, app):
    app = get_object_or_404(App, slug=app)
    form = AppForm(instance=app, prefix="app")
    entity_form = EntityForm(prefix="entity")
    page_form = NewPageForm(prefix="page")
    key_form = ApiKeyForm(prefix="key")
    new_key = None
    if request.method == "POST":
        kind = request.POST.get("kind")
        if kind == "app":
            form = AppForm(request.POST, instance=app, prefix="app")
            if form.is_valid():
                form.save()
                messages.success(request, _("Einstellungen gespeichert."))
                return redirect("designer_app", app.slug)
        elif kind == "entity":
            entity_form = EntityForm(request.POST, prefix="entity")
            if entity_form.is_valid():
                entity = entity_form.save(commit=False)
                entity.app = app
                entity.save()
                Field.objects.create(entity=entity, label=_("Bezeichnung"), required=True)
                return redirect("designer_entity", app.slug, entity.pk)
        elif kind == "page":
            page_form = NewPageForm(request.POST, prefix="page")
            if page_form.is_valid():
                page = page_form.save(commit=False)
                page.app = app
                page.save()
                return redirect("designer_page", app.slug, page.pk)
        elif kind == "api":
            enabled = set(request.POST.getlist("api_entity"))
            for entity in app.entities.all():
                wanted = str(entity.pk) in enabled
                if entity.api_enabled != wanted:
                    entity.api_enabled = wanted
                    entity.save(update_fields=["api_enabled"])
            messages.success(request, _("API-Freigaben gespeichert."))
            return redirect("designer_app", app.slug)
        elif kind == "version":
            version = versions.create_version(app, request.user, request.POST.get("note", "").strip())
            messages.success(request, _("Version %(number)s gespeichert.") % {"number": version.number})
            return redirect("designer_app", app.slug)
        elif kind == "share":
            _share(request, app)
            return redirect(reverse("designer_app", args=[app.slug]) + "#mitbearbeiter")
        elif kind == "key":
            key_form = ApiKeyForm(request.POST, prefix="key")
            if key_form.is_valid():
                # Der Schlüssel wird nur in dieser einen Antwort im Klartext gezeigt.
                _obj, new_key = ApiKey.issue(app, key_form.cleaned_data["name"],
                                             key_form.cleaned_data["can_write"], request.user)
                key_form = ApiKeyForm(prefix="key")
    entities = list(app.entities.prefetch_related("fields"))
    api_entity = next((e for e in entities if e.api_enabled), None)
    return render(request, "designer/app.html", {
        "app": app, "form": form, "entity_form": entity_form, "page_form": page_form,
        "entities": entities, "pages": app.pages.all(),
        "key_form": key_form, "api_keys": app.api_keys.all(), "new_key": new_key,
        "api_base": request.build_absolute_uri(reverse("api_describe", args=[app.slug])),
        "api_example": request.build_absolute_uri(reverse("api_collection", args=[app.slug, api_entity.slug])) if api_entity else "",
        "api_endpoints": sorted(hooks.API_ENDPOINTS),
        "versions": app.versions.select_related("created_by")[:30],
        "scripts": app.scripts.select_related("page", "entity"),
        "queries": app.queries.select_related("sync_entity"),
        "sources": datasources.describe_sources(),
        "can_manage": app.user_can_manage(request.user),
        "translation_progress": translation_progress(app),
        "editors": app.editors.order_by("username"),
        "editor_groups": app.editor_groups.order_by("name"),
        "other_groups": Group.objects.exclude(pk__in=app.editor_groups.values("pk")).order_by("name"),
    })


@designer_required
@require_POST
def version_restore(request, app, pk):
    version = get_object_or_404(AppVersion, pk=pk, app__slug=app)
    kept = versions.restore(version, request.user)
    messages.success(request, _("Version %(number)s wiederhergestellt. Der vorherige Stand wurde als neue Version gesichert.") % {"number": version.number})
    if kept:
        messages.success(request, _("Diese Tabellen gab es in der Version noch nicht; sie bleiben mit ihren Daten erhalten: %(names)s") % {"names": ", ".join(kept)})
    return redirect("designer_app", app)


@designer_required
def version_download(request, app, pk):
    version = get_object_or_404(AppVersion, pk=pk, app__slug=app)
    response = HttpResponse(json.dumps(version.snapshot, ensure_ascii=False, indent=2),
                            content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{app}-v{version.number}.json"'
    return response


@designer_required
@require_POST
def app_delete(request, app):
    app = get_object_or_404(App, slug=app)
    if not app.user_can_manage(request.user):
        raise PermissionDenied
    app.delete()
    messages.success(request, _("App gelöscht."))
    return redirect("designer_home")


@designer_required
@require_POST
def key_delete(request, app, pk):
    get_object_or_404(ApiKey, pk=pk, app__slug=app).delete()
    messages.success(request, _("Schlüssel gelöscht. Er funktioniert ab sofort nicht mehr."))
    return redirect("designer_app", app)


@designer_required
def entity_detail(request, app, pk):
    app = get_object_or_404(App, slug=app)
    entity = get_object_or_404(Entity, pk=pk, app=app)
    form = EntityForm(instance=entity, prefix="entity")
    field_form = FieldForm(app=app, prefix="field")
    if request.method == "POST":
        if request.POST.get("kind") == "entity":
            form = EntityForm(request.POST, instance=entity, prefix="entity")
            if form.is_valid():
                form.save()
                messages.success(request, _("Tabelle gespeichert."))
                return redirect("designer_entity", app.slug, entity.pk)
        else:
            field_form = FieldForm(request.POST, app=app, prefix="field")
            if field_form.is_valid():
                field = field_form.save(commit=False)
                field.entity = entity
                field.save()
                return redirect("designer_entity", app.slug, entity.pk)
    return render(request, "designer/entity.html", {
        "app": app, "entity": entity, "form": form, "field_form": field_form,
        "fields": entity.fields.all(), "record_count": entity.records.count(),
    })


@designer_required
@require_POST
def entity_delete(request, app, pk):
    get_object_or_404(Entity, pk=pk, app__slug=app).delete()
    messages.success(request, _("Tabelle samt Daten gelöscht."))
    return redirect("designer_app", app)


@designer_required
@require_POST
def entity_make_page(request, app, pk):
    entity = get_object_or_404(Entity, pk=pk, app__slug=app)
    page = entity_page(entity)
    messages.success(request, _("Seite „%(title)s“ erzeugt.") % {"title": page.title})
    return redirect("designer_page", app, page.pk)


@designer_required
def field_edit(request, app, pk):
    app = get_object_or_404(App, slug=app)
    field = get_object_or_404(Field, pk=pk, entity__app=app)
    form = FieldForm(request.POST or None, instance=field, app=app)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("designer_entity", app.slug, field.entity_id)
    return render(request, "designer/field.html", {"app": app, "field": field, "form": form})


@designer_required
@require_POST
def field_delete(request, app, pk):
    field = get_object_or_404(Field, pk=pk, entity__app__slug=app)
    entity_id = field.entity_id
    field.delete()
    return redirect("designer_entity", app, entity_id)


@designer_required
@require_POST
def field_move(request, app, pk, direction):
    field = get_object_or_404(Field, pk=pk, entity__app__slug=app)
    fields = list(field.entity.fields.all())
    index = fields.index(field)
    other = index - 1 if direction == "auf" else index + 1
    if 0 <= other < len(fields):
        fields[index], fields[other] = fields[other], fields[index]
        for position, f in enumerate(fields, start=1):
            if f.order != position:
                f.order = position
                f.save(update_fields=["order"])
    return redirect("designer_entity", app, field.entity_id)


@designer_required
def page_designer(request, app, pk):
    app = get_object_or_404(App, slug=app)
    page = get_object_or_404(Page, pk=pk, app=app)
    if request.method == "POST":
        try:
            payload = json.loads(request.body)
            page.layout = clean_layout(payload.get("layout"))
        except (ValueError, AttributeError):
            return JsonResponse({"ok": False, "error": _("Ungültige Daten.")}, status=400)
        title = str(payload.get("title") or "").strip()[:80]
        if title:
            page.title = title
        page.show_in_nav = bool(payload.get("show_in_nav", True))
        page.public = bool(payload.get("public", page.public))
        page.save()
        return JsonResponse({"ok": True, "layout": page.layout})
    return render(request, "designer/page.html", {
        "app": app, "page": page, "config": designer_config(app, page),
    })


@designer_required
@require_POST
def page_preview(request, app, pk):
    """Rendert ein noch nicht gespeichertes Layout für die Arbeitsfläche des Designers."""
    app = get_object_or_404(App, slug=app)
    page = get_object_or_404(Page, pk=pk, app=app)
    try:
        layout = clean_layout(json.loads(request.body).get("layout"))
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False}, status=400)
    blocks = render_layout(request, app, page, layout)
    return JsonResponse({"ok": True, "blocks": {b["id"]: b["html"] for b in blocks}})


@designer_required
@require_POST
def page_delete(request, app, pk):
    get_object_or_404(Page, pk=pk, app__slug=app).delete()
    messages.success(request, _("Seite gelöscht."))
    return redirect("designer_app", app)


# ---------- Übersetzungen ----------

@designer_required
def translations(request, app):
    """Alle Texte der App mit ihren Übersetzungen je Sprache bearbeiten, als CSV aus- und einlesen."""
    app = get_object_or_404(App, slug=app)
    languages = app_i18n.target_languages()
    if not languages:
        messages.error(request, _("Es ist nur eine Sprache eingerichtet (Einstellung LANGUAGES)."))
        return redirect("designer_app", app.slug)
    if request.method == "POST":
        if request.POST.get("kind") == "import":
            upload = request.FILES.get("file")
            if not upload or upload.size > 2 * 1024 * 1024:
                messages.error(request, _("Bitte eine CSV-Datei auswählen (höchstens 2 MB)."))
            else:
                try:
                    count = app_i18n.from_csv(app, upload.read().decode("utf-8-sig"))
                except (UnicodeDecodeError, csv.Error):
                    messages.error(request, _("Die Datei ist keine lesbare CSV-Datei (UTF-8)."))
                else:
                    messages.success(request, _("%(count)s Übersetzungen übernommen.") % {"count": count})
            return redirect("designer_translations", app.slug)
        # Zusammenführen: Texte, die nicht im Formular standen (Filter „nur fehlende“), bleiben erhalten.
        merged = {code: dict(app_i18n.mapping(app, code)) for code, _name in languages}
        sources = {key[4:]: value for key, value in request.POST.items() if key.startswith("src_")}
        for index, text in sources.items():
            for code, _name in languages:
                value = request.POST.get(f"tr_{code}_{index}", "").strip()
                if value:
                    merged[code][text] = value
                else:
                    merged[code].pop(text, None)
        known = {text for text, _where in app_i18n.collect(app)}
        app.translations = app_i18n.clean(merged, known=known)
        app.save(update_fields=["translations"])
        messages.success(request, _("Übersetzungen gespeichert."))
        return redirect("designer_translations", app.slug)

    only_missing = request.GET.get("fehlend") == "1"
    rows = []
    for index, (text, where) in enumerate(app_i18n.collect(app)):
        values = [(code, app_i18n.mapping(app, code).get(text, "")) for code, _name in languages]
        if only_missing and all(value for _code, value in values):
            continue
        rows.append({"index": index, "text": text, "where": where, "values": values,
                     "long": len(text) > 80 or "\n" in text})
    return render(request, "designer/translations.html", {
        "app": app, "languages": languages, "rows": rows, "only_missing": only_missing,
        "source": app_i18n.source_language(), "progress": translation_progress(app),
    })


def translation_progress(app):
    """[(Sprache, übersetzt, gesamt)] für die Übersicht der App."""
    texts = [text for text, _where in app_i18n.collect(app)]
    return [(name, sum(1 for t in texts if app_i18n.mapping(app, code).get(t)), len(texts))
            for code, name in app_i18n.target_languages()]


@designer_required
def translations_export(request, app):
    app = get_object_or_404(App, slug=app)
    response = HttpResponse(app_i18n.to_csv(app), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{app.slug}-uebersetzungen.csv"'
    return response


# ---------- Eigene Bausteine ----------

@designer_required
def custom_blocks(request):
    return render(request, "designer/blocks.html", {
        "html_blocks": CustomBlock.objects.filter(kind=CustomBlock.HTML),
        "presets": CustomBlock.objects.filter(kind=CustomBlock.PRESET),
    })


@designer_required
def custom_block_edit(request, pk=None):
    block = get_object_or_404(CustomBlock, pk=pk, kind=CustomBlock.HTML) if pk else None
    form = CustomBlockForm(request.POST or None, instance=block)
    if request.method == "POST" and form.is_valid():
        block = form.save(commit=False)
        block.kind = CustomBlock.HTML
        block.created_by = block.created_by or request.user
        block.save()
        messages.success(request, _("Baustein gespeichert. Er steht jetzt im Seiten-Designer unter „Eigene Bausteine“."))
        return redirect("designer_block_edit", block.pk)
    preview = render_custom(block, request, None, {}) if block else ""
    placeholders = ([s["key"] for s in block.setting_specs()] if block else []) + BUILTIN_PLACEHOLDERS
    # Nicht „block“ nennen: in Vorlagen ist das der Name des umgebenden {% block %}.
    return render(request, "designer/block_edit.html", {
        "form": form, "custom": block, "preview": preview, "placeholders": placeholders,
    })


@designer_required
@require_POST
def custom_block_delete(request, pk):
    get_object_or_404(CustomBlock, pk=pk).delete()
    messages.success(request, _("Baustein gelöscht."))
    return redirect("designer_blocks")


@designer_required
@require_POST
def preset_save(request):
    """Speichert einen eingestellten Baustein aus dem Seiten-Designer als Vorlage."""
    try:
        payload = json.loads(request.body)
        name = str(payload.get("name") or "").strip()[:80]
        cleaned = clean_layout([payload.get("block")])
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False}, status=400)
    if not name or not cleaned:
        return JsonResponse({"ok": False, "error": _("Bitte einen Namen für die Vorlage eintragen.")}, status=400)
    block = cleaned[0]
    label = all_types()[block["type"]].label
    custom = CustomBlock.objects.create(
        name=name, kind=CustomBlock.PRESET, created_by=request.user,
        description=_("Vorlage: %(type)s") % {"type": label},
        preset={"type": block["type"], "width": block["width"], "props": block["props"]},
    )
    return JsonResponse({"ok": True, "preset": {"id": custom.pk, "name": custom.name,
                                                "hint": custom.description, **custom.preset}})


# ---------- Skripte ----------

PYTHON_EXAMPLE = """# Beispiel: einen Baustein mit einem berechneten Wert füllen.
# Der Baustein braucht im Seiten-Designer den Namen „ergebnis“
# (zum Beispiel der Baustein „Ausgabe“ aus der Gruppe „Skripte“).
tabelle = app.table("{table}")
anzahl = tabelle.count()
ui.set("ergebnis", value=anzahl, label="Einträge in {table}")
print("Anzahl:", anzahl)
"""

JAVASCRIPT_EXAMPLE = """// Beispiel: im Browser einen Baustein füllen.
// Der Baustein braucht im Seiten-Designer den Namen „ergebnis“.
const anzahl = await app.table("{table}").count();
ui.set("ergebnis", {{value: anzahl, label: "Einträge in {table}"}});
console.log("Anzahl:", anzahl);
"""


def _example(app, language):
    entity = app.entities.first()
    table = entity.slug if entity else "tabelle"
    return (JAVASCRIPT_EXAMPLE if language == Script.JAVASCRIPT else PYTHON_EXAMPLE).format(table=table)


def _test_run(request, script):
    """Testlauf eines Python-Skripts mit einem passenden Anlass."""
    record = None
    if script.trigger == Script.SAVE:
        entity = script.entity or script.app.entities.first()
        latest = entity.records.order_by("-id").first() if entity else None
        if latest:
            from .scripting.ops import serialize

            record = serialize(latest, list(entity.fields.all()))
    return execute(script, "test", user=request.user, record=record,
                   event={"test": True, "page": script.page.slug if script.page else ""})


@designer_required
def script_edit(request, app, pk=None):
    app = get_object_or_404(App, slug=app)
    script = get_object_or_404(Script, pk=pk, app=app) if pk else None
    language = request.GET.get("sprache") if request.GET.get("sprache") in (Script.PYTHON, Script.JAVASCRIPT) else Script.PYTHON
    initial = {} if script else {"language": language, "code": _example(app, language), "trigger": Script.PAGE}
    form = ScriptForm(request.POST or None, instance=script, app=app, initial=initial)
    result = None
    if request.method == "POST" and form.is_valid():
        script = form.save(commit=False)
        script.app = app
        script.created_by = script.created_by or request.user
        script.save()
        if request.POST.get("action") == "test" and script.language == Script.PYTHON:
            result = _test_run(request, script)
            form = ScriptForm(instance=script, app=app)
        else:
            messages.success(request, _("Skript gespeichert."))
            return redirect("designer_script", app.slug, script.pk)
    runtime = None
    if script and script.language == Script.JAVASCRIPT:
        from django.conf import settings
        from django.middleware.csrf import get_token

        runtime = {"sandbox": reverse("script_sandbox"), "bridge": reverse("script_bridge", args=[app.slug]),
                   "csrf": get_token(request), "timeout": int(settings.BAUKASTEN_SCRIPT_TIMEOUT * 1000),
                   "user": python_scripts.user_info(request.user), "page": "", "show_errors": True,
                   "scripts": [], "buttons": {}}
    return render(request, "designer/script.html", {
        "app": app, "script": script, "form": form, "result": result,
        "result_ui_json": json.dumps(result.ui, ensure_ascii=False, indent=2, default=str) if result else "",
        "runs": script.runs.all()[:10] if script else [], "runtime": runtime,
        "language": script.language if script else language,
    })


@designer_required
@require_POST
def script_delete(request, app, pk):
    get_object_or_404(Script, pk=pk, app__slug=app).delete()
    messages.success(request, _("Skript gelöscht."))
    return redirect("designer_app", app)


# ---------- Datenquellen ----------

@designer_required
def query_edit(request, app, pk=None):
    app = get_object_or_404(App, slug=app)
    query = get_object_or_404(DataQuery, pk=pk, app=app) if pk else None
    form = QueryForm(request.POST or None, instance=query, app=app)
    preview, error = None, ""
    if request.method == "POST" and form.is_valid():
        query = form.save(commit=False)
        query.app = app
        query.created_by = query.created_by or request.user
        query.save()
        action = request.POST.get("action")
        if action == "test":
            try:
                preview = datasources.run(query.source, query.sql, limit=20)
            except datasources.QueryError as exc:
                error = str(exc)
            form = QueryForm(instance=query, app=app)
        elif action == "sync":
            ok = datasources.sync_and_record(query)
            (messages.success if ok else messages.error)(request, query.last_sync_message)
            return redirect("designer_query", app.slug, query.pk)
        else:
            messages.success(request, _("Abfrage gespeichert."))
            return redirect("designer_query", app.slug, query.pk)
    return render(request, "designer/query.html", {
        "app": app, "query": query, "form": form, "preview": preview, "error": error,
        "sources": datasources.describe_sources(),
    })


@designer_required
@require_POST
def query_delete(request, app, pk):
    get_object_or_404(DataQuery, pk=pk, app__slug=app).delete()
    messages.success(request, _("Abfrage gelöscht. Eine gespiegelte Tabelle bleibt mit ihren Daten erhalten."))
    return redirect("designer_app", app)
