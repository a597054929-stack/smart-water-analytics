"""
Chart Generator — converts water data into ECharts JSON configs.

The Agent calls these functions to produce chart options,
which the frontend renders directly with ECharts.

Phase 2 of ARCHITECTURE_OPTIMIZATION_PLAN: switched from JSON file
reads to SQLite queries (analytics_real.db). Single source of truth.
"""

import json

# Ensure agent/ is on sys.path so the relative import of _sql_helpers
# resolves whether this file is imported by tests, by the server, or
# directly as a script.
import sys
from pathlib import Path
_agent_dir = str(Path(__file__).resolve().parent)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from _sql_helpers import _query_all  # noqa: E402


def _find_dma_key(data_dict, dma_query):
    """Fuzzy match DMA name in a dictionary."""
    for key in data_dict:
        if dma_query.lower() in key.lower() or key.lower() in dma_query.lower():
            return key
    return dma_query


def weekly_trend_chart(dma: str = "Zone-3") -> dict:
    """Weekly consumption trend line chart."""
    rows = _query_all("SELECT label, totalByDma FROM weekly ORDER BY weekStart")
    if not rows:
        return {"title": {"text": "No data available"}}

    # totalByDma is a JSON string in the v2 weekly table — deserialize
    first_tbd = rows[0].get("totalByDma") or "{}"
    if isinstance(first_tbd, str):
        try:
            first_tbd = json.loads(first_tbd)
        except (ValueError, TypeError):
            first_tbd = {}
    actual_key = _find_dma_key(first_tbd, dma)

    labels = [r.get("label") or "" for r in rows]
    values = []
    for r in rows:
        tbd = r.get("totalByDma")
        if isinstance(tbd, str):
            try:
                tbd = json.loads(tbd)
            except (ValueError, TypeError):
                tbd = {}
        values.append(round((tbd or {}).get(actual_key, 0)))

    return {
        "title": {"text": f"{dma} Weekly Consumption Trend", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels, "axisLabel": {"rotate": 45}},
        "yAxis": {"type": "value", "name": "m³"},
        "series": [{"name": dma, "type": "line", "data": values, "smooth": True, "areaStyle": {"opacity": 0.3}}],
        "grid": {"left": "10%", "right": "5%", "bottom": "15%"},
    }


