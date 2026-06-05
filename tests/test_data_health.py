"""Unit tests for the three pattern-detection functions in pipeline.data_quality.

These tests cover the functions that ``stage_data_health`` (in
``pipeline.orchestrator``) uses to flag data-quality issues that
the simpler IQR / z-score outlier rules miss:

  - ``detect_per_meter_outliers`` — a meter's value many σ from its own history
  - ``detect_daily_jumps`` — a meter's value jumps > 10× its own median |Δ|
  - ``detect_negative_pairs`` — a meter's daily total looks tiny vs its median

Each test builds a minimal DataFrame inline (same pattern as
``tests/test_data_quality.py``) and asserts on the function's output.
"""

import numpy as np
import pandas as pd

from pipeline import data_quality as dq


def _df(rows: list[tuple]) -> pd.DataFrame:
    """Build a (meterId, date, total) DataFrame from (mid, date_str, total) tuples."""
    if not rows:
        return pd.DataFrame({"meterId": [], "date": [], "total": []})
    return pd.DataFrame(
        [
            {"meterId": mid, "date": pd.to_datetime(d), "total": float(t)}
            for mid, d, t in rows
        ]
    )


class TestDetectPerMeterOutliers:
    def test_no_outliers_on_clean_data(self):
        # 30 days of stable consumption per meter — no spikes.
        rows = []
        for d in pd.date_range("2026-01-01", periods=30):
            rows.append(("m1", d, 100.0))
            rows.append(("m2", d, 50.0))
        df = _df(rows)
        out = dq.detect_per_meter_outliers(df, threshold_z=4.0, min_history=14)
        assert out == [], f"expected empty, got {out}"

    def test_detects_single_spike(self):
        # m1 has 29 days at 100 and 1 day at 10,000 — that 1 day is a z > 4 outlier.
        rows = []
        for d in pd.date_range("2026-01-01", periods=30):
            v = 10_000.0 if d == pd.Timestamp("2026-01-15") else 100.0
            rows.append(("m1", d, v))
        df = _df(rows)
        out = dq.detect_per_meter_outliers(df, threshold_z=4.0, min_history=14)
        assert len(out) == 1
        assert out[0]["meterId"] == "m1"
        assert out[0]["date"] == "2026-01-15"
        assert out[0]["type"] == "per_meter_outlier"
        assert out[0]["value"] == 10_000.0
        assert out[0]["score"] > 4.0

    def test_skips_meters_with_too_little_history(self):
        # Only 5 days of data — below min_history=14, so even a huge spike is skipped.
        rows = [("m1", d, 100.0) for d in pd.date_range("2026-01-01", periods=4)]
        rows.append(("m1", pd.Timestamp("2026-01-15"), 1_000_000.0))
        df = _df(rows)
        out = dq.detect_per_meter_outliers(df, threshold_z=4.0, min_history=14)
        assert out == []

    def test_output_shape(self):
        # Each entry has exactly the 5 documented fields.
        rows = []
        for d in pd.date_range("2026-01-01", periods=30):
            v = 5_000.0 if d == pd.Timestamp("2026-01-20") else 100.0
            rows.append(("m1", d, v))
        df = _df(rows)
        out = dq.detect_per_meter_outliers(df)
        assert len(out) >= 1
        e = out[0]
        assert set(e.keys()) == {"date", "meterId", "type", "value", "score"}


class TestDetectDailyJumps:
    def test_no_jumps_on_stable_data(self):
        # Small day-to-day variation, well below 10× median.
        np.random.seed(0)
        rows = [
            ("m1", d, 100.0 + np.random.normal(0, 1))
            for d in pd.date_range("2026-01-01", periods=30)
        ]
        df = _df(rows)
        out = dq.detect_daily_jumps(df, threshold_ratio=10.0, min_history=7)
        assert out == []

    def test_detects_clean_10x_spike(self):
        # The 712720 / 4月16日 pattern: meter hovers at 2,600, one day hits 26,000.
        rows = []
        for d in pd.date_range("2026-04-01", periods=20):
            v = 26_000.0 if d == pd.Timestamp("2026-04-16") else 2_600.0
            rows.append(("m1", d, v))
        df = _df(rows)
        out = dq.detect_daily_jumps(df, threshold_ratio=10.0, min_history=7)
        assert len(out) == 1
        assert out[0]["meterId"] == "m1"
        assert out[0]["date"] == "2026-04-16"
        assert out[0]["type"] == "daily_jump"
        assert out[0]["value"] == 26_000.0
        assert out[0]["score"] >= 10.0

    def test_detects_crash_to_zero(self):
        # A meter that drops from 2,000 to 0 is also a jump (the reverse direction).
        rows = []
        for d in pd.date_range("2026-04-01", periods=20):
            v = 0.0 if d == pd.Timestamp("2026-04-10") else 2_000.0
            rows.append(("m1", d, v))
        df = _df(rows)
        out = dq.detect_daily_jumps(df, threshold_ratio=10.0, min_history=7)
        assert len(out) >= 1
        assert out[0]["date"] == "2026-04-10"
        assert out[0]["value"] == 0.0

    def test_skips_short_history(self):
        # 5 days of data, one big jump — should be skipped (min_history=7).
        rows = [
            ("m1", pd.Timestamp("2026-01-01"), 100.0),
            ("m1", pd.Timestamp("2026-01-02"), 100.0),
            ("m1", pd.Timestamp("2026-01-03"), 100.0),
            ("m1", pd.Timestamp("2026-01-04"), 100.0),
            ("m1", pd.Timestamp("2026-01-05"), 100.0),
            ("m1", pd.Timestamp("2026-01-06"), 50_000.0),
        ]
        df = _df(rows)
        out = dq.detect_daily_jumps(df, threshold_ratio=10.0, min_history=7)
        assert out == []


