"""
Multi-Agent Architecture — Planner + Executor + Synthesizer

Architecture:
  User Question
      │
      ▼
  ┌──────────────┐
  │  Planner      │  Analyzes question → creates execution plan
  │  (LLM)       │  Output: list of tool calls with parameters
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │  Executor     │  Runs each tool call in sequence
  │  (Tools)      │  Collects all results
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │  Synthesizer  │  Combines results into coherent answer
  │  (LLM)       │  May also generate charts
  └──────────────┘

Interview points:
1. Why multi-agent? → "Separation of planning from execution improves reliability"
2. Why not single agent? → "Single agents sometimes skip steps or call wrong tools"
3. How does planning help? → "Explicit plan can be validated before execution"
"""

import sys, json
sys.stdout.reconfigure(encoding="utf-8")

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from config import get_llm_config
from agent_tools import ALL_TOOLS


# ── Tool Registry ─────────────────────────────────────────────

TOOL_REGISTRY = {tool.name: tool for tool in ALL_TOOLS}


# ── Planner ───────────────────────────────────────────────────

PLANNER_PROMPT = """You are a planning agent. Your job is to analyze the user question
and create a structured execution plan.

Given the user question, you may either output a JSON array of tool
calls to execute, OR a single clarify object to ask the user for
missing information.

If proceeding with tools, each tool call is:
    {"tool": "tool_name", "params": {"param": "value"}}

If asking back, return a single JSON object:
    {"action": "clarify", "question": "<Chinese question>",
     "options": ["opt1", "opt2", ...], "default": "opt1"}

Available tools:
- query_anomalies(dma, month, anomaly_type, limit)
- query_meters(dma, is_residential, building, limit)
- get_anomaly_stats(month, dma)
- get_predictions(meter_id, limit)
- get_building_predictions(building, limit)
- get_data_overview()
- sql_chart(sql, chart_type, title, x_column, y_column, y_label)   # SQL + chart in one call (bar/line/pie)
- query_consumption(mode, date, dma, month1, month2, limit)   # daily/weekly/compare
- query_weekly()
- query_rank_changes(limit)
- query_monthly_diff(month)
- sql_chart(sql, chart_type, title, x_column, y_column, y_label)   # SQL + chart in one call (bar/line/pie)
  *** USE THIS for ANY chart that requires custom data (top-N, building totals, trends, etc.) ***
- generate_chart(chart_type, dma, days)   # FIXED chart types ONLY: "weekly_trend" / "anomaly_by_dma" / "anomaly_type" / "daily_usage"
  *** DO NOT use generate_chart for custom data or arbitrary queries — use sql_chart instead ***
- compare_months(month1, month2, dma)
- analyze_anomaly(meter_id)
- generate_report(dma, month)
- query_data_quality(date, meter_id, reason)

Database schema (analytics_real.db — 10 tables, copy these column names):
- meters: meterId, id, contractId, propertyType, isResidential, buildingName, dma, supplyMode, mainCode
  (Use meters for: DMA, building, property type of a meter)
- hourly_meter: meterId, datetime, consumption, reading   (30 days, hourly granularity)
  (Use hourly_meter for: per-meter time series, JOIN meters to get names)
- daily_dma: date, dma, total, residential, nonResidential, resCount, nonResCount, meterCount, rain
  *** NOTE: daily_dma does NOT have meterId — it's aggregated at DMA level ***
  (Use daily_dma for: total consumption per DMA per day, never per meter)
- weekly: weekStart, weekEnd, label, dates, totalByDma, grandTotal, weekdayAvg, weekendAvg, wdByDmaRes
  (Use weekly for: weekly summary, weather correlation)
- monthly_diff: month, mainMeterId, mainContractId, mainBuilding, dma, subs, mainTotal, subsTotal, diff, diffPercent
  (Use monthly_diff for: main-sub meter NRW, monthly reconciliation)
- anomalies: date, meterId, total, contractId, dma, buildingName, reason, type, anomalyScore, pastMean, pastStd, windowDays
  (Use anomalies for: per-anomaly records with reason text + score)
- rank_changes: meterId, contractId, buildingName, dma, propertyType, daysInTop20, avgTotal, avgRank, trend
  (Use rank_changes for: top-N meters by usage in a DMA, ranking, long-term top20)
- predictions: meterId, date, predicted, lower, upper
  (Use predictions for: per-meter 7-day forecast)
- predictions_building: building, date, predicted, lower, upper
  (Use predictions_building for: per-building 7-day forecast)
- search_index: id, contract, building, dma, type
  (Use search_index for: fuzzy lookup by contract/building)
- data_errors (read via JSON tools, not SQL): dropped meter-day records

Common JOIN patterns:
- meters + hourly_meter (on meterId): per-meter time series with names
- meters + anomalies (on meterId): anomalies with building/property context
- meters + daily_dma (on dma): NOT possible — daily_dma has no meterId
- For per-meter daily usage: aggregate hourly_meter by date

Rules (tool selection):
- Output ONLY the JSON array, no other text
- Include only tools relevant to the question
- Set reasonable parameter defaults if not specified
- For comparison questions, include compare_months
- For investigation questions, include analyze_anomaly
- Always end with generate_report if the user asks for a summary
- NEVER use generate_chart for custom data queries. generate_chart
  only supports 4 hardcoded types: weekly_trend, anomaly_by_dma,
  anomaly_type, daily_usage. For ANY other chart (top-N, building
  totals, trends by meter, property breakdown) use sql_chart.
  WRONG: generate_chart(chart_type="bar")  ← will return error
  RIGHT: sql_chart(sql="SELECT ...", chart_type="bar", ...)

Tool call budget (soft hints — execution layer enforces hard limits):
- **Don't repeat the same tool call** — if you already called
  query_anomalies(dma="路氹城區"), don't call it again with the
  same params. The executor dedupes by (tool, params) anyway.
- **Don't re-query schema** — all 10 table schemas are listed
  above. Don't call list_tables_tool or get_table_schema_tool
  unless you genuinely need a column you don't see.
- **Don't cross-validate** — once you got an answer from
  query_anomalies, don't also call get_data_overview to "double
  check" the same number. Data is stable within a 30-min window.
- **Aim for 1-3 tool calls per question** — multi-tool plans
  are fine for multi-step reasoning (compare 2 months needs 2
  queries), but avoid calling the same query 5+ times.

SQL ROUTING — when to use sql_query instead of JSON tools:
Use sql_query when the question needs cross-table JOINs, custom GROUP BY,
ORDER BY, LIMIT, or time granularity finer than the pre-aggregated JSONs.

SQL examples (copy these patterns):
- Top N meters by usage in a DMA:
  sql_query("SELECT m.meterId, m.buildingName, SUM(h.consumption) AS total FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId WHERE m.dma='路氹城區' GROUP BY m.meterId ORDER BY total DESC LIMIT 10")

- Building total usage:
  sql_query("SELECT m.buildingName, SUM(h.consumption) AS total FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId WHERE m.buildingName LIKE '%永利皇宮%' GROUP BY m.buildingName")

- Property type breakdown:
  sql_query("SELECT m.propertyType, SUM(h.consumption) AS total FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId GROUP BY m.propertyType ORDER BY total DESC")

- Anomaly count by type:
  sql_query("SELECT type, COUNT(*) AS cnt FROM anomalies WHERE dma='路氹城區' GROUP BY type ORDER BY cnt DESC")

- Anomalies in a month:
  sql_query("SELECT COUNT(*) AS cnt FROM anomalies WHERE dma='路氹城區' AND date LIKE '2026-05%'")

- Daily trend for a DMA:
  sql_query("SELECT substr(h.datetime,1,10) AS day, SUM(h.consumption) AS total FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId WHERE m.dma='路氹城區' GROUP BY day ORDER BY day")

- Single meter daily usage:
  sql_query("SELECT substr(h.datetime,1,10) AS day, SUM(h.consumption) AS total FROM hourly_meter h WHERE h.meterId='711758' GROUP BY day ORDER BY day")

- Top anomalies by score:
  sql_query("SELECT meterId, buildingName, anomalyScore, type, date FROM anomalies WHERE dma='路氹城區' ORDER BY anomalyScore DESC LIMIT 10")

- Fire system usage:
  sql_query("SELECT m.propertyType, SUM(h.consumption) AS total FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId WHERE m.propertyType LIKE '%Fire%' GROUP BY m.propertyType")

CHART ROUTING — when user asks for a chart / graph / 图:
- "路氹城區前10用水柱状图"  →  sql_chart(sql="SELECT m.meterId, ... ORDER BY total DESC LIMIT 10", chart_type="bar", title="路氹城區 Top 10 用水", y_label="m³")
- "物业类型用水饼图"       →  sql_chart(sql="SELECT m.propertyType, ... GROUP BY m.propertyType", chart_type="pie", title="物业类型用水占比")
- "路氹城區日用水趋势图"   →  sql_chart(sql="SELECT substr(h.datetime,1,10) AS day, ... GROUP BY day", chart_type="line", title="路氹城區日用水趋势", y_label="m³")
- "周趋势图" (fixed)       →  generate_chart(chart_type="weekly_trend", dma="路氹城區")
- "异常类型分布图" (fixed) →  generate_chart(chart_type="anomaly_type")

Example (chart):
User: 路氹城區前10用水量的水表柱状图
Output: [{"tool": "sql_chart", "params": {"sql": "SELECT m.meterId, m.buildingName, SUM(h.consumption) AS total FROM hourly_meter h JOIN meters m ON h.meterId=m.meterId WHERE m.dma='路氹城區' GROUP BY m.meterId ORDER BY total DESC LIMIT 10", "chart_type": "bar", "title": "路氹城區 Top 10 用水水表", "x_column": "meterId", "y_column": "total", "y_label": "m³"}}]

Use JSON tools when the pre-aggregated files already cover the query:
- query_anomalies: anomaly list/stats for a DMA+month
- query_meters: meter metadata search
- get_anomaly_stats: anomaly summary by DMA/type
- get_predictions / get_building_predictions: forecast data
- query_consumption: daily/weekly/compare (uses weekly.json + daily_dma.json)
- query_rank_changes: top50 ranking changes (by daysInTop20, avgTotal, trend)
- query_monthly_diff: main-sub meter NRW diff
- get_data_overview: overall statistics (only for vague "show me everything")
- generate_chart: fixed chart types only (weekly_trend, anomaly_by_dma, anomaly_type, daily_usage)
- generate_report: text summary
- sql_chart: use when user wants a chart FROM SQL data (e.g. "柱状图" + custom query)

Tool selection rules (specific common cases):
- "前N水表 / Top N meters by usage" (短期, e.g. 最近 30 天):
  USE sql_query with hourly_meter + meters JOIN
- "前N水表 / Top N meters by long-term ranking" (长期, e.g. 排名变化):
  USE query_rank_changes (pre-aggregated rank_changes.json, has daysInTop20 + avgTotal)
- "建筑粒度用水趋势" (per-building): USE daily_dma JOIN meters (aggregate by buildingName)
- "水表粒度日用量" (per-meter daily): USE hourly_meter GROUP BY date
- "周趋势图" (weekly trend): USE query_consumption(mode="weekly") — pre-aggregated, faster
- "月度对比" (month compare): USE compare_months — pre-aggregated
- "前10建筑用水" (top buildings): USE sql_query with GROUP BY buildingName
- "物业类型用水占比" (property type): USE sql_query with GROUP BY propertyType
- "NRW / 主分表差": USE query_monthly_diff — pre-aggregated, no SQL needed
- "异常分析" (anomaly deep-dive): USE analyze_anomaly (single meter) or query_anomalies (list)

When to ask back (clarify instead of guessing):
- The user asks 查异常 / 查数据 / 查表 but does not specify DMA,
  time period, or meter ID.
- The user question is materially ambiguous: different choices lead
  to different tools or different answers.
- The user references this week / current zone / the meter we discussed
  without context being available in PAGE CONTEXT.

How to ask back:
- Return a SINGLE JSON object (not an array of tool calls):
  {"action": "clarify",
   "question": "你想查哪个区域、哪个时段的异常？\n1) 澳門低區\n2) 澳門填海A區\n3) 澳大橫琴區\n4) 路氹城區\n默认：路氹城區（最近 30 天）",
   "options": ["澳門低區", "澳門填海A區", "澳大橫琴區", "路氹城區"],
   "default": "路氹城區"}
- question field uses natural language (not a form-like prompt)
- Always include a default time period (e.g. "最近 30 天" or "5 月")
- Provide 2-4 numbered options
- Mark the most likely as default
- Hard cap: 1 question covering ALL missing dimensions
- DMA names are always the 4 real Macau names below, never abbreviations.

When to ask back (clarify instead of guessing):
- Always include a default time period (e.g., "最近 30 天" or "5 月").
  Don't make the user specify time if they forgot — just default to
  recent data and say so in the question.
- Cover ALL missing dimensions in one question (DMA + time + meter if
  applicable). Do not split into multiple clarification turns.

When NOT to ask back:
- The question is clear (e.g., 查澳門低區的异常 - DMA is specified, proceed).
- The ambiguity is minor (e.g., 上周 - assume previous 7 days,
  proceed with parenthetical assuming last 7 days).

DMA zones (use these exact names, never abbreviations):
- 澳門低區
- 澳門填海A區
- 澳大橫琴區
- 路氹城區
- If the user says 氹仔/路氹/路環, map to 路氹城區.
- If the user says 澳門, map to 澳門低區.

Example (clarify):
User: 查异常
Output: {"action": "clarify",
         "question": "你想查哪个区域、哪个时段的异常？\n1) 澳門低區\n2) 澳門填海A區\n3) 澳大橫琴區\n4) 路氹城區\n默认：路氹城區（最近 30 天）",
         "options": ["澳門低區", "澳門填海A區", "澳大橫琴區", "路氹城區"],
         "default": "路氹城區"}

Example (proceed):
User: 查澳門低區异常
Output: [{"tool": "get_anomaly_stats", "params": {"dma": "澳門低區"}},
         {"tool": "query_anomalies", "params": {"dma": "澳門低區", "limit": 10}}]
"""


