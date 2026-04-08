"""Tests for studyplan.working_memory_service module."""
import pytest

from studyplan.cognitive_state import CognitiveState
from studyplan.working_memory_service import WorkingMemoryService


def _make_service() -> WorkingMemoryService:
    return WorkingMemoryService(CognitiveState())


# ---------------------------------------------------------------------------
# capture_attempt
# ---------------------------------------------------------------------------


def test_capture_attempt_correct_adds_tick_to_context():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=True)
    ctx = svc.get_context_string()
    assert "✓" in ctx


def test_capture_attempt_incorrect_adds_cross():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=False)
    ctx = svc.get_context_string()
    assert "✗" in ctx


def test_capture_attempt_sets_active_chapter():
    svc = _make_service()
    svc.capture_attempt("Chapter 7", "q1", correct=True)
    assert svc.cognitive_state.working_memory.active_chapter == "Chapter 7"


def test_capture_attempt_empty_chapter_ignored():
    svc = _make_service()
    svc.capture_attempt("", "q1", correct=True)
    assert svc.cognitive_state.working_memory.active_chapter is None


def test_capture_attempt_sets_error_streak_on_wrong():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=False)
    assert svc.cognitive_state.working_memory.struggle_flags["error_streak"] is True


def test_capture_attempt_clears_error_streak_on_correct():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=False)
    svc.capture_attempt("Chapter 1", "q2", correct=True)
    assert svc.cognitive_state.working_memory.struggle_flags["error_streak"] is False


def test_capture_attempt_latency_spike_flag():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=True, latency_ms=50000.0)
    assert svc.cognitive_state.working_memory.struggle_flags["latency_spike"] is True


def test_capture_attempt_no_latency_spike_below_threshold():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=True, latency_ms=1000.0)
    assert svc.cognitive_state.working_memory.struggle_flags["latency_spike"] is False


def test_capture_attempt_hint_dependency_flag():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=True, hints_used=3)
    assert svc.cognitive_state.working_memory.struggle_flags["hint_dependency"] is True


def test_capture_attempt_no_hint_dependency_below_threshold():
    svc = _make_service()
    svc.capture_attempt("Chapter 1", "q1", correct=True, hints_used=1)
    assert svc.cognitive_state.working_memory.struggle_flags["hint_dependency"] is False


# ---------------------------------------------------------------------------
# set_active_question / clear_active_question
# ---------------------------------------------------------------------------


def test_set_active_question_activates_quiz():
    svc = _make_service()
    svc.set_active_question(chapter="Chapter 3", question_id="q10")
    assert svc.cognitive_state.quiz_active is True
    assert svc.cognitive_state.working_memory.active_question_id == "q10"
    assert svc.cognitive_state.working_memory.active_chapter == "Chapter 3"


def test_clear_active_question_deactivates_quiz():
    svc = _make_service()
    svc.set_active_question(chapter="Chapter 3", question_id="q10")
    svc.clear_active_question()
    assert svc.cognitive_state.quiz_active is False
    assert svc.cognitive_state.working_memory.active_question_id is None


# ---------------------------------------------------------------------------
# get_context_string
# ---------------------------------------------------------------------------


def test_get_context_string_includes_recent_attempts():
    svc = _make_service()
    svc.capture_attempt("Chapter A", "q1", correct=True)
    ctx = svc.get_context_string()
    assert "Chapter A" in ctx


def test_get_context_string_shows_active_chapter():
    svc = _make_service()
    svc.capture_attempt("Chapter B", "q2", correct=True)
    ctx = svc.get_context_string()
    assert "Active chapter: Chapter B" in ctx


def test_get_context_string_signals_error_streak():
    svc = _make_service()
    svc.capture_attempt("Chapter C", "q1", correct=False)
    ctx = svc.get_context_string()
    assert "error streak" in ctx.lower()


def test_get_context_string_signals_hint_dependency():
    svc = _make_service()
    svc.capture_attempt("Chapter D", "q1", correct=True, hints_used=3)
    ctx = svc.get_context_string()
    assert "hint" in ctx.lower()


def test_get_context_string_empty_when_no_data():
    svc = _make_service()
    ctx = svc.get_context_string()
    assert ctx == ""


def test_get_context_string_mentions_quiz_active():
    svc = _make_service()
    svc.set_active_question(chapter="Chapter E", question_id="q99")
    ctx = svc.get_context_string()
    assert "quiz" in ctx.lower() or "active question" in ctx.lower()


# ---------------------------------------------------------------------------
# apply_quiz_active
# ---------------------------------------------------------------------------


def test_apply_quiz_active_true():
    svc = _make_service()
    svc.apply_quiz_active(True)
    assert svc.cognitive_state.quiz_active is True


def test_apply_quiz_active_false_clears_question_id():
    svc = _make_service()
    svc.set_active_question(chapter="Ch1", question_id="q5")
    svc.apply_quiz_active(False)
    assert svc.cognitive_state.quiz_active is False
    assert svc.cognitive_state.working_memory.active_question_id is None


# ---------------------------------------------------------------------------
# note_tutor_exchange
# ---------------------------------------------------------------------------


def test_note_tutor_exchange_user_adds_to_context():
    svc = _make_service()
    svc.note_tutor_exchange("user", "What is NPV?")
    ctx = svc.get_context_string()
    assert "U: What is NPV?" in ctx


def test_note_tutor_exchange_assistant_adds_to_context():
    svc = _make_service()
    svc.note_tutor_exchange("assistant", "NPV stands for Net Present Value.")
    ctx = svc.get_context_string()
    assert "T: NPV stands for" in ctx


def test_note_tutor_exchange_invalid_role_ignored():
    svc = _make_service()
    svc.note_tutor_exchange("system", "You are an AI.")
    ctx = svc.get_context_string()
    assert ctx == ""


def test_note_tutor_exchange_empty_content_ignored():
    svc = _make_service()
    svc.note_tutor_exchange("user", "")
    ctx = svc.get_context_string()
    assert ctx == ""


def test_note_tutor_exchange_long_content_truncated():
    svc = _make_service()
    long_msg = "a" * 200
    svc.note_tutor_exchange("user", long_msg)
    ctx = svc.get_context_string()
    # Content should be truncated (max 120 chars + prefix)
    for line in ctx.split("\n"):
        if line.startswith("U:"):
            assert len(line) <= 130  # "U: " + 120 chars + "..."
