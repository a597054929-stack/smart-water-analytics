"""Unit tests for the agent's ask-back (clarification) behavior.

When a user's question is materially ambiguous (e.g. "查异常" with no
DMA, no time period, no meter ID), the agent should ASK BACK rather
than guess. This file pins down that behavior with 5 cases.

The mock LLM in ``conftest.py`` dispatches on keywords; we add a
``ask_back_llm`` fixture here that always returns a CLARIFY response,
and use it to verify:
  - clarify response has the expected shape
  - run_multi_agent returns immediately (no executor, no synthesizer)
  - tools_called is empty
  - "查 Zone-3 异常" (specific) does NOT trigger clarify
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


CLARIFY_RESPONSE = (
    '{"action": "clarify", '
    '"question": "请选择 DMA 区域：", '
    '"options": ["Zone-1", "Zone-2", "Zone-3", "Zone-4"], '
    '"default": "Zone-1"}'
)

PLAN_RESPONSE = (
    '[{"tool": "get_anomaly_stats", "params": {"dma": "Zone-3"}}, '
    '{"tool": "query_anomalies", "params": {"dma": "Zone-3", "limit": 10}}]'
)


@pytest.fixture
def clarify_llm(monkeypatch):
    """Mock LLM that always returns a clarify response."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=CLARIFY_RESPONSE)
    monkeypatch.setattr("agent.multi_agent.ChatOpenAI", lambda *a, **k: llm)
    monkeypatch.setattr(
        "agent.multi_agent.get_llm_config",
        lambda: {"provider": "openai", "model": "mock",
                 "api_key": "sk-mock", "base_url": ""},
    )
    return llm


@pytest.fixture
def plan_llm(monkeypatch):
    """Mock LLM that always returns a normal plan."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=PLAN_RESPONSE)
    monkeypatch.setattr("agent.multi_agent.ChatOpenAI", lambda *a, **k: llm)
    monkeypatch.setattr(
        "agent.multi_agent.get_llm_config",
        lambda: {"provider": "openai", "model": "mock",
                 "api_key": "sk-mock", "base_url": ""},
    )
    return llm


def test_ask_back_when_dma_unspecified(clarify_llm):
    """'查异常' should trigger clarify, not execute tools."""
    from agent.multi_agent import run_multi_agent

    result = run_multi_agent("查异常")
    assert result.get("clarify") is not None
    assert "Zone-1" in result["clarify"]["options"]
    assert result["answer"]  # clarifying question lives in answer
    assert result["tools_called"] == []
    assert result["plan"] == []


def test_ask_back_for_vague_query(clarify_llm):
    """'查数据' is similarly vague, should also clarify."""
    from agent.multi_agent import run_multi_agent

    result = run_multi_agent("查数据")
    assert result.get("clarify") is not None
    assert "default" in result["clarify"]


def test_no_ask_back_when_dma_specified(plan_llm):
    """'查 Zone-3 异常' is specific, should NOT clarify."""
    from agent.multi_agent import run_multi_agent

    result = run_multi_agent("查 Zone-3 异常")
    assert "clarify" not in result or result.get("clarify") is None
    # Normal plan path → tools should be called
    assert len(result["tools_called"]) > 0


def test_ask_back_max_one_question(clarify_llm):
    """Ask-back response should have 2-4 options, not 10."""
    from agent.multi_agent import run_multi_agent

    result = run_multi_agent("查异常")
    options = result.get("clarify", {}).get("options", [])
    assert 2 <= len(options) <= 4, f"Expected 2-4 options, got {len(options)}"


def test_synthesizer_not_called_on_clarify(clarify_llm):
    """When clarifying, only ONE LLM call (the planner), not three."""
    from agent.multi_agent import run_multi_agent

    result = run_multi_agent("查异常")
    # Should only invoke once (planner) — no executor or synthesizer
    assert clarify_llm.invoke.call_count == 1
    # Sanity: result is the clarify path
    assert result.get("clarify") is not None


def test_plan_function_legacy_array_format(monkeypatch):
    """plan() should still handle the legacy bare-array return format."""
    from agent.multi_agent import plan

    legacy_llm = MagicMock()
    legacy_llm.invoke.return_value = MagicMock(content=PLAN_RESPONSE)

    result = plan("查 Zone-3 异常", legacy_llm)
    assert result["action"] == "plan"
    assert len(result["steps"]) == 2
    assert result["steps"][0]["tool"] == "get_anomaly_stats"


def test_plan_function_object_envelope(monkeypatch):
    """plan() should also handle the explicit {"action": "plan", "steps": [...]} envelope."""
    from agent.multi_agent import plan

    envelope = '{"action": "plan", "steps": [{"tool": "get_data_overview", "params": {}}]}'
    env_llm = MagicMock()
    env_llm.invoke.return_value = MagicMock(content=envelope)

    result = plan("总览", env_llm)
    assert result["action"] == "plan"
    assert result["steps"][0]["tool"] == "get_data_overview"


def test_plan_function_clarify(monkeypatch):
    """plan() should return a clarify dict when LLM emits the clarify envelope."""
    from agent.multi_agent import plan

    cl_llm = MagicMock()
    cl_llm.invoke.return_value = MagicMock(content=CLARIFY_RESPONSE)

    result = plan("查异常", cl_llm)
    assert result["action"] == "clarify"
    assert result["question"] == "请选择 DMA 区域："
    assert "Zone-1" in result["options"]
    assert result["default"] == "Zone-1"


def test_plan_function_fallback_on_garbage(monkeypatch):
    """plan() should return a safe fallback when the LLM emits garbage."""
    from agent.multi_agent import plan

    bad_llm = MagicMock()
    bad_llm.invoke.return_value = MagicMock(content="this is not json at all")

    result = plan("???", bad_llm)
    assert result["action"] == "plan"
    # Fallback uses get_data_overview
    assert result["steps"][0]["tool"] == "get_data_overview"
