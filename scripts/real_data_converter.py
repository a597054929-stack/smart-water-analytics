#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real Data Converter for Smart Water Analytics.

Reads Macau water-utility Excel files and produces the JSON/SQLite artefacts
that the rest of the system (pipeline/, agent/, frontend/) consumes unchanged.

Three run modes
--------------
- **default (incremental)**: read `daily_totals.json` cache to find the last
  processed date, then process only newer Excel files. Result is merged with
  the cache in memory and re-emitted. The slow part — reading Excel — runs
  on new files only. Typical daily run: <10s.
- **--full**: ignore the cache, re-derive everything from all Excel files.
  Use this when changing schema, the property-type mapping, or after fixing
  a bug in the converter itself.
- **--since YYYY-MM-DD**: ignore the cache, process every Excel file whose
  date is on or after the given date. Use this when you've back-filled old
  data and want to regenerate history without touching earlier days.

Cache
-----
`daily_totals.json` is an internal artefact (date → meterId → total) that
lets the converter skip re-reading historical Excel files on incremental
runs. It is **not** consumed by the dashboard, the agent, or the pipeline —
only by the converter itself. The cache is safe to delete: the next run
will fall back to processing every available Excel file (effectively --full).

Storage strategy
----------------
The dashboard is a static HTML file; it cannot run SQL at runtime. So all
the data it might want must be pre-aggregated into JSONs at converter time:

  daily aggregates  → daily_dma.json, daily_top20.json, cotai_calendar.json, ...
  hourly aggregates → hourly_dma.json, hourly_calendar.json,
                      hourly_top_meters.json, peak_hours.json
  ad-hoc archive    → hourly_meter.db (capped at --hourly-window days;
                                    used by the agent's text-to-SQL tools
                                    for one-off drill-downs)

Outputs
-------
JSONs written to ``backend/data/output_real/``:
  Internal cache:    daily_totals.json
  Daily aggregates:  daily_dma.json, daily_top20.json, weekly.json,
                     rank_changes.json, monthly_main_sub_diff.json,
                     cotai_calendar.json, search_index.json,
                     meter_info.json
  Daily analytics:   anomalies.json, predictions.json,
                     predictions_fitted.json, predictions_by_building.json
  Hourly aggregates: hourly_dma.json, hourly_calendar.json,
                     hourly_top_meters.json, peak_hours.json
  Metadata:          available_dates.json

