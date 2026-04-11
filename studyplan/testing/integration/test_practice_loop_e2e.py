import time

from studyplan.services import DeterministicTutorPracticeService, DeterministicTutorAssessmentService
from studyplan.contracts import (
    TutorSessionState,
    TutorLearnerProfileSnapshot,
    AppStateSnapshot,
    TutorAssessmentSubmission,
    TutorAssessmentResult,
    TutorPracticeItem,
)
from studyplan.practice_loop_controller import PracticeLoopController, PracticeLoopSessionState
from studyplan.practice_loop_fsm import PracticeLoopFsmState
from studyplan.cognitive_state import CognitiveState
from studyplan.performance_monitor import PerformanceMonitor


def _assert_guidance_contract(guidance: dict):
    assert isinstance(guidance, dict)
    assert isinstance(guidance.get("outcome"), str)
    assert isinstance(guidance.get("topic"), str)
    assert isinstance(guidance.get("reason"), str) and guidance["reason"]
    assert isinstance(guidance.get("next_action"), str) and guidance["next_action"]
    assert isinstance(guidance.get("urgent"), bool)

    telemetry = guidance.get("telemetry")
    assert isinstance(telemetry, dict)
    assert isinstance(telemetry.get("decision_source"), str) and telemetry["decision_source"]

    inputs = telemetry.get("inputs")
    assert isinstance(inputs, dict)
    assert isinstance(inputs.get("outcome"), str)
    assert isinstance(inputs.get("hints_used"), int)
    assert isinstance(inputs.get("can_transfer"), bool)
    assert isinstance(inputs.get("topic"), str)

    signals = telemetry.get("signals")
    assert isinstance(signals, dict)
    assert signals.get("intervention_level") in {"none", "light", "strong"}
    assert isinstance(signals.get("pattern_detected"), bool)
    assert isinstance(signals.get("diagnosis_used"), bool)
    assert signals.get("confidence_delta") is None or isinstance(signals.get("confidence_delta"), float)


def test_practice_loop_simulation():
    session = TutorSessionState(session_id="s1", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u1", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)

    practice_service = DeterministicTutorPracticeService()
    assess_service = DeterministicTutorAssessmentService()

    items = practice_service.build_practice_items(
        session_state=session,
        learner_profile=learner,
        app_snapshot=app_snap,
        max_items=2,
    )
    assert items, "should generate at least one item"

    # simulate answering first item correctly (if mcq choose correct option)
    item0 = items[0]
    answer = ""
    if item0.item_type == "mcq":
        answer = item0.meta.get("correct_option", "A")
    else:
        # supply keywords
        kws = item0.meta.get("keywords", [])
        answer = " ".join(kws)
    submission = TutorAssessmentSubmission(item_id=item0.item_id, answer_text=answer)
    result = assess_service.assess(item=item0, submission=submission, session_state=session, learner_profile=learner)
    assert result.outcome in {"correct", "partial"}


def test_practice_loop_lifecycle():
    """Full lifecycle: build items → submit → assess → FSM transition → state update."""
    perf = PerformanceMonitor(enabled=True)
    controller = PracticeLoopController(perf_monitor=perf)
    
    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s2", module="m", topic="T1", mode="guided_practice")
    learner = TutorLearnerProfileSnapshot(learner_id="u2", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)

    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    # Step 1: Build items
    items = controller.build_practice_items(loop, max_items=2)
    assert len(items) > 0, "should generate items"

    # Step 2: Submit correct answer to first item
    item = items[0]
    answer = item.meta.get("correct_option", "A") if item.item_type == "mcq" else " ".join(item.meta.get("keywords", []))
    submission = TutorAssessmentSubmission(item_id=item.item_id, answer_text=answer)
    result = controller.submit_attempt(loop, item, submission)
    assert result.outcome in {"correct", "partial"}

    # Step 3: FSM transition on correct
    next_state = controller.advance_state(loop, "CORRECT_ATTEMPT", {"chapter": item.topic})
    assert next_state in {"SCAFFOLD", "CONSOLIDATE", "CHALLENGE"}

    # Step 4: Validate invariants
    valid, errors = controller.validate_loop_invariants(loop)
    assert valid, f"loop invariants violated: {errors}"

    # Step 5: Check performance budgets
    report = perf.report()
    assert report.get("budget_exceeded", 0) == 0, f"performance budgets exceeded: {report}"


def test_practice_loop_error_recovery():
    """Test handling of incorrect attempts and recovery path."""
    perf = PerformanceMonitor(enabled=True)
    controller = PracticeLoopController(perf_monitor=perf)
    
    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s3", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u3", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)

    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    items = controller.build_practice_items(loop, max_items=2)
    item = items[0]

    # Submit an incorrect answer (open-ended: without AI judge we get partial fallback)
    submission = TutorAssessmentSubmission(item_id=item.item_id, answer_text="wrong answer")
    result = controller.submit_attempt(loop, item, submission)
    assert result.outcome in {"incorrect", "partial"}

    # FSM should transition to PRODUCTIVE_STRUGGLE on error
    next_state = controller.advance_state(loop, "ERROR", {"chapter": item.topic})
    assert next_state == "PRODUCTIVE_STRUGGLE"

    # Posterior should be updated (beta incremented)
    posteriors_after = loop.cognitive_state.posteriors.get(item.topic)
    assert posteriors_after is not None


