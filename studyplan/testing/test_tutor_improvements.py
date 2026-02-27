"""Tests for hint system, error analysis, and confidence tracking."""

import pytest

from studyplan.hint_system import HintBank, HintLevel
from studyplan.error_analysis import (
    ErrorCategory,
    ErrorAnalysis,
    MisconceptionLibrary,
    ErrorPatternDetector,
)
from studyplan.confidence_tracking import (
    ConfidenceCalibrator,
    ConfidenceCalibration,
)


class TestHintBank:
    """Test progressive hint generation."""
    
    def test_numeric_hint_sequence(self):
        """Test hints escalate from nudge to solution."""
        bank = HintBank(
            topic="NPV calculation",
            concept="net present value",
            item_type="numeric",
            expected_answer="250000",
            error_tags=("formula_error",),
        )
        hints = bank.generate_hints()
        
        assert len(hints) == 5
        assert hints[0].level == 0
        assert hints[0].label == "Nudge"
        assert hints[4].level == 4
        assert hints[4].label == "Solution"
    
    def test_short_answer_hints(self):
        """Test short answer hints."""
        bank = HintBank(
            topic="Working Capital",
            concept="operating cycle",
            item_type="short_answer",
            expected_answer="The operating cycle is receivables plus inventory minus payables",
        )
        hints = bank.generate_hints()
        
        # Should have content at each level
        for hint in hints:
            assert hint.text  # Not empty
            assert hint.context  # Contextual label
    
    def test_hint_escalation(self):
        """Test recommend_next_level logic."""
        # No attempt → same level
        assert HintBank.recommend_next_level(0, has_attempted=False, is_struggling=False) == 0
        
        # After attempt → next level
        assert HintBank.recommend_next_level(1, has_attempted=True, is_struggling=False) == 2
        
        # Struggling → escalate faster
        assert HintBank.recommend_next_level(0, has_attempted=True, is_struggling=True) == 2
        
        # Clamp to max level
        assert HintBank.recommend_next_level(4, has_attempted=True, is_struggling=False) == 4


class TestErrorAnalysis:
    """Test misconception detection."""
    
    def test_sign_error_detection(self):
        """Detect sign errors in numeric answers."""
        analysis = MisconceptionLibrary.diagnose_error(
            topic="npv",
            error_tags=("sign_error",),
            user_answer="-250000",
            expected_answer="250000",
        )
        
        assert analysis.category == ErrorCategory.PROCEDURAL
        assert analysis.confidence > 0.8
        assert "sign" in analysis.remediation.lower()
    
    def test_formula_error_detection(self):
        """Detect when formula is wrong."""
        analysis = MisconceptionLibrary.diagnose_error(
            topic="wacc",
            error_tags=("formula_error",),
        )
        
        assert analysis.category == ErrorCategory.PROCEDURAL
    
    def test_procedural_vs_careless(self):
        """Distinguish procedural errors from careless ones."""
        procedural = MisconceptionLibrary.diagnose_error(
            topic="npv",
            error_tags=("formula_error",),
        )
        assert procedural.category == ErrorCategory.PROCEDURAL
        
        careless = MisconceptionLibrary.diagnose_error(
            topic="npv",
            error_tags=("precision_error",),
        )
        assert careless.category == ErrorCategory.CARELESS
    
    def test_misconception_remediation(self):
        """Test remediation steps for misconception."""
        misconception = MisconceptionLibrary.MISCONCEPTIONS["npv"]["ignores_time"]
        steps = MisconceptionLibrary.get_remediation_steps(misconception)
        
        assert len(steps) == 4
        assert "Identify" in steps[0]
        assert "Understand" in steps[1]
        assert "Practice" in steps[2]
        assert "Reflect" in steps[3]


