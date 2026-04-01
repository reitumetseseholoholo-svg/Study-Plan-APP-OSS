from studyplan.cognitive_state import CognitiveState, CompetencyPosterior
from studyplan.contracts import (
    AppStateSnapshot,
    TutorAssessmentSubmission,
    TutorLearnerProfileSnapshot,
    TutorLoopTurnRequest,
    TutorPracticeItem,
    TutorSessionState,
)
from studyplan.practice_loop_controller import PracticeLoopController, PracticeLoopSessionState


def test_dialog_prompt_construction():
    # smoke simulation: ensure data structures support a request
    session = TutorSessionState(session_id="s1", module="m", topic="T1")
    learner = TutorLearnerProfileSnapshot(learner_id="u1", module="m")
    app = AppStateSnapshot(module="m", current_topic="T1", coach_pick="", days_to_exam=None, must_review_due=0, overdue_srs_count=0)
    req = TutorLoopTurnRequest(
        user_message="Hello tutor",
        app_snapshot=app,
        session_state=session,
        learner_profile=learner,
    )
    assert "Hello tutor" in req.user_message
    # just ensure conversion to dict doesn't crash
    d = req.__dict__
    assert d["user_message"] == "Hello tutor"


def test_learner_flow_feedback_tap_adapts_next_action():
    """Strict learner flow: start -> ask -> answer -> feedback tap -> next answer adapts."""
    controller = PracticeLoopController()

    session = TutorSessionState(session_id="sess-1", module="fm", topic="npv")
    learner = TutorLearnerProfileSnapshot(learner_id="u1", module="fm")
    app = AppStateSnapshot(
        module="fm",
        current_topic="npv",
        coach_pick="",
        days_to_exam=None,
        must_review_due=0,
        overdue_srs_count=0,
    )
    loop_state = PracticeLoopSessionState(
        cognitive_state=CognitiveState(),
        session_state=session,
        learner_profile=learner,
        app_snapshot=app,
    )

    item = TutorPracticeItem(
        item_id="npv-mcq-1",
        item_type="mcq",
        prompt="In NPV, what sign is the initial investment?",
        topic="npv",
        meta={
            "correct_option": "B",
            "marks_max": 1.0,
            "error_tags_by_option": {"A": "sign_error"},
        },
    )

    # 1) First checked answer is wrong.
    first_submission = TutorAssessmentSubmission(item_id=item.item_id, answer_text="A")
    first_result = controller.submit_attempt(loop_state, item, first_submission)
    assert first_result.outcome == "incorrect"

    first_guidance = controller.recommend_next_action(loop_state, item, first_result, hints_used=0)
    assert first_guidance["urgent"] is True
    assert "retry" in str(first_guidance["next_action"]).lower()

    # 2) Learner taps feedback/hint.
    hint = controller.get_next_hint(
        loop_state,
        item,
        has_attempted=False,
        error_tags=first_result.error_tags,
    )
    assert str(hint.text or "").strip()

    # Make learner transfer-ready so we can verify hint usage changes next action.
    loop_state.cognitive_state.structure_posteriors[item.topic] = CompetencyPosterior(alpha=12.0, beta=2.0)

    # 3) Next checked answer is correct.
    second_submission = TutorAssessmentSubmission(item_id=item.item_id, answer_text="B")
    second_result = controller.submit_attempt(loop_state, item, second_submission)
    assert second_result.outcome == "correct"

    # Baseline without feedback usage would promote transfer.
    guidance_without_feedback = controller.recommend_next_action(loop_state, item, second_result, hints_used=0)
    assert "transfer" in str(guidance_without_feedback["next_action"]).lower()

    # After feedback tap (hints used), next action should adapt away from transfer.
    guidance_after_feedback = controller.recommend_next_action(loop_state, item, second_result, hints_used=1)
    assert "transfer" not in str(guidance_after_feedback["next_action"]).lower()
    assert guidance_after_feedback["next_action"] != guidance_without_feedback["next_action"]
