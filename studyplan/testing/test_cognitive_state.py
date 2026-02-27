import pytest

from studyplan.cognitive_state import CognitiveState, CognitiveStateValidator


def test_validator_good_default():
    st = CognitiveState()
    valid, errors = CognitiveStateValidator.validate(st)
    assert valid
    assert errors == []


def test_posteriors_mean_bounds():
    st = CognitiveState()
    st.posteriors["topicA"] = type("P", (), {"mean": 1.5})()
    valid, errors = CognitiveStateValidator.validate(st)
    assert not valid
    assert any("outside [0,1]" in e for e in errors)


def test_quiz_active_invariant():
    st = CognitiveState()
    st.quiz_active = True
    st.working_memory.active_question_id = None
    valid, errors = CognitiveStateValidator.validate(st)
    assert not valid
    assert any("quiz_active" in e for e in errors)


def test_mark_corrupted_sets_readonly():
    st = CognitiveState()
    st.mark_corrupted("whatever")
    assert st.mode == CognitiveState.Mode.READONLY
    assert "last_error" in st.recovery_hints
