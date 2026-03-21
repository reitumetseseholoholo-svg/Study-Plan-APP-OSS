"""assemble_ai_tutor_turn_prompt learning-context dedup line (Phase 1)."""

from __future__ import annotations

from studyplan_ai_tutor import assemble_ai_tutor_turn_prompt


def test_assemble_inserts_fingerprint_when_context_unchanged():
    out = assemble_ai_tutor_turn_prompt(
        "BASE",
        learning_context="",
        rag_context="",
        planner_brief="",
        learning_context_unchanged_sha256="deadbeef",
    )
    assert "Unchanged since the prior turn" in out
    assert "sha256:deadbeef" in out
    assert "Learning context" in out


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
