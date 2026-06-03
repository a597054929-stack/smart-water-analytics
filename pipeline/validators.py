"""Validation helpers used by the pipeline orchestrator.

These wrap Pandera + lightweight JSON structural checks in a uniform interface
that the orchestrator can call after every stage. Errors are raised as
`ValidationError` so the orchestrator can catch them once and log uniformly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pandera.errors as pa_errors

try:
    from . import logger as plog
    from . import schema as pschema
except ImportError:
    import logger as plog  # type: ignore
    import schema as pschema  # type: ignore


class ValidationError(Exception):
    """Raised when an artifact fails validation. Carries context for triage."""


def validate_dataframe(
    df: pd.DataFrame,
    schema_name: str,
    stage: str,
) -> pd.DataFrame:
    """Validate `df` against the named schema. Returns df on success.

    Args:
        df: the DataFrame to validate.
        schema_name: key into `schema.SCHEMA_REGISTRY`.
        stage: pipeline stage name (for log context).

    Raises:
        ValidationError: when the schema check fails.
    """
    log = plog.get_logger(f"pipeline.{stage}")
    try:
        result = pschema.validate(df, schema_name)
    except pa_errors.SchemaErrors as e:
        log.error(
            "schema validation failed",
            extra={
                "stage": stage,
                "metrics": {
                    "schema": schema_name,
                    "errors": str(e)[:500],
                    "n_failures": (
                        len(e.failure_cases)
                        if getattr(e, "failure_cases", None) is not None
                        else 0
                    ),
                },
            },
        )
        raise ValidationError(
            f"[{stage}] schema '{schema_name}' failed: {e}"
        ) from e
    except KeyError as e:
        raise ValidationError(str(e)) from e

    log.info(
        "schema validation passed",
        extra={
            "stage": stage,
            "metrics": {"schema": schema_name, "rows": int(len(result))},
        },
    )
    return result


def validate_json_structure(
    file_path: str | Path,
    expected_keys: Iterable[str],
    stage: str,
) -> dict:
    """Load a JSON file and confirm the expected top-level keys are present.

    Use this for manifest and config files where we don't want to spin up a
    full Pandera schema.
    """
    log = plog.get_logger(f"pipeline.{stage}")
    p = Path(file_path)
    if not p.exists():
        raise ValidationError(f"[{stage}] missing file: {p}")

    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValidationError(f"[{stage}] invalid JSON in {p}: {e}") from e

    missing = set(expected_keys) - set(data.keys() if isinstance(data, dict) else [])
    if missing:
        raise ValidationError(
            f"[{stage}] {p.name} missing required keys: {sorted(missing)}"
        )

    log.info(
        "json structure ok",
        extra={"stage": stage, "metrics": {"file": str(p), "n_keys": len(data)}},
    )
    return data


def check_no_nulls_in_critical_columns(
    df: pd.DataFrame,
    cols: Iterable[str],
    stage: str,
) -> None:
    """Raise if any of the critical columns contains nulls."""
    log = plog.get_logger(f"pipeline.{stage}")
    bad = [c for c in cols if c in df.columns and df[c].isna().any()]
    if bad:
        sample = (
            df[df[bad].isna().any(axis=1)]
            .head(3)
            .to_dict(orient="records")
        )
        raise ValidationError(
            f"[{stage}] nulls in critical columns {bad}. sample={sample}"
        )
    log.info(
        "no nulls in critical cols",
        extra={"stage": stage, "metrics": {"checked": list(cols)}},
    )


def check_unique(df: pd.DataFrame, col: str, stage: str) -> None:
    """Raise if a column has duplicate values (e.g. meterId)."""
    log = plog.get_logger(f"pipeline.{stage}")
    if col not in df.columns:
        raise ValidationError(f"[{stage}] column {col!r} not in dataframe")
    dupes = df[df[col].duplicated()][col].head(5).tolist()
    if dupes:
        raise ValidationError(
            f"[{stage}] column {col!r} has duplicates. sample={dupes}"
        )
    log.info(
        "uniqueness ok",
        extra={"stage": stage, "metrics": {"column": col, "n": int(len(df))}},
    )


def check_row_count(
    df: pd.DataFrame,
    min_rows: int,
    max_rows: int | None,
    stage: str,
) -> None:
    """Sanity check the row count of an artifact."""
    n = len(df)
    if n < min_rows:
        raise ValidationError(
            f"[{stage}] too few rows: {n} < {min_rows}"
        )
    if max_rows is not None and n > max_rows:
        raise ValidationError(
            f"[{stage}] too many rows: {n} > {max_rows}"
        )
    plog.get_logger(f"pipeline.{stage}").info(
        "row count ok",
        extra={"stage": stage, "metrics": {"rows": n}},
    )


__all__ = [
    "ValidationError",
    "validate_dataframe",
    "validate_json_structure",
    "check_no_nulls_in_critical_columns",
    "check_unique",
    "check_row_count",
]
