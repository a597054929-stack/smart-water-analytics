"""Data drift detection.

Why this matters for HKT:
- HKT customer behavior shifts seasonally (summer travel) and during
  promotional campaigns. A model trained on January will be wrong by April.
- "Data drift" is the production name for this. We catch it statistically,
  not by waiting for the business to complain.
- Telecom-specific signals: call volume, ARPU, churn — all drift.
  Same code, different column.

Method:
- Numeric columns: two-sample Kolmogorov-Smirnov test.
  Non-parametric, works on any distribution, gives a single p-value.
- Categorical columns: chi-square test of independence.
  We bucket both runs into the same categories, count, and compare.
- Flag any column with p < 0.05 as "drift suspected". A small p means the
  two distributions are unlikely to have been drawn from the same process.

Output:
- reports/drift_report.json: per-column verdict + summary metrics.
- A baseline JSON (saved on first run) for next time.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

try:
    from . import logger as plog
except ImportError:
    import logger as plog  # type: ignore


REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
BASELINE_DIR = REPORTS_DIR / "baselines"
DEFAULT_BASELINE_PATH = BASELINE_DIR / "drift_baseline.json"
DEFAULT_REPORT_PATH = REPORTS_DIR / "drift_report.json"

DRIFT_P_THRESHOLD = 0.05


def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series)


def _ks_test_numeric(baseline: pd.Series, current: pd.Series) -> dict[str, float]:
    """Two-sample KS test. Returns {statistic, p_value}."""
    b = baseline.dropna().to_numpy()
    c = current.dropna().to_numpy()
    if len(b) < 5 or len(c) < 5:
        return {"statistic": float("nan"), "p_value": float("nan"), "n_baseline": int(len(b)), "n_current": int(len(c))}
    res = stats.ks_2samp(b, c)
    return {
        "statistic": float(res.statistic),
        "p_value": float(res.pvalue),
        "n_baseline": int(len(b)),
        "n_current": int(len(c)),
    }


def _chi_square_categorical(baseline: pd.Series, current: pd.Series) -> dict[str, Any]:
    """Chi-square test of independence for two categorical distributions."""
    b_counts = baseline.value_counts(dropna=False)
    c_counts = current.value_counts(dropna=False)
    cats = sorted(set(b_counts.index) | set(c_counts.index), key=str)
    b = np.array([int(b_counts.get(cat, 0)) for cat in cats], dtype=float)
    c = np.array([int(c_counts.get(cat, 0)) for cat in cats], dtype=float)
    if b.sum() == 0 or c.sum() == 0:
        return {"statistic": float("nan"), "p_value": float("nan"), "categories": len(cats)}
    # scipy expects the contingency table.
    contingency = np.vstack([b, c])
    try:
        res = stats.chi2_contingency(contingency)
        return {
            "statistic": float(res.statistic),
            "p_value": float(res.pvalue),
            "categories": len(cats),
        }
    except ValueError as e:
        return {"statistic": float("nan"), "p_value": float("nan"), "error": str(e)}


def _summarize_series(series: pd.Series) -> dict[str, Any]:
    """Compact summary used both for the baseline and the report."""
    s = series.dropna()
    if _is_numeric(series):
        return {
            "type": "numeric",
            "n": int(len(s)),
            "min": float(s.min()) if len(s) else None,
            "max": float(s.max()) if len(s) else None,
            "mean": float(s.mean()) if len(s) else None,
            "std": float(s.std(ddof=0)) if len(s) else None,
        }
    counts = s.value_counts().head(20)
    return {
        "type": "categorical",
        "n": int(len(s)),
        "n_unique": int(s.nunique()),
        "top": {str(k): int(v) for k, v in counts.items()},
    }


def compare_to_baseline(
    current: pd.DataFrame,
    baseline: dict[str, dict],
    columns: list[str] | None = None,
    threshold: float = DRIFT_P_THRESHOLD,
) -> dict[str, Any]:
    """Compare a current DataFrame to a previously-saved baseline.

    Args:
        current: current run's DataFrame.
        baseline: the dict loaded from disk (one entry per column).
        columns: subset of columns to check; default = intersection with baseline.
        threshold: p-value below which we flag drift.

    Returns:
        A dict with `per_column` results, `drift_count`, `flagged_columns`,
        and `overall_status` ("drift_detected" or "ok").
    """
    cols = columns or [c for c in baseline.keys() if c in current.columns]
    per_column: dict[str, dict] = {}
    flagged: list[str] = []

    for col in cols:
        if col not in baseline:
            continue
        if col not in current.columns:
            per_column[col] = {"status": "missing_in_current"}
            continue
        kind = baseline[col].get("type", "categorical")
        if kind == "numeric":
            test = _ks_test_numeric(
                pd.Series(baseline[col].get("_values", [])),
                current[col],
            )
        else:
            # Rebuild the baseline value distribution from the saved `top` counts.
            b = pd.Series(
                [
                    k
                    for k, v in (baseline[col].get("top") or {}).items()
                    for _ in range(int(v))
                ]
            )
            test = _chi_square_categorical(b, current[col])
        p = test.get("p_value", float("nan"))
        drift = (p == p) and p < threshold  # NaN-safe
        if drift:
            flagged.append(col)
        per_column[col] = {
            "type": kind,
            "test": "ks_2samp" if kind == "numeric" else "chi2",
            "p_value": p,
            "statistic": test.get("statistic"),
            "drift": drift,
            "n_baseline": test.get("n_baseline"),
            "n_current": test.get("n_current"),
        }

    return {
        "per_column": per_column,
        "drift_count": len(flagged),
        "flagged_columns": flagged,
        "overall_status": "drift_detected" if flagged else "ok",
        "threshold": threshold,
    }


def make_baseline(df: pd.DataFrame, columns: list[str] | None = None) -> dict[str, dict]:
    """Create a baseline dict from a DataFrame.

    For numeric columns we store the full raw values (small enough for our use).
    For categorical columns we store the value counts.
    """
    cols = columns or list(df.columns)
    baseline: dict[str, dict] = {}
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col]
        summary = _summarize_series(s)
        if summary["type"] == "numeric":
            summary["_values"] = s.dropna().tolist()[:10000]
        baseline[col] = summary
    return baseline


def run_drift_check(
    current: pd.DataFrame,
    columns: list[str] | None = None,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    """Top-level entry point.

    If no baseline exists yet, save the current run as the baseline and return
    `{"overall_status": "baseline_saved"}`. Otherwise compare and write the
    report.
    """
    log = plog.get_logger("pipeline.drift")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = Path(baseline_path)
    report_path = Path(report_path)

    if not baseline_path.exists():
        baseline = make_baseline(current, columns=columns)
        baseline["_meta"] = {
            "created_at": datetime.utcnow().isoformat() + "Z",
            "n_rows": int(len(current)),
        }
        with baseline_path.open("w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2, default=str)
        log.info(
            "baseline saved",
            extra={
                "stage": "drift",
                "metrics": {"path": str(baseline_path), "n_cols": len(baseline) - 1},
            },
        )
        return {"overall_status": "baseline_saved", "path": str(baseline_path)}

    with baseline_path.open("r", encoding="utf-8") as f:
        baseline = json.load(f)
    baseline.pop("_meta", None)

    result = compare_to_baseline(current, baseline, columns=columns)
    result["generated_at"] = datetime.utcnow().isoformat() + "Z"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log.info(
        "drift check complete",
        extra={
            "stage": "drift",
            "metrics": {
                "drift_count": result["drift_count"],
                "flagged": result["flagged_columns"][:10],
                "status": result["overall_status"],
            },
        },
    )
    return result


__all__ = [
    "run_drift_check",
    "make_baseline",
    "compare_to_baseline",
    "DRIFT_P_THRESHOLD",
]


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "reports/drift_report.json"
    # Quick self-test: load anomalies and pretend the "type" column is the focus.
    import json
    data = json.load(open("backend/data/output/anomalies.json"))
    df = pd.DataFrame(data)
    cols = ["total", "anomalyScore", "type", "dma"]
    out = run_drift_check(df, columns=cols)
    print(json.dumps(out, indent=2, default=str)[:1500])
