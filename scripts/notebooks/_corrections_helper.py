"""Helper functions for the data-correction notebook workflow.

This module is the engine behind ``scripts/notebooks/01_data_correction.ipynb``
and ``02_health_check.ipynb``. It:

- Loads the converter's internal cache (``daily_totals.json``) as a tidy
  ``(date, meterId, total)`` DataFrame so notebooks can use pandas/numpy.
- Provides three "find anomalies" queries that match the patterns that
  actually appear in the Macau dataset:
    * per-meter z-score outliers (a meter that suddenly jumps far from
      its own history)
    * day-over-day jumps (a meter whose value today is many times its
      own median |Δ|)
    * negative-reading pairs (a meter with both positive and negative
      totals on the same day — the 713911 / 1月8日 pattern)
- Adds a new correction to ``backend/data/corrections.json`` with
  duplicate / overlap detection so two notebook edits don't step on
  each other.
- Re-derives all 12 downstream daily JSONs from the patched cache by
  calling the converter's existing ``_build_*`` functions — no
  converter code is changed.

The workflow this enables is:
    investigate (find_*) → confirm (manual) → apply (add_correction)
    → rebuild (rebuild_downstream) → verify (re-run find_*)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

# Reuse the converter's internal paths and pure-function builders so the
# notebook workflow stays in lockstep with the regular converter run.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import real_data_converter as rdc  # noqa: E402
from pipeline import data_quality as dq  # noqa: E402

CACHE_PATH = rdc.DAILY_TOTALS_CACHE  # backend/data/output_real/daily_totals.json
OUTPUT_DIR = rdc.OUTPUT_DIR            # backend/data/output_real/
CORRECTIONS_PATH = rdc.DEFAULT_CORRECTIONS_FILE  # backend/data/corrections.json
HOURLY_SQLITE = rdc.DAILY_SQLITE      # backend/data/output_real/hourly_meter.db


# ── Load / cache ─────────────────────────────────────────────

def load_cache_as_df(cache_path: Path | str = CACHE_PATH) -> pd.DataFrame:
    """Pivot ``daily_totals.json`` into a tidy long-form DataFrame.

    Returns a DataFrame with columns ``[date, meterId, total]`` where
    ``date`` is a ``datetime64[ns]`` and ``total`` is float. Empty
    rows (where total == 0) are kept — they are valid "no consumption"
    readings.
    """
    p = Path(cache_path)
    if not p.exists():
        return pd.DataFrame(columns=["date", "meterId", "total"])
    with p.open("r", encoding="utf-8") as f:
        cache: dict = json.load(f)
    rows: list[dict] = []
    for date_str, by_meter in cache.items():
        for mid, total in by_meter.items():
            rows.append({"date": pd.to_datetime(date_str), "meterId": mid, "total": float(total)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["meterId", "date"]).reset_index(drop=True)
    return df


def load_corrections(path: Path | str = CORRECTIONS_PATH) -> list[dict]:
    """Read corrections.json. Empty list if the file is missing or empty."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f) or []
    if not isinstance(data, list):
        raise ValueError(f"corrections file must be a JSON list, got {type(data).__name__}")
    return data


# ── Find anomalies ───────────────────────────────────────────

def find_per_meter_outliers(
    df: pd.DataFrame,
    threshold_z: float = 4.0,
    min_history: int = 14,
) -> pd.DataFrame:
    """Per-meter z-score outliers.

    Delegates to ``pipeline.data_quality.detect_per_meter_outliers``
    (single source of truth) and reshapes the list output into a
    DataFrame sorted by ``|z|`` descending. Columns: ``[date, meterId,
    total, score]``. Empty DataFrame if nothing matches.
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "meterId", "total", "score"])
    entries = dq.detect_per_meter_outliers(
        df, threshold_z=threshold_z, min_history=min_history
    )
    if not entries:
        return pd.DataFrame(columns=["date", "meterId", "total", "score"])
    out = pd.DataFrame(entries)[["date", "meterId", "value", "score"]].rename(
        columns={"value": "total"}
    )
    out["date"] = pd.to_datetime(out["date"])
    out["total"] = out["total"].astype(float)
    return out.reset_index(drop=True)


def find_daily_jumps(
    df: pd.DataFrame,
    threshold_ratio: float = 20.0,
    min_history: int = 7,
) -> pd.DataFrame:
    """Day-over-day value-ratio jumps.

    Delegates to ``pipeline.data_quality.detect_daily_jumps`` (single
    source of truth) and reshapes the list output into a DataFrame
    sorted by ``score`` (= max/min) descending. Columns: ``[date,
    meterId, total, score]``. Threshold of 20 catches the 712720
    pattern (2,600 → 26,000 = 10× raw; 26,000/2,600 = 10× ratio in
    detect_daily_jumps's value-ratio definition).
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "meterId", "total", "score"])
    entries = dq.detect_daily_jumps(
        df, threshold_ratio=threshold_ratio, min_history=min_history
    )
    if not entries:
        return pd.DataFrame(columns=["date", "meterId", "total", "score"])
    out = pd.DataFrame(entries)[["date", "meterId", "value", "score"]].rename(
        columns={"value": "total"}
    )
    out["date"] = pd.to_datetime(out["date"])
    out["total"] = out["total"].astype(float)
    return out.reset_index(drop=True)


