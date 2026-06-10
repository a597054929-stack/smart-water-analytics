"""Shared SQLite helpers for agent tools.

Phase 2 of ARCHITECTURE_OPTIMIZATION_PLAN: replaces the JSON _load(filename)
pattern in agent/agent_tools.py with run_query(sql) calls against the
single source of truth (analytics_real.db).

Reuses pipeline.sql_loader.run_query (already used by agent/sql_tools.py
for sql_query, list_tables_tool, get_table_schema_tool, and by
agent/agent_tools.py:sql_chart).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable so 'pipeline.sql_loader' resolves
# whether this file is imported by tests, by the server, or as a module.
_agent_dir = str(Path(__file__).resolve().parent)
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

from pipeline.sql_loader import run_query, list_tables, get_table_schema  # noqa: E402


def _query_all(sql: str) -> list[dict]:
    """Execute a SELECT, return list of dict rows.

    Wraps pipeline.sql_loader.run_query (which returns (cols, rows) tuples)
    into a list of column-keyed dicts that the tools can JSON-dump directly.
    """
    cols, rows = run_query(sql, limit=1000)
    return [dict(zip(cols, r)) for r in rows]


def _query_one(sql: str) -> dict | None:
    """Execute a SELECT, return first dict row or None.

    Convenience for COUNT(*), MAX(*), single-row fetches.
    """
    rows = _query_all(sql)
    return rows[0] if rows else None


__all__ = ["_query_all", "_query_one", "run_query", "list_tables", "get_table_schema"]
