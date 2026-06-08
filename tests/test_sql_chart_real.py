"""Unit tests for the agent.sql_chart tool against the REAL database.

These tests use the actual analytics_real.db (path fixed by the
conftest sys.path injection) so they exercise real JOINs and
real column names. They are the regression net for the PLANNER
SQL routing rules: if a rule references a column that doesn't
exist (e.g. "daily_dma.meterId"), these tests catch it.

5 cases:
1. Top N meters in a DMA — uses hourly_meter + meters
2. Building total usage — uses hourly_meter + meters + WHERE LIKE
3. Property type breakdown — uses hourly_meter + meters + GROUP BY
4. Anomaly count by type — uses anomalies table directly
5. Daily DMA trend — uses hourly_meter + meters + date GROUP BY
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure repo root is importable (same bootstrap as conftest.py)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "agent") not in sys.path:
    sys.path.insert(0, str(ROOT / "agent"))

# sql_loader defaults to analytics.db (mock). Point at analytics_real.db
# for these regression tests so the PLANNER rules are tested against
# the real 9,963-meter schema, not the 500-meter mock.
REAL_DB = ROOT / "backend" / "data" / "analytics_real.db"
os.environ["WATER_DB_PATH"] = str(REAL_DB)


def _invoke_sql_chart(sql: str, chart_type: str = "bar", title: str = "test"):
    """Call sql_chart.invoke with a JSON-encoded kwargs dict."""
    from agent.agent_tools import sql_chart
    return json.loads(
        sql_chart.invoke(
            {"sql": sql, "chart_type": chart_type, "title": title}
        )
    )


def test_top_n_meters_in_dma():
    """PLANNER example: 路氹城區前10用水水表."""
    sql = (
        "SELECT m.meterId, m.buildingName, SUM(h.consumption) AS total "
        "FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId "
        "WHERE m.dma='路氹城區' "
        "GROUP BY m.meterId "
        "ORDER BY total DESC LIMIT 10"
    )
    result = _invoke_sql_chart(sql, chart_type="bar", title="路氹城區 Top 10")
    assert "echarts_option" in result
    echarts = result["echarts_option"]
    assert echarts["title"]["text"] == "路氹城區 Top 10"
    # 10 series points
    assert len(echarts["series"][0]["data"]) == 10
    # First (highest) should be > 0
    assert echarts["series"][0]["data"][0] > 0
    # X-axis labels = meterId
    assert len(echarts["xAxis"]["data"]) == 10


def test_building_total_usage():
    """PLANNER example: 永利皇宮 used how much water."""
    sql = (
        "SELECT m.buildingName, SUM(h.consumption) AS total "
        "FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId "
        "WHERE m.buildingName LIKE '%永利皇宮%' "
        "GROUP BY m.buildingName"
    )
    result = _invoke_sql_chart(sql, chart_type="pie", title="永利皇宮总用水")
    echarts = result["echarts_option"]
    # pie should have series type pie
    assert echarts["series"][0]["type"] == "pie"
    # 1 row (1 building matched)
    assert len(echarts["series"][0]["data"]) == 1
    # value should be > 0 (永利皇宮 has 37 meters, all DIRECT)
    assert echarts["series"][0]["data"][0]["value"] > 0


def test_property_type_breakdown():
    """PLANNER example: 住宅 / 商业 / 工业 用水占比."""
    sql = (
        "SELECT m.propertyType, SUM(h.consumption) AS total "
        "FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId "
        "GROUP BY m.propertyType "
        "ORDER BY total DESC"
    )
    result = _invoke_sql_chart(sql, chart_type="pie", title="物业类型用水占比")
    echarts = result["echarts_option"]
    # 5+ property types expected (Entertainment, Hotel, Commercial, etc.)
    assert len(echarts["series"][0]["data"]) >= 3
    # First (largest) should be Entertainment
    assert "Entertainment" in echarts["series"][0]["data"][0]["name"]


def test_anomaly_count_by_type():
    """PLANNER example: 路氹城區异常按类型统计."""
    sql = (
        "SELECT type, COUNT(*) AS cnt "
        "FROM anomalies "
        "WHERE dma='路氹城區' "
        "GROUP BY type "
        "ORDER BY cnt DESC"
    )
    result = _invoke_sql_chart(sql, chart_type="bar", title="路氹城區异常类型")
    echarts = result["echarts_option"]
    # 4 anomaly types expected
    assert len(echarts["series"][0]["data"]) >= 2
    # Each count > 0
    for v in echarts["series"][0]["data"]:
        assert v > 0


def test_daily_dma_trend():
    """PLANNER example: 路氹城區每天用水趋势."""
    sql = (
        "SELECT substr(h.datetime,1,10) AS day, SUM(h.consumption) AS total "
        "FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId "
        "WHERE m.dma='路氹城區' "
        "GROUP BY day "
        "ORDER BY day"
    )
    result = _invoke_sql_chart(sql, chart_type="line", title="路氹城區日用水")
    echarts = result["echarts_option"]
    # line chart
    assert echarts["series"][0]["type"] == "line"
    # 30 days
    assert len(echarts["series"][0]["data"]) == 30
    # Sum should be positive
    assert sum(echarts["series"][0]["data"]) > 0
