"""Regression tests: units and property types stay consistent after reload.

These tests guard against two bugs that have occurred in production:
1. Unit mismatch: JSON in m³ but SQLite in L (1000x off)
2. Property type drift: REAL_PROPERTY_TYPE_MAPPING not matching actual xlsx codes
"""
import json
import sqlite3
from pathlib import Path

import pytest

REAL_DATA_DIR = Path(__file__).resolve().parent.parent / "backend" / "data" / "output_real"
REAL_DB = Path(__file__).resolve().parent.parent / "backend" / "data" / "analytics_real.db"


@pytest.mark.skipif(not REAL_DATA_DIR.exists(), reason="real data not available")
@pytest.mark.skipif(not REAL_DB.exists(), reason="real DB not available")
class TestUnitConsistency:
    """Ensure JSON (m³) and SQLite values match after reload."""

    def test_daily_dma_units_match(self):
        """daily_dma.json total (m³) == SQLite daily_dma.total (m³)."""
        with open(REAL_DATA_DIR / "daily_dma.json", "r", encoding="utf-8") as f:
            daily = json.load(f)

        # Pick the first day's 澳門低區 entry
        sample = daily[0]
        date = sample["date"]
        json_total = sample["dmas"]["澳門低區"]["total"]

        con = sqlite3.connect(str(REAL_DB))
        cur = con.cursor()
        row = cur.execute(
            "SELECT total FROM daily_dma WHERE date=? AND dma=?",
            (date, "澳門低區"),
        ).fetchone()
        con.close()

        assert row is not None, f"No row for {date} 澳門低區"
        sql_total = row[0]
        # Both should be in m³ — allow small float drift
        assert abs(sql_total - json_total) < 1.0, (
            f"Unit mismatch: JSON={json_total:.2f} m³, SQLite={sql_total:.2f}. "
            f"If SQLite is ~1000x larger, the DB was loaded from pre-migration JSONs."
        )

    def test_predictions_units_match(self):
        """predictions.json value (m³) == SQLite predictions.predicted (m³)."""
        with open(REAL_DATA_DIR / "predictions.json", "r", encoding="utf-8") as f:
            preds = json.load(f)

        first_pred = preds["predictions"][0]
        meter_id = first_pred["meterId"]
        date = first_pred["predictions"][0]["date"]
        json_val = first_pred["predictions"][0]["value"]

        con = sqlite3.connect(str(REAL_DB))
        cur = con.cursor()
        row = cur.execute(
            "SELECT predicted FROM predictions WHERE meterId=? AND date=?",
            (meter_id, date),
        ).fetchone()
        con.close()

        assert row is not None, f"No prediction for {meter_id} on {date}"
        sql_val = row[0]
        assert abs(sql_val - json_val) < 1.0, (
            f"Unit mismatch: JSON={json_val:.2f} m³, SQLite={sql_val:.2f}"
        )


@pytest.mark.skipif(not REAL_DATA_DIR.exists(), reason="real data not available")
class TestPropertyTypes:
    """Ensure meter_info.json uses correct property type mapping."""

    def test_no_mock_office_code(self):
        """005:Office should not exist — 005 maps to Recreation, not Office."""
        with open(REAL_DATA_DIR / "meter_info.json", "r", encoding="utf-8") as f:
            mi = json.load(f)

        office_count = sum(
            1 for info in mi.values()
            if info.get("propertyType") == "005:Office"
        )
        assert office_count == 0, (
            f"Found {office_count} meters with '005:Office' — "
            f"this is a mock mapping. 005 should map to Recreation."
        )

    def test_no_mock_casino_as_hotel(self):
        """003:博彩 (Casino) should map to Entertainment, not Hotel."""
        with open(REAL_DATA_DIR / "meter_info.json", "r", encoding="utf-8") as f:
            mi = json.load(f)

        # 002:Entertainment comes from code 003 (博彩/Casino)
        entertainment_count = sum(
            1 for info in mi.values()
            if info.get("propertyType") == "002:Entertainment"
        )
        assert entertainment_count > 100, (
            f"Expected >100 Entertainment meters (from 003:博彩), got {entertainment_count}"
        )

    def test_hotel_from_code_009(self):
        """009:酒店 should map to 003:Hotel."""
        with open(REAL_DATA_DIR / "meter_info.json", "r", encoding="utf-8") as f:
            mi = json.load(f)

        hotel_count = sum(
            1 for info in mi.values()
            if info.get("propertyType") == "003:Hotel"
        )
        # 009:酒店 has 154 meters in xlsx, but some may have been deduped
        assert hotel_count > 100, (
            f"Expected >100 Hotel meters (from 009:酒店), got {hotel_count}"
        )
