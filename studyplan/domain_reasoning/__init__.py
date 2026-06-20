"""Domain reasoning layer: deterministic concept-aware evaluation.

Pure, GTK-free package with explicit concept metadata, executable
templates, evaluation pipeline, and structured diagnostic output.
"""

from __future__ import annotations

from studyplan.domain_reasoning.concepts import (
    ConceptMetadata,
    BUILTIN_CONCEPTS,
    STRUCTURE_TYPE_CONCEPTS,
    detect_concepts,
)

from studyplan.domain_reasoning.templates import (
    ConceptTemplate,
    TEMPLATE_REGISTRY,
    run_template,
    FormulaTemplate,
)

from studyplan.domain_reasoning.diagnostics import (
    StepEvaluation,
    ConceptEvaluation,
    QuestionDiagnostic,
    merge_concept_results,
    format_error_summary,
)

from studyplan.domain_reasoning.evaluator import (
    evaluate_question,
)

from studyplan.domain_reasoning.reasoning_engine import (
    ReasoningTrace,
    PlanStep,
    ExecutionRecord,
    reason_question,
)

__all__ = [
    "ConceptMetadata",
    "ConceptTemplate",
    "FormulaTemplate",
    "StepEvaluation",
    "ConceptEvaluation",
    "QuestionDiagnostic",
    "ReasoningTrace",
    "PlanStep",
    "ExecutionRecord",
    "BUILTIN_CONCEPTS",
    "STRUCTURE_TYPE_CONCEPTS",
    "TEMPLATE_REGISTRY",
    "detect_concepts",
    "run_template",
    "evaluate_question",
    "reason_question",
    "merge_concept_results",
    "format_error_summary",
]
