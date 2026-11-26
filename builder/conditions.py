"""Feste Bedingung eines Bausteins: zeigt oder zählt nur Einträge, für die sie gilt.

Eine Bedingung je Zeile, alle müssen zutreffen. Links steht ein Feld (Bezeichnung oder Kurzname),
rechts ein Wert, ein anderes Feld oder ein Datum:

    Status != Behoben
    Priorität = Hoch, Mittel          (eins von mehreren Werten)
    Nächste Fälligkeit < heute
    Datum >= monatsanfang
    Bestand < Mindestbestand          (zwei Felder vergleichen)
    Bemerkung ist leer
    Erledigt = nein

Datumswörter: heute, heute+7, heute-30, wochenanfang, monatsanfang, quartalsanfang, jahresanfang
(englisch: today, weekstart, monthstart, quarterstart, yearstart; is empty, is not empty, contains).

Ein Baustein mit Bedingung legt sie während seines Renderns am Request ab (siehe active()).
filtered() in blocks.py wendet sie dann auf seine Tabelle an. So gilt die Bedingung für jeden
Baustein, der seine Einträge über filtered() holt, ohne dass jeder Baustein sie kennen muss.
"""
import re
from contextlib import contextmanager
from datetime import date, timedelta

from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .models import Field

_ATTR = "baukasten_condition"
OPERATORS = [("ist nicht leer", "notempty"), ("is not empty", "notempty"), ("ist leer", "empty"), ("is empty", "empty"),
             ("enthält", "contains"), ("contains", "contains"), ("!=", "ne"), ("≠", "ne"),
             ("<=", "le"), ("≤", "le"), (">=", "ge"), ("≥", "ge"), ("=", "eq"), ("<", "lt"), (">", "gt")]
_OP_RE = re.compile("|".join(re.escape(op) for op, _k in OPERATORS))
_DATE_WORD = re.compile(r"^(heute|today|wochenanfang|weekstart|monatsanfang|monthstart|quartalsanfang|quarterstart|"
                        r"jahresanfang|yearstart)\s*(?:([+-])\s*(\d{1,4}))?$",
                        re.IGNORECASE)
MAX_LINES = 10


class ConditionError(ValueError):
    pass


def _find_field(fields, name):
    name = name.strip()
    wanted = slugify(name).replace("-", "_")
    for f in fields:
        if f.key == name or f.label.strip().lower() == name.lower() or f.key == wanted:
            return f
    return None


def parse(text, entity):
    """Liste von (Feld, Operator, rechte Seite). rechte Seite: ("field", Feld) | ("value", [Texte])."""
    if not (text or "").strip():
        return []
    fields = list(entity.fields.all())
    result = []
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip() and not ln.strip().startswith("#")]
    for line in lines[:MAX_LINES]:
        match = _OP_RE.search(line)
        if not match:
            raise ConditionError(_("Bedingung „%(line)s“: Vergleich fehlt (=, !=, <, >, <=, >=, enthält, ist leer).")
                                 % {"line": line})
        op = dict(OPERATORS)[match.group(0)]
        left, right = line[:match.start()].strip(), line[match.end():].strip()
        field = _find_field(fields, left)
        if not field:
            raise ConditionError(_("Bedingung „%(line)s“: Ein Feld „%(name)s“ gibt es in „%(table)s“ nicht.")
                                 % {"line": line, "name": left, "table": entity.name})
        if op in ("empty", "notempty"):
            result.append((field, op, ("value", [])))
            continue
        other = _find_field(fields, right) if right else None
        if other and other is not field:
            result.append((field, op, ("field", other)))
        else:
            values = [v.strip() for v in right.split(",")] if op in ("eq", "ne") else [right]
            result.append((field, op, ("value", [v for v in values if v != ""] or [""])))
    return result


