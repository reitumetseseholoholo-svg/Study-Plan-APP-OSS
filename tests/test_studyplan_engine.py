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
    assert any("fallback draft generated" in str(w).lower() for w in warnings)
    assert eng.recall_model_sklearn_meta is None


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
    built = eng.build_module_config_from_syllabus(parsed, base_config={"title": "ACCA FM"})
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
    built_a = eng.build_module_config_from_syllabus(parsed, base_config={"title": "ACCA FM"})
    built_b = eng.build_module_config_from_syllabus(parsed, base_config={"title": "ACCA FM"})
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
        "title": "ACCA FM",
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
