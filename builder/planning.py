"""Planungs-Bausteine: Einsatzplanung per Drag-and-drop, Wochenübersicht und Kanban-Board.

Die Bausteine kennen keine festen Tabellen. Sie arbeiten mit drei Rollen, die der Designer
festlegt:

- Quelle (wen einplanen, z. B. Mitarbeitende),
- Ziel (wohin, z. B. Schichten) mit Kapazität und optional einer Gruppe (z. B. Linie) mit Priorität,
- Zuordnung (eine Tabelle mit Verweisen auf Quelle und Ziel, optional mit Datum: Einsätze).

Gespeichert wird über TableOps mit den Rechten der angemeldeten Person; es gelten also
dieselben Prüfungen und dasselbe Änderungsprotokoll wie bei Formularen und Skripten.
"""
from datetime import date, timedelta

from django.db.models import TextField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext, ngettext
from django.utils.translation import gettext_lazy as _

from .blocks import _entity, display_value, filtered, register
from .models import Field, Record

DAY_PARAM = "datum"     # ?datum=2026-11-19: Tag der Einsatzplanung
WEEK_PARAM = "woche"    # ?woche=2026-11-16: irgendein Tag der gewünschten Woche
MAX_SOURCES = 500
MAX_TARGETS = 300
OVERBOOK = ("warn", "block", "allow")


# ---------- Hilfen ----------

def parse_day(raw, default=None):
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return default


def _field(entity, key, types=None):
    if not entity or not key:
        return None
    f = next((f for f in entity.fields.all() if f.key == key), None)
    return f if f and (not types or f.type in types) else None


def _number(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value):
    number = _number(value)
    return int(number) if number is not None else None


def page_slug(request, app):
    """Seite, auf der der Baustein gerade gezeigt wird (leer in der Vorschau des Designers)."""
    match = getattr(request, "resolver_match", None)
    if not match or match.url_name not in ("page", "page_block"):
        return ""
    if match.kwargs.get("page"):
        return match.kwargs["page"]
    home = app.home_page
    return home.slug if home else ""


def _urls(request, app, block):
    """Adressen für Aktionen und Neuladen. Ohne Seite (Vorschau) ist der Baustein nur zum Ansehen."""
    slug = page_slug(request, app)
    if not slug or not request.user.is_authenticated:
        return {}
    try:
        return {"action_url": reverse("block_action", args=[app.slug, slug, block["id"]]),
                "reload_url": reverse("page_block", args=[app.slug, slug, block["id"]])}
    except NoReverseMatch:
        return {}


def _state(count, capacity):
    if not capacity:
        return "none"
    if count > capacity:
        return "over"
    if count == capacity:
        return "full"
    return "open" if count else "empty"


def weekday_label(day, fmt="D d.m."):
    return date_format(day, fmt)


# ---------- Konfiguration aus den Einstellungen ----------

