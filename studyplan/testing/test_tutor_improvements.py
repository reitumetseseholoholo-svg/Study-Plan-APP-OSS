"""Tests for hint system, error analysis, and confidence tracking."""

import pytest
import studyplan.practice_loop_controller as plc
from typing import Any, cast

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
from studyplan.practice_loop_controller import PracticeLoopController, PracticeLoopState
from studyplan.cognitive_state import CognitiveState
from studyplan.contracts import (
    TutorPracticeItem,
    TutorAssessmentSubmission,
    TutorAssessmentResult,
    TutorSessionState,
    TutorLearnerProfileSnapshot,
    AppStateSnapshot,
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

        maybe_pattern = detector.detect_pattern()
        assert maybe_pattern is not None
        pattern, conf = maybe_pattern
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

        maybe_pattern = detector.detect_pattern()
        assert maybe_pattern is not None
        pattern, conf = maybe_pattern
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


def _build_controller_loop_item(topic: str = "npv"):
    controller = PracticeLoopController()
    loop = PracticeLoopState(
        cognitive_state=CognitiveState(),
        session_state=TutorSessionState(session_id="reg1", module="m", topic=topic),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u-reg", module="m"),
        app_snapshot=AppStateSnapshot(
            module="m",
            current_topic=topic,
            coach_pick="",
            days_to_exam=None,
            must_review_due=0,
            overdue_srs_count=0,
        ),
    )
    item = TutorPracticeItem(
        item_id="q-reg-1",
        item_type="short_answer",
        prompt="Explain the sign convention in NPV.",
        topic=topic,
    )
    return controller, loop, item


def test_controller_recommend_next_action_recurring_misconception_escalates():
    controller, loop, item = _build_controller_loop_item("npv")
    bad = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="incorrect",
        marks_awarded=0.0,
        marks_max=2.0,
        feedback="Wrong sign again",
        error_tags=("sign_error",),
    )

    # Build repeated misconception pattern over multiple incorrect attempts.
    for _ in range(2):
        controller.recommend_next_action(loop, item, bad, hints_used=1)
    guidance = controller.recommend_next_action(loop, item, bad, hints_used=1)

    assert guidance["outcome"] == "incorrect"
    assert guidance["urgent"] is True
    assert guidance["telemetry"]["signals"]["pattern_detected"] is True
    assert "Recurring" in guidance["reason"]


def test_controller_recommend_next_action_overconfidence_incorrect_is_strong():
    controller, loop, item = _build_controller_loop_item("wacc")

    # Seed clear overconfidence (high predicted confidence + low accuracy).
    for _ in range(4):
        loop.confidence_tracker.add_attempt(predicted_confidence=5, was_correct=False, topic="wacc")

    bad = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="incorrect",
        marks_awarded=0.0,
        marks_max=2.0,
        feedback="Incorrect answer",
        error_tags=("formula_error",),
    )
    guidance = controller.recommend_next_action(loop, item, bad, hints_used=1)

    assert guidance["telemetry"]["signals"]["intervention_level"] == "strong"
    assert guidance["telemetry"]["signals"]["confidence_delta"] is not None
    assert guidance["telemetry"]["signals"]["confidence_delta"] >= 0.25
    assert guidance["reason"].startswith("Immediate intervention required.")


def test_controller_recommend_next_action_correct_low_support_progresses():
    controller, loop, item = _build_controller_loop_item("T1")

    # Set strong mastery so transfer progression is allowed for correct low-support attempt.
    posterior = loop.cognitive_state.get_structure_posterior(item.topic)
    posterior.alpha = 9.0
    posterior.beta = 2.0

    good = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="correct",
        marks_awarded=2.0,
        marks_max=2.0,
        feedback="Strong answer",
    )
    guidance = controller.recommend_next_action(loop, item, good, hints_used=0)

    assert guidance["outcome"] == "correct"
    assert guidance["urgent"] is False
    assert guidance["telemetry"]["inputs"]["can_transfer"] is True
    assert guidance["telemetry"]["signals"]["intervention_level"] == "none"
    assert "transfer" in guidance["next_action"].lower()


