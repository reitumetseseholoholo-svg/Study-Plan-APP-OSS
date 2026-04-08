"""Unit tests for studyplan/confidence_tracking.py."""
from __future__ import annotations

import pytest

from studyplan.confidence_tracking import (
    ConfidenceCalibration,
    ConfidenceCalibrator,
    ConfidenceRecord,
    ConfidenceThresholdPolicy,
)


# ---------------------------------------------------------------------------
# ConfidenceCalibrator — edge cases
# ---------------------------------------------------------------------------


@pytest.fixture
def calibrator():
    return ConfidenceCalibrator(window_size=20)


def test_empty_calibrator_returns_zero_sample_size(calibrator):
    cal = calibrator.assess_calibration()
    assert cal.sample_size == 0


def test_fewer_than_three_attempts_returns_empty_calibration(calibrator):
    calibrator.add_attempt(predicted_confidence=4, was_correct=True, topic="NPV")
    calibrator.add_attempt(predicted_confidence=2, was_correct=False, topic="NPV")
    cal = calibrator.assess_calibration()
    assert cal.sample_size == 2
    assert cal.calibration_error == 0.0


def test_overconfident_detection():
    c = ConfidenceCalibrator(window_size=20)
    # 5/5 confidence every time, but only 2/5 correct.
    for _ in range(5):
        c.add_attempt(5, was_correct=False, topic="WACC")
    for _ in range(2):
        c.add_attempt(5, was_correct=True, topic="WACC")
    cal = c.assess_calibration()
    assert cal.is_overconfident is True
    assert cal.is_underconfident is False


def test_underconfident_detection():
    c = ConfidenceCalibrator(window_size=20)
    # Always 1/5 confidence, but always correct.
    for _ in range(8):
        c.add_attempt(1, was_correct=True, topic="DCF")
    cal = c.assess_calibration()
    assert cal.is_underconfident is True
    assert cal.is_overconfident is False


def test_well_calibrated_neither_flag():
    c = ConfidenceCalibrator(window_size=20)
    # 60 % confidence, 60 % correct.
    for _ in range(3):
        c.add_attempt(3, was_correct=True, topic="CAPM")
    for _ in range(2):
        c.add_attempt(3, was_correct=False, topic="CAPM")
    cal = c.assess_calibration()
    assert cal.is_overconfident is False
    assert cal.is_underconfident is False


def test_calibration_error_is_absolute_value(calibrator):
    for _ in range(5):
        calibrator.add_attempt(5, was_correct=False, topic="WC")
    cal = calibrator.assess_calibration()
    assert cal.calibration_error >= 0.0


def test_severity_severe_for_large_gap():
    c = ConfidenceCalibrator()
    for _ in range(10):
        c.add_attempt(5, was_correct=False, topic="NPV")
    cal = c.assess_calibration()
    assert cal.severity == "severe"


def test_severity_none_for_well_calibrated():
    c = ConfidenceCalibrator()
    for _ in range(6):
        c.add_attempt(3, was_correct=True, topic="FM")
    for _ in range(4):
        c.add_attempt(3, was_correct=False, topic="FM")
    cal = c.assess_calibration()
    assert cal.severity in {"none", "moderate"}


def test_window_size_enforced():
    c = ConfidenceCalibrator(window_size=5)
    for i in range(10):
        c.add_attempt(3, was_correct=(i % 2 == 0), topic="Topic")
    assert len(c.history) == 5


# ---------------------------------------------------------------------------
# ConfidenceCalibrator.get_calibration_feedback
# ---------------------------------------------------------------------------


def test_feedback_mentions_overconfident():
    c = ConfidenceCalibrator()
    for _ in range(8):
        c.add_attempt(5, was_correct=False, topic="NPV")
    fb = c.get_calibration_feedback()
    assert "overconfident" in fb.lower() or "confident" in fb.lower() or "humble" in fb.lower()


