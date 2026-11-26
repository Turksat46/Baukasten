"""Allgemeine Bausteine: Filterleiste, Kalender, Checkliste, Schieberegler, Aufklappbereich.

Filterleiste, Kalender, Checkliste und Schieberegler arbeiten auf einer Tabelle der App.
Die Filterleiste setzt Parameter in der Adresse (?tabelle.feld=wert); alle Bausteine derselben
Tabelle auf der Seite beachten sie (blocks.filtered). Checkliste und Schieberegler speichern
über views.block_action mit den Rechten der Person.
"""
import calendar as pycalendar
from datetime import date, timedelta

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format, number_format
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from . import app_i18n
from .blocks import _entity, _format_number, display_value, filter_param, filtered, reference_labels, register, rich_value
from .models import Field
from .page_path import page_url

MONTH_PARAM = "monat"   # ?monat=2026-11
GANTT_PARAM = "zeitraum"  # ?zeitraum=2026-11-16
GANTT_DAYS = 28
MAX_ITEMS = 200


def _field(entity, key, types=None):
    if not entity or not key:
        return None
    f = next((f for f in entity.fields.all() if f.key == key), None)
    return f if f and (not types or f.type in types) else None


def _label(record, label_field, refs=None):
    if label_field:
        value = display_value(label_field, record.data.get(label_field.key), refs)
        if value:
            return value
    return str(record)


def _urls(request, app, block):
    from .planning import _urls as urls
    return urls(request, app, block)


def _next(request):
    return page_url(request)


# ---------- Filterleiste ----------

