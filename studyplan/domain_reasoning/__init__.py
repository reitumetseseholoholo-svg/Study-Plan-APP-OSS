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
    ErrorPattern,
    classify_step_errors,
    classify_step_id_error,
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

from studyplan.domain_reasoning.formula_registry import (
    declare_concept,
    declare_formula,
    declare_formula_chain,
)

from studyplan.domain_reasoning.auto_declare import (
    ProposedFormula,
    ValidationResult,
    FormulaDiscoveryResult,
    run_auto_discovery,
    extract_computational_outcomes,
    gather_questions_for_outcome,
    build_llm_prompt,
    parse_llm_response,
    validate_proposal,
    register_proposal,
    _default_question_filter,
)

# Load domain registries (ACCA FM, PMP, etc.)
from studyplan.domain_reasoning import domains  # noqa: F401

from studyplan.domain_reasoning.concept_types import (
    RuleChainTemplate,
    RuleChainStep,
    Rule,
    RuleChainConfig,
    LookupTemplate,
    LookupRule,
    LookupConfig,
    ClassificationTemplate,
    ClassificationNode,
    Branch,
    ClassificationConfig,
)

from studyplan.domain_reasoning.process import (
    ProcessTemplate,
    DiagnosticConfig,
    DiagnosticTemplate,
    ProcessHypothesis,
    ProcessFeature,
    ProcessAction,
    EvaluationConfig,
    EvaluationCriterion,
    EvaluationTemplate,
    declare_process,
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
    "ErrorPattern",
    "classify_step_errors",
    "classify_step_id_error",
    "declare_concept",
    "declare_formula",
    "declare_formula_chain",
    "ProposedFormula",
    "ValidationResult",
    "FormulaDiscoveryResult",
    "run_auto_discovery",
    "extract_computational_outcomes",
    "gather_questions_for_outcome",
    "build_llm_prompt",
    "parse_llm_response",
    "validate_proposal",
    "register_proposal",
    "RuleChainTemplate",
    "RuleChainStep",
    "Rule",
    "RuleChainConfig",
    "LookupTemplate",
    "LookupRule",
    "LookupConfig",
    "ClassificationTemplate",
    "ClassificationNode",
    "Branch",
    "ClassificationConfig",
    "ProcessTemplate",
    "DiagnosticConfig",
    "DiagnosticTemplate",
    "ProcessHypothesis",
    "ProcessFeature",
    "ProcessAction",
    "EvaluationConfig",
    "EvaluationCriterion",
    "EvaluationTemplate",
    "declare_process",
]