class Plan:
    """Aufgelöste Einstellungen eines Planungs-Bausteins (Einsatzplanung oder Wochenübersicht)."""

    def __init__(self, app, props):
        self.app = app
        self.props = props
        self.source = _entity(app, props.get("source"))
        self.target = _entity(app, props.get("target"))
        self.link = _entity(app, props.get("link"))
        self.source_label = _field(self.source, props.get("source_label"))
        self.source_info = _field(self.source, props.get("source_info"))
        self.source_active = _field(self.source, props.get("source_active"), [Field.BOOL])
        self.capacity = _field(self.target, props.get("capacity_field"), [Field.NUMBER, Field.DECIMAL])
        self.group = _field(self.target, props.get("group_field"), [Field.REFERENCE, Field.CHOICE, Field.TEXT])
        group_entity = self.group.reference if self.group and self.group.type == Field.REFERENCE else None
        self.priority = _field(group_entity, props.get("priority_field"), [Field.NUMBER, Field.DECIMAL])
        self.link_source = _field(self.link, props.get("link_source"), [Field.REFERENCE])
        self.link_target = _field(self.link, props.get("link_target"), [Field.REFERENCE])
        self.link_date = _field(self.link, props.get("link_date"), [Field.DATE])
        self.overbook = props.get("overbook") if props.get("overbook") in OVERBOOK else "warn"

    def error(self, need_source=True):
        if not self.target:
            return gettext("Wähle die Tabelle mit den Zielen (z. B. Schichten).")
        if need_source and not self.source:
            return gettext("Wähle die Tabelle mit den Einträgen, die eingeplant werden (z. B. Personen).")
        if not self.link:
            return gettext("Wähle die Tabelle, in der die Zuordnungen gespeichert werden (z. B. Einsätze).")
        if not self.link_target or self.link_target.reference_id != self.target.pk:
            return gettext("Die Zuordnungs-Tabelle braucht ein Verweisfeld auf die Ziel-Tabelle.")
        if need_source and (not self.link_source or self.link_source.reference_id != self.source.pk):
            return gettext("Die Zuordnungs-Tabelle braucht ein Verweisfeld auf die Quell-Tabelle.")
        return None

    # --- Ziele und Gruppen ---

    def targets(self):
        """Ziele mit Gruppe und Priorität, wichtigste Gruppe zuerst."""
        records = list(self.target.records.order_by("id")[:MAX_TARGETS])
        groups = {}
        if self.group and self.group.type == Field.REFERENCE:
            ids = {_int(r.data.get(self.group.key)) for r in records} - {None}
            for g in Record.objects.filter(pk__in=ids).select_related("entity"):
                prio = _number(g.data.get(self.priority.key)) if self.priority else None
                groups[g.pk] = {"key": g.pk, "label": str(g), "priority": prio}
        elif self.group and self.group.type == Field.CHOICE:
            for index, choice in enumerate(self.group.choice_list(), start=1):
                groups[choice] = {"key": choice, "label": display_value(self.group, choice), "priority": None,
                                  "order": index}
        result = []
        for r in records:
            raw = r.data.get(self.group.key) if self.group else None
            key = _int(raw) if self.group and self.group.type == Field.REFERENCE else raw
            group = groups.get(key) or {"key": key or "", "label": str(raw or "") or gettext("Ohne Gruppe"),
                                        "priority": None}
            capacity = _int(r.data.get(self.capacity.key)) if self.capacity else None
            result.append({"id": r.pk, "label": str(r), "capacity": capacity or 0, "group": group})

        def order(item):
            g = item["group"]
            prio = g.get("priority")
            return (prio is None, prio if prio is not None else g.get("order", 0), g["label"], item["id"])
        result.sort(key=order)
        return result

    # --- Zuordnungen ---

    def links(self, first=None, last=None):
        """Zuordnungen als Liste (id, ziel_id, quell_id, tag). Mit Datum nur im Zeitraum."""
        records = self.link.records.all()
        if self.link_date and first:
            key = self.link_date.key
            records = (records.annotate(_d=Cast(KeyTextTransform(key, "data"), TextField()))
                       .filter(_d__gte=first.isoformat(), _d__lte=(last or first).isoformat()))
        result = []
        for pk, data in records.values_list("pk", "data")[:20000]:
            target = _int(data.get(self.link_target.key))
            source = _int(data.get(self.link_source.key)) if self.link_source else None
            day = parse_day(data.get(self.link_date.key)) if self.link_date else None
            if target is not None:
                result.append((pk, target, source, day))
        return result

    def source_labels(self, ids):
        if not self.source:
            return {}
        records = self.source.records.filter(pk__in=ids)
        return {r.pk: self.label_of(r) for r in records}

    def label_of(self, record):
        if self.source_label:
            value = display_value(self.source_label, record.data.get(self.source_label.key))
            if value:
                return value
        return str(record)


# ---------- Einsatzplanung ----------