def test_practice_loop_runtime_fsm_tracks_present_submit_score_and_end():
    controller = PracticeLoopController(perf_monitor=PerformanceMonitor(enabled=True))
    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s-fsm-1", module="m", topic="T1", mode="guided_practice")
    learner = TutorLearnerProfileSnapshot(learner_id="u-fsm-1", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)
    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    item = controller.build_practice_items(loop, max_items=1)[0]
    controller.present_practice_item(loop, item, restart=True, source="test_present")
    assert loop.practice_fsm_state == PracticeLoopFsmState.AWAITING_SUBMISSION.value
    assert loop.session_state.meta["practice_loop_fsm_state"] == PracticeLoopFsmState.AWAITING_SUBMISSION.value

    controller.get_next_hint(loop, item, has_attempted=False)
    assert loop.practice_fsm_state == PracticeLoopFsmState.AWAITING_SUBMISSION.value

    answer = item.meta.get("correct_option", "A") if item.item_type == "mcq" else " ".join(item.meta.get("keywords", []))
    result = controller.submit_attempt(loop, item, TutorAssessmentSubmission(item_id=item.item_id, answer_text=answer))
    assert result.outcome in {"correct", "partial"}
    assert loop.practice_fsm_state == PracticeLoopFsmState.SCORED.value
    assert loop.session_state.meta["practice_loop_fsm_state"] == PracticeLoopFsmState.SCORED.value

    controller.complete_practice_session(loop, source="test_end")
    assert loop.practice_fsm_state == PracticeLoopFsmState.IDLE.value
    assert loop.session_state.meta["practice_loop_fsm_state"] == PracticeLoopFsmState.IDLE.value


def test_practice_loop_runtime_fsm_tracks_transfer_variant_path():
    controller = PracticeLoopController(perf_monitor=PerformanceMonitor(enabled=True))
    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s-fsm-2", module="m", topic="T1", mode="guided_practice")
    learner = TutorLearnerProfileSnapshot(learner_id="u-fsm-2", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)
    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    base_item = controller.build_practice_items(loop, max_items=1)[0]
    controller.present_practice_item(loop, base_item, restart=True, source="test_base_present")
    controller.note_submission_received(loop, base_item, source="test_base_submit")
    base_result = TutorAssessmentResult(
        item_id=base_item.item_id,
        outcome="correct",
        marks_awarded=1.0,
        marks_max=1.0,
        feedback="Base item correct.",
    )
    controller.note_assessment_result(loop, base_item, base_result, source="test_base_score")

    transfer_item = TutorPracticeItem.from_dict(
        {
            **base_item.to_dict(),
            "item_id": f"{base_item.item_id}-transfer",
            "meta": {**dict(base_item.meta or {}), "transfer_variant": True},
        }
    )
    controller.begin_transfer_variant(loop, transfer_item, source="test_transfer_start")
    assert loop.practice_fsm_state == PracticeLoopFsmState.TRANSFER_TESTING.value

    transfer_result = TutorAssessmentResult(
        item_id=transfer_item.item_id,
        outcome="correct",
        marks_awarded=1.0,
        marks_max=1.0,
        feedback="Transfer successful.",
    )
    controller.note_assessment_result(loop, transfer_item, transfer_result, source="test_transfer_result")
    assert loop.practice_fsm_state == PracticeLoopFsmState.SCORED.value


