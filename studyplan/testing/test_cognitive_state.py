import pytest

from studyplan.cognitive_state import CognitiveState, CognitiveStateValidator, CompetencyPosterior


def test_validator_good_default():
    st = CognitiveState()
    valid, errors = CognitiveStateValidator.validate(st)
    assert valid
    assert errors == []


def test_posteriors_mean_bounds():
    st = CognitiveState()
    st.posteriors["topicA"] = CompetencyPosterior(alpha=3.0, beta=-1.0)
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


def test_recommend_intervention_level_none_for_clean_correct():
    st = CognitiveState()
    level = st.recommend_intervention_level(
        outcome="correct",
        hints_used=0,
        pattern_detected=False,
        confidence_delta=None,
    )
    assert level == "none"


def test_recommend_intervention_level_strong_for_incorrect():
    st = CognitiveState()
    level = st.recommend_intervention_level(
        outcome="incorrect",
        hints_used=1,
        pattern_detected=False,
        confidence_delta=None,
    )
    assert level == "strong"


def test_recommend_intervention_level_escalates_with_pattern():
    st = CognitiveState()
    level = st.recommend_intervention_level(
        outcome="partial",
        hints_used=2,
        pattern_detected=True,
        confidence_delta=0.3,
    )
    assert level == "strong"


def test_recommend_intervention_level_unknown_outcome_defaults_none_without_signals():
    st = CognitiveState()
    level = st.recommend_intervention_level(
        outcome="mystery",
        hints_used=0,
        pattern_detected=False,
        confidence_delta=None,
    )
    assert level == "none"


def test_recommend_intervention_level_handles_non_finite_confidence_delta():
    st = CognitiveState()
    level_nan = st.recommend_intervention_level(
        outcome="partial",
        hints_used=0,
        pattern_detected=False,
        confidence_delta=float("nan"),
    )
    level_inf = st.recommend_intervention_level(
        outcome="partial",
        hints_used=0,
        pattern_detected=False,
        confidence_delta=float("inf"),
    )
    assert level_nan == "light"
    assert level_inf == "light"
