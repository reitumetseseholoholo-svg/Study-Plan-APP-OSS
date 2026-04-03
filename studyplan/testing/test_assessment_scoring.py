from studyplan.services import DeterministicTutorPracticeService, DeterministicTutorAssessmentService
from studyplan.contracts import (
    TutorPracticeItem,
    TutorAssessmentSubmission,
    TutorSessionState,
    TutorLearnerProfileSnapshot,
)

INVENTORY_OPTIONS = [
    "To verify the accuracy of the inventory records",
    "To ensure the safety of the inventory",
    "To calculate the gross profit",
    "To determine the cost of goods sold",
]


def make_short_answer_item():
    return TutorPracticeItem(
        item_id="i1",
        item_type="short_answer",
        prompt="Explain X",
        topic="topic",
        expected_format="1-2 lines",
        meta={"keywords": ["x", "explain"], "marks_max": 2.0},
    )


def make_mcq_item(correct_option="A", options=None):
    """MCQ item — correct_option may be a letter or full text (to exercise both paths)."""
    return TutorPracticeItem(
        item_id="mcq1",
        item_type="mcq",
        prompt="What is the primary purpose of conducting an inventory count?",
        topic="Chapter 6",
        expected_format="Answer A-D",
        meta={
            "options": options or INVENTORY_OPTIONS,
            "correct_option": correct_option,
            "marks_max": 1.0,
        },
    )


def _assess(item, answer_text):
    service = DeterministicTutorAssessmentService()
    return service.assess(
        item=item,
        submission=TutorAssessmentSubmission(item_id=item.item_id, answer_text=answer_text),
        session_state=TutorSessionState(session_id="s1", module="m", topic="topic"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u1", module="m"),
    )


def test_short_answer_requires_ai_judge():
    """Open-ended items use AI judge only; deterministic returns fallback (no keyword matching)."""
    item = make_short_answer_item()
    service = DeterministicTutorAssessmentService()
    submission = TutorAssessmentSubmission(item_id="i1", answer_text="x explain")
    result = service.assess(
        item=item,
        submission=submission,
        session_state=TutorSessionState(session_id="s1", module="m", topic="topic"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u1", module="m"),
    )
    assert result.outcome == "partial"
    assert "AI judge" in result.feedback or "ai_judge" in str(result.error_tags)


def test_short_answer_fallback_no_keywords():
    """Deterministic never uses keywords; open-ended always gets same fallback."""
    item = make_short_answer_item()
    service = DeterministicTutorAssessmentService()
    submission = TutorAssessmentSubmission(item_id="i1", answer_text="nothing relevant")
    result = service.assess(
        item=item,
        submission=submission,
        session_state=TutorSessionState(session_id="s2", module="m", topic="topic"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u2", module="m"),
    )
    assert result.outcome == "partial"
    assert "ai_judge_required" in result.error_tags


# ---------------------------------------------------------------------------
# MCQ assessment – core correctness
# ---------------------------------------------------------------------------

def test_mcq_plain_letter_correct():
    """User types the bare letter — the happy path."""
    assert _assess(make_mcq_item(correct_option="A"), "A").outcome == "correct"


def test_mcq_plain_letter_wrong():
    """User types a wrong letter."""
    assert _assess(make_mcq_item(correct_option="A"), "B").outcome == "incorrect"


# ---------------------------------------------------------------------------
# Bug fix: correct_option stored as full option text (the exact bug in screenshot)
# ---------------------------------------------------------------------------

def test_mcq_correct_option_full_text_user_types_letter():
    """LLM stored correct_option as full text; user types the matching letter.
    Previously returned 'incorrect' because 'A' != 'TO VERIFY THE ACCURACY…'."""
    item = make_mcq_item(correct_option=INVENTORY_OPTIONS[0])  # full text → index 0 = A
    result = _assess(item, "A")
    assert result.outcome == "correct", (
        f"Expected correct but got {result.outcome!r}. Feedback: {result.feedback!r}"
    )


def test_mcq_correct_option_full_text_user_types_full_text():
    """correct_option is full text and user also types the full text."""
    assert _assess(make_mcq_item(correct_option=INVENTORY_OPTIONS[0]), INVENTORY_OPTIONS[0]).outcome == "correct"


def test_mcq_correct_option_full_text_wrong_letter():
    """correct_option is full text (index 0 = A) but user picks a different letter."""
    assert _assess(make_mcq_item(correct_option=INVENTORY_OPTIONS[0]), "C").outcome == "incorrect"


# ---------------------------------------------------------------------------
# Bug fix: regex word-boundary — letters inside words must not be extracted
# ---------------------------------------------------------------------------

def test_mcq_natural_language_answer_correct():
    """'my answer is A' — previously 'a' in 'answer' was extracted, giving wrong letter."""
    assert _assess(make_mcq_item(correct_option="A"), "my answer is A").outcome == "correct"


def test_mcq_word_before_letter_not_mistaken():
    """'because D' — 'b' in 'because' must not be treated as answer choice B."""
    assert _assess(make_mcq_item(correct_option="D"), "because D").outcome == "correct"


def test_mcq_letter_in_word_ignored():
    """'about option D' — 'b' in 'about' must not shadow D."""
    assert _assess(make_mcq_item(correct_option="D"), "I talked about option D").outcome == "correct"


# ---------------------------------------------------------------------------
# Bug fix: full-text answer accepted as fallback
# ---------------------------------------------------------------------------

def test_mcq_full_text_answer_accepted():
    """User types the complete option text instead of a letter."""
    assert _assess(make_mcq_item(correct_option="A"), INVENTORY_OPTIONS[0]).outcome == "correct"


def test_mcq_full_text_wrong_option_rejected():
    """User types a different option's full text — must still be incorrect."""
    assert _assess(make_mcq_item(correct_option="A"), INVENTORY_OPTIONS[2]).outcome == "incorrect"
