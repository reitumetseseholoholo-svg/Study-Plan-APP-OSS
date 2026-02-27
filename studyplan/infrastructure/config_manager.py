from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return bool(default)
    value = str(raw).strip().lower()
    if not value:
        return bool(default)
    return value in {"1", "true", "yes", "on"}


def _parse_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(raw).strip()) if raw is not None else int(default)
    except Exception:
        parsed = int(default)
    return max(int(minimum), min(int(maximum), int(parsed)))


@dataclass(frozen=True)
class StudyPlanRuntimeConfig:
    cache_size: int = 500
    write_interval_seconds: int = 30
    max_file_size_bytes: int = 10 * 1024 * 1024
    allowed_extensions: tuple[str, ...] = (".json", ".csv")
    enable_performance_monitoring: bool = False
    enable_secure_imports: bool = True


class ConfigManager:
    """Runtime config loader with environment overrides."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._env = environ if environ is not None else os.environ

    def load(self) -> StudyPlanRuntimeConfig:
        env = self._env
        cache_size = _parse_int(env.get("STUDYPLAN_CACHE_SIZE"), 500, 16, 50_000)
        write_interval = _parse_int(env.get("STUDYPLAN_WRITE_INTERVAL"), 30, 5, 3600)
        max_file_size = _parse_int(env.get("STUDYPLAN_MAX_FILE_SIZE"), 10 * 1024 * 1024, 1024, 1024 * 1024 * 1024)
        raw_extensions = str(env.get("STUDYPLAN_ALLOWED_EXTENSIONS", ".json,.csv") or ".json,.csv")
        extensions: list[str] = []
        for item in raw_extensions.split(","):
            ext = str(item or "").strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = f".{ext}"
            if ext not in extensions:
                extensions.append(ext)
        if not extensions:
            extensions = [".json", ".csv"]
        perf = _parse_bool(env.get("STUDYPLAN_ENABLE_PERFORMANCE_MONITORING"), False)
        secure_imports = _parse_bool(env.get("STUDYPLAN_ENABLE_SECURE_IMPORTS"), True)
        return StudyPlanRuntimeConfig(
            cache_size=cache_size,
            write_interval_seconds=write_interval,
            max_file_size_bytes=max_file_size,
            allowed_extensions=tuple(extensions),
            enable_performance_monitoring=perf,
            enable_secure_imports=secure_imports,
        )

