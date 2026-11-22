"""Bausteine, aus denen Seiten bestehen.

Jeder Baustein hat ein Schema (welche Einstellungen der Designer anbietet) und
eine prepare-Funktion, die die Daten für die Anzeige holt. Eine Seite ist eine
Liste von Bausteinen: {"id", "type", "width", "props"}.
"""
import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Avg, Count, FloatField, Sum, TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Substr, TruncMonth
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format, number_format
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from . import app_i18n, hooks
from .forms import RecordForm
from .models import CustomBlock, DataQuery, Field, Record, Script
from .sanitize import fill_placeholders, sanitize_html, sanitize_html_report
from .services import HttpNotAllowed, http_json

log = logging.getLogger(__name__)

WIDTHS = (3, 4, 6, 8, 12)
REFRESH = (0, 10, 30, 60, 300)
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
TONES = {"info", "success", "warning", "danger"}
# Was Skripte an einem Baustein setzen dürfen (Python: ui.set, JavaScript: ui.set)
TEXT_OVERRIDES = {"text", "subtitle", "title", "label", "unit", "tone", "submit_label"}


@dataclass
class BlockType:
    key: str
    label: str
    icon: str
    fields: list = field(default_factory=list)
    prepare: object = None
    category: str = "Eigene"
    hint: str = ""
    action: object = None  # fn(app, block, payload, user) für interaktive Bausteine (views.block_action)


REGISTRY = {}
CATEGORIES = [
    ("Inhalt", _("Inhalt")), ("Daten", _("Daten")), ("Planung", _("Planung")), ("Auswertung", _("Auswertung")),
    ("Navigation", _("Navigation")), ("Layout", _("Layout")), ("Anbindung", _("Anbindung")),
    ("Skripte", _("Skripte")), ("Eigene", _("Eigene Bausteine")),
]


def register(key, label, icon, fields=(), prepare=None, category="Inhalt", hint="", action=None):
    REGISTRY[key] = BlockType(key, label, icon, list(fields), prepare, category, hint, action)


def _call_hook_block(fn, request, app, props):
    import inspect

    try:
        sig = inspect.signature(fn)
        accepts_props = len(sig.parameters) >= 3 or any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values()
        )
    except (ValueError, TypeError):
        accepts_props = False
    return fn(request, app, props) if accepts_props else fn(request, app)


def all_types():
    types = dict(REGISTRY)
    for key, custom in hooks.CUSTOM_BLOCKS.items():
        fn = custom["fn"]
        types[f"x-{key}"] = BlockType(
            f"x-{key}", custom["label"], custom["icon"], custom.get("fields", []),
            lambda request, app, block, fn=fn: {"custom_html": _call_hook_block(fn, request, app, block.get("props", {}))},
            "Eigene", custom.get("hint") or _("Aus dem Ordner extensions"),
        )
    for custom in CustomBlock.objects.filter(kind=CustomBlock.HTML):
        types[f"c-{custom.slug}"] = BlockType(
            f"c-{custom.slug}", custom.name, "🧩", custom.setting_specs(),
            lambda request, app, block, custom=custom: {"custom_plain": render_custom(custom, request, app, block["props"])},
            "Eigene", custom.description,
        )
    return types


# ---------- Eigene HTML-Bausteine ----------

def render_custom_report(custom, request, app, props):
    """Setzt Einstellungen und feste Platzhalter ein und liefert (HTML, Sanitizer-Hinweise)."""
    user = request.user
    values = {spec["key"]: props.get(spec["key"], spec["default"]) for spec in custom.setting_specs()}
    values.update({
        "nutzer": (user.get_full_name() or user.get_username()) if user.is_authenticated else "",
        "app": app.name if app else "",
        "datum": date_format(timezone.localdate(), "SHORT_DATE_FORMAT"),
    })
    clean, warnings = sanitize_html_report(fill_placeholders(custom.html, values))
    return mark_safe(clean), warnings


def render_custom(custom, request, app, props):
    """Setzt Einstellungen und feste Platzhalter ein und bereinigt das Ergebnis."""
    return render_custom_report(custom, request, app, props)[0]


BUILTIN_PLACEHOLDERS = ["nutzer", "app", "datum"]


# ---------- Hilfen ----------

def _entity(app, slug):
    return app.entities.filter(slug=slug).first() if slug else None


def reference_labels(fields, records):
    ids = {
        r.data.get(f.key)
        for f in fields if f.type == Field.REFERENCE
        for r in records
    }
    ids = {i for i in ids if isinstance(i, int)}
    if not ids:
        return {}
    found = Record.objects.filter(pk__in=ids).prefetch_related("entity__fields")
    return {r.pk: str(r) for r in found}


def link_target(f, value):
    """Ziel für Felder vom Typ Link: nur http(s) oder Pfade dieser Anwendung, nie javascript: o. Ä."""
    if f.type != Field.URL or not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith(("https://", "http://")) or (value.startswith("/") and not value.startswith("//")):
        return value
    return ""


def display_value(f, value, refs=None):
    if value in (None, ""):
        return ""
    if f.type == Field.BOOL:
        return gettext("Ja") if value else gettext("Nein")
    if f.type == Field.DATE:
        try:
            return date_format(date.fromisoformat(value), "SHORT_DATE_FORMAT")
        except (TypeError, ValueError):
            return str(value)
    if f.type == Field.DECIMAL and isinstance(value, (int, float)):
        return number_format(value, decimal_pos=2, use_l10n=True, force_grouping=True)
    if f.type == Field.REFERENCE:
        return (refs or {}).get(value, f"#{value}")
    if f.type == Field.CHOICE:
        return app_i18n.t(str(value))  # gespeichert bleibt der Wert der Quellsprache
    return str(value)


# ---------- Filter aus der Adresse (Baustein „Filterleiste“) ----------

def filter_param(entity, f, suffix=""):
    """Name des Adress-Parameters, z. B. geraete.kategorie oder ausleihen.von.bis."""
    return f"{entity.slug}.{f.key}{suffix}"


