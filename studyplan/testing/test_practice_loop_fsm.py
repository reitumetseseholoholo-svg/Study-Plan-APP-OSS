import pytest

from studyplan.practice_loop_fsm import PracticeLoopFSM, PracticeLoopEvent, PracticeLoopState


def test_fsm_initial_state():
    fsm = PracticeLoopFSM()
    assert fsm.current_state == PracticeLoopState.IDLE


def test_fsm_valid_transition():
    fsm = PracticeLoopFSM()
    assert fsm.can_transition(PracticeLoopEvent.QUIZ_START)
    next_state, action = fsm.transition(PracticeLoopEvent.QUIZ_START)
    assert next_state == PracticeLoopState.PRESENTING
    assert fsm.current_state == PracticeLoopState.PRESENTING


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
    assert fsm.current_state == PracticeLoopState.PRESENTING
    fsm.transition(PracticeLoopEvent.ITEM_PRESENTED)
    assert fsm.current_state == PracticeLoopState.AWAITING_SUBMISSION
    fsm.transition(PracticeLoopEvent.SUBMISSION_RECEIVED)
    assert fsm.current_state == PracticeLoopState.ASSESSING
    next_s, action = fsm.transition(PracticeLoopEvent.ASSESSMENT_CORRECT)
    assert action == "update_posterior_alpha"
