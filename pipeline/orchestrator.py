"""Pipeline orchestrator.

Run the end-to-end data flow with:
- Stage-level structured logging
- Pandera schema validation at the boundary of every stage
- Checkpoint files so a failure can be resumed without re-doing work
- A final run summary (rows processed, validation status, timing)

Stages (in order):
    1. ingest         Read JSON outputs from `backend/data/output/`
    2. clean          Apply data-quality rules to `meter_daily`
    3. detect_anomalies  Re-score anomalies (no-op on existing data; demonstrates
                       the hook for a real detector)
    4. predict        (Re)run the building-level forecasting (mock for portfolio)
    5. load_sql       Build the analytics SQLite database
    6. drift          Compare current distributions to the saved baseline
    7. data_health    Pattern detection: per-meter z-score outliers, day-over-day
                     jumps, and cancellation pairs. Written to
                     `checkpoints/stage_data_health.json` and consumed by
                     `scripts/notebooks/02_health_check.ipynb`.

Why a stage-based runner?
- MLOps reality: every stage fails differently. Ingest can fail on a missing
  file. Clean can fail on a null in a critical column. SQL can fail on disk
  full. Each needs its own log line and recovery hook.
- Checkpointing is the "resume after crash" primitive. Without it, every
  partial run costs you an hour of re-computation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

try:
    from . import data_quality as dq
    from . import drift
    from . import logger as plog
    from . import sql_loader
    from . import validators as val
    from . import schema as pschema
except ImportError:
    import data_quality as dq  # type: ignore
    import drift  # type: ignore
    import logger as plog  # type: ignore
    import sql_loader  # type: ignore
    import validators as val  # type: ignore
    import schema as pschema  # type: ignore


# ── Paths ────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data"
OUTPUT_DIR = DATA_DIR / "output"
DB_PATH = DATA_DIR / "analytics.db"
CHECKPOINT_DIR = ROOT / "checkpoints"
REPORTS_DIR = ROOT / "reports"
LOGS_DIR = ROOT / "logs"


# ── Stage implementations ────────────────────────────────────

def stage_ingest(src: Path, log) -> dict[str, pd.DataFrame]:
    """Read every JSON file in the output directory into DataFrames."""
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
        slog.info(
            "ingest complete",
            extra={
                "stage": "ingest",
                "metrics": {
                    "n_artifacts": len(artifacts),
                    **{k: int(len(v)) for k, v in artifacts.items()},
                },
            },
        )
    return artifacts


def stage_clean(artifacts: dict[str, pd.DataFrame], log) -> dict[str, Any]:
    """Apply the data quality rules to meter_daily. Returns a quality report."""
    df = artifacts.get("meter_daily", pd.DataFrame())
    if df.empty:
        log.warning("clean: meter_daily is empty, skipping")
        return {"status": "skipped"}
    with plog.stage("clean") as slog:
        cleaned, report = dq.clean_daily_readings(df, value_col="total")
        artifacts["meter_daily"] = cleaned
        slog.info(
            "clean complete",
            extra={
                "stage": "clean",
                "metrics": {"rows_in": report.get("rows_in"), "rows_out": report.get("rows_out")},
            },
        )
    return report


def stage_detect_anomalies(artifacts: dict[str, pd.DataFrame], log) -> dict[str, Any]:
    """Hook for re-running the anomaly detector.

    The portfolio keeps the pre-computed `anomalies.json` from the upstream
    process. This stage validates the artifact and reports stats so the
    pipeline has a uniform shape.
    """
    df = artifacts.get("anomalies", pd.DataFrame())
    if df.empty:
        log.warning("detect_anomalies: no anomalies to process")
        return {"status": "empty"}
    with plog.stage("detect_anomalies") as slog:
        validated = val.validate_dataframe(df, "anomalies", "detect_anomalies")
        # Distribution stats
        by_type = validated["type"].value_counts().to_dict()
        by_dma = validated["dma"].value_counts().to_dict()
        slog.info(
            "detect_anomalies complete",
            extra={
                "stage": "detect_anomalies",
                "metrics": {
                    "n": int(len(validated)),
                    "by_type": {k: int(v) for k, v in by_type.items()},
                    "by_dma": {k: int(v) for k, v in by_dma.items()},
                },
            },
        )
        return {"n": int(len(validated)), "by_type": by_type, "by_dma": by_dma}


def stage_predict(artifacts: dict[str, pd.DataFrame], log) -> dict[str, Any]:
    """Hook for re-running the predictor.

    The portfolio keeps the pre-computed `predictions.json` /
    `predictions_by_building.json`. This stage validates them.
    """
    with plog.stage("predict") as slog:
        out: dict[str, Any] = {}
        for name, schema in [
            ("predictions", None),
            ("predictions_building", None),
        ]:
            df = artifacts.get(name, pd.DataFrame())
            if df.empty:
                out[name] = {"n": 0}
                continue
            # We don't have a fully Pandera-checked schema for the nested form,
            # so we only check row count here.
            n = int(len(df))
            if n < 1:
                raise val.ValidationError(f"predict: {name} has 0 rows")
            out[name] = {"n": n}
        slog.info(
            "predict complete",
            extra={"stage": "predict", "metrics": out},
        )
        return out


def stage_load_sql(artifacts: dict[str, pd.DataFrame], log, db_path: Path, src: Path) -> dict[str, int]:
    """Reload everything from JSON into SQLite (fresh DB).

    `src` is the JSON output directory; previously this stage hard-coded
    OUTPUT_DIR which silently loaded hourly_meter.db from the mock-data path
    when the user ran with --src pointing at real data. Now we honor --src.
    """
    with plog.stage("load_sql") as slog:
        loader = sql_loader.SqlLoader(db_path=db_path, drop=True)
        result = loader.load_all(src)
        loader.close()
        slog.info(
            "load_sql complete",
            extra={
                "stage": "load_sql",
                "metrics": {"db": str(db_path), "src": str(src), "tables": len(result), "rows": sum(result.values())},
            },
        )
    return result


def stage_drift(artifacts: dict[str, pd.DataFrame], log) -> dict[str, Any]:
    """Run the data-drift check on anomalies (small, illustrative)."""
    with plog.stage("drift") as slog:
        df = artifacts.get("anomalies", pd.DataFrame())
        if df.empty:
            slog.warning("drift: nothing to compare")
            return {"overall_status": "skipped"}
        out = drift.run_drift_check(
            df,
            columns=["total", "anomalyScore", "type", "dma"],
        )
        return out


def stage_data_health(artifacts: dict[str, pd.DataFrame], log) -> dict[str, Any]:
    """Pattern detection on the cleaned daily data.

    Runs three checks on ``artifacts["meter_daily"]`` (the
    ``[date, meterId, total]`` DataFrame that stage_ingest loads):

    - ``detect_per_meter_outliers`` — per-meter z-score > 4.0.
    - ``detect_daily_jumps`` — value at least 20× the meter's own
      median (catches the 712720 / 4月16日 pattern, which is 100-500×).
    - ``detect_negative_pairs`` — daily total < 1% of the meter's own
      median (catches cancellation-style errors).

    Output is split into:
      - ``summary``: counts per check (cheap to scan)
      - ``recent_*``: top-50 entries from the last 30 days, sorted by
        score descending (the part humans actually look at)
      - ``*_all``: full lists (for notebooks that want the whole picture)

    The result is stored in ``artifacts["data_health"]`` and
    checkpointed as ``checkpoints/stage_data_health.json``. The
    notebook ``02_health_check.ipynb`` consumes it.
    """
    with plog.stage("data_health") as slog:
        df = artifacts.get("meter_daily", pd.DataFrame())
        if df.empty:
            slog.warning("data_health: meter_daily is empty, skipping")
            out = {
                "summary": {"per_meter_outliers": 0, "daily_jumps": 0, "negative_pairs": 0},
                "recent_per_meter_outliers": [],
                "recent_daily_jumps": [],
                "recent_negative_pairs": [],
                "per_meter_outliers_all": [],
                "daily_jumps_all": [],
                "negative_pairs_all": [],
            }
            artifacts["data_health"] = out
            return out

        outliers = dq.detect_per_meter_outliers(df)
        jumps = dq.detect_daily_jumps(df)
        pairs = dq.detect_negative_pairs(df)

        # Find the cutoff: last 30 days of data. Use the maximum date in
        # the cleaned data so the "recent" window is meaningful even on
        # partial-date datasets.
        if "date" in df.columns and not df.empty:
            try:
                latest = pd.to_datetime(df["date"]).max()
                cutoff = (latest - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            except Exception:
                cutoff = "1970-01-01"
        else:
            cutoff = "1970-01-01"

        def _recent_top(entries: list[dict], top: int = 50) -> list[dict]:
            r = [e for e in entries if e["date"] >= cutoff]
            r.sort(key=lambda e: -e["score"])
            return r[:top]

        out = {
            "summary": {
                "per_meter_outliers": len(outliers),
                "daily_jumps": len(jumps),
                "negative_pairs": len(pairs),
                "recent_window_days": 30,
                "cutoff_date": cutoff,
            },
            "recent_per_meter_outliers": _recent_top(outliers),
            "recent_daily_jumps": _recent_top(jumps),
            "recent_negative_pairs": _recent_top(pairs),
            "per_meter_outliers_all": outliers,
            "daily_jumps_all": jumps,
            "negative_pairs_all": pairs,
        }
        artifacts["data_health"] = out
        slog.info(
            "data_health complete",
            extra={
                "stage": "data_health",
                "metrics": {
                    "summary": out["summary"],
                    "recent_counts": {
                        "per_meter_outliers": len(out["recent_per_meter_outliers"]),
                        "daily_jumps": len(out["recent_daily_jumps"]),
                        "negative_pairs": len(out["recent_negative_pairs"]),
                    },
                },
            },
        )
        return out


# ── Checkpointing ────────────────────────────────────────────

def _write_checkpoint(name: str, payload: dict, ckpt_dir: Path) -> None:
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    with (ckpt_dir / f"{name}.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def _read_checkpoint(name: str, ckpt_dir: Path) -> dict | None:
    p = ckpt_dir / f"{name}.json"
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _clear_checkpoints(ckpt_dir: Path) -> None:
    if ckpt_dir.exists():
        shutil.rmtree(ckpt_dir)


# ── Run ──────────────────────────────────────────────────────

STAGES: list[tuple[str, Callable]] = [
    ("ingest", stage_ingest),
    ("clean", stage_clean),
    ("detect_anomalies", stage_detect_anomalies),
    ("predict", stage_predict),
    ("load_sql", stage_load_sql),
    ("drift", stage_drift),
    ("data_health", stage_data_health),
]


def run(
    src: Path = OUTPUT_DIR,
    db_path: Path = DB_PATH,
    ckpt_dir: Path = CHECKPOINT_DIR,
    force: bool = False,
) -> dict[str, Any]:
    """Run the full pipeline with checkpointing.

    Args:
        src: directory containing the JSON outputs.
        db_path: path to the analytics SQLite database.
        ckpt_dir: where to write stage checkpoints.
        force: if True, ignore existing checkpoints and re-run every stage.
    """
    plog.new_run_id()
    if force:
        _clear_checkpoints(ckpt_dir)
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
                "ckpt_dir": str(ckpt_dir),
            },
        },
    )

    started = time.perf_counter()
    stage_results: dict[str, Any] = {}
    failed: list[str] = []

    # Stage 1 (ingest) — always runs first; produces the artifacts dict.
    if not force and (ckpt := _read_checkpoint("ingest", ckpt_dir)):
        log.info(
            "ingest: using checkpoint",
            extra={"stage": "orchestrator", "metrics": {"ckpt": "ingest"}},
        )
        # Re-load the artifacts from disk; we don't store full DataFrames.
        artifacts = stage_ingest(src, log)
    else:
        artifacts = stage_ingest(src, log)
        _write_checkpoint("ingest", {"rows": {k: int(len(v)) for k, v in artifacts.items()}}, ckpt_dir)

    # Stages 2..N: each receives `artifacts` and may mutate it.
    for name, fn in STAGES[1:]:
        ckpt_name = f"stage_{name}"
        if not force and (ckpt := _read_checkpoint(ckpt_name, ckpt_dir)):
            log.info(
                f"{name}: using checkpoint",
                extra={"stage": "orchestrator", "metrics": {"ckpt": ckpt_name}},
            )
            stage_results[name] = ckpt
            continue
        try:
            if name == "load_sql":
                out = fn(artifacts, log, db_path, src)
            else:
                out = fn(artifacts, log)
            stage_results[name] = out
            _write_checkpoint(ckpt_name, out, ckpt_dir)
        except Exception as e:
            failed.append(name)
            log.error(
                f"{name} failed: {e}",
                extra={"stage": "orchestrator", "metrics": {"failed": name}},
            )
            break

    elapsed = time.perf_counter() - started
    summary = {
        "run_id": plog.get_run_id(),
        "started_at": datetime.utcnow().isoformat() + "Z",
        "elapsed_s": round(elapsed, 3),
        "stages": list(stage_results.keys()),
        "failed": failed,
        "ingest": {k: int(len(v)) for k, v in artifacts.items()},
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

    # Write the run summary
    with (REPORTS_DIR / f"run_{plog.get_run_id()}.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    (REPORTS_DIR / "latest_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


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
    print("\ningest (rows):")
    _print_table(summary["ingest"], indent=1)
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
