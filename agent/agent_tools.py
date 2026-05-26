"""
Agent Tools — Water Analytics functions exposed as LangChain Tools.

Each @tool-decorated function becomes callable by the LLM agent.
The docstring is critical — the agent reads it to decide when to use each tool.
"""

import json, os
from langchain_core.tools import tool

DATA_DIR = os.environ.get(
    "WATER_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "backend", "data", "output")
)


def _load(filename):
    with open(os.path.join(DATA_DIR, filename), "r", encoding="utf-8") as f:
        return json.load(f)


def _match_dma(query, dma_name):
    """Fuzzy match DMA name."""
    if not query:
        return True
    q = query.lower().strip()
    d = dma_name.lower().strip()
    return q in d or d in q


# ── Tool 1: Query anomalies ──────────────────────────────────

@tool
def query_anomalies(dma: str = "", month: str = "", anomaly_type: str = "", limit: int = 10) -> str:
    """Query water consumption anomaly records. Filter by DMA zone, month, or anomaly type.
    Use when the user asks about anomalies, unusual consumption, or alerts.
    Parameters: dma - DMA zone name (e.g. 'Zone-3'), month - YYYY-MM format, anomaly_type - spike/drop/zero/watch, limit - max results."""
    anomalies = _load("anomalies.json")

    if dma:
        anomalies = [a for a in anomalies if _match_dma(dma, a.get("dma", ""))]
    if month:
        anomalies = [a for a in anomalies if a["date"].startswith(month)]
    if anomaly_type:
        anomalies = [a for a in anomalies if a.get("type") == anomaly_type]

    anomalies.sort(key=lambda x: x.get("anomalyScore", 0), reverse=True)
    return json.dumps(anomalies[:limit], ensure_ascii=False, indent=2)


# ── Tool 2: Query meters ─────────────────────────────────────

@tool
def query_meters(dma: str = "", is_residential: bool = None, building: str = "", limit: int = 10) -> str:
    """Query smart water meter information. Filter by DMA zone, residential type, or building name.
    Use when the user asks about specific meters, buildings, or meter details."""
    meters = _load("meter_info.json")

    results = []
    for meter_id, info in meters.items():
        if dma and not _match_dma(dma, info.get("dma", "")):
            continue
        if is_residential is not None and info.get("isResidential") != is_residential:
            continue
        if building and building.lower() not in info.get("buildingName", "").lower():
            continue
        results.append({"meter_id": meter_id, **info})
        if len(results) >= limit:
            break

    return json.dumps(results, ensure_ascii=False, indent=2)


# ── Tool 3: Anomaly statistics ───────────────────────────────

@tool
def get_anomaly_stats(month: str = "", dma: str = "") -> str:
    """Get anomaly statistics summary. Shows count by DMA zone and anomaly type.
    Use when the user asks about anomaly overview, which zone has most issues, or monthly summary."""
    anomalies = _load("anomalies.json")

    if month:
        anomalies = [a for a in anomalies if a["date"].startswith(month)]
    if dma:
        anomalies = [a for a in anomalies if _match_dma(dma, a.get("dma", ""))]

    dma_count = {}
    type_count = {}
    for a in anomalies:
        d = a.get("dma", "Unknown")
        t = a.get("type", "Unknown")
        dma_count[d] = dma_count.get(d, 0) + 1
        type_count[t] = type_count.get(t, 0) + 1

    return json.dumps({
        "filters": {"month": month or "all", "dma": dma or "all"},
        "total_anomalies": len(anomalies),
        "by_dma": dict(sorted(dma_count.items(), key=lambda x: -x[1])),
        "by_type": type_count,
    }, ensure_ascii=False, indent=2)


# ── Tool 4: Predictions ──────────────────────────────────────

@tool
def get_predictions(meter_id: str = "", limit: int = 5) -> str:
    """Get water consumption predictions (7-day forecast). Optionally filter by meter ID.
    Use when the user asks about predictions, future trends, or forecast."""
    data = _load("predictions.json")
    predictions = data.get("predictions", [])

    if meter_id:
        pred = [p for p in predictions if p.get("meterId") == meter_id]
        if not pred:
            return f"No prediction found for meter {meter_id}"
        return json.dumps(pred[0], ensure_ascii=False, indent=2)

    # Return top N by model score
    top = sorted(predictions, key=lambda x: x.get("modelScore", 0), reverse=True)[:limit]
    summary = [{
        "meterId": p["meterId"],
        "building": p.get("info", {}).get("buildingName", ""),
        "dma": p.get("info", {}).get("dma", ""),
        "trend": p.get("trend", ""),
        "modelScore": p.get("modelScore", 0),
        "avgHistorical": p.get("avgHistorical", 0),
        "next7days_avg": round(sum(x["value"] for x in p.get("predictions", [])) / max(1, len(p.get("predictions", []))), 2),
    } for p in top]
    return json.dumps({"total_predictions": len(predictions), "top": summary}, ensure_ascii=False, indent=2)