def filtered(request, entity, records=None):
    """Einträge einer Tabelle, gefiltert nach den Parametern der Seite (?tabelle.feld=wert).

    Gilt für alle Bausteine derselben Tabelle auf der Seite. Text sucht enthalten, Ja/Nein
    nimmt 1/0, Datum nimmt Grenzen über .von und .bis, alles andere vergleicht genau."""
    records = entity.records.all() if records is None else records
    params = getattr(request, "GET", None)
    if not params:
        return records
    for f in entity.fields.all():
        if f.type == Field.DATE:
            low, high = params.get(filter_param(entity, f, ".von")), params.get(filter_param(entity, f, ".bis"))
            if low or high:
                records = records.annotate(**{f"_f_{f.key}": Cast(KeyTextTransform(f.key, "data"), TextField())})
                if low:
                    records = records.filter(**{f"_f_{f.key}__gte": low[:10]})
                if high:
                    records = records.filter(**{f"_f_{f.key}__lte": high[:10]})
            continue
        value = params.get(filter_param(entity, f))
        if value in (None, ""):
            continue
        if f.type == Field.BOOL:
            records = (records.filter(**{f"data__{f.key}": True}) if value in ("1", "true", "ja")
                       else records.exclude(**{f"data__{f.key}": True}))
        elif f.type in (Field.TEXT, Field.LONGTEXT, Field.EMAIL, Field.URL):
            records = (records.annotate(**{f"_f_{f.key}": KeyTextTransform(f.key, "data")})
                       .filter(**{f"_f_{f.key}__icontains": value[:200]}))
        elif f.type in (Field.NUMBER, Field.REFERENCE, Field.DECIMAL):
            try:
                number = int(value) if f.type != Field.DECIMAL else float(value)
            except ValueError:
                continue
            records = records.filter(**{f"data__{f.key}": number})
        else:
            records = records.filter(**{f"data__{f.key}": value[:200]})
    return records


# ---------- prepare-Funktionen ----------

