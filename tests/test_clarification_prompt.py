"""Tests for the ask-back CLARIFICATION block in the agent's system prompt.

The clarification behavior is implemented as a prompt rule (not a tool),
so the tests verify the prompt is loaded correctly and stays under the
token budget. End-to-end behavior is verified via the live eval in
`tests/evaluate.py` against the `ask_clarification` QA pairs.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))


def test_prompt_has_clarification_header():
    """The CLARIFICATION block must be present and titled."""
    from agent.agent_executor import SYSTEM_PROMPT
    assert "CLARIFICATION" in SYSTEM_PROMPT, "CLARIFICATION header missing"


def test_prompt_teaches_ask_rule():
    """The ASK rule (one question, numbered options, no tool calls) must be present."""
    from agent.agent_executor import SYSTEM_PROMPT
    assert "ASK" in SYSTEM_PROMPT
    # The rule must say "one question only" / cap at 1
    assert "one question only" in SYSTEM_PROMPT or "1 question per turn" in SYSTEM_PROMPT


def test_prompt_teaches_guess_rule():
    """The GUESS+STATE fallback must be present (so we don't over-ask)."""
    from agent.agent_executor import SYSTEM_PROMPT
    assert "GUESS" in SYSTEM_PROMPT, "GUESS rule missing"
    # Must mention stating the assumption
    assert "state" in SYSTEM_PROMPT.lower()


def test_prompt_caps_at_one_question():
    """The rule must explicitly cap ask-back to 1 question per turn."""
    from agent.agent_executor import SYSTEM_PROMPT
    # Look for the explicit cap. Either "one question only" or "1 question per turn".
    has_cap = (
        "one question only" in SYSTEM_PROMPT
        or "1 question per turn" in SYSTEM_PROMPT
    )
    assert has_cap, "Ask-back cap rule (1 question per turn) missing"


def test_prompt_under_token_budget():
    """The full system prompt must stay under 1200 tokens. Budget bumped
    from 1100 to 1200 in 2026-06-05 after switching the EXAMPLES from
    mock DMA names (Zone-1..4) to real Macau names (澳門低區, 路氹城區,
    澳大橫琴區, 澳門填海A區) — Chinese names tokenize ~3x heavier than
    ASCII aliases, so the same example count costs ~50 more tokens.
    1200 still leaves room for future additions (~12% headroom)."""
    from agent.agent_executor import SYSTEM_PROMPT
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o-mini")
        n = len(enc.encode(SYSTEM_PROMPT))
    except ImportError:
        # Fallback: rough char/4 estimate
        n = len(SYSTEM_PROMPT) // 4
    assert n < 1200, f"Prompt tokens {n} exceeded budget 1200"
