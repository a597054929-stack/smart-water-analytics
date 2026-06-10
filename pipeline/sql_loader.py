"""JSON → SQLite loader.

Why SQLite?
- Zero-config. No separate server. Perfect for a portfolio and for
  developer-laptop runs. The same SQL works against Postgres if you ever
  promote to production.
- Faster aggregations than reading 16 JSON files every time the agent runs.
- The agent's text-to-SQL tools can query this database directly.

Tables created:
    meters               — one row per meter
    meter_daily          — one row per (meter, date) reading
    anomalies            — anomaly detections
    daily_dma            — daily total by DMA, with the per-DMA columns
                           denormalized into a single table
    weekly               — weekly aggregate
    rank_changes         — long-term top-20 entries
    monthly_diff         — main-vs-sub meter difference (NRW signal)
    predictions          — forecast rows
    predictions_building — per-building forecast rows
    search_index         — flat row per meter for fuzzy search
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import logger as plog
except ImportError:
    import logger as plog  # type: ignore


# Default location: backend/data/analytics.db (sibling of the JSON output dir).
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "backend" / "data"
DEFAULT_OUTPUT_DIR = DEFAULT_DATA_DIR / "output"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "analytics.db"


def _resolve_db_path() -> Path:
    """Return WATER_DB_PATH env override or default analytics.db."""
    env_path = os.environ.get("WATER_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


# ── Helpers ──────────────────────────────────────────────────

def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _df_of_list(path: Path) -> pd.DataFrame:
    data = _read_json(path)
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


def _denormalize_daily_dma(records: list[dict]) -> pd.DataFrame:
    """daily_dma.json has a `dmas` dict; flatten to one row per (date, DMA)."""
    rows = []
    for r in records:
        date = r.get("date")
        for dma, payload in (r.get("dmas") or {}).items():
            rows.append(
                {
                    "date": date,
                    "dma": dma,
                    "total": payload.get("total"),
                    "residential": payload.get("residential"),
                    "nonResidential": payload.get("nonResidential"),
                    "resCount": payload.get("resCount"),
                    "nonResCount": payload.get("nonResCount"),
                    "meterCount": payload.get("meterCount"),
                    "rain": payload.get("rain"),
                }
            )
    return pd.DataFrame(rows)


def _flatten_main_sub_diff(records: list[dict]) -> pd.DataFrame:
    """monthly_main_sub_diff.json has nested `diffs` arrays; expand them."""
    rows = []
    for r in records:
        month = r.get("month")
        for d in r.get("diffs") or []:
            rows.append(
                {
                    "month": month,
                    "mainMeterId": d.get("mainMeterId"),
                    "mainContractId": d.get("mainContractId"),
                    "mainBuilding": d.get("mainBuilding"),
                    "dma": d.get("dma"),
                    "subs": json.dumps(d.get("subs") or []),
                    "mainTotal": d.get("mainTotal"),
                    "subsTotal": d.get("subsTotal"),
                    "diff": d.get("diff"),
                    "diffPercent": d.get("diffPercent"),
                }
            )
    return pd.DataFrame(rows)


def _df_of_meter_info(path: Path) -> pd.DataFrame:
    """meter_info.json is `{meterId: {...}}`; turn into DataFrame rows."""
    data = _read_json(path) or {}
    if not data:
        return pd.DataFrame()
    return pd.DataFrame([{"meterId": k, **v} for k, v in data.items()])


# ── Loader ───────────────────────────────────────────────────

class SqlLoader:
    """One-call loader. Each `load_*` method reads the JSON and writes a table.

    Usage:
        loader = SqlLoader(db_path=Path("backend/data/analytics.db"))
        loader.load_all(Path("backend/data/output"))
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH, drop: bool = False):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        if drop:
            self._drop_all()
        self._create_indexes_done: set[str] = set()
        self.log = plog.get_logger("pipeline.sql_loader")

    def _drop_all(self) -> None:
        cur = self.conn.cursor()
        for t in [
            "meters", "meter_daily", "anomalies", "daily_dma", "weekly",
            "rank_changes", "monthly_diff", "predictions", "predictions_building",
            "search_index", "hourly_meter",
        ]:
            cur.execute(f"DROP TABLE IF EXISTS {t}")
        self.conn.commit()

    def _create_indexes(self, table: str, cols: Iterable[str]) -> None:
        key = f"{table}:{','.join(cols)}"
        if key in self._create_indexes_done:
            return
        self._create_indexes_done.add(key)
        cur = self.conn.cursor()
        for c in cols:
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{c} ON {table}({c})")
        self.conn.commit()

    def _write(
        self,
        df: pd.DataFrame,
        table: str,
        index_cols: Iterable[str] = (),
    ) -> int:
        if df.empty:
            self.log.info(
                f"skip {table}: empty",
                extra={"stage": "load_sql", "metrics": {"table": table}},
            )
            return 0
        df.to_sql(table, self.conn, if_exists="replace", index=False)
        self._create_indexes(table, index_cols)
        self.log.info(
            f"wrote {table}",
            extra={
                "stage": "load_sql",
                "metrics": {"table": table, "rows": int(len(df))},
            },
        )
        return int(len(df))

    # ── Individual loaders ───────────────────────────────────

    def load_meters(self, src: Path) -> int:
        df = _df_of_meter_info(src / "meter_info.json")
        return self._write(df, "meters", ["meterId", "dma"])

    def load_meter_daily(self, src: Path) -> int:
        # meter_daily.json is {meterId: {date: value}} — explode to rows.
        # Real data converter no longer writes this file (daily aggregates live
        # in daily_dma.json), so missing-file is the common case.
        path = src / "meter_daily.json"
        if not path.exists():
            self.log.info("skip meter_daily: file not found (use daily_dma)")
            return 0
        data = _read_json(path) or {}
        rows: list[dict] = []
        for meter_id, series in data.items():
            for date, total in (series or {}).items():
                rows.append({"meterId": meter_id, "date": date, "total": total})
        df = pd.DataFrame(rows)
        return self._write(df, "meter_daily", ["meterId", "date"])

    def load_hourly_meter(self, src: Path) -> int:
        """Real-data only: ingest hourly_meter.db (created by the converter).

        The hourly table holds ~15M rows for 30 days of real data, so we
        ATTACH the converter's SQLite file as a read-only database and
        copy into analytics.db in one shot.
        """
        hourly_db = src / "hourly_meter.db"
        if not hourly_db.exists():
            self.log.info("skip hourly_meter: hourly_meter.db not found (mock data)")
            return 0
        # Drop existing table to allow re-runs
        cur = self.conn.cursor()
        cur.execute("DROP TABLE IF EXISTS hourly_meter")
        self.conn.commit()

        # Attach the hourly database and copy all rows.
        attach_cur = self.conn.cursor()
        attach_cur.execute(f"ATTACH DATABASE '{hourly_db.as_posix()}' AS hourly")
        attach_cur.execute(
            "CREATE TABLE hourly_meter AS SELECT * FROM hourly.hourly_meter"
        )
        attach_cur.execute("DETACH DATABASE hourly")
        self.conn.commit()

        # Indexes
        self._create_indexes("hourly_meter", ["meterId", "datetime"])

        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM hourly_meter")
        n = cur.fetchone()[0]
        self.log.info(
            "wrote hourly_meter",
            extra={
                "stage": "load_sql",
                "metrics": {"table": "hourly_meter", "rows": n},
            },
        )
        return n

    def load_anomalies(self, src: Path) -> int:
        df = _df_of_list(src / "anomalies.json")
        return self._write(df, "anomalies", ["date", "meterId", "dma", "type"])

    def load_daily_dma(self, src: Path) -> int:
        df = _denormalize_daily_dma(_read_json(src / "daily_dma.json") or [])
        return self._write(df, "daily_dma", ["date", "dma"])

    def load_weekly(self, src: Path) -> int:
        records = _read_json(src / "weekly.json") or []
        # SQLite has no native dict — serialize the nested maps to JSON strings.
        rows = []
        for r in records:
            row = dict(r)
            for k in ("totalByDma", "wdByDmaRes", "dates", "dailyTotals"):
                if k in row and not isinstance(row[k], str):
                    row[k] = json.dumps(row[k])
            rows.append(row)
        df = pd.DataFrame(rows)
        return self._write(df, "weekly", ["weekStart", "weekEnd"])

    def load_rank_changes(self, src: Path) -> int:
        df = _df_of_list(src / "rank_changes.json")
        return self._write(df, "rank_changes", ["meterId", "dma", "trend"])

    def load_monthly_diff(self, src: Path) -> int:
        df = _flatten_main_sub_diff(_read_json(src / "monthly_main_sub_diff.json") or [])
        return self._write(df, "monthly_diff", ["month", "mainMeterId", "dma"])

    def load_predictions(self, src: Path) -> int:
        data = _read_json(src / "predictions.json") or {}
        preds = data.get("predictions") or []
        rows: list[dict] = []
        for p in preds:
            mid = p.get("meterId")
            for day in p.get("predictions") or []:
                v = day.get("predicted")
                if v is None:
                    v = day.get("value")
                rows.append(
                    {
                        "meterId": mid,
                        "date": day.get("date"),
                        "predicted": v,
                        "lower": day.get("lower"),
                        "upper": day.get("upper"),
                    }
                )
        df = pd.DataFrame(rows)
        return self._write(df, "predictions", ["meterId", "date"])

    def load_predictions_building(self, src: Path) -> int:
        data = _read_json(src / "predictions_by_building.json")
        # Mock data wraps a `predictions` list; real data is a bare list.
        if isinstance(data, dict):
            buildings = data.get("predictions") or []
        else:
            buildings = data or []
        rows: list[dict] = []
        for b in buildings:
            # Real data uses `buildingName`; mock data used `building`.
            name = b.get("building") or b.get("buildingName")
            for day in b.get("predictions") or []:
                v = day.get("predicted")
                if v is None:
                    v = day.get("value")
                rows.append(
                    {
                        "building": name,
                        "date": day.get("date"),
                        "predicted": v,
                        "lower": day.get("lower"),
                        "upper": day.get("upper"),
                    }
                )
        df = pd.DataFrame(rows)
        return self._write(df, "predictions_building", ["building", "date"])

    def load_search_index(self, src: Path) -> int:
        df = _df_of_list(src / "search_index.json")
        return self._write(df, "search_index", ["id", "dma"])

    def load_all(self, src: Path = DEFAULT_OUTPUT_DIR) -> dict[str, int]:
        """Run every loader. Returns a dict of {table: rows}."""
        self.log = plog.get_logger("pipeline.sql_loader")
        src = Path(src)
        results: dict[str, int] = {}
        results["meters"] = self.load_meters(src)
        results["meter_daily"] = self.load_meter_daily(src)
        results["hourly_meter"] = self.load_hourly_meter(src)
        results["anomalies"] = self.load_anomalies(src)
        results["daily_dma"] = self.load_daily_dma(src)
        results["weekly"] = self.load_weekly(src)
        results["rank_changes"] = self.load_rank_changes(src)
        results["monthly_diff"] = self.load_monthly_diff(src)
        results["predictions"] = self.load_predictions(src)
        results["predictions_building"] = self.load_predictions_building(src)
        results["search_index"] = self.load_search_index(src)
        self.log.info(
            "load_all complete",
            extra={
                "stage": "load_sql",
                "metrics": {"tables": len(results), "rows": sum(results.values())},
            },
        )
        return results

    def close(self) -> None:
        self.conn.close()


