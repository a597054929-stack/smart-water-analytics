"""One-shot migration: convert L → m³ across all data outputs.

Replaces the slow --full re-aggregation. Two passes:

1. Unit migration: every field that holds consumption (total, predicted,
   pastMean, etc.) gets /1000. Counts, percents, scores, indices, hours
   are passed through. Numeric lists whose parent key is a known
   consumption list (e.g. hourlyProfile) also get /1000.

2. Anomaly re-detection: re-run _detect_anomalies() with the new
   supplyMode == 'DIRECT' filter on the migrated cache.

The xlsx files are not re-read — we trust the prior incremental
aggregation was correct and just convert the output units.
"""

import json
import sqlite3
import sys
from pathlib import Path

OUTPUT_DIR = Path(r"C:\Users\Administrator\.openclaw\workspace\portfolio\backend\data\output_real")

# Field names whose VALUE is a single consumption number (L → /1000).
SCALAR_CONSUMPTION = {
    "total", "residential", "nonResidential",
    "predicted", "lower", "upper", "pMin", "pMax",
    "pastMean", "pastStd",
    "value",
    "mainTotal", "subsTotal", "diff",
    "avgHistorical", "totalHistorical",
    "peakValue", "offPeakAvg",
    "resWdAvg", "resWeAvg", "nonResWdAvg", "nonResWeAvg",
    "weekdayAvg", "weekendAvg", "grandTotal", "grand_total",
    "consumption", "reading",
}

# Field names whose VALUE is a LIST of consumption numbers (each /1000).
LIST_CONSUMPTION = {
    "hourlyProfile",
}


def _migrate(obj):
    if isinstance(obj, dict):
        return {k: _migrate_field(k, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_migrate_field(None, x) for x in obj]
    return obj


def _migrate_field(key, val):
    if isinstance(val, dict):
        return _migrate(val)
    if isinstance(val, list):
        if val and isinstance(val[0], (int, float)) and key in LIST_CONSUMPTION:
            return [round(x / 1000.0, 2) for x in val]
        return [_migrate_field(None, x) for x in val]
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        if key in SCALAR_CONSUMPTION:
            return round(val / 1000.0, 2)
        return val
    return val


def migrate_json(name: str) -> None:
    p = OUTPUT_DIR / name
    if not p.exists():
        print(f"  skip {name} (not found)")
        return
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    migrated = _migrate(data)
    with p.open("w", encoding="utf-8") as f:
        json.dump(migrated, f, ensure_ascii=False)
    size_mb = p.stat().st_size / 1024 / 1024
    print(f"  ✓ {name} ({size_mb:.2f} MB)")


def migrate_sqlite() -> None:
    p = OUTPUT_DIR / "hourly_meter.db"
    if not p.exists():
        print("  skip hourly_meter.db (not found)")
        return
    con = sqlite3.connect(str(p))
    cur = con.cursor()
    # Discover the hourly-detail table. Schema has been `hourly_meter`
    # historically; keep the lookup open in case it ever changes.
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    print(f"  tables: {tables}")
    for tbl in tables:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({tbl})").fetchall()]
        num_cols = [c for c in cols if c in SCALAR_CONSUMPTION]
        for c in num_cols:
            before = cur.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE {c} IS NOT NULL"
            ).fetchone()[0]
            cur.execute(
                f"UPDATE {tbl} SET {c} = ROUND({c} / 1000.0, 2) "
                f"WHERE {c} IS NOT NULL"
            )
            print(f"  ✓ {tbl}.{c}: {before:,} rows updated")
    con.commit()
    con.close()


def rebuild_daily_totals_cache() -> None:
    """Aggregate the (now-m³) hourly SQLite into the {date: {meterId:
    total}} cache shape. The cache was deleted before the migration
    attempt; re-deriving it from xlsx is the slow path we're avoiding.
    SQLite has 4.6M hourly rows covering 151 days × 9963 meters, so a
    GROUP BY over (date, meterId) is plenty fast (~10s).
    """
    db = OUTPUT_DIR / "hourly_meter.db"
    if not db.exists():
        return
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    rows = cur.execute(
        "SELECT substr(datetime, 1, 10) AS date, meterId, "
        "ROUND(SUM(consumption), 2) AS total "
        "FROM hourly_meter GROUP BY date, meterId"
    ).fetchall()
    con.close()
    cache: dict = {}
    for date, mid, total in rows:
        cache.setdefault(date, {})[mid] = total
    out = OUTPUT_DIR / "daily_totals.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print(f"  ✓ daily_totals.json rebuilt from SQLite: "
          f"{len(cache):,} dates, {sum(len(v) for v in cache.values()):,} entries "
          f"({out.stat().st_size/1024/1024:.2f} MB)")


def regenerate_anomalies() -> None:
    sys.path.insert(0, str(Path(r"C:\Users\Administrator\.openclaw\workspace\portfolio\scripts")))
    from real_data_converter import _detect_anomalies, _load_reference_meters

    cache_path = OUTPUT_DIR / "daily_totals.json"
    with cache_path.open("r", encoding="utf-8") as f:
        daily = json.load(f)
    meter_map = _load_reference_meters()

    anomalies = _detect_anomalies(daily, meter_map)
    out = OUTPUT_DIR / "anomalies.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(anomalies, f, ensure_ascii=False)
    print(f"  ✓ anomalies.json (DIRECT-only): {len(anomalies):,} entries "
          f"({out.stat().st_size/1024/1024:.2f} MB)")


if __name__ == "__main__":
    print(f"[1/4] Migrating unit (L → m³) across {OUTPUT_DIR}")
    targets = [
        "daily_dma.json",
        "daily_top20.json",
        "rank_changes.json",
        "monthly_main_sub_diff.json",
        "cotai_calendar.json",
        "weekly.json",
        "hourly_dma.json",
        "hourly_calendar.json",
        "hourly_top_meters.json",
        "peak_hours.json",
        "predictions.json",
        "predictions_fitted.json",
        "predictions_by_building.json",
        "anomalies.json",
    ]
    for t in targets:
        migrate_json(t)

    print("\n[2/4] Migrating hourly_meter.db (SQLite)")
    migrate_sqlite()

    print("\n[3/4] Rebuilding daily_totals.json cache from SQLite")
    rebuild_daily_totals_cache()

    print("\n[4/4] Re-running anomaly detection (DIRECT-only filter)")
    regenerate_anomalies()

    print("\nDone.")
