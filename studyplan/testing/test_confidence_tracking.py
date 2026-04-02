"""Tests for studyplan.confidence_tracking module."""
import pytest

from studyplan.confidence_tracking import (
    ConfidenceCalibration,
    ConfidenceCalibrator,
    ConfidenceThresholdPolicy,
)


# ---------------------------------------------------------------------------
# ConfidenceCalibrator — basic recording
# ---------------------------------------------------------------------------


def test_add_attempt_stores_record():
    cal = ConfidenceCalibrator()
    cal.add_attempt(3, True, topic="npv")
    assert len(cal.history) == 1


def test_window_size_enforced():
    cal = ConfidenceCalibrator(window_size=3)
    for i in range(5):
        cal.add_attempt(3, True)
    assert len(cal.history) == 3


def test_normalizes_confidence_1_5_scale():
    cal = ConfidenceCalibrator()
    cal.add_attempt(5, True)  # 5/5 = 100%
    assert cal.history[0].predicted_confidence == 100


def test_normalizes_confidence_0_100_scale():
    cal = ConfidenceCalibrator()
    cal.add_attempt(80, True)  # > 5 → treated as 0-100
    assert cal.history[0].predicted_confidence == 80


# ---------------------------------------------------------------------------
# ConfidenceCalibrator.assess_calibration
# ---------------------------------------------------------------------------


def test_assess_calibration_small_sample_returns_default():
    cal = ConfidenceCalibrator()
    cal.add_attempt(3, True)
    result = cal.assess_calibration()
    assert result.sample_size < 3
    assert result.calibration_error == 0.0


def test_assess_calibration_overconfident():
    cal = ConfidenceCalibrator()
    # 5/5 confident (100%) but all wrong
    for _ in range(5):
        cal.add_attempt(5, False)
    result = cal.assess_calibration()
    assert result.is_overconfident is True
    assert result.is_underconfident is False


def test_assess_calibration_underconfident():
    cal = ConfidenceCalibrator()
    # 1/5 confident (20%) but all correct
    for _ in range(5):
        cal.add_attempt(1, True)
    result = cal.assess_calibration()
    assert result.is_underconfident is True
    assert result.is_overconfident is False


def test_assess_calibration_well_calibrated():
    cal = ConfidenceCalibrator()
    # ~3/5 confident (60%) and ~60% correct
    for _ in range(3):
        cal.add_attempt(3, True)
    for _ in range(2):
        cal.add_attempt(3, False)
    result = cal.assess_calibration()
    assert result.severity in ("none", "moderate")


def test_assess_calibration_severity_severe():
    cal = ConfidenceCalibrator()
    # 100% confidence, 0% accuracy → >30% calibration error
    for _ in range(5):
        cal.add_attempt(5, False)
    result = cal.assess_calibration()
    assert result.severity == "severe"


def test_assess_calibration_returns_correct_sample_size():
    cal = ConfidenceCalibrator()
    for _ in range(4):
        cal.add_attempt(3, True)
    result = cal.assess_calibration()
    assert result.sample_size == 4


# ---------------------------------------------------------------------------
# ConfidenceCalibrator.get_calibration_feedback
# ---------------------------------------------------------------------------


def test_feedback_small_sample():
    cal = ConfidenceCalibrator()
    feedback = cal.get_calibration_feedback()
    assert "few more" in feedback.lower() or "keep" in feedback.lower()


def test_feedback_overconfident_message():
    cal = ConfidenceCalibrator()
    for _ in range(5):
        cal.add_attempt(5, False)
    feedback = cal.get_calibration_feedback()
    assert "confident" in feedback.lower() or "humble" in feedback.lower()


def test_feedback_underconfident_message():
    cal = ConfidenceCalibrator()
    for _ in range(5):
        cal.add_attempt(1, True)
    feedback = cal.get_calibration_feedback()
    assert "capable" in feedback.lower() or "trust" in feedback.lower()