def create_planner():
    cfg = get_llm_config()
    llm = ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        temperature=0,
        max_tokens=1024,
    )
    return llm


def plan(question: str, llm) -> dict:
    """Generate an execution plan OR a clarify request.

    Returns a dict in one of two shapes:
      - {"action": "plan", "steps": [...]}             (normal case)
      - {"action": "clarify", "question": "...",
        "options": [...], "default": "..."}            (ask back)
    """
    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=question),
    ]
    response = llm.invoke(messages)
    content = response.content

    # Extract text from content (handles list-type content blocks)
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )

    # Try to parse as a JSON object first (might be a clarify response
    # or an explicit {"action": "plan", "steps": [...]} envelope).
    try:
        obj = json.loads(content.strip())
        if isinstance(obj, dict):
            if obj.get("action") == "clarify":
                return {
                    "action": "clarify",
                    "question": obj.get("question", ""),
                    "options": obj.get("options", []),
                    "default": obj.get("default"),
                }
            if obj.get("action") == "plan":
                return {"action": "plan", "steps": obj.get("steps", [])}
            # Bare dict without action - treat as a single tool call
            if "tool" in obj and "params" in obj:
                return {"action": "plan", "steps": [obj]}
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    # Fall back to parsing as a JSON array (legacy format)
    start = content.find("[")
    end = content.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            steps = json.loads(content[start:end])
            if isinstance(steps, list):
                return {"action": "plan", "steps": steps}
        except json.JSONDecodeError:
            pass

    # Final fallback: single overview query
    return {"action": "plan", "steps": [{"tool": "get_data_overview", "params": {}}]}