def prep_table(request, app, block):
    props, bid = block["props"], block["id"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Liste ist keine Tabelle ausgewählt.")}
    fields = list(entity.fields.all())
    columns = [f for f in fields if f.show_in_list] or fields[:5]
    records = filtered(request, entity)
    query = request.GET.get(f"q_{bid}", "").strip()
    if query and props.get("searchable", True):
        records = records.annotate(_text=Cast("data", TextField())).filter(_text__icontains=query)
    size = min(max(int(props.get("page_size") or 20), 1), 200)
    page_obj = Paginator(records, size).get_page(request.GET.get(f"p_{bid}"))
    refs = reference_labels(columns, page_obj.object_list)
    rows = [
        {"record": r, "cells": [(app_i18n.t(f.label), display_value(f, r.data.get(f.key), refs), link_target(f, r.data.get(f.key)))
                                for f in columns]}
        for r in page_obj.object_list
    ]
    return {
        "entity": entity, "columns": columns, "rows": rows, "page_obj": page_obj,
        "query": query, "next": request.get_full_path(),
    }


def prep_form(request, app, block):
    entity = _entity(app, block["props"].get("entity"))
    if not entity:
        return {"error": gettext("Für dieses Formular ist keine Tabelle ausgewählt.")}
    if not entity.allow_create:
        return {"error": gettext("In dieser Tabelle ist das Anlegen nicht erlaubt.")}
    return {
        "entity": entity,
        "form": RecordForm(entity, prefix=block["id"]),
        "action_url": reverse("record_create", args=[app.slug, entity.slug]),
        "next": request.get_full_path(),
    }


def _number(entity, props, records=None):
    """Anzahl, Summe oder Durchschnitt einer Tabelle. Gibt (Zahl, Fehlertext) zurück."""
    records = entity.records.all() if records is None else records
    aggregate = props.get("aggregate") or "count"
    if aggregate == "count":
        return records.count(), None
    f = entity.fields.filter(key=props.get("field"), type__in=[Field.NUMBER, Field.DECIMAL]).first()
    if not f:
        return None, gettext("Summe und Durchschnitt brauchen ein Zahlenfeld.")
    expr = Cast(KeyTextTransform(f.key, "data"), FloatField())
    func = Sum if aggregate == "sum" else Avg
    return records.aggregate(v=func(expr))["v"] or 0, None


def _format_number(value):
    if isinstance(value, int):
        return number_format(value, force_grouping=True, use_l10n=True)
    return number_format(value, decimal_pos=2, use_l10n=True, force_grouping=True)


def _groups(entity, f, limit=12, records=None):
    """Zählt Einträge je Wert eines Feldes: Liste von (Beschriftung, Anzahl), häufigste zuerst."""
    records = entity.records.all() if records is None else records
    rows = (
        records.annotate(v=KeyTextTransform(f.key, "data"))
        .values("v").annotate(c=Count("id")).order_by("-c")[:limit]
    )
    result = []
    for row in rows:
        raw = row["v"]
        if raw in (None, ""):
            label = gettext("(leer)")
        elif f.type == Field.BOOL:
            label = gettext("Ja") if str(raw).lower() in ("1", "true") else gettext("Nein")
        elif f.type == Field.REFERENCE and str(raw).isdigit():
            label = str(Record.objects.filter(pk=int(raw)).first() or f"#{raw}")
        else:
            label = display_value(f, raw)
        result.append((label, row["c"]))
    return result


def _entity_and_field(app, props):
    entity = _entity(app, props.get("entity"))
    f = entity.fields.filter(key=props.get("field")).first() if entity else None
    return entity, f


def prep_stat(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Kennzahl ist keine Tabelle ausgewählt.")}
    value, error = _number(entity, props, filtered(request, entity))
    return {"error": error} if error else {"value": _format_number(value)}


def prep_progress(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diesen Fortschritt ist keine Tabelle ausgewählt.")}
    value, error = _number(entity, props, filtered(request, entity))
    if error:
        return {"error": error}
    target = max(int(props.get("target") or 0), 0)
    if not target:
        return {"error": gettext("Für diesen Fortschritt fehlt der Zielwert.")}
    return {
        "value": _format_number(value), "target": _format_number(target),
        "percent": min(round(100 * value / target), 100), "percent_label": round(100 * value / target),
    }


def prep_chart(request, app, block):
    from .datascience import _filter_href

    entity, f = _entity_and_field(app, block["props"])
    if not f:
        return {"error": gettext("Für dieses Diagramm fehlen Tabelle und Feld.")}
    records = filtered(request, entity)
    groups = _groups(entity, f, records=records)
    top = max((count for _, count in groups), default=0)
    total = records.count()
    param = filter_param(entity, f)
    return {"bars": [
        {"label": label, "count": count,
         "percent": round(100 * count / top) if top else 0,
         "share": round(100 * count / total) if total else 0,
         "href": _filter_href(request, param, label)}
        for label, count in groups
    ]}


def prep_donut(request, app, block):
    from .datascience import _filter_href

    entity, f = _entity_and_field(app, block["props"])
    if not f:
        return {"error": gettext("Für dieses Kreisdiagramm fehlen Tabelle und Feld.")}
    records = filtered(request, entity)
    total = records.count()
    groups = _groups(entity, f, limit=5, records=records)
    rest = total - sum(count for _, count in groups)
    if rest > 0:
        groups.append((gettext("Sonstige"), rest))
    param = filter_param(entity, f)
    segments, done = [], 0.0
    for index, (label, count) in enumerate(groups, start=1):
        share = 100 * count / total if total else 0
        segments.append({
            "label": label, "count": count, "share": round(share), "index": index,
            "dash": f"{share:.2f} {100 - share:.2f}", "offset": f"{125 - done:.2f}",
            "href": _filter_href(request, param, label) if label != gettext("Sonstige") else "",
        })
        done += share
    return {"segments": segments, "total": _format_number(total)}


def prep_timeline(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diesen Verlauf ist keine Tabelle ausgewählt.")}
    f = entity.fields.filter(key=props.get("field"), type=Field.DATE).first()
    if f:
        rows = (filtered(request, entity).annotate(m=Substr(KeyTextTransform(f.key, "data"), 1, 7))
                .values("m").annotate(c=Count("id")))
        counts = {row["m"]: row["c"] for row in rows if row["m"]}
    else:
        rows = filtered(request, entity).annotate(m=TruncMonth("created_at")).values("m").annotate(c=Count("id"))
        counts = {row["m"].strftime("%Y-%m"): row["c"] for row in rows if row["m"]}
    today = timezone.localdate()
    months = []
    year, month = today.year, today.month
    for _ in range(min(max(int(props.get("months") or 12), 3), 24)):
        months.append((year, month))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    months.reverse()
    values = [counts.get(f"{y}-{m:02d}", 0) for y, m in months]
    top = max(values, default=0)
    return {
        "columns": [
            {"label": date_format(date(y, m, 1), "M"), "title": date_format(date(y, m, 1), "F Y"), "count": value,
             "percent": round(100 * value / top) if top else 0, "new_year": m == 1}
            for (y, m), value in zip(months, values)
        ],
        "basis": f.label if f else gettext("Erfassungsdatum"),
    }


LINE_PERIODS = {"day": (7, 90), "week": (4, 52), "month": (3, 36)}  # (min, max) Anzahl Zeitabschnitte


def _line_buckets(period, count, today):
    """Startdaten der letzten `count` Zeitabschnitte, ältester zuerst, und eine Funktion Datum → Abschnitt."""
    if period == "day":
        starts = [today - timedelta(days=i) for i in range(count)]
        key = lambda d: d  # noqa: E731
    elif period == "week":
        monday = today - timedelta(days=today.weekday())
        starts = [monday - timedelta(weeks=i) for i in range(count)]
        key = lambda d: d - timedelta(days=d.weekday())  # noqa: E731
    else:
        starts, year, month = [], today.year, today.month
        for _ in range(count):
            starts.append(date(year, month, 1))
            year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        key = lambda d: d.replace(day=1)  # noqa: E731
    return list(reversed(starts)), key


def _line_label(period, start):
    if period == "day":
        return date_format(start, gettext("d.m.")), date_format(start, "SHORT_DATE_FORMAT")
    if period == "week":
        week = start.isocalendar()[1]
        return gettext("KW %(week)s") % {"week": week}, gettext("KW %(week)s, ab %(date)s") % {
            "week": week, "date": date_format(start, "SHORT_DATE_FORMAT")}
    return date_format(start, "M"), date_format(start, "F Y")


def prep_line(request, app, block):
    """Liniendiagramm: Anzahl, Summe oder Durchschnitt je Tag, Woche oder Monat."""
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für dieses Liniendiagramm ist keine Tabelle ausgewählt.")}
    aggregate = props.get("aggregate") or "count"
    value_field = None
    if aggregate != "count":
        value_field = entity.fields.filter(key=props.get("field"), type__in=[Field.NUMBER, Field.DECIMAL]).first()
        if not value_field:
            return {"error": gettext("Summe und Durchschnitt brauchen ein Zahlenfeld.")}
    period = props.get("period") if props.get("period") in LINE_PERIODS else "month"
    low, high = LINE_PERIODS[period]
    count = min(max(int(props.get("count") or 12), low), high)
    starts, bucket_of = _line_buckets(period, count, timezone.localdate())
    date_field = entity.fields.filter(key=props.get("date_field"), type=Field.DATE).first()

    records = filtered(request, entity)
    if date_field:
        records = (records.annotate(_d=Cast(KeyTextTransform(date_field.key, "data"), TextField()))
                   .filter(_d__gte=starts[0].isoformat()).values_list("_d", "data"))
    else:
        records = records.filter(created_at__date__gte=starts[0]).values_list("created_at", "data")
    sums, counts = {}, {}
    for raw, data in records:
        try:
            day = date.fromisoformat(raw[:10]) if isinstance(raw, str) else timezone.localtime(raw).date()
        except (TypeError, ValueError):
            continue
        bucket = bucket_of(day)
        if value_field:
            try:
                number = float(data.get(value_field.key))
            except (TypeError, ValueError):
                continue
        else:
            number = 1
        sums[bucket] = sums.get(bucket, 0) + number
        counts[bucket] = counts.get(bucket, 0) + 1

    values = []
    for start in starts:
        if aggregate == "avg":
            values.append(sums[start] / counts[start] if counts.get(start) else None)
        else:
            values.append(sums.get(start, 0))
    known = [v for v in values if v is not None]
    threshold_val = None
    if str(props.get("threshold") or "").strip():
        try:
            threshold_val = float(props.get("threshold"))
        except (TypeError, ValueError):
            threshold_val = None
    top = max(known + ([threshold_val] if threshold_val is not None else []), default=0) or 1
    width, height = 600, 180
    step = width / len(values)  # jeder Punkt in der Mitte seiner Spalte, wie Beschriftung und Tooltip
    points = [(round((i + .5) * step, 1), round(height - height * v / top, 1))
              for i, v in enumerate(values) if v is not None]
    line = " ".join(f"{x},{y}" for x, y in points)
    area = f"{points[0][0]},{height} {line} {points[-1][0]},{height}" if points else ""

    band_area = ""
    anomalies = []
    if props.get("show_band") and len(known) >= 2:
        import math as _math

        mean = sum(known) / len(known)
        std = _math.sqrt(sum((v - mean) ** 2 for v in known) / len(known))
        upper_y = round(max(0.0, min(height, height - height * (mean + std) / top)), 1)
        lower_y = round(max(0.0, min(height, height - height * max(0.0, mean - std) / top)), 1)
        if points:
            x0, x1 = points[0][0], points[-1][0]
            band_area = f"{x0},{upper_y} {x1},{upper_y} {x1},{lower_y} {x0},{lower_y}"
        limit_val = threshold_val if threshold_val is not None else (mean + 1.8 * std if std > 0 else None)
        if limit_val is not None:
            for i, v in enumerate(values):
                if v is not None and v > limit_val:
                    anomalies.append({
                        "cx": f"{round((i + .5) * step, 1)}",
                        "cy": f"{round(height - height * v / top, 1)}",
                        "value": _format_number(round(v, 2) if isinstance(v, float) else v),
                    })
    threshold_y = (f"{round(max(0.0, min(height, height - height * threshold_val / top)), 1)}"
                   if threshold_val is not None else None)

    every = max(1, round(len(starts) / 8))  # höchstens etwa 8 Beschriftungen unter der Achse
    unit = props.get("unit") or ""
    entries = []
    for i, (start, value) in enumerate(zip(starts, values)):
        short, full = _line_label(period, start)
        shown = _format_number(round(value, 2) if isinstance(value, float) else value) if value is not None else "–"
        entries.append({"label": short if i % every == 0 or i == len(starts) - 1 else "",
                        "title": f"{full}: {shown}{(' ' + unit) if unit and value is not None else ''}",
                        "value": shown, "full": full})
    return {
        "line": line, "area": area, "width": width, "height": height, "entries": entries,
        "band_area": band_area, "threshold_y": threshold_y, "anomalies": anomalies,
        "max": _format_number(round(top, 2) if isinstance(top, float) else top),
        "last": entries[-1]["value"], "basis": date_field.label if date_field else gettext("Erfassungsdatum"),
        "empty": not any(known),
    }


PARAM_RE = re.compile(r"\{([a-z][a-z0-9_]{0,39})\}")


def prep_tableau(request, app, block):
    """Tableau-Ansicht: Dashboard von einem freigegebenen Tableau-Server, optional mit Filtern."""
    from . import tableau

    props = block["props"]
    src = str(props.get("url") or "").strip()
    host = tableau.host_of(src)
    if not src:
        return {"error": gettext("Für diese Tableau-Ansicht fehlt die Adresse des Dashboards.")}
    if not host:
        return {"error": gettext("Der Tableau-Server ist nicht freigegeben (Einstellung TABLEAU_HOSTS) "
                                 "oder die Adresse beginnt nicht mit https://.")}
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"error": gettext("Tableau-Ansichten gibt es nur für angemeldete Personen.")}
    # Filter: eine Zeile je Filter „Feld = Wert“; {name} setzt Werte aus der Adresse der Seite ein (?name=…).
    filters = []
    for line in str(props.get("filters") or "").splitlines()[:20]:
        field_name, sep, value = line.partition("=")
        if not sep or not field_name.strip():
            continue
        value = PARAM_RE.sub(lambda m: request.GET.get(m.group(1), ""), value.strip())
        if value:
            filters.append({"field": field_name.strip()[:200], "value": value[:500]})
    selection_map = {}
    for line in str(props.get("selection_map") or "").splitlines()[:20]:
        t_field, sep, url_param = line.partition("=")
        if sep and t_field.strip() and url_param.strip():
            selection_map[t_field.strip()[:120]] = url_param.strip()[:120]
    try:
        height = min(max(int(props.get("height") or 600), 200), 2000)
    except (TypeError, ValueError):
        height = 600
    toolbar = props.get("toolbar") if props.get("toolbar") in ("bottom", "top", "hidden") else "bottom"
    return {
        "src": src, "script_url": tableau.script_url(host), "token": tableau.connected_app_token(user),
        "filters": filters, "height": height, "toolbar": toolbar,
        "selection_map_json": json.dumps(selection_map, ensure_ascii=False) if selection_map else "",
    }


def prep_cards(request, app, block):
    props, bid = block["props"], block["id"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Karten ist keine Tabelle ausgewählt.")}
    fields = list(entity.fields.all())
    if not fields:
        return {"error": gettext("Die Tabelle hat noch keine Felder.")}
    title_field, detail_fields = fields[0], [f for f in fields[1:] if f.show_in_list][:4]
    size = min(max(int(props.get("page_size") or 6), 1), 60)
    page_obj = Paginator(filtered(request, entity), size).get_page(request.GET.get(f"p_{bid}"))
    refs = reference_labels(fields, page_obj.object_list)
    cards = [
        {"record": r,
         "title": display_value(title_field, r.data.get(title_field.key), refs) or f"#{r.pk}",
         "details": [(app_i18n.t(f.label), display_value(f, r.data.get(f.key), refs)) for f in detail_fields]}
        for r in page_obj.object_list
    ]
    return {"entity": entity, "cards": cards, "page_obj": page_obj, "next": request.get_full_path()}


def prep_pagelinks(request, app, block):
    return {"links": list(app.pages.filter(show_in_nav=True))}


def prep_image(request, app, block):
    url = (block["props"].get("url") or "").strip()
    if not url:
        return {"error": gettext("Für dieses Bild ist keine Adresse eingetragen.")}
    if not url.startswith(("https://", "/")):
        return {"error": gettext("Die Bildadresse muss mit https:// oder / beginnen.")}
    return {"src": url}


def prep_greeting(request, app, block):
    user = request.user
    name = user.first_name or user.get_username()
    return {"name": name, "today": date_format(timezone.localdate(), gettext("l, j. F Y"))}


def prep_export(request, app, block):
    entity = _entity(app, block["props"].get("entity"))
    if not entity:
        return {"error": gettext("Für diesen Export ist keine Tabelle ausgewählt.")}
    href = reverse("entity_export", args=[app.slug, entity.slug])
    query = request.GET.urlencode() if hasattr(request, "GET") else ""
    return {"entity": entity, "href": f"{href}?{query}" if query else href}


def prep_button(request, app, block):
    props = block["props"]
    target = props.get("target") or "page"
    ctx = {"next": request.get_full_path()}
    # Parameter der Seite (z. B. ?event=12) gehen an Button-Skripte und Aktionen weiter.
    query = request.GET.urlencode()
    if target == "script":
        script = app.scripts.filter(slug=props.get("script"), trigger=Script.BUTTON, enabled=True).first()
        if not script:
            return {"error": gettext("Für diesen Button ist kein aktives Skript ausgewählt.")}
        if script.language == Script.JAVASCRIPT:
            ctx["js_script"] = script.slug
        else:
            ctx["action_url"] = reverse("run_script", args=[app.slug, script.slug]) + (f"?{query}" if query else "")
    elif target == "action":
        name = props.get("action")
        if name not in hooks.ACTIONS:
            return {"error": gettext("Die gewählte Aktion gibt es nicht (mehr).")}
        ctx["action_url"] = reverse("run_action", args=[app.slug, name]) + (f"?{query}" if query else "")
    elif target == "url":
        url = (props.get("url") or "").strip()
        if not url.startswith(("https://", "http://", "/")):
            return {"error": gettext("Der Link muss mit https:// oder / beginnen.")}
        ctx["href"] = url
    else:
        page = app.pages.filter(slug=props.get("page")).first()
        if not page:
            return {"error": gettext("Für diesen Button ist keine Seite ausgewählt.")}
        ctx["href"] = reverse("page", args=[app.slug, page.slug])
    return ctx


def prep_http(request, app, block):
    props = block["props"]
    url = (props.get("url") or "").strip()
    if not url:
        return {"error": gettext("Für diesen Web-Request ist keine Adresse eingetragen.")}
    cache_key = f"baukasten-http-{url}"
    data = cache.get(cache_key)
    if data is None:
        try:
            data = http_json(url)
        except HttpNotAllowed as exc:
            return {"error": str(exc)}
        except Exception as exc:
            log.warning("Web-Request an %s fehlgeschlagen: %s", url, exc)
            return {"error": gettext("Der Web-Request ist fehlgeschlagen.")}
        cache.set(cache_key, data, 60)
    for part in [p for p in (props.get("path") or "").split(".") if p]:
        data = data.get(part) if isinstance(data, dict) else None
    limit = min(max(int(props.get("max_rows") or 20), 1), 200)
    if isinstance(data, list) and data and all(isinstance(i, dict) for i in data):
        columns = list(data[0].keys())[:8]
        rows = [[item.get(c, "") for c in columns] for item in data[:limit]]
        return {"http_columns": columns, "http_rows": rows}
    return {"http_text": json.dumps(data, indent=2, ensure_ascii=False)[:5000]}


def prep_output(request, app, block):
    return {"value": None}


INPUT_KINDS = {"text": "text", "email": "email", "number": "number", "textarea": "textarea",
               "range": "range", "date": "date", "select": "select", "checkbox": "checkbox"}
RESERVED_PARAMS = {"next", "csrfmiddlewaretoken", "form_prefix"}


def prep_input(request, app, block):
    """Eingabefeld: Ein Skript-Button auf derselben Seite schickt den Wert als params[<Name>] mit."""
    param = str(block["props"].get("param") or "").strip()
    if not NAME_RE.match(param) or param in RESERVED_PARAMS:
        return {"error": gettext("Das Eingabefeld braucht einen Namen aus Kleinbuchstaben, Ziffern und _ (z. B. vorname).")}
    props = block["props"]
    kind = INPUT_KINDS.get(props.get("kind"), "text")
    value = request.GET.get(param, "")
    ctx = {"param": param, "kind": kind, "value": value}
    if kind == "range":
        low, high = _int_prop(props, "min", 0), _int_prop(props, "max", 100)
        high = high if high > low else low + 1
        step = max(_int_prop(props, "step", 1), 1)
        try:
            current = min(max(float(value), low), high) if value != "" else low + (high - low) // 2
        except ValueError:
            current = low
        ctx.update({"min": low, "max": high, "step": step, "value": _plain_number(current)})
    elif kind == "select":
        ctx["options"] = [o.strip() for o in str(props.get("options") or "").splitlines() if o.strip()][:100]
    return ctx


def _int_prop(props, key, default):
    try:
        return int(props.get(key))
    except (TypeError, ValueError):
        return default


def _plain_number(value):
    return int(value) if float(value).is_integer() else round(value, 4)


def prep_query(request, app, block):
    from . import datasources

    props = block["props"]
    query = app.queries.filter(slug=props.get("query")).first()
    if not query:
        return {"error": gettext("Für diesen Baustein ist keine Abfrage ausgewählt.")}
    # Nachladende Bausteine warten nicht im Server (das hielte einen Thread fest),
    # sondern bekommen sofort „wird geladen“; der Browser fragt nach 2 Sekunden wieder.
    lazy = getattr(settings, "BAUKASTEN_LAZY_QUERIES", True)
    try:
        result = datasources.run_saved(query, wait=0 if lazy else None)
    except datasources.QueryBusy as exc:
        if not lazy:
            return {"error": gettext("Abfrage „%(name)s“: %(error)s") % {"name": query.name, "error": exc}}
        return {"loading": True, "loading_title": props.get("title") or query.name,
                "loading_text": str(exc), "retry": 2}
    except datasources.QueryError as exc:
        return {"error": gettext("Abfrage „%(name)s“: %(error)s") % {"name": query.name, "error": exc}}
    limit = min(max(int(props.get("max_rows") or 50), 1), 500)
    fetched = timezone.localtime(datetime.fromisoformat(result["fetched_at"]))
    return {
        "query": query, "q_columns": result["columns"],
        "q_rows": [[row.get(c) for c in result["columns"]] for row in result["rows"][:limit]],
        "q_more": len(result["rows"]) > limit or result["truncated"],
        "fetched": f"{date_format(fetched, 'SHORT_DATE_FORMAT')} {fetched:%H:%M:%S}" if props.get("show_time", True) else "",
        "q_stale": bool(result.get("stale")),
    }


def _rows_from(value):
    """Zeilen für den Ausgabe-Baustein: Liste von Dictionaries oder Listen."""
    if not isinstance(value, (list, tuple)):
        return [], []
    rows = list(value)[:500]
    if rows and isinstance(rows[0], dict):
        columns = list(rows[0].keys())[:12]
        return columns, [["" if row.get(c) is None else row.get(c) for c in columns] for row in rows if isinstance(row, dict)]
    return [], [list(row)[:12] if isinstance(row, (list, tuple)) else [row] for row in rows]


def apply_overrides(block_type, props, ctx, values, request=None, app=None, block=None):
    """Übernimmt, was ein Skript per ui.set für diesen Baustein gesetzt hat. Gibt False zurück, wenn er verborgen ist."""
    if values.get("hidden"):
        return False
    for key, value in values.items():
        if key in TEXT_OVERRIDES:
            props[key] = "" if value is None else str(value)[:5000]
    if props.get("tone") not in TONES:
        props["tone"] = "info"
    if "value" in values:
        value = values["value"]
        ctx["value"] = _format_number(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else (
            "" if value is None else str(value)[:500])
        if block_type == "stat":
            ctx.pop("error", None)  # ein Skript darf eine Kennzahl auch ohne Tabelle füllen
    if "rows" in values:
        ctx["out_columns"], ctx["out_rows"] = _rows_from(values["rows"])
        ctx["has_rows"] = True
    if block_type == "output" and ("value" in values or "rows" in values) and "text" not in values:
        props["text"] = ""  # der Platzhaltertext gilt nur, solange nichts gesetzt ist
    if block_type == "form" and isinstance(values.get("values"), dict) and ctx.get("entity"):
        ctx["form"] = RecordForm(ctx["entity"], prefix=block["id"], initial=values["values"])
    return True


# ---------- Registrierung der Standard-Bausteine ----------

ENTITY = {"key": "entity", "label": _("Tabelle"), "type": "entity"}
AGGREGATE = {"key": "aggregate", "label": _("Berechnung"), "type": "select", "default": "count",
             "options": [["count", _("Anzahl")], ["sum", _("Summe")], ["avg", _("Durchschnitt")]]}
NUMBER_FIELD = {"key": "field", "label": _("Feld (für Summe/Durchschnitt)"), "type": "field"}

# Inhalt
register("heading", _("Überschrift"), "🔤", [
    {"key": "text", "label": _("Text"), "type": "text", "default": _("Überschrift")},
    {"key": "subtitle", "label": _("Unterzeile (optional)"), "type": "text", "default": ""},
    {"key": "level", "label": _("Größe"), "type": "select", "default": "2",
     "options": [["1", _("Groß")], ["2", _("Mittel")], ["3", _("Klein")]]},
], hint=_("Titel mit optionaler Unterzeile"))
register("text", _("Text"), "📝", [
    {"key": "text", "label": _("Text"), "type": "textarea", "default": _("Text")},
], hint=_("Absatz mit Zeilenumbrüchen"))
register("notice", _("Hinweis"), "💡", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "text", "label": _("Text"), "type": "textarea", "default": _("Hinweistext")},
    {"key": "tone", "label": _("Art"), "type": "select", "default": "info",
     "options": [["info", _("Information")], ["success", _("Erfolg")], ["warning", _("Warnung")], ["danger", _("Wichtig")]]},
], hint=_("Farbig hervorgehobener Kasten"))
register("image", _("Bild"), "🖼️", [
    {"key": "url", "label": _("Bildadresse (https://… oder /static/…)"), "type": "text", "default": ""},
    {"key": "alt", "label": _("Beschreibung für Screenreader"), "type": "text", "default": ""},
    {"key": "caption", "label": _("Bildunterschrift (optional)"), "type": "text", "default": ""},
], prep_image, hint=_("Bild von einer Adresse"))
register("greeting", _("Begrüßung"), "👋", [
    {"key": "text", "label": _("Zusatztext (optional)"), "type": "text", "default": ""},
], prep_greeting, hint=_("Begrüßt den Nutzer mit Namen und Datum"))

# Daten
register("table", _("Liste"), "📋", [
    ENTITY,
    {"key": "title", "label": _("Titel (optional, sonst Name der Tabelle)"), "type": "text", "default": ""},
    {"key": "page_size", "label": _("Zeilen pro Seite"), "type": "number", "default": 20},
    {"key": "searchable", "label": _("Suchfeld anzeigen"), "type": "checkbox", "default": True},
], prep_table, "Daten", _("Tabelle mit Suche, Anlegen, Bearbeiten"))
register("cards", _("Karten"), "🗂️", [
    ENTITY,
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "page_size", "label": _("Karten pro Seite"), "type": "number", "default": 6},
], prep_cards, "Daten", _("Einträge als Karten statt als Zeilen"))
register("form", _("Formular"), "✏️", [
    ENTITY,
    {"key": "submit_label", "label": _("Beschriftung Button"), "type": "text", "default": _("Speichern")},
], prep_form, "Daten", _("Neuen Eintrag direkt erfassen"))
register("export", _("CSV-Export"), "⬇️", [
    ENTITY,
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Als CSV herunterladen")},
], prep_export, "Daten", _("Alle Einträge für Excel herunterladen"))

# Auswertung
register("stat", _("Kennzahl"), "🔢", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Anzahl")},
    ENTITY, AGGREGATE, NUMBER_FIELD,
    {"key": "unit", "label": _("Einheit (optional, z. B. €)"), "type": "text", "default": ""},
], prep_stat, "Auswertung", _("Anzahl, Summe oder Durchschnitt"))
register("progress", _("Fortschritt"), "🎯", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Fortschritt")},
    ENTITY, AGGREGATE, NUMBER_FIELD,
    {"key": "target", "label": _("Zielwert"), "type": "number", "default": 100},
    {"key": "unit", "label": _("Einheit (optional)"), "type": "text", "default": ""},
], prep_progress, "Auswertung", _("Wert im Verhältnis zu einem Ziel"))
register("chart", _("Balkendiagramm"), "📊", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Verteilung")},
    ENTITY,
    {"key": "field", "label": _("Gruppieren nach"), "type": "field"},
], prep_chart, "Auswertung", _("Einträge je Wert als Rangliste"))
register("donut", _("Kreisdiagramm"), "🍩", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Anteile")},
    ENTITY,
    {"key": "field", "label": _("Gruppieren nach"), "type": "field"},
], prep_donut, "Auswertung", _("Anteile der häufigsten Werte"))
register("timeline", _("Verlauf"), "📈", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Einträge pro Monat")},
    ENTITY,
    {"key": "field", "label": _("Datumsfeld (leer: Erfassungsdatum)"), "type": "field"},
    {"key": "months", "label": _("Anzahl Monate"), "type": "number", "default": 12},
], prep_timeline, "Auswertung", _("Einträge pro Monat"))
register("line", _("Liniendiagramm"), "📉", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Entwicklung")},
    ENTITY,
    {"key": "date_field", "label": _("Datumsfeld (leer: Erfassungsdatum)"), "type": "field"},
    AGGREGATE,
    {"key": "field", "label": _("Zahlenfeld (für Summe/Durchschnitt)"), "type": "field"},
    {"key": "period", "label": _("Zeitraster"), "type": "select", "default": "month",
     "options": [["day", _("Tage")], ["week", _("Wochen")], ["month", _("Monate")]]},
    {"key": "count", "label": _("Anzahl Zeitabschnitte"), "type": "number", "default": 12},
    {"key": "unit", "label": _("Einheit (optional)"), "type": "text", "default": ""},
    {"key": "show_band", "label": _("Konfidenzband (±1σ) und Anomalien anzeigen"), "type": "checkbox", "default": False},
    {"key": "threshold", "label": _("Schwellenwert-Linie (optional)"), "type": "text", "default": ""},
], prep_line, "Auswertung", _("Werte je Tag, Woche oder Monat als Linie"))

