"""Expression-based concept (existing single-step formula).

This is a re-export of the existing ``ExpressionTemplate`` from
``formula_registry.py``, exposed through the type-consistent factory
interface so that ``declare_concept(type="expression")`` works via the
same path as all other types.
"""

from __future__ import annotations

from typing import Any, Callable

from studyplan.domain_reasoning.formula_registry import (
    ExpressionTemplate as _ExpressionTemplate,
    _make_expression_solver,
)


def make_expression_template(
    concept_id: str,
    expression: str,
    param_names: tuple[str, ...],
) -> _ExpressionTemplate:
    """Factory: build an ``ExpressionTemplate`` from an expression string.

    This is called by ``declare_concept(type="expression")`` to create the
    solver template that the reasoning engine uses.
    """
    solver = _make_expression_solver(expression, param_names)
    return _ExpressionTemplate(
        concept_id=concept_id,
        solver_fn=solver,
        expression=expression,
    )


def make_expression_candidate_fn(
    expression: str,
    param_names: tuple[str, ...],
    param_kinds: tuple[str, ...],
    solver_fn: Callable[..., float] | None = None,
) -> Callable[..., list[dict[str, Any]]]:
    """Build a candidate extractor for an expression-based concept."""
    from studyplan.domain_reasoning.formula_registry import _make_candidate_fn

    return _make_candidate_fn(param_names, param_kinds, solver_fn)


# Re-export so consumers can ``from ...concept_types import ExpressionTemplate``
ExpressionTemplate = _ExpressionTemplate
