"""Phase 3 tutor prompt layer helpers."""

from __future__ import annotations

from studyplan.ai.tutor_prompt_layers import derive_pedagogical_mode


def test_derive_pedagogical_mode_exam_only():
    assert (
        derive_pedagogical_mode(concise_mode=True, exam_technique_only=True, mode_hint="teach")
        == "exam_technique"
    )


def test_derive_pedagogical_mode_from_hint():
    assert derive_pedagogical_mode(mode_hint="revision_planner") == "revision"
    assert derive_pedagogical_mode(mode_hint="retrieval_drill") == "practice"


def test_derive_pedagogical_mode_concise_defaults_to_revision():
    assert derive_pedagogical_mode(concise_mode=True, mode_hint="teach") == "revision"