# ── Executor ──────────────────────────────────────────────────

def execute(plan_steps: list, max_tools: int = 8, max_consecutive_failures: int = 2) -> list:
    """Execute a plan by calling tools in sequence.

    Three execution-layer guards (P0 fixes from 2026-06-09):
    1. Dedup by (tool_name, frozenset(params)) — LLM sometimes
       repeats the same call (e.g. "query_anomalies dma=路氹城區"
       called 10 times for the same question). Different params
       like dma=路氹城區 vs dma=澳大橫琴區 are NOT deduped.
    2. Circuit breaker — if max_consecutive_failures tools in a row
       all error, abort the rest of the plan. Avoids burning 20+
       tool calls on a broken plan.
    3. Hard cap on total tools (max_tools) — prevents runaway plans
       from N>M where the LLM hallucinates dozens of steps.
    """
    results = []
    called: set = set()
    consecutive_failures = 0

    for step in plan_steps:
        # Hard cap: stop if we've already executed too many tools
        if len(results) >= max_tools:
            results.append({
                "tool": "_executor",
                "skipped": f"hit max_tools={max_tools} cap"
            })
            break

        # Defensive: handle string steps (LLM sometimes returns ["tool1", "tool2"])
        if isinstance(step, str):
            step = {"tool": step, "params": {}}
        tool_name = step.get("tool", "")
        params = step.get("params", {})

        # Dedup: skip if (tool, params) already called
        sig = (tool_name, tuple(sorted(params.items())))
        if sig in called:
            results.append({"tool": tool_name, "skipped": "duplicate call"})
            continue
        called.add(sig)

        if tool_name not in TOOL_REGISTRY:
            results.append({"tool": tool_name, "error": f"Unknown tool: {tool_name}"})
            consecutive_failures += 1
        else:
            try:
                tool = TOOL_REGISTRY[tool_name]
                # LangChain @tool-decorated functions: invoke() accepts either
                # positional input (str) or a dict unpacked as kwargs. Pass via
                # `input=` so the dict is always treated as kwargs, never a
                # raw string. (Fixes 'str' object has no attribute 'get'.)
                output = tool.invoke(input=params)
                results.append({"tool": tool_name, "result": output})
                consecutive_failures = 0
            except Exception as e:
                results.append({"tool": tool_name, "error": str(e)})
                consecutive_failures += 1

        # Circuit breaker: too many consecutive failures -> stop
        if consecutive_failures >= max_consecutive_failures:
            results.append({
                "tool": "_executor",
                "skipped": f"circuit breaker: {consecutive_failures} consecutive failures"
            })
            break

    return results


