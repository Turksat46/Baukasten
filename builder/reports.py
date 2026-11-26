"""Baustein „Berichte-Feed“: Einträge mit formatiertem Text als Zeitleiste, neueste zuerst.

Gedacht für Berichte, die n8n-Agenten, Teams-Workflows oder Copilot über den Eingang
(api.inbox) ablegen. Ein optionales Quellfeld (z. B. „agent“) erscheint als Plakette und
als Schnellfilter; die Filterleiste und andere Bausteine derselben Tabelle wirken ebenfalls.
"""
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from . import app_i18n, policy
from .blocks import (_entity, _groups, display_value, filter_param, filtered, reference_labels, register,
                     rich_value)
from .models import Field
from .page_path import page_url


def _pick(entity, key, types):
    fields = [f for f in entity.fields.all() if f.type in types]
    return next((f for f in fields if f.key == key), None) if key else (fields[0] if fields else None)


def _when(moment):
    local = timezone.localtime(moment)
    today = timezone.localdate()
    if local.date() == today:
        return gettext("heute, %(zeit)s") % {"zeit": date_format(local, "TIME_FORMAT")}
    if (today - local.date()).days == 1:
        return gettext("gestern, %(zeit)s") % {"zeit": date_format(local, "TIME_FORMAT")}
    return date_format(local, "SHORT_DATETIME_FORMAT")


def prep_report_feed(request, app, block):
    props, bid = block["props"], block["id"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für den Berichte-Feed ist keine Tabelle ausgewählt.")}
    content = _pick(entity, props.get("field"), (Field.HTML,))
    if content is None:
        return {"error": gettext("Der Berichte-Feed braucht ein Feld vom Typ „Formatierter Text (HTML)“.")}
    title_field = _pick(entity, props.get("title_field"), (Field.TEXT,)) if props.get("title_field") else \
        next((f for f in entity.fields.all() if f.type == Field.TEXT), None)
    source = _pick(entity, props.get("source_field"), (Field.TEXT, Field.CHOICE, Field.REFERENCE)) \
        if props.get("source_field") else None

    records = filtered(request, entity).order_by("-created_at", "-id")
    size = min(max(int(props.get("page_size") or 10), 1), 50)
    page_obj = Paginator(records, size).get_page(request.GET.get(f"p_{bid}"))
    items = list(page_obj.object_list)
    refs = reference_labels([source] if source else [], items)
    reports = [{
        "record": r,
        "title": display_value(title_field, r.data.get(title_field.key)) if title_field else "",
        "source": display_value(source, r.data.get(source.key), refs) if source else "",
        "when": _when(r.created_at),
        "iso": r.created_at.isoformat(),
        "body": rich_value(content, r.data.get(content.key)),
    } for r in items]

    chips = []
    if source is not None:
        param = filter_param(entity, source)
        current = request.GET.get(param, "")
        base = request.GET.copy()
        base.pop(param, None)
        base.pop(f"p_{bid}", None)
        chips.append({"label": gettext("Alle"), "href": "?" + base.urlencode(), "active": not current})
        for label, count, value in _groups(entity, source, limit=12):
            if value is None:
                continue
            query = base.copy()
            query[param] = value
            chips.append({"label": label, "count": count, "href": "?" + query.urlencode(),
                          "active": current == value})
    def page_href(number):
        query = request.GET.copy()
        query[f"p_{bid}"] = number
        return "?" + query.urlencode()

    return {
        "entity": entity, "reports": reports, "page_obj": page_obj, "chips": chips,
        "newer_href": page_href(page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "older_href": page_href(page_obj.next_page_number()) if page_obj.has_next() else "",
        "source_label": app_i18n.t(source.label) if source else "",
        "edit": policy.darf(request.user, policy.AENDERN, entity),
        "next": page_url(request),
        "inbox_url": request.build_absolute_uri(reverse("api_inbox", args=[app.slug, entity.slug]))
        if entity.api_enabled else "",
    }


register("report_feed", _("Berichte-Feed"), "📰", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "field", "label": _("Inhalt (Formatierter Text; leer: erstes solches Feld)"), "type": "field"},
    {"key": "title_field", "label": _("Überschrift (optional; leer: erstes Textfeld)"), "type": "field"},
    {"key": "source_field", "label": _("Quelle, z. B. Agent (optional, mit Schnellfilter)"), "type": "field"},
    {"key": "page_size", "label": _("Berichte pro Seite"), "type": "number", "default": 10},
], prep_report_feed, "Daten", _("Berichte von n8n, Teams-Workflows oder Copilot als Zeitleiste"))