def list_tables(db_path: Path | None = None) -> list[dict]:
    if db_path is None:
        db_path = _resolve_db_path()
    """Return a list of {name, n_rows} for every table in the analytics DB."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = []
    for (name,) in cur.fetchall():
        cur2 = conn.cursor()
        cur2.execute(f"SELECT COUNT(*) FROM {name}")
        n = cur2.fetchone()[0]
        tables.append({"name": name, "rows": n})
    conn.close()
    return tables


def get_table_schema(table_name: str, db_path: Path | None = None) -> list[dict]:
    if db_path is None:
        db_path = _resolve_db_path()
    """Return column metadata for a table."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    rows = cur.fetchall()
    conn.close()
    return [
        {"cid": r[0], "name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])}
        for r in rows
    ]


def run_query(sql: str, db_path: Path | None = None, limit: int = 1000) -> tuple[list[str], list[tuple]]:
    if db_path is None:
        db_path = _resolve_db_path()
    """Execute a read-only SQL query. Returns (column_names, rows).

    For safety:
        - Only SELECT / WITH queries are allowed.
        - LIMIT is forced if missing (max 1000) to avoid runaway scans.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"db not found: {db_path}. Run SqlLoader first.")
    sql_clean = sql.strip().rstrip(";")
    if not sql_clean:
        raise ValueError("empty query")
    first = sql_clean.split(None, 1)[0].upper()
    if first not in ("SELECT", "WITH"):
        raise ValueError("only SELECT/WITH queries are allowed")
    if "LIMIT" not in sql_clean.upper():
        sql_clean = f"{sql_clean} LIMIT {limit}"

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(sql_clean)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    conn.close()
    return cols, rows


__all__ = [
    "DEFAULT_DB_PATH",
    "SqlLoader",
    "list_tables",
    "get_table_schema",
    "run_query",
]


if __name__ == "__main__":
    import sys
    db = DEFAULT_DB_PATH
    if "--db" in sys.argv:
        db = Path(sys.argv[sys.argv.index("--db") + 1])
    loader = SqlLoader(db_path=db, drop=True)
    res = loader.load_all()
    loader.close()
    print(json.dumps(res, indent=2))
    print("--- tables ---")
    print(json.dumps(list_tables(db), indent=2))
