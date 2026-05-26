"""
Chart Generator — converts water data into ECharts JSON configs.

The Agent calls these functions to produce chart options,
which the frontend renders directly with ECharts.
"""

import json, os

DATA_DIR = os.environ.get(
    "WATER_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "backend", "data", "output")
)


def _load(filename):
    with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def _find_dma_key(data_dict, dma_query):
    """Fuzzy match DMA name in a dictionary."""
    for key in data_dict:
        if dma_query.lower() in key.lower() or key.lower() in dma_query.lower():
            return key
    return dma_query


def weekly_trend_chart(dma: str = "Zone-3") -> dict:
    """Weekly consumption trend line chart."""
    weeks = _load("weekly.json")
    if not weeks:
        return {"title": {"text": "No data available"}}

    actual_key = _find_dma_key(weeks[0].get("totalByDma", {}), dma)
    labels = [w["label"] for w in weeks]
    values = [round(w.get("totalByDma", {}).get(actual_key, 0)) for w in weeks]

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
    anomalies = _load("anomalies.json")
    dma_count = {}
    for a in anomalies:
        d = a.get("dma", "Unknown")
        dma_count[d] = dma_count.get(d, 0) + 1

    data = [{"name": k, "value": v} for k, v in sorted(dma_count.items(), key=lambda x: -x[1])]
    return {
        "title": {"text": "Anomalies by DMA Zone", "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "series": [{"type": "pie", "radius": ["40%", "70%"], "data": data, "label": {"formatter": "{b}\n{c}"}}],
    }


def anomaly_type_chart() -> dict:
    """Anomaly type distribution (bar chart)."""
    anomalies = _load("anomalies.json")
    type_count = {}
    for a in anomalies:
        t = a.get("type", "Unknown")
        type_count[t] = type_count.get(t, 0) + 1

    type_names = {"spike": "Spike", "drop": "Drop", "zero": "Zero", "watch": "Watch"}
    labels = [type_names.get(k, k) for k in type_count.keys()]
    values = list(type_count.values())

    return {
        "title": {"text": "Anomaly Type Distribution", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": labels},
        "yAxis": {"type": "value", "name": "Count"},
        "series": [{"type": "bar", "data": values, "itemStyle": {"color": "#2563eb"}}],
    }


def daily_usage_chart(dma: str = "Zone-3", days: int = 30) -> dict:
    """Daily consumption trend line chart."""
    daily = _load("daily_dma.json")
    if not daily:
        return {"title": {"text": "No data available"}}

    sample_dmas = daily[0].get("dmas", {})
    actual_key = _find_dma_key(sample_dmas, dma)

    recent = daily[-days:]
    dates = [d["date"] for d in recent]
    values = [round(d.get("dmas", {}).get(actual_key, {}).get("total", 0), 1) for d in recent]

    return {
        "title": {"text": f"{dma} Last {days} Days Usage", "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": dates, "axisLabel": {"rotate": 45}},
        "yAxis": {"type": "value", "name": "m³"},
        "series": [{"name": dma, "type": "line", "data": values}],
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
