import pytest

from studyplan.coach_fsm import SocraticFSM, SocraticDecision
from studyplan.cognitive_state import CognitiveState


def test_transition_invalid_state_logs():
    state = CognitiveState()
    # corrupt the socratic state
    state.working_memory.socratic_state = "UNKNOWN"
    fsm = SocraticFSM(state)
    dec = fsm.transition("QUIZ_START")
    assert isinstance(dec, SocraticDecision)
    assert dec.state in SocraticFSM.STATES


def test_basic_error_to_productive():
    state = CognitiveState()
    fsm = SocraticFSM(state)
    dec = fsm.transition("ERROR", {"chapter": "foo"})
    assert dec.state == "PRODUCTIVE_STRUGGLE"
