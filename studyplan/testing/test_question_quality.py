"""Unit tests for question quality evaluation."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from studyplan.question_quality import QuestionQuality, QuestionBankEvaluator


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
    assert "duplicate option" in rpt["warnings"][0]
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
    assert files, "No question files found for evaluation"
    evaluator = QuestionBankEvaluator(files)
    evaluator.run()
    summary = evaluator.summary()
    assert summary["total"] >= 1
    assert summary["low_quality_count"] == 0
    assert summary["average_score"] >= 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
