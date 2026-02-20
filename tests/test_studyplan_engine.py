import datetime
import types
import builtins
import json
import sys
import os
from pathlib import Path
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


def test_cleanup_joblib_loky_runtime_is_idempotent(monkeypatch):
    calls = {"count": 0, "kwargs": []}
    created = {"count": 0}

    class _Executor:
        def shutdown(self, **kwargs):
            calls["count"] += 1
            calls["kwargs"].append(dict(kwargs))

    def _get_reusable_executor():
        created["count"] += 1
        return _Executor()

    fake_module = types.SimpleNamespace(_executor=_Executor(), get_reusable_executor=_get_reusable_executor)
    monkeypatch.setitem(sys.modules, "joblib.externals.loky.reusable_executor", fake_module)

    original_done = bool(getattr(StudyPlanEngine, "_LOKY_CLEANUP_DONE", False))
    try:
        StudyPlanEngine._LOKY_CLEANUP_DONE = False
        StudyPlanEngine._cleanup_joblib_loky_runtime()
        StudyPlanEngine._cleanup_joblib_loky_runtime()
    finally:
        StudyPlanEngine._LOKY_CLEANUP_DONE = original_done

    assert calls["count"] == 1
    assert created["count"] == 0
    assert calls["kwargs"]
    assert calls["kwargs"][0].get("wait") is False


def test_cleanup_joblib_loky_runtime_skips_when_no_executor(monkeypatch):
    created = {"count": 0}

    def _get_reusable_executor():
        created["count"] += 1
        return object()

    fake_module = types.SimpleNamespace(_executor=None, get_reusable_executor=_get_reusable_executor)
    monkeypatch.setitem(sys.modules, "joblib.externals.loky.reusable_executor", fake_module)

    original_done = bool(getattr(StudyPlanEngine, "_LOKY_CLEANUP_DONE", False))
    try:
        StudyPlanEngine._LOKY_CLEANUP_DONE = False
        StudyPlanEngine._cleanup_joblib_loky_runtime()
    finally:
        StudyPlanEngine._LOKY_CLEANUP_DONE = original_done

    assert created["count"] == 0


def test_shutdown_runtime_requests_blocking_loky_cleanup(monkeypatch):
    captured: dict[str, bool] = {}

    def _fake_cleanup(cls, wait_for_workers: bool = False):
        captured["wait_for_workers"] = bool(wait_for_workers)

    monkeypatch.setattr(
        StudyPlanEngine,
        "_cleanup_joblib_loky_runtime",
        classmethod(_fake_cleanup),
        raising=True,
    )

    engine = StudyPlanEngine.__new__(StudyPlanEngine)
    StudyPlanEngine.shutdown_runtime(engine)
    assert captured.get("wait_for_workers") is True


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


def test_match_chapter_low_confidence_logging_is_deduplicated(engine_no_io, monkeypatch):
    eng = engine_no_io
    logs: list[str] = []
    monkeypatch.setattr(
        builtins,
        "print",
        lambda *args, **_kwargs: logs.append(" ".join(str(a) for a in args)),
    )
    for _ in range(5):
        StudyPlanEngine._match_chapter(eng, "G")
    low_conf = [row for row in logs if "Low confidence match" in row]
    assert len(low_conf) == 1


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
    setattr(eng, "BACKUP_RETENTION", 5)

    # First save creates data file; subsequent saves should create snapshots.
    for i in range(12):
        eng.pomodoro_log["total_minutes"] = i
        eng.save_data()

    backups_dir = tmp_path / "backups"
    assert backups_dir.exists()
    snapshots = [p for p in backups_dir.iterdir() if p.name.startswith("data.json.") and p.name.endswith(".bak")]
    assert snapshots, "Expected at least one rolling backup snapshot"
    assert len(snapshots) <= 5, "Expected rolling backups to be pruned to retention limit"


def test_list_backup_snapshots_returns_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    eng.pomodoro_log["total_minutes"] = 1
    eng.save_data()
    eng.pomodoro_log["total_minutes"] = 2
    eng.save_data()
    eng.pomodoro_log["total_minutes"] = 3
    eng.save_data()

    rows = eng.list_backup_snapshots(limit=10)
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert all(isinstance(r, dict) for r in rows)
    assert all("path" in r and "name" in r and "modified" in r for r in rows)
    assert all(Path(str(r["path"])).exists() for r in rows)
    # list should be newest first by modified timestamp
    modified = [str(r.get("modified", "")) for r in rows]
    assert modified == sorted(modified, reverse=True)


def test_list_backup_snapshots_includes_legacy_bak(tmp_path, monkeypatch):
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    data_file.write_text('{"competence": {}}', encoding="utf-8")
    legacy = tmp_path / "data.json.bak"
    legacy.write_text('{"competence": {"FM Function": 9}}', encoding="utf-8")

    rows = eng.list_backup_snapshots(limit=5)
    names = [str(r.get("name", "")) for r in rows]
    assert "data.json.bak" in names


def test_load_data_auto_recovers_from_latest_snapshot(tmp_path, monkeypatch):
    real_load_data = StudyPlanEngine.load_data
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    chapter = "FM Function"
    eng.competence[chapter] = 37
    eng.save_data()  # Create primary file
    eng.save_data()  # Create rolling backup from previous primary file

    # Corrupt primary data file.
    data_file.write_text("{ this is not valid json", encoding="utf-8")
    eng.competence[chapter] = 0

    real_load_data(eng)
    assert eng.competence[chapter] == 37
    assert eng.last_load_recovered is True
    assert isinstance(eng.last_load_recovery_snapshot, str)
    assert eng.last_load_recovery_snapshot.endswith(".bak")
    # Recovery should have rewritten a valid primary file.
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert payload.get("competence", {}).get(chapter) == 37


def test_load_data_corrupt_without_snapshot_keeps_runtime_state(tmp_path, monkeypatch):
    real_load_data = StudyPlanEngine.load_data
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    chapter = "FM Function"
    eng.competence[chapter] = 11
    data_file.write_text("{ broken json", encoding="utf-8")

    real_load_data(eng)
    assert eng.competence[chapter] == 11
    assert eng.last_load_recovered is False


def test_load_data_recovery_flag_clears_after_successful_load(tmp_path, monkeypatch):
    real_load_data = StudyPlanEngine.load_data
    monkeypatch.setattr(StudyPlanEngine, "load_data", lambda self: None, raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)
    data_file = tmp_path / "data.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)

    eng = StudyPlanEngine()
    chapter = "FM Function"
    eng.competence[chapter] = 21
    eng.save_data()
    eng.save_data()
    data_file.write_text("{ broken", encoding="utf-8")
    eng.competence[chapter] = 0

    real_load_data(eng)
    assert eng.last_load_recovered is True

    # A clean subsequent load should clear recovery state.
    eng.competence[chapter] = 55
    eng.save_data()
    real_load_data(eng)
    assert eng.last_load_recovered is False
    assert eng.last_load_recovery_snapshot == ""
    assert eng.last_load_recovery_error == ""


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


