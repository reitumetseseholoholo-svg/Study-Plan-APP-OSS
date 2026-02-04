import datetime
import types
import builtins
import json
from unittest import mock

import pytest

from studyplan_engine import StudyPlanEngine


@pytest.fixture
def engine_no_io(monkeypatch):
    # Prevent __init__ from performing any file I/O by stubbing load_data and migrate_pomodoro_log
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    eng = StudyPlanEngine()
    return eng


def test_constructor_sets_today_and_initial_structures(monkeypatch):
    # Freeze today's date
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 1)
    today = FakeDate(2026, 1, 1)
    monkeypatch.setattr(datetime, "date", FakeDate)

    # Avoid file I/O in init
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)

    eng = StudyPlanEngine()

    assert eng.exam_date == today
    assert isinstance(eng.competence, dict)
    assert set(eng.competence.keys()) == set(StudyPlanEngine.CHAPTERS)
    assert all(v == 0 for v in eng.competence.values())
    assert isinstance(eng.pomodoro_log, dict)
    assert eng.pomodoro_log.get("total_minutes") == 0
    assert eng.pomodoro_log.get("by_chapter") == {}


def test_competence_initialization_covers_all_chapters(engine_no_io):
    eng = engine_no_io
    assert set(eng.competence.keys()) == set(StudyPlanEngine.CHAPTERS)
    assert all(isinstance(v, (int, float)) for v in eng.competence.values())


def test_get_questions_known_and_unknown(engine_no_io):
    eng = engine_no_io

    # Known chapter returns a non-empty list matching QUESTIONS_DEFAULT
    chapter = "FM Function"
    qs = eng.get_questions(chapter)
    assert isinstance(qs, list)
    assert qs, "Expected non-empty questions list for known chapter"

    # Unknown chapter returns an empty list
    unknown_qs = eng.get_questions("Nonexistent Chapter")
    assert isinstance(unknown_qs, list)
    assert unknown_qs == []


def test_update_competence_applies_delta(engine_no_io):
    eng = engine_no_io
    chapter = StudyPlanEngine.CHAPTERS[0]
    start = eng.competence[chapter]

    eng.update_competence(chapter, +3)
    assert eng.competence[chapter] == start + 3

    eng.update_competence(chapter, -2)
    assert eng.competence[chapter] == start + 1


def test_get_overall_mastery_from_srs(engine_no_io):
    eng = engine_no_io
    # Clear all SRS data and set a controlled sample for one chapter
    for ch in StudyPlanEngine.CHAPTERS:
        eng.srs_data[ch] = []
    chapter = StudyPlanEngine.CHAPTERS[0]
    eng.srs_data[chapter] = [
        {"last_review": "2026-01-01", "interval": 21, "efactor": 2.5},
        {"last_review": "2026-01-01", "interval": 30, "efactor": 2.0},
        {"last_review": "2026-01-01", "interval": 5, "efactor": 2.5},
        {"last_review": None, "interval": 1, "efactor": 2.5},
    ]
    expected_mastery = 50.0

    overall = eng.get_overall_mastery()
    assert isinstance(overall, (int, float))
    assert abs(overall - expected_mastery) < 1e-9


def test_get_daily_plan_returns_requested_count(engine_no_io):
    eng = engine_no_io
    plan3 = eng.get_daily_plan(num_topics=3)
    assert isinstance(plan3, list)
    assert len(plan3) == 3
    assert set(plan3).issubset(set(StudyPlanEngine.CHAPTERS))

    plan5 = eng.get_daily_plan(num_topics=5)
    assert len(plan5) == 5
    assert set(plan5).issubset(set(StudyPlanEngine.CHAPTERS))

def test_toggle_completed_affects_is_completed(monkeypatch, engine_no_io):
    eng = engine_no_io
    today = datetime.date(2026, 1, 2)
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return today
    monkeypatch.setattr(datetime, "date", FakeDate)

    chapter = StudyPlanEngine.CHAPTERS[0]
    assert eng.is_completed(chapter) is False
    assert eng.toggle_completed(chapter) is True
    assert eng.is_completed(chapter) is True
    assert eng.toggle_completed(chapter) is False
    assert eng.is_completed(chapter) is False