def find_negative_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """Meters with both positive and negative totals on the same day.

    The 1月8日 713911 pattern: a +42,940,982 reading and a -42,940,982
    reading on the same date from the same meter (fire test, meter
    swap, manual-entry typo). Returns rows with
    ``[date, meterId, total]`` — one per (date, meterId) where the
    daily sum is near zero but the individual hourly rows cancel.
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "meterId", "total"])
    # The daily cache stores the SUM of hourly rows, so the daily value
    # may already be near zero from cancellation. We look for a per-day
    # total that is much smaller than the absolute hourly activity
    # recorded in hourly_meter.db.
    if not HOURLY_SQLITE.exists():
        return pd.DataFrame(columns=["date", "meterId", "total"])
    try:
        con = sqlite3.connect(str(HOURLY_SQLITE))
        hourly = pd.read_sql_query(
            """
            SELECT meterId, substr(datetime, 1, 10) AS date,
                   SUM(consumption) AS sum_h,
                   SUM(ABS(consumption)) AS abs_h
            FROM hourly_meter
            GROUP BY meterId, date
            HAVING sum_h < abs_h * 0.1
            """,
            con,
        )
        con.close()
    except Exception:
        return pd.DataFrame(columns=["date", "meterId", "total"])
    if hourly.empty:
        return pd.DataFrame(columns=["date", "meterId", "total"])
    hourly["date"] = pd.to_datetime(hourly["date"])
    out = hourly.rename(columns={"sum_h": "total"})
    return out[["date", "meterId", "total"]].sort_values("date").reset_index(drop=True)


# ── Add a correction ─────────────────────────────────────────

def _overlaps(a: dict, b: dict) -> bool:
    """Return True if two corrections cover any common (meterId, date)."""
    if a["meterId"] != b["meterId"]:
        return False
    return not (a["end"] < b["start"] or b["end"] < a["start"])


def add_correction(
    meterId: str,
    start: str,
    end: str,
    factor: float,
    reason: str,
    corrections_path: Path | str = CORRECTIONS_PATH,
) -> dict:
    """Append a new correction to ``corrections.json`` after overlap check.

    Refuses to add if an existing correction for the same ``meterId``
    overlaps the ``[start, end]`` window (inclusive). The overlap check
    is the notebook's safety net: two interactive edits for the same
    meter / window would silently double-correct, and the converter's
    own check is per-row not per-correction.
    """
    new_entry = {
        "meterId": str(meterId),
        "start": str(start),
        "end": str(end),
        "factor": float(factor),
        "reason": str(reason),
    }
    # Field validation — mirror the converter's own checks.
    for k in ("meterId", "start", "end", "factor", "reason"):
        if k not in new_entry:
            raise ValueError(f"missing field {k!r} in new correction")
    try:
        datetime.strptime(new_entry["start"], "%Y-%m-%d")
        datetime.strptime(new_entry["end"], "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"start/end must be YYYY-MM-DD: {e}") from e
    if new_entry["end"] < new_entry["start"]:
        raise ValueError(f"end {new_entry['end']!r} is before start {new_entry['start']!r}")
    if new_entry["factor"] == 0:
        raise ValueError("factor must be non-zero")

    existing = load_corrections(corrections_path)
    for e in existing:
        if _overlaps(new_entry, e):
            raise ValueError(
                f"overlaps existing correction for {new_entry['meterId']!r}: "
                f"{e['start']}..{e['end']} factor={e['factor']}"
            )

    p = Path(corrections_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing.append(new_entry)
    with p.open("w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return new_entry


# ── Rebuild downstream JSONs ──────────────────────────────────

def _prune_hourly_sqlite(meterIds: list[str], start: str, end: str) -> int:
    """Delete hourly_meter rows for the (meterIds, [start, end]) window.

    The unique (meterId, datetime) index means INSERT OR IGNORE skips
    duplicates, so we must delete before re-inserting corrected values.
    Returns the number of rows deleted.
    """
    if not meterIds or not HOURLY_SQLITE.exists():
        return 0
    placeholders = ",".join("?" * len(meterIds))
    con = sqlite3.connect(str(HOURLY_SQLITE))
    n = con.execute(
        f"DELETE FROM hourly_meter "
        f"WHERE meterId IN ({placeholders}) "
        f"AND datetime BETWEEN ? AND ?",
        (*meterIds, f"{start} 00:00:00", f"{end} 23:00:00"),
    ).rowcount
    con.commit()
    con.close()
    return n


def rebuild_downstream(
    affected_meterIds: list[str] | None = None,
    affected_dates: list[str] | None = None,
    output_dir: Path | str = OUTPUT_DIR,
    hourly_window: int = 30,
) -> dict:
    """Re-derive the 12 daily JSONs from the (possibly patched) cache.

    The converter's ``_build_*`` functions are pure (they only read the
    cache and ``meter_map``), so this is the same code path that runs
    during a normal converter run. We skip the hourly JSONs (those
    are append-only and require re-reading the Excel files; a one-off
    notebook fix doesn't touch them).

    Args:
        affected_meterIds: meters whose hourly rows should be pruned
            before the next converter run (so re-insert picks up the
            corrected values). None = no SQLite change.
        affected_dates: ``[start, end]`` window for the prune.
        output_dir: where to write the daily JSONs.
        hourly_window: kept for parity with the converter CLI; not used
            here (the next converter run will use its own flag).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cache = rdc._load_daily_totals_cache()
    if not cache:
        return {"status": "no cache", "files_written": []}
    try:
        meter_map = rdc._load_reference_meters()
    except SystemExit as e:
        # _load_reference_meters() calls sys.exit() when reference Excels
        # are missing. Convert that to a normal error so the notebook
        # kernel stays alive.
        return {
            "status": "error",
            "error": "reference meters unavailable — run convert_real_data.bat once first",
            "files_written": [],
        }

    # Re-derive the 9 daily aggregates. Predictions return a tuple.
    daily_dma = rdc._build_daily_dma(cache, meter_map)
    top20 = rdc._build_top20_daily(cache, meter_map)
    rank = rdc._build_rank_changes(cache, meter_map)
    monthly_diff = rdc._build_monthly_main_sub_diff(cache, meter_map)
    search_idx = rdc._build_search_index(meter_map)
    cotai = rdc._build_cotai_calendar(cache, meter_map)
    weekly = rdc._build_weekly(daily_dma)
    anomalies = rdc._detect_anomalies(cache, meter_map)
    predictions, predictions_fitted = rdc._build_predictions(cache, meter_map)

    # Re-merge data_errors into anomalies as a convenience.
    data_errors = rdc._load_data_errors()
    data_error_anomalies = [
        {
            "date": e["date"],
            "meterId": e["meterId"],
            "type": "data_error",
            "severity": "high",
            "rawValue": e["rawValue"],
            "reason": e["reason"],
            "dma": (meter_map.get(e["meterId"], {}) or {}).get("dma", "Unclassified"),
            "propertyType": (meter_map.get(e["meterId"], {}) or {}).get("propertyType", ""),
            "buildingName": (meter_map.get(e["meterId"], {}) or {}).get("buildingName", ""),
        }
        for e in data_errors
    ]

    written: list[str] = []
    for name, payload in [
        ("daily_dma.json", daily_dma),
        ("weekly.json", weekly),
        ("daily_top20.json", top20),
        ("rank_changes.json", rank),
        ("monthly_main_sub_diff.json", monthly_diff),
        ("search_index.json", search_idx),
        ("cotai_calendar.json", cotai),
        ("anomalies.json", anomalies + data_error_anomalies),
        ("predictions.json", predictions),
        ("predictions_fitted.json", predictions_fitted),
    ]:
        with (out_dir / name).open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        written.append(name)

    n_pruned = 0
    if affected_meterIds and affected_dates and len(affected_dates) == 2:
        n_pruned = _prune_hourly_sqlite(
            affected_meterIds, affected_dates[0], affected_dates[1]
        )

    return {
        "status": "ok",
        "files_written": written,
        "dates_in_cache": len(cache),
        "meters_in_cache": sum(len(v) for v in cache.values()),
        "hourly_rows_pruned": n_pruned,
    }


# ── Public surface ───────────────────────────────────────────

__all__ = [
    "CACHE_PATH",
    "OUTPUT_DIR",
    "CORRECTIONS_PATH",
    "HOURLY_SQLITE",
    "load_cache_as_df",
    "load_corrections",
    "find_per_meter_outliers",
    "find_daily_jumps",
    "find_negative_pairs",
    "add_correction",
    "rebuild_downstream",
]


if __name__ == "__main__":
    # Quick smoke test
    df = load_cache_as_df()
    print(f"cache: {len(df):,} rows, {df['meterId'].nunique():,} meters, "
          f"{df['date'].min()} → {df['date'].max()}")
    o = find_per_meter_outliers(df)
    j = find_daily_jumps(df)
    n = find_negative_pairs(df)
    print(f"per_meter_outliers : {len(o)}")
    print(f"daily_jumps        : {len(j)}")
    print(f"negative_pairs     : {len(n)}")
