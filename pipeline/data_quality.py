"""Data quality module — outlier detection and missing-value handling.

Why this matters:
- Smart meter data is noisy. Stale meters report 0, faulty meters report
  huge spikes, comms outages produce gaps. Before we feed this to anomaly
  detection or forecasting, we have to clean it.
- In a real HKT-style production stack, this is the layer that decides:
  "is today's CDR ingestion trustworthy?" The same code runs against CDR
  files, network counters, or customer care tickets.

Methods chosen and why:
- IQR for outlier detection: distribution-free, robust to heavy tails.
  Better than z-score when the data is right-skewed (consumption is).
- Z-score as a fast alternative for ~normal data.
- Winsorization (capping) instead of dropping: dropping rows loses context
  and breaks continuity in time series.
- Forward fill then interpolation for missing: respects temporal order,
  assumes short gaps. Configurable strategy for longer gaps.
"""

from __future__ import annotations

from typing import Iterable, Literal

import numpy as np
import pandas as pd

try:
    from . import logger as plog
except ImportError:  # direct script execution
    import logger as plog  # type: ignore

MissingStrategy = Literal["drop", "ffill", "bfill", "mean", "median", "interpolate", "zero"]


# ── Outlier detection ────────────────────────────────────────

def detect_outliers_iqr(
    df: pd.DataFrame,
    col: str,
    k: float = 1.5,
) -> pd.Series:
    """Return a boolean mask: True where the value is an outlier by IQR rule.

    The IQR rule flags any point outside [Q1 - k*IQR, Q3 + k*IQR].
    k=1.5 is the standard "fence" (Tukey); k=3.0 is "extreme only".

    Accepts either a DataFrame (with `col`) or a Series.
    """
    s = _coerce_series(df, col)
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return pd.Series(False, index=s.index)
    lo = q1 - k * iqr
    hi = q3 + k * iqr
    return (s < lo) | (s > hi)


def detect_outliers_zscore(
    df: pd.DataFrame,
    col: str,
    threshold: float = 3.0,
) -> pd.Series:
    """Return a boolean mask: True where |z-score| > threshold.

    Accepts either a DataFrame (with `col`) or a Series.
    """
    s = _coerce_series(df, col)
    mu = s.mean()
    sigma = s.std(ddof=0)
    if sigma == 0 or pd.isna(sigma):
        return pd.Series(False, index=s.index)
    z = (s - mu) / sigma
    return z.abs() > threshold


def _coerce_series(df, col: str) -> pd.Series:
    """Pull a Series out of either a DataFrame (by col) or pass-through Series."""
    if isinstance(df, pd.Series):
        return df
    if col not in df.columns:
        raise KeyError(f"column {col!r} not in dataframe")
    return df[col]


def cap_values(
    df: pd.DataFrame,
    col: str,
    lower: float | None = None,
    upper: float | None = None,
) -> pd.DataFrame:
    """Winsorize a column in-place style: return a copy with values clamped."""
    if col not in df.columns:
        raise KeyError(f"column {col!r} not in dataframe")
    out = df.copy()
    if lower is not None:
        out[col] = out[col].clip(lower=lower)
    if upper is not None:
        out[col] = out[col].clip(upper=upper)
    return out


# ── Missing-value handling ───────────────────────────────────

def handle_missing(
    df: pd.DataFrame,
    cols: Iterable[str],
    strategy: MissingStrategy = "interpolate",
) -> pd.DataFrame:
    """Apply a missing-value strategy to the specified columns.

    Args:
        df: input DataFrame (assumed to be sorted by time/index if needed).
        cols: columns to clean.
        strategy:
            - drop: drop rows with any null in the listed columns
            - ffill: forward fill
            - bfill: backward fill
            - mean / median: fill with the column mean/median
            - interpolate: linear interpolation, with ffill/bfill for edges
            - zero: fill with 0 (use for counters that should be 0 if absent)
    """
    out = df.copy()
    cols = list(cols)

    if strategy == "drop":
        return out.dropna(subset=cols).reset_index(drop=True)
    if strategy == "zero":
        for c in cols:
            if c in out.columns:
                out[c] = out[c].fillna(0)
        return out
    if strategy in ("mean", "median"):
        fill = out[cols].mean() if strategy == "mean" else out[cols].median()
        for c in cols:
            if c in out.columns:
                out[c] = out[c].fillna(fill[c])
        return out
    if strategy in ("ffill", "bfill"):
        for c in cols:
            if c in out.columns:
                if strategy == "ffill":
                    out[c] = out[c].ffill()
                else:
                    out[c] = out[c].bfill()
        return out
    if strategy == "interpolate":
        for c in cols:
            if c in out.columns:
                out[c] = out[c].interpolate(method="linear", limit_direction="both")
        return out
    raise ValueError(f"unknown strategy: {strategy}")


