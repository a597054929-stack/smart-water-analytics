"""
Agent Tools — Water Analytics functions exposed as LangChain Tools.

Each @tool-decorated function becomes callable by the LLM agent.
The docstring is critical — the agent reads it to decide when to use each tool.
"""

import json
import os

# Page-context state lives in its own module so that LangGraph's tool
# runtime (which may rebind tool functions into its own namespace) still
# sees the same global dict. See _page_state.py for the rationale.
from _page_state import (
    PAGE_STATE,
    get_page_context,
)
from langchain_core.tools import tool

from safe_tool_call import safe_tool_call

# Always resolve the data dir to an absolute path.
#
# Rule:
#   - If WATER_DATA_DIR is set AND absolute → use it.
#   - If WATER_DATA_DIR is set but relative → IGNORE it (resolved against
#     CWD, which is unreliable). Fall through to the default.
#   - Otherwise → default to <project>/backend/data/output.
#
# This prevents the bug where the bat set WATER_DATA_DIR=..\backend\data\output
# and running from portfolio/ resolved it to workspace/backend/... (wrong).
_DEFAULT_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", "output")
)
_env_dir = os.environ.get("WATER_DATA_DIR", "")
if _env_dir and os.path.isabs(_env_dir):
    DATA_DIR = _env_dir
else:
    DATA_DIR = _DEFAULT_DATA_DIR

# Per-process page context. The actual state is held in `_page_state.PAGE_STATE`
# (see the import block at the top of this file). `set_page_context` and
# `get_page_context` are re-exported from there for callers that used to
# import them from this module.


_data_cache = {}

def _load(filename):
    if filename not in _data_cache:
        with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
            _data_cache[filename] = json.load(f)
    return _data_cache[filename]


def _load_errors():
    """Load data_errors.json — try DATA_DIR first, then the sibling output_real/.

    data_errors.json is a real-data-only artefact (the mock data is clean
    by construction). If WATER_DATA_DIR is set to `output/`, we still want
    the tool to find the real-data errors by looking in `output_real/`.
    Returns [] if the file doesn't exist in either location.
    """
    candidates = [os.path.join(DATA_DIR, "data_errors.json")]
    parent = os.path.dirname(DATA_DIR.rstrip("/").rstrip("\\"))
    for sibling in ("output_real", "output"):
        candidates.append(os.path.join(parent, sibling, "data_errors.json"))
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return []


def _match_dma(query, dma_name):
    """Fuzzy match DMA name."""
    if not query:
        return True
    q = query.lower().strip()
    d = dma_name.lower().strip()
    return q in d or d in q


# ── Tool 1: Query anomalies (merged) ─────────────────────────