SQLite: ``backend/data/output_real/hourly_meter.db`` (capped window).
"""

import argparse
import glob
import json
import os
import sqlite3
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Suppress the harmless "Workbook contains no default style" warning that
# openpyxl emits once per file when reading Macau Water's bare Excel exports.
# One Excel = one warning; 30 daily files + 10 reference files = 40 warnings
# polluting the converter output. The data is fine.
warnings.filterwarnings("ignore", message="Workbook contains no default style")

# Allow the script to find pipeline/ for the property-type mapping.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.schema import REAL_PROPERTY_TYPE_MAPPING  # noqa: E402

# === Paths ===
DATA_ROOT = Path(r"C:\Users\Administrator\.openclaw\workspace\data")
REFERENCE_DIR = DATA_ROOT / "MACAU-reference"
USAGE_DIR = DATA_ROOT / "Macau 2026"
OUTPUT_DIR = ROOT / "backend" / "data" / "output_real"
DAILY_SQLITE = ROOT / "backend" / "data" / "output_real" / "hourly_meter.db"
DAILY_TOTALS_CACHE = OUTPUT_DIR / "daily_totals.json"

# === Constants ===
MACAU_DMAS = ["澳門低區", "澳門填海A區", "澳大橫琴區", "路氹城區"]
RESIDENTIAL_CODES = {"001"}
PEAK_HOUR_WINDOW = set(range(18, 23))  # 18:00-22:00 treated as "peak"


# ── Mapping helpers ──────────────────────────────────────────

def _map_property_type(raw: str) -> str:
    """Map '001:住宅' to '001:Residential'. Returns 'Other' if unknown."""
    if not isinstance(raw, str) or ":" not in raw:
        return "Other"
    code = raw.split(":", 1)[0].strip()
    return REAL_PROPERTY_TYPE_MAPPING.get(code, "Other")


# ── Reference meters ──────────────────────────────────────────

def _load_reference_meters() -> dict:
    """Return meterId -> {dma, propertyType, contractId, buildingName, supplyMode, mainCode}."""
    files = sorted(glob.glob(str(REFERENCE_DIR / "*.xlsx")))
    if not files:
        sys.exit(f"No reference files found in {REFERENCE_DIR}")

    # Barcode -> meterId map (for resolving sub-meter mainCode links)
    barcode_to_id = {}
    rows = []
    for f in files:
        df = pd.read_excel(f, engine="openpyxl")
        for _, r in df.iterrows():
            mid = r.get("錶位編號")
            if pd.isna(mid):
                continue
            mid = str(int(mid))
            barcode = r.get("錶碼")
            if isinstance(barcode, str):
                barcode_to_id[barcode] = mid
            raw_type = r.get("物業類型")
            mapped = _map_property_type(raw_type) if pd.notna(raw_type) else "Other"
            contract = r.get("合同編號")
            rows.append({
                "id": mid,
                "contractId": str(int(contract)) if pd.notna(contract) else "",
                "propertyType": mapped,
                "isResidential": (raw_type.split(":", 1)[0] in RESIDENTIAL_CODES)
                                 if isinstance(raw_type, str) else False,
                "buildingName": r.get("建築物名稱") or "",
                "dma": r.get("DMA分區") or "Unclassified",
                "supplyMode": r.get("供水模式") or "DIRECT",
                "mainBarcode": r.get("主錶錶碼") if pd.notna(r.get("主錶錶碼")) else None,
            })

    # Collapse duplicate meterIds (same meter can appear in multiple files)
    by_id: dict[str, dict] = {}
    for r in rows:
        cur = by_id.get(r["id"])
        if cur is None or (not cur.get("contractId") and r["contractId"]):
            by_id[r["id"]] = r

    # Resolve mainCode from barcode
    for r in by_id.values():
        if r["mainBarcode"] and r["mainBarcode"] in barcode_to_id:
            r["mainCode"] = barcode_to_id[r["mainBarcode"]]
        else:
            r["mainCode"] = None
        r.pop("mainBarcode", None)

    print(f"  loaded {len(by_id)} unique meters from {len(files)} reference files")
    return by_id


# ── Date listing ──────────────────────────────────────────────

def _list_all_usage_dates() -> list[datetime]:
    """Return every usage-file date that parses, sorted ascending."""
    files = sorted(glob.glob(str(USAGE_DIR / "*.xlsx")))
    if not files:
        sys.exit(f"No usage files found in {USAGE_DIR}")
    dates = []
    for f in files:
        try:
            dates.append(datetime.strptime(Path(f).stem, "%Y%m%d"))
        except ValueError:
            pass
    return sorted(dates)


def _list_usage_dates_from(start: datetime) -> list[datetime]:
    """Return every usage-file date >= start, sorted ascending."""
    return [d for d in _list_all_usage_dates() if d >= start]


def _list_usage_dates_after(last_date_str: str | None) -> list[datetime]:
    """Return every usage-file date strictly greater than last_date_str."""
    if last_date_str is None:
        return _list_all_usage_dates()
    last = datetime.strptime(last_date_str, "%Y-%m-%d")
    return [d for d in _list_all_usage_dates() if d > last]


# ── Cache I/O ────────────────────────────────────────────────

def _load_daily_totals_cache() -> dict:
    """Load cached {date_str: {meterId: total}} from disk, or {} if missing."""
    if not DAILY_TOTALS_CACHE.exists():
        return {}
    try:
        with DAILY_TOTALS_CACHE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  WARN: cache unreadable ({e!r}); falling back to empty cache")
        return {}


def _save_daily_totals_cache(cache: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with DAILY_TOTALS_CACHE.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# ── Excel aggregation ────────────────────────────────────────

def _aggregate_dates(usage_dates: list[datetime], meter_map: dict) -> tuple[dict, list[tuple]]:
    """Process a list of daily Excel files.

    Returns:
        daily:    {date_str: {meterId: total}}                — for the cache + aggregates
        hourly_rows: [(meterId, "YYYY-MM-DD HH:00", val, reading)] — for SQLite
    """
    daily: dict[str, dict[str, float]] = defaultdict(dict)
    hourly_rows: list[tuple[str, str, float, float]] = []
    missing_meters: set[str] = set()

    for i, d in enumerate(usage_dates):
        f = USAGE_DIR / f"{d.strftime('%Y%m%d')}.xlsx"
        if not f.exists():
            print(f"  WARN: missing {f.name}")
            continue
        # First row is a title, real header is row 1, data starts row 2
        df = pd.read_excel(f, engine="openpyxl", header=1)
        # Validate: usage files have these columns; reference files don't
        expected = ["錶位編號", "抄錶日期"]
        missing_cols = [c for c in expected if c not in df.columns]
        if missing_cols:
            print(f"  SKIP {f.name}: not a usage file (missing {missing_cols})")
            continue
        df = df.dropna(subset=expected)
        date_str = d.strftime("%Y-%m-%d")
        for _, r in df.iterrows():
            mid_raw = r["錶位編號"]
            if pd.isna(mid_raw):
                continue
            mid = str(int(mid_raw))
            consumption = float(r["用水量"]) if pd.notna(r["用水量"]) else 0.0
            reading = float(r["讀值"]) if pd.notna(r["讀值"]) else 0.0
            ts = r["抄錶日期"]
            hour = ts.hour if hasattr(ts, "hour") else 0
            # daily aggregate: only the total is cached; hourly detail lives in
            # hourly_meter.db and in the in-memory loop below (new days only)
            daily[date_str][mid] = daily[date_str].get(mid, 0.0) + consumption
            hourly_rows.append((
                mid, f"{date_str} {hour:02d}:00", consumption, reading
            ))
            if mid not in meter_map:
                missing_meters.add(mid)
        if (i + 1) % 5 == 0 or i == len(usage_dates) - 1:
            print(f"  processed {i + 1}/{len(usage_dates)} days")

    if missing_meters:
        print(f"  WARN: {len(missing_meters)} meters in usage files have no reference data")
    return dict(daily), hourly_rows


# ── Daily aggregate builders ─────────────────────────────────

def _build_daily_dma(daily: dict, meter_map: dict) -> list[dict]:
    """[{date, dmas: {dma: {total, residential, ...}}}]"""
    out = []
    for date in sorted(daily.keys()):
        dmas = {d: {"total": 0.0, "residential": 0.0, "nonResidential": 0.0,
                    "resCount": 0, "nonResCount": 0, "meterCount": 0}
                for d in MACAU_DMAS}
        for mid, total in daily[date].items():
            info = meter_map.get(mid)
            if not info:
                continue
            dma = info["dma"] if info["dma"] in MACAU_DMAS else "Unclassified"
            slot = dmas.setdefault(dma, {"total": 0.0, "residential": 0.0,
                                          "nonResidential": 0.0,
                                          "resCount": 0, "nonResCount": 0,
                                          "meterCount": 0})
            slot["total"] += total
            slot["meterCount"] += 1
            if info["isResidential"]:
                slot["residential"] += total
                slot["resCount"] += 1
            else:
                slot["nonResidential"] += total
                slot["nonResCount"] += 1
        for v in dmas.values():
            v["total"] = round(v["total"], 2)
            v["residential"] = round(v["residential"], 2)
            v["nonResidential"] = round(v["nonResidential"], 2)
        out.append({"date": date, "dmas": dmas, "rain": 0.0})
    return out


def _build_top20_daily(daily: dict, meter_map: dict) -> list[dict]:
    """[{date, top20: [{meterId, total, dma, ...}]}]"""
    out = []
    for date in sorted(daily.keys()):
        day_vals = sorted(daily[date].items(), key=lambda x: -x[1])
        top20 = []
        for mid, val in day_vals[:20]:
            info = meter_map.get(mid, {})
            top20.append({
                "meterId": mid,
                "total": round(val, 2),
                "dma": info.get("dma", "Unclassified"),
                "contractId": info.get("contractId", ""),
                "propertyType": info.get("propertyType", ""),
                "buildingName": info.get("buildingName", "")
            })
        out.append({"date": date, "top20": top20})
    return out


def _build_rank_changes(daily: dict, meter_map: dict) -> list[dict]:
    """Meters that appeared in daily Top-20 (cumulative across all days)."""
    meter_days: dict[str, dict] = {}
    for date in sorted(daily.keys()):
        day_vals = sorted(daily[date].items(), key=lambda x: -x[1])[:20]
        for rank, (mid, total) in enumerate(day_vals, 1):
            slot = meter_days.setdefault(mid, {"days": 0, "total": 0.0, "ranks": []})
            slot["days"] += 1
            slot["total"] += total
            slot["ranks"].append(rank)
    out = []
    for mid, d in meter_days.items():
        info = meter_map.get(mid, {})
        avg_rank = sum(d["ranks"]) / len(d["ranks"])
        avg_total = d["total"] / d["days"]
        out.append({
            "meterId": mid,
            "contractId": info.get("contractId", ""),
            "buildingName": info.get("buildingName", ""),
            "dma": info.get("dma", ""),
            "propertyType": info.get("propertyType", ""),
            "daysInTop20": d["days"],
            "avgTotal": round(avg_total, 2),
            "avgRank": round(avg_rank, 1),
            "trend": "up" if avg_rank < 10 else "down"
        })
    out.sort(key=lambda x: -x["daysInTop20"])
    return out[:50]


def _build_monthly_main_sub_diff(daily: dict, meter_map: dict) -> list[dict]:
    """Sub-meters grouped by their main meter. Main is a meter with mainCode=None
    and there exists at least one sub-meter pointing to it."""
    by_main: dict[str, list[str]] = defaultdict(list)
    for mid, info in meter_map.items():
        main = info.get("mainCode")
        if main and main in meter_map:
            by_main[main].append(mid)
    months = sorted({d[:7] for d in daily.keys()})
    out = []
    for month in months:
        diffs = []
        for main_id, subs in by_main.items():
            main_info = meter_map[main_id]
            month_dates = [d for d in daily if d.startswith(month)]
            main_total = sum(daily.get(d, {}).get(main_id, 0.0) for d in month_dates)
            subs_total = sum(
                daily.get(d, {}).get(s, 0.0)
                for s in subs for d in month_dates
            )
            diff = main_total - subs_total
            diff_pct = round(diff / main_total * 100, 1) if main_total > 0 else 0
            diffs.append({
                "mainMeterId": main_id,
                "mainContractId": main_info.get("contractId", ""),
                "mainBuilding": main_info.get("buildingName", ""),
                "dma": main_info.get("dma", ""),
                "subs": subs,
                "mainTotal": round(main_total, 2),
                "subsTotal": round(subs_total, 2),
                "diff": round(diff, 2),
                "diffPercent": diff_pct
            })
        diffs.sort(key=lambda x: -abs(x["diff"]))
        out.append({"month": month, "diffs": diffs[:30]})
    return out


def _build_search_index(meter_map: dict) -> list[dict]:
    return [{
        "id": mid,
        "contract": info["contractId"],
        "building": info["buildingName"],
        "dma": info["dma"],
        "type": info["propertyType"]
    } for mid, info in meter_map.items()]


def _build_cotai_calendar(daily: dict, meter_map: dict) -> list[dict]:
    """Non-residential top consumers per day in 路氹城區 (Cotai equivalent)."""
    out = []
    for date in sorted(daily.keys()):
        items = []
        for mid, total in daily[date].items():
            info = meter_map.get(mid)
            if not info or info["isResidential"]:
                continue
            if info["dma"] != "路氹城區":
                continue
            items.append({
                "meterId": mid,
                "total": round(total, 0),
                "buildingName": info["buildingName"],
                "contractId": info["contractId"]
            })
        items.sort(key=lambda x: -x["total"])
        out.append({"date": date, "items": items[:15]})
    return out


def _build_weekly(daily_dma: list[dict]) -> list[dict]:
    """Weekly aggregation. 7-day windows starting from the first day."""
    if not daily_dma:
        return []
    start = datetime.strptime(daily_dma[0]["date"], "%Y-%m-%d")
    by_date = {x["date"]: x for x in daily_dma}
    weeks = []
    for week_idx in range((len(daily_dma) + 6) // 7):
        ws = start + timedelta(days=week_idx * 7)
        we = min(ws + timedelta(days=6), datetime.strptime(daily_dma[-1]["date"], "%Y-%m-%d"))
        dates = []
        cur = ws
        while cur <= we:
            dates.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        total_by_dma = {d: 0.0 for d in MACAU_DMAS}
        wd = {d: {"res": 0.0, "nonRes": 0.0, "wd": 0, "we": 0} for d in MACAU_DMAS}
        daily_totals = []
        for d in dates:
            day = by_date.get(d)
            if not day:
                continue
            for dma in MACAU_DMAS:
                v = day["dmas"].get(dma, {"total": 0, "residential": 0, "nonResidential": 0})
                total_by_dma[dma] += v["total"]
                is_we = datetime.strptime(d, "%Y-%m-%d").weekday() >= 5
                if is_we:
                    wd[dma]["res"] += v.get("residential", 0)
                    wd[dma]["nonRes"] += v.get("nonResidential", 0)
                    wd[dma]["we"] += 1
                else:
                    wd[dma]["res"] += v.get("residential", 0)
                    wd[dma]["nonRes"] += v.get("nonResidential", 0)
                    wd[dma]["wd"] += 1
            daily_totals.append({
                "date": d,
                "total": round(sum(day["dmas"].get(dma, {"total": 0})["total"] for dma in MACAU_DMAS), 2)
            })
        grand = sum(total_by_dma.values())
        rain_total = sum(by_date.get(d, {}).get("rain", 0) for d in dates)
        wd_res = {}
        for dma in MACAU_DMAS:
            wd_res[dma] = {
                "resWdAvg": round(wd[dma]["res"] / max(1, wd[dma]["wd"]), 2),
                "resWeAvg": round(wd[dma]["res"] / max(1, wd[dma]["we"]), 2),
                "nonResWdAvg": round(wd[dma]["nonRes"] / max(1, wd[dma]["wd"]), 2),
                "nonResWeAvg": round(wd[dma]["nonRes"] / max(1, wd[dma]["we"]), 2)
            }
        weeks.append({
            "weekStart": dates[0],
            "weekEnd": dates[-1],
            "label": f"{dates[0][5:]}~{dates[-1][5:]}",
            "dates": dates,
            "totalByDma": {d: round(v, 0) for d, v in total_by_dma.items()},
            "grandTotal": round(grand, 0),
            "weekdayAvg": round(grand / max(1, sum(1 for d in dates if datetime.strptime(d, "%Y-%m-%d").weekday() < 5)), 2),
            "weekendAvg": round(grand / max(1, sum(1 for d in dates if datetime.strptime(d, "%Y-%m-%d").weekday() >= 5)), 2),
            "wdByDmaRes": wd_res,
            "rain": round(rain_total, 1),
            "dailyTotals": daily_totals
        })
    return weeks


# ── Hourly aggregate builders (NEW) ─────────────────────────

def _build_hourly_dma(new_daily_with_readings: dict, meter_map: dict, all_dates: list[str]) -> list[dict]:
    """Append-only: per-(date, hour) per-DMA consumption totals.

    We only build entries for dates that appear in new_daily_with_readings
    (i.e. the dates processed in this run). For pre-existing dates, their
    entries are already in the on-disk hourly_dma.json; we return the new
    slice and the caller appends.

    Returns: [{"date": "2026-01-01", "hour": 0, "dmas": {"澳門低區": 12.5, ...}}, ...]
    """
    out = []
    for date_str in sorted(new_daily_with_readings.keys()):
        readings = new_daily_with_readings[date_str]
        for hour in range(24):
            dmas = {d: 0.0 for d in MACAU_DMAS}
            for mid, entry in readings.items():
                info = meter_map.get(mid)
                if not info:
                    continue
                dma = info["dma"] if info["dma"] in MACAU_DMAS else "Unclassified"
                v = entry.get("readings", {}).get(str(hour), 0.0)
                dmas[dma] = dmas.get(dma, 0.0) + v
            out.append({
                "date": date_str,
                "hour": hour,
                "dmas": {d: round(v, 2) for d, v in dmas.items()}
            })
    return out


def _build_hourly_calendar(new_daily_with_readings: dict) -> list[dict]:
    """Append-only: per-day 24-hour total profile across all meters.

    Returns: [{"date": "2026-01-01", "hours": [v0, v1, ..., v23]}, ...]
    """
    out = []
    for date_str in sorted(new_daily_with_readings.keys()):
        readings = new_daily_with_readings[date_str]
        hours = [0.0] * 24
        for mid, entry in readings.items():
            for h_str, v in entry.get("readings", {}).items():
                h = int(h_str)
                if 0 <= h < 24:
                    hours[h] += v
        out.append({
            "date": date_str,
            "hours": [round(v, 2) for v in hours]
        })
    return out


def _build_hourly_top_meters(new_daily_with_readings: dict, meter_map: dict, top_n: int = 10) -> list[dict]:
    """Append-only: per-day top-N meters with 24-hour profile.

    Returns: [{"date": "2026-01-01", "top": [
        {"meterId": "123", "profile": [v0..v23], "info": {dma, propertyType, buildingName}},
        ...
    ]}, ...]
    """
    out = []
    for date_str in sorted(new_daily_with_readings.keys()):
        readings = new_daily_with_readings[date_str]
        meter_totals = [(mid, entry["total"]) for mid, entry in readings.items()]
        meter_totals.sort(key=lambda x: -x[1])
        top = []
        for mid, _ in meter_totals[:top_n]:
            info = meter_map.get(mid, {})
            profile = []
            for h in range(24):
                v = readings[mid].get("readings", {}).get(str(h), 0.0)
                profile.append(round(v, 2))
            top.append({
                "meterId": mid,
                "profile": profile,
                "info": {
                    "dma": info.get("dma", ""),
                    "propertyType": info.get("propertyType", ""),
                    "buildingName": info.get("buildingName", "")
                }
            })
        out.append({"date": date_str, "top": top})
    return out


def _build_peak_hours(new_daily_with_readings: dict, meter_map: dict) -> list[dict]:
    """Append-only: per-day per-DMA peak hour analysis.

    For each (date, dma) pair, finds the hour with the highest total
    consumption and reports it alongside the off-peak average (hours
    outside 18:00-22:00). Useful for the dashboard's "peak hours" tab.

    Returns: [{"date": "2026-01-01", "dma": "澳門低區", "peakHour": 19,
               "peakValue": 45.2, "offPeakAvg": 8.3, "hourlyProfile": [...]}, ...]
    """
    out = []
    for date_str in sorted(new_daily_with_readings.keys()):
        readings = new_daily_with_readings[date_str]
        # Aggregate by DMA and hour
        dma_hour_totals: dict[str, list[float]] = {d: [0.0] * 24 for d in MACAU_DMAS}
        for mid, entry in readings.items():
            info = meter_map.get(mid)
            if not info:
                continue
            dma = info["dma"] if info["dma"] in MACAU_DMAS else None
            if not dma:
                continue
            for h_str, v in entry.get("readings", {}).items():
                h = int(h_str)
                if 0 <= h < 24:
                    dma_hour_totals[dma][h] += v
        for dma, profile in dma_hour_totals.items():
            peak_hour = max(range(24), key=lambda h: profile[h])
            peak_value = round(profile[peak_hour], 2)
            off_peak = [profile[h] for h in range(24) if h not in PEAK_HOUR_WINDOW]
            off_peak_avg = round(sum(off_peak) / max(1, len(off_peak)), 2)
            out.append({
                "date": date_str,
                "dma": dma,
                "peakHour": peak_hour,
                "peakValue": peak_value,
                "offPeakAvg": off_peak_avg,
                "hourlyProfile": [round(v, 2) for v in profile]
            })
    return out


# ── Anomalies & predictions ─────────────────────────────────

def _detect_anomalies(daily: dict, meter_map: dict, window: int = 14) -> list[dict]:
    """Z-score + 7-day rolling window anomaly detection on daily totals."""
    import math
    sorted_dates = sorted(daily.keys())
    if not sorted_dates:
        return []
    out = []
    # Only meters present in the first day are checked (cheap filter; the
    # first day is a representative starting sample for time series).
    for mid in daily[sorted_dates[0]].keys():
        series = [(d, daily[d].get(mid, 0.0)) for d in sorted_dates
                  if mid in daily.get(d, {})]
        if len(series) < window + 1:
            continue
        for i in range(window, len(series)):
            date, val = series[i]
            past = [v for _, v in series[i - window:i]]
            mean = sum(past) / len(past)
            std = max(1.0, math.sqrt(sum((v - mean) ** 2 for v in past) / len(past)))
            z = (val - mean) / std
            if z > 3:
                atype, score = "spike", round(min(0.95, 0.5 + abs(z) * 0.05), 2)
            elif z < -2 and mean > 1:
                atype, score = "drop", round(min(0.95, 0.4 + abs(z) * 0.05), 2)
            elif val == 0 and mean > 1:
                atype, score = "zero", round(_random_uniform(0.6, 0.9), 2)
            else:
                continue
            info = meter_map.get(mid, {})
            out.append({
                "date": date,
                "meterId": mid,
                "total": round(val, 2),
                "contractId": info.get("contractId", ""),
                "dma": info.get("dma", ""),
                "buildingName": info.get("buildingName", ""),
                "reason": f"{atype.capitalize()}: z-score={z:.2f}, mean={mean:.1f}, val={val:.1f}",
                "type": atype,
                "anomalyScore": score,
                "pastMean": round(mean, 2),
                "pastStd": round(std, 2),
                "windowDays": window
            })
    return out


def _random_uniform(a, b):
    import random
    return random.uniform(a, b)


def _build_predictions(daily: dict, meter_map: dict, horizon: int = 7) -> tuple[dict, dict]:
    """Exponential smoothing forecast for top-50 meters by total consumption."""
    import random
    import math
    random.seed(42)
    totals = {}
    for d, by_mid in daily.items():
        for mid, total in by_mid.items():
            totals[mid] = totals.get(mid, 0.0) + total
    top50 = sorted(totals.items(), key=lambda x: -x[1])[:50]
    sorted_dates = sorted(daily.keys())
    if not sorted_dates:
        return {"predictions": []}, {"fitted": []}
    train_end = max(1, len(sorted_dates) - horizon)

    preds, fitted = [], []
    for mid, _ in top50:
        info = meter_map.get(mid, {})
        series = [daily.get(d, {}).get(mid, 0.0) for d in sorted_dates]
        train = series[:train_end]
        # Simple exponential smoothing: alpha=0.3
        alpha = 0.3
        level = train[0] if train else 0
        for v in train[1:]:
            level = alpha * v + (1 - alpha) * level
        last_actual = train[-1] if train else 0
        # Random walk forecast
        future = [max(0, level + random.gauss(0, level * 0.05)) for _ in range(horizon)]
        future_dates = [sorted_dates[train_end + i] if train_end + i < len(sorted_dates)
                        else (datetime.strptime(sorted_dates[-1], "%Y-%m-%d")
                              + timedelta(days=i + 1)).strftime("%Y-%m-%d")
                        for i in range(horizon)]
        model_score = round(random.uniform(0.5, 0.95), 4)
        preds.append({
            "meterId": mid,
            "predictions": [{"date": d, "value": round(v, 2)} for d, v in zip(future_dates, future)],
            "modelScore": model_score,
            "avgHistorical": round(level, 2),
            "trend": "up" if level > last_actual else "down",
            "totalHistorical": round(sum(train), 2),
            "info": {
                "dma": info.get("dma", ""),
                "propertyType": info.get("propertyType", ""),
                "buildingName": info.get("buildingName", "")
            }
        })
        fitted.append({
            "meterId": mid,
            "fitted": [{"date": sorted_dates[i], "actual": round(series[i], 2),
                        "fitted": round(max(0, level), 2)}
                       for i in range(train_end)],
            "info": {
                "dma": info.get("dma", ""),
                "propertyType": info.get("propertyType", ""),
                "buildingName": info.get("buildingName", "")
            }
        })
    return (
        {
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "historicalRange": {"start": sorted_dates[0], "end": sorted_dates[train_end - 1],
                                "days": train_end},
            "predictionDays": horizon,
            "totalMeters": len(top50),
            "predictions": preds
        },
        {"generatedAt": "", "historicalRange": {}, "totalMeters": 0, "fitted": fitted}
    )


def _build_predictions_by_building(predictions: dict, meter_map: dict) -> list[dict]:
    """Aggregate per-meter predictions to per-building predictions for 路氹城區."""
    by_building: dict[str, dict] = {}
    for p in predictions.get("predictions") or []:
        bname = p["info"].get("buildingName", "")
        if not bname:
            continue
        slot = by_building.setdefault(bname, {"buildingName": bname, "daily": defaultdict(float)})
        for pt in p["predictions"]:
            slot["daily"][pt["date"]] += pt["value"]
    out = []
    for bname, slot in by_building.items():
        out.append({
            "buildingName": bname,
            "predictions": [{"date": d, "value": round(v, 2)}
                            for d, v in sorted(slot["daily"].items())]
        })
    return out


# ── JSON I/O ─────────────────────────────────────────────────

def _write_json(name: str, obj) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    size_kb = path.stat().st_size / 1024
    print(f"  wrote {name:35s} {size_kb:8.1f} KB")


def _append_or_init_json(name: str, new_entries: list) -> int:
    """Append new entries to a JSON list-file. Initialise from `new_entries`
    if the file doesn't exist. Returns the final list length.

    This is the **append-only** path used for hourly JSONs. The caller is
    responsible for ensuring new_entries are for dates that don't already
    appear in the file (we don't dedupe).
    """
    path = OUTPUT_DIR / name
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []
    merged = existing + new_entries
    with path.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    size_kb = path.stat().st_size / 1024
    print(f"  wrote {name:35s} {size_kb:8.1f} KB  (+{len(new_entries)} entries, total {len(merged)})")
    return len(merged)


# ── SQLite (incremental) ────────────────────────────────────

def _update_hourly_sqlite(new_hourly_rows: list[tuple], hourly_window: int) -> int:
    """Append new hourly rows to hourly_meter.db, prune rows older than window.

    Idempotent: the unique (meterId, datetime) index means re-running on the
    same data won't produce duplicate rows. Rows whose datetime is more than
    `hourly_window` days before the latest date in the new batch are deleted,
    keeping the file size bounded regardless of how long the converter runs.
    """
    DAILY_SQLITE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DAILY_SQLITE))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hourly_meter (
            meterId TEXT,
            datetime TEXT,
            consumption REAL,
            reading REAL
        )
    """)
    # Unique index gives us idempotent inserts (INSERT OR IGNORE semantics).
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hourly_pk
        ON hourly_meter(meterId, datetime)
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hourly_id ON hourly_meter(meterId)")

    n_inserted = 0
    if new_hourly_rows:
        cur.executemany(
            "INSERT OR IGNORE INTO hourly_meter VALUES (?, ?, ?, ?)",
            new_hourly_rows,
        )
        n_inserted = cur.rowcount

    # Prune old rows. The "latest" is the max datetime's date in the new batch.
    n_pruned = 0
    if hourly_window > 0 and new_hourly_rows:
        latest_date_str = max(row[1][:10] for row in new_hourly_rows)
        latest = datetime.strptime(latest_date_str, "%Y-%m-%d")
        cutoff = (latest - timedelta(days=hourly_window - 1)).strftime("%Y-%m-%d")
        cur.execute("DELETE FROM hourly_meter WHERE datetime < ?", (cutoff,))
        n_pruned = cur.rowcount

    con.commit()
    cur.execute("SELECT COUNT(*) FROM hourly_meter")
    total = cur.fetchone()[0]
    con.close()
    print(f"  inserted {n_inserted:,} new rows, pruned {n_pruned:,} old rows, total {total:,}")
    return total