@tool
def get_building_predictions(building: str = "", limit: int = 10) -> str:
    """Get building-level water consumption predictions for Zone-3.
    Use when the user asks about building forecasts or hotel/resort predictions."""
    data = _load("predictions_by_building.json")
    predictions = data.get("predictions", [])

    if building:
        pred = [p for p in predictions if building.lower() in p.get("building", "").lower()]
        if not pred:
            return f"No prediction found for building '{building}'"
        return json.dumps(pred, ensure_ascii=False, indent=2)

    top = predictions[:limit]
    summary = [{
        "building": p["building"],
        "propertyType": p.get("propertyType", ""),
        "meterCount": p.get("meterCount", 0),
        "trend": p.get("trend", ""),
        "modelScore": p.get("modelScore", 0),
        "avgHistorical": p.get("avgHistorical", 0),
    } for p in top]
    return json.dumps({"total_buildings": len(predictions), "top": summary}, ensure_ascii=False, indent=2)


# ── Tool 5: Data overview ────────────────────────────────────

@tool
def get_data_overview() -> str:
    """Get overall data overview: total meters, DMA zones, date range, anomaly count.
    Use when the user asks about data summary, system overview, or general stats."""
    anomalies = _load("anomalies.json")
    meters = _load("meter_info.json")
    dates = _load("available_dates.json")

    return json.dumps({
        "total_meters": len(meters),
        "total_anomalies": len(anomalies),
        "dma_zones": sorted(set(m.get("dma", "") for m in meters.values())),
        "anomaly_types": sorted(set(a.get("type", "") for a in anomalies)),
        "date_range": f"{dates[0]} ~ {dates[-1]}" if dates else "no data",
        "total_days": len(dates),
    }, ensure_ascii=False, indent=2)


# ── Tool 6: Daily DMA data ──────────────────────────────────

@tool
def query_daily_dma(date: str = "", dma: str = "", limit: int = 7) -> str:
    """Query daily DMA consumption summary. Filter by date or DMA zone.
    Use when the user asks about daily usage, consumption by zone, or specific dates."""
    daily = _load("daily_dma.json")

    results = []
    for day in daily:
        if date and date not in day["date"]:
            continue
        for dma_name, stats in day.get("dmas", {}).items():
            if dma and not _match_dma(dma, dma_name):
                continue
            results.append({
                "date": day["date"],
                "dma": dma_name,
                "total": round(stats["total"], 1),
                "residential": round(stats.get("residential", 0), 1),
                "nonResidential": round(stats.get("nonResidential", 0), 1),
                "meterCount": stats.get("meterCount", 0),
            })
        if len(results) >= limit * 5:
            break

    return json.dumps(results[:limit * 5], ensure_ascii=False, indent=2)


# ── Tool 7: Weekly comparison ────────────────────────────────

@tool
def query_weekly() -> str:
    """Get weekly consumption comparison data including weekday vs weekend patterns.
    Use when the user asks about weekly trends or weekday/weekend comparison."""
    return json.dumps(_load("weekly.json"), ensure_ascii=False, indent=2)


# ── Tool 8: Rank changes ─────────────────────────────────────

@tool
def query_rank_changes(limit: int = 10) -> str:
    """Query Top-20 consumption ranking changes. Shows meters that consistently appear in high-usage rankings.
    Use when the user asks about highest consumption meters, ranking trends, or Top-20 tracking."""
    ranks = _load("rank_changes.json")
    return json.dumps(ranks[:limit], ensure_ascii=False, indent=2)


# ── Tool 9: NRW / Main-Sub diff ─────────────────────────────

@tool
def query_monthly_diff(month: str = "") -> str:
    """Query main-sub meter difference data for Non-Revenue Water (NRW) analysis.
    Use when the user asks about water loss, leakage, NRW rate, or meter differences."""
    months = _load("monthly_main_sub_diff.json")

    if month:
        for m in months:
            if m["month"] == month:
                return json.dumps(m, ensure_ascii=False, indent=2)
        return f"No data found for {month}"

    # Summary of all months
    summary = []
    for m in months:
        total_main = sum(d.get("mainTotal", 0) for d in m.get("diffs", []))
        total_subs = sum(d.get("subsTotal", 0) for d in m.get("diffs", []))
        diff_pct = round((total_main - total_subs) / total_main * 100, 1) if total_main > 0 else 0
        summary.append({
            "month": m["month"],
            "meters_tracked": len(m.get("diffs", [])),
            "total_main": round(total_main, 1),
            "total_subs": round(total_subs, 1),
            "diff_percent": diff_pct,
        })
    return json.dumps(summary, ensure_ascii=False, indent=2)


# ── Tool 10: Generate chart ──────────────────────────────────

