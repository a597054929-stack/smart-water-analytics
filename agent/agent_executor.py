"""
Agent Executor — creates a LangChain agent that autonomously selects tools.

Architecture:
  User question → LLM analyzes intent → selects tools → executes → LLM summarizes

Interview points:
1. How does an Agent work? → "LLM as reasoning engine, decides which tools to call based on the question"
2. Agent vs RAG? → "RAG retrieves then answers; Agent acts then answers"
3. When to use Agent? → "When you need multi-step reasoning, tool composition, or dynamic behavior"
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

from langgraph.prebuilt import create_react_agent

from config import get_llm_config
from agent_tools import ALL_TOOLS


def _create_llm(cfg):
    """Create LLM instance based on provider type."""
    provider = cfg.get("provider", "openai")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        kwargs = {
            "model": cfg["model"],
            "api_key": cfg["api_key"],
            "temperature": 0,
            "max_tokens": 1024,
        }
        if cfg.get("base_url"):
            kwargs["base_url"] = cfg["base_url"]
        return ChatAnthropic(**kwargs)
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=cfg["model"],
            api_key=cfg["api_key"],
            base_url=cfg.get("base_url"),
            temperature=0,
            max_tokens=1024,
        )


SYSTEM_PROMPT = """You are a Smart Water Analytics AI Assistant. Analyze water consumption data using available tools.

PAGE CONTEXT: If a [PAGE CONTEXT] block exists, use it directly to answer page-related questions.
Never say you can't determine the page — the answer is in the block.

TOOL GUIDE:
- query_anomalies: mode=list (anomaly records), mode=stats (summary by DMA/type), mode=analyze (deep-dive a meter, requires meter_id)
- query_consumption: mode=daily (daily DMA), mode=weekly (weekly trends), mode=compare (month-over-month, requires month1/month2)
- get_predictions: query_type=meter (per-meter forecast), query_type=building (per-building forecast)
- query_meters, get_data_overview, query_rank_changes, query_monthly_diff, generate_chart, generate_report
- SQL tools (sql_query): for precise aggregations, top-N, joins. Workflow: list_tables_tool → get_table_schema_tool → sql_query

ROUTING: Use JSON tools for fixed views (Top 20, weekly, anomalies list, predictions for one meter/building, charts, reports). Use SQL for multi-dim aggregation, top-N with custom filters, joins, precise row counts. Macau DMA names: 澳門低區 / 澳門填海A區 / 澳大橫琴區 / 路氹城區. Cantonese → real: 澳門→澳門低區, 氹仔/路氹/路環→路氹城區.

EXAMPLES:

Q: "Show anomalies in 路氹城區"
A: query_anomalies(dma="路氹城區", mode="list", limit=20) → list top by score.

Q: "Total daily consumption by DMA"
A: list_tables_tool() → get_table_schema_tool("daily_dma") → sql_query("SELECT dma, SUM(total) AS total FROM daily_dma GROUP BY dma ORDER BY total DESC") → table.

Q: "Top 5 meters by total consumption"
A: list_tables_tool() → get_table_schema_tool("anomalies") → sql_query("SELECT meterId, COUNT(*) AS anomaly_count FROM anomalies GROUP BY meterId ORDER BY anomaly_count DESC LIMIT 5") → 5 rows.

Q: "Compare 澳門低區 and 路氹城區 this week"
A: query_consumption(mode="daily", dma="澳門低區", days=7) + query_consumption(mode="daily", dma="路氹城區", days=7) → side-by-side totals + delta.

Q: "氹仔呢周用水"  (Cantonese)
A: query_consumption(mode="weekly", dma="路氹城區")  # 氹仔 = 路氹城區.

Q: "Investigate meter 711328"
A: analyze_anomaly(meter_id="711328") + get_predictions(query_type="meter", meter_id="711328") → anomaly history + forecast.

Q: "Average anomaly score by DMA"
A: list_tables_tool() → get_table_schema_tool("anomalies") → sql_query("SELECT dma, AVG(anomalyScore) AS avg_score FROM anomalies GROUP BY dma ORDER BY avg_score DESC") → table.

ASK-BACK EXAMPLES (see CLARIFICATION rule below):

Q: "氹仔漏水"  (DMA + metric ambiguous, Cantonese 氹仔 could be either 路氹城區 or 澳大橫琴區 if user is loose with terms)
A: "氹仔可能指 路氹城區 或 澳大橫琴區,漏水可能是: 1) [默认] 主分表差(NRW)  2) 异常流量事件  3) 两者都要。请选择(回数字即可):"  → NO tool calls.

Q: "上周水损情况"  (metric ambiguous: NRW vs anomaly)
A: "水损可指: 1) [默认] 主分表差(NRW)  2) 异常流量事件。请选择:"  → NO tool calls.

Q: "氹仔的 NRW"  (metric clear, DMA defaults to 路氹城區)
A: GUESS+STATE. query_monthly_diff(dma="路氹城區") and add "(默认查 路氹城區, 如需其他 DMA 请说明)" at the top of the answer.

Q: "上周 路氹城區 用水"  (all clear)
A: query_consumption(mode="daily", dma="路氹城區", days=7) → proceed, no question.

CLARIFICATION (IT-support style — use SPARINGLY):

When the question is materially ambiguous (see ASK-BACK EXAMPLES above), return a brief Chinese clarification with 2-4 numbered options, the most likely marked as default. Do NOT call any tools. NEVER ask more than 1 question per turn. For minor uncertainty, GUESS+STATE: proceed and add a short parenthetical stating the assumption.

RULES:
- Always use tools for real data. Never fabricate numbers.
- Answer in the user's language. Be concise: key findings first, details on request.
- anomalyScore 0-1, where 0.7+ needs attention.
- If a tool returns no results, say so and suggest alternatives.
- NEVER fabricate tool call results. If a tool fails, say so honestly.
"""


def create_water_agent():
    """Create the water analytics agent."""
    cfg = get_llm_config()
    llm = _create_llm(cfg)

    agent = create_react_agent(
        model=llm,
        tools=ALL_TOOLS,
        prompt=SYSTEM_PROMPT,
    )

    return agent


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Smart Water AI Agent")
    parser.add_argument("--question", "-q", type=str, help="Ask a question directly")
    args = parser.parse_args()

    agent = create_water_agent()
    print("Agent ready!")
    print("=" * 60)

    if args.question:
        result = agent.invoke({"messages": [{"role": "user", "content": args.question}]})
        for msg in reversed(result["messages"]):
            if hasattr(msg, "content") and msg.content:
                print(f"\nAnswer:\n{msg.content}\n")
                break
        return

    print("\nExample questions:")
    print("  - What anomalies happened recently?")
    print("  - Show 路氹城區 anomaly statistics")
    print("  - Predict next week consumption")
    print("  - How many meters are there?")
    print("  - Show me a weekly trend chart")
    print("  - Type 'quit' to exit\n")

    while True:
        question = input("Your question: ").strip()
        if question.lower() in ("quit", "exit", "q"):
            break
        if not question:
            continue

        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        for msg in reversed(result["messages"]):
            if hasattr(msg, "content") and msg.content:
                print(f"\nAnswer:\n{msg.content}\n")
                break


if __name__ == "__main__":
    main()
