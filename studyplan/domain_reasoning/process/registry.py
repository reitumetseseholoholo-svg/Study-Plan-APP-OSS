"""``declare_process`` — unified process declaration API.

Usage::

    # Computation (delegates to existing declare_formula)
    declare_process(
        "fm.wacc",
        type="computation",
        expression="ke * eq + kd * (1 - tx) * debt",
        param_names=["ke", "eq", "kd", "tx", "debt"],
        param_kinds=["percent", "percent", "percent", "percent", "percent"],
        output="wacc",
    )

    # Diagnostic (Bayesian belief updating)
    declare_process(
        "med.chest_pain_ddx",
        type="diagnostic",
        hypotheses=[...],
        features=[...],
        likelihoods={...},
        output="primary_diagnosis",
    )
"""

from __future__ import annotations

import re
from typing import Any

from studyplan.domain_reasoning.formula_registry import (
    FormulaDecl,
    declare_formula,
    _registry,
    _last_priority,
)
from studyplan.domain_reasoning.process.diagnostic import (
    DiagnosticConfig,
    ProcessHypothesis,
    ProcessFeature,
    ProcessAction,
    make_diagnostic_template,
)
from studyplan.domain_reasoning.process.evaluation import (
    EvaluationConfig,
    EvaluationCriterion,
    EvaluationTemplate,
)


def declare_process(
    concept_id: str,
    *,
    type: str = "computation",
    # Computation-specific
    expression: str | None = None,
    param_names: list[str] | tuple[str, ...] | None = None,
    param_kinds: list[str] | tuple[str, ...] | None = None,
    # Diagnostic-specific
    hypotheses: list[ProcessHypothesis] | None = None,
    features: list[ProcessFeature] | None = None,
    likelihoods: dict[str, dict[str, Any]] | None = None,
    investigations: list[ProcessAction] | None = None,
    update: str = "bayesian",
    stop_when: str = "max_posterior > 0.95",
    # Evaluation-specific
    criteria: list[EvaluationCriterion] | None = None,
    candidates: list[str] | None = None,
    # Common
    patterns: list[str] | None = None,
    label: str = "",
    output: str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    dependencies: list[str] | tuple[str, ...] | None = None,
    centrality: float = 0.5,
    chapter_refs: list[str] | tuple[str, ...] | None = None,
    structure_types: list[str] | tuple[str, ...] | None = None,
) -> FormulaDecl:
    """Declare a cognitive process of the given *type*.

    ``type="computation"`` delegates to ``declare_formula`` with the
    expression-based template.

    ``type="diagnostic"`` creates a Bayesian belief-updating template
    that maintains a distribution over hypotheses.
    """
    if type == "computation":
        return declare_formula(  # type: ignore[no-any-return]
            concept_id,
            expression=expression,
            patterns=patterns,
            param_names=param_names,
            param_kinds=param_kinds,
            label=label,
            output_slot=output,
            diagnostic_tags=tags,
            dependencies=dependencies,
            centrality=centrality,
            chapter_refs=chapter_refs,
            structure_types=structure_types,
        )

    if type == "diagnostic":
        return _declare_diagnostic_process(
            concept_id,
            hypotheses=hypotheses or [],
            features=features or [],
            likelihoods=likelihoods or {},
            investigations=investigations or [],
            update=update,
            stop_when=stop_when,
            patterns=patterns,
            label=label,
            output=output,
            tags=tags,
            dependencies=dependencies,
            centrality=centrality,
            chapter_refs=chapter_refs,
            structure_types=structure_types,
        )

    if type == "evaluation":
        return _declare_evaluation_process(
            concept_id,
            criteria=criteria or [],
            candidates=candidates or [],
            patterns=patterns,
            label=label,
            output=output,
            tags=tags,
            dependencies=dependencies,
            centrality=centrality,
            chapter_refs=chapter_refs,
            structure_types=structure_types,
        )

    raise ValueError(f"Unknown process type: {type!r}. Expected 'computation', 'diagnostic', or 'evaluation'.")


def _declare_diagnostic_process(
    concept_id: str,
    *,
    hypotheses: list[ProcessHypothesis],
    features: list[ProcessFeature],
    likelihoods: dict[str, dict[str, Any]],
    investigations: list[ProcessAction],
    update: str,
    stop_when: str,
    patterns: list[str] | None = None,
    label: str = "",
    output: str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    dependencies: list[str] | tuple[str, ...] | None = None,
    centrality: float = 0.5,
    chapter_refs: list[str] | tuple[str, ...] | None = None,
    structure_types: list[str] | tuple[str, ...] | None = None,
) -> FormulaDecl:
    """Register a diagnostic process in the concept registry."""
    global _last_priority
    _last_priority += 1

    config = DiagnosticConfig(
        hypotheses=list(hypotheses),
        features=list(features),
        likelihoods=dict(likelihoods),
        update=update,
        stop_when=stop_when,
        investigations=list(investigations),
        output=output or "primary_diagnosis",
    )

    template = make_diagnostic_template(concept_id, config)

    compiled_patterns: list[re.Pattern] = []
    if patterns:
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    slot = output or config.output
    tag_tup = tuple(tags or ())
    dep_tup = tuple(dependencies or ())
    chap_tup = tuple(chapter_refs or ())
    styp_tup = tuple(structure_types or ())

    decl = FormulaDecl(
        concept_id=concept_id,
        concept_type="diagnostic_process",
        formula_name=concept_id.split(".", 1)[-1] if "." in concept_id else concept_id,
        solver_fn=None,
        candidate_fn=None,
        compiled_patterns=compiled_patterns,
        template=template,
        expression=None,
        param_names=(),
        param_kinds=(),
        label=label or concept_id,
        output_slot=slot,
        priority=_last_priority,
        diagnostic_tags=tag_tup,
        dependencies=dep_tup,
        centrality=centrality,
        chapter_refs=chap_tup,
        structure_types=styp_tup,
    )
    _registry[concept_id] = decl
    return decl


def _declare_evaluation_process(
    concept_id: str,
    *,
    criteria: list[EvaluationCriterion],
    candidates: list[str],
    patterns: list[str] | None = None,
    label: str = "",
    output: str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
    dependencies: list[str] | tuple[str, ...] | None = None,
    centrality: float = 0.5,
    chapter_refs: list[str] | tuple[str, ...] | None = None,
    structure_types: list[str] | tuple[str, ...] | None = None,
) -> FormulaDecl:
    """Register an evaluation process in the concept registry."""
    global _last_priority
    _last_priority += 1

    config = EvaluationConfig(
        criteria=list(criteria),
        candidates=list(candidates),
        output=output or "judgment",
    )

    template = EvaluationTemplate(concept_id, config)

    compiled_patterns: list[re.Pattern] = []
    if patterns:
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    slot = output or config.output
    tag_tup = tuple(tags or ())
    dep_tup = tuple(dependencies or ())
    chap_tup = tuple(chapter_refs or ())
    styp_tup = tuple(structure_types or ())

    decl = FormulaDecl(
        concept_id=concept_id,
        concept_type="evaluation_process",
        formula_name=concept_id.split(".", 1)[-1] if "." in concept_id else concept_id,
        solver_fn=None,
        candidate_fn=None,
        compiled_patterns=compiled_patterns,
        template=template,
        expression=None,
        param_names=(),
        param_kinds=(),
        label=label or concept_id,
        output_slot=slot,
        priority=_last_priority,
        diagnostic_tags=tag_tup,
        dependencies=dep_tup,
        centrality=centrality,
        chapter_refs=chap_tup,
        structure_types=styp_tup,
    )
    _registry[concept_id] = decl
    return decl
