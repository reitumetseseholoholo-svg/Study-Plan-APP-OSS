"""Tests for tutor-visible LLM output polish (not JSON / cache paths)."""

from studyplan.ai.llm_output_sanitize import polish_tutor_answer_prose, sanitize_visible_local_llm_answer


def test_sanitize_visible_strips_think_only():
    raw = "<think>\nsecret\n</think>\nKeep this"
    out = sanitize_visible_local_llm_answer(raw)
    assert "secret" not in out
    assert "Keep this" in out


def test_polish_strips_planner_and_debrief():
    raw = (
        "Now, the learner is asking about IAS 36. I should be clear.\n\n"
        "(1) Direct Answer:\nReal content here.\n\n"
        "(2) More:\nDetails.\n\n"
        "Why this works:\n- exam focus\n\nEnd of Session.\nNext drill."
    )
    out = polish_tutor_answer_prose(raw)
    assert "learner is asking" not in out.lower()
    assert "Real content" in out
    assert "Why this works" not in out
    assert "End of Session" not in out
