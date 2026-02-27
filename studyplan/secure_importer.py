import os
from pathlib import Path
from typing import Any

from .config import Config
from .logging_config import get_logger

logger = get_logger(__name__)


class ImportSecurityError(Exception):
    pass


class SecureImporter:
    """Hardened import path validation: size, extension, directory whitelist."""

    @staticmethod
    def validate_and_load(file_path: str) -> dict[str, Any]:
        """Load and validate a file before import."""
        if not Config.SECURE_IMPORT_ENABLED:
            logger.warning("secure import disabled; using unsafe path")
            return SecureImporter._unsafe_load(file_path)

        file_path = str(file_path or "").strip()
        if not file_path:
            raise ImportSecurityError("empty file_path")

        path = Path(file_path).resolve()

        # Check extension
        ext = path.suffix
        if ext not in Config.SECURE_IMPORT_ALLOWED_EXTENSIONS:
            raise ImportSecurityError(f"extension {ext} not allowed")

        # Check directory whitelist
        allowed = any(
            path.is_relative_to(Path(d).resolve()) for d in Config.SECURE_IMPORT_ALLOWED_DIRS
        )
        if not allowed:
            raise ImportSecurityError(f"path {path} not in whitelist")

        # Check size
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > Config.SECURE_IMPORT_MAX_SIZE_MB:
            raise ImportSecurityError(f"file {size_mb}MB exceeds max {Config.SECURE_IMPORT_MAX_SIZE_MB}MB")

        logger.info(f"secure import validation passed", extra={"path": str(path)})
        return SecureImporter._safe_load(path)

    @staticmethod
    def _safe_load(path: Path) -> dict[str, Any]:
        """Load JSON/JSONL after validation."""
        import json

        if path.suffix == ".json":
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        elif path.suffix == ".jsonl":
            records = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        records.append(json.loads(line))
            return {"records": records}
        else:
            raise ImportSecurityError(f"unsupported format: {path.suffix}")

    @staticmethod
    def _unsafe_load(file_path: str) -> dict[str, Any]:
        """Fallback for dev: direct load without validation."""
        import json

        path = Path(file_path)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
