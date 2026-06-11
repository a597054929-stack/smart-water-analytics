"""End-to-end tests for the pipeline orchestrator.

Runs every stage of the pipeline on the live mock data and checks the
expected outputs.

Phase 5 (C5-1): rewritten for the 4-stage pipeline.
- STAGES = {ingest, validate, transform, publish} (was 7)
- No more latest_run.json (SQLite state IS the latest state)
- No more checkpoint resume (no per-stage JSON checkpoints)
- Per-run run_<id>.json is still written
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_ckpt(tmp_path):
    """A fresh checkpoint dir per test (kept for backward-compat signature;
    the 4-stage pipeline no longer writes checkpoints)."""
    ckpt = tmp_path / "checkpoints"
    ckpt.mkdir()
    return ckpt


def test_pipeline_runs_end_to_end(tmp_ckpt, tmp_path):
    """Force-run the full 4-stage pipeline. All stages should succeed."""
    from pipeline.orchestrator import run

    db = tmp_path / "test_analytics.db"
    summary = run(db_path=db, ckpt_dir=tmp_ckpt, force=True)

    assert summary["status"] == "ok"
    # Phase 4: 4 stages, not 7
    assert set(summary["stages"]) == {"ingest", "validate", "transform", "publish"}
    # Ingest returns a dict of DataFrames per artifact
    ingest = summary["stage_results"]["ingest"]
    assert "meter_daily" in ingest
    assert len(ingest["meter_daily"]) > 0


def test_pipeline_creates_sqlite(tmp_ckpt, tmp_path):
    """The ingest stage must create a SQLite database with expected tables."""
    from pipeline.orchestrator import run
    from pipeline.sql_loader import list_tables

    db = tmp_path / "test_analytics.db"
    run(db_path=db, ckpt_dir=tmp_ckpt, force=True)
    tables = {t["name"] for t in list_tables(db)}
    # The corrections table is created on-demand by stage_transform
    # (not by the legacy sql_loader.load_all v1 schema), so we don't
    # assert on it here.
    assert {"anomalies", "meters", "daily_dma", "meter_daily", "weekly"}.issubset(tables)


def test_pipeline_recreates_db_on_every_run(tmp_ckpt, tmp_path):
    """Re-running should re-create the DB (no checkpoint cache to skip ingest).

    This replaces the old test_pipeline_checkpoint_resume — the 4-stage
    pipeline does not cache; every run reads fresh from src and re-writes
    the DB. The previous test verified that deleting the DB after a
    checkpointed run did NOT re-run load_sql. That semantic is gone.
    """
    from pipeline.orchestrator import run

    db = tmp_path / "test_analytics.db"

    # First run
    s1 = run(db_path=db, ckpt_dir=tmp_ckpt, force=True)
    assert s1["status"] == "ok"
    assert db.exists()

    # Delete the DB; second run re-creates it
    db.unlink()
    s2 = run(db_path=db, ckpt_dir=tmp_ckpt, force=True)
    assert s2["status"] == "ok"
    assert db.exists()


def test_pipeline_run_summary_saved(tmp_ckpt, tmp_path):
    """The orchestrator must write a per-run summary (run_<id>.json) with timing."""
    from pipeline.orchestrator import run

    db = tmp_path / "test_analytics.db"
    summary = run(db_path=db, ckpt_dir=tmp_ckpt, force=True)

    # Phase 4 cutover: latest_run.json is gone. The per-run snapshot
    # (run_<id>.json) is still written; the run_id is in the returned summary.
    assert "elapsed_s" in summary
    assert "run_id" in summary
    assert summary["status"] == "ok"

    # Verify the snapshot file exists somewhere in reports/
    reports_dir = ROOT / "reports"
    run_snapshots = list(reports_dir.glob(f"run_{summary['run_id']}.json"))
    assert len(run_snapshots) == 1
    snap = json.loads(run_snapshots[0].read_text(encoding="utf-8"))
    assert snap["run_id"] == summary["run_id"]
    assert snap["status"] == "ok"
    # Per-stage metrics are in the snapshot
    assert "stage_results" in snap
    assert "publish" in snap["stage_results"]


def test_schema_validates_real_data():
    """Every registered schema should accept the real mock data."""
    import pandas as pd

    from pipeline.schema import SCHEMA_REGISTRY

    base = ROOT / "backend" / "data" / "output"
    samples = {
        "anomalies": pd.DataFrame(json.loads((base / "anomalies.json").read_text())),
        "weekly": pd.DataFrame(json.loads((base / "weekly.json").read_text())),
        "rank_changes": pd.DataFrame(json.loads((base / "rank_changes.json").read_text())),
        "search_index": pd.DataFrame(json.loads((base / "search_index.json").read_text())),
    }
    for name, df in samples.items():
        SCHEMA_REGISTRY[name].validate(df, lazy=True)
