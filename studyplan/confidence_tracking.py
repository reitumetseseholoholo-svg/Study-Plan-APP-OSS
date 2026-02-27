"""Real-time confidence calibration tracking.

Monitors learner's self-predicted confidence vs actual performance
to improve metacognitive awareness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .logging_config import get_logger


logger = get_logger(__name__)


@dataclass
class ConfidenceRecord:
    """Single confidence prediction and outcome."""
    
    predicted_confidence: int  # [1, 5] or [0, 100%]
    was_correct: bool
    topic: str = ""
    concept: str = ""
    timestamp: str = ""


@dataclass
class ConfidenceCalibration:
    """Aggregated calibration metrics."""
    
    predicted_confidence: float  # [0, 1] average
    actual_accuracy: float       # [0, 1] when they said confident
    calibration_error: float     # |predicted - actual|, 0=perfect
    is_overconfident: bool       # predicted > actual
    is_underconfident: bool      # predicted < actual
    sample_size: int             # How many samples
    severity: str = "none"       # "severe" | "moderate" | "none"


class ConfidenceCalibrator:
    """Track and improve learner confidence calibration."""
    
    def __init__(self, window_size: int = 20):
        """
        Initialize calibrator.
        
        Args:
            window_size: How many recent attempts to analyze
        """
        self.window_size = window_size
        self.history: list[ConfidenceRecord] = []
    
    def add_attempt(
        self,
        predicted_confidence: int,
        was_correct: bool,
        topic: str = "",
        concept: str = "",
    ) -> None:
        """
        Record a confidence prediction and outcome.
        
        Args:
            predicted_confidence: 1-5 or 0-100
            was_correct: Actual performance
            topic: Topic attempted
            concept: Concept name
        """
        # Normalize to [0, 1] if needed
        conf_normalized = predicted_confidence / 100.0 if predicted_confidence > 5 else predicted_confidence / 5.0
        conf_normalized = max(0.0, min(1.0, conf_normalized))
        
        record = ConfidenceRecord(
            predicted_confidence=int(conf_normalized * 100),
            was_correct=was_correct,
            topic=topic,
            concept=concept,
        )
        self.history.append(record)
        
        if len(self.history) > self.window_size:
            self.history.pop(0)
        
        logger.debug(
            "confidence recorded",
            extra={
                "confidence": predicted_confidence,
                "correct": was_correct,
                "topic": topic,
            },
        )
    
    def assess_calibration(self) -> ConfidenceCalibration:
        """
        Compute calibration metrics.
        
        Returns:
            ConfidenceCalibration with error and recommendations
        """
        if len(self.history) < 3:
            return ConfidenceCalibration(
                predicted_confidence=0.0,
                actual_accuracy=0.0,
                calibration_error=0.0,
                is_overconfident=False,
                is_underconfident=False,
                sample_size=len(self.history),
            )
        
        # Average predicted confidence (normalize to [0, 1])
        avg_predicted = sum(r.predicted_confidence for r in self.history) / len(self.history) / 100.0
        
        # Actual accuracy
        avg_actual = sum(1.0 for r in self.history if r.was_correct) / len(self.history)
        
        # Calibration error: |predicted - actual|
        calibration_error = abs(avg_predicted - avg_actual)
        
        # Direction
        is_overconfident = avg_predicted > avg_actual + 0.10
        is_underconfident = avg_predicted < avg_actual - 0.10
        
        # Severity
        if calibration_error > 0.3:
            severity = "severe"
        elif calibration_error > 0.15:
            severity = "moderate"
        else:
            severity = "none"
        
        return ConfidenceCalibration(
            predicted_confidence=avg_predicted,
            actual_accuracy=avg_actual,
            calibration_error=calibration_error,
            is_overconfident=is_overconfident,
            is_underconfident=is_underconfident,
            sample_size=len(self.history),
            severity=severity,
        )
    
    def get_calibration_feedback(self) -> str:
        """Generate feedback on confidence calibration."""
        cal = self.assess_calibration()
        
        if cal.sample_size < 3:
            return "Keep practicing—I'll calibrate your confidence after a few more attempts."
        
        lines = []
        
        if cal.is_overconfident:
            lines.append(
                f"🎯 You're saying you're ~{int(cal.predicted_confidence * 100)}% confident, "
                f"but you're getting about {int(cal.actual_accuracy * 100)}% correct."
            )
            lines.append("💡 Try being a bit more humble—trust yourself only when you're sure.")
            lines.append("Action: Before answering, ask 'Can I explain why this is right?'")
        elif cal.is_underconfident:
            lines.append(
                f"✨ You're only saying you're ~{int(cal.predicted_confidence * 100)}% confident, "
                f"but you're getting {int(cal.actual_accuracy * 100)}% correct!"
            )
            lines.append("💪 You're more capable than you think. Trust yourself more.")
            lines.append(
                "Action: Notice when you get it right, then claim it: 'Yes, I knew that!'"
            )
        else:
            lines.append(
                f"✓ Great self-awareness! You say you're ~{int(cal.predicted_confidence * 100)}% sure, "
                f"and you're actually {int(cal.actual_accuracy * 100)}% correct."
            )
            lines.append("💎 Your confidence matches your knowledge. Keep this up!")
        
        return "\n".join(lines)
    
    def get_summary_stats(self) -> dict[str, Any]:
        """Get all calibration statistics."""
        cal = self.assess_calibration()
        return {
            "sample_size": cal.sample_size,
            "predicted_confidence": f"{cal.predicted_confidence * 100:.0f}%",
            "actual_accuracy": f"{cal.actual_accuracy * 100:.0f}%",
            "calibration_error": f"{cal.calibration_error * 100:.0f}%",
            "is_overconfident": cal.is_overconfident,
            "is_underconfident": cal.is_underconfident,
            "severity": cal.severity,
        }


class ConfidenceThresholdPolicy:
    """Decide action based on confidence vs performance."""
    
    @staticmethod
    def should_escalate_difficulty(
        confidence: int,  # 1-5
        recent_accuracy: float,  # [0, 1]
        confidence_matches_accuracy: bool,
    ) -> bool:
        """
        Should we increase difficulty?
        
        Args:
            confidence: Learner's stated confidence
            recent_accuracy: Actual performance (last 3 attempts)
            confidence_matches_accuracy: Is calibration good?
        
        Returns:
            True = escalate, False = stay same or decrease
        """
        # If they're confident AND accurate AND calibrated, increase
        if confidence >= 4 and recent_accuracy >= 0.75 and confidence_matches_accuracy:
            return True
        
        return False
    
    @staticmethod
    def should_provide_extra_scaffolding(
        confidence: int,  # 1-5
        recent_accuracy: float,  # [0, 1]
        confidence_matches_accuracy: bool,
    ) -> bool:
        """
        Should we provide more scaffolding?
        
        Args:
            confidence: Learner's stated confidence
            recent_accuracy: Actual performance
            confidence_matches_accuracy: Is calibration good?
        
        Returns:
            True = add scaffolding, False = normal help
        """
        # If they're not confident AND struggling, definitely scaffold
        if confidence <= 2 and recent_accuracy < 0.50:
            return True
        
        # If they're confident but failing (overconfident), scaffold
        if confidence >= 4 and recent_accuracy < 0.50 and not confidence_matches_accuracy:
            return True
        
        return False
    
    @staticmethod
    def should_trigger_metacognition_training(
        calibration: ConfidenceCalibration,
    ) -> bool:
        """
        Should we explicitly train confidence calibration?
        
        Args:
            calibration: Current calibration metrics
        
        Returns:
            True = run intervention, False = continue normal practice
        """
        # If severe miscalibration + enough samples, intervene
        return calibration.severity == "severe" and calibration.sample_size >= 5