def test_save_data_writes_json_structure(tmp_path, monkeypatch):
    # Prepare engine with no side effects and deterministic data
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)

    # Redirect DATA_FILE to temp path before init so module path resolution uses it
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    eng.pomodoro_log["total_minutes"] = 25

    # Intercept open to write to the tmp path normally
    eng.save_data()

    # Validate file contents
    with open(data_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    # Minimal expected keys and types
    for key in [
        "competence",
        "pomodoro_log",
        "srs_data",
        "exam_date",
        "study_days",
        "must_review",
        "study_hub_stats",
        "quiz_results",
        "progress_log",
        "availability",
        "completed_chapters",
        "completed_chapters_date",
    ]:
        assert key in payload

    assert payload["pomodoro_log"]["total_minutes"] == 25
    assert "FM Function" in payload["competence"]


def test_save_data_creates_and_prunes_rolling_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    eng.BACKUP_RETENTION = 5

    # First save creates data file; subsequent saves should create snapshots.
    for i in range(12):
        eng.pomodoro_log["total_minutes"] = i
        eng.save_data()

    backups_dir = tmp_path / "backups"
    assert backups_dir.exists()
    snapshots = [p for p in backups_dir.iterdir() if p.name.startswith("data.json.") and p.name.endswith(".bak")]
    assert snapshots, "Expected at least one rolling backup snapshot"
    assert len(snapshots) <= 5, "Expected rolling backups to be pruned to retention limit"


def test_select_srs_questions_avoids_recent_when_possible(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    total = len(eng.QUESTIONS.get(chapter, []))
    assert total >= 12

    # Make everything previously reviewed and not overdue to isolate cooldown behavior.
    eng.srs_data[chapter] = [
        {"last_review": datetime.date.today().isoformat(), "interval": 30, "efactor": 2.5}
        for _ in range(total)
    ]
    eng.must_review[chapter] = {}
    # Recent history contains first 12 indices (cooldown window for count=6 is 12).
    eng.quiz_recent[chapter] = list(range(12))

    picked = eng.select_srs_questions(chapter, count=6)
    assert len(picked) == 6
    # Should prefer non-cooldown questions when available.
    assert all(idx >= 12 for idx in picked)


def test_select_srs_questions_keeps_due_even_if_recent(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    total = len(eng.QUESTIONS.get(chapter, []))
    assert total >= 10

    eng.srs_data[chapter] = [
        {"last_review": datetime.date.today().isoformat(), "interval": 30, "efactor": 2.5}
        for _ in range(total)
    ]
    today_iso = datetime.date.today().isoformat()
    eng.must_review[chapter] = {"0": today_iso, "1": today_iso}
    eng.quiz_recent[chapter] = list(range(12))

    picked = eng.select_srs_questions(chapter, count=6)
    assert len(picked) == 6
    # Must-review questions should still be included despite cooldown.
    assert 0 in picked
    assert 1 in picked


def test_select_srs_questions_handles_corrupt_recent_history(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    total = len(eng.QUESTIONS.get(chapter, []))
    assert total >= 8

    eng.srs_data[chapter] = [
        {"last_review": datetime.date.today().isoformat(), "interval": 30, "efactor": 2.5}
        for _ in range(total)
    ]
    eng.must_review[chapter] = {}
    # Mix of garbage/non-int/out-of-range values should not break selection.
    eng.quiz_recent[chapter] = ["x", None, -5, 999999, {"bad": 1}, 0, 1, 2]

    picked = eng.select_srs_questions(chapter, count=5)
    assert len(picked) == 5
    assert all(isinstance(i, int) for i in picked)
    assert all(0 <= i < total for i in picked)


def test_import_data_snapshot_clamps_srs_to_question_count(tmp_path, monkeypatch):
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    chapter = "FM Function"
    q_count = len(eng.QUESTIONS.get(chapter, []))
    assert q_count > 0

    snapshot = {
        "competence": {chapter: 55},
        "srs_data": {
            chapter: [{"last_review": None, "interval": 1, "efactor": 2.5} for _ in range(q_count + 200)]
        },
        "study_days": [datetime.date.today().isoformat()],
    }
    snap_path = tmp_path / "snapshot.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f)

    result = eng.import_data_snapshot(str(snap_path))
    assert isinstance(result, dict)
    assert len(eng.srs_data[chapter]) == q_count
