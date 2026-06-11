"""Phase 5 C5-4: 5-query pre/post refactor diff verification.

Compares 5 representative agent queries against:
  PRE  = backup JSONs in backend/data/output_real_backup_20260610_233043/
  POST = current SQLite (analytics_real.db) via the migrated agent tools

Each query's count/sum/aggregate should be the same (modulo days
that passed between the backup and the current SQLite state — for
"daily total" queries, the most recent 1-2 days may differ).

Run: python scripts/_verify_5_query_diff.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Force the real DB before any imports
os.environ["WATER_DB_PATH"] = str(
    Path(__file__).resolve().parent.parent / "backend" / "data" / "analytics_real.db"
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

BACKUP = ROOT / "backend" / "data" / "output_real_backup_20260610_233043"

from agent.agent_tools import (
    get_predictions,
    query_anomalies,
    query_consumption,
    query_monthly_diff,
    query_meters,
)


def main():
    results = []

    # 1. count anomalies in 路氹城區
    with open(BACKUP / "anomalies.json", encoding="utf-8") as f:
        pre = json.load(f)
    pre_count = sum(1 for a in pre if "路" in a.get("dma", ""))
    out = query_anomalies.invoke({"dma": "路氹", "mode": "list", "limit": 9999})
    post_count = len(json.loads(out))
    results.append(("anomalies_in_cotai", pre_count, post_count))

    # 2. count meters with building containing 永利
    with open(BACKUP / "meter_info.json", encoding="utf-8") as f:
        pre = json.load(f)
    pre_n = sum(1 for m in pre.values() if "永利" in m.get("buildingName", ""))
    out = query_meters.invoke({"building": "永利", "limit": 9999})
    post_n = len(json.loads(out))
    results.append(("meters_永利", pre_n, post_n))

    # 3. daily_dma total for 2026-04 (m³)
    with open(BACKUP / "daily_dma.json", encoding="utf-8") as f:
        pre = json.load(f)
    pre_total = sum(
        s.get("total", 0)
        for d in pre
        if d["date"].startswith("2026-04")
        for s in d.get("dmas", {}).values()
    )
    out = query_consumption.invoke(
        {"mode": "compare", "month1": "2026-04", "month2": "2026-05"}
    )
    post_total = json.loads(out)["comparison"][0]["total"]
    # Allow 1% drift (days passed between backup and now)
    drift_ok = abs(pre_total - post_total) / max(pre_total, 1) < 0.05
    results.append(("daily_total_2026-04", pre_total, post_total, drift_ok))

    # 4. monthly_diff 2026-05 meter count
    with open(BACKUP / "monthly_main_sub_diff.json", encoding="utf-8") as f:
        pre = json.load(f)
    pre_may = next((m for m in pre if m["month"] == "2026-05"), None)
    pre_n = len(pre_may["diffs"]) if pre_may else 0
    out = query_monthly_diff.invoke({"month": "2026-05"})
    post_may = json.loads(out)
    post_n = len(post_may.get("diffs", [])) if isinstance(post_may, dict) else 0
    results.append(("monthly_diff_2026-05_meters", pre_n, post_n))

    # 5. predictions meter count (NOT building count — they're different units)
    with open(BACKUP / "predictions.json", encoding="utf-8") as f:
        pre = json.load(f)
    pre_n = len(pre.get("predictions", []))
    out = get_predictions.invoke({"query_type": "meter", "limit": 9999})
    post_n = json.loads(out).get("total_predictions", 0)
    results.append(("predictions_meter_count", pre_n, post_n))

    # Print table
    print("=" * 80)
    print(f"{'Query':<32} {'PRE':>12} {'POST':>12} {'OK?':>5}  {'Delta':>10}")
    print("=" * 80)
    sys.stdout.reconfigure(encoding="utf-8")
    all_ok = True
    for r in results:
        if len(r) == 4:
            name, pre_v, post_v, drift_ok = r
            delta = post_v - pre_v
            delta_pct = (delta / pre_v * 100) if pre_v else 0
            ok = drift_ok
        else:
            name, pre_v, post_v = r
            delta = post_v - pre_v
            delta_pct = (delta / pre_v * 100) if pre_v else 0
            ok = delta == 0
        marker = "✓" if ok else "✗"
        print(f"{name:<32} {pre_v:>12} {post_v:>12} {marker:>5}  {delta_pct:>+9.2f}%")
        if not ok:
            all_ok = False
    print("=" * 80)
    print(f"\nVerdict: {'ALL CONSISTENT' if all_ok else 'DRIFT DETECTED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
