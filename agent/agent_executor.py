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

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from config import get_llm_config
from agent_tools import ALL_TOOLS


SYSTEM_PROMPT = """You are a Smart Water Analytics AI Assistant. You help users analyze water consumption data using the available tools.

Your capabilities:
1. Query anomaly records (spike, drop, zero, watch) by DMA zone, month, or type
2. Look up meter information by DMA, building, or residential type
3. Get consumption predictions (7-day forecast) for meters or buildings
4. Retrieve daily/weekly consumption data and comparisons
5. Analyze Non-Revenue Water (NRW) via main-sub meter differences
6. Generate ECharts visualizations (trends, distributions)

Rules:
- Always use tools to get actual data. Never fabricate numbers.
- Answer in the same language as the user's question.
- When showing results, include specific numbers and dates.
- For anomaly data: anomalyScore ranges 0-1, where 0.7+ needs attention.
- If asked to visualize, use the generate_chart tool and explain what the chart shows.
- If a tool returns no results, say so clearly and suggest alternative queries.
"""


def create_water_agent():
    """Create the water analytics agent."""
    cfg = get_llm_config()

    llm = ChatOpenAI(
        model=cfg["model"],
        api_key=cfg["api_key"],
        base_url=cfg.get("base_url"),
        temperature=0,
        max_tokens=2048,
    )

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
    print("  - Show Zone-3 anomaly statistics")
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