@tool
@safe_tool_call("query_anomalies", timeout_seconds=30)
def query_anomalies(mode: str = "list", dma: str = "", month: str = "",
                    anomaly_type: str = "", meter_id: str = "", limit: int = 10) -> str:
    """Query anomaly data. mode=list (default): list anomaly records; mode=stats: summary by DMA/type; mode=analyze: deep-dive a specific meter.
    Parameters: mode=list/stats/analyze, dma - Zone name, month - YYYY-MM, anomaly_type - spike/drop/zero/watch, meter_id - for mode=analyze, limit - max results."""
    from _sql_helpers import _query_all, _query_one

    where = []
    if dma:
        where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")
    if month:
        where.append(f"date LIKE '{month}%'")
    if anomaly_type:
        where.append(f"type = '{anomaly_type}'")

    if mode == "stats":
        sql = "SELECT dma, type, COUNT(*) AS n FROM anomalies"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY dma, type"
        rows = _query_all(sql)
        dma_count: dict[str, int] = {}
        type_count: dict[str, int] = {}
        for r in rows:
            d = r.get("dma") or "Unknown"
            t = r.get("type") or "Unknown"
            dma_count[d] = dma_count.get(d, 0) + r["n"]
            type_count[t] = type_count.get(t, 0) + r["n"]
        return json.dumps({
            "filters": {"month": month or "all", "dma": dma or "all"},
            "total_anomalies": sum(r["n"] for r in rows),
            "by_dma": dict(sorted(dma_count.items(), key=lambda x: -x[1])),
            "by_type": type_count,
        }, ensure_ascii=False, indent=2)

    if mode == "analyze":
        if not meter_id:
            return json.dumps({"error": "meter_id is required for mode=analyze"})
        rows = _query_all(f"SELECT * FROM anomalies WHERE meterId = '{meter_id}'")
        if not rows:
            return json.dumps({"message": f"No anomalies found for meter {meter_id}"})
        info = _query_one(f"SELECT * FROM meters WHERE meterId = '{meter_id}'") or {}
        type_counts: dict[str, int] = {}
        for a in rows:
            t = a.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        scores = [a.get("anomalyScore", 0) or 0 for a in rows]
        avg_score = sum(scores) / len(scores) if scores else 0
        causes = []
        if type_counts.get("spike", 0) > 2:
            causes.append("Repeated spikes may indicate pipe leakage or unauthorized usage")
        if type_counts.get("zero", 0) > 1:
            causes.append("Multiple zero-consumption periods suggest meter malfunction or vacancy")
        if type_counts.get("drop", 0) > 2:
            causes.append("Frequent drops could mean intermittent supply issues")
        if avg_score > 0.7:
            causes.append("High average anomaly score — requires immediate investigation")
        return json.dumps({
            "meter_id": meter_id, "building": info.get("buildingName", "Unknown"),
            "dma": info.get("dma", "Unknown"), "property_type": info.get("propertyType", "Unknown"),
            "total_anomalies": len(rows), "type_breakdown": type_counts,
            "avg_anomaly_score": round(avg_score, 2), "recent_anomalies": rows[:5],
            "possible_causes": causes,
        }, ensure_ascii=False, indent=2)

    # Default: list mode
    sql = "SELECT * FROM anomalies"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY anomalyScore DESC LIMIT {int(limit)}"
    rows = _query_all(sql)
    return json.dumps(rows, ensure_ascii=False, indent=2)


# ── Tool 2: Query meters ─────────────────────────────────────

@tool
@safe_tool_call("query_meters", timeout_seconds=30)
def query_meters(dma: str = "", is_residential: bool = None, building: str = "", limit: int = 10) -> str:
    """Query smart water meter information. Filter by DMA zone, residential type, or building name.
    Use when the user asks about specific meters, buildings, or meter details."""
    from _sql_helpers import _query_all

    where = []
    if dma:
        where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")
    if is_residential is not None:
        where.append(f"isResidential = {1 if is_residential else 0}")
    if building:
        where.append(f"LOWER(buildingName) LIKE '%{building.lower()}%'")

    sql = "SELECT * FROM meters"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" LIMIT {int(limit)}"

    rows = _query_all(sql)
    # Surface meter_id (camelCase) for backward-compat with the JSON shape
    results = [{"meter_id": r.get("meterId"), **r} for r in rows]
    return json.dumps(results, ensure_ascii=False, indent=2)


# ── Tool 3: Anomaly statistics ───────────────────────────────

@tool
@safe_tool_call("get_anomaly_stats", timeout_seconds=30)
def get_anomaly_stats(month: str = "", dma: str = "") -> str:
    """Get anomaly statistics summary. Shows count by DMA zone and anomaly type.
    Use when the user asks about anomaly overview, which zone has most issues, or monthly summary."""
    from _sql_helpers import _query_all

    where = []
    if month:
        where.append(f"date LIKE '{month}%'")
    if dma:
        where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")

    sql = "SELECT dma, type, COUNT(*) AS n FROM anomalies"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY dma, type"

    rows = _query_all(sql)
    dma_count: dict[str, int] = {}
    type_count: dict[str, int] = {}
    total = 0
    for r in rows:
        d = r.get("dma") or "Unknown"
        t = r.get("type") or "Unknown"
        dma_count[d] = dma_count.get(d, 0) + r["n"]
        type_count[t] = type_count.get(t, 0) + r["n"]
        total += r["n"]

    return json.dumps({
        "filters": {"month": month or "all", "dma": dma or "all"},
        "total_anomalies": total,
        "by_dma": dict(sorted(dma_count.items(), key=lambda x: -x[1])),
        "by_type": type_count,
    }, ensure_ascii=False, indent=2)


