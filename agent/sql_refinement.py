"""Self-refinement wrapper around the SQL tool.

Why: ReFoRCE (Snowflake Labs, 138 stars) showed that for text-to-SQL, a
self-refinement loop beats single-shot generation. SQLite errors are
enumerable (no such table, no such column, syntax error, ...) and the
fix space is small. We catch the error, ask the LLM to rewrite the SQL,
and retry — without consuming a ReAct step.

Design:
- This is a tool-level wrapper, NOT an agent-level loop. ReAct stays
  out of the retry path so the agent doesn't see the iterations.
- Each retry is one direct LLM call (no tool routing, no history).
- Max 2 retries (3 total attempts). Beyond that, return the original
  error so the agent can decide what to do.
- Schema context is passed in: the LLM sees the same column list
  get_table_schema_tool would have returned. This means callers can
  skip the schema-discovery step before calling sql_query.

Trade-off: 1 extra LLM call per failed query (worst case 3 extra). For
queries that succeed first try, the wrapper is a no-op (~0ms overhead).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from langchain_core.tools import tool

# Same bootstrap as sql_tools.py: `agent/` is not a real package (no
# __init__.py), so `from .sql_tools` always fails. Fall back to a flat
# import that uses an absolute path.
try:
    from .sql_tools import sql_query as _raw_sql_query, get_table_schema_tool
except ImportError:
    import sys
    from pathlib import Path
    _agent_dir = str(Path(__file__).resolve().parent)
    if _agent_dir not in sys.path:
        sys.path.insert(0, _agent_dir)
    from sql_tools import sql_query as _raw_sql_query, get_table_schema_tool  # type: ignore

from config import get_llm_config

log = logging.getLogger("sql_refinement")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


_MAX_RETRIES = 2
_FEW_SHOT = """\
You are a SQL repair assistant. Given a failed SQL query and the error
message, return ONLY a corrected SELECT/WITH statement.

RULES:
- Keep the user's intent identical (same WHERE, same aggregations).
- Only fix the syntax / table / column reference that caused the error.
- Do not add LIMIT unless the original had it.
- Do not change table aliases the user invented.
- Output ONE SQL statement, no prose, no markdown fences.

Example 1:
Failed: SELECT * FROM anomalys WHERE dma = 'Zone-3'
Error: no such table: anomalys
Fix:   SELECT * FROM anomalies WHERE dma = 'Zone-3'

Example 2:
Failed: SELECT dma, AVG(score) FROM anomalies GROUP BY dma
Error: no such column: score
Fix:   SELECT dma, AVG(anomalyScore) FROM anomalies GROUP BY dma

