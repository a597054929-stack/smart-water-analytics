"""Structured JSON logging for the pipeline.

Design goals:
- Every log line is one JSON object → easy to ingest in any log aggregator
- A single `run_id` propagates through every stage of one pipeline execution
- Stage-aware loggers (`pipeline.clean`, `pipeline.detect_anomalies`) keep
  filter rules simple in production
- Writes to BOTH stdout (for `tail -f`) and `logs/pipeline.log` (for replay)

Why JSON?
- In HKT's production observability stack, every component emits JSON logs.
- Structured fields (stage, run_id, metrics) can be indexed and queried.
- No fragile regex over plain text.
"""

import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

_RUN_ID: Optional[str] = None
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_DEFAULT_LOG_FILE = _DEFAULT_LOG_DIR / "pipeline.log"


def _utf8_stream():
    """Return a stdout stream configured to encode UTF-8.

    On Windows the default stdout encoding is often cp950 / cp936 / cp1252,
    which can't encode characters like U+EBF3 (the PUA variant of 氹 that
    real Macau data sometimes uses for 路氹城區). Without this, logging
    one of those characters raises UnicodeEncodeError and the log line
    is dropped. We reconfigure if possible; otherwise wrap with
    errors="replace" so the log at least goes through.
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            return sys.stdout
    except Exception:
        pass
    return _SafeReplaceStream(sys.stdout, enc)


class _SafeReplaceStream:
    """Minimal file-like wrapper that replaces un-encodable chars with '?'."""

    def __init__(self, base, enc: str) -> None:
        self._base = base
        self._enc = enc

    def write(self, s: str) -> int:
        return self._base.write(s.encode(self._enc, errors="replace").decode(self._enc))

    def flush(self) -> None:
        self._base.flush()

    def isatty(self) -> bool:
        return getattr(self._base, "isatty", lambda: False)()


def new_run_id() -> str:
    """Generate a fresh run_id. Called once at the start of a pipeline execution."""
    global _RUN_ID
    _RUN_ID = f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    return _RUN_ID


def get_run_id() -> str:
    """Return the current run_id, creating one if none exists yet."""
    global _RUN_ID
    if _RUN_ID is None:
        _RUN_ID = new_run_id()
    return _RUN_ID


def set_run_id(run_id: str) -> None:
    """Override the current run_id (used when resuming from a checkpoint)."""
    global _RUN_ID
    _RUN_ID = run_id


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": get_run_id(),
        }
        # Optional fields (set via `extra=`)
        stage = getattr(record, "stage", None)
        if stage:
            payload["stage"] = stage
        metrics = getattr(record, "metrics", None)
        if metrics is not None:
            payload["metrics"] = metrics
        exc_info = getattr(record, "exc_info", None)
        if exc_info and record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.__dict__.get("stack_info"):
            payload["stack"] = record.stack_info
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured: set[str] = set()


def _configure_root(log_file: Optional[Path] = None) -> None:
    """Idempotently configure the root logger with our JSON formatter."""
    key = str(log_file) if log_file else "stdout-only"
    if key in _configured:
        return
    _configured.add(key)

    log_file = log_file or _DEFAULT_LOG_FILE
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_file = None  # fall back to stdout only

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = JsonFormatter()

    sh = logging.StreamHandler(_utf8_stream())
    sh.setFormatter(fmt)
    root.addHandler(sh)

    if log_file is not None:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def get_logger(stage: str, log_file: Optional[Path] = None) -> logging.Logger:
    """Return a stage-scoped logger.

    Example:
        log = get_logger("pipeline.clean")
        log.info("cleaned 1234 rows", extra={"metrics": {"rows": 1234}})
    """
    _configure_root(log_file)
    return logging.getLogger(stage)


@contextmanager
def stage(stage_name: str, log_file: Optional[Path] = None):
    """Context manager that logs stage start/finish with duration.

    Example:
        with stage("clean") as log:
            log.info("removing outliers", extra={"metrics": {"dropped": 12}})
    """
    log = get_logger(stage_name, log_file=log_file)
    start = time.perf_counter()
    log.info(
        f"stage_start: {stage_name}",
        extra={"stage": stage_name, "metrics": {"event": "start"}},
    )
    try:
        yield log
    except Exception as e:
        elapsed = time.perf_counter() - start
        log.exception(
            f"stage_failed: {stage_name}: {e}",
            extra={"stage": stage_name, "metrics": {"elapsed_s": round(elapsed, 3)}},
        )
        raise
    elapsed = time.perf_counter() - start
    log.info(
        f"stage_done: {stage_name}",
        extra={"stage": stage_name, "metrics": {"elapsed_s": round(elapsed, 3)}},
    )


if __name__ == "__main__":
    new_run_id()
    log = get_logger("pipeline.demo")
    log.info("logger ok", extra={"metrics": {"rows": 1, "stage": "demo"}})
    log.warning("low rows", extra={"stage": "demo", "metrics": {"rows": 0}})
    with stage("demo") as l:
        l.info("inside stage", extra={"stage": "demo"})
    print(f"run_id = {get_run_id()}", file=sys.stderr)
    print(f"wrote {_DEFAULT_LOG_FILE}")
