"""Shared pytest fixtures for the test suite.

Centralizes the most common fixtures so individual test modules don't
have to redefine them:

- `ROOT` / `sys.path` injection — so `import pipeline` works whether
  tests are run from repo root or from inside `tests/`
- `tmp_ckpt` — fresh checkpoint dir per test (used by orchestrator tests)
- `db_path` — temporary SQLite path, used by DB-loading tests
- `pipeline_output` — module-scoped fixture that runs the full pipeline
  once and exposes the JSON artifacts (used by regression tests)

If a test needs something project-specific, define it next to the test
rather than here — keep this file small.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "agent"

# Ensure repo root is importable for `import pipeline`, `import agent`, etc.
# Idempotent: harmless if it's already there.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# agent/ uses bare imports (e.g. `from agent_tools import ALL_TOOLS`),
# expecting cwd==agent. Inject agent/ so the modules load under pytest too.
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def tmp_ckpt(tmp_path: Path) -> Path:
    """A fresh checkpoint dir per test. Used by orchestrator tests."""
    ckpt = tmp_path / "checkpoints"
    ckpt.mkdir()
    return ckpt


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A fresh SQLite path per test. The file is not created — loaders
    that take a path are responsible for opening it."""
    return tmp_path / "test_analytics.db"


@pytest.fixture(scope="module")
def pipeline_output():
    """Run the full pipeline once for the whole module, then expose the
    JSON artifacts as a dict keyed by stage name.

    Tests that need a fully-built set of pipeline outputs (regression
    checks) should depend on this. Tests that want to *re-run* the
    pipeline with different parameters should use `tmp_ckpt` and call
    `pipeline.orchestrator.run(...)` directly.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pipeline.orchestrator", "--force"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, f"Pipeline failed: {result.stderr}"

    output_dir = ROOT / "backend" / "data" / "output"
    artifacts: dict[str, list] = {}
    if output_dir.is_dir():
        for path in output_dir.glob("*.json"):
            import json
            try:
                artifacts[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Non-data JSON files (e.g. summary) — skip silently
                pass
    return artifacts


# ── Mock LLM for harness tests (added 2026-06-08, see ADR-0004) ──

# Keywords for tool selection. The order matters — more specific first.
_PLANNER_KEYWORDS = [
    # (kw_substring, tool_name, default_params)
    ("对比", "compare_months", {}),
    ("compare", "compare_months", {}),
    ("睇下", "query_anomalies", {"dma": "Zone-3"}),
    ("drop", "get_data_overview", {}),
    ("delete", "get_data_overview", {}),
    ("删", "get_data_overview", {}),
    ("ignore", "get_data_overview", {}),
    ("prompt", "get_data_overview", {}),
    ("母子表", "query_monthly_diff", {}),
    ("monthly_diff", "query_monthly_diff", {}),
    ("月差", "query_monthly_diff", {}),
    ("building_predictions", "get_building_predictions", {}),
    ("建筑预测", "get_building_predictions", {}),
    ("大厦", "get_building_predictions", {}),
    ("预测", "get_predictions", {}),
    ("predict", "get_predictions", {}),
    ("anomal", "query_anomalies", {"dma": "Zone-3"}),
    ("异常", "query_anomalies", {"dma": "Zone-3"}),
    ("rank", "query_rank_changes", {}),
    ("排名", "query_rank_changes", {}),
    ("weekly", "query_weekly", {}),
    ("周", "query_weekly", {}),
    ("daily_dma", "query_daily_dma", {}),
    ("meter 7", "get_predictions", {"meter_id": "753832"}),
    ("meter", "query_meters", {}),
    ("水表", "query_meters", {}),
    ("overview", "get_data_overview", {}),
    ("总览", "get_data_overview", {}),
    ("用水", "query_daily_dma", {}),
]


def _plan_for(question: str) -> list:
    """Return a mock plan based on keyword matching against the question.

    The ``question`` may be the raw user input OR the augmented version
    (with ``[PAGE CONTEXT]...`` prefix added by ``run_multi_agent``).
    We always try keyword matching first — the length guard only kicks
    in for inputs that are genuinely too long (>500 chars) to be a
    real user question (e.g. the 200-word ``"用水 用水 ..."`` case).
    """
    # Guard: very long inputs (>500 chars) default to overview.
    # Real LLMs treat a 200-word repetition as a general request.
    if len(question) > 500:
        return [{"tool": "get_data_overview", "params": {}}]
    q = question.lower()
    for kw, tool, params in _PLANNER_KEYWORDS:
        if kw in q or kw in question:
            return [{"tool": tool, "params": params}]
    return [{"tool": "get_data_overview", "params": {}}]


def _synth_for(question: str) -> str:
    """Return a mock synthesis. Mirror the question's content flag."""
    low = question.lower()
    # ── C. privilege-escalation rejection ──
    # Must come BEFORE generic tool-match so refusals override defaults.
    dangerous_kw = [
        "删", "delete", "drop", "清除", "重置", "reset",
        "ignore", "prompt", "system", "instruction",
        "os.system", "exec", "eval", "import os", "rm -rf",
        "gpt-4",
    ]
    config_kw = [
        "model 换", "换 model", "api_key", "secret",
        "password", "模型", "config", "配置", "把 model",
        "读 .env", "读取 .env", ".env",
    ]
    is_dangerous = any(kw in question or kw in low for kw in dangerous_kw)
    is_config = any(kw in question or kw in low for kw in config_kw)
    if is_dangerous or is_config:
        return "我无法执行此操作 — 出于安全考虑，agent 不能修改数据库、删除数据、读取敏感文件、修改配置或透露系统 prompt。请使用仪表盘的搜索和分析功能查询。"
    if not question.strip():
        return "请输入具体的水表号、时间范围或区域 (Zone-3 / 澳門低區 ...)"
    # Detect ambiguous inputs: short, no specific entity
    has_entity = any(
        kw in question
        for kw in ["Zone", "zone", "区域", "澳門", "路氹", "meter", "表号",
                    "大厦", "塔", "酒店", "3 月", "4 月", "2026", "2026-05",
                    "5 月", "5月", "05", "monthly", "weekly", "daily"]
    )
    if not has_entity and len(question.strip()) < 10:
        return "请提供更具体的水务问题 — 比如「Zone-3 异常」「预测 meter 753832」「对比 3 月 4 月」。"
    return f"已查询：{question[:50]}（mock 合成结果）"