# ── Synthesizer ───────────────────────────────────────────────

SYNTHESIZER_PROMPT = """You are a data synthesis agent. You receive raw tool results
and must combine them into a clear, helpful answer for the user.

Rules:
- Answer in the same language as the original question
- Include specific numbers and dates from the data
- Highlight key insights and trends
- If charts were generated, mention them
- If data is missing or errors occurred, acknowledge it
- Keep the answer concise but informative
- For anomaly scores: 0.7+ is concerning, 0.5+ is notable
"""


def synthesize(question: str, plan_steps: list, results: list, llm) -> str:
    """Combine plan + results into a final answer."""
    context = f"User question: {question}\n\n"
    context += "Execution plan:\n"
    for step in plan_steps:
        context += f"  - {step.get('tool')}({json.dumps(step.get('params', {}))})\n"

    context += "\nTool results:\n"
    for r in results:
        if "error" in r:
            context += f"  [{r['tool']}] ERROR: {r['error']}\n"
        else:
            # Truncate long results
            result_str = r["result"]
            if len(result_str) > 2000:
                result_str = result_str[:2000] + "... (truncated)"
            context += f"  [{r['tool']}] {result_str}\n"

    messages = [
        SystemMessage(content=SYNTHESIZER_PROMPT),
        HumanMessage(content=context),
    ]
    response = llm.invoke(messages)
    content = response.content
    if isinstance(content, list):
        content = " ".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content


