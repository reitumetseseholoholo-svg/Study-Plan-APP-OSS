"""Tests for logging configuration (logging_config.py).

Covers: JSONFormatter format output, CaptureAndLog context manager,
log_on_error decorator, get_logger, and safe_json_diagnostics.
"""

from __future__ import annotations

import json
import logging


from studyplan.logging_config import (
    JSONFormatter,
    CaptureAndLog,
    get_logger,
    log_on_error,
    safe_json_diagnostics,
)


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


def test_json_formatter_basic() -> None:
    fmt = JSONFormatter()
    record = logging.LogRecord(
        name="test.name",
        level=logging.INFO,
        pathname="/test/path.py",
        lineno=42,
        msg="hello world",
        args=(),
        exc_info=None,
    )
    output = fmt.format(record)
    parsed = json.loads(output)
    assert parsed["level"] == "INFO"
    assert parsed["name"] == "test.name"
    assert parsed["msg"] == "hello world"
    assert "ts" in parsed
    assert "exc" not in parsed


def test_json_formatter_with_exception() -> None:
    fmt = JSONFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys

        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="/p.py",
        lineno=1,
        msg="error occurred",
        args=(),
        exc_info=exc_info,
    )
    output = fmt.format(record)
    parsed = json.loads(output)
    assert parsed["level"] == "ERROR"
    assert parsed["msg"] == "error occurred"
    assert "exc" in parsed
    assert "ValueError" in parsed["exc"]
    assert "test error" in parsed["exc"]


def test_json_formatter_with_extras() -> None:
    fmt = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="/p.py",
        lineno=1,
        msg="with extra",
        args=(),
        exc_info=None,
    )
    record.extra_field = "extra_value"  # type: ignore[attr-defined]
    output = fmt.format(record)
    parsed = json.loads(output)
    assert parsed["level"] == "WARNING"
    assert parsed["msg"] == "with extra"
    assert parsed["extra"] == {"extra_field": "extra_value"}


def test_json_formatter_skips_reserved_keys() -> None:
    fmt = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="/p.py",
        lineno=1,
        msg="reserved test",
        args=(),
        exc_info=None,
    )
    record.loggerName = "should_not_appear"  # type: ignore[attr-defined]
    record.timestamp = 12345  # type: ignore[attr-defined]
    output = fmt.format(record)
    parsed = json.loads(output)
    assert "loggerName" not in parsed
    if "extra" in parsed:
        assert "loggerName" not in parsed["extra"]
        assert "timestamp" not in parsed["extra"]


# ---------------------------------------------------------------------------
# CaptureAndLog
# ---------------------------------------------------------------------------


def test_capture_and_log_no_exception() -> None:
    log = logging.getLogger("test_capture")
    with CaptureAndLog(log, "test msg") as cap:
        pass
    assert cap is not None  # no exception, clean exit


def test_capture_and_log_suppresses_exception() -> None:
    log = logging.getLogger("test_capture_suppress")
    with CaptureAndLog(log, "caught"):
        raise ValueError("should be caught")
    # Should not propagate — we're past the context manager


def test_capture_and_log_default_logger() -> None:
    """Uses the root studyplan logger if none provided."""
    with CaptureAndLog(msg="default logger test") as cap:
        pass
    assert cap is not None


# ---------------------------------------------------------------------------
# log_on_error
# ---------------------------------------------------------------------------


def test_log_on_error_success() -> None:
    @log_on_error(default=None)
    def add(a: int, b: int) -> int:
        return a + b

    assert add(3, 4) == 7


def test_log_on_error_exception_returns_default() -> None:
    @log_on_error(default="fallback")
    def crash() -> str:
        raise RuntimeError("boom")

    assert crash() == "fallback"


def test_log_on_error_no_default() -> None:
    @log_on_error()
    def crash() -> str:
        raise RuntimeError("boom")

    assert crash() is None


def test_log_on_error_custom_logger() -> None:
    log = logging.getLogger("test_log_on_error")
    call_count: list[int] = [0]

    class TrackingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            call_count[0] += 1

    log.addHandler(TrackingHandler())
    log.setLevel(logging.WARNING)

    @log_on_error(logger=log, msg="custom logger")
    def crash() -> str:
        raise ValueError("tracked")

    crash()
    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


def test_get_logger_root() -> None:
    log = get_logger()
    assert log.name == "studyplan"


def test_get_logger_sub() -> None:
    log = get_logger("ai")
    assert log.name == "studyplan.ai"


# ---------------------------------------------------------------------------
# safe_json_diagnostics
# ---------------------------------------------------------------------------


def test_safe_json_diagnostics() -> None:
    diag = safe_json_diagnostics()
    assert isinstance(diag, dict)
    assert "log_dir" in diag
    assert "app_log" in diag
    assert "json_log" in diag
    assert "handlers" in diag
    assert isinstance(diag["handlers"], list)
    assert len(diag["handlers"]) > 0
    assert all(isinstance(h, str) for h in diag["handlers"])
