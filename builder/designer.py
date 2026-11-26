"""Designer: Apps, Tabellen, Felder, Seiten, eigene Bausteine und API-Zugänge bearbeiten."""
import csv
import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST

from . import app_i18n, audit, hooks, platform
from .blocks import (BUILTIN_PLACEHOLDERS, all_types, clean_layout, designer_config, make_block,
                     render_custom_report, render_layout)
from .sanitize import sanitize_html_report
from . import datasources
from .forms import (ApiKeyForm, AppForm, AutomationForm, AutomationScriptForm, CustomBlockForm, EntityForm,
                    FieldForm, NewAppForm, NewEntityForm, NewPageForm, QueryForm, ScriptForm)
from . import versions
from .models import (ApiKey, App, AppVersion, CustomBlock, DataQuery, Entity, Field, Page, Script, ScriptRun,
                     can_automate, can_design)
from .scripting import python as python_scripts
from .scripting import schedule, worker
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
        audit.log("share", "app", app=app, target_id=app.pk, label=app.name, note="App übernommen (Eigentümer/in)")
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
        elif app.is_automation and not can_automate(user):
            messages.error(request, _("%(name)s darf keine Automatisierungen bearbeiten (Gruppe „Automatisierer“ fehlt).")
                           % {"name": user.get_username()})
        else:
            app.editors.add(user)
            audit.log("share", "app", app=app, target_id=app.pk, label=app.name,
                      note=f"Mitbearbeiter/in hinzugefügt: {user.get_username()}")
            messages.success(request, _("%(name)s darf die App jetzt bearbeiten.") % {"name": user.get_username()})
    elif action == "remove_user":
        for person in app.editors.filter(pk=request.POST.get("user")):
            app.editors.remove(person)
            audit.log("share", "app", app=app, target_id=app.pk, label=app.name,
                      note=f"Mitbearbeiter/in entfernt: {person.get_username()}")
        messages.success(request, _("Mitbearbeiter entfernt."))
    elif action == "add_group":
        group = Group.objects.filter(pk=request.POST.get("group")).first()
        if group:
            app.editor_groups.add(group)
            audit.log("share", "app", app=app, target_id=app.pk, label=app.name,
                      note=f"Mitbearbeiter-Gruppe hinzugefügt: {group.name}")
            messages.success(request, _("Designer in der Gruppe „%(name)s“ dürfen die App jetzt bearbeiten.") % {"name": group.name})
    elif action == "remove_group":
        for group in app.editor_groups.filter(pk=request.POST.get("group")):
            app.editor_groups.remove(group)
            audit.log("share", "app", app=app, target_id=app.pk, label=app.name,
                      note=f"Mitbearbeiter-Gruppe entfernt: {group.name}")
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
    from . import tutorial

    # In der Einführung ist der erste Schritt schon vorausgefüllt.
    coach = tutorial.state(request.user)
    initial = {"name": "Urlaub", "icon": "🌴"} if coach and not coach["finished"] and coach["number"] == 1 else None
    automator = can_automate(request.user)
    is_auto = request.method == "POST" and "auto-name" in request.POST
    if is_auto and not automator:
        raise PermissionDenied
    form = NewAppForm(request.POST if request.method == "POST" and not is_auto else None, initial=initial)
    auto_form = NewAppForm(request.POST if is_auto else None, prefix="auto", initial={"icon": "⚙️"}) if automator else None
    if is_auto and auto_form.is_valid():
        app = auto_form.save(commit=False)
        app.kind = App.AUTOMATION
        app.created_by = request.user
        app.save()
        return redirect("designer_app", app.slug)
    if request.method == "POST" and not is_auto and form.is_valid():
        app = form.save(commit=False)
        app.created_by = request.user
        app.save()
        Page.objects.create(app=app, title=_("Start"), layout=[
            make_block("heading", text=app.name, level="1"),
            make_block("text", text=_("Willkommen. Diese Seite lässt sich im Designer frei gestalten.")),
        ])
        return redirect("designer_app", app.slug)
    everything = list(App.editable_by(request.user).select_related("created_by").prefetch_related("scripts"))
    for item in everything:
        item.can_manage = item.user_can_manage(request.user)
    apps = [a for a in everything if not a.is_automation]
    automations = [_automation_summary(a) for a in everything if a.is_automation]
    # Welcher Reiter unter „Neu anlegen“ offen ist: nach einem Fehler der betroffene, sonst ?neu=…
    tab = request.GET.get("neu", "app")
    if is_auto:
        tab = "automation"
    if tab not in ("app", "automation", "datei") or (tab == "automation" and not automator):
        tab = "app"
    return render(request, "designer/home.html", {
        "apps": apps, "automations": automations, "form": form, "auto_form": auto_form, "tab": tab,
        "custom_count": CustomBlock.objects.count(),
        "running_total": sum(a.running for a in automations),
        "error_total": sum(a.errors for a in automations),
    })


