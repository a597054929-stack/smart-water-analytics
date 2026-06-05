"""Agent evaluation harness.

Runs every QA pair from `qa_pairs.json` through the agent and scores:
- **Tool accuracy**: did it call the expected tool?
- **Keyword recall**: what fraction of expected keywords appear in the answer?
- **Latency**: end-to-end wall time
- **Failure rate**: % of unanswered or errored questions

Output:
- `reports/eval_per_qa.json` — per-question results
- `reports/eval_report.md` — human-readable aggregate report
- Pass/fail threshold is configurable (default 80%)

This is the "evaluation framework" the agent lives under. In production
you'd run it in CI before any model change ships.

Usage:
    python tests/evaluate.py             # full run, save report
    python tests/evaluate.py --print     # print results, don't save
    python tests/evaluate.py --threshold 0.7
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

os.environ.setdefault("WATER_DATA_DIR", str(ROOT / "backend" / "data" / "output"))

REPORTS_DIR = ROOT / "reports"
QA_PATH = Path(__file__).resolve().parent / "qa_pairs.json"


# ── Tool-call extraction ─────────────────────────────────────

def _extract_tool_calls(messages: list) -> list[str]:
    """Walk the agent's message log and return the names of tools it called."""
    called: list[str] = []
    for m in messages:
        # langchain tool messages have a `name` attribute
        if getattr(m, "name", None) and getattr(m, "type", "") == "tool":
            called.append(m.name)
        # Some versions store tool calls on the AIMessage
        tc = getattr(m, "tool_calls", None)
        if tc:
            for c in tc:
                name = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
                if name:
                    called.append(name)
    return called


def _extract_final_answer(messages: list) -> str:
    """Return the last AI message text content (handles list/dict blocks)."""
    for m in reversed(messages):
        if getattr(m, "type", "") == "ai" and getattr(m, "content", None):
            c = m.content
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                texts = []
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                if texts:
                    return " ".join(texts)
            return str(c)
    return ""


def _extract_tool_outputs(messages: list) -> str:
    """Concatenate raw tool outputs (so column names from SQL count as hits).

    The final-answer text often paraphrases column names (e.g. `anomalyScore`
    → `异常分数`), which makes pure text kw_recall unreliable for SQL pairs.
    The raw tool output, on the other hand, is a JSON string with the actual
    `columns` array, so checking keywords against (final_answer + tool_outputs)
    catches both the LLM's summary and the underlying data.
    """
    parts: list[str] = []
    for m in messages:
        if getattr(m, "type", "") != "tool":
            continue
        c = getattr(m, "content", None)
        if c is None:
            continue
        if isinstance(c, str):
            parts.append(c)
        else:
            parts.append(str(c))
    return " ".join(parts)


# ── Scoring ──────────────────────────────────────────────────

def score_one(
    question: str,
    expected_tool: str,
    expected_keywords: list[str],
    tool_calls: list[str],
    final_answer: str,
    elapsed_s: float,
    error: str | None = None,
    expected_behavior: str = "",
    tool_outputs: str = "",
) -> dict[str, Any]:
    tool_match = expected_tool in tool_calls
    if expected_keywords:
        # 2026-06-06: combine final answer + raw tool output. The LLM
        # often paraphrases column names in the summary (e.g. `anomalyScore`
        # → `异常分数`); the raw tool output contains the literal column
        # name. Checking both prevents false-FAIL on perfectly-correct SQL
        # pairs (the 6 Type A fails on the 2026-06-05 real-data eval).
        combined = (final_answer + "\n" + tool_outputs).lower()
        hits = sum(1 for kw in expected_keywords if kw.lower() in combined)
        kw_recall = hits / len(expected_keywords)
    else:
        kw_recall = 1.0

    # Behavior-aware scoring (2026-06-05: ask-back clarifications don't
    # call tools, so the default `tool_match and kw_recall` rule would
    # always FAIL them). Switch the success criterion per behavior:
    if expected_behavior == "ask_clarification":
        # pass if: no tool calls (LLM asked back, didn't act) AND
        #           the clarification contains the expected keywords
        behavior_ok = len(tool_calls) == 0
    elif expected_behavior == "guess_with_state":
        # pass if: LLM acted (some tool call) AND keywords present
        behavior_ok = len(tool_calls) > 0
    else:
        # default: tool must match the expected one
        behavior_ok = tool_match

    return {
        "question": question,
        "expected_tool": expected_tool,
        "expected_behavior": expected_behavior,
        "expected_keywords": expected_keywords,
        "tool_calls": tool_calls,
        "tool_match": tool_match,
        "kw_recall": round(kw_recall, 3),
        "elapsed_s": round(elapsed_s, 3),
        "answer_chars": len(final_answer),
        "error": error,
        "pass_": behavior_ok and kw_recall >= 0.5 and not error,
    }


# ── Runner ───────────────────────────────────────────────────