# Navigation
register("button", _("Button"), "🔘", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Weiter")},
    {"key": "target", "label": _("Was passiert beim Klick?"), "type": "select", "default": "page",
     "options": [["page", _("Seite öffnen")], ["url", _("Link öffnen")], ["script", _("Skript ausführen")],
                 ["action", _("Python-Aktion ausführen")]]},
    {"key": "page", "label": _("Seite"), "type": "page"},
    {"key": "url", "label": _("Link"), "type": "text", "default": ""},
    {"key": "script", "label": _("Skript"), "type": "script"},
    {"key": "action", "label": _("Aktion"), "type": "action"},
    {"key": "style", "label": _("Aussehen"), "type": "select", "default": "primary",
     "options": [["primary", _("Hervorgehoben")], ["secondary", _("Dezent")]]},
    {"key": "align", "label": _("Ausrichtung"), "type": "select", "default": "left",
     "options": [["left", _("Links")], ["right", _("Rechts")]]},
], prep_button, "Navigation", _("Seite, Link oder Python-Aktion"))
register("pagelinks", _("Seitenkacheln"), "🧭", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
], prep_pagelinks, "Navigation", _("Kacheln zu allen Seiten der App"))

# Layout
register("divider", _("Trennlinie"), "➖", [], category="Layout", hint=_("Waagerechte Linie"))
register("spacer", _("Abstand"), "↕️", [
    {"key": "size", "label": _("Höhe"), "type": "select", "default": "m",
     "options": [["s", _("Klein")], ["m", _("Mittel")], ["l", _("Groß")]]},
], category="Layout", hint=_("Leerraum zwischen Bausteinen"))