def test_feedback_mentions_underconfident():
    c = ConfidenceCalibrator()
    for _ in range(8):
        c.add_attempt(1, was_correct=True, topic="DCF")
    fb = c.get_calibration_feedback()
    assert any(word in fb.lower() for word in ("underconfident", "capable", "trust yourself", "more capable"))


def test_feedback_positive_for_calibrated():
    c = ConfidenceCalibrator()
    for _ in range(3):
        c.add_attempt(3, was_correct=True, topic="CAPM")
    for _ in range(2):
        c.add_attempt(3, was_correct=False, topic="CAPM")
    fb = c.get_calibration_feedback()
    assert any(word in fb.lower() for word in ("great", "good", "self-awareness", "matches"))


def test_feedback_with_too_few_samples_is_encouraging():
    c = ConfidenceCalibrator()
    c.add_attempt(3, was_correct=True, topic="T")
    fb = c.get_calibration_feedback()
    assert "practicing" in fb.lower() or "calibrate" in fb.lower() or "few" in fb.lower()


# ---------------------------------------------------------------------------
# ConfidenceCalibrator.get_summary_stats
# ---------------------------------------------------------------------------


def test_get_summary_stats_keys():
    c = ConfidenceCalibrator()
    for _ in range(5):
        c.add_attempt(3, was_correct=True, topic="T")
    stats = c.get_summary_stats()
    assert "sample_size" in stats
    assert "predicted_confidence" in stats
    assert "actual_accuracy" in stats
    assert "calibration_error" in stats
    assert "severity" in stats


# ---------------------------------------------------------------------------
# ConfidenceThresholdPolicy
# ---------------------------------------------------------------------------


def test_should_escalate_difficulty_when_confident_and_accurate():
    result = ConfidenceThresholdPolicy.should_escalate_difficulty(
        confidence=5, recent_accuracy=0.9, confidence_matches_accuracy=True
    )
    assert result is True


def test_should_not_escalate_if_not_accurate():
    result = ConfidenceThresholdPolicy.should_escalate_difficulty(
        confidence=5, recent_accuracy=0.4, confidence_matches_accuracy=False
    )
    assert result is False


def test_should_provide_scaffolding_when_low_confidence_and_struggling():
    result = ConfidenceThresholdPolicy.should_provide_extra_scaffolding(
        confidence=1, recent_accuracy=0.2, confidence_matches_accuracy=False
    )
    assert result is True


def test_should_provide_scaffolding_overconfident_failing():
    result = ConfidenceThresholdPolicy.should_provide_extra_scaffolding(
        confidence=5, recent_accuracy=0.3, confidence_matches_accuracy=False
    )
    assert result is True


def test_no_scaffolding_when_doing_well():
    result = ConfidenceThresholdPolicy.should_provide_extra_scaffolding(
        confidence=4, recent_accuracy=0.9, confidence_matches_accuracy=True
    )
    assert result is False


def test_trigger_metacognition_training_when_severe():
    cal = ConfidenceCalibration(
        predicted_confidence=0.9,
        actual_accuracy=0.4,
        calibration_error=0.5,
        is_overconfident=True,
        is_underconfident=False,
        sample_size=6,
        severity="severe",
    )
    assert ConfidenceThresholdPolicy.should_trigger_metacognition_training(cal) is True


def test_no_metacognition_trigger_with_too_few_samples():
    cal = ConfidenceCalibration(
        predicted_confidence=0.9,
        actual_accuracy=0.3,
        calibration_error=0.6,
        is_overconfident=True,
        is_underconfident=False,
        sample_size=2,
        severity="severe",
    )
    assert ConfidenceThresholdPolicy.should_trigger_metacognition_training(cal) is False


def test_normalized_confidence_over_5_scales_correctly():
    c = ConfidenceCalibrator()
    # Confidence passed as 100 (percentage) should be treated as >5, normalised to 1.0, then
    # stored as predicted_confidence = int(1.0 * 100) = 100.
    c.add_attempt(100, was_correct=True, topic="T")
    assert c.history[0].predicted_confidence == 100  # stored as int(normalised_fraction * 100)
