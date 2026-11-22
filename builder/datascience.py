"""Data-Science-Visualisierungen: Streudiagramm, Boxplot, Heatmap, Histogramm/Drift und Spec-Chart."""
import functools
import json
import math
from urllib.parse import urlencode

from django.conf import settings
from django.utils.translation import gettext, gettext_lazy as _

from . import app_i18n, datasources
from .blocks import ENTITY, LAZY_WITH_QUERY, _entity, _format_number, filter_param, filtered, register
from .models import DataQuery, Field

FIELD = {"type": "field"}
QUERY_OPT = {"key": "query", "label": _("Oder Datenbank-Abfrage (DataQuery)"), "type": "query"}


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
    if not param:
        return ""
    query = request.GET.copy() if hasattr(request, "GET") else {}
    str_val = str(value)
    if query.get(param) == str_val:
        query.pop(param, None)
    else:
        query[param] = str_val
    encoded = urlencode(query, doseq=True)
    path = getattr(request, "path", "") or ""
    return f"{path}?{encoded}" if encoded else path


def _load_source_rows(request, app, props, max_rows=1000):
    """Lädt Zeilen wahlweise aus einer DataQuery (SQL/Databricks) oder einer App-Tabelle (Entity).

    Gibt (rows_als_dicts_mit_optionaler_pk, entity_oder_None, spalten_labels_dict, fehlertext) zurück.
    """
    if props.get("query"):
        dq = DataQuery.objects.filter(app=app, slug=props.get("query")).first()
        if not dq:
            return None, None, {}, gettext("Die gewählte Datenbank-Abfrage gibt es nicht.")
        # Nicht im Server warten (das hielte einen Thread fest): Läuft die Abfrage noch,
        # kommt QueryBusy, und der Baustein zeigt „wird geladen“ (siehe with_loading).
        wait = 0 if getattr(settings, "BAUKASTEN_LAZY_QUERIES", True) else None
        try:
            res = datasources.run_saved(dq, {}, wait=wait)
        except datasources.QueryBusy:
            raise
        except datasources.QueryError as exc:
            return None, None, {}, str(exc)
        cols = list(res["columns"])
        rows = []
        for idx, raw in enumerate(res["rows"][:max_rows]):
            # Abfragen liefern Zeilen als Dictionaries {Spalte: Wert}; Listen nur der Vollständigkeit halber.
            data = dict(raw) if isinstance(raw, dict) else dict(zip(cols, raw))
            first = data.get(cols[0]) if cols else None
            rows.append({"_pk": idx + 1, "data": data, "label": str(first) if first not in (None, "") else f"#{idx + 1}"})
        return rows, None, {c: c for c in cols}, None
    entity = _entity(app, props.get("entity"))
    if not entity:
        return None, None, {}, None
    labels = {f.key: app_i18n.t(f.label) for f in entity.fields.all()}
    rows = [{"_pk": r.pk, "data": r.data, "label": str(r)} for r in filtered(request, entity)[:max_rows]]
    return rows, entity, labels, None


