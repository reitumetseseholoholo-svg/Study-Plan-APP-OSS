from dataclasses import dataclass, field
from typing import Any

from .cognitive_state import CognitiveState, CognitiveStateValidator
from .mastery_kernel import MasteryKernel
from .coach_fsm import SocraticFSM
from .contracts import (
    TutorPracticeItem,
    TutorAssessmentSubmission,
    TutorAssessmentResult,
    TutorSessionState,
    TutorLearnerProfileSnapshot,
    AppStateSnapshot,
)
from .services import DeterministicTutorPracticeService, DeterministicTutorAssessmentService
from .performance_monitor import PerformanceMonitor
from .logging_config import get_logger
from .learning_Science import (
    SpacedRetrievalSchedule,
    ElaborationQuestionSet,
    SessionReflection,
    TransferTaskGenerator,
    DesirableDifficultyCalibrator,
)
from .hint_system import HintBank, HintLevel
from .error_analysis import (
    MisconceptionLibrary,
    ErrorPatternDetector,
)
from .confidence_tracking import (
    ConfidenceCalibrator,
    ConfidenceThresholdPolicy,
)

logger = get_logger(__name__)


@dataclass
class PracticeLoopState:
    """Represents state during an active practice session."""

    cognitive_state: CognitiveState
    session_state: TutorSessionState
    learner_profile: TutorLearnerProfileSnapshot
    app_snapshot: AppStateSnapshot
    current_item: TutorPracticeItem | None = None
    current_result: TutorAssessmentResult | None = None
    
    # Tutor improvement tracking
    error_detector: ErrorPatternDetector = field(default_factory=ErrorPatternDetector)
    confidence_tracker: ConfidenceCalibrator = field(default_factory=ConfidenceCalibrator)
    current_hint_level: int = 0  # 0-4 for progressive hints


