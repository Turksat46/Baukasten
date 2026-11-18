"""Verwaltung unter /admin/, geordnet nach Apps.

Die Startseite zeigt alle Apps mit ihren Zahlen. Je App gibt es eine Datenansicht,
die jede Tabelle mit echten Spalten zeigt statt als JSON. Alle Listen lassen sich
nach App filtern.
"""
import json

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, TextField
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from .blocks import display_value, reference_labels
from .models import (ApiKey, App, AppVersion, AuditEntry, CustomBlock, DataQuery, DesignerToken, Entity, Field,
                     Page, PlatformSettings, Record, ReleaseNote, Script, ScriptRun, UnicodeJSONEncoder)

admin.site.site_header = "Baukasten – Verwaltung"
admin.site.site_title = "Baukasten"
admin.site.index_title = _("Übersicht")


# ---------- Filter ----------

class AppFilter(admin.SimpleListFilter):
    """Filter „nach App“ für alle Listen; der Pfad zur App wird je Modell angegeben."""

    title = _("App")
    parameter_name = "app"
    app_path = "app"

    def lookups(self, request, model_admin):
        return [(a.pk, a.name) for a in App.objects.all()]

    def queryset(self, request, queryset):
        return queryset.filter(**{f"{self.app_path}__pk": self.value()}) if self.value() else queryset


def app_filter(path_to_app):
    return type(f"AppFilter_{path_to_app}", (AppFilter,), {"app_path": path_to_app})


class EntityFilter(admin.SimpleListFilter):
    """Tabellen; nach Wahl einer App nur deren Tabellen."""

    title = _("Tabelle")
    parameter_name = "tabelle"

    def lookups(self, request, model_admin):
        entities = Entity.objects.select_related("app")
        if request.GET.get("app"):
            entities = entities.filter(app__pk=request.GET["app"])
        return [(e.pk, f"{e.app.name} / {e.name}") for e in entities.order_by("app__name", "name")]

    def queryset(self, request, queryset):
        return queryset.filter(entity__pk=self.value()) if self.value() else queryset


# ---------- Apps ----------

class EntityInline(admin.TabularInline):
    model = Entity
    extra = 0
    fields = ["name", "slug", "allow_create", "allow_edit", "allow_delete", "api_enabled", "entries"]
    readonly_fields = ["slug", "entries"]
    show_change_link = True

    @admin.display(description=_("Einträge"))
    def entries(self, obj):
        if not obj.pk:
            return "–"
        url = reverse("admin:builder_record_changelist") + f"?app={obj.app_id}&tabelle={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, obj.records.count())


class PageInline(admin.TabularInline):
    model = Page
    extra = 0
    fields = ["title", "slug", "show_in_nav", "order"]
    readonly_fields = ["slug"]


class ScriptInline(admin.TabularInline):
    model = Script
    extra = 0
    fields = ["name", "language", "trigger", "enabled", "last_run_at"]
    readonly_fields = ["last_run_at"]
    show_change_link = True


class QueryInline(admin.TabularInline):
    model = DataQuery
    fk_name = "app"
    extra = 0
    fields = ["name", "source", "sync_entity", "sync_interval", "last_sync_at", "last_sync_ok"]
    readonly_fields = ["last_sync_at", "last_sync_ok"]
    show_change_link = True


class ApiKeyInline(admin.TabularInline):
    model = ApiKey
    extra = 0
    fields = ["name", "prefix", "can_write", "created_by", "last_used"]
    readonly_fields = ["prefix", "created_by", "last_used"]
    can_delete = True

    def has_add_permission(self, request, obj=None):
        return False  # Schlüssel entstehen im Designer, damit der Klartext einmal angezeigt wird


