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


# Phase 5 (commit next): TestStageDataHealth (2 tests) removed.
# The functions it tested (orchestrator.stage_data_health,
# orchestrator.stage_clean, stage_detect_anomalies, etc.) were
# removed in the same commit — they were the 6 DEPRECATED 7-stage
# pipeline stages that got cut over to the new 4-stage pipeline
# in commit c27a4d4. The new stage_transform (which replaced
# stage_data_health's data_health role) is exercised by
# tests/test_pipeline.py.