def prep_assign(request, app, block):
    plan = Plan(app, block["props"])
    problem = plan.error()
    if problem:
        return {"error": problem}
    today = timezone.localdate()
    day = parse_day(request.GET.get(DAY_PARAM), today) if plan.link_date else None
    links = plan.links(day, day)
    targets = plan.targets()

    sources = plan.source.records.order_by("id")
    people = []
    labels = {}
    for r in sources[:MAX_SOURCES]:
        if plan.source_active and not r.data.get(plan.source_active.key):
            continue
        labels[r.pk] = plan.label_of(r)
        info = display_value(plan.source_info, r.data.get(plan.source_info.key)) if plan.source_info else ""
        people.append({"id": r.pk, "label": labels[r.pk], "info": info, "count": 0, "where": []})
    people.sort(key=lambda p: p["label"].lower())
    by_id = {p["id"]: p for p in people}
    missing = {s for _pk, _t, s, _d in links if s is not None and s not in labels}
    labels.update(plan.source_labels(missing))  # z. B. inzwischen inaktive Personen

    target_labels = {t["id"]: t["label"] for t in targets}
    slots = {t["id"]: [] for t in targets}
    for pk, target, source, _day in links:
        if target not in slots:
            continue
        slots[target].append({"link": pk, "source": source, "label": labels.get(source, f"#{source}")})
        if source in by_id:
            by_id[source]["count"] += 1
            by_id[source]["where"].append(target_labels[target])

    groups, total = [], {"capacity": 0, "count": 0, "open": 0, "over": 0}
    for t in targets:
        assigned = sorted(slots[t["id"]], key=lambda a: a["label"].lower())
        count, cap = len(assigned), t["capacity"]
        slot = {**t, "assigned": assigned, "count": count, "state": _state(count, cap),
                "open": max(cap - count, 0), "percent": min(round(100 * count / cap), 100) if cap else 0}
        if not groups or groups[-1]["key"] != t["group"]["key"]:
            groups.append({**t["group"], "slots": [], "capacity": 0, "count": 0, "open": 0, "over": 0})
        g = groups[-1]
        g["slots"].append(slot)
        g["capacity"] += cap
        g["count"] += count
        g["open"] += slot["open"]
        g["over"] += max(count - cap, 0) if cap else 0
        total["capacity"] += cap
        total["count"] += count
        total["open"] += slot["open"]
        total["over"] += max(count - cap, 0) if cap else 0
    for rank, g in enumerate(groups, start=1):
        g["rank"] = rank
        g["state"] = _state(g["count"], g["capacity"])
        if g["priority"] is not None:
            g["priority_label"] = _format_priority(g["priority"])

    ctx = {
        "groups": groups, "people": people, "total": total, "unassigned": sum(1 for p in people if not p["count"]),
        "show_priority": bool(plan.priority), **_urls(request, app, block),
    }
    if day:
        ctx.update({
            "day": day.isoformat(), "day_label": date_format(day, "l, j. F Y"),
            "prev_day": (day - timedelta(days=1)).isoformat(), "next_day": (day + timedelta(days=1)).isoformat(),
            "is_today": day == today, "today": today.isoformat(), "day_param": DAY_PARAM,
        })
    return ctx


def _format_priority(value):
    return str(int(value)) if float(value).is_integer() else str(value)


# ---------- Wochenübersicht ----------

