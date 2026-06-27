import functools
import json
import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from typing import Any, Callable

_LOG_RECORD_BUILTIN_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

_LOG_RECORD_RESERVED = frozenset({"loggerName", "timestamp", "function", "file", "line"})


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _LOG_RECORD_BUILTIN_ATTRS and k not in _LOG_RECORD_RESERVED
        }
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            payload["exc"] = "".join(traceback.format_exception(*record.exc_info))
        if extras:
            payload["extra"] = extras
        return json.dumps(payload, ensure_ascii=False)


_LOG_DIR = os.environ.get("STUDYPLAN_LOG_DIR", "")
if not _LOG_DIR:
    _config_home = os.environ.get("STUDYPLAN_CONFIG_HOME", os.path.expanduser("~/.config/studyplan"))
    _LOG_DIR = os.path.join(_config_home, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_APP_LOG = os.path.join(_LOG_DIR, "app.log")
_JSON_LOG = os.path.join(_LOG_DIR, "app.jsonl")

_logger = logging.getLogger("studyplan")
_logger.setLevel(logging.DEBUG)
_logger.handlers.clear()

_text_handler = RotatingFileHandler(
    _APP_LOG,
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_text_handler.setLevel(logging.DEBUG)
_text_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
)
_logger.addHandler(_text_handler)

_json_handler = RotatingFileHandler(
    _JSON_LOG,
    maxBytes=5 * 1024 * 1024,
    backupCount=2,
    encoding="utf-8",
)
_json_handler.setLevel(logging.DEBUG)
_json_handler.setFormatter(JSONFormatter())
_logger.addHandler(_json_handler)

_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.INFO)
_stdout_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
)
_logger.addHandler(_stdout_handler)

STUDYPLAN_LOG_DIR = _LOG_DIR
STUDYPLAN_APP_LOG = _APP_LOG
STUDYPLAN_JSON_LOG = _JSON_LOG


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"studyplan.{name}")
    return _logger


def safe_json_diagnostics() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "log_dir": _LOG_DIR,
        "app_log": _APP_LOG,
        "json_log": _JSON_LOG,
        "handlers": [str(h) for h in _logger.handlers],
    }
    try:
        from studyplan.config import Config

        payload["config_home"] = str(getattr(Config, "CONFIG_HOME", ""))
    except Exception:
        pass
    return payload


class CaptureAndLog:
    """Context manager that catches exceptions and logs them instead of crashing.

    Use this to replace bare ``except Exception: pass`` blocks so that
    swallowed errors are preserved in the log for post-mortem analysis.
    """

    def __init__(self, logger: logging.Logger | None = None, msg: str = "") -> None:
        self._log = logger or _logger
        self._msg = msg or "Suppressed exception"

    def __enter__(self) -> "CaptureAndLog":
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> bool:
        if exc_type is not None:
            self._log.warning(self._msg, exc_info=(exc_type, exc_val, exc_tb))
        return True


def log_on_error(
    logger: logging.Logger | None = None,
    msg: str = "",
    default: Any = None,
) -> Callable:
    """Decorator: wrap a function so that any exception is logged.

    Returns *default* on error (or None).
    """
    _log = logger or _logger
    _msg = msg or "Function raised"

    def _decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception:
                _log.warning(_msg, exc_info=True)
                return default

        return _wrapper

    return _decorator