# Anbindung
register("http", _("Web-Request"), "🌐", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Daten")},
    {"key": "url", "label": _("Adresse (liefert JSON)"), "type": "text", "default": ""},
    {"key": "path", "label": _("Pfad im JSON (optional, z. B. data.items)"), "type": "text", "default": ""},
    {"key": "max_rows", "label": _("Maximale Zeilen"), "type": "number", "default": 20},
], prep_http, "Anbindung", _("JSON von einer freigegebenen Adresse"))
register("tableau", _("Tableau-Ansicht"), "📊", [
    {"key": "label", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "url", "label": _("Adresse des Dashboards (https://…/views/…)"), "type": "text", "default": ""},
    {"key": "height", "label": _("Höhe in Pixeln"), "type": "number", "default": 600},
    {"key": "toolbar", "label": _("Werkzeugleiste"), "type": "select", "default": "bottom",
     "options": [["bottom", _("Unten")], ["top", _("Oben")], ["hidden", _("Ausblenden")]]},
    {"key": "hide_tabs", "label": _("Reiter ausblenden"), "type": "checkbox", "default": False},
    {"key": "filters", "label": _("Filter, je Zeile „Feld = Wert“; {name} übernimmt ?name=… aus der Adresse"),
     "type": "textarea", "default": ""},
    {"key": "selection_map", "label": _("Klick im Dashboard filtert Seite (je Zeile „Tableau-Feld = URL-Parameter“)"),
     "type": "textarea", "default": ""},
], prep_tableau, "Anbindung", _("Dashboard von eurem Tableau-Server oder Tableau Cloud"))
register("query", _("Datenbank-Abfrage"), "🗄️", [
    {"key": "query", "label": _("Abfrage"), "type": "query"},
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "max_rows", "label": _("Maximale Zeilen"), "type": "number", "default": 50},
    {"key": "show_time", "label": _("Zeitpunkt der Daten anzeigen"), "type": "checkbox", "default": True},
], prep_query, "Anbindung", _("Live-Daten aus einer Datenbank oder Databricks"))