class VersionInline(admin.TabularInline):
    model = AppVersion
    extra = 0
    fields = ["number", "note", "automatic", "created_by", "created_at"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(App)
class AppAdmin(admin.ModelAdmin):
    list_display = ["title", "published", "n_tables", "n_records", "n_pages", "n_scripts", "n_keys", "links"]
    list_filter = ["published"]
    search_fields = ["name", "slug", "description"]
    readonly_fields = ["slug", "created_at", "links"]
    fields = ["name", "slug", "description", "icon", "published", "groups",
              "created_by", "editors", "editor_groups", "created_at", "links"]
    filter_horizontal = ["groups", "editors", "editor_groups"]
    inlines = [EntityInline, PageInline, ScriptInline, QueryInline, ApiKeyInline, VersionInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _tables=Count("entities", distinct=True), _records=Count("entities__records", distinct=True),
            _pages=Count("pages", distinct=True), _scripts=Count("scripts", distinct=True),
            _keys=Count("api_keys", distinct=True),
        )

    @admin.display(description=_("App"), ordering="name")
    def title(self, obj):
        return f"{obj.icon} {obj.name}"

    @admin.display(description=_("Tabellen"), ordering="_tables")
    def n_tables(self, obj):
        return getattr(obj, "_tables", obj.entities.count())

    @admin.display(description=_("Einträge"), ordering="_records")
    def n_records(self, obj):
        return getattr(obj, "_records", Record.objects.filter(entity__app=obj).count())

    @admin.display(description=_("Seiten"), ordering="_pages")
    def n_pages(self, obj):
        return getattr(obj, "_pages", obj.pages.count())

    @admin.display(description=_("Skripte"), ordering="_scripts")
    def n_scripts(self, obj):
        return getattr(obj, "_scripts", obj.scripts.count())

    @admin.display(description=_("API-Schlüssel"), ordering="_keys")
    def n_keys(self, obj):
        return getattr(obj, "_keys", obj.api_keys.count())

    @admin.display(description=_("Öffnen"))
    def links(self, obj):
        if not obj.pk:
            return "–"
        return format_html(
            '<a href="{}">{}</a> · <a href="{}">{}</a> · <a href="{}">{}</a>',
            reverse("admin:builder_app_data", args=[obj.pk]), _("Daten ansehen"),
            reverse("designer_app", args=[obj.slug]), _("Designer"),
            reverse("page", args=[obj.slug]), _("App"),
        )

    def get_urls(self):
        return [path("<int:pk>/daten/", self.admin_site.admin_view(self.data_view), name="builder_app_data")] + super().get_urls()

    def data_view(self, request, pk):
        """Alle Tabellen einer App mit ihren Einträgen in Spalten."""
        if not request.user.has_perm("builder.view_record"):
            raise PermissionDenied
        app = get_object_or_404(App, pk=pk)
        tables = []
        for entity in app.entities.prefetch_related("fields"):
            fields = list(entity.fields.all())
            page = Paginator(entity.records.order_by("-id"), 50).get_page(request.GET.get(f"s_{entity.pk}"))
            refs = reference_labels(fields, page.object_list)
            rows = [{"record": r, "cells": [display_value(f, r.data.get(f.key), refs) for f in fields]}
                    for r in page.object_list]
            tables.append({"entity": entity, "fields": fields, "rows": rows, "page": page,
                           "synced": entity.synced_by.exists()})
        context = {
            **self.admin_site.each_context(request),
            "title": _("Daten von „%(app)s“") % {"app": app.name},
            "app_obj": app, "tables": tables, "opts": self.model._meta,
            "can_change_record": request.user.has_perm("builder.change_record"),
        }
        return TemplateResponse(request, "admin/builder/app_data.html", context)


# ---------- Einträge ----------

class RecordForm(forms.ModelForm):
    data = forms.JSONField(label=_("Inhalt"), encoder=UnicodeJSONEncoder,
                           widget=forms.Textarea(attrs={"rows": 16, "cols": 80, "style": "font-family: monospace"}),
                           help_text=_("Die Werte des Eintrags, je Feld unter seinem Kurznamen."))

    class Meta:
        model = Record
        fields = ["entity", "data"]


@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    form = RecordForm
    list_display = ["id", "title", "app_name", "entity_name", "updated_at", "created_by"]
    list_display_links = ["id", "title"]
    list_filter = [app_filter("entity__app"), EntityFilter, "updated_at"]
    list_select_related = ["entity", "entity__app", "created_by"]
    search_fields = ["id"]
    readonly_fields = ["fields_view", "created_by", "created_at", "updated_at"]
    fields = ["entity", "fields_view", "data", "created_by", "created_at", "updated_at"]
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("entity__fields")

    def get_search_results(self, request, queryset, search_term):
        """Sucht im gesamten Inhalt eines Eintrags (wie die Suche in Listen der Apps)."""
        if not search_term:
            return queryset, False
        found = queryset.annotate(_text=Cast("data", TextField())).filter(_text__icontains=search_term)
        if search_term.isdigit():
            found = found | queryset.filter(pk=int(search_term))
        return found, False

    @admin.display(description=_("Eintrag"))
    def title(self, obj):
        return str(obj)

    @admin.display(description=_("App"), ordering="entity__app__name")
    def app_name(self, obj):
        return obj.entity.app.name

    @admin.display(description=_("Tabelle"), ordering="entity__name")
    def entity_name(self, obj):
        return obj.entity.name

    @admin.display(description=_("Felder"))
    def fields_view(self, obj):
        if not obj.pk:
            return "–"
        fields = list(obj.entity.fields.all())
        refs = reference_labels(fields, [obj])
        rows = format_html_join("", "<tr><th>{}</th><td>{}</td></tr>",
                                ((f.label, display_value(f, obj.data.get(f.key), refs) or "–") for f in fields))
        return format_html('<table class="baukasten-fields">{}</table>', rows)


# ---------- Aufbau der Apps ----------

@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ["name", "app", "slug", "api_enabled", "n_records"]
    list_filter = [app_filter("app"), "api_enabled"]
    list_select_related = ["app"]
    search_fields = ["name", "slug"]
    readonly_fields = ["slug"]

    @admin.display(description=_("Einträge"))
    def n_records(self, obj):
        url = reverse("admin:builder_record_changelist") + f"?app={obj.app_id}&tabelle={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, obj.records.count())


@admin.register(Field)
class FieldAdmin(admin.ModelAdmin):
    list_display = ["label", "key", "type", "entity", "app_name", "required"]
    list_filter = [app_filter("entity__app"), EntityFilter, "type"]
    list_select_related = ["entity", "entity__app"]
    search_fields = ["label", "key"]
    readonly_fields = ["key"]

    @admin.display(description=_("App"), ordering="entity__app__name")
    def app_name(self, obj):
        return obj.entity.app.name


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ["title", "app", "slug", "show_in_nav", "order"]
    list_filter = [app_filter("app")]
    list_select_related = ["app"]
    search_fields = ["title", "slug"]
    readonly_fields = ["slug"]


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = ["name", "app", "language", "trigger", "enabled", "created_by", "last_run_at"]
    list_filter = [app_filter("app"), "language", "trigger", "enabled"]
    list_select_related = ["app", "created_by"]
    search_fields = ["name", "code"]
    readonly_fields = ["slug", "last_run_at", "updated_at"]


@admin.register(ScriptRun)
class ScriptRunAdmin(admin.ModelAdmin):
    list_display = ["started_at", "script", "app_name", "trigger", "ok", "duration_ms"]
    list_filter = [app_filter("script__app"), "ok", "trigger"]
    list_select_related = ["script", "script__app"]
    readonly_fields = ["script", "started_at", "trigger", "duration_ms", "ok", "log", "error"]

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("App"), ordering="script__app__name")
    def app_name(self, obj):
        return obj.script.app.name


