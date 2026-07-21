"""Structured diagnostic output types and aggregation.

Each evaluation produces a ``QuestionDiagnostic`` that can be merged
upward into learner profile, tutor context, and autopilot evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Error Pattern Taxonomy (Phase 4d)
# ---------------------------------------------------------------------------


class ErrorPattern(Enum):
    """Standardised error pattern taxonomy for step-level diagnosis.

    Each member maps to a stable tag string consumed by the AI tutor
    and the diagnostic summary pipeline.
    """

    OFF_BY_ONE = "step_off_by_one"
    WRONG_FORMULA = "wrong_formula"
    SIGN_ERROR = "sign_error"
    UNIT_ERROR = "unit_error"
    WRONG_INPUT = "wrong_input"
    ORDER_ERROR = "order_error"
    COMPOUND_ERROR = "compound_error"
    TAX_NEGLECT = "tax_neglect"
    WRONG_DISCOUNT_RATE = "wrong_discount_rate"


# ---------------------------------------------------------------------------
# Step-Error Classifier
# ---------------------------------------------------------------------------

_STEP_PATTERN_MAP: list[tuple[str, ErrorPattern]] = [
    ("sign", ErrorPattern.SIGN_ERROR),
    ("rate", ErrorPattern.WRONG_DISCOUNT_RATE),
    ("discount", ErrorPattern.WRONG_DISCOUNT_RATE),
    ("unit", ErrorPattern.UNIT_ERROR),
    ("tax", ErrorPattern.TAX_NEGLECT),
    ("compound", ErrorPattern.COMPOUND_ERROR),
    ("order", ErrorPattern.ORDER_ERROR),
    ("off_by_one", ErrorPattern.OFF_BY_ONE),
    ("wrong_formula", ErrorPattern.WRONG_FORMULA),
    ("wrong_input", ErrorPattern.WRONG_INPUT),
]


def classify_step_id_error(step_id: str) -> ErrorPattern | None:
    """Map a step ID to a semantic error pattern based on known keywords."""
    if not step_id:
        return None
    step_lower = step_id.lower().replace("_", " ").replace("-", " ")
    for keyword, pattern in _STEP_PATTERN_MAP:
        if keyword in step_lower:
            return pattern
    # Fallback: detect common formula-step patterns
    if step_lower.startswith("pv ") or step_lower.startswith("fv "):
        return ErrorPattern.WRONG_INPUT
    return None


def classify_step_errors(
    step_matches: list[dict[str, Any]],
    *,
    truth: dict[str, Any] | None = None,
) -> list[str]:
    """Generate error tags from step-match results using the formal taxonomy.

    Returns tags like ``sign_error``, ``wrong_discount_rate``, etc.
    Falls back to generic ``step_{id}_mismatch`` for unrecognised steps.
    """
    tags: list[str] = []
    for m in step_matches:
        step_id = str(m.get("step_id", "") or "")
        if not step_id:
            continue
        if m.get("match", False):
            continue
        pattern = classify_step_id_error(step_id)
        if pattern is not None:
            tag = str(pattern.value)
            if tag not in tags:
                tags.append(tag)
        else:
            tags.append(f"step_{step_id}_mismatch")
    return tags


@dataclass
class StepEvaluation:
    """Result of comparing one learner step against truth."""

    step_id: str
    description: str = ""
    expected: float | None = None
    actual: float | None = None
    match: bool = False


@dataclass
class ConceptEvaluation:
    """Evaluation result for a single concept."""

    concept_id: str
    template_version: str = ""
    result: float | None = None
    is_nan: bool = False
    steps: list[StepEvaluation] = field(default_factory=list)
    error_tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    inputs_used: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuestionDiagnostic:
    """Full diagnostic for a single question.

    Carries concept-level evaluations plus a summary for the tutor/autopilot.
    """

    question_slug: str = ""
    concept_ids: list[str] = field(default_factory=list)
    primary_concept_id: str = ""
    concept_evaluations: list[ConceptEvaluation] = field(default_factory=list)
    all_error_tags: list[str] = field(default_factory=list)
    has_deterministic_truth: bool = False
    diagnostic_confidence: float = 0.0

    # Tutor-facing summary
    error_summary: str = ""
    weak_concepts: list[str] = field(default_factory=list)
    blocked_dependencies: list[str] = field(default_factory=list)


def merge_concept_results(
    evaluations: list[ConceptEvaluation],
    concepts_metadata: dict[str, Any] | None = None,
) -> QuestionDiagnostic:
    """Aggregate multiple concept evaluations into a single QuestionDiagnostic.

    ``concepts_metadata`` should be the ``BUILTIN_CONCEPTS`` dict (or subset)
    for dependency lookups.
    """
    if concepts_metadata is None:
        concepts_metadata = {}

    all_tags: list[str] = []
    concept_ids: list[str] = []
    primary = ""
    best_conf = 0.0
    blocked: list[str] = []

    for ev in evaluations:
        concept_ids.append(ev.concept_id)
        all_tags.extend(ev.error_tags)
        if ev.confidence > best_conf:
            best_conf = ev.confidence
            primary = ev.concept_id
        # Check blocked dependencies
        meta = concepts_metadata.get(ev.concept_id)
        if meta and hasattr(meta, "dependencies"):
            for dep_id in meta.dependencies:
                dep_ev = next((e for e in evaluations if e.concept_id == dep_id), None)
                if dep_ev and dep_ev.error_tags:
                    blocked.append(f"{ev.concept_id} blocked by {dep_id}")

    has_truth = any(not e.is_nan for e in evaluations)
    confidence = best_conf if evaluations else 0.0

    error_summary = "; ".join(sorted(set(all_tags))) if all_tags else ""
    weak = sorted({ev.concept_id for ev in evaluations if ev.error_tags})

    return QuestionDiagnostic(
        concept_ids=concept_ids,
        primary_concept_id=primary,
        concept_evaluations=list(evaluations),
        all_error_tags=sorted(set(all_tags)),
        has_deterministic_truth=has_truth,
        diagnostic_confidence=confidence,
        error_summary=error_summary,
        weak_concepts=weak,
        blocked_dependencies=blocked,
    )


def format_error_summary(diag: QuestionDiagnostic, max_tags: int = 5) -> str:
    """Format a human-readable error summary for tutor context."""
    parts: list[str] = []
    if diag.primary_concept_id:
        parts.append(f"concept: {diag.primary_concept_id}")
    if diag.all_error_tags:
        tags = diag.all_error_tags[:max_tags]
        parts.append(f"errors: {', '.join(tags)}")
        if len(diag.all_error_tags) > max_tags:
            parts.append(f"(+{len(diag.all_error_tags) - max_tags} more)")
    if diag.blocked_dependencies:
        parts.append(f"blocked: {len(diag.blocked_dependencies)} dependency")
    if not diag.has_deterministic_truth:
        parts.append("no deterministic truth")
    if diag.diagnostic_confidence > 0:
        parts.append(f"confidence: {diag.diagnostic_confidence:.2f}")
    return " | ".join(parts) if parts else "no diagnostics available"
