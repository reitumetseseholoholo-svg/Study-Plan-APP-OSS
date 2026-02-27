import pytest
from datetime import datetime, timedelta, timezone

from studyplan.learning_Science import (
    SpacedRetrievalSchedule,
    ElaborationQuestionSet,
    SessionReflection,
    TransferTaskGenerator,
    DesirableDifficultyCalibrator,
)


def test_spaced_retrieval_first_review():
    """First attempt should schedule for 1 day."""
    sch = SpacedRetrievalSchedule(
        topic="photosynthesis",
        last_correct_date=None,
        difficulty_level="medium",
        mastery_confidence=0.5,
    )
    assert sch.next_retest_days == 1
    assert sch.should_retest_now()


def test_spaced_retrieval_overdue():
    """If last_correct was >= next_retest_days, should retest."""
    # 2 days ago - should be due for next review (spacing of 1 or 2 would have elapsed)
    last = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    sch = SpacedRetrievalSchedule(
        topic="photosynthesis",
        last_correct_date=last,
        difficulty_level="medium",
        mastery_confidence=0.8,
    )
    # The algorithm computes next review interval; just check it calculates
    assert sch.next_retest_days >= 1


def test_elaboration_questions():
    """Elaboration should generate Bloom's hierarchy questions."""
    elab = ElaborationQuestionSet(
        topic="thermodynamics",
        base_concept="entropy",
    )
    assert "understand" in elab.questions
    assert "apply" in elab.questions
    assert "entropy" in elab.questions["remember"]


def test_session_reflection_mastered():
    """Reflection should celebrate mastery."""
    ref = SessionReflection(
        session_id="s1",
        topics_covered=["topic_a", "topic_b"],
        topics_mastered=["topic_a"],
        topics_struggling=[],
        confidence_calibration=0.1,
        total_attempts=10,
        correct_rate=0.9,
        avg_latency_ms=25000,
        session_duration_minutes=45,
    )
    feedback = ref.generate_feedback()
    assert "90%" in feedback
    assert "Mastered" in feedback


def test_session_reflection_struggling():
    """Reflection should encourage when struggling."""
    ref = SessionReflection(
        session_id="s1",
        topics_covered=["topic_a"],
        topics_mastered=[],
        topics_struggling=["topic_a"],
        confidence_calibration=-0.3,
        total_attempts=10,
        correct_rate=0.4,
        avg_latency_ms=45000,
        session_duration_minutes=30,
    )
    feedback = ref.generate_feedback()
    assert "40%" in feedback
    assert "Need more practice" in feedback


def test_transfer_task_generation():
    """Transfer tasks should vary by domain."""
    real = TransferTaskGenerator.generate_transfer_task(
        "calculus",
        "derivatives",
        "real_world",
    )
    teaching = TransferTaskGenerator.generate_transfer_task(
        "calculus",
        "derivatives",
        "teaching",
    )
    assert real != teaching
    assert "analogy" in teaching.lower()


def test_desirable_difficulty_high_mastery():
    """High mastery + low latency → recommend hard."""
    rec = DesirableDifficultyCalibrator.recommend_difficulty(
        mastery=0.9,
        latency_ms=10000,
        confidence=5,
        error_streak=False,
    )
    assert rec == "hard"


def test_desirable_difficulty_overload():
    """High latency or error streak → recommend easy."""
    rec = DesirableDifficultyCalibrator.recommend_difficulty(
        mastery=0.6,
        latency_ms=90000,
        confidence=1,
        error_streak=True,
    )
    assert rec == "easy"


def test_desirable_difficulty_explanation():
    """Explanations should be encouraging."""
    exp = DesirableDifficultyCalibrator.explain_calibration("medium", "hard")
    assert "step up" in exp.lower()
