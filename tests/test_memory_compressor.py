"""Unit tests for agent.memory_compressor.MemoryCompressor.

All tests use a ``MagicMock`` LLM — no live LLM calls, no network,
safe to run in CI on every commit.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent.memory_compressor import MemoryCompressor


def _msgs(n: int) -> list:
    """Build a deterministic ``n``-message alternating user/assistant history."""
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(HumanMessage(content=f"Q{i} about Zone-3"))
        else:
            out.append(AIMessage(content=f"A{i}: 12 anomalies in 2026-03"))
    return out


def test_short_history_returned_raw():
    llm = MagicMock()
    c = MemoryCompressor(llm, recent_turns=6)
    history = _msgs(4)
    out = c.compress(history)
    assert out["recent"] == history
    assert out["summary"] == ""
    llm.invoke.assert_not_called()


def test_long_history_summarized():
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="Zone-3 anomalies in 2026-03: 12 found.")
    c = MemoryCompressor(llm, recent_turns=6)
    out = c.compress(_msgs(20))
    assert len(out["recent"]) == 6
    assert "Zone-3" in out["summary"]
    llm.invoke.assert_called_once()


def test_summary_truncated_to_max_chars():
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="x" * 5000)
    c = MemoryCompressor(llm, recent_turns=6, summary_max_chars=800)
    out = c.compress(_msgs(20))
    assert 0 < len(out["summary"]) <= 800


def test_reconstruct_context_shape():
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="User discussed Zone-3.")
    c = MemoryCompressor(llm, recent_turns=6)
    compressed = c.compress(_msgs(20))
    text = c.reconstruct_context(compressed)
    assert "[Earlier conversation summary]" in text
    assert "[Recent conversation]" in text
    recent_block = text.split("[Recent conversation]")[-1]
    assert recent_block.count("User:") + recent_block.count("Assistant:") == 6


def test_llm_failure_degrades_gracefully():
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("API down")
    c = MemoryCompressor(llm, recent_turns=6)
    out = c.compress(_msgs(20))
    assert out["summary"] == ""
    assert len(out["recent"]) == 6


def test_recent_turns_validation():
    with pytest.raises(ValueError):
        MemoryCompressor(MagicMock(), recent_turns=0)


def test_exact_boundary():
    """History of exactly recent_turns should NOT trigger summarization."""
    llm = MagicMock()
    c = MemoryCompressor(llm, recent_turns=6)
    out = c.compress(_msgs(6))
    assert out["summary"] == ""
    llm.invoke.assert_not_called()


def test_empty_history_no_crash():
    llm = MagicMock()
    c = MemoryCompressor(llm, recent_turns=6)
    out = c.compress([])
    assert out["recent"] == []
    assert out["summary"] == ""
    llm.invoke.assert_not_called()
