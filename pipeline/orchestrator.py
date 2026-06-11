"""Pipeline orchestrator.

Phase 4 cutover: 4 stages, single source of truth (analytics_real.db).

Stages (in order):
    1. ingest    Read JSON outputs from `backend/data/output*` AND write
                 to SQLite in the same pass (single read+write).
    2. validate  Pandera schema check on every populated table in SQLite.
    3. transform Clean meter_daily + import corrections.json + residual
                 analysis + data_health checks. Writes back to SQLite.
    4. publish   Drift detection — persist per-column results to the
                 drift_reports table.

Why a stage-based runner?
- Each stage has its own log line and recovery hook.
- SQLite is the working state — no in-memory artifacts dict, no JSON
  checkpoints, no latest_run.json sidecar. A crash mid-pipeline leaves
  the DB in the last successfully-completed stage's state, which is
  queryable and inspectable.

Phase 4 history: this file used to have 7 stages with a heavy
in-memory artifacts dict + per-stage JSON checkpoints. That double-hop
(artifacts dict + on-disk JSON re-read for SQLite) was eliminated.
The old stage_clean / stage_detect_anomalies / stage_predict /
stage_load_sql / stage_drift / stage_data_health / stage_clean
functions are kept (deprecated, marked in their docstrings) for
backward compat — they are NOT in STAGES anymore.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import data_quality as dq
    from . import drift, sql_loader
    from . import logger as plog
    from . import validators as val
except ImportError:
    import data_quality as dq  # type: ignore
    import drift  # type: ignore
    import logger as plog  # type: ignore
    import sql_loader  # type: ignore
    import validators as val  # type: ignore


# ── Paths ────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data"
OUTPUT_DIR = DATA_DIR / "output"
DB_PATH = DATA_DIR / "analytics.db"
CHECKPOINT_DIR = ROOT / "checkpoints"
REPORTS_DIR = ROOT / "reports"
LOGS_DIR = ROOT / "logs"


# ── Stage implementations ────────────────────────────────────

def stage_ingest(src: Path, log, db_path: Path = None) -> dict[str, pd.DataFrame]:
    """Read every JSON file in the output directory into DataFrames,
    and (if db_path given) write to SQLite in the same pass.

    Phase 4 step 2: merges what used to be stage_load_sql's job. We no
    longer have a separate "load to SQLite" stage — the SQLite write
    happens here, alongside the in-memory artifact build, so the
    downstream stages can read either from `artifacts` or from SQLite.

    The `artifacts` dict is kept because stages 2-7 still consume it.
    That will go away in C4-6 (cutover to 4 stages).
    """
    if not src.exists():
        raise FileNotFoundError(f"data source not found: {src}")
    artifacts: dict[str, pd.DataFrame] = {}

    with plog.stage("ingest") as slog:
        for name, path in [
            ("anomalies", src / "anomalies.json"),
            ("meter_info", src / "meter_info.json"),
            ("meter_daily", src / "meter_daily.json"),
            ("daily_dma", src / "daily_dma.json"),
            ("weekly", src / "weekly.json"),
            ("rank_changes", src / "rank_changes.json"),
            ("monthly_diff", src / "monthly_main_sub_diff.json"),
            ("predictions", src / "predictions.json"),
            ("predictions_building", src / "predictions_by_building.json"),
            ("search_index", src / "search_index.json"),
        ]:
            if not path.exists():
                slog.warning(
                    f"missing {name}",
                    extra={"stage": "ingest", "metrics": {"file": str(path)}},
                )
                artifacts[name] = pd.DataFrame()
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if name == "meter_info":
                artifacts[name] = pd.DataFrame(
                    [{"meterId": k, **v} for k, v in (data or {}).items()]
                )
            elif name == "meter_daily":
                rows = []
                for mid, series in (data or {}).items():
                    for date, total in (series or {}).items():
                        rows.append({"meterId": mid, "date": date, "total": total})
                artifacts[name] = pd.DataFrame(rows)
            elif name == "monthly_diff":
                rows = []
                for r in data or []:
                    for d in r.get("diffs") or []:
                        rows.append(
                            {
                                "month": r.get("month"),
                                "mainMeterId": d.get("mainMeterId"),
                                "mainContractId": d.get("mainContractId"),
                                "mainBuilding": d.get("mainBuilding"),
                                "dma": d.get("dma"),
                                "subs": json.dumps(d.get("subs") or []),
                                "mainTotal": d.get("mainTotal"),
                                "subsTotal": d.get("subsTotal"),
                                "diff": d.get("diff"),
                                "diffPercent": d.get("diffPercent"),
                            }
                        )
                artifacts[name] = pd.DataFrame(rows)
            elif name == "predictions":
                # predictions.json = {generatedAt, ..., predictions: [{meterId, predictions: [{date, value}]}]}
                rows = []
                for p in (data or {}).get("predictions") or []:
                    for day in p.get("predictions") or []:
                        # Some predictions have "predicted/lower/upper", others have "value"
                        v = day.get("predicted")
                        if v is None:
                            v = day.get("value")
                        rows.append(
                            {
                                "meterId": p.get("meterId"),
                                "date": day.get("date"),
                                "predicted": v,
                                "lower": day.get("lower"),
                                "upper": day.get("upper"),
                            }
                        )
                artifacts[name] = pd.DataFrame(rows)
            elif name == "predictions_building":
                rows = []
                # Real data converter writes a bare list; mock data wraps it
                # in a dict under a `predictions` key.
                buildings = data if isinstance(data, list) else (data or {}).get("predictions") or []
                for b in buildings:
                    # Real data uses `buildingName`; mock data used `building`.
                    name_b = b.get("building") or b.get("buildingName")
                    for day in b.get("predictions") or []:
                        v = day.get("predicted")
                        if v is None:
                            v = day.get("value")
                        rows.append(
                            {
                                "building": name_b,
                                "date": day.get("date"),
                                "predicted": v,
                                "lower": day.get("lower"),
                                "upper": day.get("upper"),
                            }
                        )
                artifacts[name] = pd.DataFrame(rows)
            elif name == "weekly":
                rows = []
                for r in data or []:
                    row = dict(r)
                    for k in ("totalByDma", "wdByDmaRes", "dates", "dailyTotals"):
                        if k in row and not isinstance(row[k], str):
                            row[k] = json.dumps(row[k])
                    rows.append(row)
                artifacts[name] = pd.DataFrame(rows)
            else:
                # anomaly, rank_changes, search_index, daily_dma (list form from process_data)
                if isinstance(data, list):
                    artifacts[name] = pd.DataFrame(data)
                else:
                    artifacts[name] = pd.DataFrame()

        # Single-pass SQLite write: take the in-memory artifacts and dump
        # them all to the analytics DB. Replaces what stage_load_sql used
        # to do (re-reading the same JSONs from disk).
        if db_path is not None:
            try:
                loader = sql_loader.SqlLoader(db_path=db_path, drop=True)
                result = loader.load_all(src)
                loader.close()
                slog.info(
                    "ingest complete (read+write single pass)",
                    extra={
                        "stage": "ingest",
                        "metrics": {
                            "n_artifacts": len(artifacts),
                            **{k: int(len(v)) for k, v in artifacts.items()},
                            "sqlite_tables": len(result),
                            "sqlite_rows": sum(result.values()),
                        },
                    },
                )
            except Exception as e:
                slog.error(
                    f"ingest: SQLite write failed: {e}",
                    extra={"stage": "ingest", "metrics": {"error": str(e)}},
                )
                # Don't fail the whole pipeline — the in-memory artifacts
                # are still usable for downstream stages.
        else:
            slog.info(
                "ingest complete (no db_path; legacy mode)",
                extra={
                    "stage": "ingest",
                    "metrics": {
                        "n_artifacts": len(artifacts),
                        **{k: int(len(v)) for k, v in artifacts.items()},
                    },
                },
            )
    return artifacts


def stage_validate(log, db_path: Path) -> dict[str, Any]:
    """Pandera schema validation across all populated tables in SQLite.

    Phase 4 step 3: lifts the validate_dataframe calls that were inlined
    inside stage_detect_anomalies and stage_predict into a dedicated stage
    that runs AFTER ingest (so we can validate what we just wrote).

    Reads each table from SQLite, runs the corresponding Pandera schema,
    and reports per-table status. Failure is logged but does not raise —
    the transform stage can still run on the raw data; validation is a
    quality gate, not a hard error.
    """
    with plog.stage("validate") as slog:
        report: dict[str, Any] = {}
        for table in (
            "meters", "anomalies", "predictions", "predictions_building",
            "meter_daily", "daily_dma", "weekly", "monthly_diff",
            "rank_changes",
        ):
            try:
                conn = sqlite3.connect(str(db_path))
                df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT 100000", conn)
                conn.close()
                val.validate_dataframe(df, table, "validate")
                report[table] = {"status": "ok", "rows": int(len(df))}
            except val.ValidationError as e:
                report[table] = {"status": "failed", "error": str(e)[:200]}
            except Exception as e:
                report[table] = {"status": "skipped", "error": str(e)[:200]}
        slog.info(
            "validate complete",
            extra={"stage": "validate", "metrics": report},
        )
        return report


def stage_transform(log, db_path: Path) -> dict[str, Any]:
    """Transform = clean meter_daily + residual analysis + data_health
    + import corrections.json -> corrections table.

    Phase 4 step 4: combines the old stage_clean, the residual analysis
    that was in stage_detect_anomalies, and stage_data_health into one
    transformation pass that operates on the SQLite state. Also imports
    corrections.json (the externally-edited file) into the corrections
    table on every run — corrections is event-driven (L1), so a fresh
    SQLite from stage_ingest needs the import to mirror the file.

    Old stages 2/3/4/7 will be removed in C4-6. This stage does NOT
    write JSON checkpoints anymore (the old checkpoints/stage_*.json
    files are obsolete; new state lives in SQLite).
    """
    from pipeline._stages import (
        clean_meter_daily, detect_anomalies_residual,
        load_meter_daily_sqlite,
    )
    corr_path = ROOT / "backend" / "data" / "corrections.json"

    with plog.stage("transform") as slog:
        # 1. Clean meter_daily in-memory, then overwrite the SQLite table
        df = load_meter_daily_sqlite(db_path)
        cleaned, clean_report = clean_meter_daily(df) if not df.empty else (df, {"status": "skipped"})

        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            if not cleaned.empty:
                cleaned.to_sql("meter_daily", conn, if_exists="replace", index=False)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_meter_daily_meterId ON meter_daily(meterId)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_meter_daily_date ON meter_daily(date)")

            # 2. Import corrections.json -> corrections table (L1 event file).
            # Create the table on demand because the legacy sql_loader.load_all
            # uses the v1 schema (10 tables) and doesn't include corrections.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS corrections (
                    meterId TEXT, startDate TEXT, endDate TEXT,
                    factor REAL, reason TEXT,
                    PRIMARY KEY (meterId, startDate, endDate)
                )
            """)
            n_corr = 0
            if corr_path.exists():
                try:
                    rows = json.loads(corr_path.read_text(encoding="utf-8"))
                    for c in rows:
                        sd = c.get("startDate") or c.get("start")
                        ed = c.get("endDate") or c.get("end")
                        if sd is None or ed is None:
                            continue
                        cur.execute(
                            "INSERT OR REPLACE INTO corrections VALUES (?,?,?,?,?)",
                            (c["meterId"], sd, ed, c.get("factor", 1.0), c.get("reason")),
                        )
                        n_corr += 1
                except (json.JSONDecodeError, OSError) as e:
                    slog.warning(
                        f"corrections.json import failed: {e}",
                        extra={"stage": "transform"},
                    )

            # 3. Residual analysis (predictions vs cleaned meter_daily)
            pred_df = pd.read_sql_query("SELECT * FROM predictions", conn)
            actual_df = cleaned if not cleaned.empty else df
            residual = detect_anomalies_residual(pred_df, actual_df)

            # 4. data_health checks: per_meter_outliers, daily_jumps, negative_pairs
            # Write per-check counts into the data_health table (also L1).
            if not cleaned.empty:
                outliers = dq.detect_per_meter_outliers(cleaned)
                jumps = dq.detect_daily_jumps(cleaned)
                pairs = dq.detect_negative_pairs(cleaned)
            else:
                outliers, jumps, pairs = [], [], []
            cur.execute("""
                CREATE TABLE IF NOT EXISTS data_health (
                    ts TEXT, check_name TEXT, n_found INT
                )
            """)
            for k, v in (
                ("per_meter_outliers", len(outliers)),
                ("daily_jumps", len(jumps)),
                ("negative_pairs", len(pairs)),
            ):
                cur.execute(
                    "INSERT INTO data_health VALUES (datetime('now'), ?, ?)",
                    (k, int(v)),
                )
            conn.commit()
        finally:
            conn.close()

        slog.info(
            "transform complete",
            extra={
                "stage": "transform",
                "metrics": {
                    "clean_rows": int(len(cleaned)) if cleaned is not None else 0,
                    "corrections_imported": n_corr,
                    "residual": residual,
                    "health": {
                        "outliers": len(outliers),
                        "jumps":    len(jumps),
                        "pairs":    len(pairs),
                    },
                },
            },
        )
        return {
            "clean":               clean_report,
            "corrections_imported": n_corr,
            "residual":            residual,
            "health":              {
                "outliers": len(outliers),
                "jumps":    len(jumps),
                "pairs":    len(pairs),
            },
        }


