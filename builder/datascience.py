"""Data-Science-Visualisierungen: Streudiagramm (Scatter/Bubble), Boxplot, Heatmap/Korrelation und Spec-Chart."""
import json
import math
from urllib.parse import urlencode

from django.utils.translation import gettext, gettext_lazy as _

from . import app_i18n, datasources
from .blocks import ENTITY, _entity, _format_number, filter_param, filtered, register
from .models import DataQuery, Field

FIELD = {"type": "field"}


def _num_fields(entity):
    return list(entity.fields.filter(type__in=[Field.NUMBER, Field.DECIMAL]))


def _to_float(val):
    if val is None or val == "" or isinstance(val, bool):
        return None
    try:
        num = float(val)
        return num if math.isfinite(num) else None
    except (TypeError, ValueError):
        return None


def _filter_href(request, param, value):
    query = request.GET.copy() if hasattr(request, "GET") else {}
    str_val = str(value)
    if query.get(param) == str_val:
        query.pop(param, None)
    else:
        query[param] = str_val
    encoded = urlencode(query, doseq=True)
    path = getattr(request, "path", "") or ""
    return f"{path}?{encoded}" if encoded else path


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None, None, None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 1e-12 or syy <= 1e-12:
        return 0.0, 0.0, my
    slope = sxy / sxx
    intercept = my - slope * mx
    r = max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))
    return r, slope, intercept


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return sorted_vals[low]
    return sorted_vals[low] + (sorted_vals[high] - sorted_vals[low]) * (pos - low)


# ---------- 1. Streudiagramm & Bubble-Chart ----------

