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

PLANNER_PROMPT = """You are a planning agent. Your job is to analyze the user's question
and create a structured execution plan.

Given the user question, output a JSON array of tool calls to execute.
Each tool call should be: {"tool": "tool_name", "params": {"param": "value"}}

Available tools:
- query_anomalies(dma, month, anomaly_type, limit)
- query_meters(dma, is_residential, building, limit)
- get_anomaly_stats(month, dma)
- get_predictions(meter_id, limit)
- get_building_predictions(building, limit)
- get_data_overview()
- query_daily_dma(date, dma, limit)
- query_weekly()
- query_rank_changes(limit)
- query_monthly_diff(month)
- generate_chart(chart_type, dma, days)
- compare_months(month1, month2, dma)
- analyze_anomaly(meter_id)
- generate_report(dma, month)

Rules:
- Output ONLY the JSON array, no other text
- Include only tools relevant to the question
- Set reasonable parameter defaults if not specified
- For comparison questions, include compare_months
- For investigation questions, include analyze_anomaly
- Always end with generate_report if the user asks for a summary

Example:
User: "Show me Zone-3 anomalies for March"
Output: [{"tool": "get_anomaly_stats", "params": {"month": "2026-03", "dma": "Zone-3"}}, {"tool": "query_anomalies", "params": {"month": "2026-03", "dma": "Zone-3", "limit": 10}}]
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


def plan(question: str, llm) -> list:
    """Generate an execution plan for the question."""
    messages = [
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=question),
    ]
    response = llm.invoke(messages)
    content = response.content

    # Extract JSON from response
    if isinstance(content, list):
        content = " ".join(block.get("text", "") for block in content if isinstance(block, dict))

    # Find JSON array in response
    start = content.find("[")
    end = content.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end])
        except json.JSONDecodeError:
            pass

    # Fallback: single query
    return [{"tool": "get_data_overview", "params": {}}]


# ── Executor ──────────────────────────────────────────────────

def execute(plan_steps: list) -> list:
    """Execute a plan by calling tools in sequence."""
    results = []
    for step in plan_steps:
        tool_name = step.get("tool", "")
        params = step.get("params", {})

        if tool_name not in TOOL_REGISTRY:
            results.append({"tool": tool_name, "error": f"Unknown tool: {tool_name}"})
            continue

        try:
            tool = TOOL_REGISTRY[tool_name]
            output = tool.invoke(params)
            results.append({"tool": tool_name, "result": output})
        except Exception as e:
            results.append({"tool": tool_name, "error": str(e)})

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

def run_multi_agent(question: str) -> dict:
    """Run the full multi-agent pipeline: Plan → Execute → Synthesize."""
    cfg = get_llm_config()
    llm = ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        temperature=0,
        max_tokens=2048,
    )

    # Step 1: Plan
    plan_steps = plan(question, llm)

    # Step 2: Execute
    results = execute(plan_steps)

    # Step 3: Synthesize
    answer = synthesize(question, plan_steps, results, llm)

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