# Skripte
register("output", _("Ausgabe"), "📤", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Ergebnis")},
    {"key": "unit", "label": _("Einheit (optional)"), "type": "text", "default": ""},
    {"key": "text", "label": _("Text, solange nichts gesetzt ist"), "type": "text", "default": ""},
], prep_output, "Skripte", _("Zeigt Werte, Text oder Tabellen aus einem Skript"))
register("input", _("Eingabefeld"), "⌨️", [
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("Name")},
    {"key": "param", "label": _("Name des Werts (im Skript: params[\"…\"])"), "type": "text", "default": "name"},
    {"key": "kind", "label": _("Art"), "type": "select", "default": "text",
     "options": [["text", _("Text")], ["email", _("E-Mail")], ["number", _("Zahl")], ["textarea", _("Langer Text")],
                 ["range", _("Schieberegler")], ["date", _("Datum")], ["select", _("Auswahl")],
                 ["checkbox", _("Ja/Nein")]]},
    {"key": "required", "label": _("Pflichtfeld"), "type": "checkbox", "default": False},
    {"key": "placeholder", "label": _("Platzhalter (optional)"), "type": "text", "default": ""},
    {"key": "min", "label": _("Schieberegler: kleinster Wert"), "type": "number", "default": 0},
    {"key": "max", "label": _("Schieberegler: größter Wert"), "type": "number", "default": 100},
    {"key": "step", "label": _("Schieberegler: Schrittweite"), "type": "number", "default": 1},
    {"key": "options", "label": _("Auswahl: ein Wert je Zeile"), "type": "textarea", "default": ""},
], prep_input, "Skripte", _("Wert, den ein Skript-Button auf der Seite mitschickt"))