def _date_word(text, today):
    m = _DATE_WORD.match(text.strip())
    if not m:
        return None
    word = {"today": "heute", "weekstart": "wochenanfang", "monthstart": "monatsanfang", "quarterstart": "quartalsanfang",
            "yearstart": "jahresanfang"}.get(m.group(1).lower(), m.group(1).lower())
    if word == "heute":
        base = today
    elif word == "wochenanfang":
        base = today - timedelta(days=today.weekday())
    elif word == "monatsanfang":
        base = today.replace(day=1)
    elif word == "quartalsanfang":
        base = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    else:
        base = date(today.year, 1, 1)
    if m.group(2):
        days = int(m.group(3))
        base = base + timedelta(days=days if m.group(2) == "+" else -days)
    return base.isoformat()


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _normalize(field, value, today):
    """Wert für den Vergleich: Zahl, ISO-Datum, True/False oder Text in Kleinbuchstaben."""
    if value in (None, ""):
        return None
    if field.type in (Field.NUMBER, Field.DECIMAL):
        return _number(value)
    if field.type == Field.REFERENCE:
        return _number(value)
    if field.type == Field.DATE:
        text = str(value).strip()
        return _date_word(text, today) or text[:10]
    if field.type == Field.BOOL:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "ja", "yes", "wahr", "x")
    return str(value).strip().lower()


def _compare(op, left, right):
    if op == "contains":
        return left is not None and right is not None and str(right) in str(left)
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if left is None or right is None:
        return False
    try:
        return {"lt": left < right, "le": left <= right, "gt": left > right, "ge": left >= right}[op]
    except TypeError:
        return False


def matches(conditions, data, today=None):
    today = today or timezone.localdate()
    for field, op, (kind, rhs) in conditions:
        left = _normalize(field, data.get(field.key), today)
        if op == "empty":
            if left is not None and left is not False:
                return False
            continue
        if op == "notempty":
            if left is None:
                return False
            continue
        if kind == "field":
            if not _compare(op, left, _normalize(rhs, data.get(rhs.key), today)):
                return False
            continue
        if field.type == Field.BOOL and left is None:
            left = False
        rights = [_normalize(field, v, today) for v in rhs]
        if op == "eq":
            if left not in rights:
                return False
        elif op == "ne":
            if left in rights:
                return False
        elif not _compare(op, left, rights[0]):
            return False
    return True


def apply(records, entity, conditions):
    if not conditions:
        return records
    today = timezone.localdate()
    keep = [pk for pk, data in records.values_list("pk", "data").iterator() if matches(conditions, data or {}, today)]
    return records.filter(pk__in=keep)


def current(request, entity):
    """Bedingung des gerade gerenderten Bausteins, falls sie für diese Tabelle gilt."""
    active_cond = getattr(request, _ATTR, None) if request is not None else None
    if active_cond and active_cond[0] == entity.pk:
        return active_cond[1]
    return None


@contextmanager
def active(request, app, block):
    """Legt die Bedingung des Bausteins für die Dauer seines Renderns am Request ab.

    Wirft ConditionError, wenn die Bedingung nicht verstanden wird."""
    props = block.get("props") or {}
    text = (props.get("where") or "").strip()
    if not text or request is None:
        yield
        return
    from .blocks import _entity

    entity = _entity(app, props.get("entity"))
    if not entity:
        yield
        return
    conditions = parse(text, entity)
    previous = getattr(request, _ATTR, None)
    setattr(request, _ATTR, (entity.pk, conditions))
    try:
        yield
    finally:
        setattr(request, _ATTR, previous)


WHERE_SPEC = {
    "key": "where", "label": gettext_lazy("Nur Einträge, für die gilt (optional)"), "type": "textarea", "default": "",
    "help": gettext_lazy("Eine Bedingung je Zeile, z. B. „Status != Erledigt“, „Fällig < heute“, „Datum >= monatsanfang“ "
              "oder „Bestand < Mindestbestand“."),
}
# Bausteine, deren Einträge über filtered() kommen und die darum eine Bedingung haben können
WHERE_TYPES = ("table", "cards", "stat", "progress", "chart", "donut", "timeline", "line", "kanban", "checklist",
               "calendar", "gantt", "pivot", "scatter", "boxplot", "histogram", "heatmap", "report_feed", "sliders")
