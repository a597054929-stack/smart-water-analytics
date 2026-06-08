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
- query_consumption(mode, date, dma, month1, month2, limit)   # daily/weekly/compare
- query_weekly()
- query_rank_changes(limit)
- query_monthly_diff(month)
- generate_chart(chart_type, dma, days)
- compare_months(month1, month2, dma)
- analyze_anomaly(meter_id)
- generate_report(dma, month)
- query_data_quality(date, meter_id, reason)

Rules (tool selection):
- Output ONLY the JSON array, no other text
- Include only tools relevant to the question
- Set reasonable parameter defaults if not specified
- For comparison questions, include compare_months
- For investigation questions, include analyze_anomaly
- Always end with generate_report if the user asks for a summary

When to ask back (clarify instead of guessing):
- The user asks 查异常 / 查数据 / 查表 but does not specify DMA,
  time period, or meter ID.
- The user question is materially ambiguous: different choices lead
  to different tools or different answers.
- The user references this week / current zone / the meter we discussed
  without context being available in PAGE CONTEXT.

How to ask back:
- Return a SINGLE JSON object (not an array of tool calls):
  {"action": "clarify", "question": "<Chinese clarification>",
   "options": ["澳門低區", "澳門填海A區", "澳大橫琴區", "路氹城區"],
   "default": "澳門低區"}
- Provide 2-4 numbered options
- Mark the most likely as default
- Hard cap: 1 question per turn (no lists of 4 questions)
- DMA names are always the 4 real Macau names below, never abbreviations.

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
         "question": "请选择要查询的 DMA 区域",
         "options": ["澳門低區", "澳門填海A區", "澳大橫琴區", "路氹城區"],
         "default": "澳門低區"}

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
