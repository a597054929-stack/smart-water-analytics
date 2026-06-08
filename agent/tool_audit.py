"""Audit log for tool calls. One JSON line per call.

Why:
- In production, an agent may run hundreds of tool calls per session.
  When something goes wrong ("why did it read that file?"), we need
  a forensic trail.
- Per Claude Code's "audit log" design point: every tool call should
  record (tool, params-keys, duration, success, error, output size).
- We log *params_keys* instead of *params* values to avoid leaking
  sensitive data into the log file.

Format: JSONL (one JSON object per line). Default path
``logs/tool_audit.log``; overridable for tests via ``AUDIT_LOG`` env
or direct attribute assignment on the module.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

AUDIT_LOG = Path(os.environ.get("WATER_AUDIT_LOG", "logs/tool_audit.log"))


def log_tool_call(
    tool_name,
    params,
    duration_ms,
    success,
    error=None,
    output_bytes=0,
) -> None:
    """Append a single JSON line to the audit log."""
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "tool": tool_name,
        "params_keys": list(params.keys()) if isinstance(params, dict) else None,
        "duration_ms": int(duration_ms),
        "success": bool(success),
        "error": error,
        "output_bytes": int(output_bytes),
    }
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = ["log_tool_call", "AUDIT_LOG"]