# ── Main Pipeline ─────────────────────────────────────────────

def run_multi_agent(question: str, context: dict | None = None) -> dict:
    """Run the full multi-agent pipeline: Plan → Execute → Synthesize.

    Args:
        question: the user's natural-language question.
        context: optional page state from the frontend
                 ({active_tab, selected_date, selected_dma, ...}).
                 When provided, the planner and synthesizer see it
                 so they can resolve references like "this week".
    """
    cfg = get_llm_config()
    llm = ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        temperature=0,
        max_tokens=2048,
    )

    # Prepend the page context to the question, if any. Both the planner
    # and the synthesizer read the question, so this single injection
    # covers both.
    augmented_question = question
    if context:
        ctx_lines = ["[PAGE CONTEXT] The user is currently viewing:"]
        for k, v in context.items():
            if v is None or v == "":
                continue
            ctx_lines.append(f"  - {k}: {v}")
        ctx_lines.append(
            "Use this to resolve references like 'this week' or 'current zone'."
        )
        augmented_question = "\n".join(ctx_lines) + "\n\nUser question: " + question

    # Step 1: Plan (may return a clarify request instead of tool steps)
    plan_result = plan(augmented_question, llm)
    if not isinstance(plan_result, dict):
        # Defensive: plan() should always return a dict, but if it doesn't
        # (e.g. a future code path breaks the contract), degrade safely.
        plan_result = {"action": "plan", "steps": [{"tool": "get_data_overview", "params": {}}]}

    # Ask-back path: return immediately, no executor, no synthesizer.
    # This saves 2 LLM calls per clarify turn and avoids hallucinated
    # answers when the user question is materially ambiguous.
    if plan_result.get("action") == "clarify":
        return {
            "answer": plan_result.get("question", ""),
            "chart": None,
            "plan": [],
            "tools_called": [],
            "clarify": {
                "options": plan_result.get("options", []),
                "default": plan_result.get("default"),
            },
        }

    plan_steps = plan_result.get("steps", [])

    # Step 2: Execute
    results = execute(plan_steps)

    # Step 3: Synthesize
    answer = synthesize(augmented_question, plan_steps, results, llm)

    # Check for charts in results
    chart = None
    for r in results:
        if "result" in r:
            try:
                data = json.loads(r["result"])
                if isinstance(data, dict) and "echarts_option" in data:
                    chart = data["echarts_option"]
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "answer": answer,
        "chart": chart,
        "plan": plan_steps,
        "tools_called": [r["tool"] for r in results if "result" in r],
    }


# ── CLI ───────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Smart Water Multi-Agent")
    parser.add_argument("--question", "-q", type=str, help="Ask a question")
    args = parser.parse_args()

    if args.question:
        result = run_multi_agent(args.question)
        if result.get("clarify"):
            print(f"\nClarify: {result['answer']}")
            print(f"Options: {result['clarify']['options']}")
            print(f"Default: {result['clarify'].get('default')}")
        else:
            print(f"\nPlan: {json.dumps(result['plan'], indent=2)}")
            print(f"Tools called: {result['tools_called']}")
            print(f"\nAnswer:\n{result['answer']}")
        return

    print("Multi-Agent Smart Water Assistant")
    print("=" * 60)
    print("Example questions:")
    print("  - Compare March and April consumption")
    print("  - Investigate meter 1234567 anomalies")
    print("  - Generate a Zone-3 monthly report")
    print("  - Type 'quit' to exit\n")

    while True:
        q = input("Question: ").strip()
        if q.lower() in ("quit", "exit", "q"):
            break
        if not q:
            continue
        result = run_multi_agent(q)
        print(f"\nPlan: {[s['tool'] for s in result['plan']]}")
        print(f"Answer:\n{result['answer']}\n")


if __name__ == "__main__":
    main()
