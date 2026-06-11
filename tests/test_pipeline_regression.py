"""
Pipeline regression tests.

These tests run the full pipeline on mock data and verify that key JSON
artifacts have the expected shape (columns, row counts within bounds,
required keys). If the pipeline behavior changes intentionally, update
the snapshots here; if they drift unexpectedly, these tests catch it.
"""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(ROOT, "backend", "data", "output")


@pytest.fixture(scope="module")
def pipeline_output():
    """Generate mock data and run the pipeline once for all tests."""
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "mock_data_generator.py")],
        capture_output=True, text=True, cwd=ROOT,
    )
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.orchestrator", "--force"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, f"Pipeline failed: {result.stderr}"

    artifacts = {}
    for name in [
        "all_data.json", "anomalies.json", "daily_dma.json",
        "predictions.json", "predictions_by_building.json",
        "rank_changes.json", "search_index.json", "weekly.json",
    ]:
        path = os.path.join(OUTPUT_DIR, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                artifacts[name] = json.load(f)
    return artifacts


class TestPipelineRegression:
    """Verify key artifacts after a full pipeline run."""

    def test_all_data_has_dates(self, pipeline_output):
        data = pipeline_output["all_data.json"]
        assert "dates" in data
        assert len(data["dates"]) >= 100

    def test_all_data_has_dma(self, pipeline_output):
        data = pipeline_output["all_data.json"]
        assert "dma" in data
        assert len(data["dma"]) >= 100
        # Each day should have DMA entries
        first_day = data["dma"][0]
        assert "dmas" in first_day
        assert "date" in first_day

    def test_anomalies_have_required_fields(self, pipeline_output):
        anomalies = pipeline_output["anomalies.json"]
        assert len(anomalies) > 0
        required = {"date", "meterId", "total", "dma", "type", "anomalyScore"}
        for a in anomalies[:5]:
            assert required.issubset(a.keys()), f"Missing fields in anomaly: {required - a.keys()}"

    def test_predictions_have_required_fields(self, pipeline_output):
        pred = pipeline_output["predictions.json"]
        assert "predictions" in pred
        assert len(pred["predictions"]) > 0
        first = pred["predictions"][0]
        assert "meterId" in first
        assert "predictions" in first
        assert len(first["predictions"]) == 7
        day = first["predictions"][0]
        assert "date" in day
        assert "value" in day

    def test_predictions_by_building(self, pipeline_output):
        pred = pipeline_output["predictions_by_building.json"]
        # Mock data wraps in dict; real data is bare list
        buildings = pred if isinstance(pred, list) else pred.get("predictions", [])
        assert len(buildings) > 0
        first = buildings[0]
        assert "building" in first or "buildingName" in first

    def test_rank_changes_have_fields(self, pipeline_output):
        ranks = pipeline_output["rank_changes.json"]
        assert len(ranks) > 0
        first = ranks[0]
        assert "meterId" in first
        assert "daysInTop20" in first
        assert "avgRank" in first

    def test_search_index_not_empty(self, pipeline_output):
        idx = pipeline_output["search_index.json"]
        assert len(idx) >= 100
        first = idx[0]
        assert "id" in first

    def test_weekly_has_grand_total(self, pipeline_output):
        weekly = pipeline_output["weekly.json"]
        assert len(weekly) > 0
        first = weekly[0]
        assert "grandTotal" in first
        assert "totalByDma" in first
        assert first["grandTotal"] > 0

    def test_daily_dma_row_count(self, pipeline_output):
        dma = pipeline_output["daily_dma.json"]
        assert len(dma) >= 100
        assert len(dma) <= 200