def _resolve_field_key(entity, labels, key, numeric=False):
    key = str(key or "").strip()
    if not key:
        return None, ""
    if entity is not None:
        qs = entity.fields.filter(key=key)
        if numeric:
            qs = qs.filter(type__in=[Field.NUMBER, Field.DECIMAL])
        f = qs.first()
        return (f.key, app_i18n.t(f.label)) if f else (None, "")
    return (key, labels.get(key, key)) if key in labels else (key, key)


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
    rows, entity, labels, err = _load_source_rows(request, app, props, max_rows=500)
    if err:
        return {"error": err}
    if rows is None:
        return {"error": gettext("Für dieses Streudiagramm ist keine Tabelle ausgewählt.")}
    x_key, x_label = _resolve_field_key(entity, labels, props.get("x_field"), numeric=True)
    y_key, y_label = _resolve_field_key(entity, labels, props.get("y_field"), numeric=True)
    if not x_key or not y_key:
        return {"error": gettext("Für das Streudiagramm werden zwei Zahlenfelder (X und Y) benötigt.")}
    color_key, _ = _resolve_field_key(entity, labels, props.get("color_field"))
    size_key, _ = _resolve_field_key(entity, labels, props.get("size_field"), numeric=True)
    label_key, _ = _resolve_field_key(entity, labels, props.get("label_field"))

    raw_points, groups = [], {}
    for row in rows:
        data = row["data"]
        x = _to_float(data.get(x_key))
        y = _to_float(data.get(y_key))
        if x is None or y is None:
            continue
        grp = str(data.get(color_key) or gettext("Ohne")) if color_key else ""
        if grp and grp not in groups:
            groups[grp] = (len(groups) % 5) + 1
        sz = _to_float(data.get(size_key)) if size_key else None
        lbl = str(data.get(label_key) or row["label"]) if label_key else row["label"]
        raw_points.append({"pk": row["_pk"], "x": x, "y": y, "group": grp, "tone": groups.get(grp, 1), "size": sz, "label": lbl})

    width, height, pad_x, pad_y = 480, 240, 24, 20
    if not raw_points:
        return {
            "entity": entity, "x_label": x_label, "y_label": y_label,
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
        return round(pad_x + (val - min_x) / span_x * (width - 2 * pad_x), 1)

    def sy(val):
        return round(height - pad_y - (val - min_y) / span_y * (height - 2 * pad_y), 1)

    color_field = entity.fields.filter(key=color_key).first() if (entity and color_key) else None
    color_param = filter_param(entity, color_field) if color_field else ""
    points = []
    for p in raw_points:
        r = 7.0
        if size_key and p["size"] is not None:
            r = round(5.5 + ((p["size"] - min_s) / span_s) * 9.0, 1)
        tooltip = f"{p['label']}: {x_label}={_format_number(round(p['x'], 2))}, {y_label}={_format_number(round(p['y'], 2))}"
        if p["group"]:
            tooltip += f" ({p['group']})"
        points.append({
            "cx": f"{sx(p['x'])}", "cy": f"{sy(p['y'])}", "r": f"{r}", "tone": p["tone"],
            "title": tooltip, "group": p["group"],
            "href": _filter_href(request, color_param, p["group"]) if color_param else (f"?id={p['pk']}" if entity else "#"),
        })

    trend = None
    if props.get("trendline", True) and len(raw_points) >= 2:
        r_val, slope, intercept = _pearson(xs, ys)
        if r_val is not None:
            y1 = slope * min_x + intercept
            y2 = slope * max_x + intercept
            trend = {
                "x1": f"{sx(min_x)}", "y1": f"{max(pad_y, min(height - pad_y, sy(y1)))}",
                "x2": f"{sx(max_x)}", "y2": f"{max(pad_y, min(height - pad_y, sy(y2)))}",
                "r": _format_number(round(r_val, 3)),
                "r2": _format_number(round(r_val ** 2, 3)),
            }

    legend = [
        {"label": g, "tone": t, "href": _filter_href(request, color_param, g)}
        for g, t in groups.items()
    ]
    return {
        "entity": entity,
        "x_label": x_label,
        "y_label": y_label,
        "min_x": _format_number(round(min_x, 2)), "max_x": _format_number(round(max_x, 2)),
        "min_y": _format_number(round(min_y, 2)), "max_y": _format_number(round(max_y, 2)),
        "points": points, "trend": trend, "legend": legend,
        "count": len(points), "width": width, "height": height, "empty": False,
    }


# ---------- 2. Boxplot & Verteilungs-Baustein ----------

def prep_boxplot(request, app, block):
    props = block["props"]
    rows, entity, labels, err = _load_source_rows(request, app, props, max_rows=1000)
    if err:
        return {"error": err}
    if rows is None:
        return {"error": gettext("Für diesen Boxplot ist keine Tabelle ausgewählt.")}
    f_key, f_label = _resolve_field_key(entity, labels, props.get("field"), numeric=True)
    if not f_key:
        return {"error": gettext("Für den Boxplot wird ein Zahlenfeld benötigt.")}
    g_key, _ = _resolve_field_key(entity, labels, props.get("group_field"))

    buckets = {}
    for row in rows:
        val = _to_float(row["data"].get(f_key))
        if val is None:
            continue
        grp = str(row["data"].get(g_key) or gettext("Ohne")) if g_key else f_label
        buckets.setdefault(grp, []).append(val)

    if not buckets:
        return {"entity": entity, "field_label": f_label, "rows": [], "empty": True}

    all_vals = [v for vals in buckets.values() for v in vals]
    g_min, g_max = min(all_vals), max(all_vals)
    span = (g_max - g_min) or 1.0

    def pct(v):
        return round(max(0.0, min(100.0, (v - g_min) / span * 100.0)), 2)

    group_field = entity.fields.filter(key=g_key).first() if (entity and g_key) else None
    group_param = filter_param(entity, group_field) if group_field else ""
    show_outliers = bool(props.get("show_outliers", True))
    out_rows = []
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
        outliers = [f"{pct(v)}" for v in s if v < low_fence or v > high_fence] if show_outliers else []
        mean = sum(s) / n
        out_rows.append({
            "label": grp, "count": n, "tone": (index - 1) % 5 + 1,
            "href": _filter_href(request, group_param, grp) if group_param else "",
            "q1_pct": f"{pct(q1)}", "med_pct": f"{pct(med)}", "q3_pct": f"{pct(q3)}",
            "box_width": f"{round(max(1.5, pct(q3) - pct(q1)), 2)}",
            "w_low_pct": f"{pct(w_low)}", "w_high_pct": f"{pct(w_high)}",
            "whisker_width": f"{round(max(0.0, pct(w_high) - pct(w_low)), 2)}",
            "mean_pct": f"{pct(mean)}",
            "outliers": outliers[:30],
            "min": _format_number(round(s[0], 2)),
            "q1": _format_number(round(q1, 2)),
            "median": _format_number(round(med, 2)),
            "q3": _format_number(round(q3, 2)),
            "max": _format_number(round(s[-1], 2)),
            "mean": _format_number(round(mean, 2)),
        })

    return {
        "entity": entity, "field_label": f_label,
        "min_label": _format_number(round(g_min, 2)), "max_label": _format_number(round(g_max, 2)),
        "rows": out_rows, "empty": False,
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
    rows, entity, labels, err = _load_source_rows(request, app, props, max_rows=1000)
    if err:
        return {"error": err}
    if rows is None:
        return {"error": gettext("Für diese Heatmap ist keine Tabelle ausgewählt.")}
    mode = props.get("mode") or "correlation"

    if mode == "correlation":
        if entity is not None:
            num_keys = [(f.key, app_i18n.t(f.label)) for f in _num_fields(entity)[:10]]
        else:
            num_keys = []
            for k, lbl in labels.items():
                if any(_to_float(r["data"].get(k)) is not None for r in rows[:20]):
                    num_keys.append((k, lbl))
            num_keys = num_keys[:10]
        if len(num_keys) < 2:
            return {"error": gettext("Für eine Korrelationsmatrix braucht die Tabelle mindestens zwei Zahlenfelder.")}
        col_labels = [lbl for _, lbl in num_keys]
        matrix_rows = []
        for k1, l1 in num_keys:
            cells = []
            for k2, l2 in num_keys:
                if k1 == k2:
                    r_val = 1.0
                else:
                    pairs = [(_to_float(r["data"].get(k1)), _to_float(r["data"].get(k2))) for r in rows]
                    valid = [(x, y) for x, y in pairs if x is not None and y is not None]
                    r_val = _pearson([x for x, _ in valid], [y for _, y in valid])[0] if len(valid) >= 2 else 0.0
                    r_val = r_val or 0.0
                cells.append({
                    "value": _format_number(round(r_val, 2)),
                    "css": _heat_class(r_val, negative=r_val < 0),
                    "title": f"{l1} × {l2}: r = {_format_number(round(r_val, 3))}",
                })
            matrix_rows.append({"label": l1, "cells": cells})
        return {"mode": "correlation", "columns": col_labels, "rows": matrix_rows, "empty": not rows}

    row_key, _ = _resolve_field_key(entity, labels, props.get("row_field"))
    col_key, _ = _resolve_field_key(entity, labels, props.get("col_field"))
    if not row_key or not col_key:
        return {"error": gettext("Für die Heatmap im Modus Kreuztabelle werden Zeilen- und Spaltenfeld benötigt.")}
    agg = props.get("agg") if props.get("agg") in ("count", "sum", "avg") else "count"
    val_key, _ = (_resolve_field_key(entity, labels, props.get("value_field"), numeric=True)
                  if agg != "count" else ("", ""))
    if agg != "count" and not val_key:
        return {"error": gettext("Summe und Durchschnitt brauchen ein Zahlenfeld.")}

    row_keys, col_keys = [], []
    sums, counts = {}, {}
    for r in rows:
        rk = str(r["data"].get(row_key) or "–")
        ck = str(r["data"].get(col_key) or "–")
        if rk not in row_keys and len(row_keys) < 15:
            row_keys.append(rk)
        if ck not in col_keys and len(col_keys) < 12:
            col_keys.append(ck)
        if rk not in row_keys or ck not in col_keys:
            continue
        num = _to_float(r["data"].get(val_key)) if val_key else 1.0
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
    row_field = entity.fields.filter(key=row_key).first() if entity else None
    r_param = filter_param(entity, row_field) if row_field else ""
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


# ---------- 4. Histogramm & Data-Drift (PSI) ----------

def prep_histogram(request, app, block):
    props = block["props"]
    rows, entity, labels, err = _load_source_rows(request, app, props, max_rows=1000)
    if err:
        return {"error": err}
    if rows is None:
        return {"error": gettext("Für dieses Histogramm ist keine Tabelle ausgewählt.")}
    f_key, f_label = _resolve_field_key(entity, labels, props.get("field"), numeric=True)
    if not f_key:
        return {"error": gettext("Für das Histogramm wird ein Zahlenfeld benötigt.")}
    g_key, _ = _resolve_field_key(entity, labels, props.get("group_field"))
    try:
        num_bins = min(max(int(props.get("bins") or 8), 3), 20)
    except (TypeError, ValueError):
        num_bins = 8

    items = []
    group_counts = {}
    for r in rows:
        v = _to_float(r["data"].get(f_key))
        if v is None:
            continue
        grp = str(r["data"].get(g_key) or gettext("Ohne")) if g_key else ""
        if grp:
            group_counts[grp] = group_counts.get(grp, 0) + 1
        items.append((v, grp))

    if not items:
        return {"field_label": f_label, "bins": [], "empty": True}

    vals = [v for v, _ in items]
    low, high = min(vals), max(vals)
    span = (high - low) or 1.0
    step = span / num_bins

    top_groups = [g for g, _ in sorted(group_counts.items(), key=lambda x: -x[1])[:2]]
    compare = len(top_groups) == 2
    g_a, g_b = (top_groups[0], top_groups[1]) if compare else ("", "")

    bin_totals = [0] * num_bins
    bin_a = [0] * num_bins
    bin_b = [0] * num_bins
    for v, grp in items:
        idx = min(num_bins - 1, max(0, int((v - low) / step)))
        bin_totals[idx] += 1
        if compare:
            if grp == g_a:
                bin_a[idx] += 1
            elif grp == g_b:
                bin_b[idx] += 1

    max_bin = max(bin_totals, default=1) or 1
    total_n = len(items)
    total_a = sum(bin_a) or 1
    total_b = sum(bin_b) or 1

    psi_val = None
    drift_label = ""
    drift_tone = "ok"
    if compare and sum(bin_a) >= 2 and sum(bin_b) >= 2:
        psi_sum = 0.0
        for ca, cb in zip(bin_a, bin_b):
            pa = max(0.001, ca / total_a)
            pb = max(0.001, cb / total_b)
            psi_sum += (pa - pb) * math.log(pa / pb)
        psi_val = _format_number(round(psi_sum, 3))
        if psi_sum >= 0.25:
            drift_label = gettext("Starker Drift")
            drift_tone = "warn"
        elif psi_sum >= 0.1:
            drift_label = gettext("Moderater Drift")
            drift_tone = "warn"
        else:
            drift_label = gettext("Stabil")
            drift_tone = "ok"

    bins_out = []
    for i in range(num_bins):
        b_start = low + i * step
        b_end = low + (i + 1) * step
        c = bin_totals[i]
        bins_out.append({
            "range": f"{_format_number(round(b_start, 1))}–{_format_number(round(b_end, 1))}",
            "count": c,
            "percent": round(100 * c / max_bin),
            "share": round(100 * c / total_n),
            "count_a": bin_a[i],
            "count_b": bin_b[i],
            "pct_a": round(100 * bin_a[i] / max_bin),
            "pct_b": round(100 * bin_b[i] / max_bin),
        })

    return {
        "field_label": f_label, "count": total_n, "bins": bins_out,
        "compare": compare, "group_a": g_a, "group_b": g_b,
        "psi": psi_val, "drift_label": drift_label, "drift_tone": drift_tone,
        "empty": False,
    }


# ---------- 5. Spec-Chart (Vega-Lite-kompatible JSON-Spezifikation auf Tabelle oder DataQuery) ----------

def prep_spec_chart(request, app, block):
    props = block["props"]
    try:
        spec = json.loads(props.get("spec") or "{}")
        if not isinstance(spec, dict):
            raise ValueError
    except ValueError:
        return {"error": gettext("Die Chart-Spezifikation ist kein gültiges JSON-Objekt.")}

    rows_meta, _entity_obj, _labels, err = _load_source_rows(request, app, props, max_rows=500)
    if err:
        return {"error": err}
    if rows_meta is None:
        return {"error": gettext("Bitte eine Tabelle oder eine Datenbank-Abfrage auswählen.")}
    rows = [r["data"] for r in rows_meta]

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
            "cx": f"{pts[i][0]}", "cy": f"{pts[i][1]}",
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

def with_loading(prepare):
    """Zeigt „wird geladen“, solange die gewählte Abfrage noch läuft; der Browser fragt dann nach."""
    @functools.wraps(prepare)
    def wrapper(request, app, block):
        try:
            return prepare(request, app, block)
        except datasources.QueryBusy as exc:
            props = block.get("props") or {}
            return {"loading": True, "loading_title": props.get("title") or "", "loading_text": str(exc), "retry": 2}
    return wrapper


LAZY_WITH_QUERY.update({"scatter", "boxplot", "heatmap", "histogram", "spec_chart"})

register("scatter", _("Streudiagramm"), "🫧", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Korrelation")},
    ENTITY, QUERY_OPT,
    {"key": "x_field", "label": _("X-Achse (Zahlenfeld)"), **FIELD},
    {"key": "y_field", "label": _("Y-Achse (Zahlenfeld)"), **FIELD},
    {"key": "color_field", "label": _("Farbe / Cluster nach Feld (optional)"), **FIELD},
    {"key": "size_field", "label": _("Punktgröße nach Zahlenfeld (Bubble-Chart, optional)"), **FIELD},
    {"key": "label_field", "label": _("Beschriftung im Tooltip (optional)"), **FIELD},
    {"key": "trendline", "label": _("Regressionslinie und R² anzeigen"), "type": "checkbox", "default": True},
], with_loading(prep_scatter), "Auswertung", _("Zwei Zahlenfelder als Punkte oder Bubbles mit Trendlinie und R²"))

register("boxplot", _("Boxplot & Verteilung"), "📦", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Verteilung")},
    ENTITY, QUERY_OPT,
    {"key": "field", "label": _("Zahlenfeld"), **FIELD},
    {"key": "group_field", "label": _("Gruppieren nach Feld (optional)"), **FIELD},
    {"key": "show_outliers", "label": _("Ausreißer (1,5 × IQR) markieren"), "type": "checkbox", "default": True},
], with_loading(prep_boxplot), "Auswertung", _("Quantile (Q1, Median, Q3), Mittelwert und Ausreißer"))

