from studyplan.contracts import (
    TutorLoopTurnRequest,
    AppStateSnapshot,
    TutorSessionState,
    TutorLearnerProfileSnapshot,
)


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