# ── Quality report ───────────────────────────────────────────

def generate_quality_report(
    df: pd.DataFrame,
    cols: Iterable[str] | None = None,
) -> dict:
    """Summarize data quality for a DataFrame.

    Returns a dict suitable for serializing to JSON and shipping with the run.
    """
    cols = list(cols) if cols is not None else list(df.columns)
    report: dict = {
        "n_rows": int(len(df)),
        "n_cols": int(len(df.columns)),
        "columns": {},
    }
    for c in cols:
        if c not in df.columns:
            continue
        s = df[c]
        col_report = {
            "dtype": str(s.dtype),
            "n_null": int(s.isna().sum()),
            "pct_null": round(100.0 * s.isna().sum() / max(1, len(s)), 3),
            "n_unique": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s):
            col_report["type"] = "numeric"
            col_report.update(
                {
                    "min": float(s.min()) if not s.empty else None,
                    "max": float(s.max()) if not s.empty else None,
                    "mean": round(float(s.mean()), 4) if not s.empty else None,
                    "std": round(float(s.std(ddof=0)), 4) if not s.empty else None,
                }
            )
            non_null = s.dropna()
            if len(non_null) > 0:
                col_report["outliers_iqr"] = int(detect_outliers_iqr(s, c).sum())
                col_report["outliers_zscore"] = int(detect_outliers_zscore(s, c).sum())
        else:
            col_report["type"] = "categorical"
        report["columns"][c] = col_report
    return report


# ── Convenience: full clean ──────────────────────────────────

def clean_daily_readings(
    df: pd.DataFrame,
    value_col: str = "total",
    outlier_k: float = 3.0,
    neg_value_strategy: str = "zero",
) -> tuple[pd.DataFrame, dict]:
    """One-call cleaning for the most common case: daily meter readings.

    Steps:
        1. Coerce negatives to NaN (or zero, configurable).
        2. Cap obvious outliers via IQR rule with k=3 (extreme only).
        3. Interpolate short gaps.
        4. Drop rows that are still null after interpolation.

    Returns (cleaned_df, quality_report).
    """
    log = plog.get_logger("pipeline.clean")
    out = df.copy()

    n_before = len(out)
    if value_col in out.columns:
        if neg_value_strategy == "zero":
            out.loc[out[value_col] < 0, value_col] = 0
        else:
            out.loc[out[value_col] < 0, value_col] = pd.NA

        mask = detect_outliers_iqr(out, value_col, k=outlier_k)
        n_out = int(mask.sum())
        # Cap instead of drop: keeps the time series continuous.
        if n_out > 0:
            q1 = out[value_col].quantile(0.25)
            q3 = out[value_col].quantile(0.75)
            iqr = q3 - q1
            lo = max(0, q1 - outlier_k * iqr)
            hi = q3 + outlier_k * iqr
            out = cap_values(out, value_col, lower=lo, upper=hi)
            log.info(
                "outliers capped",
                extra={"stage": "clean", "metrics": {"n": n_out, "lo": lo, "hi": hi}},
            )

    out = handle_missing(out, [value_col] if value_col in out.columns else [], "interpolate")
    out = out.dropna(subset=[value_col]).reset_index(drop=True)

    report = generate_quality_report(out, [value_col])
    report["rows_in"] = n_before
    report["rows_out"] = int(len(out))
    return out, report


if __name__ == "__main__":
    # Quick self-test
    df = pd.DataFrame(
        {
            "meterId": ["m1"] * 10,
            "date": pd.date_range("2026-01-01", periods=10),
            "total": [10, 12, 11, None, 1000, 13, 11, 12, -1, 14],
        }
    )
    cleaned, rep = clean_daily_readings(df)
    print("cleaned total:", cleaned["total"].tolist())
    print("report:", rep)
