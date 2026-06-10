"""Migrate backend/data/output_real/*.json -> analytics_real.db (v2 schema).

Phase 1 PoC: verifies that the new 4-layer schema can absorb all
existing JSON data without loss. Run this once to produce a fresh
analytics_real.db from the existing JSON exports.

Usage:
    python scripts/migrate_to_sqlite_v2.py [--src backend/data/output_real] [--db analytics_real.db]

Does NOT delete the source JSONs. Use --backup to copy them aside
first (recommended for the first run).

Note on hourly_meter: this converter writes 11 of 12 v2 tables.
hourly_meter (~15M rows, 2.7GB) is intentionally NOT migrated here:
  1. it's a separate SQLite file the converter produces natively
  2. the v2 design uses ATTACH to consolidate at query time
  3. copying 15M rows through Python would 5x the migration time
Phase 4 (orchestrator) will ATTACH hourly_meter.db into analytics_real.db.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "backend" / "data" / "output_real"
DEFAULT_DB = ROOT / "backend" / "data" / "analytics_real.db"


def _read_json(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _exec_schema(conn, schema_path: Path) -> None:
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())


def _bulk_insert(conn, sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    cur = conn.cursor()
    cur.executemany(sql, rows)
    conn.commit()
    return cur.rowcount


def migrate_meters(conn, src: Path) -> int:
    raw = _read_json(src / "meter_info.json")
    if raw is None: return 0
    rows = [
        (mid, info.get("id"), info.get("contractId"), info.get("propertyType"),
         int(bool(info.get("isResidential"))), info.get("buildingName"),
         info.get("dma"), info.get("supplyMode"), info.get("mainCode"))
        for mid, info in raw.items()
    ]
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO meters VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def migrate_predictions(conn, src: Path) -> int:
    raw = _read_json(src / "predictions.json")
    if raw is None: return 0
    pred = raw.get("predictions", [])
    rows = []
    for p in pred:
        for day in p.get("predictions", []):
            v = day.get("predicted") or day.get("value")
            rows.append((p["meterId"], day["date"], v, day.get("lower"), day.get("upper")))
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?)",
        rows,
    )


def migrate_predictions_building(conn, src: Path) -> int:
    raw = _read_json(src / "predictions_by_building.json")
    if raw is None: return 0
    rows = []
    for b in raw:
        # Real data uses "buildingName"; mock data used "building"
        bname = b.get("building") or b.get("buildingName")
        for day in b.get("predictions", []):
            v = day.get("predicted") or day.get("value")
            rows.append((bname, day["date"], v, day.get("lower"), day.get("upper")))
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO predictions_building VALUES (?,?,?,?,?)",
        rows,
    )


def migrate_rank_changes(conn, src: Path) -> int:
    raw = _read_json(src / "rank_changes.json")
    if raw is None: return 0
    rows = [
        (r["meterId"], r.get("contractId"), r.get("buildingName"),
         r.get("dma"), r.get("propertyType"),
         r.get("daysInTop20"), r.get("avgTotal"), r.get("avgRank"),
         r.get("trend"))
        for r in raw
    ]
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO rank_changes VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def migrate_anomalies(conn, src: Path) -> int:
    raw = _read_json(src / "anomalies.json")
    if raw is None: return 0
    rows = [
        (a["date"], a["meterId"], a.get("total"), a.get("contractId"),
         a.get("dma"), a.get("buildingName"), a.get("reason"),
         a.get("type"), a.get("anomalyScore"),
         a.get("pastMean"), a.get("pastStd"), a.get("windowDays"),
         a.get("originalType"))
        for a in raw
    ]
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO anomalies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def migrate_daily_dma(conn, src: Path) -> int:
    raw = _read_json(src / "daily_dma.json")
    if raw is None: return 0
    rows = []
    for day in raw:
        for dma, vals in (day.get("dmas") or {}).items():
            rows.append((
                day["date"], dma, vals.get("total", 0),
                vals.get("residential", 0), vals.get("nonResidential", 0),
                vals.get("resCount", 0), vals.get("nonResCount", 0),
                vals.get("meterCount", 0), vals.get("rain"),
            ))
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO daily_dma VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )


def migrate_meter_daily(conn, src: Path) -> int:
    """L2: water-table-level daily aggregates from daily_totals.json.

    daily_totals.json shape: {date: {meterId: total}}
    Output: 626K rows (4150 meters * 151 days) into meter_daily.
    """
    raw = _read_json(src / "daily_totals.json")
    if raw is None: return 0
    rows = []
    for date, meters in raw.items():
        for mid, total in meters.items():
            rows.append((mid, date, total))
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO meter_daily VALUES (?,?,?)",
        rows,
    )


def migrate_weekly(conn, src: Path) -> int:
    raw = _read_json(src / "weekly.json")
    if raw is None: return 0
    rows = []
    for w in raw:
        rows.append((
            w["weekStart"], w.get("weekEnd"), w.get("label"),
            json.dumps(w.get("dates", [])),
            json.dumps(w.get("totalByDma", {})),
            w.get("grandTotal", 0), w.get("weekdayAvg", 0),
            w.get("weekendAvg", 0),
            json.dumps(w.get("wdByDmaRes", {})),
            w.get("rain", 0),
            json.dumps(w.get("dailyTotals", [])),
        ))
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO weekly VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def migrate_monthly_diff(conn, src: Path) -> int:
    raw = _read_json(src / "monthly_main_sub_diff.json")
    if raw is None: return 0
    rows = []
    for m in raw:
        for d in m.get("diffs", []):
            # Fix: dma lives on the inner diff, not the month-level wrapper.
            # Matches pipeline.sql_loader._flatten_main_sub_diff behavior.
            rows.append((
                m["month"], d.get("mainMeterId"), d.get("mainContractId"),
                d.get("mainBuilding"), d.get("dma"),
                json.dumps(d.get("subs", [])),
                d.get("mainTotal", 0), d.get("subsTotal", 0),
                d.get("diff", 0), d.get("diffPercent", 0),
            ))
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO monthly_diff VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def migrate_data_errors(conn, src: Path) -> int:
    raw = _read_json(src / "data_errors.json")
    if raw is None: return 0
    rows = [(e.get("ts"), e.get("meterId"), e.get("date"),
             e.get("reason"), e.get("rawValue")) for e in raw]
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO data_errors VALUES (?,?,?,?,?)",
        rows,
    )


def migrate_corrections(conn, src: Path) -> int:
    raw = _read_json(src.parent / "corrections.json")
    if raw is None: return 0
    rows = []
    for c in raw:
        # Schema columns are startDate/endDate, but real-data JSON uses start/end.
        # Accept both for forward-compat with any future writer.
        sd = c.get("startDate") or c.get("start")
        ed = c.get("endDate") or c.get("end")
        if sd is None or ed is None:
            continue
        rows.append((c["meterId"], sd, ed,
                     c.get("factor", 1.0), c.get("reason")))
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO corrections VALUES (?,?,?,?,?)",
        rows,
    )


def migrate_search_index(conn, src: Path) -> int:
    raw = _read_json(src / "search_index.json")
    if raw is None: return 0
    rows = [(s["id"], s.get("contract"), s.get("building"),
             s.get("dma"), s.get("type")) for s in raw]
    return _bulk_insert(
        conn,
        "INSERT OR REPLACE INTO search_index VALUES (?,?,?,?,?)",
        rows,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--schema", type=Path,
                    default=ROOT / "pipeline" / "schema_v2.sql")
    ap.add_argument("--backup", action="store_true",
                    help="Copy source JSONs to a timestamped backup dir first")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    if not args.src.exists():
        print(f"ERROR: source dir not found: {args.src}")
        sys.exit(1)
    if not args.schema.exists():
        print(f"ERROR: schema not found: {args.schema}")
        sys.exit(1)

    if args.backup:
        import shutil
        import datetime
        backup_dir = args.src.parent / f"output_real_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}"
        shutil.copytree(args.src, backup_dir)
        print(f"Backed up {args.src} -> {backup_dir}")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.db.exists():
        args.db.unlink()
        print(f"Removed existing {args.db}")

    conn = sqlite3.connect(str(args.db))
    print(f"Created {args.db}")
    _exec_schema(conn, args.schema)
    print(f"Applied schema {args.schema}")

    print("\nMigrating...")
    steps = [
        ("meters",            migrate_meters),
        ("predictions",        migrate_predictions),
        ("predictions_building", migrate_predictions_building),
        ("rank_changes",       migrate_rank_changes),
        ("anomalies",          migrate_anomalies),
        ("data_errors",        migrate_data_errors),
        ("corrections",        migrate_corrections),
        ("search_index",       migrate_search_index),
        ("daily_dma",          migrate_daily_dma),
        ("meter_daily",        migrate_meter_daily),
        ("weekly",             migrate_weekly),
        ("monthly_diff",       migrate_monthly_diff),
    ]
    total = 0
    for name, fn in steps:
        n = fn(conn, args.src)
        print(f"  {name:<22} {n:>8,} rows")
        total += n
    conn.close()
    print(f"\nTotal: {total:,} rows migrated -> {args.db}")


if __name__ == "__main__":
    main()