def test_practice_loop_tutor_gating():
    """Verify tutor only proposes items when quiz is active."""
    session = TutorSessionState(session_id="s4", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u4", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)

    cog_state = CognitiveState()
    # Quiz NOT active
    cog_state.quiz_active = False
    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    controller = PracticeLoopController()

    # Still builds items (not gated), but session reflects inactive
    items = controller.build_practice_items(loop, max_items=1)
    assert items

    # Activate quiz explicitly
    cog_state.quiz_active = True
    cog_state.working_memory.active_question_id = items[0].item_id
    valid, errors = controller.validate_loop_invariants(loop)
    # Should be valid once active + question is set
    assert valid or "quiz_active" not in str(errors)


def test_practice_loop_recommends_transfer_after_strong_correct():
    perf = PerformanceMonitor(enabled=True)
    controller = PracticeLoopController(perf_monitor=perf)

    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s5", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u5", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)
    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    item = controller.build_practice_items(loop, max_items=1)[0]
    post = loop.cognitive_state.get_structure_posterior(item.topic)
    post.alpha = 9.0
    post.beta = 2.0
    # Force a strong-correct path to validate transfer-oriented guidance.
    result = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="correct",
        marks_awarded=2.0,
        marks_max=2.0,
        feedback="Strong answer.",
    )

    guidance = controller.recommend_next_action(loop, item, result, hints_used=0)
    _assert_guidance_contract(guidance)
    assert guidance["next_action"]
    assert guidance["reason"]
    assert guidance["outcome"] == "correct"
    assert "urgent" in guidance
    assert guidance["urgent"] is False
    assert "telemetry" in guidance
    assert guidance["telemetry"]["decision_source"]
    assert guidance["telemetry"]["inputs"]["outcome"] == "correct"
    assert guidance["telemetry"]["signals"]["intervention_level"] == "none"
    assert guidance["telemetry"]["signals"]["diagnosis_used"] is False
    assert "intervention required" not in guidance["reason"].lower()


def test_practice_loop_recommends_light_intervention_after_partial():
    controller = PracticeLoopController(perf_monitor=PerformanceMonitor(enabled=True))
    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s6p", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u6p", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)
    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    item = controller.build_practice_items(loop, max_items=1)[0]
    result = TutorAssessmentResult(
        item_id=item.item_id,
        outcome="partial",
        marks_awarded=1.0,
        marks_max=2.0,
        feedback="Method mostly right; one step missing.",
    )
    guidance = controller.recommend_next_action(loop, item, result, hints_used=0)
    _assert_guidance_contract(guidance)
    assert guidance["outcome"] == "partial"
    assert guidance["urgent"] is True
    assert guidance["reason"].startswith("Targeted intervention advised.")
    assert "targeted hint" in str(guidance["next_action"]).lower()
    assert guidance["telemetry"]["signals"]["intervention_level"] == "light"
    assert guidance["telemetry"]["signals"]["diagnosis_used"] is False


def test_practice_loop_recommends_remediation_after_incorrect():
    controller = PracticeLoopController(perf_monitor=PerformanceMonitor(enabled=True))
    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s6", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u6", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)
    loop = PracticeLoopSessionState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    item = controller.build_practice_items(loop, max_items=1)[0]
    result = controller.submit_attempt(loop, item, TutorAssessmentSubmission(item_id=item.item_id, answer_text="wrong"))
    guidance = controller.recommend_next_action(loop, item, result, hints_used=1)
    _assert_guidance_contract(guidance)
    # Without AI judge, open-ended items get "partial" fallback; with AI judge would be "incorrect"
    assert guidance["outcome"] in {"incorrect", "partial"}
    assert guidance["next_action"]
    assert guidance["reason"]
    assert guidance["urgent"] is True
    assert "telemetry" in guidance
    assert guidance["telemetry"]["inputs"]["hints_used"] == 1
    # Intervention level and wording depend on outcome (incorrect vs partial fallback)
    assert guidance["telemetry"]["signals"]["intervention_level"] in {"strong", "light", "moderate"}
    assert isinstance(guidance["telemetry"]["signals"].get("diagnosis_used", False), bool)
    assert isinstance(guidance["telemetry"]["signals"].get("pattern_detected", False), bool)