def prep_filter(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Filterleiste ist keine Tabelle ausgewählt.")}
    keys = [props.get(k) for k in ("field", "field2", "field3", "field4")]
    fields = [f for f in (_field(entity, k) for k in keys if k) if f]
    if not fields:
        return {"error": gettext("Wähle mindestens ein Feld, nach dem gefiltert wird.")}
    params = request.GET
    controls, own = [], set()
    for f in fields:
        label = app_i18n.t(f.label)
        name = filter_param(entity, f)
        if f.type == Field.DATE:
            low, high = name + ".von", name + ".bis"
            own.update({low, high})
            controls.append({"kind": "date", "label": label, "low": low, "high": high,
                             "low_value": params.get(low, ""), "high_value": params.get(high, "")})
            continue
        own.add(name)
        current = params.get(name, "")
        if f.type == Field.CHOICE:
            options = [(c, display_value(f, c)) for c in f.choice_list()]
        elif f.type == Field.BOOL:
            options = [("1", gettext("Ja")), ("0", gettext("Nein"))]
        elif f.type == Field.REFERENCE and f.reference_id:
            options = [(str(r.pk), str(r)) for r in f.reference.records.order_by("id")[:MAX_ITEMS]]
        else:
            controls.append({"kind": "number" if f.type in (Field.NUMBER, Field.DECIMAL) else "text",
                             "label": label, "name": name, "value": current})
            continue
        controls.append({"kind": "select", "label": label, "name": name, "value": current, "options": options})
    # Andere Parameter der Seite (z. B. ?datum=…) bleiben erhalten; Blättern beginnt von vorn.
    keep = [(k, v) for k, v in params.items() if k not in own and not k.startswith("p_")]
    active = any(params.get(k) for k in own)
    total = entity.records.count()
    return {
        "entity": entity, "controls": controls, "keep": keep, "active": active,
        "count": filtered(request, entity).count() if active else total, "total": total,
        "reset": "?" + "&".join(f"{k}={v}" for k, v in keep) if keep else "?",
    }


# ---------- Kalender ----------

def prep_calendar(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diesen Kalender ist keine Tabelle ausgewählt.")}
    start_field = _field(entity, props.get("date_field"), [Field.DATE])
    if not start_field:
        return {"error": gettext("Der Kalender braucht ein Datumsfeld.")}
    end_field = _field(entity, props.get("end_field"), [Field.DATE])
    label_field = _field(entity, props.get("label_field"))
    color_field = _field(entity, props.get("color_field"), [Field.CHOICE])

    today = timezone.localdate()
    try:
        year, month = (int(x) for x in str(request.GET.get(MONTH_PARAM, ""))[:7].split("-"))
        first = date(year, month, 1)
    except (TypeError, ValueError):
        first = today.replace(day=1)
    last = first.replace(day=pycalendar.monthrange(first.year, first.month)[1])
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=6 - last.weekday())

    records = list(filtered(request, entity).order_by("id")[:2000])
    refs = reference_labels([label_field], records) if label_field else {}
    colors = {c: i % 6 + 1 for i, c in enumerate(color_field.choice_list())} if color_field else {}
    by_day = {}
    for r in records:
        try:
            begin = date.fromisoformat(str(r.data.get(start_field.key))[:10])
        except ValueError:
            continue
        end = begin
        if end_field:
            try:
                end = max(date.fromisoformat(str(r.data.get(end_field.key))[:10]), begin)
            except ValueError:
                pass
        end = min(end, begin + timedelta(days=62))
        if end < grid_start or begin > grid_end:
            continue
        item = {"id": r.pk, "label": _label(r, label_field, refs),
                "tone": colors.get(r.data.get(color_field.key)) if color_field else None,
                "multi": end > begin}
        day = max(begin, grid_start)
        while day <= min(end, grid_end):
            by_day.setdefault(day, []).append(item)
            day += timedelta(days=1)

    limit = 3
    can_create = entity.allow_create and bool(props.get("create_links", True)) and start_field.show_in_form
    create_url = reverse("record_create", args=[app.slug, entity.slug]) if can_create else ""
    next_url = _next(request)
    weeks, day = [], grid_start
    while day <= grid_end:
        week = []
        for _i in range(7):
            items = by_day.get(day, [])
            week.append({"day": day, "num": day.day, "iso": day.isoformat(), "in_month": day.month == first.month,
                         "today": day == today, "items": items[:limit], "more": max(len(items) - limit, 0),
                         "count": len(items), "weekend": day.weekday() >= 5})
            day += timedelta(days=1)
        weeks.append(week)
    prev_month = (first - timedelta(days=1)).replace(day=1)
    next_month = last + timedelta(days=1)
    legend = [{"label": display_value(color_field, c), "tone": t} for c, t in colors.items()] if color_field else []
    return {
        "entity": entity, "weeks": weeks, "month_label": date_format(first, "F Y"),
        "weekdays": [date_format(grid_start + timedelta(days=i), "D") for i in range(7)],
        "prev": prev_month.strftime("%Y-%m"), "next": next_month.strftime("%Y-%m"),
        "this": today.strftime("%Y-%m"), "is_this": first == today.replace(day=1), "param": MONTH_PARAM,
        "create_url": create_url, "date_key": start_field.key, "next_url": next_url, "legend": legend,
        "edit": entity.allow_edit, "total": sum(1 for d in by_day if first <= d <= last and by_day[d]),
    }


# ---------- Checkliste ----------

def prep_checklist(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Checkliste ist keine Tabelle ausgewählt.")}
    done_field = _field(entity, props.get("field"), [Field.BOOL])
    if not done_field:
        return {"error": gettext("Die Checkliste braucht ein Ja/Nein-Feld (z. B. Erledigt).")}
    label_field = _field(entity, props.get("label_field"))
    detail_field = _field(entity, props.get("detail"))
    records = list(filtered(request, entity).order_by("id")[:MAX_ITEMS])
    refs = reference_labels([f for f in (label_field, detail_field) if f], records)
    items = [{"id": r.pk, "label": _label(r, label_field, refs), "done": bool(r.data.get(done_field.key)),
              "detail": display_value(detail_field, r.data.get(detail_field.key), refs) if detail_field else ""}
             for r in records]
    done = sum(1 for i in items if i["done"])
    if props.get("hide_done"):
        shown = [i for i in items if not i["done"]]
    else:
        shown = sorted(items, key=lambda i: i["done"])  # offene zuerst, sonst in Reihenfolge
    return {"entity": entity, "items": shown, "done": done, "count": len(items),
            "percent": round(100 * done / len(items)) if items else 0,
            "editable": entity.allow_edit, "next": page_url(request), **_urls(request, app, block)}


def handle_checklist(app, block, payload, user):
    from .scripting.ops import OpsError, TableOps

    props = block["props"]
    entity = _entity(app, props.get("entity"))
    done_field = _field(entity, props.get("field"), [Field.BOOL])
    if not entity or not done_field or not isinstance(payload, dict) or payload.get("op") != "toggle":
        raise OpsError(gettext("Unbekannte Aktion."))
    record = _record(entity, payload.get("record"))
    TableOps(app, user=user, enforce_flags=True).update(entity.slug, record.pk, {done_field.key: payload.get("value") is True})
    return {"ok": True}


def _record(entity, raw):
    from .scripting.ops import OpsError

    try:
        record = entity.records.filter(pk=int(raw)).first()
    except (TypeError, ValueError):
        record = None
    if record is None:
        raise OpsError(gettext("Diesen Eintrag gibt es nicht (mehr). Bitte die Seite neu laden."))
    return record


# ---------- Schieberegler ----------

def _range(props):
    def number(key, default):
        try:
            return int(props.get(key))
        except (TypeError, ValueError):
            return default
    low, high = number("min", 0), number("max", 100)
    return low, (high if high > low else low + 1), max(number("step", 1), 1)


def prep_sliders(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Schieberegler ist keine Tabelle ausgewählt.")}
    value_field = _field(entity, props.get("field"), [Field.NUMBER, Field.DECIMAL])
    if not value_field:
        return {"error": gettext("Die Schieberegler brauchen ein Zahlenfeld (z. B. Fortschritt).")}
    label_field = _field(entity, props.get("label_field"))
    low, high, step = _range(props)
    records = list(filtered(request, entity).order_by("id")[:MAX_ITEMS])
    refs = reference_labels([label_field], records) if label_field else {}
    items = []
    for r in records:
        raw = r.data.get(value_field.key)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = None
        shown = min(max(value, low), high) if value is not None else low
        items.append({"id": r.pk, "label": _label(r, label_field, refs), "empty": value is None,
                      "value": int(shown) if float(shown).is_integer() else shown,
                      "percent": round(100 * (shown - low) / (high - low))})
    return {"entity": entity, "items": items, "min": low, "max": high, "step": step,
            "editable": entity.allow_edit, **_urls(request, app, block)}


def handle_sliders(app, block, payload, user):
    from .scripting.ops import OpsError, TableOps

    props = block["props"]
    entity = _entity(app, props.get("entity"))
    value_field = _field(entity, props.get("field"), [Field.NUMBER, Field.DECIMAL])
    if not entity or not value_field or not isinstance(payload, dict) or payload.get("op") != "set":
        raise OpsError(gettext("Unbekannte Aktion."))
    record = _record(entity, payload.get("record"))
    low, high, step = _range(props)
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        raise OpsError(gettext("Bitte eine Zahl angeben.")) from None
    if not low <= value <= high:
        raise OpsError(gettext("Erlaubt sind Werte von %(min)s bis %(max)s.") % {"min": low, "max": high})
    value = low + round((value - low) / step) * step  # auf das Raster ziehen
    value = int(value) if value_field.type == Field.NUMBER else float(value)
    TableOps(app, user=user, enforce_flags=True).update(entity.slug, record.pk, {value_field.key: value})
    return {"ok": True, "value": value}


# ---------- Pivot- / Kreuztabelle ----------

def _pivot_key(field, value, refs):
    """Normalisiert einen Feldwert zu (sort_key, anzeige_label)."""
    if value is None or value == "":
        return ("", "—")
    label = display_value(field, value, refs)
    return (str(label).casefold(), str(label))


def _fmt_num(value):
    """Zahl in der Kreuztabelle: mit Tausenderpunkt und Dezimalkomma wie die Kennzahlen, ohne unnötige Nullen."""
    if value is None:
        return "—"
    if float(value).is_integer():
        return _format_number(int(value))
    text = _format_number(round(float(value), 2))
    decimal = number_format(0.5, decimal_pos=1, use_l10n=True)[1]  # „,“ oder „.“ je nach Sprache
    return text.rstrip("0").rstrip(decimal) if decimal in text else text


def _agg_value(agg, count, total):
    if agg == "count":
        return count
    if not count:
        return None
    return total if agg == "sum" else round(total / count, 2)


def prep_pivot(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Kreuztabelle ist keine Tabelle ausgewählt.")}
    row_field = _field(entity, props.get("row_field"))
    if not row_field:
        return {"error": gettext("Die Kreuztabelle braucht ein Zeilenfeld.")}
    col_field = _field(entity, props.get("col_field"))
    agg = props.get("agg") or "count"
    if agg not in ("count", "sum", "avg"):
        agg = "count"
    value_field = _field(entity, props.get("value_field"), [Field.NUMBER, Field.DECIMAL])
    if agg in ("sum", "avg") and not value_field:
        return {"error": gettext("Für Summe oder Durchschnitt braucht die Kreuztabelle ein Zahlenfeld.")}

    records = list(filtered(request, entity).order_by("id")[:2000])
    refs = reference_labels([f for f in (row_field, col_field) if f], records)

    row_labels, col_labels = {}, {}
    cells = {}  # (row_key, col_key) -> [count, sum]
    row_acc, col_acc = {}, {}
    grand_count, grand_sum = 0, 0.0

    for r in records:
        rk, rlabel = _pivot_key(row_field, r.data.get(row_field.key), refs)
        row_labels[rk] = rlabel
        if col_field:
            ck, clabel = _pivot_key(col_field, r.data.get(col_field.key), refs)
            col_labels[ck] = clabel
        else:
            ck, clabel = "__all__", gettext("Wert")
            col_labels[ck] = clabel

        num = 0.0
        if agg != "count":
            try:
                num = float(r.data.get(value_field.key))
            except (TypeError, ValueError):
                continue

        cell = cells.setdefault((rk, ck), [0, 0.0])
        cell[0] += 1
        cell[1] += num
        ra = row_acc.setdefault(rk, [0, 0.0])
        ra[0] += 1
        ra[1] += num
        ca = col_acc.setdefault(ck, [0, 0.0])
        ca[0] += 1
        ca[1] += num
        grand_count += 1
        grand_sum += num

    sorted_cols = sorted(col_labels.items(), key=lambda item: (item[0] == "", item[0]))
    sorted_rows = sorted(row_labels.items(), key=lambda item: (item[0] == "", item[0]))

    rows = []
    for rk, rlabel in sorted_rows:
        values = []
        for ck, _clabel in sorted_cols:
            c_count, c_sum = cells.get((rk, ck), (0, 0.0))
            val = _agg_value(agg, c_count, c_sum)
            values.append({"display": _fmt_num(val), "empty": val is None or val == 0})
        rc, rs = row_acc.get(rk, (0, 0.0))
        rtot = _agg_value(agg, rc, rs)
        rows.append({"label": rlabel, "values": values, "total": _fmt_num(rtot)})

    col_totals = []
    for ck, _clabel in sorted_cols:
        cc, cs = col_acc.get(ck, (0, 0.0))
        col_totals.append(_fmt_num(_agg_value(agg, cc, cs)))
    grand_total = _fmt_num(_agg_value(agg, grand_count, grand_sum))

    return {
        "entity": entity,
        "row_label": app_i18n.t(row_field.label),
        "cols": [label for _k, label in sorted_cols],
        "rows": rows,
        "col_totals": col_totals,
        "grand_total": grand_total,
        "show_totals": bool(props.get("show_totals", True)),
        "has_cols": bool(col_field),
        "total_records": len(records),
    }


# ---------- Gantt- / Zeitstrahl-Ansicht ----------

def _parse_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _gantt_labelled(i, d):
    """Beschriftung jeden 7. Tag und am Monatsersten. Liegt der Monatserste direkt neben der
    Wochenbeschriftung, fällt diese weg – sonst überlappen „30.11.“ und „1.12.“."""
    if d.day == 1:
        return True
    near = (d + timedelta(days=k) for k in (-1, 1, 2))
    return i % 7 == 0 and all(n.day != 1 for n in near)


def prep_gantt(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Zeitstrahl-Ansicht ist keine Tabelle ausgewählt.")}
    start_field = _field(entity, props.get("start_field"), [Field.DATE])
    if not start_field:
        return {"error": gettext("Die Zeitstrahl-Ansicht braucht ein Startdatum.")}
    end_field = _field(entity, props.get("end_field"), [Field.DATE])
    label_field = _field(entity, props.get("label_field"))
    group_field = _field(entity, props.get("group_field"))
    color_field = _field(entity, props.get("color_field"), [Field.CHOICE])

    today = timezone.localdate()
    this_monday = today - timedelta(days=today.weekday())
    win_start = _parse_date(request.GET.get(GANTT_PARAM)) or this_monday
    win_end = win_start + timedelta(days=GANTT_DAYS - 1)

    records = list(filtered(request, entity).order_by("id")[:MAX_ITEMS])
    ref_fields = [f for f in (label_field, group_field) if f]
    refs = reference_labels(ref_fields, records) if ref_fields else {}
    colors = {c: i % 6 + 1 for i, c in enumerate(color_field.choice_list())} if color_field else {}

    days = []
    for i in range(GANTT_DAYS):
        d = win_start + timedelta(days=i)
        days.append({"day": d, "num": d.day, "today": d == today, "weekend": d.weekday() >= 5,
                     "label": date_format(d, "j.n.") if _gantt_labelled(i, d) else ""})

    items = []
    for r in records:
        begin = _parse_date(r.data.get(start_field.key))
        if not begin:
            continue
        end = (_parse_date(r.data.get(end_field.key)) if end_field else None) or begin
        if end < begin:
            end = begin
        if end < win_start or begin > win_end:
            continue
        clipped_start = max(begin, win_start)
        clipped_end = min(end, win_end)
        offset = (clipped_start - win_start).days
        span = (clipped_end - clipped_start).days + 1
        group_name = ""
        if group_field:
            group_name = display_value(group_field, r.data.get(group_field.key), refs) or "—"
        items.append({
            "id": r.pk,
            "label": _label(r, label_field, refs),
            "group": str(group_name),
            "start": begin,
            "end": end,
            "left": round(100 * offset / GANTT_DAYS, 3),
            "width": round(100 * span / GANTT_DAYS, 3),
            "tone": colors.get(r.data.get(color_field.key)) if color_field else None,
            "clip_left": begin < win_start,
            "clip_right": end > win_end,
        })

    if group_field:
        items.sort(key=lambda x: (x["group"] == "—", x["group"].casefold(), x["start"], x["id"]))
    else:
        items.sort(key=lambda x: (x["start"], x["id"]))

    legend = [{"label": display_value(color_field, c), "tone": t} for c, t in colors.items()] if color_field else []
    step = timedelta(days=14)
    return {
        "entity": entity,
        "days": days,
        "items": items,
        "has_groups": bool(group_field),
        "range_label": f"{date_format(win_start, 'd.m.Y')} – {date_format(win_end, 'd.m.Y')}",
        "param": GANTT_PARAM,
        "prev": (win_start - step).isoformat(),
        "next": (win_start + step).isoformat(),
        "this": this_monday.isoformat(),
        "is_this": win_start == this_monday,
        "edit": entity.allow_edit,
        "next_url": _next(request),
        "legend": legend,
    }


# ---------- Detailansicht, Verknüpfte Unterliste, Suchbox, Status-Leiste ----------

def _target_record(request, entity, param_name):
    raw = (request.GET.get(param_name or "id") or "").strip()
    if not raw.isdigit():
        return None, False
    return entity.records.filter(pk=int(raw)).first(), True


def prep_detail(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Detailansicht ist keine Tabelle ausgewählt.")}
    param = (props.get("param") or "id").strip() or "id"
    record, has_param = _target_record(request, entity, param)
    if not has_param:
        return {"entity": entity, "missing": True, "param": param}
    if not record:
        return {"error": gettext("Der ausgewählte Eintrag wurde nicht gefunden.")}
    fields = list(entity.fields.all())
    refs = reference_labels(fields, [record])
    rows = [{"label": app_i18n.t(f.label), "value": rich_value(f, record.data.get(f.key), refs) or "—"}
            for f in fields]
    show_actions = bool(props.get("show_actions", True))
    return {
        "entity": entity,
        "record": record,
        "title_text": str(record),
        "rows": rows,
        "edit_url": reverse("record_edit", args=[app.slug, entity.slug, record.pk]) if (show_actions and entity.allow_edit) else "",
        "delete_url": reverse("record_delete", args=[app.slug, entity.slug, record.pk]) if (show_actions and entity.allow_delete) else "",
        "next_url": _next(request),
    }


def prep_related_list(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Unterliste ist keine Tabelle ausgewählt.")}
    ref_field = _field(entity, props.get("ref_field"), [Field.REFERENCE])
    if not ref_field:
        return {"error": gettext("Die Unterliste braucht ein Verweisfeld.")}
    param = (props.get("param") or "id").strip() or "id"
    raw = (request.GET.get(param) or "").strip()
    if not raw.isdigit():
        return {"entity": entity, "missing": True, "param": param}
    parent_id = int(raw)
    # In der Datenbank filtern: vorher wurden nur die ersten 500 Einträge der ganzen Tabelle
    # geladen, bei größeren Tabellen fehlten Untereinträge ohne Hinweis.
    # Verweise stehen als Zahl im JSON; ältere Daten können sie als Text enthalten.
    matching = filtered(request, entity).filter(
        Q(**{f"data__{ref_field.key}": parent_id}) | Q(**{f"data__{ref_field.key}": str(parent_id)})
    ).order_by("id")
    records = list(matching[:MAX_ITEMS + 1])
    more = len(records) > MAX_ITEMS
    records = records[:MAX_ITEMS]
    cols = [f for f in entity.fields.all() if f.show_in_list and f.key != ref_field.key] or list(entity.fields.all()[:4])
    refs = reference_labels(cols, records)
    items = [{
        "id": r.pk,
        "cells": [display_value(c, r.data.get(c.key), refs) or "—" for c in cols],
    } for r in records]
    can_create = entity.allow_create and bool(props.get("show_add", True))
    create_url = reverse("record_create", args=[app.slug, entity.slug]) if can_create else ""
    return {
        "entity": entity,
        "cols": [app_i18n.t(c.label) for c in cols],
        "items": items,
        "edit": entity.allow_edit,
        "create_url": create_url,
        "ref_key": ref_field.key,
        "parent_id": parent_id,
        "more": more,
        "max_items": MAX_ITEMS,
        "next_url": _next(request),
    }


def prep_search(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Suchbox ist keine Tabelle ausgewählt.")}
    field = _field(entity, props.get("field"))
    if not field:
        return {"error": gettext("Die Suchbox braucht ein Suchfeld.")}
    name = filter_param(entity, field)
    target_slug = (props.get("target_page") or "").strip()
    target_page = app.pages.filter(slug=target_slug).first() if target_slug else None
    action_url = reverse("page", args=[app.slug, target_page.slug]) if target_page else ""
    value = request.GET.get(name, "")
    return {
        "entity": entity,
        "name": name,
        "value": value,
        "action_url": action_url,
        "placeholder": props.get("placeholder") or gettext("Suchen …"),
        "field_label": app_i18n.t(field.label),
    }


def prep_stepper(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Status-Leiste ist keine Tabelle ausgewählt.")}
    field = _field(entity, props.get("field"), [Field.CHOICE])
    if not field:
        return {"error": gettext("Die Status-Leiste braucht ein Auswahlfeld.")}
    param = (props.get("param") or "id").strip() or "id"
    record, has_param = _target_record(request, entity, param)
    if not has_param:
        return {
            "entity": entity,
            "record": None,
            "missing": True,
            "param": param,
            "field_label": app_i18n.t(field.label),
        }
    if not record:
        return {"error": gettext("Der ausgewählte Eintrag wurde nicht gefunden.")}
    choices = field.choice_list()
    current = record.data.get(field.key)
    current_idx = choices.index(current) if current in choices else -1
    steps = []
    for i, c in enumerate(choices):
        state = "done" if (current_idx >= 0 and i < current_idx) else ("current" if i == current_idx else "upcoming")
        steps.append({"value": c, "label": display_value(field, c), "state": state, "num": i + 1})
    return {
        "entity": entity,
        "record": record,
        "field_label": app_i18n.t(field.label),
        "steps": steps,
        "editable": entity.allow_edit,
        **_urls(request, app, block),
    }


def handle_stepper(app, block, payload, user):
    from .scripting.ops import OpsError, TableOps

    props = block["props"]
    entity = _entity(app, props.get("entity"))
    field = _field(entity, props.get("field"), [Field.CHOICE])
    if not entity or not field or not isinstance(payload, dict) or payload.get("op") != "step":
        raise OpsError(gettext("Unbekannte Aktion."))
    record = _record(entity, payload.get("record"))
    value = payload.get("value")
    if value not in field.choice_list():
        raise OpsError(gettext("Ungültiger Status."))
    TableOps(app, user=user, enforce_flags=True).update(entity.slug, record.pk, {field.key: value})
    return {"ok": True, "value": value}


def prep_csv_import(request, app, block):
    entity = _entity(app, block["props"].get("entity"))
    if not entity:
        return {"error": gettext("Für diesen CSV-Import ist keine Tabelle ausgewählt.")}
    if not entity.allow_create or not getattr(request.user, "is_authenticated", False):
        return {"entity": entity, "href": ""}
    return {"entity": entity, "href": reverse("entity_import", args=[app.slug, entity.slug]), "next": _next(request)}


# ---------- Registrierung ----------

FIELD = {"type": "field"}

register("details", _("Aufklappbereich"), "🔽", [
    {"key": "title", "label": _("Überschrift (immer sichtbar)"), "type": "text", "default": _("Mehr erfahren")},
    {"key": "text", "label": _("Text (aufgeklappt)"), "type": "textarea", "default": _("Text")},
    {"key": "open", "label": _("Anfangs aufgeklappt"), "type": "checkbox", "default": False},
], category="Inhalt", hint=_("Text zum Auf- und Zuklappen, z. B. für Fragen und Antworten"))

register("filter", _("Filterleiste"), "🔎", [
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "field", "label": _("Filter nach Feld"), **FIELD},
    {"key": "field2", "label": _("Zweites Feld (optional)"), **FIELD},
    {"key": "field3", "label": _("Drittes Feld (optional)"), **FIELD},
    {"key": "field4", "label": _("Viertes Feld (optional)"), **FIELD},
], prep_filter, "Daten", _("Filtert alle Listen, Karten und Auswertungen dieser Tabelle auf der Seite"))

register("calendar", _("Kalender"), "📅", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "date_field", "label": _("Datumsfeld (Beginn)"), **FIELD},
    {"key": "end_field", "label": _("Enddatum (optional, für mehrtägige Einträge)"), **FIELD},
    {"key": "label_field", "label": _("Beschriftung (leer: erstes Feld)"), **FIELD},
    {"key": "color_field", "label": _("Farbe nach Auswahlfeld (optional)"), **FIELD},
    {"key": "create_links", "label": _("„+“ an jedem Tag zum Anlegen"), "type": "checkbox", "default": True},
], prep_calendar, "Planung", _("Einträge im Monatskalender nach einem Datumsfeld"))

register("checklist", _("Checkliste"), "☑️", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "field", "label": _("Erledigt-Feld (Ja/Nein)"), **FIELD},
    {"key": "label_field", "label": _("Beschriftung (leer: erstes Feld)"), **FIELD},
    {"key": "detail", "label": _("Zusatzinfo (optional)"), **FIELD},
    {"key": "hide_done", "label": _("Erledigte ausblenden"), "type": "checkbox", "default": False},
], prep_checklist, "Planung", _("Einträge per Häkchen abhaken, mit Fortschritt"), action=handle_checklist)

register("sliders", _("Schieberegler"), "🎚️", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "field", "label": _("Zahlenfeld, das der Regler ändert"), **FIELD},
    {"key": "label_field", "label": _("Beschriftung (leer: erstes Feld)"), **FIELD},
    {"key": "min", "label": _("Kleinster Wert"), "type": "number", "default": 0},
    {"key": "max", "label": _("Größter Wert"), "type": "number", "default": 100},
    {"key": "step", "label": _("Schrittweite"), "type": "number", "default": 5},
    {"key": "unit", "label": _("Einheit (optional, z. B. %)"), "type": "text", "default": ""},
], prep_sliders, "Daten", _("Zahlenwerte von Einträgen direkt per Regler ändern"), action=handle_sliders)

register("pivot", _("Kreuztabelle"), "🧮", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "row_field", "label": _("Zeilenfeld"), **FIELD},
    {"key": "col_field", "label": _("Spaltenfeld (optional)"), **FIELD},
    {"key": "agg", "label": _("Auswertung"), "type": "select", "default": "count",
     "options": [["count", _("Anzahl")], ["sum", _("Summe")], ["avg", _("Durchschnitt")]]},
    {"key": "value_field", "label": _("Zahlenfeld (für Summe/Durchschnitt)"), **FIELD},
    {"key": "show_totals", "label": _("Summen anzeigen"), "type": "checkbox", "default": True},
], prep_pivot, "Auswertung", _("Pivot-Auswertung nach Zeilen- und Spaltenfeld"))

