"""Export SQLite (analytics_real.db) -> output_real/*.json for frontend build.

This is the transitional bridge restored after C4-7 deleted it.
Phase 5 still uses this because stage_publish doesn't emit JSON
(a future commit can move the logic into the orchestrator).

Restores the 14 JSON files that frontend/build.cjs copies into
dist/data/ when USE_REAL_DATA=1.
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


def _rows(conn, sql: str, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _maybe_json_load(v):
    if isinstance(v, str) and v:
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"ERROR: db not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    args.out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(args.db))
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Exporting from {args.db} -> {args.out}")

    # 1. meter_info — {meterId: {info}}
    data = {r["meterId"]: {k: v for k, v in r.items() if k != "meterId"}
            for r in _rows(conn, "SELECT * FROM meters")}
    for v in data.values():
        if "isResidential" in v:
            v["isResidential"] = bool(v["isResidential"])
    (args.out / "meter_info.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  meter_info.json: {len(data)}")

    # 2. available_dates
    data = [r["date"] for r in _rows(conn, "SELECT DISTINCT date FROM daily_dma ORDER BY date") if r.get("date")]
    (args.out / "available_dates.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  available_dates.json: {len(data)}")

    # 3. daily_dma — nested [{date, dmas: {dma: {total, residential, ...}}}]
    data = []
    for r in _rows(conn, "SELECT * FROM daily_dma ORDER BY date, dma"):
        date = r.get("date")
        if not date:
            continue
        if not data or data[-1]["date"] != date:
            data.append({"date": date, "dmas": {}})
        data[-1]["dmas"][r["dma"]] = {
            "total": r.get("total", 0), "residential": r.get("residential", 0),
            "nonResidential": r.get("nonResidential", 0),
            "resCount": r.get("resCount", 0), "nonResCount": r.get("nonResCount", 0),
            "meterCount": r.get("meterCount", 0), "rain": r.get("rain"),
        }
    (args.out / "daily_dma.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  daily_dma.json: {len(data)}")

    # 4. weekly — JSON-deserialize nested columns
    rows = _rows(conn, "SELECT * FROM weekly ORDER BY weekStart")
    for r in rows:
        for k in ("totalByDma", "wdByDmaRes", "dates", "dailyTotals"):
            r[k] = _maybe_json_load(r.get(k))
    (args.out / "weekly.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  weekly.json: {len(rows)}")

    # 5. daily_totals — {date: {meterId: total}}
    data = {}
    for r in _rows(conn, "SELECT meterId, date, total FROM meter_daily"):
        data.setdefault(r["date"], {})[r["meterId"]] = r.get("total", 0)
    (args.out / "daily_totals.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  daily_totals.json: {len(data)} days")

    # 6. daily_top20 — computed from daily_totals
    data = []
    for date in sorted(data):
        pass  # placeholder; we already wrote daily_totals above
    rows_by_date = {}
    for r in _rows(conn, "SELECT date, meterId, total FROM meter_daily ORDER BY date"):
        rows_by_date.setdefault(r["date"], []).append(
            {"meterId": r["meterId"], "total": r.get("total", 0)})
    top20_data = []
    for date in sorted(rows_by_date):
        items = sorted(rows_by_date[date], key=lambda x: -x["total"])[:20]
        top20_data.append({"date": date, "top20": items})
    (args.out / "daily_top20.json").write_text(
        json.dumps(top20_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  daily_top20.json: {len(top20_data)} days")

    # 7. rank_changes
    data = _rows(conn, "SELECT * FROM rank_changes ORDER BY daysInTop20 DESC")
    (args.out / "rank_changes.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  rank_changes.json: {len(data)}")

    # 8. monthly_main_sub_diff — nested [{month, diffs: [...]}]
    data = []
    for r in _rows(conn, "SELECT * FROM monthly_diff ORDER BY month, mainMeterId"):
        month = r.get("month")
        if not month:
            continue
        if not data or data[-1]["month"] != month:
            data.append({"month": month, "diffs": []})
        d = dict(r)
        d["subs"] = _maybe_json_load(d.get("subs")) or []
        data[-1]["diffs"].append(d)
    (args.out / "monthly_main_sub_diff.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  monthly_main_sub_diff.json: {len(data)}")

    # 9. search_index
    data = _rows(conn, "SELECT * FROM search_index")
    (args.out / "search_index.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  search_index.json: {len(data)}")

    # 10. anomalies
    data = _rows(conn, "SELECT * FROM anomalies ORDER BY date DESC, anomalyScore DESC")
    (args.out / "anomalies.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  anomalies.json: {len(data)}")

    # 11. data_errors
    data = _rows(conn, "SELECT * FROM data_errors ORDER BY ts DESC")
    (args.out / "data_errors.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  data_errors.json: {len(data)}")

    # 12. predictions — {predictions: [{meterId, info, predictions: [...]}]}
    info_map = {r["meterId"]: r for r in _rows(conn, "SELECT * FROM meters") if r.get("meterId")}
    by_meter: dict[str, list] = {}
    for r in _rows(conn, "SELECT * FROM predictions ORDER BY meterId, date"):
        by_meter.setdefault(r["meterId"], []).append({
            "date": r["date"], "value": r.get("predicted"),
            "lower": r.get("lower"), "upper": r.get("upper")})
    preds_out = []
    for mid, days in by_meter.items():
        preds_out.append({
            "meterId": mid, "info": info_map.get(mid, {}),
            "predictions": days, "trend": "", "modelScore": 0, "avgHistorical": 0,
        })
    date_rows = _rows(conn, "SELECT MIN(date) AS lo, MAX(date) AS hi FROM predictions")
    date_range = date_rows[0] if date_rows else {}
    (args.out / "predictions.json").write_text(
        json.dumps({
            "predictions": preds_out,
            "generatedAt": None,
            "historicalRange": [date_range.get("lo"), date_range.get("hi")],
            "totalMeters": len(preds_out),
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  predictions.json: {len(preds_out)}")

    # 13. predictions_fitted — not in v2 schema, empty stub
    (args.out / "predictions_fitted.json").write_text(
        json.dumps({"fitted": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  predictions_fitted.json: empty stub")

    # 14. cotai_calendar — not in v2 schema, preserve if exists
    cotai = args.out / "cotai_calendar.json"
    if not cotai.exists():
        cotai.write_text(json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  cotai_calendar.json: empty stub")
    else:
        print(f"  cotai_calendar.json: preserved")

    conn.close()
    print(f"\nDone. {len(list(args.out.glob('*.json')))} JSON files in {args.out}")


if __name__ == "__main__":
    main()
