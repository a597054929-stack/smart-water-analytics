"""Fast daily aggregation from raw xlsx files (no pandas, no openpyxl).

The previous --full converter used pandas+openpyxl which is 50s per
21MB xlsx. This script uses zip + regex to extract just the meterId
and consumption columns directly from the sheet1.xml stream:

  - unzip xl/worksheets/sheet1.xml once per file (0.4s)
  - regex-extract the B (meterId) and F (用水量) cells per <row> (3s)

So 151 days of xlsx completes in ~8 minutes instead of ~125 minutes.

Output: replaces daily_totals.json with the full 151-day
{date: {meterId: total_m3}} cache. Source xlsx reports in liters,
we divide by 1000 at write time so the result is in m³ end-to-end.
"""

import json
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

USAGE_DIR = Path(r"C:\Users\Administrator\.openclaw\workspace\data\Macau 2026")
OUTPUT = Path(r"C:\Users\Administrator\.openclaw\workspace\portfolio\backend\data\output_real\daily_totals.json")

ROW_RE = re.compile(rb'<row[^>]*>(.*?)</row>', re.DOTALL)
# Inline-string meterId: <c r="B###" t="inlineStr"><is><t>123456</t>
B_RE = re.compile(rb'<c r="B\d+"[^>]*t="inlineStr"><is><t>(\d+)</t>')
# Numeric consumption: <c r="F###" t="n"><v>1234.0</v>
F_RE = re.compile(rb'<c r="F\d+"[^>]*t="n"><v>([\d.]+)')

HDR1 = b"TMTRCONS"
HDR2 = "物業編號".encode("utf-8")  # 物業編號 — header row 2


def aggregate_one(xlsx_path: Path) -> dict[str, float]:
    """Return {meterId: total_m3} for a single xlsx (in m³).

    The xlsx filename is the date (e.g. 20260101.xlsx → 2026-01-01),
    and the C-column in each row is an Excel serial number, not a
    string. We trust the filename as the canonical date and only
    extract B (meterId) and F (用水量) from the row body.
    """
    out: dict[str, float] = {}
    with zipfile.ZipFile(xlsx_path) as z:
        with z.open("xl/worksheets/sheet1.xml") as s:
            data = s.read()
    for m in ROW_RE.finditer(data):
        body = m.group(1)
        if HDR1 in body or HDR2 in body:
            continue
        bm = B_RE.search(body)
        fm = F_RE.search(body)
        if not (bm and fm):
            continue
        mid = bm.group(1).decode("ascii")
        # xlsx reports in liters → /1000 to m³. Round to 3 decimals.
        val = round(float(fm.group(1)) / 1000.0, 2)
        out[mid] = out.get(mid, 0.0) + val
    return out


def main():
    files = sorted(USAGE_DIR.glob("*.xlsx"))
    print(f"Files to process: {len(files)}", flush=True)
    if not files:
        sys.exit(f"No xlsx files in {USAGE_DIR}")

    t0 = time.time()
    # {date_str: {meterId: total_m3}} for the full 151-day window
    merged: dict[str, dict[str, float]] = {}
    meter_set: set[str] = set()
    for i, f in enumerate(files):
        t = time.time()
        # Filename is the canonical date
        date_str = f.stem  # "20260101"
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        by_mid = aggregate_one(f)
        merged[date_str] = by_mid
        meter_set.update(by_mid.keys())
        elapsed = time.time() - t
        total = time.time() - t0
        eta = (len(files) - i - 1) * (total / (i + 1))
        print(f"  [{i+1:3d}/{len(files)}] {f.name} ({date_str}): "
              f"{len(by_mid):,} meters — "
              f"{elapsed:5.2f}s/file, ETA {eta/60:4.1f}min", flush=True)

    print(f"\nTotal: {len(merged)} dates, {len(meter_set):,} unique meters, "
          f"{sum(len(v) for v in merged.values()):,} entries "
          f"in {time.time()-t0:.1f}s", flush=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    print(f"Wrote {OUTPUT} ({size_mb:.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