class TestErrorPatternDetector:
    """Test pattern detection in repeated errors."""
    
    def test_no_pattern_with_few_errors(self):
        """Pattern requires enough samples."""
        detector = ErrorPatternDetector()
        error1 = ErrorAnalysis(ErrorCategory.PROCEDURAL)
        detector.add_error(error1)
        
        assert detector.detect_pattern() is None
        assert not detector.should_trigger_intervention()
    
    def test_recurring_misconception_detection(self):
        """Detect when same misconception repeats."""
        detector = ErrorPatternDetector()
        misconception = MisconceptionLibrary.MISCONCEPTIONS["npv"]["sign_error"]
        
        # Add same misconception 3 times
        for _ in range(3):
            error = ErrorAnalysis(
                category=ErrorCategory.PROCEDURAL,
                misconception=misconception,
                confidence=0.85,
            )
            detector.add_error(error)
        
        pattern, conf = detector.detect_pattern()
        assert pattern is not None
        assert "Recurring" in pattern
        assert conf > 0.70  # High confidence in pattern
        assert detector.should_trigger_intervention()
    
    def test_error_category_pattern(self):
        """Detect when same error category repeats."""
        detector = ErrorPatternDetector()
        
        for _ in range(3):
            error = ErrorAnalysis(category=ErrorCategory.CARELESS)
            detector.add_error(error)
        
        pattern, conf = detector.detect_pattern()
        assert pattern is not None
        assert "Pattern" in pattern or "Recurring" in pattern


class TestConfidenceCalibrator:
    """Test confidence calibration tracking."""
    
    def test_perfect_calibration(self):
        """Test when confidence matches accuracy."""
        calibrator = ConfidenceCalibrator()
        
        # Add high-confidence + high-accuracy
        for _ in range(5):
            calibrator.add_attempt(predicted_confidence=5, was_correct=True, topic="npv")
        
        cal = calibrator.assess_calibration()
        assert cal.sample_size == 5
        assert cal.actual_accuracy == 1.0  # 100% correct
        assert abs(cal.predicted_confidence - 1.0) < 0.1  # ~100% confident
        assert cal.calibration_error < 0.15  # Well calibrated
        assert cal.severity == "none"
    
    def test_overconfidence_detection(self):
        """Detect when learner is overconfident."""
        calibrator = ConfidenceCalibrator()
        
        # High confidence, low accuracy
        for _ in range(5):
            calibrator.add_attempt(predicted_confidence=5, was_correct=False, topic="wacc")
        
        cal = calibrator.assess_calibration()
        assert cal.is_overconfident
        assert not cal.is_underconfident
        assert cal.actual_accuracy < 0.3
    
    def test_underconfidence_detection(self):
        """Detect when learner is underconfident."""
        calibrator = ConfidenceCalibrator()
        
        # Low confidence, high accuracy
        for _ in range(5):
            calibrator.add_attempt(predicted_confidence=2, was_correct=True, topic="wcm")
        
        cal = calibrator.assess_calibration()
        assert cal.is_underconfident
        assert not cal.is_overconfident
        assert cal.actual_accuracy > 0.8
    
    def test_calibration_feedback(self):
        """Test feedback generation."""
        calibrator = ConfidenceCalibrator()
        
        # Underconfident: low confidence, high accuracy
        for _ in range(4):
            calibrator.add_attempt(predicted_confidence=2, was_correct=True, topic="test")
        
        feedback = calibrator.get_calibration_feedback()
        assert "capable" in feedback.lower()  # Encouragement for underconfident
        assert "✨" in feedback or "💪" in feedback
    
    def test_calibration_summary(self):
        """Test summary statistics."""
        calibrator = ConfidenceCalibrator()
        for i in range(5):
            calibrator.add_attempt(
                predicted_confidence=4,
                was_correct=(i % 2 == 0),
                topic="test",
            )
        
        stats = calibrator.get_summary_stats()
        assert "sample_size" in stats
        assert "predicted_confidence" in stats
        assert "actual_accuracy" in stats
        assert "severity" in stats


def test_hint_integration_with_errors():
    """Test hint system adapts to error type."""
    sign_error = MisconceptionLibrary.diagnose_error(
        topic="npv",
        error_tags=("sign_error",),
    )
    
    # Create hint bank that knows about sign errors
    bank = HintBank(
        topic="NPV",
        concept="net present value",
        item_type="numeric",
        error_tags=("sign_error",),
    )
    
    # Light hint should mention signs
    light_hint = bank.get_hint(1)
    assert light_hint.level == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