@admin.register(DataQuery)
class DataQueryAdmin(admin.ModelAdmin):
    list_display = ["name", "app", "source", "sync_entity", "sync_interval", "last_sync_at", "last_sync_ok"]
    list_filter = [app_filter("app"), "source", "last_sync_ok"]
    list_select_related = ["app", "sync_entity"]
    search_fields = ["name", "sql"]
    readonly_fields = ["slug", "last_sync_at", "last_sync_ok", "last_sync_message"]


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "app", "prefix", "can_write", "created_by", "last_used"]
    list_filter = [app_filter("app"), "can_write"]
    list_select_related = ["app", "created_by"]
    search_fields = ["name", "prefix"]
    readonly_fields = ["app", "prefix", "created_by", "created_at", "last_used"]
    exclude = ["key_hash"]

    def has_add_permission(self, request):
        return False  # Schlüssel entstehen im Designer, damit der Klartext einmal angezeigt wird


@admin.register(ReleaseNote)
class ReleaseNoteAdmin(admin.ModelAdmin):
    """Release Notes für /ueber/. Erst mit „veröffentlicht“ für alle sichtbar."""

    list_display = ["version", "title", "released_on", "published"]
    list_editable = ["published"]
    search_fields = ["version", "title", "body"]

    def view_on_site(self, obj):
        return "/ueber/#neuigkeiten"


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    """Fachliche Einstellungen ohne Neustart. Leere Felder: Wert aus der Umgebung (settings.py)."""

    readonly_fields = ["updated_at", "updated_by"]

    def has_add_permission(self, request):
        return request.user.is_superuser and not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def changelist_view(self, request, extra_context=None):
        # Es gibt genau einen Datensatz: direkt zum Bearbeiten
        from django.shortcuts import redirect
        from django.urls import reverse

        obj, _created = PlatformSettings.objects.get_or_create(pk=1)
        return redirect(reverse("admin:builder_platformsettings_change", args=[obj.pk]))

    def get_form(self, request, obj=None, **kwargs):
        from . import platform

        form = super().get_form(request, obj, **kwargs)
        for name in platform.FALLBACK:
            field = form.base_fields.get(name)
            if field is not None:
                field.help_text = f"{field.help_text} Leer lassen = Standard aus der Umgebung: {platform.default(name)}".strip()
        return form

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """Änderungsprotokoll, auch für gelöschte Apps. Nur lesen: Einträge werden nie geändert."""

    list_display = ["created_at", "app_name", "username", "actor", "via", "action", "target_type", "target_label"]
    list_filter = ["via", "action", "target_type", "app_name"]
    search_fields = ["target_label", "username", "actor", "note", "app_slug"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # gelöscht wird nur nach Ablauf von AUDIT_RETENTION_DAYS


@admin.register(DesignerToken)
class DesignerTokenAdmin(admin.ModelAdmin):
    """KI-Zugänge zum Designer: Verwalter können fremde Zugänge im Notfall löschen."""

    list_display = ["name", "user", "prefix", "created_at", "last_used"]
    list_select_related = ["user"]
    search_fields = ["name", "prefix", "user__username"]
    readonly_fields = ["user", "prefix", "created_at", "last_used"]
    exclude = ["key_hash"]

    def has_add_permission(self, request):
        return False  # entstehen auf der Profilseite, damit der Klartext einmal angezeigt wird


@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display = ["app", "number", "note", "automatic", "created_by", "created_at"]
    list_filter = [app_filter("app"), "automatic"]
    list_select_related = ["app", "created_by"]
    readonly_fields = ["app", "number", "automatic", "created_by", "created_at", "snapshot_view"]
    exclude = ["snapshot"]

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("Inhalt"))
    def snapshot_view(self, obj):
        return format_html("<pre style='max-height:30em;overflow:auto'>{}</pre>",
                           json.dumps(obj.snapshot, ensure_ascii=False, indent=2))


@admin.register(CustomBlock)
class CustomBlockAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "description", "created_by", "created_at"]
    list_filter = ["kind"]
    search_fields = ["name", "description"]
    readonly_fields = ["slug"]
