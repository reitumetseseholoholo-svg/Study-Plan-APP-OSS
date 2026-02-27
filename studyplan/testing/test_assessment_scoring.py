from studyplan.services import DeterministicTutorPracticeService, DeterministicTutorAssessmentService
from studyplan.contracts import (
    TutorPracticeItem,
    TutorAssessmentSubmission,
    TutorSessionState,
    TutorLearnerProfileSnapshot,
)


def make_short_answer_item():
    return TutorPracticeItem(
        item_id="i1",
        item_type="short_answer",
        prompt="Explain X",
        topic="topic",
        expected_format="1-2 lines",
        meta={"keywords": ["x", "explain"], "marks_max": 2.0},
    )


def test_keyword_assessment_correct():
    item = make_short_answer_item()
    service = DeterministicTutorAssessmentService()
    submission = TutorAssessmentSubmission(item_id="i1", answer_text="x explain")
    result = service.assess(
        item=item,
        submission=submission,
        session_state=TutorSessionState(session_id="s1", module="m", topic="topic"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u1", module="m"),
    )
    assert result.outcome == "correct"


def test_keyword_assessment_incorrect_no_keywords():
    item = make_short_answer_item()
    service = DeterministicTutorAssessmentService()
    submission = TutorAssessmentSubmission(item_id="i1", answer_text="nothing relevant")
    result = service.assess(
        item=item,
        submission=submission,
        session_state=TutorSessionState(session_id="s2", module="m", topic="topic"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u2", module="m"),
    )
    assert result.outcome == "incorrect"