def test_import_questions_json_reports_semantic_mapping_quality(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    monkeypatch.setattr(eng, "save_questions", lambda: None)
    monkeypatch.setattr(eng, "save_data", lambda: None)

    payload = {
        "chapter": "FM Function",
        "questions": [
            {
                "question": "Import semantic mapping question 1?",
                "options": ["A", "B", "C", "D"],
                "correct": "A",
                "explanation": "x",
            },
            {
                "question": "Import semantic mapping question 2?",
                "options": ["A", "B", "C", "D"],
                "correct": "B",
                "explanation": "y",
            },
        ],
    }
    path = tmp_path / "import_questions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    def _route(_chapter, idx):
        if idx % 2 == 0:
            return {
                "outcome_ids": ["A.1"],
                "semantic_match_confidence": 0.86,
                "semantic_match_method": "model",
                "reason": "semantic map from question text",
            }
        return {
            "outcome_ids": ["A.2"],
            "semantic_match_confidence": 0.33,
            "semantic_match_method": "tfidf",
            "reason": "semantic map from question text",
        }

    monkeypatch.setattr(eng, "resolve_question_outcomes", _route)
    result = eng.import_questions_json(str(path))
    assert result.get("added") == 2
    semantic = result.get("semantic_import", {})
    assert isinstance(semantic, dict)
    assert int(semantic.get("total_new", 0) or 0) == 2
    assert int(semantic.get("mapped", 0) or 0) == 1
    assert int(semantic.get("low_confidence", 0) or 0) == 1
    assert float(semantic.get("coverage_pct", 0.0) or 0.0) > 0.0


def test_import_questions_json_keeps_pretagged_outcomes(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    monkeypatch.setattr(eng, "save_questions", lambda: None)
    monkeypatch.setattr(eng, "save_data", lambda: None)

    payload = {
        "chapter": "FM Function",
        "questions": [
            {
                "question": "Pretagged outcome import question?",
                "options": ["A", "B", "C", "D"],
                "correct": "C",
                "explanation": "z",
                "outcome_ids": ["A.7"],
            }
        ],
    }
    path = tmp_path / "import_pretagged.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        eng,
        "resolve_question_outcomes",
        lambda *_args, **_kwargs: {
            "outcome_ids": ["A.1"],
            "semantic_match_confidence": 0.1,
            "semantic_match_method": "fallback",
            "reason": "stable deterministic fallback",
        },
    )

    result = eng.import_questions_json(str(path))
    semantic = result.get("semantic_import", {})
    assert int(semantic.get("mapped", 0) or 0) == 1
    assert int(semantic.get("pretagged", 0) or 0) == 1


def test_finalize_semantic_import_stats_flags_review_required(engine_no_io):
    eng = engine_no_io
    stats = eng._build_semantic_import_stats()
    stats.update(
        {
            "total_new": 10,
            "mapped": 3,
            "low_confidence": 2,
            "unmapped": 5,
            "outcome_counts": {"A.1": 3},
            "chapter_breakdown": {
                "FM Function": {
                    "total": 10,
                    "mapped": 3,
                    "low_confidence": 2,
                    "unmapped": 5,
                }
            },
        }
    )
    finalized = eng._finalize_semantic_import_stats(stats)
    assert bool(finalized.get("needs_review", False)) is True
    assert str(finalized.get("quality_band", "")) == "weak"
    reasons = finalized.get("review_reasons", [])
    assert isinstance(reasons, list)
    assert "low_coverage" in reasons
    assert "high_unmapped_ratio" in reasons
    alerts = finalized.get("chapter_alerts", [])
    assert isinstance(alerts, list)
    assert "FM Function" in alerts


def test_import_questions_json_counts_cross_method(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    monkeypatch.setattr(eng, "save_questions", lambda: None)
    monkeypatch.setattr(eng, "save_data", lambda: None)

    payload = {
        "chapter": "FM Function",
        "questions": [
            {
                "question": "Cross-method semantic import question?",
                "options": ["A", "B", "C", "D"],
                "correct": "A",
                "explanation": "x",
            }
        ],
    }
    path = tmp_path / "import_cross.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        eng,
        "resolve_question_outcomes",
        lambda *_args, **_kwargs: {
            "outcome_ids": ["A.1"],
            "semantic_match_confidence": 0.82,
            "semantic_match_method": "cross",
            "reason": "cross rerank",
        },
    )

    result = eng.import_questions_json(str(path))
    semantic = result.get("semantic_import", {})
    methods = semantic.get("method_counts", {})
    assert isinstance(methods, dict)
    assert int(methods.get("cross", 0) or 0) >= 1


def test_add_questions_semantic_dedup_skips_near_duplicates(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.QUESTIONS[chapter] = [
        {
            "question": "Which formula is used for weighted average cost of capital?",
            "options": ["A", "B", "C", "D"],
            "correct": "A",
            "explanation": "",
        }
    ]
    eng.srs_data[chapter] = [{"last_review": None, "interval": 1, "efactor": 2.5}]
    eng.IMPORT_SEMANTIC_DEDUP_MIN_SCORE = 0.90

    class FakeModel:
        def encode(self, texts, normalize_embeddings=True):
            vectors = []
            for raw in texts:
                t = str(raw).lower()
                if "weighted average cost of capital" in t or "wacc formula" in t:
                    vectors.append([1.0, 0.0])
                elif "investment appraisal" in t:
                    vectors.append([0.0, 1.0])
                else:
                    vectors.append([0.5, 0.5])
            return vectors

    monkeypatch.setattr(eng, "_semantic_get_model", lambda: FakeModel())

    incoming = [
        {
            "question": "What is the WACC formula?",
            "options": ["A", "B", "C", "D"],
            "correct": "B",
            "explanation": "",
        },
        {
            "question": "What is investment appraisal?",
            "options": ["A", "B", "C", "D"],
            "correct": "C",
            "explanation": "",
        },
    ]
    added, dedup = eng._add_questions_with_stats(chapter, incoming)
    assert added == 1
    assert int(dedup.get("checked", 0) or 0) >= 1
    assert int(dedup.get("skipped", 0) or 0) == 1
    assert str(dedup.get("method", "")) == "model"


def test_add_questions_semantic_dedup_fallback_when_model_unavailable(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.QUESTIONS[chapter] = [
        {
            "question": "Which formula is used for weighted average cost of capital?",
            "options": ["A", "B", "C", "D"],
            "correct": "A",
            "explanation": "",
        }
    ]
    eng.srs_data[chapter] = [{"last_review": None, "interval": 1, "efactor": 2.5}]
    monkeypatch.setattr(eng, "_semantic_get_model", lambda: None)

    incoming = [
        {
            "question": "What is the WACC formula?",
            "options": ["A", "B", "C", "D"],
            "correct": "B",
            "explanation": "",
        }
    ]
    added, dedup = eng._add_questions_with_stats(chapter, incoming)
    assert added == 1
    assert int(dedup.get("skipped", 0) or 0) == 0
    assert bool(dedup.get("enabled", False)) is False


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


def test_restart_preserves_learning_cards_for_json_added_questions(tmp_path, monkeypatch):
    chapter = "FM Function"
    base_count = len(StudyPlanEngine.QUESTIONS_DEFAULT.get(chapter, []))
    assert base_count > 0

    data_file = tmp_path / "data.json"
    questions_file = tmp_path / "questions.json"
    monkeypatch.setattr(StudyPlanEngine, "DATA_FILE", str(data_file), raising=True)
    monkeypatch.setattr(StudyPlanEngine, "QUESTIONS_FILE", str(questions_file), raising=True)
    monkeypatch.setattr(StudyPlanEngine, "migrate_pomodoro_log", lambda self: None, raising=True)

    extra_questions = [
        {"question": "Extra Q1", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": ""},
        {"question": "Extra Q2", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": ""},
    ]
    questions_file.write_text(json.dumps({chapter: extra_questions}), encoding="utf-8")

    srs_rows = [{"last_review": None, "interval": 1, "efactor": 2.5} for _ in range(base_count)]
    srs_rows.extend(
        [
            {"last_review": "2026-02-01", "interval": 5, "efactor": 2.2},
            {"last_review": "2026-02-02", "interval": 4, "efactor": 2.1},
        ]
    )
    payload = {
        "competence": {chapter: 55.0},
        "pomodoro_log": {"total_minutes": 0.0, "by_chapter": {}},
        "srs_data": {chapter: srs_rows},
        "study_days": [],
    }
    data_file.write_text(json.dumps(payload), encoding="utf-8")

    eng = StudyPlanEngine(default_exam_date_to_today=False)
    stats = eng.get_mastery_stats(chapter)
    assert int(stats.get("total", 0) or 0) == base_count + 2
    assert int(stats.get("learning", 0) or 0) == 2
    assert int(stats.get("new", 0) or 0) == base_count
    assert eng.srs_data.get(chapter, [])[-1].get("last_review") == "2026-02-02"


def test_select_leech_questions_targets_low_accuracy_recent_items(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    assert len(eng.QUESTIONS.get(chapter, [])) >= 3
    today = datetime.date.today().isoformat()
    eng.question_stats[chapter] = {
        "0": {"attempts": 8, "correct": 2, "streak": 0, "last_seen": today},  # leech
        "1": {"attempts": 8, "correct": 7, "streak": 2, "last_seen": today},  # too accurate
        "2": {"attempts": 6, "correct": 1, "streak": 0, "last_seen": today},  # leech
    }

    picked = eng.select_leech_questions(chapter, count=3)
    assert picked
    assert 1 not in picked
    assert any(i in picked for i in (0, 2))


def test_select_leech_questions_prefers_non_recent(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    assert len(eng.QUESTIONS.get(chapter, [])) >= 2
    today = datetime.date.today().isoformat()
    eng.question_stats[chapter] = {
        "0": {"attempts": 7, "correct": 1, "streak": 0, "last_seen": today},
        "1": {"attempts": 7, "correct": 1, "streak": 0, "last_seen": today},
    }
    eng.quiz_recent[chapter] = [0]

    picked = eng.select_leech_questions(chapter, count=1)
    assert picked == [1]


def test_load_recall_model_sklearn_rejects_bad_feature_count(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    model = types.SimpleNamespace(predict_proba=lambda X: [[0.4, 0.6] for _ in X])
    payload = {"model": model, "meta": {"feature_count": 999}}
    fake_joblib = types.SimpleNamespace(load=lambda _path: payload)
    monkeypatch.setitem(sys.modules, "joblib", fake_joblib)

    pkl = tmp_path / "recall_model.pkl"
    pkl.write_text("x", encoding="utf-8")
    eng.recall_model_sklearn_path = str(pkl)
    eng._load_recall_model_sklearn()

    assert eng.recall_model_sklearn is None


def test_load_recall_model_sklearn_blocks_low_auc(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    model = types.SimpleNamespace(predict_proba=lambda X: [[0.3, 0.7] for _ in X])
    payload = {
        "model": model,
        "meta": {"feature_count": 5, "metrics": {"auc": 0.50, "ece": 0.10}},
    }
    fake_joblib = types.SimpleNamespace(load=lambda _path: payload)
    monkeypatch.setitem(sys.modules, "joblib", fake_joblib)

    pkl = tmp_path / "recall_model.pkl"
    pkl.write_text("x", encoding="utf-8")
    eng.recall_model_sklearn_path = str(pkl)
    eng._load_recall_model_sklearn()

    assert eng.recall_model_sklearn is None
    assert isinstance(eng.recall_model_sklearn_block_reason, str)
    assert "auc" in eng.recall_model_sklearn_block_reason


def test_load_recall_model_sklearn_allows_good_metrics(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    model = types.SimpleNamespace(predict_proba=lambda X: [[0.3, 0.7] for _ in X])
    payload = {
        "model": model,
        "meta": {"feature_count": 5, "metrics": {"auc": 0.72, "ece": 0.08}},
    }
    fake_joblib = types.SimpleNamespace(load=lambda _path: payload)
    monkeypatch.setitem(sys.modules, "joblib", fake_joblib)

    pkl = tmp_path / "recall_model.pkl"
    pkl.write_text("x", encoding="utf-8")
    eng.recall_model_sklearn_path = str(pkl)
    eng._load_recall_model_sklearn()

    assert eng.recall_model_sklearn is not None
    assert eng.recall_model_sklearn_block_reason is None


def test_predict_recall_prob_requires_chapter_ml_confidence(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    today = datetime.date.today().isoformat()
    eng.recall_model_sklearn = types.SimpleNamespace(predict_proba=lambda X: [[0.2, 0.8] for _ in X])
    eng.recall_model_sklearn_meta = {"feature_count": 5}
    eng.recall_model_json = None

    eng.ML_MIN_SAMPLES = 1
    eng.ML_MIN_ATTEMPTS = 1
    eng.ML_MIN_CHAPTER_SAMPLES = 6
    eng.ML_MIN_CHAPTER_COVERAGE = 0.20
    eng.ML_MIN_CHAPTER_CONFIDENCE = 0.70

    eng.question_stats[chapter] = {
        "0": {"attempts": 3, "correct": 2, "streak": 1, "avg_time_sec": 20, "last_seen": today}
    }
    assert eng.predict_recall_prob(chapter, 0) is None

    expanded = {}
    for idx in range(min(12, len(eng.QUESTIONS.get(chapter, [])))):
        expanded[str(idx)] = {
            "attempts": 3,
            "correct": 2,
            "streak": 1,
            "avg_time_sec": 20,
            "last_seen": today,
        }
    eng.question_stats[chapter] = expanded
    prob = eng.predict_recall_prob(chapter, 0)
    assert prob is not None
    assert 0.0 <= prob <= 1.0


def test_get_question_difficulty_falls_back_when_chapter_ml_not_ready(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    today = datetime.date.today().isoformat()
    eng.difficulty_model = {
        "model": types.SimpleNamespace(predict=lambda X: [1 for _ in X]),
        "label_map": {1: "hard"},
    }

    eng.ML_MIN_SAMPLES = 1
    eng.ML_MIN_ATTEMPTS = 1
    eng.ML_MIN_CHAPTER_SAMPLES = 10
    eng.ML_MIN_CHAPTER_COVERAGE = 0.50
    eng.ML_MIN_CHAPTER_CONFIDENCE = 0.90
    eng.question_stats[chapter] = {
        "0": {"attempts": 1, "correct": 1, "streak": 1, "avg_time_sec": 10, "last_seen": today}
    }

    assert eng.get_question_difficulty(chapter, 0) == "easy"

    eng.ML_MIN_CHAPTER_SAMPLES = 1
    eng.ML_MIN_CHAPTER_COVERAGE = 0.01
    eng.ML_MIN_CHAPTER_CONFIDENCE = 0.10
    assert eng.get_question_difficulty(chapter, 0) == "hard"


def test_get_chapter_ml_status_reports_readiness(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    today = datetime.date.today().isoformat()

    eng.ML_MIN_SAMPLES = 1
    eng.ML_MIN_CHAPTER_SAMPLES = 4
    eng.ML_MIN_CHAPTER_COVERAGE = 0.10
    eng.ML_MIN_CHAPTER_CONFIDENCE = 0.50

    eng.question_stats[chapter] = {
        "0": {"attempts": 3, "correct": 2, "streak": 1, "avg_time_sec": 12, "last_seen": today}
    }
    low = eng.get_chapter_ml_status(chapter)
    assert low["ready"] is False
    assert low["sample_count"] == 1
    assert 0.0 <= float(low["confidence"]) <= 1.0

    expanded = {}
    for idx in range(min(10, len(eng.QUESTIONS.get(chapter, [])))):
        expanded[str(idx)] = {
            "attempts": 3,
            "correct": 2,
            "streak": 1,
            "avg_time_sec": 12,
            "last_seen": today,
        }
    eng.question_stats[chapter] = expanded
    high = eng.get_chapter_ml_status(chapter)
    assert high["ready"] is True
    assert int(high["sample_count"]) >= 4
    assert 0.0 <= float(high["coverage"]) <= 1.0


def test_import_syllabus_from_sparse_text_returns_fallback_draft(engine_no_io):
    eng = engine_no_io
    sparse_text = "This is a scanned syllabus extract with weak structure and no explicit section headers."
    result = eng.import_syllabus_from_pdf_text(sparse_text, module_id="acca_sparse")
    assert isinstance(result, dict)
    config = result.get("config", {})
    assert isinstance(config, dict)
    chapters = config.get("chapters", [])
    assert isinstance(chapters, list)
    assert len(chapters) >= 1
    diagnostics = result.get("diagnostics", {})
    warnings = diagnostics.get("warnings", []) if isinstance(diagnostics, dict) else []
    assert isinstance(warnings, list)
    # Local model artifacts may exist on developer machines; ensure this test
    # remains focused on syllabus fallback behavior only.
    meta = getattr(eng, "recall_model_sklearn_meta", None)
    assert meta is None or isinstance(meta, dict)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "syllabus"


@pytest.mark.parametrize(
    ("fixture_name", "min_chapters", "min_confidence", "expect_warning"),
    [
        ("clean_fm_like.txt", 8, 0.70, False),
        ("ocr_noisy_fm_like.txt", 6, 0.30, False),
        ("sparse_extract.txt", 1, 0.00, True),
    ],
)
def test_import_syllabus_fixture_regression(
    engine_no_io,
    fixture_name,
    min_chapters,
    min_confidence,
    expect_warning,
):
    eng = engine_no_io
    fixture_path = FIXTURE_DIR / fixture_name
    text = fixture_path.read_text(encoding="utf-8")

    result = eng.import_syllabus_from_pdf_text(text, module_id=f"acca_{fixture_name.split('.')[0]}")

    assert isinstance(result, dict)
    config = result.get("config", {})
    assert isinstance(config, dict)
    chapters = config.get("chapters", [])
    assert isinstance(chapters, list)
    assert len(chapters) >= min_chapters

    diagnostics = result.get("diagnostics", {})
    assert isinstance(diagnostics, dict)
    confidence = float(diagnostics.get("confidence", 0.0) or 0.0)
    assert 0.0 <= confidence <= 1.0
    assert confidence >= min_confidence

    warnings = diagnostics.get("warnings", [])
    assert isinstance(warnings, list)
    if expect_warning:
        assert warnings


def test_parse_syllabus_cache_returns_independent_copy(engine_no_io):
    eng = engine_no_io
    first = eng.parse_syllabus_pdf_text(SAMPLE_SYLLABUS_TEXT)
    assert isinstance(first, dict)
    assert len(eng._syllabus_parse_cache) == 1

    first_warnings = first.get("warnings", [])
    assert isinstance(first_warnings, list)
    first_warnings.append("mutated in test")

    second = eng.parse_syllabus_pdf_text(SAMPLE_SYLLABUS_TEXT)
    second_warnings = second.get("warnings", [])
    assert isinstance(second_warnings, list)
    assert "mutated in test" not in second_warnings


def test_parse_syllabus_cache_is_bounded(engine_no_io):
    eng = engine_no_io
    limit = int(eng.SYLLABUS_PARSE_CACHE_MAX)
    for idx in range(limit + 5):
        payload = (
            "2. Main capabilities\n"
            f"A Capability {idx}\n"
            "4. The syllabus\n"
            f"A Capability {idx}\n"
            "5. Detailed study guide\n"
            f"A Capability {idx}\n"
            "a) Explain the capability.[2]\n"
            "6. Summary of changes\n"
        )
        parsed = eng.parse_syllabus_pdf_text(payload)
        assert isinstance(parsed, dict)
    assert len(eng._syllabus_parse_cache) <= limit
    assert len(eng._syllabus_parse_cache_order) <= limit


def test_import_syllabus_cache_skips_reparse_and_returns_copy(engine_no_io, monkeypatch):
    eng = engine_no_io
    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []
    parse_calls = 0
    original_parse = eng.parse_syllabus_pdf_text

    def _wrapped_parse(text):
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(text)

    monkeypatch.setattr(eng, "parse_syllabus_pdf_text", _wrapped_parse)

    first = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    second = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")

    assert parse_calls == 1
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    second_perf = second.get("diagnostics", {}).get("perf", {})
    assert isinstance(second_perf, dict)
    assert second_perf.get("import_cache_hit") is True

    first_warnings = first.get("diagnostics", {}).get("warnings", [])
    assert isinstance(first_warnings, list)
    first_warnings.append("mutated in test")

    third = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    third_warnings = third.get("diagnostics", {}).get("warnings", [])
    assert isinstance(third_warnings, list)
    assert "mutated in test" not in third_warnings


def test_import_syllabus_cache_is_bounded(engine_no_io):
    eng = engine_no_io
    limit = int(eng.SYLLABUS_IMPORT_CACHE_MAX)
    for idx in range(limit + 4):
        payload = (
            "2. Main capabilities\n"
            f"A Capability {idx}\n"
            "4. The syllabus\n"
            f"A Capability {idx}\n"
            "5. Detailed study guide\n"
            f"A Capability {idx}\n"
            "a) Explain the capability.[2]\n"
            "6. Summary of changes\n"
        )
        parsed = eng.import_syllabus_from_pdf_text(payload, module_id=f"acca_cache_{idx}")
        assert isinstance(parsed, dict)
    assert len(eng._syllabus_import_cache) <= limit
    assert len(eng._syllabus_import_cache_order) <= limit


def test_import_syllabus_exposes_perf_diagnostics(engine_no_io):
    eng = engine_no_io
    result = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    diagnostics = result.get("diagnostics", {})
    assert isinstance(diagnostics, dict)
    perf = diagnostics.get("perf", {})
    assert isinstance(perf, dict)
    for key in ("import_cache_hit", "parse_cache_hit", "parse_ms", "build_ms", "validate_ms", "total_ms"):
        assert key in perf
    assert perf.get("import_cache_hit") is False


def test_import_syllabus_disk_cache_roundtrip(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    eng.syllabus_import_cache_file = str(tmp_path / "syllabus_import_cache.json")
    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []

    first = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    assert isinstance(first, dict)
    assert os.path.exists(eng.syllabus_import_cache_file)

    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []
    eng._load_syllabus_import_cache_disk()
    assert eng._syllabus_import_cache

    def _should_not_parse(_text):
        raise AssertionError("parse_syllabus_pdf_text should not run on disk-cache hit")

    monkeypatch.setattr(eng, "parse_syllabus_pdf_text", _should_not_parse)
    second = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    perf = second.get("diagnostics", {}).get("perf", {})
    assert isinstance(perf, dict)
    assert perf.get("import_cache_hit") is True


def test_import_syllabus_disk_cache_rejects_signature_mismatch(engine_no_io, tmp_path):
    eng = engine_no_io
    eng.syllabus_import_cache_file = str(tmp_path / "syllabus_import_cache.json")
    key = "acca_f9:abc:def"
    payload = {
        "schema_version": int(eng.SYLLABUS_IMPORT_CACHE_SCHEMA_VERSION),
        "parser_signature": "different_signature",
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "order": [key],
        "cache": {
            key: {
                "cached_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "result": {"module_id": "acca_f9", "diagnostics": {"confidence": 0.5}},
            }
        },
    }
    with open(eng.syllabus_import_cache_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)

    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []
    eng._load_syllabus_import_cache_disk()
    assert eng._syllabus_import_cache == {}
    assert eng._syllabus_import_cache_order == []


def test_import_syllabus_disk_cache_rejects_stale_entries(engine_no_io, tmp_path):
    eng = engine_no_io
    eng.syllabus_import_cache_file = str(tmp_path / "syllabus_import_cache.json")
    old_date = (datetime.datetime.now() - datetime.timedelta(days=eng.SYLLABUS_IMPORT_CACHE_MAX_AGE_DAYS + 2)).isoformat(
        timespec="seconds"
    )
    key = "acca_f9:abc:def"
    payload = {
        "schema_version": int(eng.SYLLABUS_IMPORT_CACHE_SCHEMA_VERSION),
        "parser_signature": str(eng.SYLLABUS_PARSER_SIGNATURE),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "order": [key],
        "cache": {
            key: {
                "cached_at": old_date,
                "result": {"module_id": "acca_f9", "diagnostics": {"confidence": 0.5}},
            }
        },
    }
    with open(eng.syllabus_import_cache_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)

    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []
    eng._load_syllabus_import_cache_disk()
    assert eng._syllabus_import_cache == {}
    assert eng._syllabus_import_cache_order == []


def test_syllabus_cache_stats_and_clear(engine_no_io, tmp_path):
    eng = engine_no_io
    eng.syllabus_import_cache_file = str(tmp_path / "syllabus_import_cache.json")
    eng._syllabus_parse_cache = {}
    eng._syllabus_parse_cache_order = []
    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []

    result = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    assert isinstance(result, dict)

    stats_before = eng.get_syllabus_import_cache_stats()
    assert int(stats_before.get("memory_import_entries", 0) or 0) >= 1
    assert bool(stats_before.get("disk_exists", False)) is True
    assert int(stats_before.get("disk_entries", 0) or 0) >= 1

    cleared = eng.clear_syllabus_import_cache(clear_disk=True)
    assert int(cleared.get("cleared_import_entries", 0) or 0) >= 1

    stats_after = eng.get_syllabus_import_cache_stats()
    assert int(stats_after.get("memory_parse_entries", 0) or 0) == 0
    assert int(stats_after.get("memory_import_entries", 0) or 0) == 0
    assert bool(stats_after.get("disk_exists", False)) is False


def test_syllabus_cache_metrics_track_hits_and_misses(engine_no_io):
    eng = engine_no_io
    eng._syllabus_parse_cache = {}
    eng._syllabus_parse_cache_order = []
    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []
    eng._syllabus_cache_metrics = {
        "parse_hits": 0,
        "parse_misses": 0,
        "import_hits": 0,
        "import_misses": 0,
    }

    _ = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    _ = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")

    stats = eng.get_syllabus_import_cache_stats()
    assert int(stats.get("parse_misses", 0) or 0) >= 1
    assert int(stats.get("import_misses", 0) or 0) >= 1
    assert int(stats.get("import_hits", 0) or 0) >= 1
    assert 0.0 <= float(stats.get("parse_hit_rate", 0.0) or 0.0) <= 1.0
    assert 0.0 <= float(stats.get("import_hit_rate", 0.0) or 0.0) <= 1.0

    cleared = eng.clear_syllabus_import_cache(clear_disk=False)
    assert int(cleared.get("cleared_parse_hits", 0) or 0) >= 0
    assert int(cleared.get("cleared_import_hits", 0) or 0) >= 0
    stats_after = eng.get_syllabus_import_cache_stats()
    assert int(stats_after.get("parse_hits", 0) or 0) == 0
    assert int(stats_after.get("parse_misses", 0) or 0) == 0
    assert int(stats_after.get("import_hits", 0) or 0) == 0
    assert int(stats_after.get("import_misses", 0) or 0) == 0


def test_syllabus_cache_metrics_persist_to_disk(engine_no_io, tmp_path):
    eng = engine_no_io
    eng.syllabus_import_cache_file = str(tmp_path / "syllabus_import_cache.json")
    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []
    eng._syllabus_cache_metrics = {
        "parse_hits": 7,
        "parse_misses": 3,
        "import_hits": 5,
        "import_misses": 4,
    }

    # Ensure there is at least one cache entry so disk payload is produced in a normal path.
    _ = eng.import_syllabus_from_pdf_text(SAMPLE_SYLLABUS_TEXT, module_id="acca_f9")
    eng._save_syllabus_import_cache_disk()

    eng._syllabus_cache_metrics = {
        "parse_hits": 0,
        "parse_misses": 0,
        "import_hits": 0,
        "import_misses": 0,
    }
    eng._syllabus_import_cache = {}
    eng._syllabus_import_cache_order = []
    eng._load_syllabus_import_cache_disk()

    stats = eng.get_syllabus_import_cache_stats()
    assert int(stats.get("parse_hits", 0) or 0) >= 7
    assert int(stats.get("parse_misses", 0) or 0) >= 3
    assert int(stats.get("import_hits", 0) or 0) >= 5
    assert int(stats.get("import_misses", 0) or 0) >= 4


def test_load_recall_model_sklearn_accepts_matching_feature_count(engine_no_io, monkeypatch, tmp_path):
    eng = engine_no_io
    model = types.SimpleNamespace(predict_proba=lambda X: [[0.3, 0.7] for _ in X])
    payload = {"model": model, "meta": {"feature_count": eng.RECALL_FEATURE_COUNT}}
    fake_joblib = types.SimpleNamespace(load=lambda _path: payload)
    monkeypatch.setitem(sys.modules, "joblib", fake_joblib)

    pkl = tmp_path / "recall_model.pkl"
    pkl.write_text("x", encoding="utf-8")
    eng.recall_model_sklearn_path = str(pkl)
    eng._load_recall_model_sklearn()

    assert eng.recall_model_sklearn is model
    assert isinstance(eng.recall_model_sklearn_meta, dict)
    assert int(eng.recall_model_sklearn_meta.get("feature_count", 0)) == eng.RECALL_FEATURE_COUNT


SAMPLE_SYLLABUS_TEXT = """
2. Main capabilities
A Discuss the role and purpose of the financial management function
B Assess and discuss the impact of the economic environment on financial management
C Discuss and apply working capital management techniques
D Carry out effective investment appraisal
E Identify and evaluate alternative sources of business finance
F Discuss and apply principles of business and asset valuations
G Explain and apply risk management techniques in business
H Demonstrate employability and technology skills
3. Intellectual levels
4. The syllabus
A Financial management function
1. The nature and purpose of financial management
2. Financial objectives and relationship with corporate strategy
B Financial management environment
1. The economic environment for business
2. The nature and role of financial markets and institutions
C Working capital management
1. The nature, elements and importance of working capital
2. Management of inventories, accounts receivable, accounts payable and cash
D Investment appraisal
1. Investment appraisal techniques
2. Allowing for inflation and taxation in DCF
E Business finance
1. Sources of business finance
2. Estimating the cost of capital
F Business and asset valuations
1. Nature and purpose of valuation
G Risk management
1. Nature and types of risk
H Employability and technology skills
1. Use technology effectively in exam responses
5. Detailed study guide
A Financial management function
a) Explain the nature and purpose of financial management.[1]
b) Discuss the relationship between financial objectives and strategy.[2]
B Financial management environment
a) Explain the role of financial markets and institutions.[2]
C Working capital management
a) Apply inventory and receivables management techniques.[2]
b) Evaluate working capital funding strategies.[2]
D Investment appraisal
a) Apply DCF techniques in investment appraisal.[2]
b) Evaluate risk and uncertainty in investment decisions.[3]
E Business finance
a) Identify and evaluate alternative sources of finance.[2]
F Business and asset valuations
a) Discuss and apply valuation principles to business assets.[3]
G Risk management
a) Explain and apply risk management techniques.[2]
H Employability and technology skills
a) Present data and information effectively in digital exam tools.[1]
6. Summary of changes
"""


def test_syllabus_parser_extracts_capabilities_from_fm_text(engine_no_io):
    eng = engine_no_io
    parsed = eng.parse_syllabus_pdf_text(SAMPLE_SYLLABUS_TEXT)
    capabilities = parsed.get("capabilities", {})
    assert isinstance(capabilities, dict)
    assert len(capabilities) == 8
    assert capabilities.get("A", "").startswith("Discuss the role")
    assert capabilities.get("H", "").startswith("Demonstrate employability")


def test_syllabus_parser_extracts_chapters_and_flow(engine_no_io):
    eng = engine_no_io
    parsed = eng.parse_syllabus_pdf_text(SAMPLE_SYLLABUS_TEXT)
    built = eng.build_module_config_from_syllabus(parsed, base_config={"title": "FM"})
    chapter_flow = built.get("chapter_flow", {})
    chapters = built.get("chapters", [])
    assert isinstance(chapters, list)
    assert len(chapters) == 8
    assert chapters[0].startswith("A.")
    assert chapters[-1].startswith("H.")
    assert chapter_flow.get(chapters[0]) == [chapters[1]]


def test_syllabus_parser_extracts_outcomes_and_levels(engine_no_io):
    eng = engine_no_io
    parsed = eng.parse_syllabus_pdf_text(SAMPLE_SYLLABUS_TEXT)
    structure = parsed.get("syllabus_structure", {})
    assert isinstance(structure, dict)
    chapter_d = next((ch for ch in structure.keys() if ch.startswith("D.")), None)
    assert isinstance(chapter_d, str)
    info = structure[chapter_d]
    outcomes = info.get("learning_outcomes", [])
    assert isinstance(outcomes, list)
    assert outcomes
    levels = [int(item.get("level", 0)) for item in outcomes if isinstance(item, dict)]
    assert 2 in levels
    assert 3 in levels


def test_weight_derivation_is_deterministic_and_bounded(engine_no_io):
    eng = engine_no_io
    parsed = eng.parse_syllabus_pdf_text(SAMPLE_SYLLABUS_TEXT)
    built_a = eng.build_module_config_from_syllabus(parsed, base_config={"title": "FM"})
    built_b = eng.build_module_config_from_syllabus(parsed, base_config={"title": "FM"})
    w_a = built_a.get("importance_weights", {})
    w_b = built_b.get("importance_weights", {})
    assert w_a == w_b
    assert isinstance(w_a, dict)
    assert w_a
    assert all(5 <= int(v) <= 40 for v in w_a.values())


def test_build_module_config_preserves_existing_questions(engine_no_io):
    eng = engine_no_io
    parsed = eng.parse_syllabus_pdf_text(SAMPLE_SYLLABUS_TEXT)
    base = {
        "title": "FM",
        "questions": {
            "A. Discuss the role and purpose of the financial management function": [
                {
                    "question": "Q?",
                    "options": ["A", "B"],
                    "correct": "A",
                    "explanation": "",
                }
            ]
        },
    }
    built = eng.build_module_config_from_syllabus(parsed, base_config=base)
    assert "questions" in built
    assert isinstance(built["questions"], dict)
    assert built["questions"]


def test_low_confidence_parse_returns_warnings(engine_no_io):
    eng = engine_no_io
    parsed = eng.parse_syllabus_pdf_text("Financial Management syllabus overview only.")
    warnings = parsed.get("warnings", [])
    assert isinstance(warnings, list)
    assert warnings
    assert float(parsed.get("confidence", 1.0)) < 0.5


def test_semantic_status_defaults_to_unloaded(engine_no_io):
    eng = engine_no_io
    status = eng.get_semantic_status()
    assert isinstance(status, dict)
    assert status.get("enabled") is True
    assert status.get("state") == "unloaded"
    assert status.get("active") is False
    assert isinstance(status.get("model_name"), str)
    assert int(status.get("alias_count_total", 0) or 0) >= int(status.get("built_in_alias_count", 0) or 0)


def test_semantic_status_reports_module_alias_counts(engine_no_io):
    eng = engine_no_io
    eng.semantic_aliases = {
        "fs analytics": "financial statement analysis",
        "FM Function": {
            "fm fn": "financial management function",
            "corp obj": "corporate objectives",
        },
    }
    status = eng.get_semantic_status()
    assert int(status.get("module_global_alias_count", 0) or 0) == 1
    assert int(status.get("module_chapter_alias_count", 0) or 0) == 2
    assert int(status.get("alias_count_total", 0) or 0) >= 3


def test_semantic_warmup_respects_disabled_flag(engine_no_io):
    eng = engine_no_io
    eng.semantic_enabled = False
    status = eng.warmup_semantic_model(force=True)
    assert status.get("enabled") is False
    assert status.get("state") == "disabled"
    assert status.get("active") is False


def test_semantic_warmup_blocks_when_sentence_transformers_missing(engine_no_io, monkeypatch):
    eng = engine_no_io

    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentence_transformers":
            raise ImportError("simulated missing dependency")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    status = eng.warmup_semantic_model(force=True)
    assert status.get("state") == "blocked"
    assert status.get("active") is False
    reason = str(status.get("block_reason", "") or "")
    assert "unavailable" in reason or "failed" in reason


def test_question_outcome_ids_prefers_semantic_mapping(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    outcome_id = "a.1"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": outcome_id, "text": "Explain the role and purpose of financial management", "level": 1}
            ],
        }
    }

    monkeypatch.setattr(eng, "_semantic_best_outcome_id", lambda *_args, **_kwargs: outcome_id)
    resolved = eng._question_outcome_ids(chapter, 0)
    assert resolved == [outcome_id]


def test_semantic_cache_is_bounded(engine_no_io):
    eng = engine_no_io
    eng.SEMANTIC_CACHE_MAX = 3
    for idx in range(6):
        eng._semantic_cache_set(f"k{idx}", f"v{idx}", "fallback", 1.0)
    assert len(eng._semantic_match_cache_order) <= 3
    assert len(eng._semantic_match_cache) <= 3


def test_semantic_tfidf_assets_reused_on_repeated_queries(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    outcome_lookup = {
        "A.1": {"text": "Explain the role and purpose of financial management"},
        "A.2": {"text": "Discuss financial objectives and policy choices"},
    }
    monkeypatch.setattr(eng, "_semantic_get_model", lambda: None)
    monkeypatch.setattr(eng, "_semantic_get_reranker", lambda: None)
    eng.semantic_min_score = 0.30

    first = eng._semantic_best_outcome_match(chapter, "What is the role of financial management?", outcome_lookup)
    second = eng._semantic_best_outcome_match(chapter, "How do policy choices affect financial objectives?", outcome_lookup)
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    stats = eng.get_semantic_perf_stats()
    assert int(stats.get("tfidf_asset_misses", 0) or 0) >= 1
    assert int(stats.get("tfidf_asset_hits", 0) or 0) >= 1
    assert chapter in eng._semantic_chapter_match_assets


def test_prefetch_question_route_meta_populates_cache(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Explain the role and purpose of financial management", "level": 1},
                {"id": "A.2", "text": "Discuss financial objectives and policy choices", "level": 2},
            ],
        }
    }
    monkeypatch.setattr(eng, "_semantic_get_model", lambda: None)
    monkeypatch.setattr(eng, "_semantic_get_reranker", lambda: None)
    eng.prefetch_question_route_meta(chapter, [0, 1, 2])
    stats = eng.get_semantic_perf_stats()
    assert int(stats.get("route_meta_calls", 0) or 0) >= 1
    assert bool(eng._semantic_match_cache)


def test_resolve_question_outcomes_semantic_disabled_skips_semantic_route(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Explain the role and purpose of financial management", "level": 1},
                {"id": "A.2", "text": "Discuss financial objectives and policy choices", "level": 2},
            ],
        }
    }
    eng.semantic_enabled = False

    def _should_not_run(*_args, **_kwargs):
        raise AssertionError("semantic matcher should not run while semantic routing is disabled")

    monkeypatch.setattr(eng, "_semantic_best_outcome_match", _should_not_run)
    route = eng.resolve_question_outcomes(chapter, 0)
    assert isinstance(route, dict)
    assert str(route.get("semantic_match_method", "")) == "fallback"
    stats = eng.get_semantic_perf_stats()
    assert int(stats.get("route_meta_calls", 0) or 0) == 0


def test_resolve_question_outcomes_exposes_semantic_metadata(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    outcome_id = "A.1"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": outcome_id, "text": "Explain the purpose of financial management", "level": 1}
            ],
        }
    }

    monkeypatch.setattr(
        eng,
        "_semantic_best_outcome_match",
        lambda *_args, **_kwargs: {"outcome_id": outcome_id, "score": 0.82, "method": "model"},
    )
    route = eng.resolve_question_outcomes(chapter, 0)
    assert route.get("outcome_ids") == [outcome_id]
    assert route.get("semantic_match_method") == "model"
    assert float(route.get("semantic_match_confidence", 0.0) or 0.0) >= 0.80


def test_semantic_best_outcome_match_uses_cross_reranker(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    outcome_lookup = {
        "A.1": {"text": "Explain the role and purpose of financial management"},
        "A.2": {"text": "Assess strategic financial objectives in business context"},
    }
    text = "How do strategic financial objectives guide management decisions?"

    class FakeDense:
        def encode(self, texts, normalize_embeddings=True):
            rows = []
            for i, _ in enumerate(texts):
                if i == 0:
                    rows.append([1.0, 0.0])
                elif i == 1:
                    rows.append([0.95, 0.05])  # dense rank winner before rerank
                else:
                    rows.append([0.10, 0.90])  # dense rank loser before rerank
            return rows

    class FakeCross:
        def predict(self, pairs):
            # Reranker flips priority to second candidate.
            return [0.15, 0.88][: len(pairs)]

    monkeypatch.setattr(eng, "_semantic_get_model", lambda: FakeDense())
    monkeypatch.setattr(eng, "_semantic_get_reranker", lambda: FakeCross())
    eng.semantic_min_score = 0.30

    match = eng._semantic_best_outcome_match(chapter, text, outcome_lookup)
    assert isinstance(match, dict)
    assert match.get("outcome_id") == "A.2"
    assert match.get("method") == "cross"
    assert float(match.get("score", 0.0) or 0.0) > 0.5


def test_resolve_question_outcomes_accepts_cross_method(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    outcome_id = "A.1"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": outcome_id, "text": "Explain the purpose of financial management", "level": 1}
            ],
        }
    }

    monkeypatch.setattr(
        eng,
        "_semantic_best_outcome_match",
        lambda *_args, **_kwargs: {"outcome_id": outcome_id, "score": 0.79, "method": "cross"},
    )
    route = eng.resolve_question_outcomes(chapter, 0)
    assert route.get("outcome_ids") == [outcome_id]
    assert route.get("semantic_match_method") == "cross"


def test_semantic_alias_normalization_maps_abbreviation(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "Ratio Analysis"
    outcome_lookup = {
        "R.1": {"text": "Apply financial statement analysis for performance review"},
        "R.2": {"text": "Use valuation ratios for investment decisions"},
    }
    eng.semantic_aliases = {"fs analysis": "financial statement analysis"}
    monkeypatch.setattr(eng, "_semantic_get_model", lambda: None)
    monkeypatch.setattr(eng, "_semantic_get_reranker", lambda: None)

    match = eng._semantic_best_outcome_match(chapter, "How does FS analysis help?", outcome_lookup)
    assert isinstance(match, dict)
    assert match.get("outcome_id") == "R.1"
    assert str(match.get("method", "")) in {"tfidf", "fallback"}


def test_semantic_alias_normalization_chapter_specific(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "Working Capital Management"
    outcome_lookup = {
        "C.1": {"text": "Apply working capital policies to liquidity management"},
        "C.2": {"text": "Discuss short-term financing choices"},
    }
    eng.semantic_aliases = {
        chapter: {
            "wc policy": "working capital policies",
        }
    }
    monkeypatch.setattr(eng, "_semantic_get_model", lambda: None)
    monkeypatch.setattr(eng, "_semantic_get_reranker", lambda: None)

    match = eng._semantic_best_outcome_match(chapter, "How do WC policy decisions affect liquidity?", outcome_lookup)
    assert isinstance(match, dict)
    assert match.get("outcome_id") == "C.1"
    assert str(match.get("method", "")) in {"tfidf", "fallback"}


def test_resolve_question_outcomes_falls_back_deterministically(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Outcome one", "level": 1},
                {"id": "A.2", "text": "Outcome two", "level": 2},
            ],
        }
    }

    monkeypatch.setattr(
        eng,
        "_semantic_best_outcome_match",
        lambda *_args, **_kwargs: {"outcome_id": None, "score": 0.0, "method": "fallback"},
    )
    route = eng.resolve_question_outcomes(chapter, 0)
    ids = route.get("outcome_ids")
    assert isinstance(ids, list)
    assert len(ids) == 1
    assert route.get("semantic_match_method") == "fallback"
    assert float(route.get("semantic_match_confidence", 0.0) or 0.0) == 0.0


def test_record_question_event_stores_semantic_fields(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    outcome_id = "A.4"
    monkeypatch.setattr(
        eng,
        "resolve_question_outcomes",
        lambda *_args, **_kwargs: {
            "outcome_ids": [outcome_id],
            "semantic_match_confidence": 0.73,
            "semantic_match_method": "tfidf",
            "reason": "semantic map from question text",
        },
    )

    eng.record_question_event(chapter, 0, is_correct=True, elapsed_sec=12.0)
    qid = eng._question_qid(chapter, 0) or "0"
    entry = eng.question_stats.get(chapter, {}).get(qid, {})
    assert isinstance(entry, dict)
    assert entry.get("outcome_id") == outcome_id
    assert float(entry.get("semantic_score", 0.0) or 0.0) == pytest.approx(0.73, rel=1e-6)
    assert entry.get("semantic_method") == "tfidf"
    assert isinstance(entry.get("last_semantic_refresh"), str)


def test_select_outcome_gap_questions_returns_uncovered_only(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Covered outcome", "level": 1},
                {"id": "A.2", "text": "Uncovered outcome", "level": 2},
            ],
        }
    }
    eng.outcome_stats = {
        chapter: {
            "A.1": {"attempts": 3, "correct": 3, "streak": 3, "last_seen": datetime.date.today().isoformat()},
            "A.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": datetime.date.today().isoformat()},
        }
    }

    mapping = {0: ["A.1"], 1: ["A.2"], 2: ["A.2"], 3: ["A.1"]}
    monkeypatch.setattr(eng, "_question_outcome_ids", lambda _chapter, idx: mapping.get(idx, []))

    picked = eng.select_outcome_gap_questions(chapter, count=4)
    assert picked
    assert set(picked).issubset({1, 2})


def test_select_outcome_gap_questions_empty_when_no_outcomes(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {}
    eng.outcome_stats = {}
    assert eng.select_outcome_gap_questions(chapter, count=5) == []


def test_select_outcome_gap_questions_empty_when_fully_covered(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Outcome one", "level": 1},
            ],
        }
    }
    eng.outcome_stats = {
        chapter: {
            "A.1": {"attempts": 4, "correct": 4, "streak": 4, "last_seen": datetime.date.today().isoformat()},
        }
    }
    monkeypatch.setattr(eng, "_question_outcome_ids", lambda _chapter, _idx: ["A.1"])
    assert eng.select_outcome_gap_questions(chapter, count=3) == []


def test_select_outcome_gap_questions_prioritizes_due_then_low_recall(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.2", "text": "Outcome two", "level": 2},
            ],
        }
    }
    eng.outcome_stats = {
        chapter: {
            "A.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": datetime.date.today().isoformat()},
        }
    }
    monkeypatch.setattr(eng, "_question_outcome_ids", lambda _chapter, idx: ["A.2"] if idx in (0, 1) else [])
    eng.must_review[chapter] = {"1": datetime.date.today().isoformat()}
    eng.srs_data[chapter] = [
        {"last_review": datetime.date.today().isoformat(), "interval": 30, "efactor": 2.5}
        for _ in range(len(eng.QUESTIONS.get(chapter, [])))
    ]
    monkeypatch.setattr(eng, "predict_recall_prob", lambda _chapter, idx: 0.2 if idx == 1 else 0.4 if idx == 0 else None)
    monkeypatch.setattr(
        type(eng),
        "_estimate_question_miss_risk",
        lambda self, _chapter, idx: 0.9 if idx == 1 else 0.3 if idx == 0 else 0.0,
    )
    picked = eng.select_outcome_gap_questions(chapter, count=2)
    assert picked[:1] == [1]