# ── Tool 4: Predictions (merged) ─────────────────────────────

@tool
@safe_tool_call("get_predictions", timeout_seconds=30)
def get_predictions(query_type: str = "meter", meter_id: str = "",
                    building: str = "", limit: int = 5) -> str:
    """Get water consumption predictions (7-day forecast).
    query_type=meter (default): per-meter predictions; query_type=building: per-building predictions.
    Parameters: query_type=meter/building, meter_id - for meter type, building - for building type, limit - max results."""
    from _sql_helpers import _query_all

    if query_type == "building":
        rows = _query_all(
            f"SELECT * FROM predictions_building ORDER BY building LIMIT {int(limit) * 7}"
        )
        if not rows:
            return f"No prediction found for building '{building}'"

        # Group by building: predictions_building is one row per (building, date)
        by_building: dict[str, dict] = {}
        for r in rows:
            b = r.get("building", "")
            if building and building.lower() not in b.lower():
                continue
            entry = by_building.setdefault(b, {
                "building": b,
                "propertyType": "",
                "meterCount": 0,
                "trend": "",
                "modelScore": 0,
                "avgHistorical": 0,
                "predictions": [],
            })
            entry["predictions"].append({
                "date": r.get("date"),
                "predicted": r.get("predicted"),
                "lower": r.get("lower"),
                "upper": r.get("upper"),
            })

        buildings = list(by_building.values())
        if not buildings:
            return f"No prediction found for building '{building}'"

        # If a specific building is requested, return its full entry
        if building:
            bl = building.lower()
            match = [b for b in buildings if bl in b["building"].lower()]
            return json.dumps(match[0] if match else {}, ensure_ascii=False, indent=2)

        # Summary (top N by first-row order)
        summary = [{
            "building": b["building"],
            "propertyType": b["propertyType"],
            "meterCount": b["meterCount"],
            "trend": b["trend"],
            "modelScore": b["modelScore"],
            "avgHistorical": b["avgHistorical"],
        } for b in buildings[:limit]]
        return json.dumps({"total_buildings": len(buildings), "top": summary},
                          ensure_ascii=False, indent=2)

    # Default: meter predictions
    if meter_id:
        rows = _query_all(
            f"SELECT * FROM predictions WHERE meterId = '{meter_id}' ORDER BY date"
        )
        if not rows:
            return f"No prediction found for meter {meter_id}"
        # TODO(phase4): merge predictions_fitted.json — currently no SQLite
        # equivalent. predictions_fitted.json not in schema_v2.sql; will be
        # added as a fitted_predictions table in Phase 4 publish.
        try:
            fitted = _load("predictions_fitted.json")
            for f in fitted.get("fitted", []):
                if f.get("meterId") == meter_id:
                    rows.append({"fitted": f.get("fitted", [])})
                    break
        except (FileNotFoundError, KeyError):
            pass
        return json.dumps(rows, ensure_ascii=False, indent=2)

    # Top N by latest predicted value
    rows = _query_all(
        f"SELECT * FROM predictions ORDER BY date DESC LIMIT {int(limit) * 7}"
    )
    by_meter: dict[str, list] = {}
    for r in rows:
        by_meter.setdefault(r.get("meterId"), []).append(r)
    summary = []
    for mid, days in list(by_meter.items())[:limit]:
        vals = [d.get("predicted") for d in days if d.get("predicted") is not None]
        avg = round(sum(vals) / max(len(vals), 1), 2) if vals else 0
        summary.append({
            "meterId": mid,
            "next7days_avg": avg,
        })
    return json.dumps({"total_predictions": len(by_meter), "top": summary},
                      ensure_ascii=False, indent=2)


# ── Tool 5: Data overview ────────────────────────────────────