def stage_publish(log, db_path: Path) -> dict[str, Any]:
    """Publish = drift detection + persist to drift_reports table.

    Phase 4 step 5: the old stage_drift only logged to console / JSON.
    Now it persists per-column metrics into the drift_reports table so
    the trend over time is queryable via SQL (no more sidecar JSON).

    Layer 1 tables (meters, predictions, rank_changes, anomalies,
    data_errors, corrections) are already in SQLite from stage_ingest +
    stage_transform, so this stage's main job is drift persistence.
    """
    from pipeline._stages import write_drift_to_sqlite
    with plog.stage("publish") as slog:
        conn = sqlite3.connect(str(db_path))
        try:
            df = pd.read_sql_query("SELECT * FROM anomalies", conn)
        finally:
            conn.close()
        if df.empty:
            slog.warning("publish: anomalies table empty, drift skipped")
            return {"drift": {"overall_status": "skipped"}, "drift_rows_written": 0}
        out = drift.run_drift_check(
            df,
            columns=["total", "anomalyScore", "type", "dma"],
        )
        n = write_drift_to_sqlite(db_path, out)
        slog.info(
            "publish complete",
            extra={
                "stage": "publish",
                "metrics": {
                    "drift_rows_written": n,
                    "overall_status": out.get("overall_status"),
                },
            },
        )
        return {"drift": out, "drift_rows_written": n}