@tool
def generate_chart(chart_type: str, dma: str = "Zone-3", days: int = 30) -> str:
    """Generate an ECharts visualization. chart_type options: weekly_trend, anomaly_by_dma, anomaly_type, daily_usage.
    Use when the user asks to see a chart, graph, or visualization."""
    from chart_generator import generate_chart as gen
    return gen(chart_type, dma=dma, days=days)


# ── Tool 11: Month-over-month comparison ─────────────────────

@tool
def compare_months(month1: str, month2: str, dma: str = "") -> str:
    """Compare water consumption between two months (e.g. '2026-03' vs '2026-04').
    Shows total consumption, meter count, and percentage change.
    Use when the user asks to compare months or see trends."""
    daily = _load("daily_dma.json")

    def month_stats(month):
        total = 0
        count = 0
        days = 0
        res_total = 0
        nonres_total = 0
        for day in daily:
            if not day["date"].startswith(month):
                continue
            days += 1
            for dma_name, stats in day.get("dmas", {}).items():
                if dma and not _match_dma(dma, dma_name):
                    continue
                total += stats.get("total", 0)
                res_total += stats.get("residential", 0)
                nonres_total += stats.get("nonResidential", 0)
                count = max(count, stats.get("meterCount", 0))
        return {
            "month": month,
            "total": round(total, 1),
            "daily_avg": round(total / max(days, 1), 1),
            "residential": round(res_total, 1),
            "nonResidential": round(nonres_total, 1),
            "days": days,
        }

    s1 = month_stats(month1)
    s2 = month_stats(month2)
    change = round((s2["total"] - s1["total"]) / max(s1["total"], 1) * 100, 1)

    return json.dumps({
        "comparison": [s1, s2],
        "change_percent": change,
        "direction": "increased" if change > 0 else "decreased",
    }, ensure_ascii=False, indent=2)


# ── Tool 12: Anomaly deep analysis ──────────────────────────

@tool
def analyze_anomaly(meter_id: str) -> str:
    """Deep-dive analysis for a specific meter's anomalies.
    Shows all anomaly history, consumption pattern, and possible causes.
    Use when the user asks to investigate a specific meter or anomaly."""
    anomalies = _load("anomalies.json")
    meter_anomalies = [a for a in anomalies if a.get("meterId") == meter_id]

    if not meter_anomalies:
        return json.dumps({"message": f"No anomalies found for meter {meter_id}"})

    info = _load("meter_info.json").get(meter_id, {})

    # Analyze patterns
    type_counts = {}
    for a in meter_anomalies:
        t = a.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    scores = [a.get("anomalyScore", 0) for a in meter_anomalies]
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
        "total_anomalies": len(meter_anomalies),
        "type_breakdown": type_counts,
        "avg_anomaly_score": round(avg_score, 2),
        "recent_anomalies": meter_anomalies[:5],
        "possible_causes": causes,
    }, ensure_ascii=False, indent=2)


# ── Tool 13: Auto-generate report ───────────────────────────

@tool
def generate_report(dma: str = "", month: str = "") -> str:
    """Generate a summary report for a DMA zone and month.
    Combines anomaly stats, consumption data, rankings, and NRW into one report.
    Use when the user asks for a report, summary, or overview analysis."""
    anomalies = _load("anomalies.json")
    daily = _load("daily_dma.json")
    ranks = _load("rank_changes.json")

    if month:
        anomalies = [a for a in anomalies if a["date"].startswith(month)]
    if dma:
        anomalies = [a for a in anomalies if _match_dma(dma, a.get("dma", ""))]

    # Anomaly summary
    type_counts = {}
    dma_counts = {}
    for a in anomalies:
        t = a.get("type", "unknown")
        d = a.get("dma", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
        dma_counts[d] = dma_counts.get(d, 0) + 1

    # Consumption summary
    total_consumption = 0
    days_count = 0
    for day in daily:
        if month and not day["date"].startswith(month):
            continue
        for dma_name, stats in day.get("dmas", {}).items():
            if dma and not _match_dma(dma, dma_name):
                continue
            total_consumption += stats.get("total", 0)
        days_count += 1

    avg_daily = round(total_consumption / max(days_count, 1), 1)

    # Top ranked meters in this DMA
    top_meters = [r for r in ranks if not dma or _match_dma(dma, r.get("dma", ""))][:5]

    report = {
        "report_period": month or "all time",
        "dma_filter": dma or "all zones",
        "consumption": {
            "total": round(total_consumption, 1),
            "daily_average": avg_daily,
            "days": days_count,
        },
        "anomalies": {
            "total": len(anomalies),
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


# ── Export all tools ──────────────────────────────────────────

ALL_TOOLS = [
    query_anomalies,
    query_meters,
    get_anomaly_stats,
    get_predictions,
    get_building_predictions,
    get_data_overview,
    query_daily_dma,
    query_weekly,
    query_rank_changes,
    query_monthly_diff,
    generate_chart,
    compare_months,
    analyze_anomaly,
    generate_report,
]