def test_has_undercovered_outcome_activity_today_strict(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    today_iso = datetime.date.today().isoformat()
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Covered", "level": 1},
                {"id": "A.2", "text": "Uncovered", "level": 2},
            ],
        }
    }
    eng.outcome_stats = {
        chapter: {
            "A.1": {"attempts": 4, "correct": 4, "streak": 4, "last_seen": today_iso},
            "A.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "1999-01-01"},
        }
    }
    assert eng.has_outcome_activity_today(["A"]) is True
    assert eng.has_undercovered_outcome_activity_today(["A"]) is False
    eng.outcome_stats[chapter]["A.2"]["last_seen"] = today_iso
    assert eng.has_undercovered_outcome_activity_today(["A"]) is True


def test_record_gap_routing_event_and_summary(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    eng.record_gap_routing_event(
        chapter=chapter,
        kind="quiz",
        meta={
            "eligible": True,
            "active": True,
            "requested": 4,
            "available": 5,
            "hit": 3,
            "selected_total": 8,
        },
        score_pct=75.0,
    )
    eng.record_gap_routing_event(
        chapter=chapter,
        kind="review",
        meta={
            "eligible": False,
            "active": False,
            "requested": 0,
            "available": 0,
            "hit": 0,
            "selected_total": 6,
        },
        score_pct=60.0,
    )
    summary = eng.get_gap_routing_summary(days=7)
    assert int(summary.get("sessions", 0) or 0) == 2
    assert int(summary.get("active_sessions", 0) or 0) == 1
    assert int(summary.get("requested_total", 0) or 0) == 4
    assert int(summary.get("hit_total", 0) or 0) == 3
    assert float(summary.get("hit_rate", 0.0) or 0.0) == pytest.approx(0.75, rel=1e-9)


def test_gap_routing_summary_by_capability(engine_no_io):
    eng = engine_no_io
    eng.syllabus_structure = {
        "FM Function": {"capability": "A", "learning_outcomes": [{"id": "A.1", "text": "x", "level": 1}]},
        "FM Environment": {"capability": "B", "learning_outcomes": [{"id": "B.1", "text": "y", "level": 1}]},
    }
    eng.record_gap_routing_event(
        chapter="FM Function",
        kind="quiz",
        meta={"eligible": True, "active": True, "requested": 4, "available": 5, "hit": 3, "selected_total": 8},
        score_pct=70.0,
    )
    eng.record_gap_routing_event(
        chapter="FM Environment",
        kind="quiz",
        meta={"eligible": True, "active": True, "requested": 2, "available": 2, "hit": 1, "selected_total": 6},
        score_pct=55.0,
    )
    summary = eng.get_gap_routing_summary_by_capability(days=7)
    by_cap = summary.get("by_capability", {})
    assert isinstance(by_cap, dict)
    assert set(by_cap.keys()) >= {"A", "B"}
    assert int(by_cap["A"].get("requested_total", 0) or 0) == 4
    assert int(by_cap["A"].get("hit_total", 0) or 0) == 3
    assert float(by_cap["A"].get("hit_rate", 0.0) or 0.0) == pytest.approx(0.75, rel=1e-9)
    assert int(by_cap["B"].get("requested_total", 0) or 0) == 2
    assert int(by_cap["B"].get("hit_total", 0) or 0) == 1
    assert float(by_cap["B"].get("hit_rate", 0.0) or 0.0) == pytest.approx(0.5, rel=1e-9)


def test_coerce_gap_routing_log_filters_invalid_rows(engine_no_io):
    eng = engine_no_io
    raw = [
        {"chapter": "FM Function", "kind": "quiz", "date": datetime.date.today().isoformat(), "requested": 2, "hit": 1},
        {"chapter": "Unknown", "kind": "quiz", "date": datetime.date.today().isoformat(), "requested": 2, "hit": 2},
        {"chapter": "FM Function", "kind": "quiz", "date": "bad-date", "requested": 2, "hit": 2},
    ]
    cleaned = eng._coerce_gap_routing_log(raw, max_keep=50)
    assert len(cleaned) == 1
    assert cleaned[0]["chapter"] == "FM Function"


def test_get_capability_coverage_debt_ranking(engine_no_io):
    eng = engine_no_io
    today_iso = datetime.date.today().isoformat()
    eng.syllabus_structure = {
        "FM Function": {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "A1", "level": 1},
                {"id": "A.2", "text": "A2", "level": 2},
                {"id": "A.3", "text": "A3", "level": 3},
            ],
            "intellectual_level_mix": {"level_1": 1, "level_2": 1, "level_3": 1},
        },
        "FM Environment": {
            "capability": "B",
            "learning_outcomes": [
                {"id": "B.1", "text": "B1", "level": 1},
                {"id": "B.2", "text": "B2", "level": 1},
            ],
            "intellectual_level_mix": {"level_1": 2, "level_2": 0, "level_3": 0},
        },
    }
    eng.outcome_stats = {
        "FM Function": {
            "A.1": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": today_iso},
            "A.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "1999-01-01"},
            "A.3": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "1999-01-01"},
        },
        "FM Environment": {
            "B.1": {"attempts": 3, "correct": 3, "streak": 3, "last_seen": today_iso},
            "B.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "1999-01-01"},
        },
    }
    debt = eng.get_capability_coverage_debt(max_coverage=95.0, min_uncovered=1)
    assert isinstance(debt, dict)
    caps = list(debt.keys())
    assert caps
    assert caps[0] == "A"
    assert float(debt["A"]["debt_score"]) >= float(debt.get("B", {"debt_score": 0.0})["debt_score"])