register("heatmap", _("Heatmap & Korrelation"), "🌡️", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Korrelationsmatrix")},
    ENTITY, QUERY_OPT,
    {"key": "mode", "label": _("Modus"), "type": "select", "default": "correlation",
     "options": [["correlation", _("Korrelationsmatrix (alle Zahlenfelder)")],
                 ["crosstab", _("Heatmap zweier Felder (Zeile × Spalte)")]]},
    {"key": "row_field", "label": _("Zeilenfeld (nur Modus Heatmap)"), **FIELD},
    {"key": "col_field", "label": _("Spaltenfeld (nur Modus Heatmap)"), **FIELD},
    {"key": "agg", "label": _("Berechnung (nur Modus Heatmap)"), "type": "select", "default": "count",
     "options": [["count", _("Anzahl")], ["sum", _("Summe")], ["avg", _("Durchschnitt")]]},
    {"key": "value_field", "label": _("Zahlenfeld (für Summe/Durchschnitt)"), **FIELD},
], with_loading(prep_heatmap), "Auswertung", _("Pearson-Korrelationsmatrix oder farbcodierte Matrix"))

register("histogram", _("Histogramm & Drift"), "📶", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Häufigkeitsverteilung")},
    ENTITY, QUERY_OPT,
    {"key": "field", "label": _("Zahlenfeld"), **FIELD},
    {"key": "bins", "label": _("Anzahl Intervalle (Bins, 3–20)"), "type": "number", "default": 8},
    {"key": "group_field", "label": _("Drift-Vergleich nach Feld (optional, berechnet PSI)"), **FIELD},
], with_loading(prep_histogram), "Auswertung", _("Häufigkeitsverteilung in Intervallen mit optionalem Data-Drift-Index (PSI)"))

register("spec_chart", _("Spec-Chart (Vega-Lite)"), "📐", [
    {"key": "title", "label": _("Titel (optional)"), "type": "text", "default": _("Auswertung")},
    ENTITY, QUERY_OPT,
    {"key": "spec", "label": _("Spezifikation (Vega-Lite JSON)"), "type": "textarea",
     "default": '{\n  "mark": "bar",\n  "encoding": {\n    "x": {"field": "kategorie"},\n    "y": {"aggregate": "count"}\n  }\n}'},
], with_loading(prep_spec_chart), "Auswertung", _("Deklaratives Diagramm (JSON-Spec) auf Tabelle oder SQL/Databricks-Abfrage"))
