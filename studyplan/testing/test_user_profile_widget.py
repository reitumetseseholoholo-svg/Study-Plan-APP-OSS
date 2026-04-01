"""Tests for the UserProfileWidget display logic using the learner profile contract."""

from studyplan.contracts import TutorLearnerProfileSnapshot
from studyplan.services import InMemoryTutorLearnerModelStore


def test_profile_store_default_profile():
    """get_or_create_profile returns a valid default profile."""
    store = InMemoryTutorLearnerModelStore()
    profile = store.get_or_create_profile(learner_id="default", module="ACCA")

    assert isinstance(profile, TutorLearnerProfileSnapshot)
    assert profile.learner_id == "default"
    assert profile.module == "ACCA"
    assert profile.preferred_explanation_style == "worked_example"
    assert profile.response_speed_tier == "unknown"
    assert profile.confidence_calibration_bias == 0.0
    assert profile.chat_to_quiz_transfer_score == 0.0


def test_profile_store_save_and_retrieve():
    """Saved profile is retrievable and preserves all fields."""
    store = InMemoryTutorLearnerModelStore()
    updated = TutorLearnerProfileSnapshot(
        learner_id="learner42",
        module="FM",
        preferred_explanation_style="analogy",
        response_speed_tier="fast",
        confidence_calibration_bias=0.25,
        chat_to_quiz_transfer_score=0.8,
        last_practice_outcome="correct",
        misconception_tags_top=("npv", "irr"),
        weak_capabilities_top=("A", "C"),
    )
    saved = store.save_profile(updated)
    retrieved = store.get_or_create_profile(learner_id="learner42", module="FM")

    assert retrieved.preferred_explanation_style == "analogy"
    assert retrieved.response_speed_tier == "fast"
    assert retrieved.confidence_calibration_bias == 0.25
    assert retrieved.chat_to_quiz_transfer_score == 0.8
    assert retrieved.last_practice_outcome == "correct"
    assert "npv" in retrieved.misconception_tags_top
    assert "A" in retrieved.weak_capabilities_top
    assert saved.learner_id == "learner42"


def test_profile_display_lines_content():
    """Verify the display lines generated from a profile contain all expected sections."""
    profile = TutorLearnerProfileSnapshot(
        learner_id="u1",
        module="FM",
        preferred_explanation_style="worked_example",
        response_speed_tier="slow",
        confidence_calibration_bias=-0.5,
        chat_to_quiz_transfer_score=0.6,
        last_practice_outcome="partial",
        last_updated_ts="2026-01-01T10:00:00",
        misconception_tags_top=("time_value", "capital_structure"),
        weak_capabilities_top=("B",),
    )

    # Replicate the display logic from UserProfileWidget.update_display
    misconceptions = ", ".join(profile.misconception_tags_top) if profile.misconception_tags_top else "none"
    weak_caps = ", ".join(profile.weak_capabilities_top) if profile.weak_capabilities_top else "none"
    last_updated = profile.last_updated_ts or "never"
    last_outcome = profile.last_practice_outcome or "none"

    lines = [
        "── Identity ──",
        f"Learner ID: {profile.learner_id or 'default'}",
        f"Module: {profile.module or 'ACCA'}",
        "",
        "── Preferences ──",
        f"Explanation style: {profile.preferred_explanation_style}",
        f"Response speed tier: {profile.response_speed_tier}",
        "",
        "── Analytics ──",
        f"Confidence calibration bias: {profile.confidence_calibration_bias:+.2f}",
        f"Chat-to-quiz transfer score: {profile.chat_to_quiz_transfer_score:.2f}",
        f"Last practice outcome: {last_outcome}",
        f"Last updated: {last_updated}",
        "",
        "── Learning Gaps ──",
        f"Top misconceptions: {misconceptions}",
        f"Weak capabilities: {weak_caps}",
    ]
    body = "\n".join(lines)

    assert "Learner ID: u1" in body
    assert "Module: FM" in body
    assert "Explanation style: worked_example" in body
    assert "Response speed tier: slow" in body
    assert "Confidence calibration bias: -0.50" in body
    assert "Chat-to-quiz transfer score: 0.60" in body
    assert "Last practice outcome: partial" in body
    assert "Last updated: 2026-01-01T10:00:00" in body
    assert "time_value" in body
    assert "capital_structure" in body
    assert "Weak capabilities: B" in body


def test_profile_display_empty_gaps():
    """Profile with no misconceptions or weak caps shows 'none'."""
    profile = TutorLearnerProfileSnapshot(learner_id="clean", module="FR")

    misconceptions = ", ".join(profile.misconception_tags_top) if profile.misconception_tags_top else "none"
    weak_caps = ", ".join(profile.weak_capabilities_top) if profile.weak_capabilities_top else "none"

    assert misconceptions == "none"
    assert weak_caps == "none"


def test_profile_round_trip_serialisation():
    """TutorLearnerProfileSnapshot serialises and deserialises cleanly."""
    original = TutorLearnerProfileSnapshot(
        learner_id="rt-user",
        module="FR",
        preferred_explanation_style="analogy",
        response_speed_tier="fast",
        confidence_calibration_bias=0.1,
        chat_to_quiz_transfer_score=0.9,
        last_practice_outcome="correct",
        misconception_tags_top=("lease_accounting",),
        weak_capabilities_top=("D",),
    )
    roundtripped = TutorLearnerProfileSnapshot.from_dict(original.to_dict())

    assert roundtripped.learner_id == original.learner_id
    assert roundtripped.module == original.module
    assert roundtripped.preferred_explanation_style == original.preferred_explanation_style
    assert roundtripped.response_speed_tier == original.response_speed_tier
    assert roundtripped.confidence_calibration_bias == original.confidence_calibration_bias
    assert roundtripped.chat_to_quiz_transfer_score == original.chat_to_quiz_transfer_score
    assert roundtripped.last_practice_outcome == original.last_practice_outcome
    assert roundtripped.misconception_tags_top == original.misconception_tags_top
    assert roundtripped.weak_capabilities_top == original.weak_capabilities_top