def test_select_semantic_interleave_questions_prioritizes_due_and_targets(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    today_iso = datetime.date.today().isoformat()
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Target", "level": 2},
                {"id": "A.2", "text": "Adjacent", "level": 2},
                {"id": "A.3", "text": "Far", "level": 2},
            ],
        }
    }
    eng.outcome_stats = {chapter: {"A.1": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": today_iso}}}
    mapping = {
        0: ["A.1"],  # target
        1: ["A.2"],  # adjacent
        2: ["A.3"],  # far
        3: ["A.3"],  # far + due
    }
    monkeypatch.setattr(eng, "_question_outcome_ids", lambda _chapter, idx: mapping.get(idx, []))
    eng.must_review[chapter] = {"3": today_iso}
    eng.srs_data[chapter] = [
        {"last_review": today_iso, "interval": 20, "efactor": 2.5}
        for _ in range(len(eng.QUESTIONS.get(chapter, [])))
    ]
    monkeypatch.setattr(eng, "predict_recall_prob", lambda _chapter, _idx: 0.4)
    monkeypatch.setattr(
        type(eng),
        "_estimate_question_miss_risk",
        lambda self, _chapter, _idx: 0.5,
    )

    picked = eng.select_semantic_interleave_questions(chapter, count=3, target_outcome_ids=["A.1"])
    assert picked
    assert 3 in picked  # must-review due question should survive quota filling
    assert any(idx in picked for idx in (0,))  # include at least one target-outcome question
    assert len(picked) == len(set(picked))


def test_select_semantic_interleave_questions_falls_back_to_srs(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {}
    monkeypatch.setattr(eng, "select_srs_questions", lambda _chapter, count: [7, 6, 5][:count])
    picked = eng.select_semantic_interleave_questions(chapter, count=3)
    assert picked == [7, 6, 5]


def test_get_semantic_interleave_mix_counts(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Target", "level": 2},
                {"id": "A.2", "text": "Adjacent", "level": 2},
                {"id": "A.3", "text": "Far", "level": 2},
            ],
        }
    }
    eng.outcome_stats = {chapter: {"A.1": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": datetime.date.today().isoformat()}}}
    mapping = {
        0: ["A.1"],
        1: ["A.2"],
        2: ["A.3"],
        3: [],
    }
    monkeypatch.setattr(eng, "_question_outcome_ids", lambda _chapter, idx: mapping.get(idx, []))
    mix = eng.get_semantic_interleave_mix(chapter, [0, 1, 2, 3], target_outcome_ids=["A.1"])
    assert mix["target"] == 1
    assert mix["adjacent"] == 1
    assert mix["far"] == 1
    assert mix["unknown"] == 1
    assert mix["total"] == 4
    assert "planned_target_ratio" in mix
    assert "planned_adjacent_ratio" in mix
    assert "planned_far_ratio" in mix
    assert float(mix.get("planned_target_ratio", 0.0) or 0.0) > 0.0


def test_adaptive_interleave_ratios_boost_target_for_high_uncovered(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "one", "level": 2},
                {"id": "A.2", "text": "two", "level": 2},
                {"id": "A.3", "text": "three", "level": 2},
                {"id": "A.4", "text": "four", "level": 2},
            ],
        }
    }
    # 1/4 covered => uncovered ratio 0.75 should trigger high-gap boost.
    eng.outcome_stats = {
        chapter: {
            "A.1": {"attempts": 3, "correct": 3, "streak": 3, "last_seen": datetime.date.today().isoformat()},
            "A.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": datetime.date.today().isoformat()},
            "A.3": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": datetime.date.today().isoformat()},
            "A.4": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": datetime.date.today().isoformat()},
        }
    }
    target, adjacent, far, mode = eng._adaptive_interleave_ratios(chapter)
    assert mode.startswith("boost-")
    assert target > float(eng.INTERLEAVE_TARGET_RATIO)
    assert target + adjacent + far == pytest.approx(1.0, rel=1e-6)


