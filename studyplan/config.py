import os
from enum import Enum


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


def _env_text(name: str, default: str = "") -> str:
    raw = os.getenv(name, default)
    text = str(raw or "").strip()
    return text if text else str(default or "")


def _parse_environment(default: Environment = Environment.DEV) -> Environment:
    raw = _env_text("STUDYPLAN_ENV", default.value).lower()
    for option in Environment:
        if option.value == raw:
            return option
    return default


def _parse_bool(name: str, default: bool = False) -> bool:
    raw = _env_text(name, "1" if default else "0").lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _parse_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int(_env_text(name, str(default)))
    except Exception:
        value = int(default)
    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


def _parse_float(
    name: str,
    default: float,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    try:
        value = float(_env_text(name, str(default)))
    except Exception:
        value = float(default)
    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


class Config:
    """Centralized configuration with environment-aware defaults."""

    ENV = _parse_environment()

    # Performance monitoring
    PERF_MONITOR_ENABLED = ENV in {Environment.DEV, Environment.STAGING}
    PERF_THRESHOLDS = {
        "state_validation": 10.0,
        "state_persistence": 50.0,
        "assess": 20.0,
        "practice_item_build": 30.0,
        "posterior_update": 5.0,
    }

    # Import security
    SECURE_IMPORT_ENABLED = True
    SECURE_IMPORT_ALLOWED_DIRS = ["./data", "./cache"]
    SECURE_IMPORT_MAX_SIZE_MB = 100
    SECURE_IMPORT_ALLOWED_EXTENSIONS = {".json", ".jsonl", ".csv"}

    # Persistence
    PERSISTENCE_SCHEMA_VERSION = 1
    PERSISTENCE_BASE_PATH = os.getenv("STUDYPLAN_DATA_PATH", "./data/state")
    PERSISTENCE_ENABLE_MIGRATIONS = True

    # Logging
    LOG_LEVEL = _env_text(
        "STUDYPLAN_LOG_LEVEL",
        "INFO" if ENV == Environment.PROD else "DEBUG",
    ).upper()

    # Llama.cpp (OpenAI-compatible endpoint) runtime controls.
    LLAMA_CPP_ENABLED = _parse_bool("STUDYPLAN_LLAMA_CPP_ENABLED", default=True)
    LLAMA_CPP_ENDPOINT = _env_text(
        "STUDYPLAN_LLAMA_CPP_ENDPOINT",
        "http://127.0.0.1:8080/v1/chat/completions",
    )
    LLAMA_CPP_MODEL = _env_text(
        "STUDYPLAN_LLAMA_CPP_MODEL",
        "llama3.1:8b-instruct-q4_k_m",
    )
    LLAMA_CPP_CONTEXT_WINDOW = _parse_int(
        "STUDYPLAN_LLAMA_CPP_CONTEXT_WINDOW",
        8192,
        min_value=512,
        max_value=32768,
    )
    LLAMA_CPP_TIMEOUT_SECONDS = _parse_float(
        "STUDYPLAN_LLAMA_CPP_TIMEOUT_SECONDS",
        30.0,
        min_value=1.0,
        max_value=300.0,
    )
    LLAMA_CPP_MAX_RETRIES = _parse_int(
        "STUDYPLAN_LLAMA_CPP_MAX_RETRIES",
        2,
        min_value=0,
        max_value=5,
    )
    LLAMA_CPP_TEMPERATURE = _parse_float(
        "STUDYPLAN_LLAMA_CPP_TEMPERATURE",
        0.2,
        min_value=0.0,
        max_value=2.0,
    )
    LLAMA_CPP_TOP_P = _parse_float(
        "STUDYPLAN_LLAMA_CPP_TOP_P",
        0.95,
        min_value=0.0,
        max_value=1.0,
    )
    LLAMA_CPP_AUTO_MODEL_DISCOVERY = _parse_bool(
        "STUDYPLAN_LLAMA_CPP_AUTO_MODEL_DISCOVERY",
        default=True,
    )
    LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED = _parse_bool(
        "STUDYPLAN_LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED",
        default=True,
    )
    LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED = _parse_bool(
        "STUDYPLAN_LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED",
        default=True,
    )
    LLAMA_CPP_OLLAMA_HOST = _env_text(
        "STUDYPLAN_LLAMA_CPP_OLLAMA_HOST",
        os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
    )
    LLAMA_CPP_GPT4ALL_MODELS_DIR = _env_text(
        "STUDYPLAN_LLAMA_CPP_GPT4ALL_MODELS_DIR",
        os.path.expanduser("~/.local/share/nomic.ai/GPT4All"),
    )
    LLAMA_CPP_MODEL_PREFERENCE = _env_text(
        "STUDYPLAN_LLAMA_CPP_MODEL_PREFERENCE",
        "fast_cpp",
    ).lower()
    LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS = _parse_float(
        "STUDYPLAN_LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS",
        120.0,
        min_value=5.0,
        max_value=3600.0,
    )

    # llama.cpp-first: managed server & direct-GGUF runtime
    LLAMA_CPP_MANAGED_SERVER = _parse_bool("STUDYPLAN_LLAMA_CPP_MANAGED_SERVER", default=True)
    LLAMA_CPP_SERVER_BIN = _env_text("STUDYPLAN_LLAMA_SERVER_BIN", "")
    LLAMA_CPP_SERVER_PORT = _parse_int(
        "STUDYPLAN_LLAMA_SERVER_PORT", 8090, min_value=1024, max_value=65535,
    )
    LLAMA_CPP_SERVER_THREADS = _parse_int(
        "STUDYPLAN_LLAMA_SERVER_THREADS",
        max(1, min(os.cpu_count() or 4, 6)),
        min_value=1,
        max_value=32,
    )
    LLAMA_CPP_SERVER_CTX_SIZE = _parse_int(
        "STUDYPLAN_LLAMA_SERVER_CTX_SIZE", 4096, min_value=512, max_value=32768,
    )
    LLAMA_CPP_SERVER_STARTUP_TIMEOUT = _parse_float(
        "STUDYPLAN_LLAMA_SERVER_STARTUP_TIMEOUT", 60.0, min_value=10.0, max_value=180.0,
    )
    LLAMA_CPP_OLLAMA_MANIFESTS_DIR = _env_text(
        "STUDYPLAN_LLAMA_CPP_OLLAMA_MANIFESTS_DIR",
        os.path.expanduser("~/.ollama/models/manifests/registry.ollama.ai/library"),
    )
    LLAMA_CPP_OLLAMA_BLOBS_DIR = _env_text(
        "STUDYPLAN_LLAMA_CPP_OLLAMA_BLOBS_DIR",
        os.path.expanduser("~/.ollama/models/blobs"),
    )
    LLAMA_CPP_EXTRA_GGUF_DIR = _env_text("STUDYPLAN_LLAMA_CPP_EXTRA_GGUF_DIR", "")
    LLAMA_CPP_OLLAMA_FALLBACK = _parse_bool(
        "STUDYPLAN_LLAMA_CPP_OLLAMA_FALLBACK", default=True,
    )
    LLAMA_CPP_RAM_BUDGET_MB = _parse_int(
        "STUDYPLAN_LLAMA_CPP_RAM_BUDGET_MB", 0, min_value=0, max_value=65536,
    )

    # Performance caching configuration
    PERFORMANCE_CACHE_ENABLED = _parse_bool("STUDYPLAN_PERFORMANCE_CACHE_ENABLED", default=True)
    PERFORMANCE_CACHE_MAX_SIZE = _parse_int("STUDYPLAN_PERFORMANCE_CACHE_MAX_SIZE", 1000, min_value=100, max_value=10000)
    PERFORMANCE_CACHE_DEFAULT_TTL_SECONDS = _parse_int("STUDYPLAN_PERFORMANCE_CACHE_DEFAULT_TTL_SECONDS", 300, min_value=60, max_value=3600)
    PERFORMANCE_CACHE_TTL_CONFIG = {
        "cognitive_state": _parse_int("STUDYPLAN_PERFORMANCE_CACHE_TTL_COGNITIVE_STATE", 300, min_value=60, max_value=1800),
        "hint_strategy": _parse_int("STUDYPLAN_PERFORMANCE_CACHE_TTL_HINT_STRATEGY", 600, min_value=120, max_value=3600),
        "ui_render": _parse_int("STUDYPLAN_PERFORMANCE_CACHE_TTL_UI_RENDER", 30, min_value=5, max_value=300),
        "pdf_text": _parse_int("STUDYPLAN_PERFORMANCE_CACHE_TTL_PDF_TEXT", 3600, min_value=300, max_value=7200),
        "rag_doc": _parse_int("STUDYPLAN_PERFORMANCE_CACHE_TTL_RAG_DOC", 1800, min_value=300, max_value=7200),
        "ollama": _parse_int("STUDYPLAN_PERFORMANCE_CACHE_TTL_OLLAMA", 120, min_value=10, max_value=1800),
        "coach_pick": _parse_int("STUDYPLAN_PERFORMANCE_CACHE_TTL_COACH_PICK", 300, min_value=30, max_value=600),
    }
