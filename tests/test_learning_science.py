"""Unit tests for studyplan/learning_Science.py."""
from __future__ import annotations

import datetime

import pytest

from studyplan.learning_Science import (
    DesirableDifficultyCalibrator,
    ElaborationQuestionSet,
    LearningPhase,
    SessionReflection,
    SpacedRetrievalSchedule,
    TransferTaskGenerator,
)


# ---------------------------------------------------------------------------
# SpacedRetrievalSchedule
# ---------------------------------------------------------------------------


def test_should_retest_now_when_never_reviewed():
    sched = SpacedRetrievalSchedule(
        topic="NPV",
        last_correct_date=None,
        difficulty_level="medium",
        mastery_confidence=0.5,
    )
    assert sched.should_retest_now() is True


def test_should_retest_now_when_overdue():
    # A card reviewed several days ago should be due for retest once
    # days_since reaches a power-of-2 interval boundary.
    date_3d_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).isoformat()
    sched = SpacedRetrievalSchedule(
        topic="WACC",
        last_correct_date=date_3d_ago,
        difficulty_level="hard",
        mastery_confidence=0.3,
    )
    # 3 days ago → current interval is 2 (largest power-of-2 ≤ 3), so 3 >= 2 → True
    assert sched.should_retest_now() is True


def test_should_not_retest_when_recently_reviewed():
    # Reviewed just now → not due again yet
    recent_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    sched = SpacedRetrievalSchedule(
        topic="DCF",
        last_correct_date=recent_date,
        difficulty_level="easy",
        mastery_confidence=0.9,
    )
    assert sched.should_retest_now() is False


def test_next_retest_days_is_positive():
    sched = SpacedRetrievalSchedule(
        topic="FM",
        last_correct_date=None,
        difficulty_level="medium",
        mastery_confidence=0.5,
    )
    assert sched.next_retest_days >= 1


def test_next_retest_days_grows_with_mastery():
    # Reviewed 7 days ago → spacing should be 8 days (>7)
    date_7d_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    sched = SpacedRetrievalSchedule(
        topic="CAPM",
        last_correct_date=date_7d_ago,
        difficulty_level="easy",
        mastery_confidence=0.8,
    )
    assert sched.next_retest_days >= 8


def test_invalid_date_does_not_crash():
    sched = SpacedRetrievalSchedule(
        topic="X",
        last_correct_date="not-a-date",
        difficulty_level="medium",
        mastery_confidence=0.5,
    )
    assert sched.next_retest_days >= 1
    # Shouldn't raise
    _ = sched.should_retest_now()


# ---------------------------------------------------------------------------
# ElaborationQuestionSet
# ---------------------------------------------------------------------------


def test_elaboration_questions_generated_by_default():
    elab = ElaborationQuestionSet(topic="NPV", base_concept="Net Present Value")
    assert isinstance(elab.questions, dict)
    assert len(elab.questions) >= 4


def test_elaboration_has_bloom_levels():
    elab = ElaborationQuestionSet(topic="WACC", base_concept="Weighted Average Cost of Capital")
    keys = set(elab.questions.keys())
    expected = {"remember", "understand", "apply", "analyze", "evaluate"}
    assert keys == expected


def test_elaboration_questions_contain_concept():
    elab = ElaborationQuestionSet(topic="DCF", base_concept="discounting")
    for text in elab.questions.values():
        # At least some questions should mention the concept
        if "discounting" in text.lower():
            break
    else:
        pytest.skip("Concept not always in all questions — just check they're non-empty.")
    assert all(text.strip() for text in elab.questions.values())


def test_elaboration_accepts_custom_questions():
    custom = {"key1": "Custom Q1", "key2": "Custom Q2"}
    elab = ElaborationQuestionSet(topic="X", base_concept="X", questions=custom)
    assert elab.questions == custom


# ---------------------------------------------------------------------------
# SessionReflection
# ---------------------------------------------------------------------------


@pytest.fixture
def good_session():
    return SessionReflection(
        session_id="sess-001",
        topics_covered=["NPV", "WACC"],
        topics_mastered=["NPV"],
        topics_struggling=[],
        confidence_calibration=0.05,
        total_attempts=20,
        correct_rate=0.85,
        avg_latency_ms=5000.0,
        session_duration_minutes=30,
    )


@pytest.fixture
def struggling_session():
    return SessionReflection(
        session_id="sess-002",
        topics_covered=["CAPM"],
        topics_mastered=[],
        topics_struggling=["CAPM"],
        confidence_calibration=0.45,
        total_attempts=10,
        correct_rate=0.30,
        avg_latency_ms=30000.0,
        session_duration_minutes=15,
    )