def test_build_canonical_concept_graph_is_deterministic(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "subtopics": ["Role of finance", "Agency"],
            "learning_outcomes": [
                {"id": "A.1", "text": "Explain the role of the finance function", "level": 1},
                {"id": "A.2", "text": "Explain agency problems", "level": 2},
            ],
        }
    }
    first = eng.build_canonical_concept_graph(force=True)
    second = eng.build_canonical_concept_graph(force=True)
    first_ids = [str(n.get("id", "")) for n in first.get("nodes", []) if isinstance(n, dict)]
    second_ids = [str(n.get("id", "")) for n in second.get("nodes", []) if isinstance(n, dict)]
    assert first_ids
    assert first_ids == second_ids
    assert int(first.get("meta", {}).get("version", 0) or 0) == int(eng.CONCEPT_GRAPH_SCHEMA_VERSION)


def test_build_outcome_cluster_graph_lexical_fallback_stable(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Working capital policy", "level": 2},
                {"id": "A.2", "text": "Working capital cycle", "level": 2},
                {"id": "A.3", "text": "Agency and governance", "level": 1},
            ],
        }
    }
    monkeypatch.setattr(eng, "_semantic_get_model", lambda: None)
    first = eng.build_outcome_cluster_graph(force=True)
    second = eng.build_outcome_cluster_graph(force=True)
    first_clusters = [str(c.get("cluster_id", "")) for c in first.get("clusters", []) if isinstance(c, dict)]
    second_clusters = [str(c.get("cluster_id", "")) for c in second.get("clusters", []) if isinstance(c, dict)]
    assert first_clusters
    assert first_clusters == second_clusters
    assert str(first.get("meta", {}).get("method", "")) == "lexical"