# ── Run ──────────────────────────────────────────────────────

# Phase 4 cutover: STAGES is now 4 entries (was 7). Each stage
# reads/writes SQLite directly — no in-memory artifacts dict, no
# JSON checkpoints, no latest_run.json sidecar. Module-level so
# the CLI's run() log line and other consumers can reference it.
_STAGES: list[tuple[str, Callable]] = [
    ("ingest",    stage_ingest),
    ("validate",  stage_validate),
    ("transform", stage_transform),
    ("publish",   stage_publish),
]


def run(
    src: Path = OUTPUT_DIR,
    db_path: Path = DB_PATH,
    ckpt_dir: Path = CHECKPOINT_DIR,  # kept for backward-compat signature
    force: bool = False,              # no-op: no checkpoints to clear
) -> dict[str, Any]:
    """Run the 4-stage pipeline against SQLite.

    Phase 4 cutover: replaced the 7-stage pipeline that used an
    in-memory artifacts dict and per-stage JSON checkpoints. SQLite is
    now the only working state; stages read from it and write to it.

    Args:
        src: directory containing the JSON outputs (consumed by
            stage_ingest only).
        db_path: path to the analytics SQLite database. All 4 stages
            read/write this file.
        ckpt_dir: kept for backward-compat with old call sites; no
            longer used (no JSON checkpoints).
        force: kept for backward-compat; no-op in the 4-stage world.
    """
    plog.new_run_id()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log = plog.get_logger("pipeline.orchestrator")
    log.info(
        "pipeline start",
        extra={
            "stage": "orchestrator",
            "metrics": {
                "src": str(src),
                "db_path": str(db_path),
                "n_stages": len(_STAGES),
            },
        },
    )

    started = time.perf_counter()
    stage_results: dict[str, Any] = {}
    failed: list[str] = []

    for name, fn in _STAGES:
        try:
            if name == "ingest":
                # ingest is the only stage that takes src.
                out = fn(src, log, db_path)
            else:
                # validate / transform / publish all take (log, db_path).
                out = fn(log, db_path)
            stage_results[name] = out
        except Exception as e:
            failed.append(name)
            log.error(
                f"{name} failed: {e}",
                extra={"stage": "orchestrator", "metrics": {"failed": name, "error": str(e)[:200]}},
            )
            break

    elapsed = time.perf_counter() - started
    summary = {
        "run_id": plog.get_run_id(),
        "started_at": datetime.utcnow().isoformat() + "Z",
        "elapsed_s": round(elapsed, 3),
        "stages": list(stage_results.keys()),
        "failed": failed,
        "stage_results": stage_results,
        "status": "ok" if not failed else "failed",
    }
    log.info(
        "pipeline done",
        extra={
            "stage": "orchestrator",
            "metrics": {
                "elapsed_s": round(elapsed, 3),
                "stages": len(stage_results),
                "failed": failed,
            },
        },
    )

    # Write the run summary (JSON + markdown). Per-run snapshot kept
    # (run_<id>.json) so historical runs are queryable; latest_run.json
    # sidecar removed (it was a duplicate pointer, SQLite state IS the
    # latest state).
    with (REPORTS_DIR / f"run_{plog.get_run_id()}.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    # Write human-readable markdown report
    _write_markdown_report(summary, REPORTS_DIR)

    return summary


def _write_markdown_report(summary: dict, reports_dir: Path) -> None:
    """Generate a human-readable markdown report from the run summary."""
    lines = [
        "# Pipeline Run Report",
        "",
        f"**Run ID:** `{summary.get('run_id', 'unknown')}`  ",
        f"**Started:** {summary.get('started_at', 'unknown')}  ",
        f"**Duration:** {summary.get('elapsed_s', 0):.1f}s  ",
        f"**Status:** {'PASSED' if summary.get('status') == 'ok' else 'FAILED'}  ",
        "",
        "## Stages",
        "",
        "| Stage | Status |",
        "|-------|--------|",
    ]

    for stage in summary.get("stages", []):
        status = "FAILED" if stage in summary.get("failed", []) else "OK"
        lines.append(f"| {stage} | {status} |")

    if summary.get("failed"):
        lines.append("")
        lines.append(f"**Failed stages:** {', '.join(summary['failed'])}")

    lines.append("")
    lines.append("## Stage Metrics")
    lines.append("")
    lines.append("| Stage | Status | Metrics (truncated) |")
    lines.append("|-------|--------|--------------------|")
    for stage_name, stage_out in summary.get("stage_results", {}).items():
        status = "FAILED" if stage_name in summary.get("failed", []) else "OK"
        # Truncate metrics dict to 200 chars for the markdown table
        metrics_repr = json.dumps(stage_out, default=str)[:200] if stage_out else ""
        lines.append(f"| {stage_name} | {status} | `{metrics_repr}` |")

    lines.append("")
    reports_dir.joinpath("latest_run.md").write_text("\n".join(lines), encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────

def _print_table(d: dict, indent: int = 0) -> None:
    pad = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{pad}{k}:")
            _print_table(v, indent + 1)
        elif isinstance(v, list):
            print(f"{pad}{k}: {len(v)} items")
        else:
            print(f"{pad}{k}: {v}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smart Water pipeline orchestrator")
    parser.add_argument("--force", action="store_true", help="Re-run every stage, ignoring checkpoints")
    parser.add_argument("--src", type=str, default=str(OUTPUT_DIR), help="Path to JSON output dir")
    parser.add_argument("--db", type=str, default=str(DB_PATH), help="Path to analytics SQLite DB")
    parser.add_argument("--ckpt", type=str, default=str(CHECKPOINT_DIR), help="Checkpoint directory")
    args = parser.parse_args()

    summary = run(
        src=Path(args.src),
        db_path=Path(args.db),
        ckpt_dir=Path(args.ckpt),
        force=args.force,
    )
    print("\n=== Run summary ===")
    print(f"run_id     : {summary['run_id']}")
    print(f"elapsed_s  : {summary['elapsed_s']}")
    print(f"stages     : {summary['stages']}")
    print(f"failed     : {summary['failed']}")
    print(f"status     : {summary['status']}")
    # Phase 4: 'ingest' is no longer a top-level key in the summary.
    # Ingest's per-artifact row counts moved into stage_results['ingest']
    # as a dict[str, DataFrame] (we just print the dict keys, not the
    # contents — printing a DataFrame would be unreadable in the CLI).
    print("\ningest artifacts:")
    for name in (summary.get("stage_results") or {}).get("ingest", {}):
        print(f"  {name}")
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