def prep_week(request, app, block):
    props = block["props"]
    plan = Plan(app, props)
    problem = plan.error(need_source=False)
    if problem:
        return {"error": problem}
    if not plan.link_date:
        return {"error": gettext("Die Wochenübersicht braucht ein Datumsfeld in der Zuordnungs-Tabelle.")}
    today = timezone.localdate()
    start = parse_day(request.GET.get(WEEK_PARAM) or request.GET.get(DAY_PARAM), today)
    monday = start - timedelta(days=start.weekday())
    days = [monday + timedelta(days=i) for i in range(5 if props.get("weekdays_only") else 7)]
    links = plan.links(days[0], days[-1])
    targets = plan.targets()
    show_names = bool(props.get("show_names")) and plan.link_source is not None and plan.source is not None
    labels = plan.source_labels({s for _pk, _t, s, _d in links if s is not None}) if show_names else {}

    cells = {}
    for _pk, target, source, day in links:
        cells.setdefault((target, day), []).append(labels.get(source, "") if show_names else "")

    link_page = app.pages.filter(slug=props.get("page")).first() if props.get("page") else None
    page_url = reverse("page", args=[app.slug, link_page.slug]) if link_page else ""

    day_totals = [{"day": d, "capacity": 0, "count": 0} for d in days]
    groups, total = [], {"capacity": 0, "count": 0, "open": 0, "over": 0}
    for t in targets:
        row = {**t, "cells": [], "count": 0, "capacity": t["capacity"] * len(days)}
        for i, d in enumerate(days):
            names = sorted(n for n in cells.get((t["id"], d), []) if n) if show_names else []
            count = len(cells.get((t["id"], d), []))
            cap = t["capacity"]
            row["cells"].append({
                "count": count, "capacity": cap, "state": _state(count, cap), "names": names,
                "href": f"{page_url}?{DAY_PARAM}={d.isoformat()}" if page_url else "",
                "title": f"{t['label']} · {date_format(d, 'l, j. F')}: {count}/{cap}",
            })
            row["count"] += count
            day_totals[i]["capacity"] += cap
            day_totals[i]["count"] += count
            total["open"] += max(cap - count, 0)
            total["over"] += max(count - cap, 0) if cap else 0
        row["state"] = _state(row["count"], row["capacity"])
        total["capacity"] += row["capacity"]
        total["count"] += row["count"]
        if not groups or groups[-1]["key"] != t["group"]["key"]:
            groups.append({**t["group"], "rows": []})
            if t["group"].get("priority") is not None:
                groups[-1]["priority_label"] = _format_priority(t["group"]["priority"])
        groups[-1]["rows"].append(row)
    for d in day_totals:
        d["state"] = _state(d["count"], d["capacity"])
        d["percent"] = round(100 * d["count"] / d["capacity"]) if d["capacity"] else 0
    week = monday.isocalendar()[1]
    return {
        "days": [{"iso": d.isoformat(), "short": date_format(d, "D"), "date": date_format(d, "d.m."),
                  "today": d == today, "weekend": d.weekday() >= 5} for d in days],
        "groups": groups, "day_totals": day_totals, "total": total, "show_names": show_names,
        "percent": round(100 * total["count"] / total["capacity"]) if total["capacity"] else 0,
        "week_label": gettext("KW %(week)s · %(start)s – %(end)s") % {
            "week": week, "start": date_format(days[0], "d.m."), "end": date_format(days[-1], "d.m.Y")},
        "prev_week": (monday - timedelta(days=7)).isoformat(), "next_week": (monday + timedelta(days=7)).isoformat(),
        "this_week": today.isoformat(), "is_this_week": monday <= today < monday + timedelta(days=7),
        "week_param": WEEK_PARAM, "show_priority": bool(plan.priority), "columns": len(days) + 2,
        "target_name": plan.target.name,
    }


# ---------- Kanban ----------

