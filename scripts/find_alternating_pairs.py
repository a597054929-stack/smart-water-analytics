"""Find alternating (negatively correlated) water meter pairs within the same
building in a given DMA.

Usage:
    python scripts/find_alternating_pairs.py --dma "路氹城區" [--threshold -0.3]

Output:
    1. backend/data/output_real/cotai_alternating_pairs.json  (structured data)
    2. reports/cotai_alternating_pairs_report.md              (human-readable)

Logic:
    1. Load meter metadata from analytics_real.db (meters table).
    2. Load per-meter daily totals from daily_totals.json (151 days).
    3. Filter to the target DMA + buildings with >= 2 meters.
    4. For each building, compute Pearson correlation between every pair.
    5. Pairs with r < threshold are flagged as "alternating".
    6. Confidence is HIGH if both meters share the same mainCode, LOW otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "backend" / "data" / "analytics_real.db"
DAILY_TOTALS_PATH = ROOT / "backend" / "data" / "output_real" / "daily_totals.json"
OUTPUT_JSON = ROOT / "backend" / "data" / "output_real" / "cotai_alternating_pairs.json"
OUTPUT_REPORT = ROOT / "reports" / "cotai_alternating_pairs_report.md"


def load_meter_metadata(db_path: Path, dma: str) -> dict:
    """Return {meterId: {buildingName, mainCode, supplyMode}} for the given DMA."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT meterId, buildingName, mainCode, supplyMode "
        "FROM meters WHERE dma = ? AND buildingName IS NOT NULL",
        (dma,),
    )
    meters = {}
    for meter_id, building, main_code, supply_mode in cur.fetchall():
        meters[meter_id] = {
            "buildingName": building,
            "mainCode": main_code or "",
            "supplyMode": supply_mode or "",
        }
    conn.close()
    return meters


def load_daily_totals(path: Path) -> dict[str, dict[str, float]]:
    """Load {date: {meterId: total}} from daily_totals.json."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def transpose_daily(daily: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Transpose {date: {meterId: total}} → {meterId: {date: total}}."""
    result: dict[str, dict[str, float]] = {}
    for date, meters in daily.items():
        for mid, val in meters.items():
            if mid not in result:
                result[mid] = {}
            result[mid][date] = val
    return result


