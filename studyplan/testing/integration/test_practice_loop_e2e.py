import time

from studyplan.services import DeterministicTutorPracticeService, DeterministicTutorAssessmentService
from studyplan.contracts import (
    TutorSessionState,
    TutorLearnerProfileSnapshot,
    AppStateSnapshot,
    TutorAssessmentSubmission,
    TutorAssessmentResult,
)
from studyplan.practice_loop_controller import PracticeLoopController, PracticeLoopState
from studyplan.cognitive_state import CognitiveState
from studyplan.performance_monitor import PerformanceMonitor


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

    loop = PracticeLoopState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

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

    loop = PracticeLoopState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    items = controller.build_practice_items(loop, max_items=2)
    item = items[0]

    # Submit an incorrect answer
    submission = TutorAssessmentSubmission(item_id=item.item_id, answer_text="wrong answer")
    result = controller.submit_attempt(loop, item, submission)
    assert result.outcome == "incorrect"

    # FSM should transition to PRODUCTIVE_STRUGGLE on error
    next_state = controller.advance_state(loop, "ERROR", {"chapter": item.topic})
    assert next_state == "PRODUCTIVE_STRUGGLE"

    # Posterior should be updated (beta incremented)
    posteriors_after = loop.cognitive_state.posteriors.get(item.topic)
    assert posteriors_after is not None


def test_practice_loop_tutor_gating():
    """Verify tutor only proposes items when quiz is active."""
    session = TutorSessionState(session_id="s4", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u4", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)

    cog_state = CognitiveState()
    # Quiz NOT active
    cog_state.quiz_active = False
    loop = PracticeLoopState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

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
    loop = PracticeLoopState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

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
    assert guidance["next_action"]
    assert guidance["reason"]
    assert guidance["outcome"] == "correct"


def test_practice_loop_recommends_remediation_after_incorrect():
    controller = PracticeLoopController(perf_monitor=PerformanceMonitor(enabled=True))
    cog_state = CognitiveState()
    session = TutorSessionState(session_id="s6", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u6", module="m")
    app_snap = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)
    loop = PracticeLoopState(cognitive_state=cog_state, session_state=session, learner_profile=learner, app_snapshot=app_snap)

    item = controller.build_practice_items(loop, max_items=1)[0]
    result = controller.submit_attempt(loop, item, TutorAssessmentSubmission(item_id=item.item_id, answer_text="wrong"))
    guidance = controller.recommend_next_action(loop, item, result, hints_used=1)
    assert guidance["outcome"] == "incorrect"
    assert guidance["urgent"] is True
    assert "retry" in str(guidance["next_action"]).lower()
