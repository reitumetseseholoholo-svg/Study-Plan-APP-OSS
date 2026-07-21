"""Evaluation pipeline: question → concept detection → template execution → diagnostics.

This is the primary entry point for deterministic concept evaluation.
It connects the concept registry, template registry, numerical solver
input extraction, and diagnostic output.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from studyplan.numerical_solver import (
    extract_numbers,
    detect_formulas,
    verify_numerical_answer,
)
from studyplan.domain_reasoning.concepts import (
    BUILTIN_CONCEPTS,
    detect_concepts,
)
from studyplan.domain_reasoning.step_matcher import (
    parse_learner_workings,
    match_learner_steps,
    compute_step_error_tags,
)
from studyplan.domain_reasoning.templates import TEMPLATE_REGISTRY
from studyplan.domain_reasoning.diagnostics import (
    ConceptEvaluation,
    QuestionDiagnostic,
    StepEvaluation,
    merge_concept_results,
)

_logger = logging.getLogger(__name__)


def evaluate_question(
    question: str,
    options: list[str] | None = None,
    correct: str | None = None,
    *,
    domain: str | None = None,
    template_ref: str | None = None,
    template_inputs: dict[str, Any] | None = None,
    explanation: str | None = None,
    learner_answer: str | None = None,
    learner_workings: str | None = None,
) -> QuestionDiagnostic:
    """Run the full deterministic evaluation pipeline on a question.

    Parameters
    ----------
    question : str
        The question text.
    domain : str | None
        Exam domain prefix (e.g. ``"fm"``, ``"pmp"``).  Defaults to ACCA FM.
    ...
    """
    # Resolve domain registry (defaults to ACCA FM globals)
    if domain is not None:
        from studyplan.domain_reasoning.domain_registry import get_registry

        reg = get_registry(domain)
        _concepts = reg.concepts
        _templates = reg.templates
    else:
        _concepts = BUILTIN_CONCEPTS
        _templates = TEMPLATE_REGISTRY

    formulas = detect_formulas(question)
    concept_ids = detect_concepts(question, formulas, domain=domain)
    nums = extract_numbers(question)
    parsed_correct = _try_parse_correct(correct)

    evaluations: list[ConceptEvaluation] = []

    # Tier 1: Exact template execution (if template_ref provided)
    if template_ref and template_inputs:
        ev = _evaluate_single_concept(
            template_ref,
            template_inputs,
            parsed_correct,
            learner_answer,
            is_primary=True,
            learner_workings=learner_workings,
            template_registry=_templates,
        )
        if ev is not None:
            evaluations.append(ev)

    # Tier 2: Detected concept evaluation
    for cid in concept_ids:
        if cid == template_ref:
            continue  # Already evaluated as Tier 1
        if cid not in _templates:
            continue
        inputs = _extract_inputs_for_concept(cid, nums, question)
        if not inputs:
            continue
        ev = _evaluate_single_concept(
            cid,
            inputs,
            parsed_correct,
            learner_answer,
            is_primary=False,
            learner_workings=learner_workings,
            template_registry=_templates,
        )
        if ev is not None:
            evaluations.append(ev)

    # Tier 3: Numerical verification using existing verify_numerical_answer
    if options and correct and not evaluations:
        v_result = verify_numerical_answer(
            question,
            options,
            correct,
            template_ref=template_ref,
            template_inputs=template_inputs,
            explanation=explanation,
        )
        if v_result is not None:
            evaluations.append(
                ConceptEvaluation(
                    concept_id="builtin.numerical_verification",
                    result=0.0,
                    error_tags=[v_result],
                    confidence=0.5,
                )
            )

    if not evaluations:
        return QuestionDiagnostic(
            question_slug=question[:80],
            has_deterministic_truth=False,
        )

    return merge_concept_results(evaluations, _concepts)


def _try_parse_correct(correct: str | None) -> float | None:
    if not correct:
        return None
    stripped = str(correct).strip().lstrip("$").lstrip("\u00a3").lstrip("\u20ac")
    stripped = stripped.replace(",", "").replace("%", "")
    try:
        return float(stripped)
    except (ValueError, TypeError):
        return None


def _evaluate_single_concept(
    concept_id: str,
    inputs: dict[str, Any],
    correct_value: float | None,
    learner_answer: str | None,
    is_primary: bool = False,
    learner_workings: str | None = None,
    template_registry: dict[str, Any] | None = None,
) -> ConceptEvaluation | None:
    _treg = template_registry if template_registry is not None else TEMPLATE_REGISTRY
    template = _treg.get(concept_id)
    if template is None:
        return None
    try:
        truth = template.solve(inputs)
    except Exception as exc:
        _logger.warning("template.solve(%s) failed: %s", concept_id, exc)
        return None
    if not truth or truth.get("is_nan", False):
        return None

    result = truth.get("result")
    truth_steps = truth.get("steps", [])

    # Parse learner workings and match against truth steps
    parsed_learner = parse_learner_workings(learner_workings or "")
    step_matches = match_learner_steps(truth_steps, parsed_learner)

    # Build step evaluations populated with actual values from matching
    step_evals: list[StepEvaluation] = []
    for i, s in enumerate(truth_steps or []):
        match_info = step_matches[i] if i < len(step_matches) else {}
        step_evals.append(
            StepEvaluation(
                step_id=s.get("step_id", ""),
                description=s.get("description", ""),
                expected=float(s.get("value", 0)) if s.get("value") is not None else None,
                actual=match_info.get("actual"),
                match=bool(match_info.get("match", False)),
            )
        )

    # Error classification
    error_tags: list[str] = []
    if correct_value is not None and result is not None:
        if not _value_matches(result, correct_value):
            error_tags.append("final_answer_mismatch")

    # Step-level error tags from matching
    step_error_tags = compute_step_error_tags(step_matches)
    error_tags.extend(step_error_tags)

    # Classify via template if learner answer available
    if learner_answer is not None:
        try:
            learner_val = float(learner_answer)
            learner_steps = [{"step_id": "learner_final", "value": learner_val}]
            tags_from_template = template.classify_errors(learner_steps, truth)
            error_tags.extend(tags_from_template)
        except (ValueError, TypeError):
            pass

    confidence = 0.9 if is_primary else 0.7
    if error_tags:
        confidence = max(0.3, confidence - len(error_tags) * 0.1)

    return ConceptEvaluation(
        concept_id=concept_id,
        template_version=getattr(template, "template_version", "1.0.0"),
        result=float(result) if result is not None else None,
        is_nan=truth.get("is_nan", False),
        steps=step_evals,
        error_tags=error_tags,
        confidence=confidence,
        inputs_used=dict(inputs),
    )


def _extract_inputs_for_concept(
    concept_id: str,
    nums: list[dict[str, Any]],
    question: str,
) -> dict[str, Any] | None:
    """Extract numerical parameters from question text for a given concept.

    Uses the same candidate functions as the numerical solver's Tier 3,
    returning the first plausible parameter set.
    """
    from studyplan.numerical_solver import _FORMULA_CANDIDATES

    formula_name = concept_id.split(".", 1)[1] if "." in concept_id else concept_id
    candidate_fn = _FORMULA_CANDIDATES.get(formula_name)
    if candidate_fn is None:
        return None
    param_sets = candidate_fn(nums)
    if not param_sets:
        return None
    return param_sets[0]


def _value_matches(ref: float, candidate: float) -> bool:
    if math.isnan(ref) or math.isnan(candidate):
        return False
    abs_tol = max(0.01, abs(ref) * 0.005)
    return abs(ref - candidate) <= abs_tol