def _automation_summary(app):
    """Kurzfassung für die Übersicht: Skripte, wie viele laufen, Fehler, nächster und letzter Lauf."""
    scripts = list(app.scripts.all())
    app.script_count = len(scripts)
    app.running = sum(1 for sc in scripts if sc.running_since)
    app.errors = 0
    for sc in scripts:
        last = sc.runs.exclude(status=ScriptRun.SKIPPED).only("status", "ok").first()
        if (last and last.state in (ScriptRun.ERROR, ScriptRun.ABORTED)) or (
                sc.trigger == Script.CONTINUOUS and sc.failures):
            app.errors += 1
    planned = [sc.next_run_at for sc in scripts if sc.enabled and sc.next_run_at and sc.trigger in schedule.TIMED]
    app.next_run = min(planned) if planned else None
    app.continuous = sum(1 for sc in scripts if sc.trigger == Script.CONTINUOUS and sc.enabled)
    runs = [sc.last_run_at for sc in scripts if sc.last_run_at]
    app.last_run = max(runs) if runs else None
    return app


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
    except versions.AutomationNotAllowed as exc:
        messages.error(request, str(exc))
        return redirect("designer_home")
    except versions.InvalidSnapshot as exc:
        messages.error(request, _("Die Datei ist keine gültige App-Datei.") + " " + str(exc))
        return redirect("designer_home")
    except (ValueError, UnicodeDecodeError):
        messages.error(request, _("Die Datei ist keine gültige App-Datei."))
        return redirect("designer_home")
    messages.success(request, _("App „%(name)s“ importiert. Sie ist noch ein Entwurf.") % {"name": app.name})
    for note in getattr(app, "import_notes", []):
        messages.warning(request, note)
    return redirect("designer_app", app.slug)


