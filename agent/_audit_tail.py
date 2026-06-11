"""Real-time tail for logs/tool_audit.log with pretty formatting.

Prints each tool call as the agent makes it, mirroring the format used
in reports/eval_per_qa.json so the operator can see exactly which tools
the LLM is calling and how long each takes.

Usage:
  python _audit_tail.py

The script polls the audit log every 250ms. On Windows this is the
simplest cross-version way to get tail -f semantics without depending
on Unix-only `tail -f` or PowerShell Get-Content -Wait quirks.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent / "logs" / "tool_audit.log"
POLL_MS = 250
TOOL_CN = {
    "query_anomalies": "查异常",
    "query_meters": "查水表",
    "get_anomaly_stats": "异常统计",
    "get_predictions": "取预测",
    "get_data_overview": "数据总览",
    "query_consumption": "查用水",
    "query_rank_changes": "查排名",
    "query_monthly_diff": "查主分表差",
    "sql_query": "SQL 查询",
    "sql_chart": "SQL 出图",
    "generate_chart": "出图",
    "analyze_anomaly": "异常分析",
    "generate_report": "生成报告",
    "query_data_quality": "查数据质量",
    "get_table_schema_tool": "查表结构",
    "list_tables_tool": "列表",
    "get_current_page_context": "取页面状态",
}


def _color(s: str, code: str) -> str:
    """ANSI color (works in Windows 10+ Terminal / VSCode integrated)."""
    return f"\033[{code}m{s}\033[0m"


def _fmt_line(entry: dict) -> str:
    ts = entry.get("ts", "")[11:19]  # HH:MM:SS
    tool = entry.get("tool", "?")
    name = TOOL_CN.get(tool, tool)
    dur = entry.get("duration_ms", 0)
    ok = entry.get("success", True)
    err = entry.get("error")
    params = entry.get("params_keys", [])
    nbytes = entry.get("output_bytes", 0)

    status = _color("OK", "32") if ok else _color("FAIL", "31")
    icon = _color("✓", "32") if ok else _color("✗", "31")
    pstr = ",".join(params) if params else "—"

    line = f"{_color(ts, '90')}  {icon} {name:<14}  {status}  {_color(f'{dur:>4}ms', '33')}  {pstr[:30]:<30}  {nbytes}B"
    if err:
        line += f"  {_color('err: ' + str(err)[:50], '31')}"
    return line


def main() -> int:
    if not LOG.parent.exists():
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.touch()

    print(_color("═══ Tool Audit (real-time) ═══", "36;1"))
    print(_color(f"watching: {LOG}", "90"))
    print(_color("press Ctrl+C to stop\n", "90"))

    pos = LOG.stat().st_size
    last_rotate_check = time.time()

    while True:
        try:
            cur_size = LOG.stat().st_size

            # Log rotation: if file shrunk, start over from beginning.
            if cur_size < pos:
                pos = 0

            if cur_size > pos:
                with LOG.open("r", encoding="utf-8") as f:
                    f.seek(pos)
                    new_data = f.read()
                    pos = f.tell()

                for raw in new_data.splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                        print(_fmt_line(entry))
                        sys.stdout.flush()
                    except json.JSONDecodeError:
                        pass  # partial line, will be re-read on next poll

            time.sleep(POLL_MS / 1000)

        except KeyboardInterrupt:
            print(_color("\nstopped", "36"))
            return 0
        except FileNotFoundError:
            time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
