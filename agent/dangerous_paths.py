"""Lightweight path sandbox for agent tool arguments.

Why this exists:
- The agent can call tools with arbitrary user-supplied strings
  (e.g. a user might say "look at the file at C:/Users/.../creds.txt").
- A prompt-injection attack could trick the LLM into reading
  ``.env`` or ``~/.ssh/id_rsa`` and exfiltrating the contents.
- We can't trust the LLM to refuse — we enforce at the tool boundary.

Three layers of defense, evaluated in order:
  1. Deny by filename          (``.env``, ``id_rsa``, ``secrets.yaml`` …)
  2. Deny by substring          (``.pem``, ``.key``, ``password``, ``secret``)
  3. Deny by path prefix        (``/etc``, ``/usr``, ``C:/Windows/...``)
  4. Deny by resolved path      (anything outside the project root, unless
                                 ``WATER_DATA_DIR`` env var allows it)

The ``scan_args`` helper applies these checks to tool-call kwargs
heuristically — any key ending in ``_path`` / ``_file`` / ``filename`` /
``dir`` OR any string value containing a path separator.
"""

from __future__ import annotations

import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_DENY_FILENAMES = {
    ".env", ".env.local", ".env.production",
    "auth.json", "credentials.json",
    "id_rsa", "id_rsa.pub",
    "secrets.yaml", "secrets.yml",
}
_DENY_PREFIXES = (
    "c:/windows", "c:\\windows",
    "/etc", "/usr", "/var", "/proc", "/sys", "/root", "/boot",
)
_DENY_SUBSTRINGS = (".pem", ".key", "password", "secret")

# Keys that look like they carry a path. Heuristic — false positives
# are OK (we'd rather over-block a tool call than leak a secret).
_PATH_KEY_SUFFIXES = ("_path", "_file", "filename", "dir")


def is_dangerous(path) -> bool:
    """Return True if ``path`` looks like a sensitive filesystem location."""
    if path is None:
        return False
    s = os.fspath(path).strip()
    if not s:
        return False
    s_norm = s.replace("\\", "/").lower()
    base = os.path.basename(s_norm)
    if base in _DENY_FILENAMES:
        return True
    if any(sub in base for sub in _DENY_SUBSTRINGS):
        return True
    for p in _DENY_PREFIXES:
        if s_norm.startswith(p):
            return True
    try:
        resolved = os.path.abspath(s)
        if not resolved.startswith(PROJECT_ROOT + os.sep) and resolved != PROJECT_ROOT:
            data_dir = os.environ.get("WATER_DATA_DIR", "")
            if data_dir and resolved.startswith(os.path.abspath(data_dir)):
                return False
            return True
    except (OSError, ValueError):
        return True
    return False


def assert_safe(path) -> None:
    """Raise ``PermissionError`` if ``path`` is dangerous."""
    if is_dangerous(path):
        raise PermissionError(f"Refused to access '{path}': dangerous path")


def scan_args(args: dict) -> None:
    """Scan tool-call args for path-typed values; raise if any are dangerous.

    Heuristic: any key ending in ``_path`` / ``_file`` / ``filename`` /
    ``dir`` is treated as a path. Additionally, any string value
    containing ``/`` or ``\\`` is checked (catches free-form path
    arguments like ``file=``).
    """
    for k, v in list(args.items()):
        if not isinstance(v, str):
            continue
        if k.lower().endswith(_PATH_KEY_SUFFIXES) or ("/" in v or "\\" in v):
            assert_safe(v)


__all__ = ["is_dangerous", "assert_safe", "scan_args", "PROJECT_ROOT"]
