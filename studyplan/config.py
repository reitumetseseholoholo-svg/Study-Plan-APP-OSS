import os
from enum import Enum


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class Config:
    """Centralized configuration with environment-aware defaults."""

    ENV = Environment(os.getenv("STUDYPLAN_ENV", "dev"))

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
    LOG_LEVEL = os.getenv("STUDYPLAN_LOG_LEVEL", "INFO" if ENV == Environment.PROD else "DEBUG")