def prep_scatter(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für dieses Streudiagramm ist keine Tabelle ausgewählt.")}
    x_field = entity.fields.filter(key=props.get("x_field"), type__in=[Field.NUMBER, Field.DECIMAL]).first()
    y_field = entity.fields.filter(key=props.get("y_field"), type__in=[Field.NUMBER, Field.DECIMAL]).first()
    if not x_field or not y_field:
        return {"error": gettext("Für das Streudiagramm werden zwei Zahlenfelder (X und Y) benötigt.")}
    color_field = entity.fields.filter(key=props.get("color_field")).first() if props.get("color_field") else None
    size_field = (entity.fields.filter(key=props.get("size_field"), type__in=[Field.NUMBER, Field.DECIMAL]).first()
                  if props.get("size_field") else None)
    label_field = entity.fields.filter(key=props.get("label_field")).first() if props.get("label_field") else None

    records = list(filtered(request, entity)[:500])
    raw_points = []
    groups = {}
    for rec in records:
        x = _to_float(rec.data.get(x_field.key))
        y = _to_float(rec.data.get(y_field.key))
        if x is None or y is None:
            continue
        grp = str(rec.data.get(color_field.key) or gettext("Ohne")) if color_field else ""
        if grp and grp not in groups:
            groups[grp] = (len(groups) % 5) + 1
        sz = _to_float(rec.data.get(size_field.key)) if size_field else None
        lbl = str(rec.data.get(label_field.key) or rec) if label_field else str(rec)
        raw_points.append({"pk": rec.pk, "x": x, "y": y, "group": grp, "tone": groups.get(grp, 1), "size": sz, "label": lbl})

    width, height, pad = 600, 260, 28
    if not raw_points:
        return {
            "entity": entity, "x_label": app_i18n.t(x_field.label), "y_label": app_i18n.t(y_field.label),
            "points": [], "width": width, "height": height, "empty": True,
        }

    xs = [p["x"] for p in raw_points]
    ys = [p["y"] for p in raw_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    sizes = [p["size"] for p in raw_points if p["size"] is not None]
    min_s, max_s = (min(sizes), max(sizes)) if sizes else (0.0, 1.0)
    span_s = (max_s - min_s) or 1.0

    def sx(val):
        return round(pad + (val - min_x) / span_x * (width - 2 * pad), 1)

    def sy(val):
        return round(height - pad - (val - min_y) / span_y * (height - 2 * pad), 1)

    color_param = filter_param(entity, color_field) if color_field else ""
    points = []
    for p in raw_points:
        r = 6.0
        if size_field and p["size"] is not None:
            r = round(4.5 + ((p["size"] - min_s) / span_s) * 8.5, 1)
        tooltip = f"{p['label']}: {app_i18n.t(x_field.label)}={_format_number(round(p['x'], 2))}, {app_i18n.t(y_field.label)}={_format_number(round(p['y'], 2))}"
        if p["group"]:
            tooltip += f" ({p['group']})"
        points.append({
            "cx": sx(p["x"]), "cy": sy(p["y"]), "r": r, "tone": p["tone"],
            "title": tooltip, "group": p["group"],
            "href": _filter_href(request, color_param, p["group"]) if color_field else f"?id={p['pk']}",
        })

    trend = None
    if props.get("trendline", True) and len(raw_points) >= 2:
        r_val, slope, intercept = _pearson(xs, ys)
        if r_val is not None:
            y1 = slope * min_x + intercept
            y2 = slope * max_x + intercept
            trend = {
                "x1": sx(min_x), "y1": max(pad, min(height - pad, sy(y1))),
                "x2": sx(max_x), "y2": max(pad, min(height - pad, sy(y2))),
                "r": _format_number(round(r_val, 3)),
                "r2": _format_number(round(r_val ** 2, 3)),
            }

    legend = [
        {"label": g, "tone": t, "href": _filter_href(request, color_param, g)}
        for g, t in groups.items()
    ]
    return {
        "entity": entity,
        "x_label": app_i18n.t(x_field.label),
        "y_label": app_i18n.t(y_field.label),
        "min_x": _format_number(round(min_x, 2)), "max_x": _format_number(round(max_x, 2)),
        "min_y": _format_number(round(min_y, 2)), "max_y": _format_number(round(max_y, 2)),
        "points": points, "trend": trend, "legend": legend,
        "count": len(points), "width": width, "height": height, "empty": False,
    }


# ---------- 2. Boxplot & Verteilungs-Baustein ----------

def prep_boxplot(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diesen Boxplot ist keine Tabelle ausgewählt.")}
    field = entity.fields.filter(key=props.get("field"), type__in=[Field.NUMBER, Field.DECIMAL]).first()
    if not field:
        return {"error": gettext("Für den Boxplot wird ein Zahlenfeld benötigt.")}
    group_field = entity.fields.filter(key=props.get("group_field")).first() if props.get("group_field") else None

    buckets = {}
    for rec in filtered(request, entity)[:1000]:
        val = _to_float(rec.data.get(field.key))
        if val is None:
            continue
        grp = str(rec.data.get(group_field.key) or gettext("Ohne")) if group_field else app_i18n.t(field.label)
        buckets.setdefault(grp, []).append(val)

    if not buckets:
        return {"entity": entity, "field_label": app_i18n.t(field.label), "rows": [], "empty": True}

    all_vals = [v for vals in buckets.values() for v in vals]
    g_min, g_max = min(all_vals), max(all_vals)
    span = (g_max - g_min) or 1.0

    def pct(v):
        return round(max(0.0, min(100.0, (v - g_min) / span * 100.0)), 2)

    group_param = filter_param(entity, group_field) if group_field else ""
    show_outliers = bool(props.get("show_outliers", True))
    rows = []
    for index, (grp, vals) in enumerate(sorted(buckets.items(), key=lambda item: item[0])[:15], start=1):
        s = sorted(vals)
        n = len(s)
        q1 = _quantile(s, 0.25)
        med = _quantile(s, 0.5)
        q3 = _quantile(s, 0.75)
        iqr = q3 - q1
        low_fence = q1 - 1.5 * iqr
        high_fence = q3 + 1.5 * iqr
        non_outliers = [v for v in s if low_fence <= v <= high_fence] or s
        w_low, w_high = min(non_outliers), max(non_outliers)
        outliers = [pct(v) for v in s if v < low_fence or v > high_fence] if show_outliers else []
        mean = sum(s) / n
        rows.append({
            "label": grp, "count": n, "tone": (index - 1) % 5 + 1,
            "href": _filter_href(request, group_param, grp) if group_field else "",
            "q1_pct": pct(q1), "med_pct": pct(med), "q3_pct": pct(q3),
            "box_width": round(max(1.5, pct(q3) - pct(q1)), 2),
            "w_low_pct": pct(w_low), "w_high_pct": pct(w_high),
            "whisker_width": round(max(0.0, pct(w_high) - pct(w_low)), 2),
            "mean_pct": pct(mean),
            "outliers": outliers[:30],
            "min": _format_number(round(s[0], 2)),
            "q1": _format_number(round(q1, 2)),
            "median": _format_number(round(med, 2)),
            "q3": _format_number(round(q3, 2)),
            "max": _format_number(round(s[-1], 2)),
            "mean": _format_number(round(mean, 2)),
        })

    return {
        "entity": entity, "field_label": app_i18n.t(field.label),
        "min_label": _format_number(round(g_min, 2)), "max_label": _format_number(round(g_max, 2)),
        "rows": rows, "empty": False,
    }


# ---------- 3. Heatmap & Korrelationsmatrix ----------

def _heat_class(ratio, negative=False):
    mag = abs(ratio)
    level = 4 if mag >= 0.75 else 3 if mag >= 0.5 else 2 if mag >= 0.25 else 1 if mag > 0.02 else 0
    if level == 0:
        return "heat-0"
    return f"heat-neg-{level}" if negative else f"heat-pos-{level}"


def prep_heatmap(request, app, block):
    props = block["props"]
    entity = _entity(app, props.get("entity"))
    if not entity:
        return {"error": gettext("Für diese Heatmap ist keine Tabelle ausgewählt.")}
    mode = props.get("mode") or "correlation"
    records = list(filtered(request, entity)[:1000])

    if mode == "correlation":
        fields = _num_fields(entity)[:10]
        if len(fields) < 2:
            return {"error": gettext("Für eine Korrelationsmatrix braucht die Tabelle mindestens zwei Zahlenfelder.")}
        labels = [app_i18n.t(f.label) for f in fields]
        matrix_rows = []
        for f1 in fields:
            cells = []
            for f2 in fields:
                if f1.pk == f2.pk:
                    r_val = 1.0
                else:
                    pairs = [
                        (_to_float(rec.data.get(f1.key)), _to_float(rec.data.get(f2.key)))
                        for rec in records
                    ]
                    valid = [(x, y) for x, y in pairs if x is not None and y is not None]
                    r_val = _pearson([x for x, _ in valid], [y for _, y in valid])[0] if len(valid) >= 2 else 0.0
                    r_val = r_val or 0.0
                cells.append({
                    "value": _format_number(round(r_val, 2)),
                    "css": _heat_class(r_val, negative=r_val < 0),
                    "title": f"{app_i18n.t(f1.label)} × {app_i18n.t(f2.label)}: r = {_format_number(round(r_val, 3))}",
                })
            matrix_rows.append({"label": app_i18n.t(f1.label), "cells": cells})
        return {"mode": "correlation", "columns": labels, "rows": matrix_rows, "empty": not records}

    row_field = entity.fields.filter(key=props.get("row_field")).first()
    col_field = entity.fields.filter(key=props.get("col_field")).first()
    if not row_field or not col_field:
        return {"error": gettext("Für die Heatmap im Modus Kreuztabelle werden Zeilen- und Spaltenfeld benötigt.")}
    agg = props.get("agg") if props.get("agg") in ("count", "sum", "avg") else "count"
    val_field = (entity.fields.filter(key=props.get("value_field"), type__in=[Field.NUMBER, Field.DECIMAL]).first()
                 if agg != "count" else None)
    if agg != "count" and not val_field:
        return {"error": gettext("Summe und Durchschnitt brauchen ein Zahlenfeld.")}

    row_keys, col_keys = [], []
    sums, counts = {}, {}
    for rec in records:
        rk = str(rec.data.get(row_field.key) or "–")
        ck = str(rec.data.get(col_field.key) or "–")
        if rk not in row_keys and len(row_keys) < 15:
            row_keys.append(rk)
        if ck not in col_keys and len(col_keys) < 12:
            col_keys.append(ck)
        if rk not in row_keys or ck not in col_keys:
            continue
        num = _to_float(rec.data.get(val_field.key)) if val_field else 1.0
        if num is None:
            continue
        sums[(rk, ck)] = sums.get((rk, ck), 0.0) + num
        counts[(rk, ck)] = counts.get((rk, ck), 0) + 1

    computed = {}
    for rk in row_keys:
        for ck in col_keys:
            c = counts.get((rk, ck), 0)
            s = sums.get((rk, ck), 0.0)
            computed[(rk, ck)] = (s / c if c else 0.0) if agg == "avg" else (s if agg == "sum" else c)

    max_v = max(computed.values(), default=0.0) or 1.0
    r_param = filter_param(entity, row_field)
    row_list = []
    for rk in row_keys:
        cells = []
        for ck in col_keys:
            v = computed.get((rk, ck), 0)
            ratio = v / max_v if max_v else 0.0
            cells.append({
                "value": _format_number(round(v, 2) if isinstance(v, float) else v),
                "css": _heat_class(ratio),
                "title": f"{rk} / {ck}: {_format_number(round(v, 2) if isinstance(v, float) else v)}",
                "href": _filter_href(request, r_param, rk),
            })
        row_list.append({"label": rk, "cells": cells})
    return {"mode": "crosstab", "columns": col_keys, "rows": row_list, "empty": not row_list}


# ---------- 4. Spec-Chart (Vega-Lite-kompatible JSON-Spezifikation auf Tabelle oder DataQuery) ----------

def _load_spec_rows(request, app, props):
    if props.get("query"):
        dq = DataQuery.objects.filter(app=app, slug=props.get("query")).first()
        if not dq:
            return None, gettext("Die gewählte Datenbank-Abfrage gibt es nicht.")
        try:
            res = datasources.run_saved(dq, {})
        except datasources.QueryError as exc:
            return None, str(exc)
        cols = res["columns"]
        return [dict(zip(cols, r)) for r in res["rows"][:500]], None
    entity = _entity(app, props.get("entity"))
    if not entity:
        return None, gettext("Bitte eine Tabelle oder eine Datenbank-Abfrage auswählen.")
    return [r.data for r in filtered(request, entity)[:500]], None


def prep_spec_chart(request, app, block):
    props = block["props"]
    try:
        spec = json.loads(props.get("spec") or "{}")
        if not isinstance(spec, dict):
            raise ValueError
    except ValueError:
        return {"error": gettext("Die Chart-Spezifikation ist kein gültiges JSON-Objekt.")}

    rows, err = _load_spec_rows(request, app, props)
    if err:
        return {"error": err}

    mark = spec.get("mark")
    if isinstance(mark, dict):
        mark = mark.get("type")
    mark = str(mark or "bar").lower()
    if mark not in ("bar", "line", "point", "area"):
        mark = "bar"

    enc = spec.get("encoding") if isinstance(spec.get("encoding"), dict) else {}
    x_enc = enc.get("x") if isinstance(enc.get("x"), dict) else {}
    y_enc = enc.get("y") if isinstance(enc.get("y"), dict) else {}
    x_key = str(x_enc.get("field") or "")
    y_key = str(y_enc.get("field") or "")
    agg = str(y_enc.get("aggregate") or ("count" if not y_key else "sum")).lower()
    if not x_key:
        return {"error": gettext("In der Spezifikation fehlt encoding.x.field.")}

    buckets, counts = {}, {}
    for row in rows:
        xv = str(row.get(x_key) if row.get(x_key) is not None else "–")
        if agg == "count":
            yv = 1.0
        else:
            yv = _to_float(row.get(y_key))
            if yv is None:
                continue
        buckets[xv] = buckets.get(xv, 0.0) + yv
        counts[xv] = counts.get(xv, 0) + 1

    series = []
    for k, total in list(buckets.items())[:24]:
        val = (total / counts[k]) if agg == "avg" and counts.get(k) else total
        series.append((k, val))

    if not series:
        return {"mark": mark, "x_label": x_key, "y_label": y_key or "count", "items": [], "empty": True}

    top = max((abs(v) for _, v in series), default=1.0) or 1.0
    width, height = 600, 190
    step = width / len(series)
    pts = [(round((i + 0.5) * step, 1), round(height - max(0.0, v) / top * (height - 20), 1))
           for i, (_, v) in enumerate(series)]
    line = " ".join(f"{x},{y}" for x, y in pts)
    area = f"{pts[0][0]},{height} {line} {pts[-1][0]},{height}" if pts else ""
    items = [
        {
            "label": k, "value": _format_number(round(v, 2) if isinstance(v, float) else v),
            "percent": round(max(0.0, v) / top * 100),
            "cx": pts[i][0], "cy": pts[i][1],
        }
        for i, (k, v) in enumerate(series)
    ]
    return {
        "mark": mark, "x_label": x_enc.get("title") or x_key,
        "y_label": y_enc.get("title") or y_key or gettext("Anzahl"),
        "items": items, "line": line, "area": area,
        "width": width, "height": height, "empty": False,
    }


# ---------- Registrierung ----------

register("scatter", _("Streudiagramm"), "🫧", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Korrelation")},
    ENTITY,
    {"key": "x_field", "label": _("X-Achse (Zahlenfeld)"), **FIELD},
    {"key": "y_field", "label": _("Y-Achse (Zahlenfeld)"), **FIELD},
    {"key": "color_field", "label": _("Farbe / Cluster nach Feld (optional)"), **FIELD},
    {"key": "size_field", "label": _("Punktgröße nach Zahlenfeld (Bubble-Chart, optional)"), **FIELD},
    {"key": "label_field", "label": _("Beschriftung im Tooltip (optional)"), **FIELD},
    {"key": "trendline", "label": _("Regressionslinie und R² anzeigen"), "type": "checkbox", "default": True},
], prep_scatter, "Auswertung", _("Zwei Zahlenfelder als Punkte oder Bubbles mit Trendlinie und R²"))

register("boxplot", _("Boxplot & Verteilung"), "📦", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Verteilung")},
    ENTITY,
    {"key": "field", "label": _("Zahlenfeld"), **FIELD},
    {"key": "group_field", "label": _("Gruppieren nach Feld (optional)"), **FIELD},
    {"key": "show_outliers", "label": _("Ausreißer (1,5 × IQR) markieren"), "type": "checkbox", "default": True},
], prep_boxplot, "Auswertung", _("Quantile (Q1, Median, Q3), Mittelwert und Ausreißer"))

register("heatmap", _("Heatmap & Korrelation"), "🌡️", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Korrelationsmatrix")},
    ENTITY,
    {"key": "mode", "label": _("Modus"), "type": "select", "default": "correlation",
     "options": [["correlation", _("Korrelationsmatrix (alle Zahlenfelder)")],
                 ["crosstab", _("Heatmap zweier Felder (Zeile × Spalte)")]]},
    {"key": "row_field", "label": _("Zeilenfeld (nur Modus Heatmap)"), **FIELD},
    {"key": "col_field", "label": _("Spaltenfeld (nur Modus Heatmap)"), **FIELD},
    {"key": "agg", "label": _("Berechnung (nur Modus Heatmap)"), "type": "select", "default": "count",
     "options": [["count", _("Anzahl")], ["sum", _("Summe")], ["avg", _("Durchschnitt")]]},
    {"key": "value_field", "label": _("Zahlenfeld (für Summe/Durchschnitt)"), **FIELD},
], prep_heatmap, "Auswertung", _("Pearson-Korrelationsmatrix oder farbcodierte Matrix"))

register("spec_chart", _("Spec-Chart (Vega-Lite)"), "📐", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Auswertung")},
    ENTITY,
    {"key": "query", "label": _("Oder Datenbank-Abfrage (DataQuery)"), "type": "query"},
    {"key": "spec", "label": _("Spezifikation (Vega-Lite JSON)"), "type": "textarea",
     "default": '{\n  "mark": "bar",\n  "encoding": {\n    "x": {"field": "kategorie"},\n    "y": {"aggregate": "count"}\n  }\n}'},
], prep_spec_chart, "Auswertung", _("Deklaratives Diagramm (JSON-Spec) auf Tabelle oder SQL/Databricks-Abfrage"))