def anomaly_by_dma_chart() -> dict:
    """Anomaly count by DMA zone (pie chart)."""
    rows = _query_all("""
        SELECT dma, COUNT(*) AS n FROM anomalies
        WHERE dma IS NOT NULL AND dma != ''
        GROUP BY dma ORDER BY n DESC
    """)
    data = [{"name": r["dma"], "value": r["n"]} for r in rows]
    return {
        "title": {"text": "Anomalies by DMA Zone", "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "series": [{"type": "pie", "radius": ["40%", "70%"], "data": data, "label": {"formatter": "{b}\n{c}"}}],
    }


def anomaly_type_chart() -> dict:
    """Anomaly type distribution (bar chart)."""
    rows = _query_all("""
        SELECT type, COUNT(*) AS n FROM anomalies
        WHERE type IS NOT NULL AND type != ''
        GROUP BY type
    """)
    type_names = {"spike": "Spike", "drop": "Drop", "zero": "Zero", "watch": "Watch"}
    labels = [type_names.get(r["type"], r["type"]) for r in rows]
    values = [r["n"] for r in rows]

    return {
        "title": {"text": "Anomaly Type Distribution", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "name": "Count"},
        "series": [{"type": "bar", "data": values, "itemStyle": {"color": "#2563eb"}}],
    }


def daily_usage_chart(dma: str = "Zone-3", days: int = 30) -> dict:
    """Daily consumption trend line chart."""
    # Find the actual DMA key in the table (real data uses Chinese names)
    sample_rows = _query_all(
        "SELECT DISTINCT dma FROM daily_dma WHERE dma LIKE ? ORDER BY dma LIMIT 1",
        # f-string for safety; user input already validated at safe_tool_call
    )
    # Use LIKE to fuzzy-match
    all_dmas = _query_all("SELECT DISTINCT dma FROM daily_dma WHERE dma IS NOT NULL AND dma != ''")
    dma_keys = {r["dma"] for r in all_dmas}
    actual_key = _find_dma_key(dma_keys, dma) if dma_keys else dma

    rows = _query_all(
        f"SELECT date, total FROM daily_dma WHERE dma = '{actual_key}' "
        f"ORDER BY date DESC LIMIT {int(days)}"
    )
    if not rows:
        return {"title": {"text": "No data available"}}

    # Reverse to chronological order for the line chart
    rows.reverse()
    dates = [r["date"] for r in rows]
    values = [round(r.get("total") or 0, 1) for r in rows]

    return {
        "title": {"text": f"{actual_key} Last {days} Days Usage", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": dates, "axisLabel": {"rotate": 45}},
        "yAxis": {"type": "value", "name": "m³"},
        "series": [{"name": actual_key, "type": "line", "data": values}],
        "grid": {"left": "10%", "right": "5%", "bottom": "15%"},
    }


CHART_GENERATORS = {
    "weekly_trend": weekly_trend_chart,
    "anomaly_by_dma": anomaly_by_dma_chart,
    "anomaly_type": anomaly_type_chart,
    "daily_usage": daily_usage_chart,
}


def generate_chart(chart_type: str, dma: str = "Zone-3", days: int = 30) -> str:
    """Generate ECharts config by chart type."""
    if chart_type not in CHART_GENERATORS:
        return json.dumps({"error": f"Unknown chart type. Options: {list(CHART_GENERATORS.keys())}"})

    if chart_type == "weekly_trend":
        config = CHART_GENERATORS[chart_type](dma=dma)
    elif chart_type == "daily_usage":
        config = CHART_GENERATORS[chart_type](dma=dma, days=days)
    else:
        config = CHART_GENERATORS[chart_type]()

    return json.dumps({"chart_type": chart_type, "echarts_option": config}, ensure_ascii=False)


def generic_chart(
    title: str,
    chart_type: str,
    labels: list[str],
    series: list[dict],
    x_label: str = "",
    y_label: str = "",
) -> str:
    """Build an ECharts config from arbitrary label + series data.

    This is the generic version that sql_query results can use.  The
    agent calls sql_query, gets rows back, extracts two columns
    (labels + values), and passes them here.

    Args:
        title: chart title
        chart_type: "line" | "bar" | "pie"
        labels: x-axis categories (or pie names)
        series: [{"name": "series1", "values": [1,2,3]}, ...]
        x_label: optional x-axis label
        y_label: optional y-axis label

    Returns:
        JSON string with echarts_option for the frontend to render.
    """
    config: dict = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis" if chart_type != "pie" else "item"},
        "grid": {"left": "10%", "right": "5%", "bottom": "15%"},
    }

    if chart_type == "pie":
        pie_data = [{"name": labels[i], "value": s["values"][i]}
                     for s in series for i in range(len(labels))]
        # For pie, flatten all series into one data array
        if len(series) == 1:
            pie_data = [{"name": labels[i], "value": series[0]["values"][i]}
                         for i in range(len(labels))]
        config["series"] = [{"type": "pie", "radius": ["40%", "70%"],
                             "data": pie_data,
                             "label": {"formatter": "{b}\n{c}"}}]
    else:
        if x_label:
            config["xAxis"] = {"type": "category", "data": labels,
                               "name": x_label,
                               "axisLabel": {"rotate": 45 if len(labels) > 8 else 0}}
        else:
            config["xAxis"] = {"type": "category", "data": labels,
                               "axisLabel": {"rotate": 45 if len(labels) > 8 else 0}}
        config["yAxis"] = {"type": "value", "name": y_label or ""}
        config["series"] = [
            {"name": s.get("name", ""), "type": chart_type, "data": s["values"],
             "smooth": chart_type == "line",
             "areaStyle": {"opacity": 0.3} if chart_type == "line" else None}
            for s in series
        ]

    return json.dumps({"chart_type": "generic", "echarts_option": config}, ensure_ascii=False)