@tool
@safe_tool_call("get_data_overview", timeout_seconds=30)
def get_data_overview() -> str:
    """Get overall data overview: total meters, DMA zones, date range, anomaly count.
    Use when the user asks about data summary, system overview, or general stats."""
    from _sql_helpers import _query_all, _query_one

    total_meters = (_query_one("SELECT COUNT(*) AS n FROM meters") or {"n": 0})["n"]
    total_anomalies = (_query_one("SELECT COUNT(*) AS n FROM anomalies") or {"n": 0})["n"]
    dma_rows = _query_all("SELECT DISTINCT dma FROM meters WHERE dma IS NOT NULL AND dma != '' ORDER BY dma")
    type_rows = _query_all("SELECT DISTINCT type FROM anomalies WHERE type IS NOT NULL AND type != '' ORDER BY type")
    date_rows = _query_all("SELECT date FROM daily_dma ORDER BY date")

    date_list = [d["date"] for d in date_rows if d.get("date")]
    return json.dumps({
        "total_meters": total_meters,
        "total_anomalies": total_anomalies,
        "dma_zones": [d["dma"] for d in dma_rows],
        "anomaly_types": [t["type"] for t in type_rows],
        "date_range": f"{date_list[0]} ~ {date_list[-1]}" if date_list else "no data",
        "total_days": len(date_list),
    }, ensure_ascii=False, indent=2)


# ── Tool 6: Consumption data (merged) ───────────────────────

@tool
@safe_tool_call("query_consumption", timeout_seconds=30)
def query_consumption(mode: str = "daily", date: str = "", dma: str = "",
                      month1: str = "", month2: str = "", limit: int = 7) -> str:
    """Query water consumption data. mode=daily: daily DMA summary; mode=weekly: weekly trends; mode=compare: month-over-month comparison.
    Parameters: mode=daily/weekly/compare, date - for daily, dma - zone filter, month1/month2 - for compare (YYYY-MM), limit - rows."""
    from _sql_helpers import _query_all, _query_one

    if mode == "weekly":
        rows = _query_all("SELECT * FROM weekly ORDER BY weekStart")
        # The v2 weekly table stores totalByDma/dates/etc. as JSON strings.
        # Deserialize so the LLM sees the same nested structure as the
        # legacy JSON path used to produce.
        for r in rows:
            for k in ("totalByDma", "wdByDmaRes", "dates", "dailyTotals"):
                v = r.get(k)
                if isinstance(v, str) and v:
                    try:
                        r[k] = json.loads(v)
                    except (ValueError, TypeError):
                        pass
        return json.dumps(rows, ensure_ascii=False, indent=2)

    if mode == "compare":
        if not month1 or not month2:
            return json.dumps({"error": "month1 and month2 are required for compare mode"})

        def month_stats(month: str) -> dict:
            where = [f"date LIKE '{month}%'"]
            if dma:
                where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")
            sql = f"""
                SELECT COALESCE(SUM(total), 0) AS total,
                       COUNT(DISTINCT date) AS days,
                       COALESCE(SUM(residential), 0) AS residential,
                       COALESCE(SUM(nonResidential), 0) AS nonResidential,
                       MAX(meterCount) AS meterCount
                FROM daily_dma WHERE {' AND '.join(where)}
            """
            r = _query_one(sql) or {}
            total = r.get("total") or 0
            days = r.get("days") or 0
            return {
                "month": month,
                "total": round(total, 1),
                "daily_avg": round(total / max(days, 1), 1),
                "residential": round(r.get("residential") or 0, 1),
                "nonResidential": round(r.get("nonResidential") or 0, 1),
                "days": days,
            }

        s1 = month_stats(month1)
        s2 = month_stats(month2)
        change = round((s2["total"] - s1["total"]) / max(s1["total"], 1) * 100, 1)
        return json.dumps({
            "comparison": [s1, s2], "change_percent": change,
            "direction": "increased" if change > 0 else "decreased",
        }, ensure_ascii=False, indent=2)

    # Default: daily mode
    where = []
    if date:
        where.append(f"date LIKE '%{date}%'")
    if dma:
        where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")

    sql = ("SELECT date, dma, total, residential, nonResidential, meterCount "
           "FROM daily_dma")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY date DESC, dma LIMIT {int(limit) * 5}"

    rows = _query_all(sql)
    for r in rows:
        r["total"] = round(r.get("total") or 0, 1)
        r["residential"] = round(r.get("residential") or 0, 1)
        r["nonResidential"] = round(r.get("nonResidential") or 0, 1)
    return json.dumps(rows, ensure_ascii=False, indent=2)


