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

# Ensure repo root is importable for `import pipeline`, `import agent`, etc.
# Idempotent: harmless if it's already there.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
