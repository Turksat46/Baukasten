"""Allgemeine Bausteine: Filterleiste, Kalender, Checkliste, Schieberegler, Aufklappbereich.

Filterleiste, Kalender, Checkliste und Schieberegler arbeiten auf einer Tabelle der App.
Die Filterleiste setzt Parameter in der Adresse (?tabelle.feld=wert); alle Bausteine derselben
Tabelle auf der Seite beachten sie (blocks.filtered). Checkliste und Schieberegler speichern
über views.block_action mit den Rechten der Person.
"""
import calendar as pycalendar
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from . import app_i18n
from .blocks import _entity, display_value, filter_param, filtered, reference_labels, register
from .models import Field

MONTH_PARAM = "monat"   # ?monat=2026-11
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
    return request.get_full_path() if hasattr(request, "get_full_path") else ""


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
            "editable": entity.allow_edit, **_urls(request, app, block)}


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

