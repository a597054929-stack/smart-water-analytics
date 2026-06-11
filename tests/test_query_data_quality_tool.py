"""Tests for the agent-facing `query_data_quality` tool.

The pipeline-level data-quality module (`pipeline/data_quality.py`) is
covered in `tests/test_data_quality.py`. This file tests the LangChain
tool that surfaces `data_errors.json` to the agent.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))


def test_tool_returns_total_and_breakdown():
    """No-filter call returns total_errors + by_reason + recent."""
    from agent.agent_tools import query_data_quality
    out = json.loads(query_data_quality.invoke({}))
    assert "total_errors" in out
    assert "by_reason" in out
    assert "recent" in out
    if out["total_errors"] > 0:
        assert sum(out["by_reason"].values()) == out["total_errors"]


def test_tool_filters_by_meter_id():
    """meter_id filter narrows the result set to a single meter."""
    from agent.agent_tools import query_data_quality
    out = json.loads(query_data_quality.invoke({"meter_id": "713911"}))
    assert out["filters"]["meter_id"] == "713911"
    for e in out["recent"]:
        assert e["meterId"] == "713911"
    # 713911 is the well-known +42,940,982 / -42,940,982 incident on 1月8日
    if out["total_errors"] > 0:
        assert all(e["date"] == "2026-01-08" for e in out["recent"])


def test_tool_filters_by_date():
    """date filter (YYYY-MM-DD) narrows to that day."""
    from agent.agent_tools import query_data_quality
    out = json.loads(query_data_quality.invoke({"date": "2026-01-08"}))
    assert out["filters"]["date"] == "2026-01-08"
    for e in out["recent"]:
        assert e["date"] == "2026-01-08"


def test_tool_filters_by_reason_substring():
    """reason filter is case-insensitive substring match."""
    from agent.agent_tools import query_data_quality
    out = json.loads(query_data_quality.invoke({"reason": "fire-test"}))
    assert out["total_errors"] > 0
    for e in out["recent"]:
        assert "fire-test" in e["reason"].lower()


def test_tool_handles_no_matching_records():
    """Phase 2: query_data_quality reads from SQLite, not JSON. The
    old 'missing file' test (pointing DATA_DIR at an empty dir) is no
    longer applicable. Replaced with a filter that matches no records
    — the tool should return total_errors=0 cleanly without crashing.
    """
    from agent.agent_tools import query_data_quality
    out = json.loads(query_data_quality.invoke({"meter_id": "000000000"}))
    assert out["total_errors"] == 0
    assert out["recent"] == []
    assert out["by_reason"] == {}


def test_tool_is_registered_in_all_tools():
    """query_data_quality must be in ALL_TOOLS so the agent can call it."""
    from agent.agent_tools import ALL_TOOLS
    assert "query_data_quality" in [t.name for t in ALL_TOOLS], (
        "query_data_quality is not registered in ALL_TOOLS — the agent "
        "won't be able to call it. Did you forget to add it to the list?"
    )