register("gantt", _("Zeitstrahl"), "📐", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "start_field", "label": _("Startdatum"), **FIELD},
    {"key": "end_field", "label": _("Enddatum (optional)"), **FIELD},
    {"key": "label_field", "label": _("Beschriftung (leer: erstes Feld)"), **FIELD},
    {"key": "group_field", "label": _("Gruppierung (optional)"), **FIELD},
    {"key": "color_field", "label": _("Farbe nach Auswahlfeld (optional)"), **FIELD},
], prep_gantt, "Planung", _("Einträge als Balken auf einer Zeitleiste (4 Wochen)"))

register("detail", _("Detailansicht"), "🪪", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "param", "label": _("URL-Parameter (Standard: id)"), "type": "text", "default": "id"},
    {"key": "show_actions", "label": _("Bearbeiten-/Löschen-Links anzeigen"), "type": "checkbox", "default": True},
], prep_detail, "Daten", _("Zeigt alle Felder eines einzelnen Datensatzes (?id=…)"))

register("related_list", _("Unterliste"), "🔗", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Zieltabelle"), "type": "entity"},
    {"key": "ref_field", "label": _("Verweisfeld auf Haupttabelle"), **FIELD},
    {"key": "param", "label": _("URL-Parameter der Haupt-ID (Standard: id)"), "type": "text", "default": "id"},
    {"key": "show_add", "label": _("„+ Neu“-Link anzeigen"), "type": "checkbox", "default": True},
], prep_related_list, "Daten", _("Verknüpfte Einträge zum aktuellen Datensatz (?id=…)"))

register("search", _("Suchbox"), "🔍", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "field", "label": _("Suchfeld"), **FIELD},
    {"key": "target_page", "label": _("Zielseite (leer: aktuelle Seite)"), "type": "page"},
    {"key": "placeholder", "label": _("Platzhaltertext"), "type": "text", "default": _("Suchen …")},
], prep_search, "Daten", _("Schnellsuche über ein Feld (optional mit Sprung auf Zielseite)"))

register("stepper", _("Status-Leiste"), "🚦", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "field", "label": _("Status-Auswahlfeld"), **FIELD},
    {"key": "param", "label": _("URL-Parameter der Datensatz-ID (Standard: id)"), "type": "text", "default": "id"},
], prep_stepper, "Planung", _("Fortschritts- und Freigabeschritte eines Datensatzes (?id=…)"), action=handle_stepper)

register("csv_import", _("CSV-Import"), "⬆️", [
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "label", "label": _("Beschriftung"), "type": "text", "default": _("CSV-Datei importieren")},
], prep_csv_import, "Daten", _("Einträge aus einer CSV-Datei in diese Tabelle laden"))