class TestDetectNegativePairs:
    def test_no_pairs_on_normal_data(self):
        # All days for all meters are positive and in the normal range.
        rows = [
            ("m1", d, 100.0)
            for d in pd.date_range("2026-01-01", periods=10)
        ]
        df = _df(rows)
        out = dq.detect_negative_pairs(df, cancellation_threshold=0.1)
        assert out == []

    def test_detects_cancellation(self):
        # m1 normally does ~1,000/day, but one day reports 5.0 — looks like
        # positive and negative activity that netted out.
        rows = [("m1", d, 1_000.0) for d in pd.date_range("2026-01-01", periods=14)]
        rows.append(("m1", pd.Timestamp("2026-01-15"), 5.0))
        df = _df(rows)
        out = dq.detect_negative_pairs(df, cancellation_threshold=0.1)
        assert len(out) == 1
        assert out[0]["meterId"] == "m1"
        assert out[0]["date"] == "2026-01-15"
        assert out[0]["type"] == "negative_pair"
        assert out[0]["value"] == 5.0

    def test_output_shape(self):
        rows = [("m1", d, 1_000.0) for d in pd.date_range("2026-01-01", periods=14)]
        rows.append(("m1", pd.Timestamp("2026-01-15"), 1.0))
        df = _df(rows)
        out = dq.detect_negative_pairs(df)
        assert out, "should have detected the cancellation"
        e = out[0]
        assert set(e.keys()) == {"date", "meterId", "type", "value", "score"}


class TestStageDataHealth:
    """End-to-end smoke test: stage_data_health wired into the pipeline.

    Verifies the stage function uses the same three detectors and
    returns the expected summary + recent + all structure.
    """

    def test_stage_returns_expected_structure(self):
        from pipeline import orchestrator

        rows = [("m1", d, 100.0) for d in pd.date_range("2026-01-01", periods=20)]
        # One big spike for m1.
        rows.append(("m1", pd.Timestamp("2026-01-21"), 5_000.0))
        df = _df(rows)
        artifacts = {"meter_daily": df}

        class _Log:
            def __call__(self, *a, **kw): pass
            def warning(self, *a, **kw): pass
            def info(self, *a, **kw): pass
            def error(self, *a, **kw): pass

        out = orchestrator.stage_data_health(artifacts, _Log())
        # The stage splits output into summary / recent_* / *_all so the
        # JSON stays scannable. Each section must be present.
        assert "summary" in out
        assert "recent_per_meter_outliers" in out
        assert "recent_daily_jumps" in out
        assert "recent_negative_pairs" in out
        assert "per_meter_outliers_all" in out
        assert "daily_jumps_all" in out
        assert "negative_pairs_all" in out
        assert out["summary"]["daily_jumps"] >= 1
        # The spike should also surface as a per-meter outlier.
        assert out["summary"]["per_meter_outliers"] >= 1
        # Recent top-N is non-empty for the spike.
        assert len(out["recent_daily_jumps"]) >= 1
        assert out["recent_daily_jumps"][0]["meterId"] == "m1"

    def test_stage_handles_empty_input(self):
        from pipeline import orchestrator

        artifacts = {"meter_daily": pd.DataFrame(columns=["meterId", "date", "total"])}

        class _Log:
            def warning(self, *a, **kw): pass
            def info(self, *a, **kw): pass

        out = orchestrator.stage_data_health(artifacts, _Log())
        assert out["summary"]["per_meter_outliers"] == 0
        assert out["summary"]["daily_jumps"] == 0
        assert out["summary"]["negative_pairs"] == 0
        assert out["per_meter_outliers_all"] == []
        assert out["daily_jumps_all"] == []
