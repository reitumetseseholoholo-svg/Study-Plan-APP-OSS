"""
JSON safety helpers for robustness in processing-heavy flows.

Goals:
- Prevent corrupt JSON from crashing the app without context.
- When enabled, quarantine corrupt files so users can restore backups manually.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from studyplan_file_safety import enforce_file_size_limit


def quarantine_corrupt_file(file_path: str, *, suffix: str | None = None) -> str | None:
    """Rename a corrupt file out of the way and return the new path.

    Returns None if quarantine could not be completed.
    """
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    src = os.path.abspath(file_path.strip())
    if not os.path.exists(src):
        return None

    ts = int(time.time())
    extra = str(suffix).strip() if isinstance(suffix, str) and suffix.strip() else ""
    new_path = f"{src}.corrupt.{ts}{('.' + extra) if extra else ''}"
    try:
        os.replace(src, new_path)
        return new_path
    except Exception:
        return None


def load_json_file_with_limit(
    file_path: str,
    max_bytes: int,
    label: str,
    *,
    quarantine_corrupt: bool = True,
) -> Any:
    """Load JSON from a file with size enforcement and corrupt-file quarantine.

    Raises:
        ValueError: for corrupt JSON or invalid inputs.
        OSError/IOError: for unreadable paths (kept as-is).
    """
    size = enforce_file_size_limit(
        file_path,
        max_bytes,
        label,
        human_readable=False,
        punctuate_simple_errors=False,
    )
    _ = size  # size is enforced; keep for readability

    path = os.path.abspath(str(file_path).strip())
    with open(path, "r", newline="", encoding="utf-8") as f:
        raw = f.read()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        quarantined_at: str | None = None
        if quarantine_corrupt:
            quarantined_at = quarantine_corrupt_file(path, suffix="json")
        if quarantined_at:
            raise ValueError(
                f"{label} JSON is corrupt: {exc}. Quarantined copy created at: {quarantined_at}"
            ) from exc
        raise ValueError(f"{label} JSON is corrupt: {exc}") from exc