# ── Tool 7: Rank changes ─────────────────────────────────────

@tool
@safe_tool_call("query_rank_changes", timeout_seconds=30)
def query_rank_changes(limit: int = 10) -> str:
    """Query Top-20 consumption ranking changes. Shows meters that consistently appear in high-usage rankings.
    Use when the user asks about highest consumption meters, ranking trends, or Top-20 tracking."""
    from _sql_helpers import _query_all
    rows = _query_all(f"SELECT * FROM rank_changes LIMIT {int(limit)}")
    return json.dumps(rows, ensure_ascii=False, indent=2)


# ── Tool 9: NRW / Main-Sub diff ─────────────────────────────

@tool
@safe_tool_call("query_monthly_diff", timeout_seconds=30)
def query_monthly_diff(month: str = "") -> str:
    """Query main-sub meter difference data for Non-Revenue Water (NRW) analysis.
    Use when the user asks about water loss, leakage, NRW rate, or meter differences."""
    from _sql_helpers import _query_all

    if month:
        rows = _query_all(f"SELECT * FROM monthly_diff WHERE month = '{month}'")
        if not rows:
            return f"No data found for {month}"
        # Reconstruct the legacy shape: a single month-level dict with
        # 'month' and 'diffs' list (subs serialized as JSON in SQLite).
        out = {"month": month, "diffs": []}
        for r in rows:
            diff = dict(r)
            subs_raw = diff.pop("subs", None)
            if isinstance(subs_raw, str) and subs_raw:
                try:
                    diff["subs"] = json.loads(subs_raw)
                except (ValueError, TypeError):
                    diff["subs"] = []
            elif not subs_raw:
                diff["subs"] = []
            out["diffs"].append(diff)
        return json.dumps(out, ensure_ascii=False, indent=2)

    # Summary across all months — SQL aggregate per month
    rows = _query_all("""
        SELECT month,
               COUNT(*) AS meters_tracked,
               SUM(mainTotal) AS total_main,
               SUM(subsTotal) AS total_subs
        FROM monthly_diff
        GROUP BY month
        ORDER BY month
    """)
    summary = []
    for r in rows:
        tm = r.get("total_main") or 0
        ts = r.get("total_subs") or 0
        diff_pct = round((tm - ts) / tm * 100, 1) if tm else 0
        summary.append({
            "month": r["month"],
            "meters_tracked": r["meters_tracked"],
            "total_main": round(tm, 1),
            "total_subs": round(ts, 1),
            "diff_percent": diff_pct,
        })
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ── Tool 10: Generate chart ──────────────────────────────────

@tool
@safe_tool_call("generate_chart", timeout_seconds=15)
def generate_chart(chart_type: str, dma: str = "Zone-3", days: int = 30) -> str:
    """Generate an ECharts visualization. chart_type options: weekly_trend, anomaly_by_dma, anomaly_type, daily_usage.
    Use when the user asks to see a chart, graph, or visualization."""
    from chart_generator import generate_chart as gen
    import json as _json
    result = gen(chart_type, dma=dma, days=days)
    if isinstance(result, dict):
        return _json.dumps({"chart_type": chart_type, "echarts_option": result}, ensure_ascii=False)
    return result


# ── Tool 10b: SQL + Chart ──────────────────────────────────────

