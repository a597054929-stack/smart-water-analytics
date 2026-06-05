"""Tests that table names referenced in the agent's SYSTEM_PROMPT actually
exist in the production SQLite database.

Background: on 2026-06-05 we discovered the system prompt referenced a
`meter_daily` table that does not exist in `analytics_real.db`. The agent
would have followed its own example and hit `no such table: meter_daily`
on real data. This test catches that class of bug at unit-test time.

Approach:
  1. Load SYSTEM_PROMPT from `agent.agent_executor`.
  2. Extract every table-like reference (after FROM, inside
     `get_table_schema_tool("...")`, etc.).
  3. Open `analytics_real.db` and read `sqlite_master`.
  4. Assert every referenced table exists. Otherwise fail with a clear
     message naming the missing table and the line it came from.
"""

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

# Tables to allow even if not in the DB (e.g. legacy / mock-only mentions
# in comments or in EXAMPLES that are illustrative rather than prescriptive).
# Keep this list short — every entry should be a deliberate, named exception.
_ALLOWED_MISSING: set[str] = set()


def _extract_table_refs(prompt: str) -> list[tuple[str, str]]:
    """Return [(table_name, matched_text), ...] for every table-like reference.

    Recognizes:
      - `get_table_schema_tool("name")` / `get_table_schema_tool('name')`
      - `FROM name` / `from name` (case-insensitive) inside SQL examples
      - `INTO name` (less common, but valid DML)
    """
    refs: list[tuple[str, str]] = []

    # 1. Explicit schema tool calls
    for m in re.finditer(r'get_table_schema_tool\(["\']([\w]+)["\']\)', prompt):
        refs.append((m.group(1), m.group(0)))

    # 2. SQL examples (FROM / INTO)
    for m in re.finditer(r'\b(?:FROM|INTO)\s+([A-Za-z_][A-Za-z0-9_]*)', prompt, re.IGNORECASE):
        name = m.group(1)
        # Skip SQL keywords that happen to follow FROM
        if name.lower() in {"select", "where", "join", "group", "order", "limit", "having"}:
            continue
        refs.append((name, m.group(0)))

    return refs


def _real_db_tables() -> set[str]:
    db_path = ROOT / "backend" / "data" / "analytics_real.db"
    if not db_path.exists():
        # Fall back to the mock DB so this test still runs in CI
        db_path = ROOT / "backend" / "data" / "analytics.db"
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def test_prompt_table_refs_exist_in_real_db():
    """Every table referenced in SYSTEM_PROMPT must exist in the real DB."""
    from agent.agent_executor import SYSTEM_PROMPT
    refs = _extract_table_refs(SYSTEM_PROMPT)
    assert refs, "No table references found — test setup is wrong"

    db_tables = _real_db_tables()
    if not db_tables:
        # No DB on disk (CI without data). Skip rather than fail.
        import pytest
        pytest.skip("No analytics_real.db or analytics.db on disk")

    missing = [
        (name, snippet) for (name, snippet) in refs
        if name not in db_tables and name not in _ALLOWED_MISSING
    ]
    assert not missing, (
        "SYSTEM_PROMPT references tables that don't exist in the real DB:\n"
        + "\n".join(f"  - {name!r} (from: {snippet!r})" for name, snippet in missing)
        + f"\n\nReal DB tables: {sorted(db_tables)}"
    )


def test_legacy_meter_daily_is_gone():
    """Regression: the `meter_daily` table reference that caused the 2026-06-05
    bug must NOT reappear in the prompt. If you intentionally add it back,
    update _ALLOWED_MISSING above and add a comment explaining why."""
    from agent.agent_executor import SYSTEM_PROMPT
    assert "meter_daily" not in SYSTEM_PROMPT, (
        "meter_daily reappeared in SYSTEM_PROMPT — this table does not exist "
        "in analytics_real.db. The agent will hit 'no such table' in production."
    )
