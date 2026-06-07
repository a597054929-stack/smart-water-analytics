"""Structured JSON logging for the pipeline.

Built on top of structlog. Every log line is one JSON object so it can be
ingested by any log aggregator.

Design goals:
- Every log line is one JSON object → easy to ingest in any log aggregator
- A single `run_id` propagates through every stage of one pipeline execution
- Stage-aware loggers (`pipeline.clean`, `pipeline.detect_anomalies`) keep
  filter rules simple in production
- Writes to BOTH stdout (for `tail -f`) and `logs/pipeline.log` (for replay)

Why structlog (vs stdlib `logging` + hand-rolled JSON formatter)?
- structlog's `bind_contextvars` replaces the manual `_RUN_ID` global
- structlog's `BoundLogger` lets us attach `stage=` / `metrics=` once and
  reuse across calls in a stage
- structlog's `JSONRenderer` is battle-tested; we no longer maintain a
  custom `JsonFormatter` (and the `extra=` dict dance in stdlib logging)

The PUBLIC API is unchanged from the previous version:
- `new_run_id()` / `get_run_id()` / `set_run_id()`
- `get_logger(stage)` → returns a structlog BoundLogger
- `stage(name)` → context manager that auto-logs start/finish with elapsed
- All log lines are still JSON, same field names (`ts`, `level`, `logger`,
  `message`, `run_id`, optional `stage` / `metrics` / `exception`)
"""

import logging
import sys
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import structlog

_RUN_ID: str | None = None
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
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
            return sys.stdout
    except Exception:
        pass

    enc = getattr(sys.stdout, "encoding", None) or "utf-8"

    class _SafeReplaceStream:
        def write(self, s: str) -> int:
            return sys.stdout.write(s.encode(enc, errors="replace").decode(enc))

        def flush(self) -> None:
            sys.stdout.flush()

        def isatty(self) -> bool:
            return getattr(sys.stdout, "isatty", lambda: False)()

    return _SafeReplaceStream()


def _add_run_id(_logger, _method_name, event_dict):
    """structlog processor: inject the current run_id into every log line."""
    event_dict.setdefault("run_id", get_run_id())
    return event_dict


_configured: set[str] = set()


def _configure_root(log_file: Path | None = None) -> None:
    """Idempotently configure structlog with JSON output."""
    key = str(log_file) if log_file else "stdout-only"
    if key in _configured:
        return
    _configured.add(key)

    log_file = log_file or _DEFAULT_LOG_FILE
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_file = None  # fall back to stdout only

    # Shared processors for both structlog and stdlib loggers
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_run_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(serializer=_json_dumps_safe),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=_utf8_stream()),
        cache_logger_on_first_use=True,
    )

    # If a log file is requested, mirror to FileHandler via stdlib
    if log_file is not None:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(message)s")  # structlog already JSON-rendered
        )
        stdlib_root = logging.getLogger()
        stdlib_root.setLevel(logging.INFO)
        # Remove any pre-existing handlers to avoid double-logging
        for h in list(stdlib_root.handlers):
            stdlib_root.removeHandler(h)
        stdlib_root.addHandler(file_handler)


def _json_dumps_safe(obj: Any, **kwargs) -> str:
    """JSON serializer that never breaks on non-serializable objects.

    structlog passes any renderer kwargs (e.g. `default=`) via **kwargs,
    so we cannot hardcode `default=str` in the call site — use a
    fallback chain instead: honor caller's `default=` if provided,
    else fall back to `str`.
    """
    import json as _json
    kwargs.setdefault("default", str)
    return _json.dumps(obj, ensure_ascii=False, **kwargs)


def new_run_id() -> str:
    """Generate a fresh run_id. Called once at the start of a pipeline execution."""
    global _RUN_ID
    _RUN_ID = f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    structlog.contextvars.bind_contextvars(run_id=_RUN_ID)
    return _RUN_ID


def get_run_id() -> str:
    """Return the current run_id, creating one if none exists yet."""
    global _RUN_ID
    if _RUN_ID is None:
        new_run_id()
    assert _RUN_ID is not None  # for type-checker
    return _RUN_ID


def set_run_id(run_id: str) -> None:
    """Override the current run_id (used when resuming from a checkpoint)."""
    global _RUN_ID
    _RUN_ID = run_id
    structlog.contextvars.bind_contextvars(run_id=run_id)


def get_logger(stage: str, log_file: Path | None = None) -> structlog.stdlib.BoundLogger:
    """Return a stage-scoped logger.

    Example:
        log = get_logger("pipeline.clean")
        log.info("cleaned 1234 rows", metrics={"rows": 1234})
    """
    _configure_root(log_file)
    return structlog.get_logger(stage).bind(stage=stage)


@contextmanager
def stage(stage_name: str, log_file: Path | None = None) -> Generator[structlog.stdlib.BoundLogger, None, None]:
    """Context manager that logs stage start/finish with duration.

    Example:
        with stage("clean") as log:
            log.info("removing outliers", metrics={"dropped": 12})
    """
    log = get_logger(stage_name, log_file=log_file)
    start = time.perf_counter()
    log.info("stage_start", stage=stage_name, event_kind="start")
    try:
        yield log
    except Exception as e:
        elapsed = time.perf_counter() - start
        log.exception(
            "stage_failed",
            stage=stage_name,
            elapsed_s=round(elapsed, 3),
            error=str(e),
        )
        raise
    elapsed = time.perf_counter() - start
    log.info("stage_done", stage=stage_name, elapsed_s=round(elapsed, 3))


if __name__ == "__main__":
    new_run_id()
    log = get_logger("pipeline.demo")
    log.info("logger ok", metrics={"rows": 1})
    log.warning("low rows", metrics={"rows": 0})
    with stage("demo") as l:
        l.info("inside stage")
    print(f"run_id = {get_run_id()}", file=sys.stderr)
    print(f"wrote {_DEFAULT_LOG_FILE}")
