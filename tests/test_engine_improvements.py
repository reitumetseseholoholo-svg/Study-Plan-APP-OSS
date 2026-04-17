"""Tests for StudyPlanEngine.export_flashcards_csv and module versioning helpers."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from unittest import mock

import pytest

from studyplan_engine import StudyPlanEngine


@pytest.fixture
def engine_no_io(monkeypatch):
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    return StudyPlanEngine()


@pytest.fixture
def engine_with_questions(engine_no_io):
    """Engine pre-seeded with a couple of questions for export tests."""
    eng = engine_no_io
    chapter = eng.CHAPTERS[0]
    eng.QUESTIONS[chapter] = [
        {
            "question": "What is NPV?",
            "options": ["A", "B", "C", "D"],
            "correct": "A",
            "explanation": "NPV discounts future cash flows.",
        },
        {
            "question": "Which formula?",
            "options": ["X", "Y"],
            "correct": "X",
            "explanation": "",
        },
    ]
    # Seed matching SRS rows.
    eng.srs_data[chapter] = [
        {"last_review": "2025-01-01", "interval": 5, "efactor": 2.3},
        {"last_review": None, "interval": 1, "efactor": 2.5},
    ]
    return eng, chapter


# ---------------------------------------------------------------------------
# export_flashcards_csv
# ---------------------------------------------------------------------------


def test_export_creates_file(engine_with_questions, tmp_path):
    eng, chapter = engine_with_questions
    out = str(tmp_path / "cards.csv")
    result = eng.export_flashcards_csv(out)
    assert os.path.exists(out)
    assert result["rows_written"] == 2
    assert chapter in result["chapters"]
    assert result["output_path"] == out


def test_export_csv_has_correct_headers(engine_with_questions, tmp_path):
    eng, chapter = engine_with_questions
    out = str(tmp_path / "cards.csv")
    eng.export_flashcards_csv(out)
    with open(out, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
    expected = {
        "chapter", "question", "option1", "option2", "option3", "option4",
        "correct", "explanation", "last_review", "interval_days", "efactor",
        "due_date", "fsrs_stability", "fsrs_difficulty", "fsrs_reps", "fsrs_lapses",
    }
    assert expected.issubset(set(headers))


def test_export_csv_content_matches_questions(engine_with_questions, tmp_path):
    eng, chapter = engine_with_questions
    out = str(tmp_path / "cards.csv")
    eng.export_flashcards_csv(out)
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert any(r["question"] == "What is NPV?" for r in rows)
    assert any(r["question"] == "Which formula?" for r in rows)


def test_export_csv_chapter_filter(engine_with_questions, tmp_path):
    eng, chapter = engine_with_questions
    out = str(tmp_path / "filtered.csv")
    result = eng.export_flashcards_csv(out, chapters=[chapter])
    assert chapter in result["chapters"]


def test_export_csv_empty_questions_skips_chapter(engine_no_io, tmp_path):
    out = str(tmp_path / "empty.csv")
    result = engine_no_io.export_flashcards_csv(out)
    assert result["rows_written"] == 0
    assert result["chapters"] == []


def test_export_csv_interval_and_efactor_in_row(engine_with_questions, tmp_path):
    eng, chapter = engine_with_questions
    out = str(tmp_path / "cards.csv")
    eng.export_flashcards_csv(out)
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    row = next(r for r in rows if r["question"] == "What is NPV?")
    assert float(row["interval_days"]) == 5.0
    assert float(row["efactor"]) > 0


def test_export_csv_raises_on_bad_path(engine_with_questions):
    eng, _ = engine_with_questions
    with pytest.raises(Exception):
        eng.export_flashcards_csv("/nonexistent_dir/subdir/out.csv")


# ---------------------------------------------------------------------------
# compute_module_content_hash
# ---------------------------------------------------------------------------


def test_content_hash_is_hex_string(engine_no_io):
    h = engine_no_io.compute_module_content_hash()
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256 hex = 64 chars
    int(h, 16)  # must be valid hex


def test_content_hash_changes_when_chapters_change(engine_no_io, monkeypatch):
    h1 = engine_no_io.compute_module_content_hash()
    engine_no_io.CHAPTERS = list(engine_no_io.CHAPTERS) + ["Extra Chapter"]
    h2 = engine_no_io.compute_module_content_hash()
    assert h1 != h2


def test_content_hash_is_stable_on_same_data(engine_no_io):
    h1 = engine_no_io.compute_module_content_hash()
    h2 = engine_no_io.compute_module_content_hash()
    assert h1 == h2


# ---------------------------------------------------------------------------
# get_module_version_info
# ---------------------------------------------------------------------------


def test_get_module_version_info_returns_expected_keys(engine_no_io):
    info = engine_no_io.get_module_version_info()
    assert "module_version" in info
    assert "content_hash" in info
    assert "stored_hash" in info
    assert "hash_matches" in info
    assert "registry_id" in info
    assert "registry_url" in info


def test_get_module_version_info_content_hash_matches_compute(engine_no_io):
    info = engine_no_io.get_module_version_info()
    assert info["content_hash"] == engine_no_io.compute_module_content_hash()


def test_get_module_version_info_no_config_path(engine_no_io):
    # No config path → defaults returned.
    info = engine_no_io.get_module_version_info()
    assert info["module_version"] == "0.0.0"
    assert info["registry_id"] == ""
    assert info["hash_matches"] is None


def test_get_module_version_info_reads_config_file(engine_no_io, tmp_path):
    config = {
        "chapters": list(engine_no_io.CHAPTERS),
        "module_version": "1.2.3",
        "content_hash": "abc123",
        "registry_id": "test_module",
        "registry_url": "https://example.com/module.json",
    }
    config_file = tmp_path / "module.json"
    config_file.write_text(json.dumps(config))
    engine_no_io._last_loaded_module_config_path = str(config_file)

    info = engine_no_io.get_module_version_info()
    assert info["module_version"] == "1.2.3"
    assert info["stored_hash"] == "abc123"
    assert info["registry_id"] == "test_module"
    assert info["registry_url"] == "https://example.com/module.json"
    # hash_matches: current hash vs "abc123" – they won't match unless the
    # chapters are exactly what was used to compute that hash, so it can be
    # True or False.  Just check the type.
    assert isinstance(info["hash_matches"], bool)


# ---------------------------------------------------------------------------
# stamp_module_content_hash
# ---------------------------------------------------------------------------


def test_stamp_content_hash_returns_false_without_config_path(engine_no_io):
    result = engine_no_io.stamp_module_content_hash()
    assert result is False


def test_stamp_content_hash_writes_hash_to_file(engine_no_io, tmp_path):
    config = {"chapters": list(engine_no_io.CHAPTERS), "module_version": "1.0.0"}
    config_file = tmp_path / "mod.json"
    config_file.write_text(json.dumps(config))
    engine_no_io._last_loaded_module_config_path = str(config_file)

    result = engine_no_io.stamp_module_content_hash()
    assert result is True

    with open(str(config_file)) as fh:
        updated = json.load(fh)
    assert "content_hash" in updated
    assert updated["content_hash"] == engine_no_io.compute_module_content_hash()


# ---------------------------------------------------------------------------
# get_accuracy_by_chapter
# ---------------------------------------------------------------------------


def _seed_question_stats(eng, chapter, entries):
    """Seed question_stats[chapter] with a list of (key, attempts, correct) tuples."""
    stats_by_ch = {}
    for key, attempts, correct in entries:
        stats_by_ch[str(key)] = {"attempts": attempts, "correct": correct, "streak": 0}
    eng.question_stats[chapter] = stats_by_ch


def test_get_accuracy_by_chapter_empty_returns_empty(engine_no_io):
    result = engine_no_io.get_accuracy_by_chapter()
    assert isinstance(result, dict)
    assert result == {}


def test_get_accuracy_by_chapter_basic(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    _seed_question_stats(engine_no_io, chapter, [("0", 4, 3), ("1", 2, 1)])
    result = engine_no_io.get_accuracy_by_chapter()
    assert chapter in result
    row = result[chapter]
    assert row["attempts"] == 6
    assert row["correct"] == 4
    assert abs(row["accuracy"] - round(4 / 6, 4)) < 1e-9
    assert row["questions_practiced"] == 2


def test_get_accuracy_by_chapter_excludes_zero_attempt_entries(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    _seed_question_stats(engine_no_io, chapter, [("0", 0, 0), ("1", 5, 5)])
    result = engine_no_io.get_accuracy_by_chapter()
    row = result[chapter]
    assert row["attempts"] == 5
    assert row["questions_practiced"] == 1


def test_get_accuracy_by_chapter_omits_chapters_with_no_attempts(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    engine_no_io.question_stats[chapter] = {"0": {"attempts": 0, "correct": 0}}
    result = engine_no_io.get_accuracy_by_chapter()
    assert chapter not in result


def test_get_accuracy_by_chapter_perfect_accuracy(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    _seed_question_stats(engine_no_io, chapter, [("0", 3, 3), ("1", 7, 7)])
    result = engine_no_io.get_accuracy_by_chapter()
    assert result[chapter]["accuracy"] == 1.0


def test_get_accuracy_by_chapter_multiple_chapters(engine_no_io):
    if len(engine_no_io.CHAPTERS) < 2:
        pytest.skip("Need at least 2 chapters")
    ch1, ch2 = engine_no_io.CHAPTERS[0], engine_no_io.CHAPTERS[1]
    _seed_question_stats(engine_no_io, ch1, [("0", 10, 8)])
    _seed_question_stats(engine_no_io, ch2, [("0", 5, 2)])
    result = engine_no_io.get_accuracy_by_chapter()
    assert ch1 in result and ch2 in result
    assert result[ch1]["accuracy"] > result[ch2]["accuracy"]


# ---------------------------------------------------------------------------
# get_weakest_questions
# ---------------------------------------------------------------------------


def test_get_weakest_questions_empty_returns_empty(engine_no_io):
    result = engine_no_io.get_weakest_questions()
    assert isinstance(result, list)
    assert result == []


def test_get_weakest_questions_respects_min_attempts(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    _seed_question_stats(engine_no_io, chapter, [("0", 1, 0)])  # 1 attempt < default min 2
    result = engine_no_io.get_weakest_questions(min_attempts=2)
    assert result == []


def test_get_weakest_questions_includes_at_min_attempts(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    _seed_question_stats(engine_no_io, chapter, [("0", 2, 0)])
    result = engine_no_io.get_weakest_questions(min_attempts=2)
    assert len(result) == 1
    assert result[0]["accuracy"] == 0.0
    assert result[0]["chapter"] == chapter


def test_get_weakest_questions_sorted_worst_first(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    engine_no_io.question_stats[chapter] = {
        "0": {"attempts": 4, "correct": 3},  # 75%
        "1": {"attempts": 4, "correct": 1},  # 25%  ← worst
        "2": {"attempts": 4, "correct": 2},  # 50%
    }
    result = engine_no_io.get_weakest_questions(n=3, min_attempts=1)
    accuracies = [r["accuracy"] for r in result]
    assert accuracies == sorted(accuracies)
    assert result[0]["accuracy"] == pytest.approx(0.25)


def test_get_weakest_questions_respects_n_limit(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    engine_no_io.question_stats[chapter] = {
        str(i): {"attempts": 3, "correct": i % 3} for i in range(10)
    }
    result = engine_no_io.get_weakest_questions(n=3, min_attempts=1)
    assert len(result) <= 3


def test_get_weakest_questions_row_keys(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    _seed_question_stats(engine_no_io, chapter, [("0", 5, 2)])
    result = engine_no_io.get_weakest_questions(min_attempts=1)
    assert len(result) == 1
    row = result[0]
    assert set(row.keys()) >= {"chapter", "index", "question", "attempts", "correct", "accuracy"}


def test_get_weakest_questions_includes_question_text(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    engine_no_io.QUESTIONS[chapter] = [
        {"question": "What is WACC?", "options": ["A", "B"], "correct": "A", "explanation": ""},
    ]
    _seed_question_stats(engine_no_io, chapter, [("0", 3, 1)])
    result = engine_no_io.get_weakest_questions(min_attempts=1)
    assert result[0]["question"] == "What is WACC?"
    assert result[0]["index"] == 0


def test_get_weakest_questions_tie_broken_by_attempts_descending(engine_no_io):
    chapter = engine_no_io.CHAPTERS[0]
    # Both 0% accuracy; higher attempts should come first on ties.
    engine_no_io.question_stats[chapter] = {
        "0": {"attempts": 2, "correct": 0},
        "1": {"attempts": 5, "correct": 0},
    }
    result = engine_no_io.get_weakest_questions(n=2, min_attempts=1)
    assert result[0]["attempts"] >= result[1]["attempts"]