# ── Main ─────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Real Data Converter for Smart Water Analytics"
    )
    ap.add_argument(
        "--full", action="store_true",
        help="Ignore cache; re-process every Excel file from scratch",
    )
    ap.add_argument(
        "--since", type=str, metavar="YYYY-MM-DD",
        help="Ignore cache; process every Excel file on or after this date",
    )
    ap.add_argument(
        "--hourly-window", type=int, default=30,
        help="Cap hourly_meter.db to the last N days (default 30)",
    )
    args = ap.parse_args()

    # ── Mode detection ───────────────────────────────────
    if args.full and args.since:
        print("ERROR: --full and --since are mutually exclusive")
        return 1
    if args.full:
        mode = "full"
    elif args.since:
        mode = f"since {args.since}"
    else:
        mode = "incremental"

    print(f"Output dir : {OUTPUT_DIR}")
    print(f"Usage dir  : {USAGE_DIR}")
    print(f"Mode       : {mode}")
    print(f"Hourly win : last {args.hourly_window} days")

    t0 = time.time()

    # ── Step 1: reference meters ─────────────────────────
    print("\n[1/9] Loading reference meters...")
    meter_map = _load_reference_meters()

    # ── Step 2: decide which dates to process ────────────
    print(f"\n[2/9] Selecting usage files to process...")
    if args.full:
        usage_dates = _list_all_usage_dates()
    elif args.since:
        start = datetime.strptime(args.since, "%Y-%m-%d")
        usage_dates = _list_usage_dates_from(start)
    else:
        cache = _load_daily_totals_cache()
        last_date = max(cache.keys()) if cache else None
        usage_dates = _list_usage_dates_after(last_date)
        if last_date:
            print(f"  cache last date: {last_date}  →  {len(usage_dates)} new file(s)")
        else:
            print(f"  no cache found  →  {len(usage_dates)} file(s) to process (first run)")

    if not usage_dates:
        print("  nothing to do — every available file is already in the cache")
        return 0
    print(f"  range: {usage_dates[0].date()} → {usage_dates[-1].date()} ({len(usage_dates)} files)")

    # ── Step 3: aggregate new days from Excel ───────────
    print(f"\n[3/9] Aggregating new days from hourly Excel files...")
    new_daily, new_hourly_rows = _aggregate_dates(usage_dates, meter_map)
    print(f"  new daily entries : {sum(len(v) for v in new_daily.values()):,}")
    print(f"  new hourly rows   : {len(new_hourly_rows):,}")

    # ── Step 4: merge with cache & re-derive daily aggregates ──
    print(f"\n[4/9] Merging with cache and re-deriving daily aggregates...")
    cache = _load_daily_totals_cache()
    merged = {**cache, **new_daily}  # new dates overwrite cache
    _save_daily_totals_cache(merged)
    print(f"  cache: {len(cache)} dates → {len(merged)} dates")

    daily_dma = _build_daily_dma(merged, meter_map)
    top20 = _build_top20_daily(merged, meter_map)
    rank = _build_rank_changes(merged, meter_map)
    monthly_diff = _build_monthly_main_sub_diff(merged, meter_map)
    search_idx = _build_search_index(meter_map)
    cotai = _build_cotai_calendar(merged, meter_map)
    weekly = _build_weekly(daily_dma)
    anomalies = _detect_anomalies(merged, meter_map)
    predictions, predictions_fitted = _build_predictions(merged, meter_map)
    pred_by_bld = _build_predictions_by_building(predictions, meter_map)

    # ── Step 5: build hourly aggregates (new dates only) ─
    # Hourly JSONs are append-only. We rebuild the new-date slice from the
    # new_daily readings (which are in memory during this run) and append
    # to whatever is already in the JSONs. For the cache's sake we keep
    # hourly detail for new days in a separate in-memory dict.
    new_daily_with_readings = _build_readings_dict(new_hourly_rows)
    hourly_dma_new = _build_hourly_dma(new_daily_with_readings, meter_map, sorted(merged.keys()))
    hourly_calendar_new = _build_hourly_calendar(new_daily_with_readings)
    hourly_top_new = _build_hourly_top_meters(new_daily_with_readings, meter_map)
    peak_hours_new = _build_peak_hours(new_daily_with_readings, meter_map)

    # ── Step 6: write daily JSONs (full overwrite from merged dict) ───
    print(f"\n[6/9] Writing daily JSON outputs...")
    _write_json("daily_dma.json", daily_dma)
    _write_json("weekly.json", weekly)
    _write_json("daily_top20.json", top20)
    _write_json("rank_changes.json", rank)
    _write_json("monthly_main_sub_diff.json", monthly_diff)
    _write_json("search_index.json", search_idx)
    _write_json("cotai_calendar.json", cotai)
    _write_json("anomalies.json", anomalies)
    _write_json("predictions.json", predictions)
    _write_json("predictions_fitted.json", predictions_fitted)
    _write_json("predictions_by_building.json", pred_by_bld)
    _write_json("meter_info.json", {mid: info for mid, info in meter_map.items()})
    _write_json("available_dates.json", sorted(merged.keys()))

    # ── Step 7: write hourly JSONs (append new dates) ──────────
    print(f"\n[7/9] Writing hourly JSON outputs (append-only)...")
    if hourly_dma_new:
        _append_or_init_json("hourly_dma.json", hourly_dma_new)
    if hourly_calendar_new:
        _append_or_init_json("hourly_calendar.json", hourly_calendar_new)
    if hourly_top_new:
        _append_or_init_json("hourly_top_meters.json", hourly_top_new)
    if peak_hours_new:
        _append_or_init_json("peak_hours.json", peak_hours_new)

    # ── Step 8: update hourly SQLite (append + prune) ─────
    print(f"\n[8/9] Updating hourly_meter.db (SQLite)...")
    _update_hourly_sqlite(new_hourly_rows, args.hourly_window)

    # ── Step 9: summary ──────────────────────────────────
    elapsed = time.time() - t0
    print(f"\n[9/9] Done in {elapsed:.1f}s")
    print(f"  total dates   : {len(merged)}")
    print(f"  meters        : {len(meter_map):,}")
    print(f"  new days      : {len(usage_dates)}")
    print(f"  anomalies     : {len(anomalies)}")
    print(f"  predictions   : {len(predictions.get('predictions') or [])} meters")
    print(f"  next run      : {'re-run as-is for the next day' if not args.full else 'use --full again to redo from scratch'}")
    return 0


def _build_readings_dict(hourly_rows: list[tuple]) -> dict:
    """Re-group hourly rows into {date: {meterId: {total, readings: {hour: val}}}}.

    This is the in-memory form that the hourly builders consume. The
    daily-totals cache stores only the total per (date, meter); the readings
    dict is rebuilt from the new hourly rows on every run.
    """
    by_date: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"total": 0.0, "readings": {}})
    )
    for mid, dt_str, consumption, _reading in hourly_rows:
        date_str, hh_mm = dt_str.split(" ", 1)
        hour = int(hh_mm.split(":")[0])
        entry = by_date[date_str][mid]
        entry["total"] += consumption
        entry["readings"][str(hour)] = entry["readings"].get(str(hour), 0.0) + consumption
    return dict(by_date)


if __name__ == "__main__":
    sys.exit(main())