@tool
@safe_tool_call("sql_chart", timeout_seconds=30)
def sql_chart(sql: str, chart_type: str = "bar", title: str = "",
              x_column: str = "", y_column: str = "", y_label: str = "") -> str:
    """Execute a SQL query and generate an ECharts chart from the results.

    Args:
        sql: the SELECT query (must return at least 2 columns)
        chart_type: "bar" | "line" | "pie"
        title: chart title (auto-generated if empty)
        x_column: column name for x-axis labels (first column if empty)
        y_column: column name for y-axis values (second column if empty)
        y_label: y-axis unit label (e.g. "m³", "count")

    Use this when the user asks for a chart AND the data needs SQL
    (e.g. "路氹城區前10用水柱状图", "物业类型用水饼图").
    """
    from chart_generator import generic_chart

    # Run SQL via the pipeline sql_loader (returns cols + rows as tuples)
    try:
        from sql_loader import run_query
        cols, raw_rows = run_query(sql, limit=1000)
    except Exception as e:
        return json.dumps({"error": f"SQL execution failed: {e}"})

    if not raw_rows:
        return json.dumps({"error": "Query returned no data"})

    # Build list-of-dicts from (cols, rows)
    data = [dict(zip(cols, row)) for row in raw_rows]

    # Pick x and y columns. y defaults to the FIRST NUMERIC column
    # (so SELECT meterId, buildingName, total picks "total" not
    # the text "buildingName"). x defaults to the first column.
    x_col = x_column if (x_column and x_column in cols) else cols[0]
    if y_column and y_column in cols:
        y_col = y_column
    else:
        y_col = cols[0]
        for c in cols:
            sample = data[0].get(c) if data else None
            if isinstance(sample, (int, float)) and not isinstance(sample, bool):
                y_col = c
                break

    labels = [str(row.get(x_col, "")) for row in data]
    values = []
    for row in data:
        v = row.get(y_col, 0)
        try:
            values.append(round(float(v), 2))
        except (TypeError, ValueError):
            values.append(0)

    chart_title = title or f"{y_col} by {x_col}"

    result = generic_chart(
        title=chart_title,
        chart_type=chart_type,
        labels=labels,
        series=[{"name": y_col, "values": values}],
        y_label=y_label,
    )
    return result


# ── Tool 11: Anomaly deep analysis ───────────────────────────

@tool
@safe_tool_call("analyze_anomaly", timeout_seconds=15)
def analyze_anomaly(meter_id: str) -> str:
    """Deep-dive analysis for a specific meter's anomalies.
    Shows all anomaly history, consumption pattern, and possible causes.
    Use when the user asks to investigate a specific meter or anomaly."""
    from _sql_helpers import _query_all, _query_one

    # anomalies + meters JOIN in one SQL
    rows = _query_all(f"""
        SELECT a.*, m.buildingName AS building, m.dma AS meter_dma,
               m.propertyType AS property_type
        FROM anomalies a LEFT JOIN meters m ON a.meterId = m.meterId
        WHERE a.meterId = '{meter_id}'
        ORDER BY a.date DESC
    """)

    if not rows:
        return json.dumps({"message": f"No anomalies found for meter {meter_id}"})

    # Normalize field names: meter_dma -> dma (matches old output)
    for r in rows:
        if "meter_dma" in r:
            r["dma"] = r.pop("meter_dma")

    info = _query_one(f"SELECT * FROM meters WHERE meterId = '{meter_id}'") or {}

    # Analyze patterns
    type_counts: dict[str, int] = {}
    for a in rows:
        t = a.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    scores = [a.get("anomalyScore", 0) or 0 for a in rows]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Possible causes
    causes = []
    if type_counts.get("spike", 0) > 2:
        causes.append("Repeated spikes may indicate pipe leakage or unauthorized usage")
    if type_counts.get("zero", 0) > 1:
        causes.append("Multiple zero-consumption periods suggest meter malfunction or vacancy")
    if type_counts.get("drop", 0) > 2:
        causes.append("Frequent drops could mean intermittent supply issues")
    if avg_score > 0.7:
        causes.append("High average anomaly score — requires immediate investigation")

    return json.dumps({
        "meter_id": meter_id,
        "building": info.get("buildingName", "Unknown"),
        "dma": info.get("dma", "Unknown"),
        "property_type": info.get("propertyType", "Unknown"),
        "total_anomalies": len(rows),
        "type_breakdown": type_counts,
        "avg_anomaly_score": round(avg_score, 2),
        "recent_anomalies": rows[:5],
        "possible_causes": causes,
    }, ensure_ascii=False, indent=2)


