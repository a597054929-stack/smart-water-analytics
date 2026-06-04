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

# Valid DMA zones (mock data + real Macau data).
VALID_DMAS = [
    # Mock zones
    "Zone-1", "Zone-2", "Zone-3", "Zone-4", "Unclassified",
    # Real Macau zones (from MACAU-reference)
    "澳門低區", "澳門填海A區", "澳大橫琴區", "路氹城區",
]
# Anomaly types the detector can produce.
VALID_ANOMALY_TYPES = ["spike", "drop", "zero", "watch"]
# Property types seen in the data. Anything else is mapped to "Other".
# Real Macau types → standardized types
REAL_PROPERTY_TYPE_MAPPING = {
    "001": "001:Residential",
    "002": "002:Commercial",
    "003": "003:Hotel",
    "004": "004:Restaurant",
    "005": "005:Office",
    "006": "006:Industrial",
    "007": "007:Government",
    "008": "008:Education",
    "009": "009:Healthcare",
    "010": "010:Recreation",
    "011": "011:Swimming Pool",
    "012": "012:Fire System",
    "013": "013:Public Facility",
    "014": "014:Green Space",
    "015": "015:Transport",
    "016": "002:Commercial",
    "017": "002:Commercial",
    "018": "013:Public Facility",
    "019": "002:Commercial",
    "020": "002:Commercial",
    "021": "002:Commercial",
    "022": "004:Restaurant",
    "023": "002:Commercial",
    "024": "002:Commercial",
    "025": "002:Commercial",
    "026": "002:Commercial",
    "027": "002:Commercial",
    "028": "002:Commercial",
    "029": "002:Commercial",
    "030": "002:Commercial",
    "031": "002:Commercial",
    "032": "002:Commercial",
    "033": "002:Commercial",
    "034": "002:Commercial",
    "035": "002:Commercial",
    "036": "002:Commercial",
    "037": "002:Commercial",
    "038": "002:Commercial",
    "039": "002:Commercial",
    "040": "002:Commercial",
    "041": "002:Commercial",
    "042": "002:Commercial",
    "043": "002:Commercial",
    "044": "002:Commercial",
    "045": "002:Commercial",
    "046": "002:Commercial",
    "047": "002:Commercial",
    "048": "009:Healthcare",
    "049": "009:Healthcare",
    "050": "007:Government",
    "051": "007:Government",
    "052": "007:Government",
    "053": "007:Government",
    "054": "007:Government",
    "055": "007:Government",
    "056": "007:Government",
    "057": "007:Government",
    "058": "005:Office",
    "059": "002:Commercial",
    "060": "002:Commercial",
    "061": "002:Commercial",
    "062": "002:Commercial",
    "063": "002:Commercial",
    "064": "002:Commercial",
    "065": "012:Fire System",
    "066": "002:Commercial",
    "067": "002:Commercial",
    "068": "002:Commercial",
    "069": "002:Commercial",
    "070": "002:Commercial",
    "071": "002:Commercial",
    "072": "002:Commercial",
    "073": "002:Commercial",
    "074": "002:Commercial",
    "075": "002:Commercial",
    "076": "002:Commercial",
    "077": "002:Commercial",
    "078": "002:Commercial",
    "079": "002:Commercial",
    "080": "002:Commercial",
    "081": "002:Commercial",
    "082": "002:Commercial",
    "083": "002:Commercial",
    "084": "002:Commercial",
    "085": "002:Commercial",
    "086": "002:Commercial",
    "087": "002:Commercial",
    "088": "002:Commercial",
    "089": "002:Commercial",
    "090": "002:Commercial",
    "091": "002:Commercial",
    "092": "002:Commercial",
    "093": "002:Commercial",
    "094": "002:Commercial",
    "095": "002:Commercial",
    "096": "002:Commercial",
    "097": "002:Commercial",
    "098": "002:Commercial",
    "099": "002:Commercial",
    "100": "002:Commercial",
}
VALID_PROPERTY_TYPES = list(REAL_PROPERTY_TYPE_MAPPING.values())


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


# ── Meter daily readings ────────────────────────────────────

class MeterDailySchema(pa.DataFrameModel):
    """One row per (meter, date) reading."""

    meterId: str = Field(str_matches=r"^\d{6,10}$")
    date: str = Field(str_length=10)
    total: float = Field(ge=0, le=1000000)

    class Config:
        coerce = True
        strict = False


# ── Cotai calendar ──────────────────────────────────────────

class CotaiCalendarSchema(pa.DataFrameModel):
    """One row per (date, meter) in Zone-3 non-residential top consumers."""

    date: str = Field(str_length=10)
    meterId: str = Field(str_matches=r"^\d{6,10}$")
    total: float = Field(ge=0)
    buildingName: str = Field(nullable=True)
    contractId: str = Field(nullable=True)

    class Config:
        coerce = True
        strict = False


# ── Daily top 20 ────────────────────────────────────────────

class DailyTop20Schema(pa.DataFrameModel):
    """One row per (date, rank) in the daily top-20 consumption list."""

    date: str = Field(str_length=10)
    meterId: str = Field(str_matches=r"^\d{6,10}$")
    total: float = Field(ge=0)
    dma: str = Field(isin=VALID_DMAS, nullable=True)
    contractId: str = Field(nullable=True)
    propertyType: str = Field(nullable=True)
    buildingName: str = Field(nullable=True)

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
    "meter_daily": MeterDailySchema,
    "cotai_calendar": CotaiCalendarSchema,
    "daily_top20": DailyTop20Schema,
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
    "REAL_PROPERTY_TYPE_MAPPING",
    "AnomalySchema",
    "MeterInfoSchema",
    "DailyDmaRowSchema",
    "PredictionRowSchema",
    "WeeklySummarySchema",
    "RankChangeSchema",
    "SearchIndexSchema",
    "MeterDailySchema",
    "CotaiCalendarSchema",
    "DailyTop20Schema",
    "SCHEMA_REGISTRY",
    "validate",
]