def test_semantic_interleave_mix_exposes_cluster_mode(engine_no_io, monkeypatch):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "Target concept", "level": 2},
                {"id": "A.2", "text": "Adjacent concept", "level": 2},
                {"id": "A.3", "text": "Far concept", "level": 2},
            ],
        }
    }
    today_iso = datetime.date.today().isoformat()
    eng.outcome_stats = {
        chapter: {
            "A.1": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": today_iso},
            "A.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": today_iso},
            "A.3": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": today_iso},
        }
    }
    mapping = {0: ["A.1"], 1: ["A.2"], 2: ["A.3"]}
    monkeypatch.setattr(eng, "_question_outcome_ids", lambda _chapter, idx: mapping.get(idx, []))
    eng.build_outcome_cluster_graph(force=True)
    mix = eng.get_semantic_interleave_mix(chapter, [0, 1, 2], target_outcome_ids=["A.1"])
    assert str(mix.get("cluster_mode", "")) in {"semantic", "lexical", "fallback"}
    assert "target_cluster_count" in mix


def test_semantic_drift_kpi_flags_gap_and_lag(engine_no_io):
    eng = engine_no_io
    chapter = "FM Function"
    eng.syllabus_structure = {
        chapter: {
            "capability": "A",
            "learning_outcomes": [
                {"id": "A.1", "text": "one", "level": 1},
                {"id": "A.2", "text": "two", "level": 2},
                {"id": "A.3", "text": "three", "level": 2},
                {"id": "A.4", "text": "four", "level": 2},
                {"id": "A.5", "text": "five", "level": 3},
            ],
        }
    }
    eng.competence[chapter] = 90.0
    eng.outcome_stats = {
        chapter: {
            "A.1": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "2000-01-01"},
            "A.2": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "2000-01-01"},
            "A.3": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "2000-01-01"},
            "A.4": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "2000-01-01"},
            "A.5": {"attempts": 1, "correct": 0, "streak": 0, "last_seen": "2000-01-01"},
        }
    }
    kpi = eng.get_semantic_drift_kpi(days=7)
    assert str(kpi.get("status", "")) in {"warning", "severe"}
    assert int(kpi.get("chapters_flagged", 0) or 0) >= 1
    alerts = eng.get_semantic_drift_alerts(days=7)
    assert alerts
    assert alerts[0].get("chapter") == chapter


