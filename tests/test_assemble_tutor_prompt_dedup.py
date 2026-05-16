"""assemble_ai_tutor_turn_prompt learning-context dedup line (Phase 1)."""

from __future__ import annotations

from studyplan_ai_tutor import assemble_ai_tutor_turn_prompt


def test_assemble_ignores_fingerprint_without_real_context():
    out = assemble_ai_tutor_turn_prompt(
        "BASE",
        learning_context="",
        rag_context="",
        planner_brief="",
        learning_context_unchanged_sha256="deadbeef",
    )
    assert out == "BASE"


def test_assemble_prefers_full_context_over_fingerprint():
    out = assemble_ai_tutor_turn_prompt(
        "BASE",
        learning_context="Topic: A",
        rag_context="",
        planner_brief="",
        learning_context_unchanged_sha256="ignored",
    )
    assert "Topic: A" in out
    assert "Unchanged since" not in out