class PracticeLoopController:
    """Orchestrates practice loop flow: build → attempt → assess → update."""

    def __init__(self, perf_monitor: PerformanceMonitor | None = None, qgen_svc=None):
        self.perf_monitor = perf_monitor or PerformanceMonitor(enabled=False)
        self.practice_svc = DeterministicTutorPracticeService()
        self.assess_svc = DeterministicTutorAssessmentService()
        # question generation service (can be real or dummy)
        from .question_generator import get_qgen_service
        self.qgen_svc = qgen_svc or get_qgen_service()

    @staticmethod
    def _expected_answer_text(item: TutorPracticeItem) -> str:
        """Best-effort expected answer extraction across item schemas."""
        rubric_value = getattr(item, "rubric", None)
        if isinstance(rubric_value, str) and rubric_value.strip():
            return rubric_value.strip()
        meta = getattr(item, "meta", {})
        if isinstance(meta, dict):
            for key in ("expected_answer", "correct_option"):
                raw = meta.get(key)
                if isinstance(raw, str) and raw.strip():
                    return raw.strip()
            keywords = meta.get("keywords")
            if isinstance(keywords, (list, tuple)):
                joined = " ".join(str(v).strip() for v in keywords if str(v).strip())
                if joined:
                    return joined
        return ""

    def build_practice_items(self, loop_state: PracticeLoopState, max_items: int = 3) -> tuple[TutorPracticeItem, ...]:
        """Generate practice items for the session."""
        with self.perf_monitor.context("practice_item_build"):
            items = self.practice_svc.build_practice_items(
                session_state=loop_state.session_state,
                learner_profile=loop_state.learner_profile,
                app_snapshot=loop_state.app_snapshot,
                max_items=max_items,
            )
            logger.info(f"built {len(items)} practice items")
            return items

    def auto_generate_questions(
        self,
        topic: str,
        source_text: str | None = None,
        count: int = 5,
    ) -> list[str]:
        """Ask the secondary backend to auto‑produce questions.

        This uses whatever `QGenService` the controller has been configured
        with; by default it's a dummy templater but it can be injected in tests
        or swapped for a real LLM/RAG implementation.
        """
        logger.info("requesting auto-generated questions", extra={"topic": topic, "count": count})
        questions = self.qgen_svc.generate_questions(
            topic=topic,
            source_text=source_text,
            count=count,
        )
        logger.debug("questions generated", extra={"questions": questions})
        return questions

    def submit_attempt(
        self,
        loop_state: PracticeLoopState,
        item: TutorPracticeItem,
        submission: TutorAssessmentSubmission,
    ) -> TutorAssessmentResult:
        """Score a learner submission and update state."""
        with self.perf_monitor.context("assess"):
            result = self.assess_svc.assess(
                item=item,
                submission=submission,
                session_state=loop_state.session_state,
                learner_profile=loop_state.learner_profile,
            )
            logger.info(f"assessment result", extra={"outcome": result.outcome, "marks": result.marks_awarded})

            # Update cognitive state based on result
            with self.perf_monitor.context("posterior_update"):
                kernel = MasteryKernel(None, loop_state.cognitive_state)
                kernel.record_attempt(
                    chapter=item.topic,
                    question_id=item.item_id,
                    correct=result.outcome == "correct",
                    latency_ms=None,
                    hints_used=0,
                )

            loop_state.current_item = item
            loop_state.current_result = result
            return result

    def advance_state(self, loop_state: PracticeLoopState, event: str, metadata: dict[str, Any] | None = None) -> str:
        """Trigger FSM transition and return next Socratic state."""
        fsm = SocraticFSM(loop_state.cognitive_state)
        decision = fsm.transition(event, metadata)
        logger.info(f"fsm transition", extra={"event": event, "next_state": decision.state})
        return decision.state

    def validate_loop_invariants(self, loop_state: PracticeLoopState) -> tuple[bool, list[str]]:
        """Check that practice loop is in a consistent state."""
        with self.perf_monitor.context("state_validation"):
            valid, errors = CognitiveStateValidator.validate(loop_state.cognitive_state)
            if not valid:
                logger.error("invariant violation in practice loop", extra={"errors": errors})
            return (valid, errors)

    def calibrate_difficulty(self, loop_state: PracticeLoopState, latency_ms: float, confidence: int) -> str:
        """Use learning science to recommend difficulty (desirable difficulty principle)."""
        topic = loop_state.session_state.topic
        posterior = loop_state.cognitive_state.posteriors.get(topic)
        mastery = posterior.mean if posterior else 0.5
        error_streak = loop_state.cognitive_state.working_memory.struggle_flags.get("error_streak", False)
        
        recommendation = DesirableDifficultyCalibrator.recommend_difficulty(
            mastery=mastery,
            latency_ms=latency_ms,
            confidence=confidence,
            error_streak=error_streak,
        )
        explanation = DesirableDifficultyCalibrator.explain_calibration(
            current="medium", recommendation=recommendation
        )
        logger.info("difficulty calibrated", extra={"rec": recommendation, "reason": explanation})
        return recommendation

    def generate_elaboration_questions(self, item: TutorPracticeItem) -> dict[str, str]:
        """Generate deeper processing questions (elaboration principle)."""
        elab = ElaborationQuestionSet(
            topic=item.topic,
            base_concept=item.prompt[:30] if item.prompt else "concept",
        )
        logger.info("elaboration questions generated", extra={"topic": item.topic})
        return elab.questions

    def generate_transfer_task(self, item: TutorPracticeItem, domain: str = "real_world") -> str:
        """Create transfer task for far-transfer learning."""
        task = TransferTaskGenerator.generate_transfer_task(
            base_topic=item.topic,
            base_concept=item.prompt[:30] if item.prompt else "concept",
            domain=domain,
        )
        logger.info("transfer task generated", extra={"topic": item.topic, "domain": domain})
        return task

    def schedule_next_retest(self, loop_state: PracticeLoopState, item: TutorPracticeItem, result: TutorAssessmentResult) -> dict[str, Any]:
        """Schedule optimal retest using spaced retrieval (Ebbinghaus spacing)."""
        from datetime import datetime, timezone
        posterior = loop_state.cognitive_state.posteriors.get(item.topic)
        mastery = posterior.mean if posterior else 0.0
        
        # Mark last_correct only if correct/partial
        last_correct = datetime.now(timezone.utc).isoformat() if result.outcome in {"correct", "partial"} else None
        
        schedule = SpacedRetrievalSchedule(
            topic=item.topic,
            last_correct_date=last_correct,
            difficulty_level=result.next_difficulty,
            mastery_confidence=mastery,
        )
        
        next_days = schedule.next_retest_days
        logger.info("retest scheduled", extra={"topic": item.topic, "days_until": next_days})
        return {
            "topic": item.topic,
            "next_retest_days": next_days,
            "should_retest_now": schedule.should_retest_now(),
        }

    def generate_session_reflection(
        self,
        loop_state: PracticeLoopState,
        session_duration_minutes: int,
        attempts_history: list[tuple[str, bool]],  # (topic, correct)
    ) -> str:
        """End-of-session summary for metacognition (reflection principle)."""
        topics_covered = list(set(t for t, _ in attempts_history))
        correct_count = sum(1 for _, c in attempts_history if c)
        total_count = len(attempts_history)
        correct_rate = correct_count / max(1, total_count)
        
        # Identify mastery/struggling topics
        topics_mastered = [t for t in topics_covered if (loop_state.cognitive_state.posteriors.get(t) or type("", (), {"mean": 0})()).mean >= 0.8]
        topics_struggling = [t for t in topics_covered if (loop_state.cognitive_state.posteriors.get(t) or type("", (), {"mean": 0.5})()).mean < 0.4]
        
        reflection = SessionReflection(
            session_id=loop_state.session_state.session_id,
            topics_covered=topics_covered,
            topics_mastered=topics_mastered,
            topics_struggling=topics_struggling,
            confidence_calibration=0.0,  # TODO: compute from learner profile
            total_attempts=total_count,
            correct_rate=correct_rate,
            avg_latency_ms=25000,  # TODO: compute from history
            session_duration_minutes=session_duration_minutes,
        )
        
        feedback = reflection.generate_feedback()
        logger.info("session reflection generated", extra={"session": loop_state.session_state.session_id})
        return feedback

    # ==================== Tutor Improvements ====================

    def generate_progressive_hints(
        self,
        loop_state: PracticeLoopState,
        item: TutorPracticeItem,
        error_tags: tuple[str, ...] = (),
    ) -> list[HintLevel]:
        """
        Generate 5-level progressive hints using ZPD (Zone of Proximal Development).
        
        Args:
            loop_state: Current practice state
            item: Practice item
            error_tags: Error tags from previous attempt (if any)
        
        Returns:
            List of HintLevel objects [nudge, light, medium, heavy, solution]
        """
        bank = HintBank(
            topic=item.topic,
            concept=item.prompt[:50] if item.prompt else "concept",
            item_type=item.item_type or "short_answer",
            expected_answer=self._expected_answer_text(item),
            error_tags=error_tags,
        )
        hints = bank.generate_hints()
        logger.info("progressive hints generated", extra={"topic": item.topic, "count": len(hints)})
        return hints

    def get_next_hint(
        self,
        loop_state: PracticeLoopState,
        item: TutorPracticeItem,
        has_attempted: bool = False,
        error_tags: tuple[str, ...] = (),
    ) -> HintLevel:
        """
        Get the appropriate next hint level based on struggle state.
        
        Args:
            loop_state: Current practice state
            item: Practice item
            has_attempted: Did learner try again after last hint?
            error_tags: Errors from current attempt
        
        Returns:
            HintLevel to show learner
        """
        is_struggling = loop_state.cognitive_state.struggle_mode
        next_level = HintBank.recommend_next_level(
            current_level=loop_state.current_hint_level,
            has_attempted=has_attempted,
            is_struggling=is_struggling,
        )
        loop_state.current_hint_level = next_level
        
        bank = HintBank(
            topic=item.topic,
            concept=item.prompt[:50] if item.prompt else "concept",
            item_type=item.item_type or "short_answer",
            expected_answer=self._expected_answer_text(item),
            error_tags=error_tags,
        )
        hint = bank.get_hint(next_level)
        logger.info(
            "hint provided",
            extra={"topic": item.topic, "level": next_level, "struggling": is_struggling},
        )
        return hint

    def analyze_error_and_diagnose(
        self,
        loop_state: PracticeLoopState,
        result: TutorAssessmentResult,
        item: TutorPracticeItem,
    ) -> dict[str, Any]:
        """
        Diagnose error root cause (misconception vs careless mistake).
        
        Args:
            loop_state: Current practice state
            result: Assessment result with error_tags
            item: Practice item
        
        Returns:
            Dict with category, misconception, remediation advice
        """
        error_analysis = MisconceptionLibrary.diagnose_error(
            topic=item.topic,
            error_tags=result.error_tags,
            user_answer=result.feedback or "",
            expected_answer=self._expected_answer_text(item),
        )
        
        # Track error pattern
        loop_state.error_detector.add_error(error_analysis)
        pattern = loop_state.error_detector.detect_pattern()
        
        logger.info(
            "error diagnosed",
            extra={
                "topic": item.topic,
                "category": error_analysis.category.value,
                "pattern": pattern[0] if pattern else None,
            },
        )
        
        return {
            "category": error_analysis.category.value,
            "misconception": error_analysis.misconception.name if error_analysis.misconception else None,
            "remediation": error_analysis.remediation,
            "confidence": error_analysis.confidence,
            "pattern_detected": pattern is not None,
            "pattern_description": pattern[0] if pattern else None,
            "should_intervene": loop_state.error_detector.should_trigger_intervention(),
        }

    def track_confidence_and_calibrate(
        self,
        loop_state: PracticeLoopState,
        predicted_confidence: int,  # 1-5
        was_correct: bool,
        topic: str = "",
        concept: str = "",
    ) -> dict[str, Any]:
        """
        Track confidence prediction vs actual outcome for metacognitive awareness.
        
        Args:
            loop_state: Current practice state
            predicted_confidence: Learner's stated confidence (1-5)
            was_correct: Actual performance
            topic: Topic attempted
            concept: Concept name
        
        Returns:
            Dict with calibration metrics and feedback
        """
        loop_state.confidence_tracker.add_attempt(
            predicted_confidence=predicted_confidence,
            was_correct=was_correct,
            topic=topic,
            concept=concept,
        )
        
        calibration = loop_state.confidence_tracker.assess_calibration()
        feedback = loop_state.confidence_tracker.get_calibration_feedback()
        
        # Check if we should intervene with extra scaffolding
        should_scaffold = ConfidenceThresholdPolicy.should_provide_extra_scaffolding(
            confidence=predicted_confidence,
            recent_accuracy=calibration.actual_accuracy,
            confidence_matches_accuracy=(calibration.severity == "none"),
        )
        
        should_escalate = ConfidenceThresholdPolicy.should_escalate_difficulty(
            confidence=predicted_confidence,
            recent_accuracy=calibration.actual_accuracy,
            confidence_matches_accuracy=(calibration.severity == "none"),
        )
        
        logger.info(
            "confidence tracked",
            extra={
                "predicted": predicted_confidence,
                "actual_accuracy": f"{calibration.actual_accuracy*100:.0f}%",
                "calibration_error": f"{calibration.calibration_error*100:.0f}%",
                "severity": calibration.severity,
            },
        )
        
        return {
            "calibration_metrics": loop_state.confidence_tracker.get_summary_stats(),
            "calibration_feedback": feedback,
            "should_provide_extra_scaffolding": should_scaffold,
            "should_escalate_difficulty": should_escalate,
            "should_trigger_training": ConfidenceThresholdPolicy.should_trigger_metacognition_training(
                calibration
            ),
        }

    def recommend_next_action(
        self,
        loop_state: PracticeLoopState,
        item: TutorPracticeItem,
        result: TutorAssessmentResult,
        *,
        hints_used: int = 0,
    ) -> dict[str, Any]:
        """Produce explicit, learner-facing next action with reason."""
        outcome = str(getattr(result, "outcome", "") or "").strip().lower()
        topic = str(getattr(item, "topic", "") or "").strip()
        reason = "Continue building momentum."
        action = "Proceed to the next question."
        urgent = False

        if outcome == "incorrect":
            diagnosis = self.analyze_error_and_diagnose(loop_state, result, item)
            if bool(diagnosis.get("pattern_detected", False)):
                reason = str(diagnosis.get("pattern_description") or "Recurring misconception detected.")
            else:
                reason = str(diagnosis.get("remediation") or "Concept gap detected.")
            action = "Review remediation, then retry a similar question."
            urgent = True
        elif outcome == "partial":
            reason = "Method is close, but one or more rubric steps are missing."
            action = "Tighten your method steps and resubmit."
            urgent = True
        elif outcome == "correct":
            hint_penalty = 1.0 if int(hints_used or 0) == 0 else 0.3
            can_transfer = loop_state.cognitive_state.should_offer_transfer_test(
                structure_id=(topic or str(getattr(loop_state.session_state, "topic", "") or "unknown")),
                base_correct=True,
                hint_penalty=float(hint_penalty),
            )
            if can_transfer:
                reason = "Strong performance with low support; this is a good transfer check moment."
                action = "Attempt a transfer variant in a new context."
            else:
                reason = "Solid result recorded; reinforce with spaced retrieval."
                action = "Proceed and review this topic again on schedule."

        next_retest_days = None
        if outcome in {"correct", "partial"}:
            try:
                next_retest_days = int(self.schedule_next_retest(loop_state, item, result).get("next_retest_days", 0))
            except Exception:
                next_retest_days = None

        payload = {
            "outcome": outcome or "unknown",
            "topic": topic,
            "reason": reason,
            "next_action": action,
            "urgent": bool(urgent),
            "next_retest_days": next_retest_days,
        }
        logger.info("next action recommended", extra=payload)
        return payload