# Planung (Einsatzplanung, Wochenübersicht, Kanban) steht in einer eigenen Datei.
from . import planning  # noqa: E402,F401  registriert die Planungs-Bausteine
from . import widgets  # noqa: E402,F401  Filter, Kalender, Checkliste, Schieberegler, Aufklappbereich
from . import datascience  # noqa: E402,F401  Scatter, Boxplot, Heatmap, Spec-Chart

# ---------- Anzeige, Prüfung, Designer-Konfiguration ----------

def render_block(request, app, block, types=None, overrides=None):
    """HTML eines Bausteins oder None, wenn ein Skript ihn verborgen hat."""
    types = types or all_types()
    block_type = types.get(block.get("type"))
    if not block_type:
        return None
    try:
        ctx = block_type.prepare(request, app, block) if block_type.prepare else {}
    except Exception:
        log.exception("Baustein %s fehlgeschlagen", block.get("type"))
        ctx = {"error": gettext("Dieser Baustein konnte nicht geladen werden.")}
    props = app_i18n.translate_props(dict(block["props"]), block_type)
    values = (overrides or {}).get(block.get("name") or "", {})
    if values and not apply_overrides(block["type"], props, ctx, values, request, app, block):
        return None
    return render_to_string(
        "builder/block.html",
        {"type": block["type"], "p": props, "bid": block["id"], "app": app, "block_name": block.get("name", ""), **ctx},
        request=request,
    )


