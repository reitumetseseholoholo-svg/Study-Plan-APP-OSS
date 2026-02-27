"""
Learning Science Framework: High-ROI features for unprecedented learning acceleration.

Core principles implemented:
1. Spaced Retrieval: Optimal retest scheduling based on forgetting curve
2. Desirable Difficulty: Calibrate struggle to keep learner in flow zone
3. Elaboration: Generate follow-up questions requiring deeper processing
4. Transfer: Explicit far-transfer task generation & tracking
5. Metacognition: Confidence calibration feedback
6. Reflection: End-of-session learning summary
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta, timezone
from typing import Any

from .logging_config import get_logger

logger = get_logger(__name__)


class LearningPhase(str, Enum):
    """Cycle of learning phases per topic."""
    INITIAL_LEARNING = "initial"      # First encounter with concept
    RETRIEVAL_PRACTICE = "retrieval"  # Repeated retrieval at spaced intervals
    ELABORATION = "elaboration"       # Deeper processing via questions
    TRANSFER = "transfer"             # Apply in new context
    REFLECTION = "reflection"         # Consolidation & metacognition


@dataclass
class SpacedRetrievalSchedule:
    """Optimal retest timing based on forgetting curve (Ebbinghaus)."""
    
    topic: str
    last_correct_date: str | None      # ISO timestamp
    difficulty_level: str              # "easy", "medium", "hard"
    mastery_confidence: float          # [0, 1]
    
    @property
    def next_retest_days(self) -> int:
        """Days until optimal retest (2^n spacing)."""
        if not self.last_correct_date:
            return 1  # First practice: tomorrow
        
        try:
            last = datetime.fromisoformat(self.last_correct_date)
            now = datetime.now(timezone.utc)
            days_since = (now - last).days
        except Exception:
            return 1
        
        # Exponential spacing: 1, 2, 4, 8, 16 days...
        spacing = 1
        while spacing <= days_since:
            spacing *= 2
        return max(1, spacing)
    
    def should_retest_now(self) -> bool:
        """Check if retest is due or overdue."""
        if not self.last_correct_date:
            return True
        try:
            last = datetime.fromisoformat(self.last_correct_date)
            now = datetime.now(timezone.utc)
            days_since = (now - last).days
            return days_since >= self.next_retest_days
        except Exception:
            return False


@dataclass
class ElaborationQuestionSet:
    """Follow-up questions for deeper processing (Bloom's higher levels)."""
    
    topic: str
    base_concept: str
    
    # Questions designed for remembering → understanding → applying → analyzing → evaluating
    questions: dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.questions:
            self.questions = self._generate_default_questions()
    
    def _generate_default_questions(self) -> dict[str, str]:
        """Generate elaboration questions by Bloom's level."""
        return {
            "remember": f"Can you recall the definition of {self.base_concept}?",
            "understand": f"Explain in your own words why {self.base_concept} matters.",
            "apply": f"Give a real-world example where {self.base_concept} is used.",
            "analyze": f"Compare {self.base_concept} with a related concept; what's different?",
            "evaluate": f"When would using {self.base_concept} be a mistake? Why?",
        }


@dataclass
class SessionReflection:
    """End-of-session learning summary for metacognition."""
    
    session_id: str
    topics_covered: list[str]
    topics_mastered: list[str]      # >= 0.8 mastery
    topics_struggling: list[str]    # < 0.4 mastery
    confidence_calibration: float   # (predicted - actual) average
    total_attempts: int
    correct_rate: float             # [0, 1]
    avg_latency_ms: float
    session_duration_minutes: int
    
    def generate_feedback(self) -> str:
        """Generate encouraging, specific reflection."""
        lines = []
        
        lines.append(f"📊 Session Summary ({self.session_duration_minutes} min)")
        lines.append(f"✓ You got {int(self.correct_rate * 100)}% of {self.total_attempts} attempts.")
        
        if self.topics_mastered:
            lines.append(f"🎯 Mastered: {', '.join(self.topics_mastered[:3])}")
        
        if self.topics_struggling:
            lines.append(f"⚠️ Need more practice: {', '.join(self.topics_struggling[:3])}")
        
        # Metacognitive feedback
        if abs(self.confidence_calibration) > 0.3:
            if self.confidence_calibration > 0:
                lines.append("💡 You're more confident than your performance suggests - stay humble!")
            else:
                lines.append("💪 You're more capable than you think - keep going!")
        else:
            lines.append("🎯 Your confidence matches your performance - great self-awareness!")
        
        # Learning science reminder
        if self.correct_rate > 0.8:
            next_review = "in 3 days (spaced retrieval)"
        elif self.correct_rate > 0.5:
            next_review = "tomorrow (massed practice)"
        else:
            next_review = "ASAP (build foundations)"
        lines.append(f"📅 Recommended next session: {next_review}")
        
        return "\n".join(lines)


class TransferTaskGenerator:
    """Generate far-transfer tasks (apply concept in new domain)."""
    
    @staticmethod
    def generate_transfer_task(
        base_topic: str,
        base_concept: str,
        domain: str = "real_world",
    ) -> str:
        """Create a transfer task that requires applying concept in new context."""
        
        transfer_prompts = {
            "real_world": (
                f"You're advising a friend on their {base_topic} problem. "
                f"How would you apply {base_concept} to help them? "
                f"Explain step-by-step."
            ),
            "teaching": (
                f"Teach someone who's never heard of {base_concept} before. "
                f"Use an analogy they would understand. "
                f"(You're not allowed to use the technical term.)"
            ),
            "debugging": (
                f"A common mistake with {base_concept} is ___. "
                f"How would you help someone who made this mistake understand their error?"
            ),
            "prediction": (
                f"If {base_concept} didn't exist, what would change in {base_topic}? "
                f"Be specific about consequences."
            ),
        }
        
        return transfer_prompts.get(domain, transfer_prompts["real_world"])


class DesirableDifficultyCalibrator:
    """Adjust difficulty to keep learner in optimal struggle zone (Vygotsky's ZPD)."""
    
    @staticmethod
    def recommend_difficulty(
        mastery: float,        # [0, 1]
        latency_ms: float,    # response time
        confidence: int,      # [1, 5]
        error_streak: bool,   # multiple errors
    ) -> str:
        """Return "easy", "medium", or "hard" based on learning state."""
        
        # Too easy
        if mastery > 0.85 and latency_ms < 20000 and confidence >= 4:
            return "hard"
        
        # Too hard (cognitive overload)
        if latency_ms > 60000 or error_streak or confidence <= 1:
            return "easy"
        
        # Optimal struggle zone
        return "medium"
    
    @staticmethod
    def explain_calibration(current: str, recommendation: str) -> str:
        """Explain why difficulty is being adjusted."""
        if current == recommendation:
            return "You're in the right difficulty zone. Keep going!"
        elif recommendation == "hard":
            return "You're ready to step up. Let's tackle something harder."
        elif recommendation == "easy":
            return "This is getting tough. Let's strengthen foundations first."
        else:
            return "Let's find your learning sweet spot."
