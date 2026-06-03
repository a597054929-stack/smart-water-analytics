"""Pandera schemas for every pipeline artifact.

Why Pandera?
- Lets us express column types, value ranges, and uniqueness constraints
  declaratively in Python — the same language as the rest of the pipeline.
- When validation fails, the error message tells you exactly which cell is bad.
- A failed schema check is the single most useful MLOps signal: the upstream
  contract changed (or there's a bug). Catch it at the boundary, not in prod.

We define one schema per artifact. Each is enforced right after the artifact
is produced. Schemas are versioned via `SCHEMA_VERSION` so future migrations
can be detected.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera import Check, Field

SCHEMA_VERSION = "1.0.0"

# Valid DMA zones (mock data uses these exact labels).
VALID_DMAS = ["Zone-1", "Zone-2", "Zone-3", "Zone-4", "Unclassified"]
# Anomaly types the detector can produce.
VALID_ANOMALY_TYPES = ["spike", "drop", "zero", "watch"]
# Property types seen in the data. Anything else is mapped to "Other".
VALID_PROPERTY_TYPES = [
    "001:Residential",
    "002:Commercial",
    "003:Hotel",
    "004:Restaurant",
    "005:Office",
    "006:Industrial",
    "007:Government",
    "008:Education",
    "009:Healthcare",
    "010:Recreation",
    "011:Swimming Pool",
    "012:Fire System",
    "013:Public Facility",
    "014:Green Space",
    "015:Transport",
]


# ── Anomalies ────────────────────────────────────────────────

class AnomalySchema(pa.DataFrameModel):
    """One row per detected meter-day anomaly."""

    date: str = Field(str_length={"min_value": 10, "max_value": 10})
    meterId: str = Field(str_matches=r"^\d{6,10}$")
    total: float = Field(ge=0, le=1000000)
    contractId: str = Field(nullable=True)
    dma: str = Field(isin=VALID_DMAS)
    buildingName: str = Field(nullable=True)
    reason: str
    type: str = Field(isin=VALID_ANOMALY_TYPES)
    anomalyScore: float = Field(ge=0.0, le=1.0)
    pastMean: float = Field(ge=0)
    pastStd: float = Field(ge=0)
    windowDays: int = Field(ge=1, le=365)

    class Config:
        coerce = True
        strict = False
        ordered = False


# ── Meter info ───────────────────────────────────────────────

class MeterInfoSchema(pa.DataFrameModel):
    """One row per meter."""

    meterId: str = Field(str_matches=r"^\d{6,10}$", unique=True)
    dma: str = Field(isin=VALID_DMAS)
    propertyType: str = Field(isin=VALID_PROPERTY_TYPES, nullable=True)
    isResidential: bool
    contractId: str = Field(nullable=True)
    buildingName: str = Field(nullable=True)
    supplyMode: str = Field(isin=["DIRECT", "INDIRECT"], nullable=True)
    mainCode: str = Field(str_matches=r"^\d{6,10}$", nullable=True)

    class Config:
        coerce = True
        strict = False


# ── Daily DMA aggregate ──────────────────────────────────────

class DailyDmaRowSchema(pa.DataFrameModel):
    """One row per date (with dmas expanded or kept as JSON)."""

    date: str = Field(str_length=10)

    class Config:
        coerce = True
        strict = False


# ── Predictions ──────────────────────────────────────────────

class PredictionRowSchema(pa.DataFrameModel):
    """One row per meter-day prediction."""

    date: str = Field(str_length=10)
    meterId: str = Field(str_matches=r"^\d{6,10}$")
    predicted: float = Field(ge=0, le=1000000)
    lower: float = Field(ge=0)
    upper: float = Field(ge=0)

    class Config:
        coerce = True
        strict = False


# ── Weekly summary ───────────────────────────────────────────

class WeeklySummarySchema(pa.DataFrameModel):
    weekStart: str = Field(str_length=10)
    weekEnd: str = Field(str_length=10)
    label: str
    grandTotal: float = Field(ge=0)
    weekdayAvg: float = Field(ge=0)
    weekendAvg: float = Field(ge=0)

    class Config:
        coerce = True
        strict = False


# ── Rank changes ─────────────────────────────────────────────

class RankChangeSchema(pa.DataFrameModel):
    meterId: str = Field(str_matches=r"^\d{6,10}$")
    daysInTop20: int = Field(ge=0, le=365)
    avgTotal: float = Field(ge=0)
    avgRank: float = Field(ge=0, le=500)
    trend: str = Field(isin=["up", "down", "flat"])

    class Config:
        coerce = True
        strict = False


# ── Search index ─────────────────────────────────────────────

class SearchIndexSchema(pa.DataFrameModel):
    id: str = Field(str_matches=r"^\d{6,10}$", unique=True)
    contract: str = Field(nullable=True)
    building: str = Field(nullable=True)
    dma: str = Field(isin=VALID_DMAS, nullable=True)
    type: str = Field(nullable=True)

    class Config:
        coerce = True
        strict = False


# ── Schema registry ──────────────────────────────────────────

SCHEMA_REGISTRY = {
    "anomalies": AnomalySchema,
    "meter_info": MeterInfoSchema,
    "daily_dma": DailyDmaRowSchema,
    "predictions": PredictionRowSchema,
    "weekly": WeeklySummarySchema,
    "rank_changes": RankChangeSchema,
    "search_index": SearchIndexSchema,
}


def validate(df: pd.DataFrame, schema_name: str) -> pd.DataFrame:
    """Validate a DataFrame against a registered schema.

    Raises:
        KeyError: unknown schema_name
        pa.errors.SchemaError: validation failure
    """
    if schema_name not in SCHEMA_REGISTRY:
        raise KeyError(f"Unknown schema: {schema_name}. "
                       f"Available: {list(SCHEMA_REGISTRY)}")
    return SCHEMA_REGISTRY[schema_name].validate(df, lazy=True)


__all__ = [
    "SCHEMA_VERSION",
    "VALID_DMAS",
    "VALID_ANOMALY_TYPES",
    "VALID_PROPERTY_TYPES",
    "AnomalySchema",
    "MeterInfoSchema",
    "DailyDmaRowSchema",
    "PredictionRowSchema",
    "WeeklySummarySchema",
    "RankChangeSchema",
    "SearchIndexSchema",
    "SCHEMA_REGISTRY",
    "validate",
]
