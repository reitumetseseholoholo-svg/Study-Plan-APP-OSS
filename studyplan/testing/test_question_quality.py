"""Unit tests for question quality evaluation."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from studyplan.question_quality import (
    QuestionQuality,
    QuestionBankEvaluator,
    correct_option_length_guessable_reason,
    option_looks_like_see_explanation,
    get_poor_quality_indices,
)


SAMPLE_ITEM = {
    "question": "What is 2+2?",
    "options": ["1", "2", "3", "4"],
    "correct": "4",
    "explanation": "Basic addition.",
}

BAD_ITEM = {
    "question": "",
    "options": ["A", "A", "B"],
    "correct": "C",
    "explanation": "",
}


def test_quality_good_item():
    q = QuestionQuality(SAMPLE_ITEM)
    q.assess()
    rpt = q.report()
    assert rpt["errors"] == []
    assert rpt["score"] > 0.8


def test_quality_bad_item():
    q = QuestionQuality(BAD_ITEM)
    q.assess()
    rpt = q.report()
    assert "missing question text" in rpt["errors"]
    assert any("duplicate option" in e for e in rpt["errors"])
    assert rpt["score"] < 0.5


def test_bank_evaluator_on_file(tmp_path: Path):
    # create temporary JSON file with two items
    data = {"chapter": [SAMPLE_ITEM, BAD_ITEM]}
    path = tmp_path / "test.json"
    path.write_text(json.dumps(data))

    evaluator = QuestionBankEvaluator([str(path)])
    evaluator.run()
    summary = evaluator.summary()
    assert summary["total"] == 2
    assert summary["low_quality_count"] == 1
    bad_list = evaluator.report_bad()
    assert len(bad_list) == 1
    loc, rpt = bad_list[0]
    assert "test.json" in loc
    assert rpt["score"] < 0.6


def test_bank_evaluator_real_files():
    """Run evaluator on the real JSON question banks and ensure no low‑quality items."""
    import glob
    files = glob.glob(os.path.join(os.path.dirname(__file__), "..", "..", "ai_questions_*.json"))
    if not files:
        pytest.skip("No ai_questions_*.json files found for evaluation (optional fixture)")
    evaluator = QuestionBankEvaluator(files)
    evaluator.run()
    summary = evaluator.summary()
    assert summary["total"] >= 1
    assert summary["low_quality_count"] == 0
    assert summary["average_score"] >= 0.9


def test_option_looks_like_see_explanation():
    """Options that are 'see explanation' in any wording are detected."""
    assert option_looks_like_see_explanation("See explanation") is True
    assert option_looks_like_see_explanation("Refer to the explanation") is True
    assert option_looks_like_see_explanation("View the solution below") is True
    assert option_looks_like_see_explanation("Explanation below") is True
    assert option_looks_like_see_explanation("See below") is True
    assert option_looks_like_see_explanation("") is False
    assert option_looks_like_see_explanation("The NPV is the present value of cash flows.") is False
    assert option_looks_like_see_explanation("A. See explanation") is True


def test_quality_see_explanation_option_is_error():
    """Question with an option like 'See explanation' gets an error and low score."""
    item = {
        "question": "What is WACC?",
        "options": ["A", "B", "C", "See explanation"],
        "correct": "A",
        "explanation": "WACC is weighted average cost of capital.",
    }
    q = QuestionQuality(item)
    q.assess()
    rpt = q.report()
    assert "option is 'see explanation' placeholder" in rpt["errors"]
    assert rpt["score"] < 0.6


def test_get_poor_quality_indices_see_explanation():
    """get_poor_quality_indices flags questions with see-explanation options."""
    items = [
        {"question": "Q1?", "options": ["1", "2", "3", "4"], "correct": "1", "explanation": "Yes."},
        {"question": "Q2?", "options": ["A", "B", "See explanation", "D"], "correct": "A", "explanation": "No."},
    ]
    poor = get_poor_quality_indices("ch", items, detect_similar=False)
    assert len(poor) == 1
    assert poor[0] == (1, "see_explanation_in_options")


def test_get_poor_quality_indices_similar():
    """get_poor_quality_indices flags similar/duplicate questions."""
    items = [
        {"question": "What is the main advantage of using NPV for investment appraisal?", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": "X"},
        {"question": "What is the main advantage of using NPV for investment appraisal?", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": "Y"},
    ]
    poor = get_poor_quality_indices("ch", items, detect_see_explanation=False, detect_bare_letter_correct=False, similar_min_words=5)
    assert len(poor) == 1
    assert poor[0][0] == 1 and poor[0][1] == "similar_question"


def test_correct_option_length_guessable_long():
    d1 = "Distractor one text here"
    d2 = "Distractor two text here"
    d3 = "Distractor three text here"
    long_correct = "X" * 90
    item = {
        "question": "Which statement best describes the treatment of deferred tax?",
        "options": [d1, d2, d3, long_correct],
        "correct": long_correct,
        "explanation": "Because standards say so.",
    }
    assert correct_option_length_guessable_reason(item) == "correct_option_much_longer_than_distractors"


def test_correct_option_length_guessable_short():
    long_d = "A detailed narrative option that runs to many characters for plausibility."
    item = {
        "question": "Which is the right classification?",
        "options": [long_d, long_d.replace("A ", "B "), long_d.replace("A ", "C "), "Yes"],
        "correct": "Yes",
        "explanation": "Yes is correct.",
    }
    assert correct_option_length_guessable_reason(item) == "correct_option_much_shorter_than_distractors"


def test_get_poor_quality_indices_length_guessable():
    d1 = "Distractor one text here"
    d2 = "Distractor two text here"
    d3 = "Distractor three text here"
    long_correct = "X" * 90
    items = [
        {"question": "Q1?", "options": ["a", "b", "c", "d"], "correct": "a", "explanation": "ok"},
        {
            "question": "Q2?",
            "options": [d1, d2, d3, long_correct],
            "correct": "D",
            "explanation": "ok",
        },
    ]
    poor = get_poor_quality_indices("ch", items, detect_see_explanation=False, detect_similar=False, detect_bare_letter_correct=False)
    assert poor == [(1, "correct_option_much_longer_than_distractors")]


def test_length_guessable_not_flagged_when_balanced():
    item = {
        "question": "What is 2+2?",
        "options": ["Three or so", "About four", "Roughly five", "Near six"],
        "correct": "About four",
        "explanation": "Arithmetic.",
    }
    assert correct_option_length_guessable_reason(item) is None


def test_quality_duplicate_options_is_error():
    """Duplicate options are now an error (not just a warning) in QuestionQuality."""
    item = {
        "question": "What is the treatment of goodwill under IFRS 3?",
        "options": ["Amortise over useful life", "Amortise over useful life", "Write off immediately", "Capitalise"],
        "correct": "Capitalise",
        "explanation": "Goodwill is not amortised under IFRS 3.",
    }
    q = QuestionQuality(item)
    q.assess()
    rpt = q.report()
    assert any("duplicate option" in e for e in rpt["errors"])
    assert rpt["score"] < 0.6


def test_quality_all_identical_options_is_error():
    """All four options being the same text is caught as duplicate options error."""
    item = {
        "question": "Which of the following is a current asset?",
        "options": ["Cash", "Cash", "Cash", "Cash"],
        "correct": "Cash",
        "explanation": "Cash is a current asset.",
    }
    q = QuestionQuality(item)
    q.assess()
    rpt = q.report()
    assert any("duplicate option" in e for e in rpt["errors"])
    assert rpt["score"] < 0.6


def test_quality_placeholder_options_is_error():
    """Options that look like LLM-generated placeholders are caught as an error."""
    item = {
        "question": "Which treatment applies to development costs under IAS 38?",
        "options": [
            "Full option text A",
            "Full option text B",
            "Full option text C",
            "Full option text D",
        ],
        "correct": "Full option text A",
        "explanation": "Development costs may be capitalised if criteria are met.",
    }
    q = QuestionQuality(item)
    q.assess()
    rpt = q.report()
    assert any("placeholder" in e for e in rpt["errors"])
    assert rpt["score"] < 0.6


def test_get_poor_quality_indices_duplicate_options():
    """get_poor_quality_indices flags questions with duplicate options."""
    items = [
        {"question": "Q1?", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": "Yes."},
        {"question": "Q2?", "options": ["Same", "Same", "Other", "Another"], "correct": "Other", "explanation": "No."},
    ]
    poor = get_poor_quality_indices("ch", items, detect_see_explanation=False, detect_similar=False, detect_bare_letter_correct=False, detect_length_guessable=False)
    assert len(poor) == 1
    assert poor[0] == (1, "duplicate_options")


def test_get_poor_quality_indices_all_identical_options():
    """get_poor_quality_indices flags questions where all four options are the same."""
    items = [
        {"question": "Q1?", "options": ["Cash", "Cash", "Cash", "Cash"], "correct": "Cash", "explanation": "Yes."},
    ]
    poor = get_poor_quality_indices("ch", items, detect_see_explanation=False, detect_similar=False, detect_bare_letter_correct=False, detect_length_guessable=False)
    assert len(poor) == 1
    assert poor[0] == (0, "duplicate_options")


def test_get_poor_quality_indices_placeholder_options():
    """get_poor_quality_indices flags questions with LLM placeholder option text."""
    items = [
        {"question": "Q1?", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": "Yes."},
        {
            "question": "Q2?",
            "options": ["Full option text A", "Full option text B", "Full option text C", "Full option text D"],
            "correct": "Full option text A",
            "explanation": "No.",
        },
    ]
    poor = get_poor_quality_indices("ch", items, detect_see_explanation=False, detect_similar=False, detect_bare_letter_correct=False, detect_length_guessable=False)
    assert len(poor) == 1
    assert poor[0] == (1, "placeholder_options")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