def compute_pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation between two arrays. Returns 0.0 if constant."""
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def find_alternating_pairs(
    meter_meta: dict,
    meter_daily: dict[str, dict[str, float]],
    threshold: float = -0.3,
    min_days: int = 30,
    min_alt_ratio: float = 0.2,
) -> list[dict]:
    """Find negatively correlated meter pairs within the same building.

    Args:
        meter_meta: {meterId: {buildingName, mainCode, supplyMode}}
        meter_daily: {meterId: {date: total}}
        threshold: Pearson r below this flags a pair (e.g. -0.3)
        min_days: minimum overlapping days to compute correlation
        min_alt_ratio: minimum fraction of days that must alternate (e.g. 0.2 = 20%)

    Returns:
        List of pair dicts, sorted by correlation (most negative first).
    """
    # Group meters by building
    buildings: dict[str, list[str]] = {}
    for mid, info in meter_meta.items():
        bld = info["buildingName"]
        if mid in meter_daily:  # only meters with daily data
            buildings.setdefault(bld, []).append(mid)

    # Only buildings with >= 2 meters
    buildings = {b: mids for b, mids in buildings.items() if len(mids) >= 2}

    # Step 1: Compute all candidate pairs across all buildings
    candidates = []
    for building, mids in buildings.items():
        mids_sorted = sorted(mids)
        for i in range(len(mids_sorted)):
            for j in range(i + 1, len(mids_sorted)):
                a_id, b_id = mids_sorted[i], mids_sorted[j]
                a_daily = meter_daily.get(a_id, {})
                b_daily = meter_daily.get(b_id, {})

                common_dates = sorted(set(a_daily.keys()) & set(b_daily.keys()))
                if len(common_dates) < min_days:
                    continue

                a_vals = np.array([a_daily[d] for d in common_dates])
                b_vals = np.array([b_daily[d] for d in common_dates])

                r = compute_pearson(a_vals, b_vals)
                if r >= threshold:
                    continue

                a_median = float(np.median(a_vals))
                b_median = float(np.median(b_vals))
                alt_days = sum(
                    1 for av, bv in zip(a_vals, b_vals)
                    if (av > a_median and bv < b_median) or (av < a_median and bv > b_median)
                )

                if alt_days / len(common_dates) < min_alt_ratio:
                    continue

                a_meta = meter_meta.get(a_id, {})
                b_meta = meter_meta.get(b_id, {})
                shared_main = bool(
                    (a_meta.get("mainCode") and a_meta["mainCode"] == b_meta.get("mainCode"))
                    or (a_meta.get("contractId") and a_meta["contractId"] == b_meta.get("contractId"))
                )

                candidates.append({
                    "building": building,
                    "meterA": a_id,
                    "meterB": b_id,
                    "correlation": round(r, 4),
                    "overlappingDays": len(common_dates),
                    "alternatingDays": alt_days,
                    "avgDailyA": round(float(a_vals.mean()), 2),
                    "avgDailyB": round(float(b_vals.mean()), 2),
                    "sharedMainCode": shared_main,
                    "mainCode": a_meta.get("mainCode", ""),
                    "supplyModeA": a_meta.get("supplyMode", ""),
                    "supplyModeB": b_meta.get("supplyMode", ""),
                })

    # Step 2: Greedy matching — each meter can only appear in ONE pair.
    # Sort by correlation (most negative = strongest alternation first),
    # then greedily assign pairs. Once a meter is "used", it cannot
    # appear in any other pair.
    candidates.sort(key=lambda p: p["correlation"])
    used: set[str] = set()
    pairs = []
    for c in candidates:
        if c["meterA"] in used or c["meterB"] in used:
            continue
        pairs.append(c)
        used.add(c["meterA"])
        used.add(c["meterB"])

    return pairs


def write_report(
    pairs: list[dict],
    dma: str,
    threshold: float,
    n_buildings: int,
    n_days: int,
    output_path: Path,
) -> None:
    """Write a human-readable markdown report."""
    high = [p for p in pairs if p["sharedMainCode"]]
    low = [p for p in pairs if not p["sharedMainCode"]]

    lines = [
        f"# {dma} 交替用水表对检测报告",
        "",
        "## 检测参数",
        f"- DMA: {dma}",
        f"- 阈值: Pearson < {threshold}",
        f"- 数据: {n_days} 天日用水量",
        "",
        "## 结果摘要",
        f"- 检测 building 数: {n_buildings}",
        f"- 标记 pair 数: {len(pairs)}",
        f"- 高置信度（共享 mainCode）: {len(high)}",
        f"- 低置信度: {len(low)}",
        "",
    ]

    if pairs:
        best = pairs[0]
        lines.append(
            f"- 最强负相关: corr = {best['correlation']:.2f} "
            f"(building: {best['building']}, "
            f"meter {best['meterA']} ↔ {best['meterB']})"
        )
        lines.append("")

    if high:
        lines.append("## 高置信度 pair（建议现场确认）")
        lines.append("")
        by_building: dict[str, list[dict]] = {}
        for p in high:
            by_building.setdefault(p["building"], []).append(p)
        for bld, bld_pairs in by_building.items():
            lines.append(f"### {bld}")
            lines.append("| 表 A | 表 B | 相关系数 | 共享主表 | 日均 A | 日均 B | 交替天数 |")
            lines.append("|------|------|---------|---------|--------|--------|---------|")
            for p in bld_pairs:
                lines.append(
                    f"| {p['meterA']} | {p['meterB']} | {p['correlation']:.2f} "
                    f"| ✅ | {p['avgDailyA']:.1f} m³ | {p['avgDailyB']:.1f} m³ "
                    f"| {p['alternatingDays']}/{p['overlappingDays']} |"
                )
            lines.append("")

    if low:
        lines.append("## 低置信度 pair（需现场排查）")
        lines.append("")
        by_building_low: dict[str, list[dict]] = {}
        for p in low:
            by_building_low.setdefault(p["building"], []).append(p)
        for bld, bld_pairs in by_building_low.items():
            lines.append(f"### {bld}")
            lines.append("| 表 A | 表 B | 相关系数 | 共享主表 | 日均 A | 日均 B | 交替天数 |")
            lines.append("|------|------|---------|---------|--------|--------|---------|")
            for p in bld_pairs:
                lines.append(
                    f"| {p['meterA']} | {p['meterB']} | {p['correlation']:.2f} "
                    f"| ❌ | {p['avgDailyA']:.1f} m³ | {p['avgDailyB']:.1f} m³ "
                    f"| {p['alternatingDays']}/{p['overlappingDays']} |"
                )
            lines.append("")

    if not pairs:
        lines.append("*未检测到负相关表对。*")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated by `scripts/find_alternating_pairs.py`*")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {output_path}")


def main():
    # Ensure UTF-8 output on Windows (cp950 console can't handle Chinese)
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Find alternating meter pairs")
    parser.add_argument("--dma", default="路氹城區", help="Target DMA zone")
    parser.add_argument("--threshold", type=float, default=-0.3, help="Pearson threshold")
    parser.add_argument("--min-days", type=int, default=30, help="Min overlapping days")
    args = parser.parse_args()

    print(f"Loading meter metadata from {DB_PATH}...")
    meter_meta = load_meter_metadata(DB_PATH, args.dma)
    print(f"  {len(meter_meta)} meters in {args.dma}")

    print(f"Loading daily totals from {DAILY_TOTALS_PATH}...")
    daily = load_daily_totals(DAILY_TOTALS_PATH)
    n_dates = len(daily)
    print(f"  {n_dates} dates loaded")

    print("Transposing to per-meter view...")
    meter_daily = transpose_daily(daily)

    print(f"Finding alternating pairs (threshold={args.threshold})...")
    pairs = find_alternating_pairs(meter_meta, meter_daily, args.threshold, args.min_days)

    n_buildings = len(set(p["building"] for p in pairs))
    n_high = sum(1 for p in pairs if p["sharedMainCode"])
    n_low = len(pairs) - n_high
    print(f"\nResults: {len(pairs)} pairs in {n_buildings} buildings")
    print(f"  High confidence (shared mainCode): {n_high}")
    print(f"  Low confidence: {n_low}")

    if pairs:
        best = pairs[0]
        print(f"  Strongest: corr={best['correlation']:.2f} "
              f"({best['building']}: {best['meterA']} ↔ {best['meterB']})")

    # Write JSON
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "dma": args.dma,
        "threshold": args.threshold,
        "minDays": args.min_days,
        "nDates": n_dates,
        "nBuildings": n_buildings,
        "nPairs": len(pairs),
        "nHighConfidence": n_high,
        "nLowConfidence": n_low,
        "pairs": pairs,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nJSON written to {OUTPUT_JSON}")

    # Write report
    write_report(pairs, args.dma, args.threshold, n_buildings, n_dates, OUTPUT_REPORT)


if __name__ == "__main__":
    main()
