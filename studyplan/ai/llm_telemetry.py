"""Unified LLM job / turn purpose labels for telemetry (Phase 0 roadmap)."""

from __future__ import annotations

import re
from typing import Final

# Stable purpose strings stored on each telemetry row (`purpose` field).
PURPOSE_TUTOR_EMBEDDED: Final[str] = "tutor_embedded"
PURPOSE_TUTOR_POPUP: Final[str] = "tutor_popup"
PURPOSE_COACH: Final[str] = "coach_turn"
PURPOSE_AUTOPILOT: Final[str] = "autopilot_decide"
PURPOSE_GAP_GEN: Final[str] = "gap_gen"
PURPOSE_SECTION_C: Final[str] = "section_c_gen"
PURPOSE_SYLLABUS: Final[str] = "syllabus_ai"
PURPOSE_UNKNOWN: Final[str] = "unknown"

_ALLOWED_PURPOSE_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def normalize_purpose(raw: str, *, default: str = PURPOSE_UNKNOWN) -> str:
    s = str(raw or "").strip().lower()
    if not s or not _ALLOWED_PURPOSE_RE.match(s):
        return str(default)
    return s
