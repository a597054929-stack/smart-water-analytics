"""Smoke tests for the agent tools.

These call each tool directly with a representative input. The goal is to
catch schema / signature regressions, not to evaluate LLM behavior.
"""

import json
import os
import sys
from pathlib import Path

# Make agent/ importable as a package
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "pipeline"))

# Set the data dir env var before importing agent modules
os.environ.setdefault("WATER_DATA_DIR", str(ROOT / "backend" / "data" / "output"))


def _ok(out, name):
    """Decode a tool result and assert it's a non-error JSON string."""
    if isinstance(out, str):
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            # Some tools return plain text. That's fine for this smoke test.
            return True
        if isinstance(data, dict) and "error" in data:
            raise AssertionError(f"{name} returned error: {data['error']}")
    return True


def test_query_anomalies():
    from agent.agent_tools import query_anomalies
    out = query_anomalies.invoke({"dma": "Zone-3", "limit": 5})
    _ok(out, "query_anomalies")
    data = json.loads(out)
    assert isinstance(data, list)
    for r in data:
        assert r["dma"] == "Zone-3"


def test_query_anomalies_no_filter():
    from agent.agent_tools import query_anomalies
    out = query_anomalies.invoke({"limit": 3})
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) <= 3


def test_query_meters():
    from agent.agent_tools import query_meters
    out = query_meters.invoke({"dma": "Zone-1", "limit": 5})
    data = json.loads(out)
    assert isinstance(data, list)
    for m in data:
        assert m["dma"] == "Zone-1"


def test_get_anomaly_stats():
    from agent.agent_tools import get_anomaly_stats
    out = get_anomaly_stats.invoke({})
    data = json.loads(out)
    assert "by_dma" in data or "total" in data


def test_get_predictions():
    from agent.agent_tools import get_predictions
    out = get_predictions.invoke({"meter_id": "3586950", "limit": 5})
    data = json.loads(out)
    # Returns a dict with meterId + predictions list
    assert isinstance(data, dict)
    assert "meterId" in data
    assert "predictions" in data or "fitted" in data


def test_get_data_overview():
    from agent.agent_tools import get_data_overview
    out = get_data_overview.invoke({})
    data = json.loads(out)
    assert isinstance(data, dict)


def test_query_consumption_daily():
    from agent.agent_tools import query_consumption
    out = query_consumption.invoke({"mode": "daily", "dma": "Zone-2", "limit": 3})
    data = json.loads(out)
    assert isinstance(data, list)


def test_query_consumption_weekly():
    from agent.agent_tools import query_consumption
    out = query_consumption.invoke({"mode": "weekly"})
    data = json.loads(out)
    assert isinstance(data, list)


def test_query_rank_changes():
    from agent.agent_tools import query_rank_changes
    out = query_rank_changes.invoke({"limit": 3})
    data = json.loads(out)
    assert isinstance(data, list)


def test_query_monthly_diff():
    from agent.agent_tools import query_monthly_diff
    out = query_monthly_diff.invoke({})
    data = json.loads(out)
    assert isinstance(data, list)


def test_sql_query():
    from agent.sql_tools import sql_query
    out = sql_query.invoke({"sql": "SELECT COUNT(*) AS n FROM anomalies"})
    data = json.loads(out)
    assert "columns" in data
    assert "rows" in data
    assert data["row_count"] == 1


def test_sql_query_forbidden():
    from agent.sql_tools import sql_query
    out = sql_query.invoke({"sql": "DROP TABLE anomalies"})
    data = json.loads(out)
    assert "error" in data


def test_list_tables_tool():
    from agent.sql_tools import list_tables_tool
    out = list_tables_tool.invoke({})
    data = json.loads(out)
    assert "tables" in data


def test_get_table_schema_tool():
    from agent.sql_tools import get_table_schema_tool
    out = get_table_schema_tool.invoke({"table_name": "anomalies"})
    data = json.loads(out)
    assert data["table"] == "anomalies"
    assert "columns" in data


def test_get_table_schema_tool_missing():
    from agent.sql_tools import get_table_schema_tool
    out = get_table_schema_tool.invoke({"table_name": "no_such_table"})
    data = json.loads(out)
    assert "error" in data