def test_feedback_well_calibrated_message():
    cal = ConfidenceCalibrator()
    for _ in range(3):
        cal.add_attempt(3, True)
    for _ in range(2):
        cal.add_attempt(3, False)
    feedback = cal.get_calibration_feedback()
    # Should be positive / no severe mismatch
    assert isinstance(feedback, str)
    assert feedback


# ---------------------------------------------------------------------------
# ConfidenceCalibrator.get_summary_stats
# ---------------------------------------------------------------------------


def test_get_summary_stats_keys():
    cal = ConfidenceCalibrator()
    for _ in range(4):
        cal.add_attempt(3, True)
    stats = cal.get_summary_stats()
    assert "sample_size" in stats
    assert "predicted_confidence" in stats
    assert "actual_accuracy" in stats
    assert "calibration_error" in stats
    assert "severity" in stats


# ---------------------------------------------------------------------------
# ConfidenceThresholdPolicy
# ---------------------------------------------------------------------------


def test_escalate_difficulty_true_when_all_conditions_met():
    assert ConfidenceThresholdPolicy.should_escalate_difficulty(
        confidence=5, recent_accuracy=0.9, confidence_matches_accuracy=True
    ) is True


def test_escalate_difficulty_false_when_low_confidence():
    assert ConfidenceThresholdPolicy.should_escalate_difficulty(
        confidence=2, recent_accuracy=0.9, confidence_matches_accuracy=True
    ) is False


def test_escalate_difficulty_false_when_low_accuracy():
    assert ConfidenceThresholdPolicy.should_escalate_difficulty(
        confidence=5, recent_accuracy=0.4, confidence_matches_accuracy=True
    ) is False


def test_escalate_difficulty_false_when_not_calibrated():
    assert ConfidenceThresholdPolicy.should_escalate_difficulty(
        confidence=5, recent_accuracy=0.9, confidence_matches_accuracy=False
    ) is False


def test_provide_scaffolding_true_low_confidence_and_low_accuracy():
    assert ConfidenceThresholdPolicy.should_provide_extra_scaffolding(
        confidence=1, recent_accuracy=0.3, confidence_matches_accuracy=True
    ) is True


def test_provide_scaffolding_true_overconfident_and_failing():
    assert ConfidenceThresholdPolicy.should_provide_extra_scaffolding(
        confidence=5, recent_accuracy=0.3, confidence_matches_accuracy=False
    ) is True


def test_provide_scaffolding_false_when_doing_well():
    assert ConfidenceThresholdPolicy.should_provide_extra_scaffolding(
        confidence=3, recent_accuracy=0.8, confidence_matches_accuracy=True
    ) is False


def test_trigger_metacognition_true_for_severe():
    cal = ConfidenceCalibration(
        predicted_confidence=0.9,
        actual_accuracy=0.1,
        calibration_error=0.8,
        is_overconfident=True,
        is_underconfident=False,
        sample_size=6,
        severity="severe",
    )
    assert ConfidenceThresholdPolicy.should_trigger_metacognition_training(cal) is True


def test_trigger_metacognition_false_for_insufficient_samples():
    cal = ConfidenceCalibration(
        predicted_confidence=0.9,
        actual_accuracy=0.1,
        calibration_error=0.8,
        is_overconfident=True,
        is_underconfident=False,
        sample_size=3,
        severity="severe",
    )
    assert ConfidenceThresholdPolicy.should_trigger_metacognition_training(cal) is False


def test_trigger_metacognition_false_for_non_severe():
    cal = ConfidenceCalibration(
        predicted_confidence=0.5,
        actual_accuracy=0.6,
        calibration_error=0.1,
        is_overconfident=False,
        is_underconfident=False,
        sample_size=10,
        severity="none",
    )
    assert ConfidenceThresholdPolicy.should_trigger_metacognition_training(cal) is False
