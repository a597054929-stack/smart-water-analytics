"""Unit tests for scripts/find_alternating_pairs.py

Pure logic tests using synthetic data — no database, no real files.
"""

import numpy as np
import pytest

from scripts.find_alternating_pairs import (
    compute_pearson,
    find_alternating_pairs,
    transpose_daily,
)


def _make_daily(meter_a: dict, meter_b: dict) -> dict[str, dict[str, float]]:
    """Build a {date: {meterId: total}} dict from two per-meter dicts."""
    daily: dict[str, dict[str, float]] = {}
    all_dates = set(meter_a.keys()) | set(meter_b.keys())
    for d in all_dates:
        daily[d] = {}
        if d in meter_a:
            daily[d]["A"] = meter_a[d]
        if d in meter_b:
            daily[d]["B"] = meter_b[d]
    return daily


def _alternating_series(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Two series that alternate: when A is high, B is low, and vice versa."""
    a = np.array([10.0 if i % 2 == 0 else 1.0 for i in range(n)])
    b = np.array([1.0 if i % 2 == 0 else 10.0 for i in range(n)])
    return a, b


def test_perfect_negative_correlation():
    """完全交替的两个序列应 corr ≈ -1.0"""
    a, b = _alternating_series(100)
    r = compute_pearson(a, b)
    assert r < -0.9, f"Expected strong negative corr, got {r}"


def test_no_correlation():
    """两个相同常数序列应 corr = 0"""
    a = np.ones(50) * 5.0
    b = np.ones(50) * 5.0
    r = compute_pearson(a, b)
    assert r == 0.0, f"Expected 0.0, got {r}"


def test_positive_correlation():
    """两个同步序列应 corr ≈ +1.0"""
    a = np.arange(50, dtype=float)
    b = np.arange(50, dtype=float) * 2
    r = compute_pearson(a, b)
    assert r > 0.99, f"Expected strong positive corr, got {r}"


def test_find_pair_detected():
    """Alternating meters in same building should be found."""
    n = 60
    dates = {f"2026-01-{d+1:02d}": float(i) for i, d in enumerate(range(n))}
    a_vals = {d: (10.0 if i % 2 == 0 else 1.0) for i, d in enumerate(sorted(dates))}
    b_vals = {d: (1.0 if i % 2 == 0 else 10.0) for i, d in enumerate(sorted(dates))}

    daily = _make_daily(a_vals, b_vals)
    meter_daily = transpose_daily(daily)

    meta = {
        "A": {"buildingName": "Test Building", "mainCode": "M001", "supplyMode": "DIRECT"},
        "B": {"buildingName": "Test Building", "mainCode": "M001", "supplyMode": "INDIRECT"},
    }

    pairs = find_alternating_pairs(meta, meter_daily, threshold=-0.3, min_days=30)
    assert len(pairs) == 1
    assert pairs[0]["correlation"] < -0.9
    assert pairs[0]["sharedMainCode"] is True


def test_different_buildings_not_paired():
    """Meters in different buildings should not be paired."""
    n = 60
    dates = [f"2026-01-{d+1:02d}" for d in range(n)]
    daily = {}
    for d in dates:
        daily[d] = {"A": 10.0, "B": 1.0}

    meter_daily = transpose_daily(daily)
    meta = {
        "A": {"buildingName": "Building A", "mainCode": "", "supplyMode": ""},
        "B": {"buildingName": "Building B", "mainCode": "", "supplyMode": ""},
    }

    pairs = find_alternating_pairs(meta, meter_daily, threshold=-0.3, min_days=30)
    assert len(pairs) == 0


def test_insufficient_days_skipped():
    """Pairs with fewer overlapping days than min_days should be skipped."""
    dates = {f"2026-01-{d+1:02d}": float(d) for d in range(10)}
    daily = _make_daily(dates, dates)
    meter_daily = transpose_daily(daily)

    meta = {
        "A": {"buildingName": "B", "mainCode": "", "supplyMode": ""},
        "B": {"buildingName": "B", "mainCode": "", "supplyMode": ""},
    }

    pairs = find_alternating_pairs(meta, meter_daily, threshold=-0.3, min_days=30)
    assert len(pairs) == 0


def test_constant_series_excluded():
    """If one meter is constant (zero std), corr=0, should not be flagged."""
    n = 60
    dates = [f"2026-01-{d+1:02d}" for d in range(n)]
    daily = {}
    for d in dates:
        daily[d] = {"A": 5.0, "B": float(n)}  # A is constant

    meter_daily = transpose_daily(daily)
    meta = {
        "A": {"buildingName": "B", "mainCode": "", "supplyMode": ""},
        "B": {"buildingName": "B", "mainCode": "", "supplyMode": ""},
    }

    pairs = find_alternating_pairs(meta, meter_daily, threshold=-0.3, min_days=30)
    assert len(pairs) == 0


def test_shared_main_code_confidence():
    """Pairs sharing mainCode should be marked high confidence."""
    n = 60
    dates = {f"2026-01-{d+1:02d}": float(i) for i, d in enumerate(range(n))}
    a_vals = {d: (10.0 if i % 2 == 0 else 1.0) for i, d in enumerate(sorted(dates))}
    b_vals = {d: (1.0 if i % 2 == 0 else 10.0) for i, d in enumerate(sorted(dates))}

    daily = _make_daily(a_vals, b_vals)
    meter_daily = transpose_daily(daily)

    # Same mainCode
    meta = {
        "A": {"buildingName": "B", "mainCode": "M001", "supplyMode": ""},
        "B": {"buildingName": "B", "mainCode": "M001", "supplyMode": ""},
    }
    pairs = find_alternating_pairs(meta, meter_daily, threshold=-0.3, min_days=30)
    assert len(pairs) == 1
    assert pairs[0]["sharedMainCode"] is True

    # Different mainCode
    meta2 = {
        "A": {"buildingName": "B", "mainCode": "M001", "supplyMode": ""},
        "B": {"buildingName": "B", "mainCode": "M002", "supplyMode": ""},
    }
    pairs2 = find_alternating_pairs(meta2, meter_daily, threshold=-0.3, min_days=30)
    assert len(pairs2) == 1
    assert pairs2[0]["sharedMainCode"] is False