def prep_kanban(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für dieses Board ist keine Tabelle ausgewählt.")}
    column_field = _field(entity, props.get("field"), [Field.CHOICE])
    if not column_field:
        return {"error": gettext("Das Board braucht ein Auswahlfeld, dessen Werte die Spalten sind.")}
    detail = _field(entity, props.get("detail"))
    limit = max(_int(props.get("limit")) or 0, 0)
    choices = column_field.choice_list()
    columns = {c: {"value": c, "label": display_value(column_field, c), "cards": []} for c in choices}
    loose = {"value": "", "label": gettext("Ohne Zuordnung"), "cards": []}
    records = list(filtered(request, entity).order_by("id")[:MAX_SOURCES])
    from .blocks import reference_labels
    refs = reference_labels([detail], records) if detail else {}
    for r in records:
        value = r.data.get(column_field.key)
        card = {"id": r.pk, "label": str(r),
                "detail": display_value(detail, r.data.get(detail.key), refs) if detail else ""}
        columns.get(value, loose)["cards"].append(card)
    result = list(columns.values())
    if loose["cards"]:
        result.insert(0, loose)
    for column in result:
        column["count"] = len(column["cards"])
        column["over"] = bool(limit and column["value"] and column["count"] > limit)
        column["full"] = bool(limit and column["value"] and column["count"] >= limit)
    return {"columns": result, "limit": limit, "entity": entity,
            "editable": entity.allow_edit, **_urls(request, app, block)}


# ---------- Aktionen aus dem Browser ----------

class Refused(Exception):
    """Aktion abgelehnt. confirm=True: mit force=true darf die Person sie trotzdem ausführen."""

    def __init__(self, title, problems, confirm=False):
        super().__init__(title)
        self.title = title
        self.problems = problems
        self.confirm = confirm

    def payload(self):
        return {"error": str(self.title), "problems": [str(p) for p in self.problems], "confirm": self.confirm}


def handle(app, block, payload, user):
    """Führt eine Aktion eines Planungs-Bausteins aus. Wirft Refused oder OpsError."""
    from .scripting.ops import OpsError, TableOps

    if not isinstance(payload, dict):
        raise OpsError(gettext("Ungültige Daten."))
    ops = TableOps(app, user=user, enforce_flags=True)
    op = str(payload.get("op") or "")
    force = payload.get("force") is True
    if block.get("type") == "kanban":
        if op != "move":
            raise OpsError(gettext("Unbekannte Aktion."))
        return _kanban_move(app, block["props"], payload, ops, force)
    if block.get("type") != "assign":
        raise OpsError(gettext("Dieser Baustein hat keine Aktionen."))
    plan = Plan(app, block["props"])
    problem = plan.error()
    if problem:
        raise OpsError(problem)
    if op == "unassign":
        link = _link_record(plan, payload.get("link"))
        ops.delete(plan.link.slug, link.pk)
        return {"ok": True}
    if op not in ("assign", "move"):
        raise OpsError(gettext("Unbekannte Aktion."))

    target = plan.target.records.filter(pk=_int(payload.get("target"))).first()
    if target is None:
        raise OpsError(gettext("Dieses Ziel gibt es nicht (mehr). Bitte die Seite neu laden."))
    moving = _link_record(plan, payload.get("link")) if op == "move" else None
    if moving:
        source_id = _int(moving.data.get(plan.link_source.key))
        day = parse_day(moving.data.get(plan.link_date.key)) if plan.link_date else None
    else:
        source_id = _int(payload.get("source"))
        day = parse_day(payload.get("day")) if plan.link_date else None
        if plan.link_date and not day:
            raise OpsError(gettext("Es fehlt der Tag, für den eingeplant wird."))
    source = plan.source.records.filter(pk=source_id).first()
    if source is None:
        raise OpsError(gettext("Diesen Eintrag gibt es nicht (mehr). Bitte die Seite neu laden."))
    if moving and _int(moving.data.get(plan.link_target.key)) == target.pk:
        return {"ok": True, "unchanged": True}

    _check(plan, target, source, day, moving, force)
    if moving:
        ops.update(plan.link.slug, moving.pk, {plan.link_target.key: target.pk})
    else:
        data = {plan.link_source.key: source.pk, plan.link_target.key: target.pk}
        if plan.link_date:
            data[plan.link_date.key] = day.isoformat()
        ops.create(plan.link.slug, data)
    return {"ok": True}


def _link_record(plan, raw):
    from .scripting.ops import OpsError

    link = plan.link.records.filter(pk=_int(raw)).first()
    if link is None:
        raise OpsError(gettext("Diese Zuordnung gibt es nicht (mehr). Bitte die Seite neu laden."))
    return link


def _check(plan, target, source, day, moving, force):
    """Kapazität, Doppelbelegung und Priorität prüfen. Harte Fehler immer, Warnungen nur ohne force."""
    links = [link for link in plan.links(day, day) if not moving or link[0] != moving.pk]
    person = plan.label_of(source)
    targets = {t["id"]: t for t in plan.targets()}
    info = targets.get(target.pk) or {"label": str(target), "capacity": 0, "group": {"label": "", "priority": None}}
    where = _where(info)
    when = date_format(day, "D, j. F") if day else ""

    if any(t == target.pk and s == source.pk for _pk, t, s, _d in links):
        raise Refused(gettext("Schon eingeplant"), [
            gettext("%(person)s ist bereits in %(where)s eingeplant.") % {"person": person, "where": where}])

    warnings, title = [], gettext("Bitte prüfen")
    count = sum(1 for _pk, t, _s, _d in links if t == target.pk)
    capacity = info["capacity"]
    if capacity and count >= capacity and plan.overbook != "allow":
        text = gettext("%(where)s ist mit %(count)s von %(capacity)s Plätzen schon voll besetzt.") % {
            "where": where, "count": count, "capacity": capacity}
        if plan.overbook == "block":
            raise Refused(gettext("Kapazität erreicht"), [text])
        warnings.append(text + " " + gettext("Danach wären %(count)s von %(capacity)s Plätzen belegt.") % {
            "count": count + 1, "capacity": capacity})
        title = gettext("Überplanung")

    if plan.props.get("double_check", True):
        others = [targets.get(t) for _pk, t, s, _d in links if s == source.pk and t != target.pk]
        for other in [o for o in others if o]:
            text = (gettext("%(person)s ist %(when)s schon in %(where)s eingeplant.")
                    if when else gettext("%(person)s ist schon in %(where)s eingeplant.")) % {
                "person": person, "when": when, "where": _where(other)}
            warnings.append(text)

    prio = info["group"].get("priority")
    if plan.props.get("priority_check", True) and prio is not None:
        counts = {}
        for _pk, t, _s, _d in links:
            counts[t] = counts.get(t, 0) + 1
        open_by_group = {}
        for t in targets.values():
            p = t["group"].get("priority")
            if p is not None and p < prio and t["capacity"]:
                free = max(t["capacity"] - counts.get(t["id"], 0), 0)
                if free:
                    key = t["group"]["label"]
                    open_by_group[key] = (p, open_by_group.get(key, (p, 0))[1] + free)
        for label, (p, free) in sorted(open_by_group.items(), key=lambda item: item[1][0]):
            warnings.append(ngettext("%(group)s hat Priorität %(prio)s und noch %(free)s offenen Platz.",
                                     "%(group)s hat Priorität %(prio)s und noch %(free)s offene Plätze.", free) % {
                "group": label, "prio": _format_priority(p), "free": free})

    if warnings and not force:
        raise Refused(title, warnings, confirm=True)


def _where(info):
    group = info["group"]["label"] if info.get("group") and info["group"].get("key") not in (None, "") else ""
    return f"„{info['label']}“ ({group})" if group else f"„{info['label']}“"


def _kanban_move(app, props, payload, ops, force):
    from .scripting.ops import OpsError

    entity = _entity(app, props.get("entity"))
    column_field = _field(entity, props.get("field"), [Field.CHOICE])
    if not entity or not column_field:
        raise OpsError(gettext("Das Board ist nicht vollständig eingerichtet."))
    record = entity.records.filter(pk=_int(payload.get("record"))).first()
    if record is None:
        raise OpsError(gettext("Diesen Eintrag gibt es nicht (mehr). Bitte die Seite neu laden."))
    value = str(payload.get("value") or "")
    if value not in column_field.choice_list():
        raise OpsError(gettext("Diese Spalte gibt es nicht."))
    if record.data.get(column_field.key) == value:
        return {"ok": True, "unchanged": True}
    limit = max(_int(props.get("limit")) or 0, 0)
    if limit and not force:
        count = entity.records.filter(**{f"data__{column_field.key}": value}).count()
        if count >= limit:
            raise Refused(gettext("Spalte ist voll"), [
                gettext("In „%(column)s“ sind schon %(count)s von höchstens %(limit)s Einträgen.") % {
                    "column": display_value(column_field, value), "count": count, "limit": limit}], confirm=True)
    ops.update(entity.slug, record.pk, {column_field.key: value})
    return {"ok": True}


# ---------- Registrierung ----------

PLAN_FIELDS = [
    {"key": "target", "label": _("Ziele: Tabelle (z. B. Schichten)"), "type": "entity"},
    {"key": "capacity_field", "label": _("Kapazität der Ziele (Zahlenfeld, z. B. Bedarf)"), "type": "field",
     "of": "target"},
    {"key": "group_field", "label": _("Gruppieren nach (z. B. Linie)"), "type": "field", "of": "target"},
    {"key": "priority_field", "label": _("Priorität der Gruppe (Zahl, 1 = am wichtigsten)"), "type": "field",
     "of": "group_field"},
    {"key": "link", "label": _("Zuordnungen: Tabelle (z. B. Einsätze)"), "type": "entity"},
    {"key": "link_source", "label": _("Zuordnung: Verweis auf die Quelle"), "type": "field", "of": "link"},
    {"key": "link_target", "label": _("Zuordnung: Verweis auf das Ziel"), "type": "field", "of": "link"},
    {"key": "link_date", "label": _("Zuordnung: Datum (optional, Planung je Tag)"), "type": "field", "of": "link"},
]

register("assign", _("Einsatzplanung"), "🧑‍🏭", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "source", "label": _("Quelle: wer wird eingeplant? (z. B. Mitarbeitende)"), "type": "entity"},
    {"key": "source_label", "label": _("Quelle: Name (leer: erstes Feld)"), "type": "field", "of": "source"},
    {"key": "source_info", "label": _("Quelle: Zusatzinfo (z. B. Qualifikation)"), "type": "field", "of": "source"},
    {"key": "source_active", "label": _("Quelle: nur wenn dieses Ja/Nein-Feld gesetzt ist"), "type": "field",
     "of": "source"},
    *PLAN_FIELDS,
    {"key": "overbook", "label": _("Wenn ein Ziel schon voll ist"), "type": "select", "default": "warn",
     "options": [["warn", _("Nachfragen (Popup)")], ["block", _("Verhindern")], ["allow", _("Erlauben")]]},
    {"key": "double_check", "label": _("Nachfragen, wenn jemand am selben Tag schon eingeplant ist"),
     "type": "checkbox", "default": True},
    {"key": "priority_check", "label": _("Nachfragen, wenn eine wichtigere Gruppe noch offene Plätze hat"),
     "type": "checkbox", "default": True},
], prep_assign, "Planung", _("Personen per Drag-and-drop in Schichten oder Termine einplanen"), action=handle)

register("weekplan", _("Wochenübersicht"), "🗓️", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "source", "label": _("Quelle (nur für Namen in den Zellen)"), "type": "entity"},
    *PLAN_FIELDS,
    {"key": "show_names", "label": _("Namen in den Zellen zeigen"), "type": "checkbox", "default": False},
    {"key": "weekdays_only", "label": _("Nur Montag bis Freitag"), "type": "checkbox", "default": False},
    {"key": "page", "label": _("Klick auf eine Zelle öffnet diese Seite (mit ?datum=…)"), "type": "page"},
], prep_week, "Planung", _("Belegung und Kapazität je Tag einer Woche"))

register("kanban", _("Kanban-Board"), "🗃️", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": ""},
    {"key": "entity", "label": _("Tabelle"), "type": "entity"},
    {"key": "field", "label": _("Spalten aus Auswahlfeld (z. B. Status)"), "type": "field"},
    {"key": "detail", "label": _("Zusatzinfo auf der Karte (optional)"), "type": "field"},
    {"key": "limit", "label": _("Höchstens Karten je Spalte (0 = ohne Grenze)"), "type": "number", "default": 0},
], prep_kanban, "Planung", _("Einträge per Drag-and-drop zwischen Status-Spalten verschieben"), action=handle)
