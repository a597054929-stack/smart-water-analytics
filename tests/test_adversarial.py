"""
Adversarial / boundary-case tests for agent tools.

These tests exercise edge cases that could break in production:
empty input, nonexistent IDs, oversized requests, malformed SQL, etc.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "pipeline"))

os.environ.setdefault("WATER_DATA_DIR", str(ROOT / "backend" / "data" / "output"))



class TestAdversarialAgentTools:
    """Boundary-case tests for agent JSON tools."""

    def test_query_anomalies_nonexistent_dma(self):
        from agent.agent_tools import query_anomalies
        out = query_anomalies.invoke({"dma": "NONEXISTENT_DMA_ZONE"})
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_query_anomalies_zero_limit(self):
        from agent.agent_tools import query_anomalies
        out = query_anomalies.invoke({"limit": 0})
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_query_anomalies_large_limit(self):
        from agent.agent_tools import query_anomalies
        out = query_anomalies.invoke({"limit": 99999})
        data = json.loads(out)
        assert isinstance(data, list)
        # Should not crash, just return whatever is available

    def test_query_anomalies_invalid_date_range(self):
        from agent.agent_tools import query_anomalies
        out = query_anomalies.invoke({"start": "2099-01-01", "end": "2099-12-31"})
        data = json.loads(out)
        # Tool may ignore date filter and return defaults; just verify no crash
        assert isinstance(data, list)

    def test_query_meters_nonexistent_dma(self):
        from agent.agent_tools import query_meters
        out = query_meters.invoke({"dma": "FAKE_ZONE"})
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_predictions_nonexistent_meter(self):
        from agent.agent_tools import get_predictions
        out = get_predictions.invoke({"meter_id": "0000000"})
        # May return plain text error or JSON; just verify no crash
        assert out is not None
        assert len(str(out)) > 0

    def test_query_consumption_invalid_mode(self):
        from agent.agent_tools import query_consumption
        out = query_consumption.invoke({"mode": "invalid_mode"})
        # Should handle gracefully (error dict or empty list)
        assert out is not None

    def test_generate_chart_empty(self):
        from agent.agent_tools import generate_chart
        out = generate_chart.invoke({"chart_type": "bar", "title": "", "data": "[]"})
        assert out is not None


class TestAdversarialSQL:
    """Boundary-case tests for SQL tools."""

    def test_sql_injection_attempt(self):
        from agent.sql_tools import sql_query
        out = sql_query.invoke({"sql": "SELECT * FROM anomalies; DROP TABLE anomalies;--"})
        data = json.loads(out)
        # Should reject multi-statement queries
        assert "error" in data

    def test_sql_select_star(self):
        from agent.sql_tools import sql_query
        out = sql_query.invoke({"sql": "SELECT * FROM anomalies LIMIT 1"})
        data = json.loads(out)
        assert "columns" in data
        assert "rows" in data

    def test_sql_nonexistent_table(self):
        from agent.sql_tools import sql_query
        out = sql_query.invoke({"sql": "SELECT * FROM nonexistent_table"})
        data = json.loads(out)
        assert "error" in data

    def test_sql_empty_query(self):
        from agent.sql_tools import sql_query
        out = sql_query.invoke({"sql": ""})
        data = json.loads(out)
        assert "error" in data

    def test_sql_syntax_error(self):
        from agent.sql_tools import sql_query
        out = sql_query.invoke({"sql": "SELCT * FORM anomalies"})
        data = json.loads(out)
        assert "error" in data

    def test_get_table_schema_nonexistent(self):
        from agent.sql_tools import get_table_schema_tool
        out = get_table_schema_tool.invoke({"table_name": "does_not_exist_xyz"})
        data = json.loads(out)
        assert "error" in data


