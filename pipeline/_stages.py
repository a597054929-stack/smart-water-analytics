"""Stage-level utilities extracted from orchestrator.

Phase 4 step 1 of ARCHITECTURE_OPTIMIZATION_PLAN: factor out reusable
bits so the new 4-stage pipeline can call them by name. No orchestrator
behavior change in this commit — the new module is just a holding pen.

Functions:
    load_meter_daily_sqlite(db_path) -> pd.DataFrame
    clean_meter_daily(df) -> (df, report)
    detect_anomalies_residual(predictions, actual) -> dict
    write_drift_to_sqlite(db_path, drift_report) -> int
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from pipeline import data_quality as dq
from pipeline import drift


def load_meter_daily_sqlite(db_path: Path) -> pd.DataFrame:
    """Read meter_daily from analytics_real.db as a DataFrame."""
    conn = sqlite3.connect(str(db_path))
    try:
        return pd.read_sql_query("SELECT * FROM meter_daily", conn)
    finally:
        conn.close()


def clean_meter_daily(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Apply IQR cap + interpolation to meter_daily. Returns (cleaned_df, report)."""
    return dq.clean_daily_readings(df, value_col="total")


def detect_anomalies_residual(predictions: pd.DataFrame,
                              actual: pd.DataFrame) -> dict:
    """Pair predictions vs actuals, report RMSE/MAE/bias.

    Skips if either frame is empty or no overlapping (meterId, date) rows.
    """
    if predictions is None or predictions.empty:
        return {"status": "skipped", "reason": "no predictions"}
    if actual is None or actual.empty:
        return {"status": "skipped", "reason": "no actual (meter_daily)"}
    joined = predictions[["meterId", "date", "predicted"]].merge(
        actual[["meterId", "date", "total"]],
        on=["meterId", "date"], how="inner",
    ).dropna(subset=["predicted", "total"])
    if len(joined) < 1:
        return {"status": "skipped", "n_compared": 0}
    resid = (joined["total"] - joined["predicted"]).astype(float)
    return {
        "status":    "ok",
        "n_compared": int(len(joined)),
        "rmse":      round(float((resid ** 2).mean() ** 0.5), 3),
        "mae":       round(float(resid.abs().mean()), 3),
        "bias":      round(float(resid.mean()), 3),
        "unit":      "m³",
    }


def write_drift_to_sqlite(db_path: Path, drift_report: dict) -> int:
    """Persist drift_report.by_column rows into the drift_reports table.

    Creates the table on first call. Returns number of rows written.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS drift_reports (
                ts TEXT, stage TEXT, column_name TEXT, status TEXT,
                metric REAL, baseline REAL, current REAL
            )
        """)
        rows = 0
        for col, payload in (drift_report.get("by_column") or {}).items():
            cur.execute(
                "INSERT INTO drift_reports VALUES (datetime('now'),?,?,?,?,?,?)",
                ("drift", col, payload.get("status"), payload.get("metric"),
                 payload.get("baseline"), payload.get("current")),
            )
            rows += 1
        conn.commit()
        return rows
    finally:
        conn.close()


__all__ = [
    "load_meter_daily_sqlite",
    "clean_meter_daily",
    "detect_anomalies_residual",
    "write_drift_to_sqlite",
]