# ── Tool 13: Auto-generate report ───────────────────────────

@tool
@safe_tool_call("generate_report", timeout_seconds=30)
def generate_report(dma: str = "", month: str = "") -> str:
    """Generate a summary report for a DMA zone and month.
    Combines anomaly stats, consumption data, rankings, and NRW into one report.
    Use when the user asks for a report, summary, or overview analysis."""
    from _sql_helpers import _query_all, _query_one

    # 1. Anomalies
    a_where = []
    if month:
        a_where.append(f"date LIKE '{month}%'")
    if dma:
        a_where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")
    a_sql = "SELECT type, dma FROM anomalies"
    if a_where:
        a_sql += " WHERE " + " AND ".join(a_where)
    a_rows = _query_all(a_sql)
    type_counts: dict[str, int] = {}
    dma_counts: dict[str, int] = {}
    for r in a_rows:
        t = r.get("type") or "unknown"
        d = r.get("dma") or "unknown"
        type_counts[t] = type_counts.get(t, 0) + 1
        dma_counts[d] = dma_counts.get(d, 0) + 1

    # 2. Consumption (SUM/COUNT via SQL)
    d_where = []
    if month:
        d_where.append(f"date LIKE '{month}%'")
    if dma:
        d_where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")
    d_sql = "SELECT COALESCE(SUM(total), 0) AS s, COUNT(DISTINCT date) AS days FROM daily_dma"
    if d_where:
        d_sql += " WHERE " + " AND ".join(d_where)
    d_row = _query_one(d_sql) or {"s": 0, "days": 0}
    total_consumption = d_row.get("s") or 0
    days_count = d_row.get("days") or 0
    avg_daily = round(total_consumption / max(days_count, 1), 1)

    # 3. Top ranked meters (filtered by DMA if provided)
    r_where = []
    if dma:
        r_where.append(f"LOWER(dma) LIKE '%{dma.lower()}%'")
    r_sql = "SELECT meterId, buildingName, daysInTop20, avgTotal FROM rank_changes"
    if r_where:
        r_sql += " WHERE " + " AND ".join(r_where)
    r_sql += " LIMIT 5"
    top_meters = _query_all(r_sql)

    report = {
        "report_period": month or "all time",
        "dma_filter": dma or "all zones",
        "consumption": {
            "total": round(total_consumption, 1),
            "daily_average": avg_daily,
            "days": days_count,
        },
        "anomalies": {
            "total": len(a_rows),
            "by_type": type_counts,
            "by_dma": dma_counts,
        },
        "top_meters": [{
            "meterId": m.get("meterId"),
            "building": m.get("buildingName"),
            "daysInTop20": m.get("daysInTop20"),
            "avgTotal": m.get("avgTotal"),
        } for m in top_meters],
    }
    return json.dumps(report, ensure_ascii=False, indent=2)


# ── Tool 15: Page context ─────────────────────────────────────

@tool
@safe_tool_call("get_current_page_context", timeout_seconds=5)
def get_current_page_context() -> str:
    """Return the user's current page state: which tab they're on, the selected
    date, the selected DMA zone, and other UI filters.

    Use this when the user asks a deictic question like:
      - "what about this week?"
      - "the meter I'm looking at"
      - "current zone consumption"
      - "compare to last month" (when looking at a chart with a known month)

    The same information is also passed as a [PAGE CONTEXT] system message at
    the start of every turn. This tool is useful when the user has switched
    tabs mid-conversation and you need a fresh read.
    """
    import sys
    ctx = get_page_context()
    print(
        f"[tool:get_current_page_context] called, PAGE_STATE={dict(PAGE_STATE)}, "
        f"returned_ctx={ctx}",
        file=sys.stderr, flush=True,
    )
    if not ctx:
        return json.dumps({"context": "no page context available"})
    return json.dumps({"context": ctx}, ensure_ascii=False)


# ── Tool 16: Data quality (added 2026-06-06) ─────────────────

