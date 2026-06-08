"""Decorator that wraps tool functions with timeout + audit + path check.

Why three things in one decorator:
- A single decoration point keeps the 16 tool definitions in
  ``agent_tools.py`` terse — ``@safe_tool_call("name", timeout=30)``
  on top of ``@tool``.
- Path check is sync (must run before the function), audit log is
  per-call, timeout is a watchdog against runaway tool calls.

Windows quirk: ``signal.alarm`` is unavailable, so we use a
``threading.Thread`` with ``.join(timeout=...)``. The thread cannot
be killed mid-flight in CPython, but we stop waiting — the agent
moves on while the runaway call eventually finishes (or OOMs, but
at least the agent isn't blocked).

Order of operations in the wrapper:
  1. Path check       (sync, raises immediately on dangerous path)
  2. Run tool         (with thread-based timeout)
  3. Audit log        (always, even on failure/timeout)
"""

from __future__ import annotations

import functools
import threading
import time

try:
    from agent.tool_audit import log_tool_call
    from agent.dangerous_paths import assert_safe, scan_args
except ImportError:
    # Fallback for when this module is imported bare (cwd == agent/),
    # e.g. when the bat files start the server with `cd agent`.
    from tool_audit import log_tool_call  # type: ignore
    from dangerous_paths import assert_safe, scan_args  # type: ignore


class ToolTimeoutError(Exception):
    """Raised when a tool call exceeds the configured timeout."""


def _run_with_timeout(func, args, kwargs, timeout_seconds):
    """Run ``func`` in a daemon thread; raise ``ToolTimeoutError`` if it overruns."""
    result = {"value": None, "exception": None}

    def target():
        try:
            result["value"] = func(*args, **kwargs)
        except Exception as e:  # propagate caller-visible exceptions
            result["exception"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        # Cannot actually kill the thread on CPython, but we stop waiting.
        # The thread becomes orphaned (daemon=True → killed at interpreter exit).
        raise ToolTimeoutError(f"exceeded {timeout_seconds}s")
    if result["exception"]:
        raise result["exception"]
    return result["value"]


def safe_tool_call(tool_name: str, timeout_seconds: int = 30):
    """Decorator: add timeout + path-safety check + audit log to a tool function.

    Args:
        tool_name: human-readable name for the audit log.
        timeout_seconds: hard upper bound on the call duration. 0 disables.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            error = None
            success = True
            output = ""

            # 1. Path check (sync, before timeout)
            try:
                scan_args(kwargs)
                for v in list(args):
                    if isinstance(v, str):
                        # Direct check on positional strings — heuristic
                        # `scan_args` only fires for keys with path
                        # suffixes or values with separators, so
                        # plain ".env" passed positionally needs an
                        # explicit ``assert_safe`` call.
                        assert_safe(v)
            except PermissionError as e:
                duration_ms = int((time.time() - start) * 1000)
                log_tool_call(tool_name, kwargs, duration_ms, False, str(e), 0)
                raise

            # 2. Run with optional timeout
            try:
                if timeout_seconds and timeout_seconds > 0:
                    result = _run_with_timeout(func, args, kwargs, timeout_seconds)
                else:
                    result = func(*args, **kwargs)
                output = str(result) if result is not None else ""
                return result
            except ToolTimeoutError as e:
                success = False
                error = f"timeout after {timeout_seconds}s"
                raise
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                # 3. Audit (always, even on failure/timeout)
                duration_ms = int((time.time() - start) * 1000)
                log_tool_call(tool_name, kwargs, duration_ms, success, error, len(output))

        return wrapper
    return decorator


__all__ = ["safe_tool_call", "ToolTimeoutError"]