@pytest.fixture
def mock_llm(monkeypatch):
    """Replace agent.multi_agent.ChatOpenAI with a deterministic mock.

    The mock dispatches on system-prompt content:
    - "planning agent"   →  plan() call → return plan JSON based on keywords
    - "synthesis agent"  →  synthesize() call → return string
    """
    from unittest.mock import MagicMock

    class _FakeLLM:
        """Looks like a ChatOpenAI instance from the planner's POV."""

        def __init__(self, *args, **kwargs):
            self._invokes: list[list] = []

        def invoke(self, messages):
            self._invokes.append(messages)
            # Find the system message and the user message
            system_content = ""
            user_content = ""
            for m in messages:
                c = getattr(m, "content", "") or ""
                # langchain_core sets `type` = "system" / "human" / "ai"
                mtype = getattr(m, "type", None) or ""
                if mtype == "system":
                    if "planning" in c.lower() or "planner" in c.lower():
                        system_content = "planner"
                    elif "synthesis" in c.lower() or "synthesizer" in c.lower():
                        system_content = "synthesizer"
                elif mtype == "human":
                    user_content = c
            if system_content == "planner":
                plan = _plan_for(user_content)
                import json as _json
                return MagicMock(content=_json.dumps(plan))
            if system_content == "synthesizer":
                # The user_content here is the full synth context, which
                # starts with "User question: <q>\n\n...". Extract the
                # actual question so the mock can make the right decision.
                import re as _re
                m = _re.search(r"User question:\s*(.+?)(?:\n|$)", user_content)
                if m:
                    question = m.group(1).strip()
                else:
                    question = user_content
                return MagicMock(content=_synth_for(question))
            # default
            return MagicMock(content="")

    # Patch the ChatOpenAI symbol used inside multi_agent.run_multi_agent
    monkeypatch.setattr("agent.multi_agent.ChatOpenAI", _FakeLLM)
    # Also patch get_llm_config so it returns a harmless dict
    monkeypatch.setattr(
        "agent.multi_agent.get_llm_config",
        lambda: {"provider": "openai", "model": "mock", "api_key": "sk-mock", "base_url": ""},
    )
    return _FakeLLM()
