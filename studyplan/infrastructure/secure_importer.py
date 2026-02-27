from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any


class SecureImporter:
    """Path and file-size guardrails for import flows."""

    def __init__(
        self,
        *,
        max_file_size_bytes: int = 10 * 1024 * 1024,
        allowed_extensions: tuple[str, ...] = (".json", ".csv"),
    ) -> None:
        self.max_file_size_bytes = max(1024, int(max_file_size_bytes))
        normalized: list[str] = []
        for ext in tuple(allowed_extensions or (".json", ".csv")):
            val = str(ext or "").strip().lower()
            if not val:
                continue
            if not val.startswith("."):
                val = f".{val}"
            if val not in normalized:
                normalized.append(val)
        self.allowed_extensions = tuple(normalized) if normalized else (".json", ".csv")

    def validate_file_path(
        self,
        file_path: str,
        *,
        allowed_extensions: tuple[str, ...] | None = None,
        base_dir: str | None = None,
    ) -> str:
        raw = str(file_path or "").strip()
        if not raw:
            raise ValueError("file path is required")
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"not a regular file: {path}")
        exts = tuple(allowed_extensions or self.allowed_extensions)
        ext_norm = []
        for ext in exts:
            value = str(ext or "").strip().lower()
            if not value:
                continue
            if not value.startswith("."):
                value = f".{value}"
            ext_norm.append(value)
        if ext_norm and path.suffix.lower() not in tuple(ext_norm):
            allowed = ", ".join(ext_norm)
            raise ValueError(f"unsupported file extension '{path.suffix}'; allowed: {allowed}")
        if base_dir:
            root = Path(str(base_dir)).expanduser().resolve(strict=True)
            common = os.path.commonpath([str(path), str(root)])
            if common != str(root):
                raise ValueError(f"path escapes allowed base directory: {path}")
        return str(path)

    def enforce_file_size(self, file_path: str, *, max_file_size_bytes: int | None = None) -> int:
        path = Path(str(file_path)).expanduser().resolve(strict=True)
        size = int(path.stat().st_size)
        max_bytes = max(1024, int(max_file_size_bytes or self.max_file_size_bytes))
        if size > max_bytes:
            raise ValueError(f"file too large ({size} bytes > {max_bytes} bytes): {path}")
        return size

    def load_json(
        self,
        file_path: str,
        *,
        base_dir: str | None = None,
        max_file_size_bytes: int | None = None,
    ) -> Any:
        path = self.validate_file_path(
            file_path,
            allowed_extensions=(".json",),
            base_dir=base_dir,
        )
        self.enforce_file_size(path, max_file_size_bytes=max_file_size_bytes)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def load_csv_rows(
        self,
        file_path: str,
        *,
        base_dir: str | None = None,
        max_file_size_bytes: int | None = None,
        max_rows: int = 50_000,
    ) -> list[dict[str, str]]:
        path = self.validate_file_path(
            file_path,
            allowed_extensions=(".csv",),
            base_dir=base_dir,
        )
        self.enforce_file_size(path, max_file_size_bytes=max_file_size_bytes)
        rows: list[dict[str, str]] = []
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append({str(k or ""): str(v or "") for k, v in dict(row or {}).items()})
                if len(rows) > int(max_rows):
                    raise ValueError(f"csv row limit exceeded ({max_rows})")
        return rows
