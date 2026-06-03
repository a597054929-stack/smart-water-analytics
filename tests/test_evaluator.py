"""Unit tests for the evaluator.

Uses a stub agent so the test is deterministic and doesn't need an LLM.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


class _StubAIMessage:
    """Pretends to be a LangChain AIMessage with `name` and `content`."""
    def __init__(self, content, name=None):
        self.content = content
        self.name = name
        self.type = "ai"


class _StubToolMessage:
    def __init__(self, name, content):
        self.name = name
        self.content = content
        self.type = "tool"


class _StubAgent:
    """Picks a tool based on a keyword → tool mapping. Deterministic."""

    def __init__(self, mapping):
        self.mapping = mapping

    def invoke(self, payload):
        q = payload["messages"][-1]["content"].lower()
        tool_name = self.mapping.get("default", "")
        for kw, name in self.mapping.items():
            if kw in q and kw != "default":
                tool_name = name
                break
        return {
            "messages": [
                _StubToolMessage(tool_name, "[]"),
                _StubAIMessage(f"Stub answer mentioning {tool_name} for: {q}"),
            ]
        }


def test_evaluator_scores_correctly(tmp_path, monkeypatch):
    """Stub the agent and check the score logic."""
    import evaluate as ev
    from agent import agent_executor

    # Stub the agent builder
    monkeypatch.setattr(
        agent_executor,
        "create_water_agent",
        lambda: _StubAgent({
            "default": "get_data_overview",
            "zone-3": "sql_query",
            "zone-1": "query_anomalies",
            "top 5": "sql_query",
        }),
    )

    # Build a tiny QA file
    qa = {
        "pairs": [
            {
                "id": "a",
                "question": "How many anomalies are in Zone-3?",
                "expected_tool": "sql_query",
                "expected_keywords": ["Zone-3", "12"],
                "difficulty": "easy",
            },
            {
                "id": "b",
                "question": "Show me anomalies in Zone-1",
                "expected_tool": "query_anomalies",
                "expected_keywords": ["Zone-1"],
                "difficulty": "easy",
            },
            {
                "id": "c",
                "question": "Top 5 meters",
                "expected_tool": "sql_query",
                "expected_keywords": ["meterId", "DESC"],
                "difficulty": "medium",
            },
        ]
    }
    qa_path = tmp_path / "qa.json"
    qa_path.write_text(json.dumps(qa), encoding="utf-8")

    # Force reports dir to a tmp location
    monkeypatch.setattr(ev, "REPORTS_DIR", tmp_path)
    s = ev.evaluate(qa_path, threshold=0.5, save=True)

    assert s["n_pairs"] == 3
    assert s["verdict"] in ("pass", "fail")
    # All 3 should have called the right tool
    assert s["tool_accuracy"] == 1.0
    # Aggregate pass rate is at least 0/3..3/3; we don't assert exact here.
    assert 0 <= s["pass_rate"] <= 1
    # Report files exist
    assert (tmp_path / "eval_per_qa.json").exists()
    assert (tmp_path / "eval_report.md").exists()


def test_extraction_handles_string_and_list_content():
    """The final-answer extractor must work for both str and list blocks."""
    import evaluate as ev

    # String content
    msgs = [_StubAIMessage("hello world")]
    assert ev._extract_final_answer(msgs) == "hello world"

    # List-of-blocks content
    msgs = [_StubAIMessage([{"type": "text", "text": "first "}, {"type": "text", "text": "second"}])]
    assert "first" in ev._extract_final_answer(msgs)
    assert "second" in ev._extract_final_answer(msgs)

    # Empty
    assert ev._extract_final_answer([]) == ""


def test_tool_call_extraction():
    """Verify tool call names are recovered from the message log."""
    import evaluate as ev

    msgs = [
        _StubAIMessage(""),
        _StubToolMessage("sql_query", "[]"),
        _StubToolMessage("get_table_schema_tool", "{}"),
        _StubAIMessage("final answer"),
    ]
    called = ev._extract_tool_calls(msgs)
    assert "sql_query" in called
    assert "get_table_schema_tool" in called
