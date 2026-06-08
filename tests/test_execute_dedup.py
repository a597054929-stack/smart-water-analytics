"""Tests for the dedup / circuit-breaker / max-tools guards in
agent.multi_agent.execute().

These tests lock in the 2026-06-09 P0 fixes:
- (tool, params) dedup — same call repeated is skipped, NOT
  silently re-executed (cost + hallucination risk).
- Different params (e.g. dma=路氹城區 vs dma=澳大橫琴區) are
  NOT deduped — the user explicitly asked for that granularity.
- Circuit breaker — max_consecutive_failures consecutive
  failures abort the rest of the plan.
- max_tools cap — total tool calls are bounded.

The tests use a fake tool registry so they don't need a real LLM
or real database. The fake tools return either success or
raise a specified exception.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo + agent on sys.path (same bootstrap as other tests)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "agent") not in sys.path:
    sys.path.insert(0, str(ROOT / "agent"))


def _install_fake_tools(monkeypatch, behavior: dict):
    """Replace TOOL_REGISTRY with a fake set of tools.

    behavior maps tool_name -> {"ok": bool, "raise": Exception|None}
    """
    import json as _json
    from agent import multi_agent

    def _make_fake(name):
        def invoke(*args, **kwargs):
            # LangChain @tool.invoke: positional or input= kwarg
            params = kwargs.get("input", args[0] if args else {})
            beh = behavior.get(name, {"ok": True, "raise": None})
            if beh.get("raise"):
                raise beh["raise"]
            return _json.dumps(
                {"ok": True, "tool": name, "params": params},
                ensure_ascii=False,
            )
        # Wrap invoke in a small object with a `.name` attribute so
        # execute() can record it in the result dict.
        class _Stub:
            pass
        s = _Stub()
        s.name = name
        s.invoke = invoke
        return s

    registry = {name: _make_fake(name) for name in behavior}
    monkeypatch.setattr(multi_agent, "TOOL_REGISTRY", registry)
    return registry


def test_duplicate_call_skipped(monkeypatch):
    """Same (tool, params) called twice -> second is skipped."""
    from agent.multi_agent import execute
    _install_fake_tools(monkeypatch, {"query_anomalies": {"ok": True}})
    plan = [
        {"tool": "query_anomalies", "params": {"dma": "路氹城區"}},
        {"tool": "query_anomalies", "params": {"dma": "路氹城區"}},
    ]
    results = execute(plan)
    # First call executes, second is skipped
    assert len(results) == 2
    assert "result" in results[0]
    assert results[1].get("skipped") == "duplicate call"
    assert results[1]["tool"] == "query_anomalies"


def test_different_params_not_deduped(monkeypatch):
    """Different params for same tool are NOT deduped (legitimate use)."""
    from agent.multi_agent import execute
    _install_fake_tools(monkeypatch, {"query_anomalies": {"ok": True}})
    plan = [
        {"tool": "query_anomalies", "params": {"dma": "路氹城區"}},
        {"tool": "query_anomalies", "params": {"dma": "澳大橫琴區"}},
    ]
    results = execute(plan)
    # Both should execute (different dma)
    assert len(results) == 2
    assert "result" in results[0]
    assert "result" in results[1]
    assert "skipped" not in results[0]
    assert "skipped" not in results[1]


def test_circuit_breaker_aborts(monkeypatch):
    """max_consecutive_failures consecutive errors -> rest aborted."""
    from agent.multi_agent import execute
    _install_fake_tools(monkeypatch, {
        "broken_tool": {"ok": False, "raise": RuntimeError("boom")},
        "good_tool": {"ok": True},
    })
    # Use different params so each call is distinct (otherwise dedup
    # would skip before the circuit breaker could trip).
    plan = [
        {"tool": "broken_tool", "params": {"i": 1}},  # fail
        {"tool": "broken_tool", "params": {"i": 2}},  # fail -> 2 consecutive
        {"tool": "good_tool",   "params": {"i": 3}},  # should NOT run
        {"tool": "good_tool",   "params": {"i": 4}},  # should NOT run
    ]
    results = execute(plan, max_consecutive_failures=2)
    # 2 failures + 1 circuit-breaker entry = 3 entries total
    assert len(results) == 3
    assert "error" in results[0]
    assert "error" in results[1]
    assert "circuit breaker" in results[2].get("skipped", "")


def test_max_tools_cap(monkeypatch):
    """Total tool calls capped at max_tools."""
    from agent.multi_agent import execute
    _install_fake_tools(monkeypatch, {"t": {"ok": True}})
    # 10 different params -> 10 legitimate calls, but cap at 3
    plan = [
        {"tool": "t", "params": {"i": i}} for i in range(10)
    ]
    results = execute(plan, max_tools=3)
    # First 3 execute, then cap triggers
    assert len(results) == 4
    assert "result" in results[0]
    assert "result" in results[1]
    assert "result" in results[2]
    assert "max_tools" in results[3].get("skipped", "")


def test_string_step_normalized(monkeypatch):
    """Defensive: LLM sometimes returns ['tool1', 'tool2'] (string list)."""
    from agent.multi_agent import execute
    _install_fake_tools(monkeypatch, {"query_anomalies": {"ok": True}})
    plan = ["query_anomalies", "query_anomalies"]  # both as strings
    results = execute(plan)
    # First runs, second is deduped (same tool, same params={})
    assert len(results) == 2
    assert "result" in results[0]
    assert results[1].get("skipped") == "duplicate call"


def test_consecutive_failures_reset_on_success(monkeypatch):
    """After a success, the failure counter resets."""
    from agent.multi_agent import execute
    _install_fake_tools(monkeypatch, {
        "flaky": {"ok": False, "raise": RuntimeError("oops")},
        "good": {"ok": True},
    })
    # Each step has different params to avoid dedup (which would
    # otherwise skip the second "good" call before the test could
    # observe the counter-reset behavior).
    plan = [
        {"tool": "flaky", "params": {"step": 1}},  # fail
        {"tool": "good",  "params": {"step": 2}},  # ok -> reset counter
        {"tool": "flaky", "params": {"step": 3}},  # fail (counter=1)
        {"tool": "good",  "params": {"step": 4}},  # ok -> reset counter
        {"tool": "flaky", "params": {"step": 5}},  # fail (counter=1)
    ]
    results = execute(plan, max_consecutive_failures=2)
    # All 5 should run (no circuit trip)
    assert len(results) == 5
    # No circuit-breaker entry
    for r in results:
        assert "circuit breaker" not in r.get("skipped", "")