@tool
@safe_tool_call("query_data_quality", timeout_seconds=15)
def query_data_quality(date: str = "", meter_id: str = "", reason: str = "") -> str:
    """Query data quality / integrity errors logged by the converter pipeline.
    Returns the records that were dropped from analytics (e.g. negative readings,
    daily totals exceeding 40,000 m³ that look like fire-test or typos).

    Use when the user asks about data quality, data integrity, dropped records,
    "数据准不准" (is the data accurate), "数据有没有问题" (is there a data issue),
    or wants to know why a specific meter/date is missing from a report.

    Parameters:
        date: optional YYYY-MM-DD filter (matches errors on that exact day)
        meter_id: optional 6-digit meter ID filter
        reason: optional substring match on the reason (e.g. 'fire-test', 'typo', '>40000')
    """
    from _sql_helpers import _query_all

    where = []
    if date:
        where.append(f"date = '{date}'")
    if meter_id:
        where.append(f"CAST(meterId AS TEXT) = '{meter_id}'")
    if reason:
        where.append(f"LOWER(reason) LIKE '%{reason.lower()}%'")

    sql = "SELECT * FROM data_errors"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts DESC LIMIT 1000"

    errors = _query_all(sql)

    by_reason: dict[str, int] = {}
    by_date: dict[str, int] = {}
    for e in errors:
        r = e.get("reason", "Unknown")
        by_reason[r] = by_reason.get(r, 0) + 1
        d = e.get("date", "Unknown")
        by_date[d] = by_date.get(d, 0) + 1

    return json.dumps({
        "total_errors": len(errors),
        "filters": {"date": date or "all", "meter_id": meter_id or "all", "reason": reason or "all"},
        "by_reason": dict(sorted(by_reason.items(), key=lambda x: -x[1])),
        "by_date_top5": dict(sorted(by_date.items(), key=lambda x: -x[1])[:5]),
        "recent": errors[-5:] if errors else [],
    }, ensure_ascii=False, indent=2)


# ── Export all tools ──────────────────────────────────────────

ALL_TOOLS = [
    query_anomalies,      # merged: list/stats/analyze modes
    query_meters,
    get_predictions,      # merged: meter/building types
    get_data_overview,
    query_consumption,    # merged: daily/weekly/compare modes (replaces query_daily_dma, query_weekly, compare_months)
    query_rank_changes,
    query_monthly_diff,
    generate_chart,
    generate_report,
    get_current_page_context,
    query_data_quality,   # data integrity errors (added 2026-06-06)
]

# Text-to-SQL tools (always available; agent picks the right one per question).
# Re-exported from sql_tools so multi_agent can discover them via ALL_TOOLS.
# `agent/` has no __init__.py and is not a real package, so a relative
# import like `from .sql_tools` would always fail. Use the same sys.path
# bootstrap as sql_tools.py itself.
#
# 2026-06-05: sql_query now self-refines on errors. We prefer the refined
# version from sql_refinement (drop-in replacement: same name, same
# signature, same return shape plus an `attempts` key on success and
# `refinement_exhausted` on failure). Falls back to the raw tool if
# the refinement module can't be imported (e.g. missing LLM config).
try:
    import sys
    from pathlib import Path
    _agent_dir = str(Path(__file__).resolve().parent)
    if _agent_dir not in sys.path:
        sys.path.insert(0, _agent_dir)
    from sql_tools import get_table_schema_tool, list_tables_tool  # raw helpers
    try:
        from sql_refinement import sql_query  # refined: 2 retries on error
        _sql_query = sql_query
    except Exception as _ref_err:
        import sys as _sys
        print(f"[agent_tools] self-refinement unavailable, using raw sql_query: {_ref_err}", file=_sys.stderr)
        from sql_tools import sql_query as _sql_query  # type: ignore
    ALL_TOOLS = list(ALL_TOOLS) + [list_tables_tool, get_table_schema_tool, _sql_query, sql_chart]
except (ImportError, Exception) as _sql_err:
    # Don't silently swallow this — it means SQL tools are missing and the
    # agent will tell the user "no SQL tools available". Surface it to the
    # server console so a missing db / broken import is visible.
    import sys
    print(f"[agent_tools] SQL tools not registered: {_sql_err}", file=sys.stderr)