# Bausteine, die auf externe Datenquellen warten. Mit lazy=True kommt die Seite sofort,
# diese Bausteine lädt der Browser danach einzeln nach (siehe runtime.js).
LAZY_TYPES = {"query"}


def render_placeholder(request, app, block):
    props = dict(block["props"])
    query = app.queries.filter(slug=props.get("query")).first() if block.get("type") == "query" else None
    return render_to_string(
        "builder/block.html",
        {"loading": True, "type": block["type"], "p": props, "bid": block["id"], "app": app,
         "loading_title": props.get("title") or (query.name if query else "")},
        request=request,
    )


def render_layout(request, app, page, layout=None, overrides=None, lazy=False):
    types = all_types()
    rendered = []
    for block in (page.layout if layout is None else layout):
        deferred = lazy and block.get("type") in LAZY_TYPES
        html = render_placeholder(request, app, block) if deferred else render_block(request, app, block, types, overrides)
        if html is None:
            continue
        rendered.append({"id": block["id"], "type": block.get("type"), "width": block.get("width", 12), "name": block.get("name", ""),
                         "refresh": block.get("refresh", 0), "lazy": deferred, "html": html})
    return rendered


def clean_layout(raw):
    """Übernimmt aus dem Designer nur bekannte Bausteine und bekannte Einstellungen."""
    if not isinstance(raw, list):
        raise ValueError("Das Layout muss eine Liste sein.")
    types = all_types()
    cleaned, seen = [], set()
    for item in raw[:200]:
        if not isinstance(item, dict) or item.get("type") not in types:
            continue
        block_type = types[item["type"]]
        bid = str(item.get("id") or "")
        if not bid.isalnum() or len(bid) > 20 or bid in seen:
            bid = "b" + secrets.token_hex(4)
        seen.add(bid)
        width = item.get("width") if item.get("width") in WIDTHS else 12
        name = str(item.get("name") or "").strip().lower()
        name = name if NAME_RE.match(name) else ""
        try:
            refresh = int(item.get("refresh") or 0)
        except (TypeError, ValueError):
            refresh = 0
        refresh = refresh if refresh in REFRESH else 0
        given = item.get("props") if isinstance(item.get("props"), dict) else {}
        props = {}
        for spec in block_type.fields:
            value = given.get(spec["key"], spec.get("default", ""))
            if spec["type"] == "checkbox":
                value = bool(value)
            elif spec["type"] == "number":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = spec.get("default", 0)
            else:
                value = str(value if value is not None else "")[:2000]
            props[spec["key"]] = value
        entry = {"id": bid, "type": item["type"], "width": width, "props": props}
        if name:
            entry["name"] = name
        if refresh:
            entry["refresh"] = refresh
        cleaned.append(entry)
    return cleaned


def default_props(type_key):
    return {s["key"]: s.get("default", "") for s in all_types()[type_key].fields}


def make_block(type_key, width=12, **props):
    return {
        "id": "b" + secrets.token_hex(4), "type": type_key, "width": width,
        "props": {**default_props(type_key), **props},
    }


def designer_config(app, page):
    return {
        "blocks": [
            {"key": t.key, "label": t.label, "icon": t.icon, "fields": t.fields,
             "category": t.category, "hint": t.hint}
            for t in all_types().values()
        ],
        "categories": [{"key": key, "label": label} for key, label in CATEGORIES],
        "entities": [
            {"slug": e.slug, "name": e.name,
             "fields": [{"key": f.key, "label": f.label, "type": f.type,
                         "reference": f.reference.slug if f.reference_id else None} for f in e.fields.all()]}
            for e in app.entities.prefetch_related("fields__reference")
        ],
        "pages": [{"slug": p.slug, "title": p.title} for p in app.pages.all()],
        "actions": [{"name": n, "label": a["label"]} for n, a in hooks.ACTIONS.items()],
        "scripts": [{"slug": sc.slug, "name": f"{sc.name} ({sc.get_language_display()})"}
                    for sc in app.scripts.filter(trigger=Script.BUTTON)],
        "queries": [{"slug": q.slug, "name": q.name} for q in app.queries.all()],
        "refresh": [[0, _("Aus")], [10, _("alle 10 Sekunden")], [30, _("alle 30 Sekunden")],
                    [60, _("jede Minute")], [300, _("alle 5 Minuten")]],
        "widths": [[3, "¼"], [4, "⅓"], [6, "½"], [8, "⅔"], [12, _("Ganze Breite")]],
        "presets": [
            {"id": c.pk, "name": c.name, "hint": c.description, **c.preset}
            for c in CustomBlock.objects.filter(kind=CustomBlock.PRESET)
            if c.preset.get("type") in all_types()
        ],
        "layout": page.layout,
        "version": page.version,
    }
