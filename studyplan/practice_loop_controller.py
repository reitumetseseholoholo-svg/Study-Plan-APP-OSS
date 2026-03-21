from dataclasses import dataclass, field
from typing import Any

from .cognitive_state import CognitiveState, CognitiveStateValidator
from .mastery_kernel import MasteryKernel
from .coach_fsm import SocraticFSM
from .practice_loop_fsm import recommend_action_policy
from .contracts import (
    TutorPracticeItem,
    TutorAssessmentSubmission,
    TutorAssessmentResult,
    TutorTurnResult,
    TutorSessionState,
    TutorLearnerProfileSnapshot,
    AppStateSnapshot,
)
from .services import (
    DeterministicTutorPracticeService,
    DeterministicTutorAssessmentService,
    TutorPracticeService,
    TutorAssessmentService,
)
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
RECOVERABLE_LOOP_ERRORS = (AttributeError, RuntimeError, TypeError, ValueError, KeyError)


@dataclass
class PracticeLoopSessionState:
    """In-memory bag for an active practice session (distinct from `PracticeLoopFsmState` in `practice_loop_fsm`)."""

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

    def __init__(
        self,
        perf_monitor: PerformanceMonitor | None = None,
        qgen_svc=None,
        assess_svc: TutorAssessmentService | None = None,
    ):
        self.perf_monitor = perf_monitor or PerformanceMonitor(enabled=False)
        self.practice_svc: TutorPracticeService = DeterministicTutorPracticeService()
        self.assess_svc: TutorAssessmentService = assess_svc or DeterministicTutorAssessmentService()
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

    @staticmethod
    def _coerce_str(value: Any, default: str = "") -> str:
        text = str(value or "").strip()
        return text if text else str(default or "")

    @staticmethod
    def _coerce_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return bool(default)
        return bool(value)

    @staticmethod
    def _coerce_int(
        value: Any,
        default: int = 0,
        *,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        try:
            out = int(value)
        except Exception:
            out = int(default)
        if min_value is not None and out < min_value:
            out = min_value
        if max_value is not None and out > max_value:
            out = max_value
        return out

    @staticmethod
    def _coerce_float(
        value: Any,
        default: float = 0.0,
        *,
        min_value: float | None = None,
        max_value: float | None = None,
    ) -> float:
        try:
            out = float(value)
        except Exception:
            out = float(default)
        if min_value is not None and out < min_value:
            out = min_value
        if max_value is not None and out > max_value:
            out = max_value
        return out

    @staticmethod
    def _normalize_practice_items(items: Any) -> tuple[TutorPracticeItem, ...]:
        if not isinstance(items, (list, tuple)):
            return ()
        normalized: list[TutorPracticeItem] = []
        for raw in items:
            if isinstance(raw, TutorPracticeItem):
                normalized.append(raw)
                continue
            if isinstance(raw, dict):
                normalized.append(TutorPracticeItem.from_dict(raw))
        return tuple(normalized)

    @staticmethod
    def _normalize_assessment_result(result: Any, *, fallback_item_id: str = "") -> TutorAssessmentResult:
        if isinstance(result, TutorAssessmentResult):
            payload = result.to_dict()
        elif isinstance(result, dict):
            payload = dict(result)
        else:
            payload = {
                "item_id": str(fallback_item_id or ""),
                "outcome": "incorrect",
                "marks_awarded": 0.0,
                "marks_max": 1.0,
                "feedback": "Assessment unavailable.",
                "error_tags": [],
                "misconception_tags": [],
                "retry_recommended": False,
                "next_difficulty": "same",
                "meta": {"fallback": True},
            }
        if not str(payload.get("item_id", "") or "").strip() and fallback_item_id:
            payload["item_id"] = str(fallback_item_id)
        return TutorAssessmentResult.from_dict(payload)

    @staticmethod
    def _normalize_hint(raw_hint: Any, *, default_level: int = 0) -> HintLevel:
        if isinstance(raw_hint, HintLevel):
            return HintLevel(
                level=PracticeLoopController._coerce_int(raw_hint.level, default_level, min_value=0, max_value=4),
                text=PracticeLoopController._coerce_str(raw_hint.text, "Think through the question step by step."),
                label=PracticeLoopController._coerce_str(raw_hint.label, "Hint"),
                context=PracticeLoopController._coerce_str(raw_hint.context, "fallback"),
            )
        if isinstance(raw_hint, dict):
            return HintLevel(
                level=PracticeLoopController._coerce_int(raw_hint.get("level"), default_level, min_value=0, max_value=4),
                text=PracticeLoopController._coerce_str(raw_hint.get("text"), "Think through the question step by step."),
                label=PracticeLoopController._coerce_str(raw_hint.get("label"), "Hint"),
                context=PracticeLoopController._coerce_str(raw_hint.get("context"), "fallback"),
            )
        return HintLevel(
            level=PracticeLoopController._coerce_int(default_level, 0, min_value=0, max_value=4),
            text="Think through the question step by step.",
            label="Hint",
            context="fallback",
        )

    @staticmethod
    def _normalize_tutor_turn_result(raw_result: Any) -> TutorTurnResult:
        fallback_text = (
            "Tutor response is temporarily unavailable. "
            "Proceed with a short checkpoint: state the concept, one rule, and one application."
        )
        payload: dict[str, Any]
        invalid_payload = False
        if isinstance(raw_result, TutorTurnResult):
            payload = {
                "text": raw_result.text,
                "model": raw_result.model,
                "latency_ms": raw_result.latency_ms,
                "error_code": raw_result.error_code,
                "telemetry": raw_result.telemetry,
            }
        elif isinstance(raw_result, dict):
            payload = dict(raw_result)
        else:
            payload = {}
            invalid_payload = True
        text = PracticeLoopController._coerce_str(payload.get("text"), fallback_text)
        model = PracticeLoopController._coerce_str(payload.get("model"), "unknown")
        latency_ms = PracticeLoopController._coerce_int(payload.get("latency_ms"), 0, min_value=0, max_value=600_000)
        default_error = "invalid_turn_payload" if invalid_payload else ""
        error_code = PracticeLoopController._coerce_str(payload.get("error_code"), default_error).lower()
        telemetry = payload.get("telemetry")
        if not isinstance(telemetry, dict):
            telemetry = {}
        return TutorTurnResult(
            text=text,
            model=model,
            latency_ms=latency_ms,
            error_code=error_code,
            telemetry=dict(telemetry),
        )

    @staticmethod
    def normalize_learner_help_feedback(value: Any) -> str:
        token = PracticeLoopController._coerce_str(value).lower()
        if token in {"clear", "cleared", "understood", "got it"}:
            return "clear"
        if token in {"partly", "partial", "partially", "almost"}:
            return "partly"
        if token in {"stuck", "still stuck", "confused", "lost", "not clear"}:
            return "stuck"
        return ""

    def build_tutor_feedback_adaptation(self, feedback: Any) -> dict[str, str]:
        signal = self.normalize_learner_help_feedback(feedback)
        if signal == "clear":
            return {
                "signal": "clear",
                "style_hint": "keep it concise, then raise difficulty with one harder check",
                "planner_hint": "Learner self-check: clear. Keep concise, then raise difficulty with one harder check.",
                "followup_prompt": "Give me one harder exam-style check on this topic. Don't show the solution until I answer.",
            }
        if signal == "partly":
            return {
                "signal": "partly",
                "style_hint": "re-explain with a simpler example, then ask one short check",
                "planner_hint": "Learner self-check: partly clear. Re-explain with a simpler example, then ask one short check.",
                "followup_prompt": "Re-explain this using a very simple example, then ask me one short check question.",
            }
        if signal == "stuck":
            return {
                "signal": "stuck",
                "style_hint": "slow down into tiny step-by-step chunks with quick confirmations",
                "planner_hint": "Learner self-check: still stuck. Slow down and break into tiny step-by-step chunks.",
                "followup_prompt": "Start from first principles and teach this in tiny step-by-step chunks, pausing after each step.",
            }
        return {"signal": "", "style_hint": "", "planner_hint": "", "followup_prompt": ""}

    def interpret_tutor_turn_for_loop(self, raw_turn_result: Any) -> dict[str, Any]:
        """Safely interpret model output into a bounded loop hint."""
        turn = self._normalize_tutor_turn_result(raw_turn_result)
        text_lower = self._coerce_str(turn.text).lower()
        if self._coerce_str(turn.error_code):
            decision_hint = "neutral_fallback"
        elif any(token in text_lower for token in ("retry", "hint", "scaffold", "checkpoint")):
            decision_hint = "support"
        elif any(token in text_lower for token in ("next question", "move on", "advance")):
            decision_hint = "advance"
        else:
            decision_hint = "neutral"
        return {
            "decision_hint": decision_hint,
            "text": turn.text,
            "model": turn.model,
            "latency_ms": int(turn.latency_ms),
            "error_code": self._coerce_str(turn.error_code),
            "has_error": bool(self._coerce_str(turn.error_code)),
            "telemetry": dict(turn.telemetry or {}),
        }

    def build_practice_items(self, loop_state: PracticeLoopSessionState, max_items: int = 3) -> tuple[TutorPracticeItem, ...]:
        """Generate practice items for the session."""
        safe_max_items = self._coerce_int(max_items, 3, min_value=1, max_value=20)
        with self.perf_monitor.context("practice_item_build"):
            try:
                raw_items = self.practice_svc.build_practice_items(
                    session_state=loop_state.session_state,
                    learner_profile=loop_state.learner_profile,
                    app_snapshot=loop_state.app_snapshot,
                    max_items=safe_max_items,
                )
            except RECOVERABLE_LOOP_ERRORS as exc:
                logger.warning(
                    "practice item build failed",
                    extra={
                        "error": str(exc),
                        "session": str(getattr(loop_state.session_state, "session_id", "") or ""),
                        "topic": str(getattr(loop_state.session_state, "topic", "") or ""),
                    },
                )
                return ()
            items = self._normalize_practice_items(raw_items)
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
        clean_topic = str(topic or "").strip()
        if not clean_topic:
            clean_topic = "General"

        try:
            requested_count = int(count)
        except (TypeError, ValueError):
            requested_count = 5
        requested_count = max(1, min(requested_count, 20))

        logger.info(
            "requesting auto-generated questions",
            extra={"topic": clean_topic, "count": requested_count},
        )
        try:
            raw_questions = self.qgen_svc.generate_questions(
                topic=clean_topic,
                source_text=source_text,
                count=requested_count,
            )
        except RECOVERABLE_LOOP_ERRORS as exc:
            logger.warning(
                "question generation backend failed, falling back to empty list",
                extra={"topic": clean_topic, "error": str(exc)},
            )
            return []

        if raw_questions is None:
            return []
        if not isinstance(raw_questions, (list, tuple)):
            logger.warning(
                "question generation backend returned invalid payload type",
                extra={"topic": clean_topic, "payload_type": type(raw_questions).__name__},
            )
            return []

        questions: list[str] = []
        for item in raw_questions:
            text = str(item or "").strip()
            if text:
                questions.append(text)
            if len(questions) >= requested_count:
                break
        logger.debug("questions generated", extra={"questions": questions})
        return questions

    def submit_attempt(
        self,
        loop_state: PracticeLoopSessionState,
        item: TutorPracticeItem,
        submission: TutorAssessmentSubmission,
    ) -> TutorAssessmentResult:
        """Score a learner submission and update state."""
        with self.perf_monitor.context("assess"):
            try:
                raw_result = self.assess_svc.assess(
                    item=item,
                    submission=submission,
                    session_state=loop_state.session_state,
                    learner_profile=loop_state.learner_profile,
                )
            except RECOVERABLE_LOOP_ERRORS as exc:
                logger.warning(
                    "assessment failed",
                    extra={
                        "error": str(exc),
                        "item_id": item.item_id,
                        "session": str(getattr(loop_state.session_state, "session_id", "") or ""),
                    },
                )
                raw_result = None
            result = self._normalize_assessment_result(raw_result, fallback_item_id=item.item_id)
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

    def advance_state(self, loop_state: PracticeLoopSessionState, event: str, metadata: dict[str, Any] | None = None) -> str:
        """Advance `SocraticFSM` (coach working-memory state); not `PracticeLoopFSM` table transitions."""
        fsm = SocraticFSM(loop_state.cognitive_state)
        try:
            decision = fsm.transition(event, metadata)
            next_state = self._coerce_str(getattr(decision, "state", ""), "DIAGNOSE")
        except RECOVERABLE_LOOP_ERRORS as exc:
            next_state = self._coerce_str(loop_state.cognitive_state.working_memory.socratic_state, "DIAGNOSE")
            logger.warning("fsm transition failed", extra={"event": event, "error": str(exc)})
        logger.info(f"fsm transition", extra={"event": event, "next_state": next_state})
        return next_state

    def validate_loop_invariants(self, loop_state: PracticeLoopSessionState) -> tuple[bool, list[str]]:
        """Check that practice loop is in a consistent state."""
        with self.perf_monitor.context("state_validation"):
            try:
                valid, errors = CognitiveStateValidator.validate(loop_state.cognitive_state)
            except RECOVERABLE_LOOP_ERRORS as exc:
                valid, errors = False, [f"validator_error:{str(exc)}"]
            normalized_errors = [self._coerce_str(e) for e in (errors or []) if self._coerce_str(e)]
            if not valid:
                logger.error("invariant violation in practice loop", extra={"errors": normalized_errors})
            return (self._coerce_bool(valid), normalized_errors)

    def calibrate_difficulty(self, loop_state: PracticeLoopSessionState, latency_ms: float, confidence: int) -> str:
        """Use learning science to recommend difficulty (desirable difficulty principle)."""
        topic = loop_state.session_state.topic
        posterior = loop_state.cognitive_state.posteriors.get(topic)
        mastery = posterior.mean if posterior else 0.5
        error_streak = loop_state.cognitive_state.working_memory.struggle_flags.get("error_streak", False)

        try:
            recommendation = DesirableDifficultyCalibrator.recommend_difficulty(
                mastery=mastery,
                latency_ms=latency_ms,
                confidence=confidence,
                error_streak=error_streak,
            )
        except Exception as exc:
            logger.warning("difficulty calibration failed", extra={"error": str(exc)})
            recommendation = "medium"
        rec = self._coerce_str(recommendation, "medium").lower()
        if rec not in {"easy", "medium", "hard", "easier", "same", "harder"}:
            rec = "medium"
        explanation = DesirableDifficultyCalibrator.explain_calibration(
            current="medium", recommendation=rec
        )
        logger.info("difficulty calibrated", extra={"rec": rec, "reason": explanation})
        return rec

    def generate_elaboration_questions(self, item: TutorPracticeItem) -> dict[str, str]:
        """Generate deeper processing questions (elaboration principle)."""
        try:
            elab = ElaborationQuestionSet(
                topic=item.topic,
                base_concept=item.prompt[:30] if item.prompt else "concept",
            )
            raw_questions = getattr(elab, "questions", {})
        except Exception as exc:
            logger.warning("elaboration question generation failed", extra={"topic": item.topic, "error": str(exc)})
            raw_questions = {}
        questions: dict[str, str] = {}
        if isinstance(raw_questions, dict):
            for key, value in raw_questions.items():
                k = self._coerce_str(key)
                v = self._coerce_str(value)
                if k and v:
                    questions[k] = v
        logger.info("elaboration questions generated", extra={"topic": item.topic})
        return questions

    def generate_transfer_task(self, item: TutorPracticeItem, domain: str = "real_world") -> str:
        """Create transfer task for far-transfer learning."""
        try:
            task = TransferTaskGenerator.generate_transfer_task(
                base_topic=item.topic,
                base_concept=item.prompt[:30] if item.prompt else "concept",
                domain=domain,
            )
        except Exception as exc:
            logger.warning("transfer task generation failed", extra={"topic": item.topic, "error": str(exc)})
            task = ""
        task = self._coerce_str(task, f"Apply {self._coerce_str(item.topic, 'this concept')} in a new scenario.")
        logger.info("transfer task generated", extra={"topic": item.topic, "domain": domain})
        return task

    def schedule_next_retest(self, loop_state: PracticeLoopSessionState, item: TutorPracticeItem, result: TutorAssessmentResult) -> dict[str, Any]:
        """Schedule optimal retest using spaced retrieval (Ebbinghaus spacing)."""
        from datetime import datetime, timezone
        posterior = loop_state.cognitive_state.posteriors.get(item.topic)
        mastery = posterior.mean if posterior else 0.0
        
        # Mark last_correct only if correct/partial
        last_correct = datetime.now(timezone.utc).isoformat() if result.outcome in {"correct", "partial"} else None
        
        try:
            schedule = SpacedRetrievalSchedule(
                topic=item.topic,
                last_correct_date=last_correct,
                difficulty_level=result.next_difficulty,
                mastery_confidence=mastery,
            )
            next_days = self._coerce_int(getattr(schedule, "next_retest_days", 1), 1, min_value=0)
            should_retest = self._coerce_bool(schedule.should_retest_now(), False)
        except Exception as exc:
            logger.warning("retest scheduling failed", extra={"topic": item.topic, "error": str(exc)})
            next_days = 1
            should_retest = False
        topic = self._coerce_str(item.topic)
        logger.info("retest scheduled", extra={"topic": topic, "days_until": next_days})
        return {
            "topic": topic,
            "next_retest_days": next_days,
            "should_retest_now": should_retest,
        }

    def generate_session_reflection(
        self,
        loop_state: PracticeLoopSessionState,
        session_duration_minutes: int,
        attempts_history: list[tuple[str, bool]],  # (topic, correct)
        latencies_ms: list[float] | None = None,
    ) -> str:
        """End-of-session summary for metacognition (reflection principle)."""
        safe_history = attempts_history if isinstance(attempts_history, list) else []
        topics_covered = list(set(self._coerce_str(t) for t, _ in safe_history if self._coerce_str(t)))
        correct_count = sum(1 for _, c in safe_history if c)
        total_count = len(safe_history)
        correct_rate = correct_count / max(1, total_count)
        
        # Identify mastery/struggling topics
        topics_mastered = [
            t
            for t in topics_covered
            if self._coerce_float(
                getattr(loop_state.cognitive_state.posteriors.get(t), "mean", 0.0),
                0.0,
                min_value=0.0,
                max_value=1.0,
            )
            >= 0.8
        ]
        topics_struggling = [
            t
            for t in topics_covered
            if self._coerce_float(
                getattr(loop_state.cognitive_state.posteriors.get(t), "mean", 0.5),
                0.5,
                min_value=0.0,
                max_value=1.0,
            )
            < 0.4
        ]
        
        # Confidence calibration: signed (predicted - actual) from session tracker
        cal = loop_state.confidence_tracker.assess_calibration()
        if cal.sample_size >= 3:
            confidence_calibration = cal.predicted_confidence - cal.actual_accuracy
        else:
            confidence_calibration = getattr(
                loop_state.learner_profile, "confidence_calibration_bias", 0.0
            )
        
        # Average latency: from history when provided, else default
        if latencies_ms and len(latencies_ms) > 0:
            avg_latency_ms = sum(latencies_ms) / len(latencies_ms)
            avg_latency_ms = max(1000.0, min(120_000.0, avg_latency_ms))
        else:
            avg_latency_ms = 25000.0
        
        try:
            reflection = SessionReflection(
                session_id=loop_state.session_state.session_id,
                topics_covered=topics_covered,
                topics_mastered=topics_mastered,
                topics_struggling=topics_struggling,
                confidence_calibration=confidence_calibration,
                total_attempts=total_count,
                correct_rate=correct_rate,
                avg_latency_ms=avg_latency_ms,
                session_duration_minutes=session_duration_minutes,
            )
            feedback = reflection.generate_feedback()
        except Exception as exc:
            logger.warning("session reflection generation failed", extra={"session": loop_state.session_state.session_id, "error": str(exc)})
            feedback = ""
        feedback = self._coerce_str(feedback, "Session complete. Review the key mistakes and retry one similar question.")
        logger.info("session reflection generated", extra={"session": loop_state.session_state.session_id})
        return feedback

    def build_session_quality_summary(
        self,
        loop_state: PracticeLoopSessionState,
        *,
        result: TutorAssessmentResult | None = None,
        guidance: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        stats_raw = loop_state.confidence_tracker.get_summary_stats()
        stats = stats_raw if isinstance(stats_raw, dict) else {}
        attempts = self._coerce_int(stats.get("sample_size"), 0, min_value=0, max_value=10_000)
        accuracy = self._coerce_float(stats.get("actual_accuracy"), 0.0, min_value=0.0, max_value=1.0)
        current_outcome = self._coerce_str(getattr(result, "outcome", "") if result is not None else "").lower()

        if attempts > 0:
            progress = f"Progress: {attempts} checked attempt(s), accuracy {accuracy*100:.0f}%."
        elif current_outcome == "correct":
            progress = "Progress: latest checked attempt is correct."
        elif current_outcome == "partial":
            progress = "Progress: latest checked attempt is partial."
        elif current_outcome == "incorrect":
            progress = "Progress: latest checked attempt is incorrect."
        else:
            progress = "Progress: submit a checked attempt to start tracking."

        weak_tokens: list[str] = []
        if result is not None:
            weak_tokens.extend(
                [
                    self._coerce_str(x)
                    for x in list(getattr(result, "error_tags", ()) or ())
                    if self._coerce_str(x)
                ]
            )
            weak_tokens.extend(
                [
                    self._coerce_str(x)
                    for x in list(getattr(result, "misconception_tags", ()) or ())
                    if self._coerce_str(x)
                ]
            )
        if not weak_tokens and current_outcome in {"partial", "incorrect"}:
            topic = self._coerce_str(getattr(loop_state.current_item, "topic", "") or loop_state.session_state.topic)
            if topic:
                weak_tokens.append(topic)
        weak_tokens = list(dict.fromkeys(weak_tokens))
        weak_spots = (
            f"Weak spots: {', '.join(weak_tokens[:3])}."
            if weak_tokens
            else "Weak spots: none flagged in this check."
        )

        next_action = ""
        if isinstance(guidance, dict):
            next_action = self._coerce_str(guidance.get("next_action"))
        if not next_action:
            if current_outcome == "correct":
                next_action = "Take one transfer check question."
            elif current_outcome == "partial":
                next_action = "Fix the weak step, then resubmit."
            elif current_outcome == "incorrect":
                next_action = "Review remediation, then retry a similar question."
            else:
                next_action = "Run one checked practice attempt."
        next_best_step = f"Next best step: {next_action}"
        if not next_best_step.endswith("."):
            next_best_step += "."
        return {
            "progress": progress,
            "weak_spots": weak_spots,
            "next_best_step": next_best_step,
        }

    # ==================== Tutor Improvements ====================

    def generate_progressive_hints(
        self,
        loop_state: PracticeLoopSessionState,
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
        try:
            hints = bank.generate_hints()
        except Exception as exc:
            logger.warning("progressive hint generation failed", extra={"topic": item.topic, "error": str(exc)})
            hints = []
        normalized_hints = [self._normalize_hint(h, default_level=i) for i, h in enumerate(hints)]
        if not normalized_hints:
            normalized_hints = [self._normalize_hint(None, default_level=0)]
        logger.info("progressive hints generated", extra={"topic": item.topic, "count": len(hints)})
        return normalized_hints

    def get_next_hint(
        self,
        loop_state: PracticeLoopSessionState,
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
        next_level = self._coerce_int(
            HintBank.recommend_next_level(
                current_level=loop_state.current_hint_level,
                has_attempted=has_attempted,
                is_struggling=is_struggling,
            ),
            loop_state.current_hint_level,
            min_value=0,
            max_value=4,
        )
        loop_state.current_hint_level = next_level
        
        bank = HintBank(
            topic=item.topic,
            concept=item.prompt[:50] if item.prompt else "concept",
            item_type=item.item_type or "short_answer",
            expected_answer=self._expected_answer_text(item),
            error_tags=error_tags,
        )
        try:
            hint = bank.get_hint(next_level)
        except Exception as exc:
            logger.warning("next hint generation failed", extra={"topic": item.topic, "level": next_level, "error": str(exc)})
            hint = None
        normalized_hint = self._normalize_hint(hint, default_level=next_level)
        logger.info(
            "hint provided",
            extra={"topic": item.topic, "level": next_level, "struggling": is_struggling},
        )
        return normalized_hint

    def analyze_error_and_diagnose(
        self,
        loop_state: PracticeLoopSessionState,
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
        try:
            error_analysis = MisconceptionLibrary.diagnose_error(
                topic=item.topic,
                error_tags=result.error_tags,
                user_answer=result.feedback or "",
                expected_answer=self._expected_answer_text(item),
            )
        except Exception as exc:
            logger.warning("error diagnosis failed", extra={"topic": item.topic, "error": str(exc)})
            error_analysis = MisconceptionLibrary.diagnose_error(
                topic="",
                error_tags=(),
                user_answer="",
                expected_answer="",
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
            "category": self._coerce_str(getattr(error_analysis.category, "value", None), "unknown"),
            "misconception": self._coerce_str(error_analysis.misconception.name, "") if error_analysis.misconception else None,
            "remediation": self._coerce_str(error_analysis.remediation, "Concept gap detected."),
            "confidence": self._coerce_float(error_analysis.confidence, 0.0, min_value=0.0, max_value=1.0),
            "pattern_detected": self._coerce_bool(pattern is not None),
            "pattern_description": self._coerce_str(pattern[0], "") if pattern else None,
            "should_intervene": self._coerce_bool(loop_state.error_detector.should_trigger_intervention()),
        }

    def track_confidence_and_calibrate(
        self,
        loop_state: PracticeLoopSessionState,
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
        
        stats = loop_state.confidence_tracker.get_summary_stats()
        if not isinstance(stats, dict):
            stats = {}
        return {
            "calibration_metrics": stats,
            "calibration_feedback": self._coerce_str(feedback, "Keep practicing to calibrate confidence."),
            "should_provide_extra_scaffolding": self._coerce_bool(should_scaffold),
            "should_escalate_difficulty": self._coerce_bool(should_escalate),
            "should_trigger_training": self._coerce_bool(
                ConfidenceThresholdPolicy.should_trigger_metacognition_training(calibration)
            ),
        }

    def recommend_next_action(
        self,
        loop_state: PracticeLoopSessionState,
        item: TutorPracticeItem,
        result: TutorAssessmentResult,
        *,
        hints_used: int = 0,
        tutor_turn_result: Any | None = None,
    ) -> dict[str, Any]:
        """Produce explicit, learner-facing next action with reason."""
        outcome = str(getattr(result, "outcome", "") or "").strip().lower()
        topic = str(getattr(item, "topic", "") or "").strip()
        diagnosis: dict[str, Any] = {}
        can_transfer = False

        if outcome == "incorrect":
            diagnosis = self.analyze_error_and_diagnose(loop_state, result, item)
        elif outcome == "correct":
            hint_penalty = 1.0 if int(hints_used or 0) == 0 else 0.3
            can_transfer = bool(loop_state.cognitive_state.should_offer_transfer_test(
                structure_id=(topic or str(getattr(loop_state.session_state, "topic", "") or "unknown")),
                base_correct=True,
                hint_penalty=float(hint_penalty),
            ))

        decision = recommend_action_policy(
            outcome=outcome,
            can_transfer=can_transfer,
            pattern_detected=bool(diagnosis.get("pattern_detected", False)),
            pattern_description=str(diagnosis.get("pattern_description") or ""),
            remediation=str(diagnosis.get("remediation") or ""),
        )

        next_retest_days = None
        if outcome in {"correct", "partial"}:
            try:
                next_retest_days = int(self.schedule_next_retest(loop_state, item, result).get("next_retest_days", 0))
            except Exception:
                next_retest_days = None

        confidence_delta = None
        try:
            calibration = loop_state.confidence_tracker.assess_calibration()
            if int(getattr(calibration, "sample_size", 0)) >= 3:
                confidence_delta = round(
                    float(getattr(calibration, "predicted_confidence", 0.0))
                    - float(getattr(calibration, "actual_accuracy", 0.0)),
                    3,
                )
        except Exception:
            confidence_delta = None

        intervention_level = loop_state.cognitive_state.recommend_intervention_level(
            outcome=outcome,
            hints_used=hints_used,
            pattern_detected=bool(diagnosis.get("pattern_detected", False)),
            confidence_delta=confidence_delta,
        )

        reason = decision.reason
        next_action = decision.next_action
        urgent = bool(decision.urgent)
        if intervention_level == "light":
            urgent = True
            reason = f"Targeted intervention advised. {reason}"
            if outcome == "correct":
                next_action = "Do one guided checkpoint question, then proceed to the next question."
            elif outcome == "partial":
                next_action = "Apply one targeted hint, then tighten your method steps and resubmit."
        elif intervention_level == "strong":
            urgent = True
            reason = f"Immediate intervention required. {reason}"
            if outcome == "incorrect":
                next_action = "Review remediation, use progressive hints, then retry a similar question."
            else:
                next_action = "Pause progression, run remediation on the weak step, then retry."

        telemetry = {
            "decision_source": "practice_loop_fsm.recommend_action_policy.v1",
            "inputs": {
                "outcome": outcome or "unknown",
                "hints_used": int(hints_used or 0),
                "can_transfer": bool(can_transfer),
                "topic": topic,
            },
            "signals": {
                "intervention_level": intervention_level,
                "pattern_detected": bool(diagnosis.get("pattern_detected", False)),
                "diagnosis_used": outcome == "incorrect",
                "confidence_delta": confidence_delta,
            },
        }
        model_signal = self.interpret_tutor_turn_for_loop(tutor_turn_result)
        model_runtime = model_signal.get("telemetry")
        if not isinstance(model_runtime, dict):
            model_runtime = {}
        telemetry["model_signal"] = {
            "decision_hint": self._coerce_str(model_signal.get("decision_hint"), "neutral"),
            "has_error": self._coerce_bool(model_signal.get("has_error"), False),
            "error_code": self._coerce_str(model_signal.get("error_code"), ""),
            "provider": self._coerce_str(model_runtime.get("provider"), "unknown"),
            "latency_ms": self._coerce_int(
                model_runtime.get("latency_ms", model_signal.get("latency_ms")),
                0,
                min_value=0,
            ),
            "retry_count": self._coerce_int(model_runtime.get("retry_count"), 0, min_value=0, max_value=10),
            "fallback_used": self._coerce_bool(
                model_runtime.get("fallback_used"),
                self._coerce_bool(model_signal.get("has_error"), False),
            ),
            "model": self._coerce_str(model_signal.get("model"), "unknown"),
        }
        payload = {
            "outcome": outcome or "unknown",
            "topic": self._coerce_str(topic),
            "reason": self._coerce_str(reason, "Continue building momentum."),
            "next_action": self._coerce_str(next_action, "Proceed to the next question."),
            "urgent": self._coerce_bool(urgent),
            "next_retest_days": next_retest_days,
            "telemetry": telemetry if isinstance(telemetry, dict) else {},
        }
        logger.info("next action recommended", extra=payload)
        return payload
