"""Text-to-SQL tools for the AI agent.

These let the agent query a SQLite database directly when the user asks a
question that benefits from SQL:
- Aggregations (sum, avg, count, group by)
- Joins across tables (anomalies joined with meters)
- Top-N with ORDER BY
- Date range filters

Why this matters for HKT:
- CDR (Call Detail Record) tables are massive — JSON tools can't summarize
  them. SQL can. The same skill (text-to-SQL) transfers directly to HKT's
  CDR / network counter stores.
- Hybrid search: combine a fuzzy search_index lookup with a SQL aggregation
  in one answer. The agent picks the right tool per sub-question.

Safety:
- Only SELECT/WITH queries allowed.
- LIMIT forced if missing (max 1000).
- Errors return a structured message the agent can show the user.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from safe_tool_call import safe_tool_call

# Reuse the loader's helpers; the loader is intentionally side-effect-light.
try:
    from .sql_loader import (
        get_table_schema,
        list_tables,
        run_query,
    )
except ImportError:
    import sys
    from pathlib import Path
    _pipe_dir = Path(__file__).resolve().parent.parent / "pipeline"
    if str(_pipe_dir) not in sys.path:
        sys.path.insert(0, str(_pipe_dir))
    from sql_loader import (  # type: ignore
        get_table_schema,
        list_tables,
        run_query,
    )


# ── Tool: list tables ────────────────────────────────────────

@tool
@safe_tool_call("list_tables_tool", timeout_seconds=5)
def list_tables_tool() -> str:
    """List all available tables in the analytics SQLite database.

    Use this when you need to discover what data is available. Returns a JSON
    array of {name, rows} for every user table.
    """
    try:
        tables = list_tables()
        return json.dumps({"tables": tables, "count": len(tables)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tool: get table schema ───────────────────────────────────

@tool
@safe_tool_call("get_table_schema_tool", timeout_seconds=5)
def get_table_schema_tool(table_name: str) -> str:
    """Get the schema (columns + types) of a specific table.

    Args:
        table_name: exact name of a table, e.g. "anomalies" or "meters".

    Use this BEFORE writing complex SQL so you know what fields exist.
    """
    try:
        cols = get_table_schema(table_name)
        if not cols:
            return json.dumps(
                {"error": f"unknown table: {table_name!r}. Call list_tables first."}
            )
        return json.dumps({"table": table_name, "columns": cols}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tool: run a SQL query ────────────────────────────────────

@tool
@safe_tool_call("sql_query", timeout_seconds=30)
def sql_query(sql: str, limit: int | None = None) -> str:
    """Execute a read-only SQL query against the analytics database.

    Args:
        sql: a SELECT or WITH statement. Always include WHERE filters to
             limit results, and ORDER BY when you want top-N.
        limit: optional row cap (default 1000, max 1000). Will be auto-added
               if missing.

    Returns:
        A JSON object: {"columns": [...], "rows": [[...]], "row_count": N}.

    Available tables (key ones):
        meters               one row per meter (meterId, dma, isResidential, buildingName)
        meter_daily          one row per (meterId, date, total)
        anomalies            one row per anomaly (date, meterId, dma, type, anomalyScore)
        daily_dma            one row per (date, dma, total, rain)
        weekly               one row per week (weekStart, grandTotal, weekdayAvg)
        rank_changes         one row per long-term top-20 meter (meterId, daysInTop20, trend)
        monthly_diff         one row per (month, mainMeterId) with main/sub consumption
        predictions          one row per (meterId, date, predicted, lower, upper)
        search_index         one row per meter (id, building, dma) for fuzzy lookup
    """
    try:
        cols, rows = run_query(sql, limit=limit or 1000)
        # Convert to JSON-serializable form (some SQLite types are not natively JSON)
        rows_out = [[_jsonable(v) for v in r] for r in rows]
        return json.dumps(
            {
                "columns": cols,
                "rows": rows_out,
                "row_count": len(rows_out),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e), "hint": "Did you call get_table_schema first?"})


def _jsonable(v):
    """Coerce SQLite values into JSON-friendly types."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return str(v)
    return str(v)


# ── Public list ──────────────────────────────────────────────

ALL_SQL_TOOLS = [list_tables_tool, get_table_schema_tool, sql_query]

__all__ = ["ALL_SQL_TOOLS", "list_tables_tool", "get_table_schema_tool", "sql_query"]


if __name__ == "__main__":
    print("list_tables:", list_tables_tool.invoke({}))
    print("\nschema:", get_table_schema_tool.invoke({"table_name": "anomalies"}))
    print(
        "\ntop 3 anomalies:",
        sql_query.invoke(
            {"sql": "SELECT date, meterId, dma, type, anomalyScore FROM anomalies ORDER BY anomalyScore DESC LIMIT 3"}
        ),
    )
