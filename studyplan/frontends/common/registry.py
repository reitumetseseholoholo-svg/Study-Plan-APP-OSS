"""Domain-agnostic process factory — dispatches concept IDs to process types.

Used by application code that needs to create the right
:class:`~studyplan.cci.process.CognitiveProcess` subclass from a
registered concept declaration without importing every frontend directly.
"""

from __future__ import annotations

from typing import Any

from studyplan.cci.process import CognitiveProcess


def process_from_registry(
    concept_id: str,
    registry: dict[str, Any] | None = None,
) -> CognitiveProcess | None:
    """Look up a ``FormulaDecl`` from the concept registry and return the
    corresponding ``CognitiveProcess`` subclass.

    Supports all four algebra types::

        process = process_from_registry("fm.wacc")
        if process is not None:
            trace = CognitiveRuntime().execute(process, {"ke": 0.12, ...})

    Returns ``None`` if the concept is not registered or has no compatible
    solver / template.
    """
    if registry is None:
        try:
            from studyplan.domain_reasoning.formula_registry import _registry as reg
        except ImportError:
            return None
    else:
        reg = registry

    decl = reg.get(concept_id)
    if decl is None:
        return None

    concept_type = str(getattr(decl, "concept_type", "") or "")

    # Computation — wraps solver fn
    if concept_type in ("computation_formula", "computation"):
        solver = getattr(decl, "solver_fn", None)
        if solver is not None:
            from studyplan.frontends.finance.computation import ComputationProcess

            return ComputationProcess(
                concept_id,
                solver,
                expression=getattr(decl, "expression", None),
            )
        return None

    # Template-based processes
    template = getattr(decl, "template", None)
    if template is None:
        return None

    if concept_type in ("classification",):
        from studyplan.frontends.finance.classification import ClassificationProcess

        return ClassificationProcess(template)

    if concept_type in ("evaluation_process", "evaluation"):
        from studyplan.frontends.finance.evaluation import EvaluationProcess

        return EvaluationProcess(template)

    if concept_type in ("diagnostic_process", "diagnostic"):
        from studyplan.frontends.finance.diagnostic import DiagnosticProcess

        return DiagnosticProcess(template)

    return None
