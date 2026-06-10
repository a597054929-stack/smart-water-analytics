"""Export SQLite -> output_real/*.json for frontend build.

Phase 3 of ARCHITECTURE_OPTIMIZATION_PLAN: keeps the frontend's JSON contract
intact while the source of truth is now analytics_real.db. Called by
frontend/build.cjs as a pre-step (or run manually after migrate_to_sqlite_v2.py).

This file is the ONLY bridge between SQLite and JSON. Phase 4 will
collapse this into the orchestrator's 'publish' stage.

Usage:
    python scripts/export_json_for_frontend.py [--db backend/data/analytics_real.db]
                                                 [--out backend/data/output_real]

Legacy JSON shapes the frontend expects (mirrored from frontend/build.cjs
and frontend/js/* loaders):

  meter_info.json            {meterId: {buildingName, contractId, ...}}
  available_dates.json       [YYYY-MM-DD, ...]
  daily_dma.json             [{date, dmas: {dma: {total, residential, ...}}}]
  weekly.json                [{weekStart, weekEnd, label, dates, totalByDma, ...}]
  daily_top20.json           [{date, top20: [{meterId, total, dma, ...}]}]
  rank_changes.json          [{meterId, contractId, buildingName, ...}]
  monthly_main_sub_diff.json [{month, diffs: [{mainMeterId, dma, subs, mainTotal, ...}]}]
  search_index.json          [{id, contract, building, dma, type}]
  cotai_calendar.json        unchanged (NOT in v2 schema; preserve existing)
  anomalies.json             [{date, meterId, total, dma, type, anomalyScore, ...}]
  data_errors.json           [{ts, meterId, date, reason, rawValue}]
  predictions.json           {predictions: [{meterId, info, predictions:[{date, value, ...}]}], ...}
  predictions_fitted.json    {fitted: []}  (NOT in v2; emit empty)
  daily_totals.json          {date: {meterId: total}}
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "backend" / "data" / "analytics_real.db"
DEFAULT_OUT = ROOT / "backend" / "data" / "output_real"

MACAU_DMAS = ["澳門低區", "澳門填海A區", "澳大橫琴區", "路氹城區"]


def _rows(conn, sql: str, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _maybe_json_load(v):
    """SQLite TEXT columns that store JSON: deserialize on read."""
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


def export_meter_info(conn) -> dict:
    """{meterId: {buildingName, contractId, dma, propertyType, isResidential, ...}}"""
    rows = _rows(conn, "SELECT * FROM meters")
    out = {}
    for r in rows:
        mid = r.pop("meterId", None)
        if mid is None:
            continue
        # Frontend expects isResidential as bool, not 0/1
        if "isResidential" in r:
            r["isResidential"] = bool(r["isResidential"])
        out[mid] = r
    return out


def export_available_dates(conn) -> list[str]:
    rows = _rows(conn, "SELECT DISTINCT date FROM daily_dma ORDER BY date")
    return [r["date"] for r in rows if r.get("date")]


def export_daily_dma(conn) -> list[dict]:
    """[{date, dmas: {dma: {total, residential, ...}}}] — nested shape."""
    rows = _rows(conn, "SELECT * FROM daily_dma ORDER BY date, dma")
    by_date: dict[str, dict] = {}
    for r in rows:
        date = r.get("date")
        if not date:
            continue
        day = by_date.setdefault(date, {"date": date, "dmas": {}})
        day["dmas"][r["dma"]] = {
            "total":          r.get("total", 0),
            "residential":    r.get("residential", 0),
            "nonResidential": r.get("nonResidential", 0),
            "resCount":       r.get("resCount", 0),
            "nonResCount":    r.get("nonResCount", 0),
            "meterCount":     r.get("meterCount", 0),
            "rain":           r.get("rain"),
        }
    return list(by_date.values())


def export_weekly(conn) -> list[dict]:
    rows = _rows(conn, "SELECT * FROM weekly ORDER BY weekStart")
    out = []
    for r in rows:
        out.append({
            "weekStart":  r.get("weekStart"),
            "weekEnd":    r.get("weekEnd"),
            "label":      r.get("label"),
            "dates":      _maybe_json_load(r.get("dates")),
            "totalByDma": _maybe_json_load(r.get("totalByDma")),
            "grandTotal": r.get("grandTotal", 0),
            "weekdayAvg": r.get("weekdayAvg", 0),
            "weekendAvg": r.get("weekendAvg", 0),
            "wdByDmaRes": _maybe_json_load(r.get("wdByDmaRes")),
            "rain":       r.get("rain", 0),
            "dailyTotals": _maybe_json_load(r.get("dailyTotals")),
        })
    return out


def export_daily_top20(conn, daily_totals: dict) -> list[dict]:
    """[{date, top20: [...]}] — recomputed from daily_totals (per-day top 20 across all meters)."""
    out = []
    for date in sorted(daily_totals.keys()):
        day = daily_totals[date]
        items = [{"meterId": mid, "total": total} for mid, total in day.items()]
        items.sort(key=lambda x: -x["total"])
        out.append({"date": date, "top20": items[:20]})
    return out


def export_rank_changes(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM rank_changes ORDER BY daysInTop20 DESC")


def export_monthly_diff(conn) -> list[dict]:
    """[{month, diffs: [{...}]}] — nested shape with 'subs' deserialized."""
    rows = _rows(conn, "SELECT * FROM monthly_diff ORDER BY month, mainMeterId")
    by_month: dict[str, dict] = {}
    for r in rows:
        m = r.get("month")
        if not m:
            continue
        out = by_month.setdefault(m, {"month": m, "diffs": []})
        d = dict(r)
        d["subs"] = _maybe_json_load(d.get("subs")) or []
        out["diffs"].append(d)
    return list(by_month.values())


def export_search_index(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM search_index")


def export_anomalies(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM anomalies ORDER BY date DESC, anomalyScore DESC")


def export_data_errors(conn) -> list[dict]:
    return _rows(conn, "SELECT * FROM data_errors ORDER BY ts DESC")


def export_predictions(conn) -> dict:
    """{predictions: [{meterId, info, predictions:[...]}], generatedAt, historicalRange, totalMeters}"""
    rows = _rows(conn, "SELECT * FROM predictions ORDER BY meterId, date")
    by_meter: dict[str, list] = {}
    for r in rows:
        mid = r.get("meterId")
        if not mid:
            continue
        by_meter.setdefault(mid, []).append({
            "date":     r.get("date"),
            "value":    r.get("predicted"),
            "lower":    r.get("lower"),
            "upper":    r.get("upper"),
        })
    # Try to enrich with meter info (buildingName, dma, etc.) — frontend
    # uses p.info.buildingName for the table display.
    info_rows = _rows(conn, "SELECT * FROM meters")
    info = {r["meterId"]: r for r in info_rows if r.get("meterId")}
    out_predictions = []
    for mid, days in by_meter.items():
        out_predictions.append({
            "meterId":      mid,
            "info":         info.get(mid, {}),
            "predictions":  days,
            "trend":        "",
            "modelScore":   0,
            "avgHistorical": 0,
        })
    # Get date range
    date_rows = _rows(conn, "SELECT MIN(date) AS lo, MAX(date) AS hi FROM predictions")
    date_range = date_rows[0] if date_rows else {}
    return {
        "predictions":     out_predictions,
        "generatedAt":     None,
        "historicalRange": [date_range.get("lo"), date_range.get("hi")],
        "totalMeters":     len(out_predictions),
    }


def export_daily_totals(conn) -> dict:
    """{date: {meterId: total}} — direct mirror of meter_daily table."""
    rows = _rows(conn, "SELECT meterId, date, total FROM meter_daily")
    out: dict[str, dict] = {}
    for r in rows:
        date = r.get("date")
        mid = r.get("meterId")
        if not date or not mid:
            continue
        out.setdefault(date, {})[mid] = r.get("total", 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: db not found: {args.db}")
        sys.exit(1)
    args.out.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(args.db))
    sys.stdout.reconfigure(encoding="utf-8")

    # Run all exports and write JSON files
    print(f"Exporting from {args.db} -> {args.out}")

    # 1. meter_info
    data = export_meter_info(conn)
    (args.out / "meter_info.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  meter_info.json: {len(data)} meters")

    # 2. available_dates
    data = export_available_dates(conn)
    (args.out / "available_dates.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  available_dates.json: {len(data)} dates")

    # 3. daily_dma (nested)
    data = export_daily_dma(conn)
    (args.out / "daily_dma.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  daily_dma.json: {len(data)} days")

    # 4. weekly
    data = export_weekly(conn)
    (args.out / "weekly.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  weekly.json: {len(data)} weeks")

    # 5. daily_totals (needed for daily_top20)
    data = export_daily_totals(conn)
    (args.out / "daily_totals.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  daily_totals.json: {len(data)} days, {sum(len(v) for v in data.values())} meter-days")

    # 6. daily_top20 (computed from daily_totals)
    data = export_daily_top20(conn, data)
    (args.out / "daily_top20.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  daily_top20.json: {len(data)} days")

    # 7. rank_changes
    data = export_rank_changes(conn)
    (args.out / "rank_changes.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  rank_changes.json: {len(data)} meters")

    # 8. monthly_main_sub_diff (nested)
    data = export_monthly_diff(conn)
    (args.out / "monthly_main_sub_diff.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  monthly_main_sub_diff.json: {len(data)} months")

    # 9. search_index
    data = export_search_index(conn)
    (args.out / "search_index.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  search_index.json: {len(data)} entries")

    # 10. anomalies
    data = export_anomalies(conn)
    (args.out / "anomalies.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  anomalies.json: {len(data)} anomalies")

    # 11. data_errors
    data = export_data_errors(conn)
    (args.out / "data_errors.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  data_errors.json: {len(data)} errors")

    # 12. predictions (legacy nested shape with .info)
    data = export_predictions(conn)
    (args.out / "predictions.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  predictions.json: {data['totalMeters']} meters")

    # 13. predictions_fitted — NOT in v2 schema; emit empty stub.
    # Frontend reads _predFitted = predFitted?.fitted ?? [] and tolerates empty.
    (args.out / "predictions_fitted.json").write_text(
        json.dumps({"fitted": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  predictions_fitted.json: empty (not in v2 schema)")

    # 14. cotai_calendar — NOT in v2 schema; preserve existing if present.
    cotai_path = args.out / "cotai_calendar.json"
    if not cotai_path.exists():
        # Emit a minimal stub so the fetch doesn't 404.
        cotai_path.write_text(
            json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  cotai_calendar.json: empty stub (was not present)")
    else:
        print(f"  cotai_calendar.json: preserved (not in v2 schema)")

    conn.close()
    print(f"\nDone. {len(list(args.out.glob('*.json')))} JSON files in {args.out}")


if __name__ == "__main__":
    main()
