"""Unit tests for studyplan/practice_loop_controller.py."""
from __future__ import annotations

from typing import Any

import pytest

from studyplan.cognitive_state import CognitiveState
from studyplan.contracts import (
    AppStateSnapshot,
    TutorAssessmentResult,
    TutorAssessmentSubmission,
    TutorLearnerProfileSnapshot,
    TutorPracticeItem,
    TutorSessionState,
    TutorTurnResult,
)
from studyplan.practice_loop_controller import PracticeLoopController, PracticeLoopSessionState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop_state(topic: str = "NPV calculation") -> PracticeLoopSessionState:
    return PracticeLoopSessionState(
        cognitive_state=CognitiveState(),
        session_state=TutorSessionState(session_id="test-001", module="acca_fm", topic=topic),
        learner_profile=TutorLearnerProfileSnapshot(
            learner_id="learner-1",
            module="acca_fm",
        ),
        app_snapshot=AppStateSnapshot(
            module="acca_fm",
            current_topic=topic,
            coach_pick=topic,
            days_to_exam=90,
            must_review_due=0,
            overdue_srs_count=0,
        ),
    )


def _make_item(topic: str = "NPV calculation") -> TutorPracticeItem:
    return TutorPracticeItem(
        item_id="item-001",
        topic=topic,
        prompt="What is NPV?",
        item_type="short_answer",
        difficulty="medium",
    )


def _make_correct_result(item: TutorPracticeItem) -> TutorAssessmentResult:
    return TutorAssessmentResult(
        item_id=item.item_id,
        outcome="correct",
        marks_awarded=1.0,
        marks_max=1.0,
        feedback="Well done.",
        error_tags=[],
        misconception_tags=[],
        retry_recommended=False,
        next_difficulty="medium",
        meta={},
    )


def _make_incorrect_result(item: TutorPracticeItem) -> TutorAssessmentResult:
    return TutorAssessmentResult(
        item_id=item.item_id,
        outcome="incorrect",
        marks_awarded=0.0,
        marks_max=1.0,
        feedback="Not quite.",
        error_tags=["formula_error"],
        misconception_tags=[],
        retry_recommended=True,
        next_difficulty="easy",
        meta={},
    )


# ---------------------------------------------------------------------------
# Controller instantiation
# ---------------------------------------------------------------------------


def test_controller_creates_without_error():
    ctrl = PracticeLoopController()
    assert ctrl is not None


def test_controller_has_practice_and_assess_services():
    ctrl = PracticeLoopController()
    assert ctrl.practice_svc is not None
    assert ctrl.assess_svc is not None


# ---------------------------------------------------------------------------
# _coerce_str / _coerce_int / _coerce_bool / _coerce_float
# ---------------------------------------------------------------------------


def test_coerce_str_normalises_none():
    assert PracticeLoopController._coerce_str(None) == ""


def test_coerce_str_returns_default_for_empty():
    assert PracticeLoopController._coerce_str("", "fallback") == "fallback"


def test_coerce_int_handles_non_numeric():
    assert PracticeLoopController._coerce_int("abc", 5) == 5


def test_coerce_int_clamps_to_min():
    assert PracticeLoopController._coerce_int(0, 5, min_value=3) == 3


def test_coerce_float_handles_none():
    assert PracticeLoopController._coerce_float(None, 1.5) == 1.5


def test_coerce_bool_handles_truthy():
    assert PracticeLoopController._coerce_bool(1) is True
    assert PracticeLoopController._coerce_bool(0) is False
    assert PracticeLoopController._coerce_bool(None, default=True) is True


# ---------------------------------------------------------------------------
# normalize_learner_help_feedback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("clear", "clear"),
    ("Cleared", "clear"),
    ("understood", "clear"),
    ("Got it", "clear"),
    ("partly", "partly"),
    ("partially", "partly"),
    ("almost", "partly"),
    ("stuck", "stuck"),
    ("confused", "stuck"),
    ("not clear", "stuck"),
    ("random_text", ""),
    (None, ""),
])
def test_normalize_learner_help_feedback(raw, expected):
    assert PracticeLoopController.normalize_learner_help_feedback(raw) == expected


# ---------------------------------------------------------------------------
# build_tutor_feedback_adaptation
# ---------------------------------------------------------------------------


def test_feedback_adaptation_clear():
    ctrl = PracticeLoopController()
    result = ctrl.build_tutor_feedback_adaptation("clear")
    assert result["signal"] == "clear"
    assert "difficulty" in result["followup_prompt"].lower() or "harder" in result["followup_prompt"].lower()


def test_feedback_adaptation_stuck():
    ctrl = PracticeLoopController()
    result = ctrl.build_tutor_feedback_adaptation("stuck")
    assert result["signal"] == "stuck"
    assert "step" in result["followup_prompt"].lower() or "chunks" in result["followup_prompt"].lower()


def test_feedback_adaptation_unknown():
    ctrl = PracticeLoopController()
    result = ctrl.build_tutor_feedback_adaptation("something_else")
    assert result["signal"] == ""


# ---------------------------------------------------------------------------
# interpret_tutor_turn_for_loop
# ---------------------------------------------------------------------------


