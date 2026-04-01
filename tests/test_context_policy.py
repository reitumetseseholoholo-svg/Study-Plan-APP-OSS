"""Context policy helpers (Phase 1 roadmap)."""

from __future__ import annotations

from studyplan.ai.context_policy import (
    CONTEXT_SECTION_DROP_ORDER,
    adaptive_tutor_recent_cap,
    context_drop_order_for_role,
    long_history_threshold_with_tier,
    map_packet_kind_to_role,
)
from studyplan.ai.llm_telemetry import normalize_purpose


def test_map_packet_kind_to_role():
    assert map_packet_kind_to_role("coach") == "coach_turn"
    assert map_packet_kind_to_role("tutor") == "tutor_turn"
    assert map_packet_kind_to_role("") == "tutor_turn"


def test_drop_order_stable():
    assert context_drop_order_for_role("tutor_turn") == CONTEXT_SECTION_DROP_ORDER
    assert "confidence_calibration" in CONTEXT_SECTION_DROP_ORDER
    assert "quiz_trend_14d" in CONTEXT_SECTION_DROP_ORDER


def test_adaptive_recent_cap_low_tier(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_DEVICE_TIER", "low")
    assert adaptive_tutor_recent_cap(16) <= 8
    monkeypatch.delenv("STUDYPLAN_DEVICE_TIER", raising=False)


def test_adaptive_recent_cap_env_override(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_TUTOR_RECENT_CAP", "6")
    assert adaptive_tutor_recent_cap(16) == 6
    monkeypatch.delenv("STUDYPLAN_TUTOR_RECENT_CAP", raising=False)


def test_long_history_threshold_low_tier(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_DEVICE_TIER", "low")
    assert long_history_threshold_with_tier(24) < 24
    monkeypatch.delenv("STUDYPLAN_DEVICE_TIER", raising=False)


def test_normalize_purpose():
    assert normalize_purpose("tutor_embedded") == "tutor_embedded"
    assert normalize_purpose("BAD PURPOSE!") == "unknown"