def test_enforce_file_size_limit_rejects_oversized_file(engine_no_io, tmp_path):
    eng = engine_no_io
    path = tmp_path / "big.json"
    path.write_text("x" * 2048, encoding="utf-8")
    with pytest.raises(ValueError):
        eng._enforce_file_size_limit(str(path), 1024, "Snapshot")


def test_enforce_file_size_limit_rejects_directory(engine_no_io, tmp_path):
    eng = engine_no_io
    with pytest.raises(ValueError):
        eng._enforce_file_size_limit(str(tmp_path), 1024, "Snapshot")


def test_load_json_file_with_limit_reads_json(engine_no_io, tmp_path):
    eng = engine_no_io
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"k": 1}), encoding="utf-8")
    loaded = eng._load_json_file_with_limit(str(path), 1024, "Snapshot")
    assert loaded == {"k": 1}


def test_import_data_snapshot_rejects_oversized_file(engine_no_io, tmp_path):
    eng = engine_no_io
    eng.MAX_SNAPSHOT_IMPORT_BYTES = 128
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"payload": "x" * 1024}), encoding="utf-8")
    with pytest.raises(ValueError):
        eng.import_data_snapshot(str(path))


def test_import_questions_json_rejects_oversized_file(engine_no_io, tmp_path):
    eng = engine_no_io
    eng.MAX_QUESTION_IMPORT_BYTES = 128
    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"chapter": "FM Function", "questions": [{"question": "Q", "options": ["A"], "correct": "A"}] * 50}), encoding="utf-8")
    with pytest.raises(ValueError):
        eng.import_questions_json(str(path))
