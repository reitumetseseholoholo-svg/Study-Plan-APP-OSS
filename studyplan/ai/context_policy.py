"""Context formatting roles, drop order, and adaptive limits (Phase 1 roadmap).

Keeps degradation order aligned with `_format_local_ai_context_block` in studyplan_app.py.
"""

from __future__ import annotations

import os
from typing import Final

# Logical roles for budget + drop sequencing (map from packet/consumer "kind").
ROLE_TUTOR_TURN: Final[str] = "tutor_turn"
ROLE_COACH_TURN: Final[str] = "coach_turn"
ROLE_AUTOPILOT_SNAPSHOT: Final[str] = "autopilot_snapshot"
ROLE_SECTION_C_GEN: Final[str] = "section_c_gen"
ROLE_DEFAULT: Final[str] = ROLE_TUTOR_TURN

# Order of section drops when formatted context exceeds char budget (matches legacy behavior).
CONTEXT_SECTION_DROP_ORDER: Final[tuple[str, ...]] = (
    "confidence_calibration",
    "tutor_past_days",
    "recent_action_mix",
    "error_patterns",
    "working_memory",
    "daily_plan_progress",
    "focus_trend_14d",
    "quiz_trend_14d",
    "cognitive_posterior_row",
    "cognitive_posteriors",
    "risk_snapshot_row",
    "due_snapshot_row",
    "weak_topics_row",
)
# After exhausting the list, the formatter truncates the text tail to the budget.


def map_packet_kind_to_role(kind: str) -> str:
    k = str(kind or "").strip().lower()
    if k == "coach":
        return ROLE_COACH_TURN
    if k in {"tutor", "tutor_turn", ""}:
        return ROLE_TUTOR_TURN
    if k in {"autopilot", "autopilot_snapshot"}:
        return ROLE_AUTOPILOT_SNAPSHOT
    if k in {"section_c", "section_c_gen"}:
        return ROLE_SECTION_C_GEN
    return ROLE_TUTOR_TURN


def context_drop_order_for_role(role: str) -> tuple[str, ...]:
    """Return ordered drop steps; same sequence for all roles until per-role tuning is needed."""
    _ = str(role or "").strip().lower()
    return CONTEXT_SECTION_DROP_ORDER


def adaptive_tutor_recent_cap(
    base_recent_limit: int,
    *,
    device_tier: str | None = None,
) -> int:
    """Cap verbatim history turns for tutor base prompt (Phase 1.4).

    - ``STUDYPLAN_DEVICE_TIER=low`` tightens the cap.
    - ``STUDYPLAN_TUTOR_RECENT_CAP`` optional int env override (2–20).
    """
    try:
        cap = max(2, min(20, int(base_recent_limit)))
    except Exception:
        cap = 10
    tier = str(device_tier if device_tier is not None else os.environ.get("STUDYPLAN_DEVICE_TIER", "") or "").strip().lower()
    if tier == "low":
        cap = min(cap, 8)
    raw = str(os.environ.get("STUDYPLAN_TUTOR_RECENT_CAP", "") or "").strip()
    if raw.isdigit():
        cap = min(cap, max(2, min(20, int(raw))))
    return cap


def long_history_threshold_with_tier(base_threshold: int) -> int:
    """When device tier is low, start older-turn summarization slightly earlier."""
    try:
        th = max(8, int(base_threshold))
    except Exception:
        th = 24
    tier = str(os.environ.get("STUDYPLAN_DEVICE_TIER", "") or "").strip().lower()
    if tier == "low":
        return max(12, int(th * 0.75))
    return th