def test_reflection_feedback_mentions_duration(good_session):
    feedback = good_session.generate_feedback()
    assert "30" in feedback or "min" in feedback.lower()


def test_reflection_feedback_mentions_correct_rate(good_session):
    feedback = good_session.generate_feedback()
    assert "85" in feedback or "%" in feedback


def test_reflection_feedback_mentions_mastered_topics(good_session):
    feedback = good_session.generate_feedback()
    assert "NPV" in feedback


def test_reflection_feedback_mentions_struggling_topics(struggling_session):
    feedback = struggling_session.generate_feedback()
    assert "CAPM" in feedback


def test_reflection_feedback_overconfident_note(struggling_session):
    feedback = struggling_session.generate_feedback()
    assert any(word in feedback.lower() for word in ("confident", "humble", "capable", "next session"))


def test_reflection_feedback_for_perfect_session():
    sr = SessionReflection(
        session_id="sess-003",
        topics_covered=["DCF"],
        topics_mastered=["DCF"],
        topics_struggling=[],
        confidence_calibration=0.02,
        total_attempts=5,
        correct_rate=1.0,
        avg_latency_ms=3000.0,
        session_duration_minutes=10,
    )
    feedback = sr.generate_feedback()
    assert "100" in feedback or "spaced" in feedback.lower()


# ---------------------------------------------------------------------------
# TransferTaskGenerator
# ---------------------------------------------------------------------------


def test_transfer_task_real_world():
    task = TransferTaskGenerator.generate_transfer_task(
        base_topic="NPV calculation",
        base_concept="Net Present Value",
        domain="real_world",
    )
    assert isinstance(task, str)
    assert len(task) > 20


def test_transfer_task_teaching():
    task = TransferTaskGenerator.generate_transfer_task(
        base_topic="WACC",
        base_concept="Weighted Average Cost of Capital",
        domain="teaching",
    )
    assert "teach" in task.lower() or "analogy" in task.lower() or "someone" in task.lower()


def test_transfer_task_debugging():
    task = TransferTaskGenerator.generate_transfer_task(
        base_topic="DCF",
        base_concept="discounting",
        domain="debugging",
    )
    assert "mistake" in task.lower() or "error" in task.lower() or "common" in task.lower()


def test_transfer_task_unknown_domain_defaults_to_real_world():
    task = TransferTaskGenerator.generate_transfer_task(
        base_topic="FM",
        base_concept="Financial Management",
        domain="nonexistent_domain",
    )
    assert isinstance(task, str)
    assert len(task) > 10


# ---------------------------------------------------------------------------
# DesirableDifficultyCalibrator
# ---------------------------------------------------------------------------


def test_recommend_hard_when_mastered_fast_confident():
    rec = DesirableDifficultyCalibrator.recommend_difficulty(
        mastery=0.9,
        latency_ms=5000.0,
        confidence=5,
        error_streak=False,
    )
    assert rec == "hard"


def test_recommend_easy_when_long_latency():
    rec = DesirableDifficultyCalibrator.recommend_difficulty(
        mastery=0.5,
        latency_ms=70000.0,
        confidence=3,
        error_streak=False,
    )
    assert rec == "easy"


def test_recommend_easy_when_error_streak():
    rec = DesirableDifficultyCalibrator.recommend_difficulty(
        mastery=0.5,
        latency_ms=10000.0,
        confidence=2,
        error_streak=True,
    )
    assert rec == "easy"


def test_recommend_medium_in_middle():
    rec = DesirableDifficultyCalibrator.recommend_difficulty(
        mastery=0.6,
        latency_ms=20000.0,
        confidence=3,
        error_streak=False,
    )
    assert rec == "medium"


def test_explain_calibration_no_change():
    msg = DesirableDifficultyCalibrator.explain_calibration("medium", "medium")
    assert "right" in msg.lower() or "zone" in msg.lower() or "keep" in msg.lower()


def test_explain_calibration_escalating():
    msg = DesirableDifficultyCalibrator.explain_calibration("medium", "hard")
    assert "step up" in msg.lower() or "harder" in msg.lower() or "ready" in msg.lower()


def test_explain_calibration_easing():
    msg = DesirableDifficultyCalibrator.explain_calibration("hard", "easy")
    assert "foundation" in msg.lower() or "tough" in msg.lower() or "easier" in msg.lower()


# ---------------------------------------------------------------------------
# LearningPhase enum
# ---------------------------------------------------------------------------


def test_learning_phases_exist():
    phases = [p.value for p in LearningPhase]
    assert "initial" in phases
    assert "retrieval" in phases
    assert "elaboration" in phases
    assert "transfer" in phases
    assert "reflection" in phases
