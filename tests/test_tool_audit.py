"""Unit tests for the tool-sandbox layer (path check + audit log)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent.dangerous_paths import is_dangerous, scan_args


def test_dangerous_env_blocked():
    assert is_dangerous(".env") is True
    assert is_dangerous("auth.json") is True
    assert is_dangerous("secrets.yaml") is True


def test_windows_system_blocked():
    assert is_dangerous("C:/Windows/System32/foo") is True
    assert is_dangerous("/etc/passwd") is True


def test_safe_path_allowed(monkeypatch):
    monkeypatch.setenv("WATER_DATA_DIR", "")
    assert is_dangerous("backend/data/output_real/foo.json") is False
    assert is_dangerous("agent/agent_tools.py") is False


def test_path_traversal_blocked():
    assert is_dangerous("../../../etc/passwd") is True


def test_scan_args_dict():
    with pytest.raises(PermissionError):
        scan_args({"file_path": ".env"})
    # Safe path should not raise
    scan_args({"file_path": "agent/agent_tools.py"})


def test_scan_args_ignores_non_strings():
    # Should not raise on int/bool
    scan_args({"limit": 10, "is_residential": True})


def test_audit_log_creates_file(tmp_path, monkeypatch):
    test_log = tmp_path / "test_audit.log"
    from agent.tool_audit import log_tool_call
    monkeypatch.setattr("agent.tool_audit.AUDIT_LOG", test_log)
    log_tool_call("test_tool", {"k": "v"}, 42, True)
    assert test_log.exists()
    entry = json.loads(test_log.read_text().strip())
    assert entry["tool"] == "test_tool"
    assert entry["duration_ms"] == 42
    assert entry["success"] is True


def test_audit_log_on_failure(tmp_path, monkeypatch):
    test_log = tmp_path / "test_audit.log"
    from agent.tool_audit import log_tool_call
    monkeypatch.setattr("agent.tool_audit.AUDIT_LOG", test_log)
    log_tool_call("test_tool", {}, 100, False, error="boom")
    entry = json.loads(test_log.read_text().strip())
    assert entry["success"] is False
    assert entry["error"] == "boom"


def test_safe_tool_call_passes_through():
    from agent.safe_tool_call import safe_tool_call
    @safe_tool_call("noop", timeout_seconds=5)
    def add(a, b):
        return a + b
    assert add(2, 3) == 5


def test_safe_tool_call_audit_on_success(tmp_path, monkeypatch):
    test_log = tmp_path / "test_audit.log"
    from agent import tool_audit
    monkeypatch.setattr(tool_audit, "AUDIT_LOG", test_log)
    from agent.safe_tool_call import safe_tool_call
    @safe_tool_call("doubler", timeout_seconds=5)
    def doubler(x):
        return x * 2
    assert doubler(x=21) == 42
    entry = json.loads(test_log.read_text().strip())
    assert entry["tool"] == "doubler"
    assert entry["success"] is True
    assert entry["error"] is None
    assert entry["params_keys"] == ["x"]


def test_safe_tool_call_blocks_dangerous_path(tmp_path, monkeypatch):
    test_log = tmp_path / "test_audit.log"
    from agent import tool_audit
    monkeypatch.setattr(tool_audit, "AUDIT_LOG", test_log)
    from agent.safe_tool_call import safe_tool_call
    @safe_tool_call("reader", timeout_seconds=5)
    def reader(file_path):
        return open(file_path).read()
    with pytest.raises(PermissionError):
        reader(".env")
    entry = json.loads(test_log.read_text().strip())
    assert entry["success"] is False
    assert "dangerous" in entry["error"].lower()
