"""Unit tests for studyplan/error_analysis.py."""
from __future__ import annotations

import pytest

from studyplan.error_analysis import (
    ErrorAnalysis,
    ErrorCategory,
    ErrorPatternDetector,
    Misconception,
    MisconceptionLibrary,
    _is_likely_sign_error,
)


# ---------------------------------------------------------------------------
# MisconceptionLibrary — built-in entries
# ---------------------------------------------------------------------------


def test_misconception_library_has_npv_entries():
    assert "npv" in MisconceptionLibrary.MISCONCEPTIONS
    assert "ignores_time" in MisconceptionLibrary.MISCONCEPTIONS["npv"]
    assert "sign_error" in MisconceptionLibrary.MISCONCEPTIONS["npv"]


def test_misconception_library_has_wacc_entries():
    assert "wacc" in MisconceptionLibrary.MISCONCEPTIONS
    assert "wrong_weights" in MisconceptionLibrary.MISCONCEPTIONS["wacc"]
    assert "ignores_tax" in MisconceptionLibrary.MISCONCEPTIONS["wacc"]


def test_misconception_fields():
    m = MisconceptionLibrary.MISCONCEPTIONS["npv"]["sign_error"]
    assert isinstance(m, Misconception)
    assert m.id
    assert m.name
    assert m.description
    assert m.correct_idea
    assert m.impact in {"low", "medium", "high"}


# ---------------------------------------------------------------------------
# MisconceptionLibrary.diagnose_error
# ---------------------------------------------------------------------------


def test_diagnose_sign_error_returns_procedural():
    analysis = MisconceptionLibrary.diagnose_error("npv", ("sign_error",))
    assert analysis.category == ErrorCategory.PROCEDURAL
    assert analysis.confidence > 0.5


def test_diagnose_sign_error_has_misconception_for_npv():
    analysis = MisconceptionLibrary.diagnose_error("npv", ("sign_error",))
    assert analysis.misconception is not None
    assert "sign" in analysis.misconception.id


def test_diagnose_formula_error_is_procedural():
    analysis = MisconceptionLibrary.diagnose_error("wacc", ("formula_error",))
    assert analysis.category == ErrorCategory.PROCEDURAL


def test_diagnose_precision_error_is_careless():
    analysis = MisconceptionLibrary.diagnose_error("npv", ("precision_error",))
    assert analysis.category == ErrorCategory.CARELESS
    assert analysis.confidence > 0.8


def test_diagnose_incomplete_error():
    analysis = MisconceptionLibrary.diagnose_error("wacc", ("incomplete",))
    assert analysis.category == ErrorCategory.INCOMPLETE


def test_diagnose_default_is_conceptual():
    analysis = MisconceptionLibrary.diagnose_error("some_topic", ())
    assert analysis.category == ErrorCategory.CONCEPTUAL


def test_diagnose_unknown_topic_still_returns_analysis():
    analysis = MisconceptionLibrary.diagnose_error("quantum_physics", ("formula_error",))
    assert isinstance(analysis, ErrorAnalysis)
    assert analysis.category in list(ErrorCategory)


def test_diagnose_detects_sign_error_from_numeric_values():
    # user_answer = -5, expected = 5 → sign error
    analysis = MisconceptionLibrary.diagnose_error("npv", (), user_answer="-5", expected_answer="5")
    assert analysis.category == ErrorCategory.PROCEDURAL


# ---------------------------------------------------------------------------
# MisconceptionLibrary.get_remediation_steps
# ---------------------------------------------------------------------------


def test_get_remediation_steps_returns_list():
    m = MisconceptionLibrary.MISCONCEPTIONS["wacc"]["ignores_tax"]
    steps = MisconceptionLibrary.get_remediation_steps(m)
    assert isinstance(steps, list)
    assert len(steps) >= 3


def test_get_remediation_steps_reference_misconception():
    m = MisconceptionLibrary.MISCONCEPTIONS["npv"]["ignores_time"]
    steps = MisconceptionLibrary.get_remediation_steps(m)
    combined = " ".join(steps).lower()
    assert any(word in combined for word in ("discount", "npv", "timing", "cash"))


# ---------------------------------------------------------------------------
# _is_likely_sign_error helper
# ---------------------------------------------------------------------------


def test_sign_error_detected_for_negatives():
    assert _is_likely_sign_error("-100", "100") is True
    assert _is_likely_sign_error("50", "-50") is True


def test_sign_error_not_detected_for_unrelated_values():
    assert _is_likely_sign_error("3", "7") is False


def test_sign_error_handles_non_numeric():
    assert _is_likely_sign_error("abc", "def") is False
    assert _is_likely_sign_error("", "") is False


# ---------------------------------------------------------------------------
# ErrorPatternDetector
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    return ErrorPatternDetector(history_limit=10)


def _make_analysis(category: ErrorCategory, misc_id: str | None = None) -> ErrorAnalysis:
    misc = None
    if misc_id:
        misc = Misconception(
            id=misc_id,
            name=misc_id,
            description="desc",
            correct_idea="correct",
        )
    return ErrorAnalysis(category=category, misconception=misc, confidence=0.8, remediation="fix")


def test_detect_pattern_returns_none_with_single_error(detector):
    detector.add_error(_make_analysis(ErrorCategory.CONCEPTUAL))
    assert detector.detect_pattern() is None


def test_detect_pattern_finds_recurring_misconception(detector):
    for _ in range(3):
        detector.add_error(_make_analysis(ErrorCategory.PROCEDURAL, misc_id="npv_sign_error"))
    result = detector.detect_pattern()
    assert result is not None
    pattern, confidence = result
    assert "npv_sign_error" in pattern
    assert 0.0 < confidence <= 1.0


def test_detect_pattern_finds_category_pattern(detector):
    for _ in range(3):
        detector.add_error(_make_analysis(ErrorCategory.CARELESS))
    result = detector.detect_pattern()
    assert result is not None
    pattern, confidence = result
    assert "careless" in pattern.lower()


def test_should_trigger_intervention_false_without_enough_errors(detector):
    detector.add_error(_make_analysis(ErrorCategory.CONCEPTUAL, misc_id="x"))
    detector.add_error(_make_analysis(ErrorCategory.CONCEPTUAL, misc_id="x"))
    assert detector.should_trigger_intervention() is False


def test_should_trigger_intervention_true_on_recurring_pattern(detector):
    for _ in range(4):
        detector.add_error(_make_analysis(ErrorCategory.PROCEDURAL, misc_id="wacc_ignores_tax"))
    result = detector.should_trigger_intervention()
    assert result is True


def test_history_limit_is_respected():
    d = ErrorPatternDetector(history_limit=3)
    for _ in range(6):
        d.add_error(_make_analysis(ErrorCategory.CARELESS))
    assert len(d.error_history) == 3
