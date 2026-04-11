import pytest

from studyplan.practice_loop_fsm import (
    PracticeLoopFSM,
    PracticeLoopEvent,
    PracticeLoopFsmState,
    coerce_practice_loop_state,
    normalize_assessment_outcome,
    recommend_action_policy,
)


def test_fsm_initial_state():
    fsm = PracticeLoopFSM()
    assert fsm.current_state == PracticeLoopFsmState.IDLE


def test_fsm_valid_transition():
    fsm = PracticeLoopFSM()
    assert fsm.can_transition(PracticeLoopEvent.QUIZ_START)
    next_state, action = fsm.transition(PracticeLoopEvent.QUIZ_START)
    assert next_state == PracticeLoopFsmState.PRESENTING
    assert fsm.current_state == PracticeLoopFsmState.PRESENTING


def test_fsm_accepts_initial_state_string():
    fsm = PracticeLoopFSM("awaiting_submission")
    assert fsm.current_state == PracticeLoopFsmState.AWAITING_SUBMISSION
    next_state, _action = fsm.transition(PracticeLoopEvent.SUBMISSION_RECEIVED)
    assert next_state == PracticeLoopFsmState.ASSESSING


def test_coerce_practice_loop_state_defaults_to_idle_for_unknown_value():
    assert coerce_practice_loop_state("mystery") == PracticeLoopFsmState.IDLE


def test_fsm_invalid_transition():
    fsm = PracticeLoopFSM()
    assert not fsm.can_transition(PracticeLoopEvent.SUBMISSION_RECEIVED)
    with pytest.raises(ValueError):
        fsm.transition(PracticeLoopEvent.SUBMISSION_RECEIVED)


def test_fsm_allowed_events():
    fsm = PracticeLoopFSM()
    allowed = fsm.allowed_events()
    assert PracticeLoopEvent.QUIZ_START in allowed
    assert len(allowed) > 0


def test_fsm_full_sequence():
    fsm = PracticeLoopFSM()
    fsm.transition(PracticeLoopEvent.QUIZ_START)
    assert fsm.current_state == PracticeLoopFsmState.PRESENTING
    fsm.transition(PracticeLoopEvent.ITEM_PRESENTED)
    assert fsm.current_state == PracticeLoopFsmState.AWAITING_SUBMISSION
    fsm.transition(PracticeLoopEvent.SUBMISSION_RECEIVED)
    assert fsm.current_state == PracticeLoopFsmState.ASSESSING
    next_s, action = fsm.transition(PracticeLoopEvent.ASSESSMENT_CORRECT)
    assert action == "update_posterior_alpha"


def test_recommend_action_policy_for_incorrect_pattern():
    decision = recommend_action_policy(
        outcome="incorrect",
        pattern_detected=True,
        pattern_description="Recurring sign error in NPV",
    )
    assert decision.urgent is True
    assert decision.reason == "Recurring sign error in NPV"
    assert "retry" in decision.next_action.lower()


def test_recommend_action_policy_for_partial():
    decision = recommend_action_policy(outcome="partial")
    assert decision.urgent is True
    assert "missing" in decision.reason.lower()
    assert "resubmit" in decision.next_action.lower()


def test_recommend_action_policy_for_correct_can_transfer():
    decision = recommend_action_policy(outcome="correct", can_transfer=True)
    assert decision.urgent is False
    assert "transfer" in decision.next_action.lower()


def test_recommend_action_policy_unknown_outcome_defaults():
    decision = recommend_action_policy(outcome="mystery")
    assert decision.urgent is False
    assert decision.reason == "Continue building momentum."
    assert "next question" in decision.next_action.lower()


def test_recommend_action_policy_incorrect_uses_remediation_text():
    decision = recommend_action_policy(
        outcome="incorrect",
        remediation="Re-check the discounting step and signs.",
    )
    assert decision.urgent is True
    assert decision.reason == "Re-check the discounting step and signs."


def test_normalize_assessment_outcome_unknown_for_unexpected_value():
    assert normalize_assessment_outcome("MYSTERY") == "unknown"
    assert normalize_assessment_outcome(None) == "unknown"


def test_recommend_action_policy_coerces_string_booleans():
    decision = recommend_action_policy(
        outcome="correct",
        can_transfer="false",
    )
    assert "transfer variant" not in decision.next_action.lower()