def test_controller_recommend_next_action_payload_shape_for_unknown_outcome():
    controller, loop, item = _build_controller_loop_item("npv")
    odd = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="mystery",
        marks_awarded=0.0,
        marks_max=2.0,
        feedback="unclassified",
    )
    guidance = controller.recommend_next_action(loop, item, odd, hints_used=2)

    required = {
        "outcome",
        "topic",
        "reason",
        "next_action",
        "urgent",
        "next_retest_days",
        "telemetry",
    }
    assert required.issubset(set(guidance.keys()))
    assert guidance["outcome"] == "mystery"
    assert isinstance(guidance["topic"], str)
    assert isinstance(guidance["reason"], str) and guidance["reason"]
    assert isinstance(guidance["next_action"], str) and guidance["next_action"]
    assert isinstance(guidance["urgent"], bool)
    assert guidance["next_retest_days"] is None

    telemetry = guidance["telemetry"]
    assert isinstance(telemetry, dict)
    assert isinstance(telemetry.get("decision_source"), str) and telemetry["decision_source"]

    inputs = telemetry.get("inputs")
    assert isinstance(inputs, dict)
    assert inputs.get("outcome") == "mystery"
    assert isinstance(inputs.get("hints_used"), int)
    assert isinstance(inputs.get("can_transfer"), bool)
    assert isinstance(inputs.get("topic"), str)

    signals = telemetry.get("signals")
    assert isinstance(signals, dict)
    assert signals.get("intervention_level") in {"none", "light", "strong"}
    assert isinstance(signals.get("pattern_detected"), bool)
    assert isinstance(signals.get("diagnosis_used"), bool)
    assert signals.get("confidence_delta") is None or isinstance(signals.get("confidence_delta"), float)


def test_build_practice_items_invalid_service_payload_returns_empty_tuple():
    controller, loop, _ = _build_controller_loop_item("npv")

    class BadPracticeService:
        def build_practice_items(self, **kwargs):
            return {"not": "a-list"}

    controller.practice_svc = cast(Any, BadPracticeService())
    items = controller.build_practice_items(loop, max_items=cast(Any, "bad"))
    assert items == ()


def test_submit_attempt_invalid_service_payload_returns_safe_result():
    controller, loop, item = _build_controller_loop_item("npv")

    class BadAssessService:
        def assess(self, **kwargs):
            return "invalid-result"

    controller.assess_svc = cast(Any, BadAssessService())
    result = controller.submit_attempt(
        loop,
        item,
        TutorAssessmentSubmission(item_id=item.item_id, answer_text="anything"),
    )
    assert isinstance(result, TutorAssessmentResult)
    assert result.item_id == item.item_id
    assert str(result.outcome) == "incorrect"


def test_advance_state_transition_error_returns_safe_fallback(monkeypatch):
    controller, loop, _ = _build_controller_loop_item("npv")
    loop.cognitive_state.working_memory.socratic_state = "TEACH"

    class ExplodingFSM:
        def __init__(self, *args, **kwargs):
            pass

        def transition(self, event, metadata):
            raise RuntimeError("boom")

    monkeypatch.setattr(plc, "SocraticFSM", ExplodingFSM)
    next_state = controller.advance_state(loop, "ANY_EVENT", {})
    assert next_state == "TEACH"


def test_generate_elaboration_questions_invalid_payload_returns_clean_dict(monkeypatch):
    controller, _, item = _build_controller_loop_item("npv")

    class BadElaborationSet:
        def __init__(self, *args, **kwargs):
            self.questions = "invalid"

    monkeypatch.setattr(plc, "ElaborationQuestionSet", BadElaborationSet)
    out = controller.generate_elaboration_questions(item)
    assert out == {}


def test_interpret_tutor_turn_for_loop_malformed_payload_is_safe():
    controller, _, _ = _build_controller_loop_item("npv")
    parsed = controller.interpret_tutor_turn_for_loop(None)
    assert parsed["decision_hint"] == "neutral_fallback"
    assert parsed["has_error"] is True
    assert isinstance(parsed["text"], str) and parsed["text"]
    assert parsed["model"] == "unknown"


def test_interpret_tutor_turn_for_loop_error_payload_maps_to_neutral_fallback():
    controller, _, _ = _build_controller_loop_item("npv")
    parsed = controller.interpret_tutor_turn_for_loop(
        {"text": "", "model": "llama-test", "latency_ms": 15, "error_code": "timeout", "telemetry": {"a": 1}}
    )
    assert parsed["decision_hint"] == "neutral_fallback"
    assert parsed["has_error"] is True
    assert parsed["error_code"] == "timeout"


