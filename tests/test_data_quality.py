"""Unit tests for pipeline/data_quality.py."""

import numpy as np
import pandas as pd
import pytest

from pipeline import data_quality as dq


class TestOutliers:
    def test_iqr_flags_extreme(self):
        s = pd.Series([1, 2, 3, 4, 5, 100], name="total")
        mask = dq.detect_outliers_iqr(s, "total")
        # 100 is far above Q3 + 1.5*IQR
        assert mask.tolist()[-1] is np.True_ or mask.tolist()[-1] is True

    def test_iqr_no_outliers_in_uniform(self):
        s = pd.Series([5, 5, 5, 5, 5], name="total")
        mask = dq.detect_outliers_iqr(s, "total")
        assert not mask.any()

    def test_zscore_flags_extreme(self):
        s = pd.Series([10, 11, 9, 10, 12, 100], name="total")
        mask = dq.detect_outliers_zscore(s, "total", threshold=2.0)
        assert mask.tolist()[-1] is np.True_ or mask.tolist()[-1] is True

    def test_zscore_no_outliers(self):
        s = pd.Series(np.random.normal(0, 1, 1000), name="total")
        mask = dq.detect_outliers_zscore(s, "total", threshold=3.0)
        # Expect <5% of 1000 to be flagged at z=3
        assert mask.sum() < 50

    def test_cap_values(self):
        df = pd.DataFrame({"total": [1, 5, 10, 100]})
        capped = dq.cap_values(df, "total", lower=2, upper=20)
        assert capped["total"].tolist() == [2, 5, 10, 20]

    def test_detect_outliers_missing_column(self):
        df = pd.DataFrame({"other": [1, 2, 3]})
        with pytest.raises(KeyError):
            dq.detect_outliers_iqr(df, "total")


class TestMissing:
    def test_interpolate(self):
        df = pd.DataFrame({"v": [1.0, None, 3.0, None, 5.0]})
        out = dq.handle_missing(df, ["v"], "interpolate")
        assert out["v"].isna().sum() == 0
        # Should recover 2 and 4 via linear interpolation
        assert out["v"].iloc[1] == 2.0
        assert out["v"].iloc[3] == 4.0

    def test_mean(self):
        df = pd.DataFrame({"v": [1.0, None, 3.0]})
        out = dq.handle_missing(df, ["v"], "mean")
        assert out["v"].isna().sum() == 0
        assert out["v"].iloc[1] == 2.0

    def test_zero(self):
        df = pd.DataFrame({"v": [1.0, None, 3.0]})
        out = dq.handle_missing(df, ["v"], "zero")
        assert out["v"].iloc[1] == 0

    def test_drop(self):
        df = pd.DataFrame({"v": [1.0, None, 3.0]})
        out = dq.handle_missing(df, ["v"], "drop")
        assert len(out) == 2

    def test_ffill(self):
        df = pd.DataFrame({"v": [1.0, None, 3.0, None]})
        out = dq.handle_missing(df, ["v"], "ffill")
        assert out["v"].iloc[1] == 1.0
        assert out["v"].iloc[3] == 3.0

    def test_unknown_strategy(self):
        df = pd.DataFrame({"v": [1.0, 2.0]})
        with pytest.raises(ValueError):
            dq.handle_missing(df, ["v"], "nonsense")  # type: ignore


class TestQualityReport:
    def test_generates_dict(self):
        df = pd.DataFrame({"v": [1, 2, 3, None, 5, 6, 7, 100]})
        rep = dq.generate_quality_report(df, ["v"])
        assert rep["n_rows"] == 8
        assert "v" in rep["columns"]
        assert rep["columns"]["v"]["n_null"] == 1
        assert rep["columns"]["v"]["outliers_iqr"] >= 1

    def test_categorical_summary(self):
        df = pd.DataFrame({"cat": ["a", "b", "a", "c", "a"]})
        rep = dq.generate_quality_report(df, ["cat"])
        assert rep["columns"]["cat"]["type"] == "categorical"
        assert rep["columns"]["cat"]["n_unique"] == 3


class TestCleanDailyReadings:
    def test_full_clean(self):
        df = pd.DataFrame(
            {
                "meterId": ["m1"] * 8,
                "date": pd.date_range("2026-01-01", periods=8),
                "total": [10, 12, 11, None, 1000, 13, -5, 14],
            }
        )
        cleaned, rep = dq.clean_daily_readings(df, outlier_k=1.5)
        assert cleaned["total"].isna().sum() == 0
        assert cleaned["total"].min() >= 0
        assert "rows_in" in rep and "rows_out" in rep

    def test_clean_empty(self):
        df = pd.DataFrame({"meterId": [], "date": [], "total": []})
        cleaned, rep = dq.clean_daily_readings(df)
        assert len(cleaned) == 0