@designer_required
def app_detail(request, app):
    app = get_object_or_404(App, slug=app)
    SettingsForm = AutomationForm if app.is_automation else AppForm
    form = SettingsForm(instance=app, prefix="app")
    entity_form = NewEntityForm(prefix="entity")
    page_form = NewPageForm(prefix="page")
    key_form = ApiKeyForm(prefix="key")
    new_key = None
    if request.method == "POST":
        kind = request.POST.get("kind")
        if kind == "app":
            form = SettingsForm(request.POST, instance=app, prefix="app")
            groups_before = sorted(app.groups.values_list("name", flat=True))
            if form.is_valid():
                form.save()
                groups_after = sorted(app.groups.values_list("name", flat=True))
                if groups_after != groups_before:  # Nutzergruppen (M2M) erfassen die Signale nicht
                    audit.log("share", "app", app=app, target_id=app.pk, label=app.name,
                              changes={"groups": [", ".join(groups_before) or "alle", ", ".join(groups_after) or "alle"]},
                              note="Nutzergruppen geändert")
                messages.success(request, _("Einstellungen gespeichert."))
                return redirect("designer_app", app.slug)
        elif kind == "entity":
            entity_form = NewEntityForm(request.POST, prefix="entity")
            if entity_form.is_valid():
                entity = entity_form.save(commit=False)
                entity.app = app
                entity.save()
                Field.objects.create(entity=entity, label=_("Bezeichnung"), required=True)
                return redirect("designer_entity", app.slug, entity.pk)
        elif kind == "page" and not app.is_automation:
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
    extra = {}
    if app.is_automation:
        extra = {"automations": [_automation_row(sc) for sc in app.scripts.all()],
                 "webhook_base": request.build_absolute_uri(reverse("api_describe", args=[app.slug])) + "ausloesen/"}
    version_list = list(app.versions.select_related("created_by")[:30])
    if version_list:
        current_snap = versions.snapshot(app)
        for v in version_list:
            v.changes = versions.diff(current_snap, v.snapshot)
    return render(request, "designer/automation.html" if app.is_automation else "designer/app.html", {
        **extra,
        "audit_recent": recent_audit(app),
        "app": app, "form": form, "entity_form": entity_form, "page_form": page_form,
        "entities": entities, "pages": app.pages.all(),
        "key_form": key_form, "api_keys": app.api_keys.all(), "new_key": new_key,
        "api_base": request.build_absolute_uri(reverse("api_describe", args=[app.slug])),
        "api_example": request.build_absolute_uri(reverse("api_collection", args=[app.slug, api_entity.slug])) if api_entity else "",
        "api_endpoints": sorted(hooks.API_ENDPOINTS),
        "versions": version_list,
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
    try:
        _data, notes = versions.upgrade(version.snapshot)
        kept = versions.restore(version, request.user)
    except versions.InvalidSnapshot as exc:
        messages.error(request, _("Diese Version lässt sich nicht wiederherstellen: %(error)s") % {"error": exc})
        return redirect("designer_app", app)
    for note in notes:
        messages.warning(request, note)
    messages.success(request, _("Version %(number)s wiederhergestellt. Der vorherige Stand wurde als neue Version gesichert.") % {"number": version.number})
    if kept:
        messages.success(request, _("Diese Tabellen gab es in der Version noch nicht; sie bleiben mit ihren Daten erhalten: %(names)s") % {"names": ", ".join(kept)})
    return redirect("designer_app", app)


@designer_required
@require_POST
def version_upload(request, app):
    """Eine heruntergeladene Version (Datei) in diese App einspielen, auch aus älteren Baukasten-Versionen."""
    app = get_object_or_404(App, slug=app)
    upload = request.FILES.get("file")
    if not upload or upload.size > 5 * 1024 * 1024:
        messages.error(request, _("Bitte eine heruntergeladene Version auswählen (höchstens 5 MB)."))
        return redirect(reverse("designer_app", args=[app.slug]) + "#versionen")
    try:
        data = json.loads(upload.read().decode("utf-8"))
        backup, kept, notes = versions.restore_from_file(app, data, request.user, upload.name[:100])
    except versions.InvalidSnapshot as exc:
        messages.error(request, _("Die Datei lässt sich nicht einspielen: %(error)s") % {"error": exc})
        return redirect(reverse("designer_app", args=[app.slug]) + "#versionen")
    except (ValueError, UnicodeDecodeError):
        messages.error(request, _("Die Datei ist keine gültige App-Datei."))
        return redirect(reverse("designer_app", args=[app.slug]) + "#versionen")
    messages.success(request, _("Datei eingespielt. Der vorherige Stand ist als Version %(number)s gesichert.")
                     % {"number": backup.number})
    for note in notes:
        messages.warning(request, note)
    if kept:
        messages.success(request, _("Diese Tabellen gab es in der Datei nicht; sie bleiben mit ihren Daten erhalten: %(names)s")
                         % {"names": ", ".join(kept)})
    return redirect(reverse("designer_app", args=[app.slug]) + "#versionen")


@designer_required
def version_download(request, app, pk):
    version = get_object_or_404(AppVersion, pk=pk, app__slug=app)
    response = HttpResponse(json.dumps(version.snapshot, ensure_ascii=False, indent=2),
                            content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{app}-v{version.number}.json"'
    return response


@designer_required
@require_POST
def app_clone(request, app):
    """Dupliziert den Aufbau einer App (Tabellen, Felder, Seiten, Skripte, Abfragen) als neuen Entwurf."""
    source = get_object_or_404(App, slug=app)
    if source.is_automation and not can_automate(request.user):
        raise PermissionDenied
    snap = versions.snapshot(source)
    copy_name = _("%(name)s (Kopie)") % {"name": source.name}
    cloned = versions.import_app(snap, request.user, name_override=copy_name)
    messages.success(
        request,
        _("App „%(name)s“ wurde als Entwurf dupliziert (ohne Datensätze).") % {"name": cloned.name},
    )
    return redirect("designer_app", cloned.slug)


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
    field_form = FieldForm(app=app, entity=entity, prefix="field")
    if request.method == "POST":
        if request.POST.get("kind") == "entity":
            form = EntityForm(request.POST, instance=entity, prefix="entity")
            if form.is_valid():
                before = _entity_rights(entity)
                form.save()
                after = _entity_rights(entity)
                if after != before:  # M2M erfassen die Signale nicht
                    audit.log("share", "entity", app=app, target_id=entity.pk, label=entity.name,
                              changes={k: [before[k], after[k]] for k in after if after[k] != before[k]},
                              note="Rechte der Tabelle geändert")
                messages.success(request, _("Tabelle gespeichert."))
                return redirect("designer_entity", app.slug, entity.pk)
        else:
            field_form = FieldForm(request.POST, app=app, entity=entity, prefix="field")
            if field_form.is_valid():
                field = field_form.save(commit=False)
                field.entity = entity
                field.save()
                return redirect("designer_entity", app.slug, entity.pk)
    return render(request, "designer/entity.html", {
        "app": app, "entity": entity, "form": form, "field_form": field_form,
        "fields": entity.fields.all(), "record_count": entity.records.count(),
    })


def _entity_rights(entity):
    return {"read_groups": ", ".join(sorted(entity.read_groups.values_list("name", flat=True))) or "alle",
            "write_groups": ", ".join(sorted(entity.write_groups.values_list("name", flat=True))) or "alle"}


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
            if not isinstance(payload, dict):
                raise ValueError("Payload muss ein JSON-Objekt sein.")
            raw_layout = payload.get("layout")
            clean_layout(raw_layout)  # nur prüfen; übernommen wird unten mit dem gespeicherten Stand
        except (ValueError, AttributeError):
            return JsonResponse({"ok": False, "error": _("Ungültige Daten.")}, status=400)
        has_version = "version" in payload
        expected_version = None
        if has_version:
            raw_version = payload.get("version")
            if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 1:
                return JsonResponse({"ok": False, "error": _("Ungültige Daten.")}, status=400)
            expected_version = raw_version
        with transaction.atomic():
            page = get_object_or_404(Page.objects.select_for_update(), pk=pk, app=app)
            if has_version and expected_version != page.version:
                return JsonResponse({
                    "ok": False,
                    "conflict": True,
                    "version": page.version,
                    "error": _("Diese Seite wurde inzwischen von jemand anderem gespeichert. Bitte lade die Seite neu, um keine Änderungen zu überschreiben."),
                }, status=409)
            # Gegen den gesperrten, gespeicherten Stand abgleichen: Bausteine und Einstellungen, die
            # dieser Baukasten nicht kennt, bleiben erhalten (Rückwärtskompatibilität bei Updates).
            page.layout = clean_layout(raw_layout, previous=page.layout)
            title = str(payload.get("title") or "").strip()[:80]
            if title:
                page.title = title
            page.show_in_nav = bool(payload.get("show_in_nav", True))
            page.public = bool(payload.get("public", page.public))
            page.save()
            if isinstance(payload.get("groups"), list):
                _save_page_groups(app, page, payload["groups"])
        # baukasten_version: Der Designer vergleicht sie mit dem Stand beim Öffnen und bittet nach
        # einem Update ums Neuladen (neue Bausteine und Einstellungen).
        return JsonResponse({"ok": True, "layout": page.layout, "version": page.version,
                             "baukasten_version": settings.BAUKASTEN_VERSION})
    return render(request, "designer/page.html", {
        "app": app, "page": page, "config": designer_config(app, page),
        "all_groups": Group.objects.order_by("name"),
        "page_group_ids": set(page.groups.values_list("pk", flat=True)),
    })


def _save_page_groups(app, page, raw):
    """Wer die Seite sehen darf. Nur bekannte Gruppen; Änderungen kommen ins Protokoll (M2M erfassen
    die Signale nicht)."""
    ids = {int(v) for v in raw if str(v).isdigit()}
    before = sorted(page.groups.values_list("name", flat=True))
    page.groups.set(Group.objects.filter(pk__in=ids))
    after = sorted(page.groups.values_list("name", flat=True))
    if after != before:
        audit.log("share", "page", app=app, target_id=page.pk, label=page.title,
                  changes={"groups": [", ".join(before) or "alle", ", ".join(after) or "alle"]},
                  note="Sichtbarkeit der Seite geändert")


@designer_required
@require_POST
def page_preview(request, app, pk):
    """Rendert ein noch nicht gespeichertes Layout für die Arbeitsfläche des Designers."""
    app = get_object_or_404(App, slug=app)
    page = get_object_or_404(Page, pk=pk, app=app)
    try:
        layout = clean_layout(json.loads(request.body).get("layout"), previous=page.layout)
    except (ValueError, AttributeError):
        return JsonResponse({"ok": False}, status=400)
    blocks = render_layout(request, app, page, layout, unknown=True)
    return JsonResponse({"ok": True, "blocks": {b["id"]: b["html"] for b in blocks}})


@designer_required
@require_POST
def page_delete(request, app, pk):
    get_object_or_404(Page, pk=pk, app__slug=app).delete()
    messages.success(request, _("Seite gelöscht."))
    return redirect("designer_app", app)


# ---------- Einführung „Deine erste App“ ----------

@designer_required
@require_POST
def tutorial_start(request):
    from . import tutorial

    tutorial.start(request.user)
    messages.success(request, _("Los geht's! Der Begleiter unten rechts führt dich Schritt für Schritt."))
    return redirect("designer_home")


@login_required
@require_POST
def tutorial_stop(request):
    from . import tutorial

    tutorial.stop(request.user)
    messages.success(request, _("Einführung beendet. Du kannst sie im Designer jederzeit neu starten."))
    return redirect(request.POST.get("next") if url_has_allowed_host_and_scheme(
        request.POST.get("next"), allowed_hosts={request.get_host()}) else "home")


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
        raw_html = request.POST.get("html") or ""
        _clean_html, stripped = sanitize_html_report(raw_html)
        block = form.save(commit=False)
        block.kind = CustomBlock.HTML
        block.created_by = block.created_by or request.user
        block.save()
        messages.success(request, _("Baustein gespeichert. Er steht jetzt im Seiten-Designer unter „Eigene Bausteine“."))
        if stripped:
            messages.warning(request, _("Sicherheitsbereinigung: ") + " ".join(stripped))
        return redirect("designer_block_edit", block.pk)
    preview, warnings = render_custom_report(block, request, None, {}) if block else ("", [])
    placeholders = ([s["key"] for s in block.setting_specs()] if block else []) + BUILTIN_PLACEHOLDERS
    # Nicht „block“ nennen: in Vorlagen ist das der Name des umgebenden {% block %}.
    return render(request, "designer/block_edit.html", {
        "form": form, "custom": block, "preview": preview, "placeholders": placeholders, "warnings": warnings,
    })


@designer_required
@require_POST
def custom_block_preview(request):
    """Live-Vorschau für einen noch nicht gespeicherten HTML-Baustein."""
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    temp = CustomBlock(
        name=str(payload.get("name") or "Vorschau")[:80],
        html=str(payload.get("html") or ""),
        settings=str(payload.get("settings") or ""),
    )
    preview, warnings = render_custom_report(temp, request, None, {})
    placeholders = [s["key"] for s in temp.setting_specs()] + BUILTIN_PLACEHOLDERS
    return JsonResponse({
        "ok": True,
        "html": str(preview),
        "placeholders": placeholders,
        "warnings": warnings,
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
    if app.is_automation:
        return automation_script_edit(request, app, script)
    language = request.GET.get("sprache") if request.GET.get("sprache") in (Script.PYTHON, Script.JAVASCRIPT) else Script.PYTHON
    initial = {} if script else {"language": language, "code": _example(app, language), "trigger": Script.PAGE}
    form = ScriptForm(request.POST or None, instance=script, app=app, initial=initial)
    result = None
    status_code = 200
    if request.method == "POST":
        expected_version = request.POST.get("expected_version", "").strip()
        if script and expected_version and expected_version != script.updated_at.isoformat():
            form.add_error(
                None,
                _("Konflikt: Dieses Skript wurde zwischenzeitlich von jemand anderem gespeichert. Bitte lade die Seite neu, um keine Änderungen zu überschreiben."),
            )
            status_code = 409
        elif form.is_valid():
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
        from django.middleware.csrf import get_token

        runtime = {"sandbox": reverse("script_sandbox"), "bridge": reverse("script_bridge", args=[app.slug]),
                   "csrf": get_token(request), "timeout": int(platform.value("script_timeout") * 1000),
                   "user": python_scripts.user_info(request.user), "page": "", "show_errors": True,
                   "scripts": [], "buttons": {}}
    return render(request, "designer/script.html", {
        "app": app, "script": script, "form": form, "result": result,
        "result_ui_json": json.dumps(result.ui, ensure_ascii=False, indent=2, default=str) if result else "",
        "runs": script.runs.all()[:10] if script else [], "runtime": runtime,
        "language": script.language if script else language,
    }, status=status_code)


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


# ---------- Automatisierungen ----------

AUTOMATION_EXAMPLE = """# Automatisierung: echtes Python im Hintergrund. Alle Bibliotheken aus
# requirements-automation.in stehen zur Verfügung (z. B. requests).
from datetime import datetime

import requests

print("Start:", datetime.now().isoformat(timespec="seconds"), "Anlass:", event["trigger"])

# Beispiel: Daten abholen und in einer Tabelle der Automatisierung festhalten.
# antwort = requests.get("https://example.com/api/status", timeout=30)
# antwort.raise_for_status()
# app.table("{table}").create(bezeichnung=antwort.json()["status"])

# Zugangsdaten nie in den Code schreiben, sondern als Geheimnis einrichten lassen:
# token = secret("MEIN_TOKEN")
print("Fertig.")
"""

STATE_LABELS = {
    "running": gettext_lazy("läuft"), "requested": gettext_lazy("startet gleich"), "off": gettext_lazy("aus"),
    "error": gettext_lazy("Fehler, Neustart geplant"), "waiting": gettext_lazy("wartet"),
}


def _state_label(state):
    return str(STATE_LABELS[state])


def _automation_row(script):
    script.state = worker.status(script)
    script.state_label = _state_label(script.state)
    script.plan = schedule.describe(script)
    script.last = script.runs.exclude(status=ScriptRun.SKIPPED).first()
    if script.trigger == Script.CONTINUOUS:
        script.can_start, script.can_stop = not script.enabled, script.enabled or script.state == "running"
    else:
        script.can_stop = script.state in ("running", "requested")
        script.can_start = not script.can_stop
    return script


def _run_json(run):
    if run is None:
        return None
    return {"id": run.pk, "status": run.state, "label": run.get_status_display() if run.status else (_("ok") if run.ok else _("Fehler")),
            "started": run.started_at.isoformat(), "finished": run.finished_at.isoformat() if run.finished_at else None,
            "duration_ms": run.duration_ms, "trigger": run.trigger, "log": run.log, "error": run.error}


def _script_json(script):
    _automation_row(script)
    return {"id": script.pk, "state": script.state, "label": script.state_label, "plan": script.plan,
            "running_since": script.running_since.isoformat() if script.running_since else None,
            "next_run_at": script.next_run_at.isoformat() if script.next_run_at and script.enabled else None,
            "requested_at": (script.request_event or {}).get("requested_at") if script.run_requested else None,
            "can_start": script.can_start, "can_stop": script.can_stop,
            "last": _run_json(script.last)}


def _automation_app(slug):
    app = get_object_or_404(App, slug=slug)
    if not app.is_automation:
        raise PermissionDenied
    return app


def start_script(script, user):
    """Knopf „Jetzt starten“: Dauerläufer einschalten, sonst einen Lauf anfordern. Gibt die Meldung zurück."""
    if script.trigger == Script.CONTINUOUS:
        Script.objects.filter(pk=script.pk).update(enabled=True, next_run_at=None, failures=0, stop_requested=False)
        audit.log("start", "script", app=script.app, target_id=script.pk, label=script.name, note="eingeschaltet")
        return True, _("„%(name)s“ ist eingeschaltet und startet in wenigen Sekunden.") % {"name": script.name}
    if worker.request_run(script, Script.MANUAL, user=user.get_username()):
        audit.log("start", "script", app=script.app, target_id=script.pk, label=script.name)
        return True, _("„%(name)s“ startet in wenigen Sekunden.") % {"name": script.name}
    return False, _("Für „%(name)s“ wartet schon ein Start.") % {"name": script.name}


def _back(request, app):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect("designer_app", app.slug)


@designer_required
@require_POST
def script_start(request, app, pk):
    app = _automation_app(app)
    script = get_object_or_404(Script, pk=pk, app=app)
    ok, text = start_script(script, request.user)
    (messages.success if ok else messages.warning)(request, text)
    return _back(request, app)


@designer_required
@require_POST
def script_stop(request, app, pk):
    """Laufenden Lauf stoppen; Dauerläufer zusätzlich ausschalten, sonst startet er neu."""
    app = _automation_app(app)
    script = get_object_or_404(Script, pk=pk, app=app)
    updates = {"run_requested": False, "request_event": None}
    if script.running_since:
        updates["stop_requested"] = True
    if script.trigger == Script.CONTINUOUS:
        updates["enabled"] = False
    Script.objects.filter(pk=script.pk).update(**updates)
    audit.log("stop", "script", app=app, target_id=script.pk, label=script.name,
              note="ausgeschaltet" if script.trigger == Script.CONTINUOUS else "")
    messages.success(request, _("„%(name)s“ wird gestoppt.") % {"name": script.name} if script.running_since
                     else _("„%(name)s“ ist angehalten.") % {"name": script.name})
    return _back(request, app)


@designer_required
def automation_status(request, app):
    """Zustand aller Skripte (für die laufende Aktualisierung der Übersicht)."""
    app = _automation_app(app)
    return JsonResponse({"scripts": [_script_json(sc) for sc in app.scripts.all()]})


@designer_required
def script_live(request, app, pk):
    """Zustand eines Skripts mit dem Protokoll des laufenden oder letzten Laufs."""
    app = _automation_app(app)
    script = get_object_or_404(Script, pk=pk, app=app)
    return JsonResponse(_script_json(script))


PLAN_FIELDS = ("trigger", "enabled", "interval_minutes", "daily_time", "weekdays_only")


def automation_script_edit(request, app, script):
    table = app.entities.first()
    initial = {} if script else {"code": AUTOMATION_EXAMPLE.format(table=table.slug if table else "protokoll"),
                                 "trigger": Script.SCHEDULE, "interval_minutes": 15, "timeout_minutes": 30}
    before = tuple(getattr(script, f) for f in PLAN_FIELDS) if script else None
    form = AutomationScriptForm(request.POST or None, instance=script, initial=initial)
    status_code = 200
    if request.method == "POST":
        expected_version = request.POST.get("expected_version", "").strip()
        if script and expected_version and expected_version != script.updated_at.isoformat():
            form.add_error(
                None,
                _("Konflikt: Dieses Skript wurde zwischenzeitlich von jemand anderem gespeichert. Bitte lade die Seite neu, um keine Änderungen zu überschreiben."),
            )
            status_code = 409
        elif form.is_valid():
            new = script is None
            script = form.save(commit=False)
            script.app = app
            script.language = Script.PYTHON
            script.created_by = script.created_by or request.user
            changed = new or tuple(getattr(script, f) for f in PLAN_FIELDS) != before
            if changed:
                script.next_run_at = (schedule.first_run(script) if script.enabled and script.trigger in schedule.TIMED
                                      else None)
                script.failures = 0
            if new:
                script.save()
            else:
                # Nur die Felder des Formulars schreiben: Zustand des Hintergrunddienstes nicht überschreiben.
                script.save(update_fields=[*form.Meta.fields, "language", "next_run_at", "failures", "updated_at"])
            if request.POST.get("action") == "run":
                script.refresh_from_db()
                ok, text = start_script(script, request.user)
                (messages.success if ok else messages.warning)(request, text)
            else:
                messages.success(request, _("Skript gespeichert."))
            return redirect("designer_script", app.slug, script.pk)
    if script:
        _automation_row(script)
    return render(request, "designer/automation_script.html", {
        "app": app, "script": script, "form": form,
        "runs": script.runs.all()[:15] if script else [],
        "max_timeout": form.limit,
    }, status=status_code)


# ---------- Änderungsprotokoll ----------

def _audit_entries(app, params):
    from django.db.models import Q

    from .models import AuditEntry

    entries = AuditEntry.objects.filter(app=app).select_related("user")
    area = params.get("bereich", "")
    if area == "daten":
        entries = entries.filter(target_type="record")
    elif area == "aufbau":
        entries = entries.exclude(target_type="record")
    if params.get("eintrag"):
        entries = entries.filter(target_type="record", target_id=str(params["eintrag"]))
    query = params.get("q", "").strip()
    if query:
        entries = entries.filter(Q(target_label__icontains=query) | Q(username__icontains=query)
                                 | Q(actor__icontains=query) | Q(note__icontains=query))
    return entries


def _audit_labels(entry):
    entry.via_label = audit.VIA_LABELS.get(entry.via, entry.via)
    entry.action_label = audit.ACTION_LABELS.get(entry.action, entry.action)
    entry.summary = audit.describe(entry)
    entry.who = entry.username or entry.actor or audit.VIA_LABELS.get(entry.via, "")
    return entry


@designer_required
def audit_log(request, app):
    """Wer hat wann was geändert – je App, mit Filter und CSV-Export."""
    from django.core.paginator import Paginator

    app = get_object_or_404(App, slug=app)
    entries = _audit_entries(app, request.GET)
    if request.GET.get("format") == "csv":
        return _audit_csv(app, entries)
    page = Paginator(entries, 50).get_page(request.GET.get("seite"))
    for entry in page.object_list:
        _audit_labels(entry)
    params = request.GET.copy()
    params.pop("seite", None)
    return render(request, "designer/audit.html", {
        "app": app, "page_obj": page, "area": request.GET.get("bereich", ""), "query": request.GET.get("q", ""),
        "record_id": request.GET.get("eintrag", ""), "params": params.urlencode(),
        "retention": platform.value("audit_retention_days"),
    })


def _audit_csv(app, entries):
    from django.http import StreamingHttpResponse

    from .views import _csv_cell, _Echo

    writer = csv.writer(_Echo(), delimiter=";")

    def rows():
        yield "\ufeff" + writer.writerow(["Zeit", "Person", "Womit", "Weg", "Aktion", "Art", "Objekt", "Änderung",
                                            "Hinweis"])
        for entry in entries.iterator(chunk_size=500):
            _audit_labels(entry)
            yield writer.writerow([_csv_cell(v) for v in (
                timezone.localtime(entry.created_at).strftime("%Y-%m-%d %H:%M:%S"), entry.username, entry.actor,
                entry.via_label, entry.action_label, entry.target_type, entry.target_label, entry.summary, entry.note)])

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{app.slug}-protokoll.csv"'
    return response


def recent_audit(app, limit=5):
    from .models import AuditEntry

    return [_audit_labels(e) for e in AuditEntry.objects.filter(app=app).select_related("user")[:limit]]