def test_recommend_next_action_with_malformed_tutor_turn_result_keeps_contract():
    controller, loop, item = _build_controller_loop_item("npv")
    good = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="correct",
        marks_awarded=2.0,
        marks_max=2.0,
        feedback="Strong answer",
    )
    guidance = controller.recommend_next_action(
        loop,
        item,
        good,
        hints_used=0,
        tutor_turn_result={"text": None, "model": None, "latency_ms": "bad", "error_code": 404, "telemetry": "bad"},
    )
    assert isinstance(guidance["reason"], str) and guidance["reason"]
    assert isinstance(guidance["next_action"], str) and guidance["next_action"]
    assert guidance["telemetry"]["model_signal"]["decision_hint"] in {
        "neutral",
        "support",
        "advance",
        "neutral_fallback",
    }
    assert isinstance(guidance["telemetry"]["model_signal"]["has_error"], bool)
    assert guidance["telemetry"]["model_signal"]["provider"] == "unknown"
    assert isinstance(guidance["telemetry"]["model_signal"]["latency_ms"], int)
    assert isinstance(guidance["telemetry"]["model_signal"]["retry_count"], int)
    assert isinstance(guidance["telemetry"]["model_signal"]["fallback_used"], bool)


def test_recommend_next_action_model_signal_carries_llama_stability_fields():
    controller, loop, item = _build_controller_loop_item("npv")
    good = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="correct",
        marks_awarded=2.0,
        marks_max=2.0,
        feedback="Strong answer",
    )
    guidance = controller.recommend_next_action(
        loop,
        item,
        good,
        hints_used=0,
        tutor_turn_result={
            "text": "Proceed to the next question.",
            "model": "llama-test",
            "latency_ms": 321,
            "error_code": "",
            "telemetry": {
                "provider": "llama.cpp",
                "latency_ms": 321,
                "retry_count": 1,
                "fallback_used": False,
                "error_code": "",
            },
        },
    )
    model_signal = guidance["telemetry"]["model_signal"]
    assert model_signal["provider"] == "llama.cpp"
    assert model_signal["latency_ms"] == 321
    assert model_signal["retry_count"] == 1
    assert model_signal["fallback_used"] is False
    assert model_signal["error_code"] == ""


def test_regression_partial_path_escalates_to_strong_when_struggling():
    controller, loop, item = _build_controller_loop_item("npv")
    loop.cognitive_state.struggle_mode = True
    partial = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="partial",
        marks_awarded=1.0,
        marks_max=2.0,
        feedback="Almost there",
    )
    guidance = controller.recommend_next_action(loop, item, partial, hints_used=3)
    assert guidance["outcome"] == "partial"
    assert guidance["urgent"] is True
    assert guidance["telemetry"]["signals"]["intervention_level"] == "strong"
    assert guidance["reason"].startswith("Immediate intervention required.")


def test_regression_unknown_outcome_none_is_normalized_to_unknown():
    controller, loop, item = _build_controller_loop_item("npv")
    weird = TutorAssessmentResult(
        item_id=item.item_id,
        outcome=None,  # type: ignore[arg-type]
        marks_awarded=0.0,
        marks_max=2.0,
        feedback="",
    )
    guidance = controller.recommend_next_action(loop, item, weird, hints_used=0)
    assert guidance["outcome"] == "unknown"
    assert guidance["urgent"] is False
    assert guidance["telemetry"]["inputs"]["outcome"] == "unknown"


def test_acceptance_learner_flow_feedback_tap_adapts_next_answer_and_session_summary():
    controller, loop, item = _build_controller_loop_item("npv")

    # Start session + ask + get answer.
    assert loop.session_state.session_id == "reg1"
    learner_question = "Why is the initial investment negative in NPV?"
    tutor_answer = "The initial investment is a cash outflow at time 0, so it is negative."
    assert learner_question and tutor_answer

    # Feedback tap -> next answer adapts.
    adaptation = controller.build_tutor_feedback_adaptation("Still stuck")
    assert adaptation["signal"] == "stuck"
    assert "step-by-step" in adaptation["style_hint"].lower()
    assert "still stuck" in adaptation["planner_hint"].lower()

    # End-of-turn summary is plain: progress, weak spots, next best step (one line each).
    bad = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="incorrect",
        marks_awarded=0.0,
        marks_max=2.0,
        feedback="Sign convention is wrong",
        error_tags=("sign_error",),
    )
    controller.track_confidence_and_calibrate(loop, predicted_confidence=4, was_correct=False, topic="npv")
    guidance = controller.recommend_next_action(loop, item, bad, hints_used=1)
    summary = controller.build_session_quality_summary(loop, result=bad, guidance=guidance)
    assert summary["progress"].startswith("Progress:")
    assert summary["weak_spots"].startswith("Weak spots:")
    assert "sign_error" in summary["weak_spots"]
    assert summary["next_best_step"].startswith("Next best step:")
    assert "\n" not in summary["progress"]
    assert "\n" not in summary["weak_spots"]
    assert "\n" not in summary["next_best_step"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
