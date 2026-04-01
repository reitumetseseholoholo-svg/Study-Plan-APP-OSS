"""Static IFRS/ACCA-oriented statement format checklists (Phase 2.1, FR plan)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

_CHECKLIST_PATH = Path(__file__).resolve().parent / "data" / "statement_format_checklists.json"

logger = logging.getLogger(__name__)


def load_statement_format_checklists() -> dict[str, list[str]]:
    """Return checklist dict: keys SoFP | SoPL | SoCF | Notes -> list of reminder lines."""
    try:
        raw = _CHECKLIST_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("Failed to load statement format checklists: %s", exc)
        return {}

    if not isinstance(data, dict):
        return {}

    out: dict[str, list[str]] = {}
    for k, v in data.items():
        key = str(k or "").strip()
        if not key:
            continue
        if isinstance(v, list):
            lines = [str(x).strip() for x in v if str(x or "").strip()]
            if lines:
                out[key] = lines
    return out


def format_checklists_as_text(data: dict[str, list[str]] | None = None) -> str:
    """Plain-text view for dialogs (stable section order)."""
    src = data if isinstance(data, dict) else load_statement_format_checklists()
    order = ["SoFP", "SoPL", "SoCF", "Notes"]
    parts: list[str] = []
    for key in order:
        rows = src.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        parts.append(f"=== {key} ===")
        for i, line in enumerate(rows, start=1):
            parts.append(f"  {i}. {line}")
        parts.append("")
    for key in sorted(k for k in src if k not in order):
        rows = src.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        parts.append(f"=== {key} ===")
        for i, line in enumerate(rows, start=1):
            parts.append(f"  {i}. {line}")
        parts.append("")
    return "\n".join(parts).strip() or "(no checklists loaded)"
