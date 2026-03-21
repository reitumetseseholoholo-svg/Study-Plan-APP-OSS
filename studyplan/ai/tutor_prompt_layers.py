"""
Modular tutor context prompt pieces (roadmap Phase 3).

Shared coach-identity lines live here so task-specific heads can evolve without
duplicating the base block. Pedagogical mode is explicit metadata for telemetry
and future routing.
"""
from __future__ import annotations

from typing import Final

# Mirrors studyplan_ai_tutor AI_TUTOR_* rules (avoid importing studyplan_ai_tutor from this package).
_TUTOR_NEXT_STEP_RULE = (
    "End with one concrete next step (topic + mode + duration); suggest topic-based practice or in-app drill."
)
_TUTOR_NO_STUDY_GUIDE_QUESTION_RULE = (
    "Never suggest a specific study-guide question or textbook page number."
)

PEDAGOGICAL_EXPLAIN = "explain"
PEDAGOGICAL_PRACTICE = "practice"
PEDAGOGICAL_EXAM_TECHNIQUE = "exam_technique"
PEDAGOGICAL_REVISION = "revision"
PEDAGOGICAL_FREEFORM = "freeform"

ALL_PEDAGOGICAL_MODES: Final[frozenset[str]] = frozenset(
    {
        PEDAGOGICAL_EXPLAIN,
        PEDAGOGICAL_PRACTICE,
        PEDAGOGICAL_EXAM_TECHNIQUE,
        PEDAGOGICAL_REVISION,
        PEDAGOGICAL_FREEFORM,
    }
)

TUTOR_COACH_IDENTITY_LINES: list[str] = [
    "Coach identity:",
    "- maximize exam readiness per minute using learner state and syllabus context.",
    "- Priority: must-review pressure → weak-topic repair → retrieval practice → formula accuracy → exam-style clarity.",
    "- Act as session pilot: diagnose gaps, prescribe actions, drill, then give one concrete next move.",
    "- Use short sections, bullets, and formulas when relevant; be concise but include brief reasoning.",
    "- Write formulas and math as humans do: use a/b for fractions, x² for squared, plain words for Greek (e.g. alpha, beta). Do not use LaTeX (e.g. \\frac, $$) or code blocks for equations.",
    "- Write in correct, professional English: no grammatical or spelling errors; use clear sentence structure and proofread before responding.",
    "- Ensure proper spacing between words and numbers (e.g., 'inventory is 30,000').",
    "- Use elaborative encoding: link new ideas to prior topics or recent activity; add one short why/how connection or application when helpful.",
    "- Maintain continuity: when learning context or working memory shows a last topic/next step, acknowledge it and build from it.",
    "- Avoid generic motivation; be operational and exam-focused.",
    "- Do not introduce non-examinable methods, metrics, or content; stay strictly within syllabus.",
    f"- {_TUTOR_NO_STUDY_GUIDE_QUESTION_RULE} Suggest topic-based practice or in-app drills instead.",
    f"- When useful, {_TUTOR_NEXT_STEP_RULE} If assumptions are needed, state them explicitly.",
    "",
]


def derive_pedagogical_mode(
    *,
    concise_mode: bool = False,
    exam_technique_only: bool = False,
    mode_hint: str = "",
) -> str:
    """
    Map tutor UI flags + mode hint to an explicit pedagogical_mode.

    mode_hint values match infer_tutor_prompt_mode_hint in studyplan_ai_tutor.
    """
    if exam_technique_only:
        return PEDAGOGICAL_EXAM_TECHNIQUE
    hint = str(mode_hint or "").strip().lower() or "teach"
    if hint == "exam_technique":
        return PEDAGOGICAL_EXAM_TECHNIQUE
    if hint in ("retrieval_drill", "guided_practice", "error_clinic", "section_c_coach"):
        return PEDAGOGICAL_PRACTICE
    if hint == "revision_planner":
        return PEDAGOGICAL_REVISION
    if concise_mode:
        return PEDAGOGICAL_REVISION
    return PEDAGOGICAL_EXPLAIN