def test_interpret_turn_normal():
    ctrl = PracticeLoopController()
    turn = TutorTurnResult(text="Let's move to the next question.", model="test", latency_ms=100)
    result = ctrl.interpret_tutor_turn_for_loop(turn)
    assert result["decision_hint"] == "advance"
    assert result["has_error"] is False


def test_interpret_turn_support():
    ctrl = PracticeLoopController()
    turn = TutorTurnResult(text="Let me give you a hint.", model="test", latency_ms=100)
    result = ctrl.interpret_tutor_turn_for_loop(turn)
    assert result["decision_hint"] == "support"


def test_interpret_turn_with_error_code():
    ctrl = PracticeLoopController()
    turn = TutorTurnResult(text="", model="test", latency_ms=0, error_code="timeout")
    result = ctrl.interpret_tutor_turn_for_loop(turn)
    assert result["decision_hint"] == "neutral_fallback"
    assert result["has_error"] is True


# ---------------------------------------------------------------------------
# validate_loop_invariants
# ---------------------------------------------------------------------------


def test_validate_loop_invariants_passes_for_fresh_state():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    valid, errors = ctrl.validate_loop_invariants(loop_state)
    assert isinstance(valid, bool)
    assert isinstance(errors, list)


# ---------------------------------------------------------------------------
# calibrate_difficulty
# ---------------------------------------------------------------------------


def test_calibrate_difficulty_returns_valid_level():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    rec = ctrl.calibrate_difficulty(loop_state, latency_ms=10000.0, confidence=3)
    assert rec in {"easy", "medium", "hard", "easier", "same", "harder"}


# ---------------------------------------------------------------------------
# generate_elaboration_questions
# ---------------------------------------------------------------------------


def test_generate_elaboration_questions_returns_dict():
    ctrl = PracticeLoopController()
    item = _make_item()
    questions = ctrl.generate_elaboration_questions(item)
    assert isinstance(questions, dict)
    assert len(questions) > 0


# ---------------------------------------------------------------------------
# generate_transfer_task
# ---------------------------------------------------------------------------


def test_generate_transfer_task_returns_string():
    ctrl = PracticeLoopController()
    item = _make_item()
    task = ctrl.generate_transfer_task(item)
    assert isinstance(task, str)
    assert len(task) > 10


# ---------------------------------------------------------------------------
# schedule_next_retest
# ---------------------------------------------------------------------------


def test_schedule_next_retest_returns_expected_keys():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    item = _make_item()
    result = _make_correct_result(item)
    sched = ctrl.schedule_next_retest(loop_state, item, result)
    assert "topic" in sched
    assert "next_retest_days" in sched
    assert "should_retest_now" in sched
    assert sched["next_retest_days"] >= 0


# ---------------------------------------------------------------------------
# generate_session_reflection
# ---------------------------------------------------------------------------


def test_generate_session_reflection_returns_string():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    attempts = [("NPV calculation", True), ("WACC", False), ("NPV calculation", True)]
    reflection = ctrl.generate_session_reflection(loop_state, 25, attempts)
    assert isinstance(reflection, str)
    assert len(reflection) > 20


def test_generate_session_reflection_handles_empty_history():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    reflection = ctrl.generate_session_reflection(loop_state, 5, [])
    assert isinstance(reflection, str)


# ---------------------------------------------------------------------------
# generate_progressive_hints
# ---------------------------------------------------------------------------


def test_generate_progressive_hints_returns_list():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    item = _make_item()
    hints = ctrl.generate_progressive_hints(loop_state, item)
    assert isinstance(hints, list)
    assert len(hints) == 5


# ---------------------------------------------------------------------------
# get_next_hint
# ---------------------------------------------------------------------------


def test_get_next_hint_returns_hint_level():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    item = _make_item()
    hint = ctrl.get_next_hint(loop_state, item, has_attempted=True)
    assert hint is not None


# ---------------------------------------------------------------------------
# analyze_error_and_diagnose
# ---------------------------------------------------------------------------


def test_analyze_error_returns_analysis():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    item = _make_item()
    result = _make_incorrect_result(item)
    analysis = ctrl.analyze_error_and_diagnose(loop_state, result, item)
    assert isinstance(analysis, dict)
    assert "category" in analysis
    assert "remediation" in analysis


# ---------------------------------------------------------------------------
# track_confidence_and_calibrate
# ---------------------------------------------------------------------------


def test_track_confidence_and_calibrate_updates_tracker():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    result = ctrl.track_confidence_and_calibrate(
        loop_state, predicted_confidence=4, was_correct=True, topic="NPV calculation"
    )
    assert isinstance(result, dict)
    assert "calibration_feedback" in result


# ---------------------------------------------------------------------------
# recommend_next_action
# ---------------------------------------------------------------------------


def test_recommend_next_action_returns_string():
    ctrl = PracticeLoopController()
    loop_state = _make_loop_state()
    item = _make_item()
    result = _make_correct_result(item)
    action = ctrl.recommend_next_action(loop_state, item, result)
    assert isinstance(action, dict)
    assert action  # non-empty
