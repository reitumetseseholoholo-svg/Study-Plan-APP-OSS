"""Error analysis and misconception-driven feedback.

Maps learner errors to root causes (misconceptions) and provides
targeted remediation feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .logging_config import get_logger


logger = get_logger(__name__)


class ErrorCategory(Enum):
    """Classify errors by root cause."""
    
    CONCEPTUAL = "conceptual"  # Misunderstands concept
    PROCEDURAL = "procedural"  # Wrong method/formula
    CARELESS = "careless"      # Arithmetic/spelling error
    INCOMPLETE = "incomplete"  # Missing steps
    MISREAD = "misread"        # Misunderstood question


@dataclass
class Misconception:
    """Root cause of repeated errors."""
    
    id: str
    name: str
    description: str  # What learner believes incorrectly
    correct_idea: str  # What they should believe
    examples: tuple[str, ...] = ()  # Common manifestations
    impact: str = "medium"  # "low" | "medium" | "high"


@dataclass
class ErrorAnalysis:
    """Diagnosis of a single error."""
    
    category: ErrorCategory
    misconception: Misconception | None = None
    confidence: float = 0.0  # [0, 1]
    remediation: str = ""  # What to do to learn


class MisconceptionLibrary:
    """Curated library of common misconceptions by topic."""
    
    # Finance/Accounting specific misconceptions
    MISCONCEPTIONS: dict[str, dict[str, Misconception]] = {
        "npv": {
            "ignores_time": Misconception(
                id="npv_ignores_time",
                name="NPV ignores the timing of cash flows",
                description="Learner thinks NPV is just sum of cash flows",
                correct_idea="NPV discounts future cash flows by the cost of capital",
                examples=(
                    "Adding cash flows without discounting",
                    "Using simple interest instead of compound discounting",
                    "Not adjusting for time period",
                ),
                impact="high",
            ),
            "wrong_discount_rate": Misconception(
                id="npv_wrong_rate",
                name="Wrong discount rate chosen",
                description="Uses arbitrary rate instead of cost of capital",
                correct_idea="Discount rate = cost of capital (risk-adjusted)",
                examples=(
                    "Using 10% instead of WACC",
                    "Using inflation rate instead of CoC",
                ),
                impact="high",
            ),
            "sign_error": Misconception(
                id="npv_sign_error",
                name="Cash flow sign errors",
                description="Outflows are positive or inflows are negative",
                correct_idea="Initial investment is negative, cash inflows are positive",
                examples=("All cash flows positive", "Reversed signs"),
                impact="medium",
            ),
        },
        "wacc": {
            "wrong_weights": Misconception(
                id="wacc_wrong_weights",
                name="Using book values instead of market values",
                description="Learner uses balance sheet values for weights",
                correct_idea="WACC uses market value weights (E/V and D/V)",
                examples=(
                    "Using net book value of debt",
                    "Using book value of equity",
                    "Not updating for market price changes",
                ),
                impact="high",
            ),
            "ignores_tax": Misconception(
                id="wacc_ignores_tax",
                name="Tax shield not applied to cost of debt",
                description="Uses pre-tax CoD instead of after-tax",
                correct_idea="WACC uses Kd(1-Tc) to account for tax deductibility",
                examples=(
                    "Forgetting the (1-Tc) term",
                    "Using gross interest rate",
                ),
                impact="high",
            ),
        },
        "working_capital": {
            "ignores_cycle": Misconception(
                id="wc_ignores_cycle",
                name="Doesn't understand operating cycle",
                description="Treats WC as static instead of cyclical",
                correct_idea="WC changes with sales growth due to receivables/inventory cycle",
                examples=(
                    "Not linking WC to Sales change",
                    "Treating WC investment as sunk cost",
                ),
                impact="high",
            ),
            "wrong_components": Misconception(
                id="wc_wrong_components",
                name="Includes non-operating items in WC",
                description="Includes cash, debt, or fixed assets",
                correct_idea="WC = (Receivables + Inventory) − Payables (excluding financing)",
                examples=(
                    "Including cash in WC calculation",
                    "Including short-term debt",
                ),
                impact="medium",
            ),
        },
    }
    
    @staticmethod
    def diagnose_error(
        topic: str,
        error_tags: tuple[str, ...],
        user_answer: str = "",
        expected_answer: str = "",
    ) -> ErrorAnalysis:
        """
        Diagnose root cause of an error.
        
        Args:
            topic: Topic area (e.g., "npv", "wacc")
            error_tags: Tags from assessment (e.g., "sign_error", "formula_error")
            user_answer: Learner's actual response
            expected_answer: What was expected
        
        Returns:
            ErrorAnalysis with category and misconception (if identified)
        """
        topic = str(topic or "").lower().strip()
        
        # Map error tags to misconceptions
        if "sign_error" in error_tags or (user_answer and expected_answer and
                                         _is_likely_sign_error(user_answer, expected_answer)):
            misconception = None
            if topic in MisconceptionLibrary.MISCONCEPTIONS:
                misconception = MisconceptionLibrary.MISCONCEPTIONS[topic].get("sign_error")
            return ErrorAnalysis(
                category=ErrorCategory.PROCEDURAL,
                misconception=misconception,
                confidence=0.85,
                remediation="Check the sign of each cash flow. Outflows −, inflows +.",
            )
        
        if "formula_error" in error_tags:
            misconception = None
            if topic in MisconceptionLibrary.MISCONCEPTIONS:
                # Choose first misconception in topic (usually the formula one)
                misconception = next(iter(MisconceptionLibrary.MISCONCEPTIONS[topic].values()), None)
            return ErrorAnalysis(
                category=ErrorCategory.PROCEDURAL,
                misconception=misconception,
                confidence=0.75,
                remediation="Revisit the formula. What are each of the components?",
            )
        
        if "precision_error" in error_tags or "rounding_error" in error_tags:
            return ErrorAnalysis(
                category=ErrorCategory.CARELESS,
                misconception=None,
                confidence=0.90,
                remediation="Check your rounding. Use consistent decimal places.",
            )
        
        if "incomplete" in error_tags:
            return ErrorAnalysis(
                category=ErrorCategory.INCOMPLETE,
                misconception=None,
                confidence=0.80,
                remediation="You're on the right track. Complete all steps. What comes next?",
            )
        
        # Default: conceptual gap
        return ErrorAnalysis(
            category=ErrorCategory.CONCEPTUAL,
            misconception=None,
            confidence=0.50,
            remediation=f"Let's review the concept of {topic} more carefully.",
        )
    
    @staticmethod
    def get_remediation_steps(misconception: Misconception) -> list[str]:
        """Steps to remediate a specific misconception."""
        return [
            f"Identify: What you believed was '{misconception.description}'",
            f"Understand: The correct idea is '{misconception.correct_idea}'",
            f"Practice: Try these examples to reinforce: {', '.join(misconception.examples[:2])}",
            f"Reflect: How does this change your understanding?",
        ]


def _is_likely_sign_error(user_answer: str, expected_answer: str) -> bool:
    """Check if user answer is numerically correct but opposite sign."""
    try:
        user_num = float(user_answer.strip())
        expected_num = float(expected_answer.strip())
        return abs(user_num + expected_num) < 0.01  # Near negatives
    except (ValueError, AttributeError):
        return False


class ErrorPatternDetector:
    """Detect patterns in repeated errors."""
    
    def __init__(self, history_limit: int = 10):
        """
        Initialize detector.
        
        Args:
            history_limit: How many recent errors to track
        """
        self.history_limit = history_limit
        self.error_history: list[ErrorAnalysis] = []
    
    def add_error(self, analysis: ErrorAnalysis) -> None:
        """Record an error."""
        self.error_history.append(analysis)
        if len(self.error_history) > self.history_limit:
            self.error_history.pop(0)
    
    def detect_pattern(self) -> tuple[str, float] | None:
        """
        Detect if same error repeats.
        
        Returns:
            (pattern_description, confidence) or None
        """
        if len(self.error_history) < 2:
            return None
        
        # Count errors by misconception
        misconception_counts: dict[str, int] = {}
        for error in self.error_history[-5:]:  # Last 5 errors
            if error.misconception:
                misconception_counts[error.misconception.id] = (
                    misconception_counts.get(error.misconception.id, 0) + 1
                )
        
        # If same misconception appears 3+ times in last 5, flag it
        for misc_id, count in misconception_counts.items():
            if count >= 3:
                confidence = min(0.95, 0.6 + (0.15 * count))
                return (f"Recurring: {misc_id}", confidence)
        
        # Count by category
        category_counts: dict[str, int] = {}
        for error in self.error_history[-5:]:
            cat = error.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        for cat, count in category_counts.items():
            if count >= 3:
                confidence = min(0.90, 0.5 + (0.15 * count))
                return (f"Pattern: {count} {cat} errors in last 5", confidence)
        
        return None
    
    def should_trigger_intervention(self) -> bool:
        """Should we intervene with extra scaffolding?"""
        pattern = self.detect_pattern()
        if pattern is None:
            return False
        
        _, confidence = pattern
        return confidence >= 0.70  # High confidence + recurring
