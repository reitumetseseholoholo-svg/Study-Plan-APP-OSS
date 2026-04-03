"""Tests for studyplan.error_analysis module."""
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
# _is_likely_sign_error
# ---------------------------------------------------------------------------


def test_sign_error_detected_for_negated_value():
    assert _is_likely_sign_error("-5.0", "5.0") is True


def test_sign_error_not_detected_for_different_magnitudes():
    assert _is_likely_sign_error("3.0", "5.0") is False


def test_sign_error_not_detected_for_non_numeric():
    assert _is_likely_sign_error("abc", "5.0") is False


def test_sign_error_not_detected_for_both_non_numeric():
    assert _is_likely_sign_error("foo", "bar") is False


def test_sign_error_with_zero():
    assert _is_likely_sign_error("0.0", "0.0") is True


# ---------------------------------------------------------------------------
# MisconceptionLibrary.diagnose_error
# ---------------------------------------------------------------------------


def test_diagnose_sign_error_tag():
    result = MisconceptionLibrary.diagnose_error("npv", ("sign_error",))
    assert result.category == ErrorCategory.PROCEDURAL
    assert "sign" in result.remediation.lower()


def test_diagnose_sign_error_from_values():
    result = MisconceptionLibrary.diagnose_error("npv", (), user_answer="-100", expected_answer="100")
    assert result.category == ErrorCategory.PROCEDURAL


def test_diagnose_formula_error_tag():
    result = MisconceptionLibrary.diagnose_error("wacc", ("formula_error",))
    assert result.category == ErrorCategory.PROCEDURAL
    assert "formula" in result.remediation.lower()


def test_diagnose_formula_error_attaches_misconception_for_known_topic():
    result = MisconceptionLibrary.diagnose_error("npv", ("formula_error",))
    assert result.misconception is not None


def test_diagnose_formula_error_no_misconception_for_unknown_topic():
    result = MisconceptionLibrary.diagnose_error("unknown_topic", ("formula_error",))
    assert result.misconception is None


def test_diagnose_precision_error_tag():
    result = MisconceptionLibrary.diagnose_error("wacc", ("precision_error",))
    assert result.category == ErrorCategory.CARELESS


def test_diagnose_rounding_error_tag():
    result = MisconceptionLibrary.diagnose_error("npv", ("rounding_error",))
    assert result.category == ErrorCategory.CARELESS


def test_diagnose_incomplete_tag():
    result = MisconceptionLibrary.diagnose_error("wacc", ("incomplete",))
    assert result.category == ErrorCategory.INCOMPLETE


def test_diagnose_default_conceptual():
    result = MisconceptionLibrary.diagnose_error("wacc", ())
    assert result.category == ErrorCategory.CONCEPTUAL


def test_diagnose_confidence_values_in_range():
    for tags in [("sign_error",), ("formula_error",), ("precision_error",), ("incomplete",), ()]:
        result = MisconceptionLibrary.diagnose_error("npv", tags)
        assert 0.0 <= result.confidence <= 1.0


def test_diagnose_empty_topic_falls_back_gracefully():
    result = MisconceptionLibrary.diagnose_error("", ())
    assert isinstance(result, ErrorAnalysis)


# ---------------------------------------------------------------------------
# MisconceptionLibrary.get_remediation_steps
# ---------------------------------------------------------------------------


def test_get_remediation_steps_returns_four_steps():
    misc = MisconceptionLibrary.MISCONCEPTIONS["npv"]["ignores_time"]
    steps = MisconceptionLibrary.get_remediation_steps(misc)
    assert len(steps) == 4


def test_get_remediation_steps_mentions_misconception_name():
    misc = MisconceptionLibrary.MISCONCEPTIONS["wacc"]["wrong_weights"]
    steps = MisconceptionLibrary.get_remediation_steps(misc)
    combined = " ".join(steps).lower()
    assert "book" in combined or "market" in combined


# ---------------------------------------------------------------------------
# ErrorPatternDetector
# ---------------------------------------------------------------------------


def _make_conceptual_error() -> ErrorAnalysis:
    return ErrorAnalysis(category=ErrorCategory.CONCEPTUAL, misconception=None, confidence=0.5)


def _make_procedural_error_with_misc(misc_id: str) -> ErrorAnalysis:
    misc = Misconception(
        id=misc_id, name="test", description="desc", correct_idea="idea"
    )
    return ErrorAnalysis(category=ErrorCategory.PROCEDURAL, misconception=misc, confidence=0.8)


def test_detect_pattern_returns_none_with_one_error():
    det = ErrorPatternDetector()
    det.add_error(_make_conceptual_error())
    assert det.detect_pattern() is None


def test_detect_pattern_returns_none_with_two_errors():
    det = ErrorPatternDetector()
    det.add_error(_make_conceptual_error())
    det.add_error(_make_conceptual_error())
    assert det.detect_pattern() is None


def test_detect_pattern_by_misconception_id():
    det = ErrorPatternDetector()
    for _ in range(3):
        det.add_error(_make_procedural_error_with_misc("npv_sign_error"))
    result = det.detect_pattern()
    assert result is not None
    pattern_desc, confidence = result
    assert "npv_sign_error" in pattern_desc
    assert confidence >= 0.70


def test_detect_pattern_by_category():
    det = ErrorPatternDetector()
    for _ in range(3):
        det.add_error(_make_conceptual_error())
    result = det.detect_pattern()
    assert result is not None
    pattern_desc, confidence = result
    assert "conceptual" in pattern_desc.lower()


def test_history_limit_enforced():
    det = ErrorPatternDetector(history_limit=5)
    for _ in range(8):
        det.add_error(_make_conceptual_error())
    assert len(det.error_history) == 5


def test_should_trigger_intervention_true_for_repeated_misconception():
    det = ErrorPatternDetector()
    for _ in range(3):
        det.add_error(_make_procedural_error_with_misc("wacc_wrong_weights"))
    assert det.should_trigger_intervention() is True


def test_should_trigger_intervention_false_for_sparse_errors():
    det = ErrorPatternDetector()
    det.add_error(_make_conceptual_error())
    assert det.should_trigger_intervention() is False