Example 3:
Failed: SELECT meterId, SUM(total) FROM meter_daily
Error: a GROUP BY clause is required
Fix:   SELECT meterId, SUM(total) FROM meter_daily GROUP BY meterId
"""


def _create_refine_llm():
    """Reuse the same provider / model / key as the main agent."""
    from langchain_openai import ChatOpenAI
    from langchain_anthropic import ChatAnthropic
    cfg = get_llm_config()
    if cfg["provider"] == "anthropic":
        return ChatAnthropic(
            model=cfg["model"],
            api_key=cfg["api_key"],
            base_url=cfg.get("base_url"),
            temperature=0,
            max_tokens=512,
        )
    return ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        temperature=0,
        max_tokens=512,
    )


def _call_refine_llm(failed_sql: str, error: str, schema_hint: str = "") -> str:
    """Ask the LLM to rewrite a failed SQL. Returns the raw text response."""
    llm = _create_refine_llm()
    user_msg = (
        f"Failed SQL:\n```sql\n{failed_sql}\n```\n\n"
        f"Error:\n{error}\n\n"
        + (f"Schema hint:\n{schema_hint}\n\n" if schema_hint else "")
        + "Return ONLY the corrected SQL."
    )
    resp = llm.invoke(
        [
            {"role": "system", "content": _FEW_SHOT},
            {"role": "user", "content": user_msg},
        ]
    )
    return _extract_sql(resp.content if hasattr(resp, "content") else str(resp))


def _extract_sql(text: str) -> str:
    """Pull a SQL statement out of the LLM's text response.

    Handles: bare SQL, ```sql ...``` fences, ``` ...``` fences, prose
    followed by a semicolon-terminated line. Strips trailing semicolons
    and whitespace.
    """
    text = text.strip()
    fence = re.search(r"```(?:sql)?\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1)
    # If still multi-line prose, take the first ; line and onward
    if ";" in text and not text.lower().startswith(("select", "with")):
        # find first SELECT / WITH
        m = re.search(r"(SELECT|WITH)\b[\s\S]+", text, re.IGNORECASE)
        if m:
            text = m.group(0)
    return text.rstrip(";").strip()


def _refine_sql(sql: str, limit: Optional[int], log_path: Optional[str]) -> dict[str, Any]:
    """Try sql_query; on error, ask LLM to fix and retry.

    Returns a dict matching the format of raw sql_query JSON output,
    with one extra key `attempts` for observability.
    """
    last_error = None
    current_sql = sql
    for attempt in range(_MAX_RETRIES + 1):
        raw = _raw_sql_query.invoke({"sql": current_sql, "limit": limit})
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"error": f"non-JSON tool output: {raw[:200]}"}

        if "error" not in parsed:
            parsed["attempts"] = attempt + 1
            if attempt > 0:
                log.info("self-refined after %d retries: %s", attempt, current_sql[:120])
                if log_path:
                    _append_log(log_path, attempt, current_sql, parsed.get("row_count"))
            return parsed

        last_error = parsed["error"]
        if attempt >= _MAX_RETRIES:
            break

        # Get the table name from the SQL (first FROM / JOIN) so we can pass schema
        m = re.search(r"(?:FROM|JOIN)\s+([A-Za-z_]\w*)", current_sql, re.IGNORECASE)
        schema_hint = ""
        if m:
            try:
                schema_raw = get_table_schema_tool.invoke({"table_name": m.group(1)})
                schema = json.loads(schema_raw)
                if "columns" in schema:
                    schema_hint = (
                        f"Table {m.group(1)} columns: "
                        + ", ".join(c.get("name", "?") for c in schema["columns"])
                    )
            except Exception:
                pass

        try:
            fixed = _call_refine_llm(current_sql, last_error, schema_hint)
            if not fixed or fixed.lower() == current_sql.lower():
                # LLM gave nothing back or echoed — give up
                break
            current_sql = fixed
        except Exception as e:
            log.warning("refine LLM call failed: %s", e)
            break

    return {
        "error": last_error,
        "attempts": _MAX_RETRIES + 1,
        "refinement_exhausted": True,
        "last_sql": current_sql,
    }


def _append_log(path: str, attempts: int, sql: str, row_count) -> None:
    """Append a one-line JSON record to a refinement log file."""
    import json as _json
    from datetime import datetime
    rec = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "attempts": attempts,
        "sql": sql[:500],
        "row_count": row_count,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Public tool ───────────────────────────────────────────────

@tool
def sql_query(sql: str, limit: Optional[int] = None) -> str:
    """Execute a read-only SQL query against the analytics database, with
    automatic self-refinement on errors.

    This is a drop-in replacement for the raw sql_query tool. It behaves
    identically on success. On failure (no such table, bad column, syntax
    error), it asks an LLM to rewrite the SQL and retries up to 2 times.
    Retries are transparent to the calling agent — they happen inside
    the tool and do not consume ReAct steps.

    Args:
        sql: a SELECT or WITH statement.
        limit: optional row cap (default 1000, max 1000).

    Returns:
        A JSON object: {"columns": [...], "rows": [[...]], "row_count": N, "attempts": K}.
        On exhausted retries: {"error": ..., "attempts": K, "refinement_exhausted": true, "last_sql": ...}.
    """
    log_path = os.environ.get("SQL_REFINEMENT_LOG", "")
    result = _refine_sql(sql, limit, log_path or None)
    return json.dumps(result, ensure_ascii=False)


__all__ = ["sql_query", "_refine_sql", "_call_refine_llm"]


if __name__ == "__main__":
    # Smoke: try a deliberately bad query and watch the refinement.
    print("== Bad SQL (should self-repair) ==")
    bad = "SELECT dma, AVG(score) FROM anomalies GROUP BY dma"
    print(sql_query.invoke({"sql": bad}))

    print("\n== Good SQL (first-try) ==")
    good = "SELECT dma, AVG(anomalyScore) AS s FROM anomalies GROUP BY dma ORDER BY s DESC LIMIT 5"
    print(sql_query.invoke({"sql": good}))

    print("\n== Truly broken (no fix possible) ==")
    broken = "SELECTGARBAGE oops"
    print(sql_query.invoke({"sql": broken}))