def evaluate(
    qa_path: Path = QA_PATH,
    threshold: float = 0.8,
    save: bool = True,
) -> dict[str, Any]:
    """Run every QA pair and return the aggregate metrics."""
    pairs = json.loads(qa_path.read_text(encoding="utf-8"))["pairs"]
    print(f"Evaluating {len(pairs)} QA pairs (threshold {threshold:.0%}) ...\n")

    try:
        from agent.agent_executor import create_water_agent
        agent = create_water_agent()
    except Exception as e:
        print(f"FATAL: could not build the agent: {e}", file=sys.stderr)
        return {"status": "agent_unavailable", "error": str(e)}

    per_qa: list[dict] = []
    passed = 0
    tool_hits = 0
    total_kw = 0.0
    total_latency = 0.0
    failed_count = 0

    for i, p in enumerate(pairs, 1):
        q = p["question"]
        et = p.get("expected_tool", "")
        ek = p.get("expected_keywords", [])
        eb = p.get("expected_behavior", "")
        print(f"[{i:2d}/{len(pairs)}] {q}")
        start = time.perf_counter()
        tool_calls: list[str] = []
        answer = ""
        tool_outputs = ""
        err: str | None = None
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": q}]})
            messages = result.get("messages", [])
            tool_calls = _extract_tool_calls(messages)
            answer = _extract_final_answer(messages)
            tool_outputs = _extract_tool_outputs(messages)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        elapsed = time.perf_counter() - start
        score = score_one(q, et, ek, tool_calls, answer, elapsed, err,
                          expected_behavior=eb, tool_outputs=tool_outputs)
        per_qa.append(score)
        if score["pass_"]:
            passed += 1
        if score["tool_match"]:
            tool_hits += 1
        total_kw += score["kw_recall"]
        total_latency += score["elapsed_s"]
        if err or not answer:
            failed_count += 1
        marker = "PASS" if score["pass_"] else "FAIL"
        print(
            f"   {marker} tool={score['tool_match']} kw={score['kw_recall']:.0%} "
            f"t={score['elapsed_s']:.1f}s"
        )

    n = len(pairs)
    summary = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "n_pairs": n,
        "pass_rate": round(passed / n, 3) if n else 0,
        "tool_accuracy": round(tool_hits / n, 3) if n else 0,
        "avg_kw_recall": round(total_kw / n, 3) if n else 0,
        "avg_latency_s": round(total_latency / n, 3) if n else 0,
        "failure_rate": round(failed_count / n, 3) if n else 0,
        "threshold": threshold,
        "verdict": "pass" if (passed / n if n else 0) >= threshold else "fail",
        "per_qa": per_qa,
    }
    print(
        f"\npass_rate={summary['pass_rate']:.1%}  tool_acc={summary['tool_accuracy']:.1%}  "
        f"avg_kw={summary['avg_kw_recall']:.1%}  avg_latency={summary['avg_latency_s']:.1f}s  "
        f"verdict={summary['verdict']}"
    )

    if save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        per_qa_path = REPORTS_DIR / "eval_per_qa.json"
        per_qa_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_md = REPORTS_DIR / "eval_report.md"
        report_md.write_text(_format_markdown(summary), encoding="utf-8")
        print(f"\nWrote {per_qa_path}\nWrote {report_md}")
    return summary


def _format_markdown(s: dict) -> str:
    rows = []
    rows.append("# Agent Evaluation Report")
    rows.append("")
    rows.append(f"- Generated: {s['generated_at']}")
    rows.append(f"- Pairs evaluated: **{s['n_pairs']}**")
    rows.append(f"- Threshold: {s['threshold']:.0%}")
    rows.append(f"- Verdict: **{s['verdict']}**")
    rows.append("")
    rows.append("## Aggregate metrics")
    rows.append("")
    rows.append("| Metric | Value |")
    rows.append("| --- | --- |")
    rows.append(f"| pass_rate | {s['pass_rate']:.1%} |")
    rows.append(f"| tool_accuracy | {s['tool_accuracy']:.1%} |")
    rows.append(f"| avg_kw_recall | {s['avg_kw_recall']:.1%} |")
    rows.append(f"| avg_latency_s | {s['avg_latency_s']:.2f} |")
    rows.append(f"| failure_rate | {s['failure_rate']:.1%} |")
    rows.append("")
    rows.append("## Per-question results")
    rows.append("")
    rows.append("| # | Pass | Tool | Tool match | KW recall | Latency | Question |")
    rows.append("| --- | --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(s["per_qa"], 1):
        rows.append(
            f"| {i} | {'PASS' if r['pass_'] else 'FAIL'} | "
            f"{r['expected_tool']} | {r['tool_match']} | {r['kw_recall']:.0%} | "
            f"{r['elapsed_s']:.1f}s | {r['question']} |"
        )
    return "\n".join(rows) + "\n"


def main():
    p = argparse.ArgumentParser(description="Run the agent evaluation suite")
    p.add_argument("--threshold", type=float, default=0.8, help="Pass-rate threshold (0-1)")
    p.add_argument("--print", action="store_true", help="Don't save results to disk")
    p.add_argument("--qa", type=str, default=str(QA_PATH), help="Path to qa_pairs.json")
    args = p.parse_args()
    s = evaluate(Path(args.qa), threshold=args.threshold, save=not args.print)
    return 0 if s.get("verdict") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
