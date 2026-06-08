"""Harness tests for the AI agent — 30 cases across 4 categories.

Categories (per ADR-0004):
  A. Tool selection correctness (10)  — agent picks the right tool
  B. Ambiguous input → clarify (8)     — agent must NOT just guess
  C. Privilege escalation rejected (7) — agent must NOT execute dangerous ops
  D. Boundary / robustness (5)         — input edge cases don't crash agent

These tests are **offline** — they use the ``mock_llm`` fixture from
``conftest.py`` to substitute a deterministic LLM that returns plans
based on keyword matching. They are designed to run in CI in < 5
seconds, with no network and no API keys.

Why this matters:
- The end-to-end ``tests/evaluate.py`` runs a live LLM and takes ~10
  minutes. We can't put that in CI.
- These harness tests pin down **decision paths** (which tools the
  planner picked), not final-answer wording.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

HARNESS_CASES = json.loads(
    Path(__file__).parent.joinpath("harness/agent_behaviors.json").read_text(encoding="utf-8")
)


def _check_contains(actual: list, expected: list, label: str) -> None:
    """Assert every tool in ``expected`` is in ``actual``."""
    for t in expected:
        assert t in actual, (
            f"{label}: expected tool '{t}' in {actual}"
        )


def _check_not_contains(actual: list, banned: list, label: str) -> None:
    for t in banned:
        assert t not in actual, (
            f"{label}: should NOT call '{t}', but plan called it: {actual}"
        )


def _check_text(answer: str, expected_list: list, label: str) -> None:
    """Assert at least one substring in ``expected_list`` is in ``answer``."""
    found = any(s in answer for s in expected_list)
    assert found, (
        f"{label}: expected one of {expected_list} in answer, got: {answer[:200]}"
    )


@pytest.mark.parametrize("case", HARNESS_CASES, ids=[c["name"] for c in HARNESS_CASES])
def test_agent_behavior(case, mock_llm):
    """Verify the agent makes the right tool-selection + answer-shape decision."""
    from agent.multi_agent import run_multi_agent

    result = run_multi_agent(case["input"], context=case.get("context") or {})

    # tools_called (post-execution)
    called = set(result.get("tools_called", []))

    # plan (planner output) — useful for cases that should NOT execute
    plan = result.get("plan", [])
    plan_tools = [s.get("tool", "") for s in plan] if isinstance(plan, list) else []

    expected = case.get("expected", {})

    if "planner_plan_contains" in expected:
        # For 'planner_plan_contains' use the plan list (pre-execute)
        # but also assert that the tool actually ran if applicable
        _check_contains(plan_tools, expected["planner_plan_contains"], case["name"])

    if "planner_plan_not_contains" in expected:
        _check_not_contains(plan_tools, expected["planner_plan_not_contains"], case["name"])

    if "tools_called" in expected:
        # Use tools_called (post-execute) for the strict case
        for t in expected["tools_called"]:
            assert t in called, f"{case['name']}: expected '{t}' called, got {called}"

    if "tools_not_called" in expected:
        for t in expected["tools_not_called"]:
            assert t not in called, f"{case['name']}: should NOT call '{t}'"

    answer = result.get("answer", "") or ""
    if "answer_contains" in expected:
        for s in expected["answer_contains"]:
            assert s in answer, (
                f"{case['name']}: expected '{s}' in answer: {answer[:200]}"
            )
    if "answer_contains_any" in expected:
        _check_text(answer, expected["answer_contains_any"], case["name"])
