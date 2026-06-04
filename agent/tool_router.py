"""Rule-based tool router — pre-selects likely tools from the user's question.

Reduces LLM decision overhead by injecting tool recommendations into the
system message. No embedding model needed — pure keyword matching.
"""

import re


# ── Rules: keyword patterns → (tool_name, suggested_params, weight) ──

_RULES = [
    # Anomaly queries
    (r"异常|anomal|spike|drop|zero|watch|警报|alert|漏水|漏损",
     "query_anomalies", {"mode": "list"}, 1.0),
    (r"异常.*(统计|汇总|概览|overview|多少|count|分布)",
     "query_anomalies", {"mode": "stats"}, 1.2),
    (r"分析|investigate|深入|deep.?dive|原因|cause",
     "query_anomalies", {"mode": "analyze"}, 1.2),

    # Consumption queries (check compare/weekly BEFORE daily to avoid duplicate tool)
    (r"同比|对比|compare|环比|比.*月",
     "query_consumption", {"mode": "compare"}, 1.2),
    (r"周|weekly|week|一周|上周|本周",
     "query_consumption", {"mode": "weekly"}, 1.0),
    (r"用水|consumption|用量|usage|水量",
     "query_consumption", {"mode": "daily"}, 0.8),

    # Predictions
    (r"预测|predict|forecast|预估|未来|下周|next.?week",
     "get_predictions", {"query_type": "meter"}, 1.0),
    (r"建筑|building|酒店|hotel|度假村|resort.*预测",
     "get_predictions", {"query_type": "building"}, 1.1),

    # Meter lookup
    (r"水表|meter|建筑.*信息|building.*info",
     "query_meters", {}, 0.8),

    # NRW / water loss
    (r"NRW|漏损率|水损|主分表|main.?sub|water.?loss",
     "query_monthly_diff", {}, 1.0),

    # Rankings
    (r"排名|rank|top.?20|最高|highest|用水量.*最多",
     "query_rank_changes", {}, 0.9),

    # Reports
    (r"报告|report|总结|summary|综合",
     "generate_report", {}, 1.0),

    # Charts
    (r"图表|chart|可视化|visualization|画图|graph|曲线",
     "generate_chart", {}, 1.0),

    # Data overview
    (r"总览|overview|数据.*概况|多少.*水表|系统|data.*summary",
     "get_data_overview", {}, 0.9),

    # SQL preferred (precise queries)
    (r"top.?N|排名前|最多的|sum|avg|average|count|聚合|精确|precise",
     "sql_query", {}, 1.1),
]

# DMA zone extraction pattern
_DMA_PATTERN = re.compile(r"Zone[-\s]?(\d+)", re.IGNORECASE)

# Month extraction patterns
_MONTH_PATTERN = re.compile(r"(20\d{2})[-/](0[1-9]|1[0-2])")
_MONTH_CN_PATTERN = re.compile(r"(\d{1,2})月")


def route_question(question: str) -> list[dict]:
    """Analyze a question and return recommended tools with parameters.

    Returns a list of dicts: [{"tool": name, "params": {...}, "weight": float}]
    sorted by weight descending. Empty list means no strong signal.
    """
    results = []
    seen_tools = set()

    for pattern, tool_name, base_params, weight in _RULES:
        if re.search(pattern, question, re.IGNORECASE):
            if tool_name not in seen_tools:
                params = dict(base_params)

                # Auto-fill DMA if mentioned
                dma_match = _DMA_PATTERN.search(question)
                if dma_match and "dma" not in params:
                    params["dma"] = f"Zone-{dma_match.group(1)}"

                # Auto-fill months for compare mode
                if params.get("mode") == "compare":
                    # Try full date format first, then Chinese format
                    months = _MONTH_PATTERN.findall(question)
                    if not months:
                        cn_months = _MONTH_CN_PATTERN.findall(question)
                        if cn_months:
                            from datetime import date
                            year = date.today().year
                            months = [(str(year), m.zfill(2)) for m in cn_months]
                    if len(months) >= 2:
                        params["month1"] = f"{months[0][0]}-{months[0][1]}"
                        params["month2"] = f"{months[1][0]}-{months[1][1]}"
                    elif len(months) == 1:
                        y, m = int(months[0][0]), int(months[0][1])
                        if m == 1:
                            params["month1"] = f"{y-1}-12"
                        else:
                            params["month1"] = f"{y}-{m-1:02d}"
                        params["month2"] = f"{months[0][0]}-{months[0][1]}"

                # Auto-fill month for other tools
                if "month" not in params and "month1" not in params:
                    month_match = _MONTH_PATTERN.search(question)
                    if month_match:
                        params["month"] = f"{month_match.group(1)}-{month_match.group(2)}"
                    else:
                        cn_match = _MONTH_CN_PATTERN.search(question)
                        if cn_match:
                            from datetime import date
                            params["month"] = f"{date.today().year}-{cn_match.group(1).zfill(2)}"

                results.append({"tool": tool_name, "params": params, "weight": weight})
                seen_tools.add(tool_name)

    # Sort by weight descending
    results.sort(key=lambda x: -x["weight"])
    return results[:3]  # Top 3 recommendations


def format_tool_hint(recommendations: list[dict]) -> str:
    """Format tool recommendations as a hint for the system message."""
    if not recommendations:
        return ""

    lines = ["[TOOL HINT] Based on the question, consider using:"]
    for rec in recommendations:
        params_str = ", ".join(f"{k}={v}" for k, v in rec["params"].items()) if rec["params"] else "no params"
        lines.append(f"  - {rec['tool']}({params_str})")
    return "\n".join(lines)
