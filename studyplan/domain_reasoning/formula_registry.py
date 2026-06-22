"""Declarative formula registration system.

Auto-generates solvers, candidates, detection, templates, and concept
metadata from a single ``declare_formula()`` call.

Usage::

    declare_formula("fm.mirr",
        expression="((terminal_value / initial_investment) ** (1/n)) - 1",
        patterns=[r"\\bMIRR\\b"], param_names=["terminal_value", "initial_investment", "n"],
        label="Modified internal rate of return", output_slot="mirr",
    )

This one line auto-generates:
  - A solver function (evaluates the expression with variable substitution)
  - A candidate extractor (heuristic mapping from extracted numbers → params)
  - Detection regex signatures
  - A single-step template with the formula shown
  - Concept metadata for BUILTIN_CONCEPTS, _FORMULA_TO_CONCEPT, etc.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ParamKind = str  # "value" | "percent" | "list"


@dataclass
class FormulaDecl:
    """Complete declaration for one formula concept.

    All fields except ``concept_id`` can be auto-generated; the module-level
    ``declare_formula()`` helper fills them in.
    """
    concept_id: str
    formula_name: str                    # e.g. "mirr" (concept_id without "fm.")
    solver_fn: Callable[..., float]      # callable that takes named params → float
    candidate_fn: Callable[..., list[dict[str, Any]]]  # nums → param-candidate list
    compiled_patterns: list[re.Pattern]  # detection regexes (compiled)
    template: Any                         # single-step or custom ConceptTemplate
    expression: str | None               # None if a hand-written solver was provided
    param_names: tuple[str, ...]
    param_kinds: tuple[ParamKind, ...]
    label: str
    output_slot: str
    priority: int
    diagnostic_tags: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    centrality: float = 0.5
    chapter_refs: tuple[str, ...] = ()
    structure_types: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

_registry: dict[str, FormulaDecl] = {}
_next_priority: int = 1000


def get_registry() -> dict[str, FormulaDecl]:
    return dict(_registry)


def get_registry_formulas() -> list[str]:
    return [d.formula_name for d in _registry.values()]


# ---------------------------------------------------------------------------
# Expression solver (variable substitution via eval with restricted env)
# ---------------------------------------------------------------------------

def _substitute_and_eval(expr: str, env: dict[str, float]) -> float:
    """Evaluate *expr* with variable names replaced by values in *env*.

    Uses a safe AST walk + restricted ``eval()``.
    """
    safe_builtins: dict[str, Any] = {
        "sqrt": math.sqrt, "abs": abs,
        "float": float, "int": int, "round": round,
        "sum": sum, "len": len, "min": min, "max": max,
    }

    # Build locals from env; fail if any name is unresolvable
    locals_dict: dict[str, float] = {}
    # Pre-parse to find all names that aren't built-in
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        raise ValueError(f"Invalid expression: {expr}")

    # Collect required names
    collector = _NameCollector()
    collector.visit(tree)

    for name in collector.names:
        if name in env:
            locals_dict[name] = float(env[name])
        elif name in safe_builtins:
            pass  # built-in, no need to add to locals
        else:
            raise NameError(f"Variable '{name}' not provided in env")

    # Use the module-level safe_expression_evaluate with env
    from studyplan.numerical_solver import safe_expression_evaluate
    result = safe_expression_evaluate(expr, env=locals_dict)
    if result is None:
        raise ValueError("Expression evaluation returned None")
    return result


class _NameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.names.add(node.id)

    def visit_Call(self, node: ast.Call) -> None:
        # Don't traverse function name as a variable
        if isinstance(node.func, ast.Name):
            for arg in node.args:
                self.visit(arg)
            for kw in node.keywords:
                self.visit(kw)
        else:
            self.generic_visit(node)


def _make_expression_solver(
    expr: str,
    param_names: tuple[str, ...],
) -> Callable[..., float]:
    """Return a function that substitutes params into *expr* and evaluates."""
    def solver(**kwargs: Any) -> float:
        env: dict[str, float] = {}
        for name in param_names:
            val = kwargs.get(name)
            if val is None:
                return float("nan")
            if isinstance(val, (int, float)):
                env[name] = float(val)
            else:
                return float("nan")
        try:
            result = _substitute_and_eval(expr, env)
            if result is None:
                return float("nan")
            return float(result)
        except Exception:
            return float("nan")

    return solver


# ---------------------------------------------------------------------------
# Auto-candidate generation
# ---------------------------------------------------------------------------

def _make_candidate_fn(
    param_names: tuple[str, ...],
    param_kinds: tuple[ParamKind, ...],
) -> Callable[..., list[dict[str, Any]]]:
    """Heuristic candidate extractor for simple scalar formulas."""
    percent_params = [
        name for name, kind in zip(param_names, param_kinds) if kind == "percent"
    ]
    value_params = [
        name for name, kind in zip(param_names, param_kinds) if kind == "value"
    ]

    def candidate_fn(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        values = [n["value"] for n in nums if not n["is_percent"]]
        pcts = [n["value"] for n in nums if n["is_percent"]]
        if len(values) < len(value_params) or len(pcts) < len(percent_params):
            return []
        sorted_vals = sorted(values, reverse=True)
        sorted_pcts = sorted(pcts, reverse=True)
        params: dict[str, Any] = {}
        for i, name in enumerate(value_params):
            params[name] = sorted_vals[i] if i < len(sorted_vals) else sorted_vals[-1]
        for i, name in enumerate(percent_params):
            params[name] = sorted_pcts[i] if i < len(sorted_pcts) else sorted_pcts[-1]
        return [dict(params)]

    return candidate_fn


# ---------------------------------------------------------------------------
# Auto-template
# ---------------------------------------------------------------------------

class ExpressionTemplate:
    """Minimal ConceptTemplate implementation for expression-based formulas."""

    concept_id: str
    template_version: str

    def __init__(
        self,
        concept_id: str,
        solver_fn: Callable[..., float],
        expression: str | None,
        version: str = "1.0.0",
    ) -> None:
        self.concept_id = concept_id
        self.template_version = version
        self._solver = solver_fn
        self._expression = expression

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        result = self._solver(**inputs)
        result_dict: dict[str, Any] = {
            "concept_id": self.concept_id,
            "result": result,
            "inputs": dict(inputs),
            "is_nan": isinstance(result, float) and math.isnan(result),
        }
        steps: list[dict[str, Any]] = []
        if self._expression:
            display_expr = self._expression
            for k, v in inputs.items():
                if isinstance(v, (int, float)):
                    display_expr = display_expr.replace(k, f"{v}")
            steps.append({
                "step_id": self.concept_id.replace("fm.", "", 1),
                "description": f"{self.concept_id} formula",
                "value": result,
                "formula": display_expr,
            })
        result_dict["steps"] = steps
        return result_dict

    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not learner_steps or not truth:
            return []
        truth_result = truth.get("result")
        results: list[dict[str, Any]] = []
        for step in learner_steps:
            step_val = step.get("value")
            if step_val is not None and truth_result is not None:
                match = abs(float(step_val) - float(truth_result)) < max(0.01, abs(float(truth_result)) * 0.005)
            else:
                match = False
            results.append({
                "step_id": step.get("step_id", ""),
                "expected": truth_result,
                "actual": step_val,
                "match": match,
            })
        return results

    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]:
        tags: list[str] = []
        if not learner_steps or not truth:
            return tags
        truth_result = truth.get("result")
        if truth_result is None or (isinstance(truth_result, float) and math.isnan(truth_result)):
            return tags
        for step in learner_steps:
            step_val = step.get("value")
            step_id = step.get("step_id", "")
            if step_id and step_val is not None:
                try:
                    diff = abs(float(step_val) - float(truth_result))
                    if diff > max(0.01, abs(float(truth_result)) * 0.005):
                        tags.append(f"{step_id}_mismatch")
                except (ValueError, TypeError):
                    tags.append(f"{step_id}_parse_error")
        return tags


# ---------------------------------------------------------------------------
# Declare API
# ---------------------------------------------------------------------------

# Shared priority counter ensures declaration order is preserved in detection
_last_priority: int = 1000


def declare_formula(
    concept_id: str,
    *,
    expression: str | None = None,
    solver_fn: Callable[..., float] | None = None,
    patterns: list[str] | None = None,
    param_names: list[str] | tuple[str, ...] | None = None,
    param_kinds: list[ParamKind] | tuple[ParamKind, ...] | None = None,
    label: str = "",
    output_slot: str | None = None,
    diagnostic_tags: list[str] | tuple[str, ...] | None = None,
    dependencies: list[str] | tuple[str, ...] | None = None,
    centrality: float = 0.5,
    chapter_refs: list[str] | tuple[str, ...] | None = None,
    structure_types: list[str] | tuple[str, ...] | None = None,
    custom_candidate_fn: Callable[..., list[dict[str, Any]]] | None = None,
    multi_step_template: Any | None = None,
) -> FormulaDecl:
    """Declare a formula concept.

    Auto-generates solver, candidate extractor, detection patterns, and
    template — no other wiring needed.  Existing hand-written solvers can be
    passed via ``solver_fn`` to wrap them in the same infrastructure.

    Parameters
    ----------
    concept_id : str
        Unique identifier (e.g. ``"fm.pe_ratio"``).
    expression : str, optional
        Math expression with variable names.  Mutually exclusive with
        ``solver_fn``.  Example: ``"market_price / eps"``.
    solver_fn : callable, optional
        Existing hand-written solver function.  Mutually exclusive with
        ``expression``.
    patterns : list[str], optional
        Regex patterns for question-text detection.  If omitted, no detection
        (concept is only reachable via explicit template_ref).
    param_names : list[str], optional
        Parameter names in order (used for candidate generation).  Required
        when ``expression`` or ``custom_candidate_fn`` is provided.  When
        ``solver_fn`` is used and no ``custom_candidate_fn``, defaults to
        ``inspect.signature(solver_fn).parameters``.
    param_kinds : list[ParamKind], optional
        ``"value"`` or ``"percent"`` per param.  Defaults to all ``"value"``.
    label : str
        Human-readable name.  Defaults to concept_id.
    output_slot : str, optional
        Slot name for dependency resolution.  Defaults to formula name (e.g.
        ``"pe_ratio"`` for ``"fm.pe_ratio"``).
    diagnostic_tags : list[str], optional
        Error classification tags.
    dependencies : list[str], optional
        Concept IDs this depends on.
    centrality : float
        Syllabus centrality 0-1.
    chapter_refs : list[str], optional
        Syllabus chapter references.
    structure_types : list[str], optional
        Structure type groups to appear in.
    custom_candidate_fn : callable, optional
        Override auto-generated candidate function.
    multi_step_template : Any, optional
        Override auto-generated single-step template with a hand-written one.
    """
    global _last_priority
    _last_priority += 1
    priority = _last_priority

    formula_name = concept_id.replace("fm.", "", 1) if concept_id.startswith("fm.") else concept_id

    if param_names is not None:
        pnames = tuple(param_names)
    else:
        pnames = ()

    if param_kinds is not None:
        pkinds = tuple(param_kinds)
    else:
        pkinds = tuple(["value"] * len(pnames))

    # -- Solver --
    if expression:
        if solver_fn:
            raise ValueError("Provide expression or solver_fn, not both")
        if not pnames:
            raise ValueError("param_names required with expression")
        solver_fn = _make_expression_solver(expression, pnames)
    elif solver_fn is None:
        raise ValueError("Either expression or solver_fn is required")

    # -- Candidate --
    if custom_candidate_fn:
        candidate_fn = custom_candidate_fn
    else:
        candidate_fn = _make_candidate_fn(pnames, pkinds)

    # -- Detection --
    compiled_patterns: list[re.Pattern] = []
    if patterns:
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    # -- Template --
    if multi_step_template:
        template = multi_step_template
    else:
        template = ExpressionTemplate(concept_id, solver_fn, expression)

    # -- Metadata defaults --
    slot = output_slot or formula_name
    lbl = label or concept_id
    tags = tuple(diagnostic_tags or ())
    deps = tuple(dependencies or ())
    chaps = tuple(chapter_refs or ())
    stypes = tuple(structure_types or ())

    decl = FormulaDecl(
        concept_id=concept_id,
        formula_name=formula_name,
        solver_fn=solver_fn,
        candidate_fn=candidate_fn,
        compiled_patterns=compiled_patterns,
        template=template,
        expression=expression,
        param_names=pnames,
        param_kinds=pkinds,
        label=lbl,
        output_slot=slot,
        priority=priority,
        diagnostic_tags=tags,
        dependencies=deps,
        centrality=centrality,
        chapter_refs=chaps,
        structure_types=stypes,
    )
    _registry[concept_id] = decl
    return decl


# ---------------------------------------------------------------------------
# Build helpers for existing data structures
# ---------------------------------------------------------------------------

def build_solver_dict(base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``formula_name → solver_fn`` for all registered formulas."""
    result = dict(base or {})
    for cid, decl in _registry.items():
        if decl.formula_name not in result:
            result[decl.formula_name] = decl.solver_fn
    return result


def build_candidate_dict(base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``formula_name → candidate_fn`` for all registered formulas."""
    result = dict(base or {})
    for cid, decl in _registry.items():
        if decl.formula_name not in result:
            result[decl.formula_name] = decl.candidate_fn
    return result


def build_signatures(
    base: list[tuple[str, list[re.Pattern], int]] | None = None,
) -> list[tuple[str, list[re.Pattern], int]]:
    """Return ``(formula_name, [Pattern], priority)`` list."""
    result = list(base or [])
    existing_names = {name for name, _, _ in result}
    # Sort by priority to preserve declaration order
    sorted_decls = sorted(_registry.values(), key=lambda d: d.priority)
    for decl in sorted_decls:
        if decl.formula_name not in existing_names and decl.compiled_patterns:
            result.append((decl.formula_name, decl.compiled_patterns, decl.priority))
            existing_names.add(decl.formula_name)
    return result


def build_concept_dict(
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``concept_id → ConceptMetadata`` from registered formulas."""
    from studyplan.domain_reasoning.concepts import ConceptMetadata
    result = dict(base or {})
    for cid, decl in _registry.items():
        if cid not in result:
            result[cid] = ConceptMetadata(
                concept_id=cid,
                label=decl.label,
                template_ref=cid,
                dependencies=decl.dependencies,
                output_slots=(decl.output_slot,),
                diagnostic_tags=decl.diagnostic_tags,
                centrality=decl.centrality,
                chapter_refs=decl.chapter_refs,
            )
    return result


def build_formula_to_concept(
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return ``formula_name → concept_id`` mapping."""
    result = dict(base or {})
    for cid, decl in _registry.items():
        if decl.formula_name not in result:
            result[decl.formula_name] = cid
    return result


def build_template_registry(
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``concept_id → template`` for all registered formulas."""
    result = dict(base or {})
    for cid, decl in _registry.items():
        if cid not in result:
            result[cid] = decl.template
    return result


def build_structure_type_concepts(
    base: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Merge registered formulas into structure-type groups."""
    result = dict(base or {})
    for cid, decl in _registry.items():
        for st in decl.structure_types:
            if st in result:
                if cid not in result[st]:
                    result[st].append(cid)
            else:
                result[st] = [cid]
    return result


# ---------------------------------------------------------------------------
# Demo / new formula registrations via the DSL
# ---------------------------------------------------------------------------

declare_formula("fm.dividend_growth_rate",
    expression="roe * retention_ratio",
    patterns=[r"\bdividend growth\b", r"\bgrowth.*model\b", r"\bretention.*growth\b"],
    param_names=["roe", "retention_ratio"],
    param_kinds=["percent", "percent"],
    label="Dividend growth rate (g = ROE × retention ratio)",
    output_slot="dividend_growth_rate",
    diagnostic_tags=["roe_error", "retention_error"],
    centrality=0.6,
    chapter_refs=["business_finance"],
    structure_types=["dividend_policy_tradeoff"],
)

declare_formula("fm.earning_yield",
    expression="eps / market_price",
    patterns=[r"\bearning yield\b", r"\bE/P\b", r"\bearnings.*price\b", r"\bEarnings yield\b"],
    param_names=["eps", "market_price"],
    param_kinds=["value", "value"],
    label="Earnings yield (EY = EPS / Market price)",
    output_slot="earning_yield",
    diagnostic_tags=["eps_error", "price_error"],
    centrality=0.55,
    chapter_refs=["business_finance"],
    structure_types=["dividend_policy_tradeoff"],
)

declare_formula("fm.quick_ratio",
    expression="(current_assets - inventory) / current_liabilities",
    patterns=[r"\bquick ratio\b", r"\bacid test\b", r"\bliquid ratio\b"],
    param_names=["current_assets", "inventory", "current_liabilities"],
    param_kinds=["value", "value", "value"],
    label="Quick ratio (acid test)",
    output_slot="quick_ratio",
    diagnostic_tags=["asset_error", "liability_error"],
    centrality=0.5,
    chapter_refs=["business_finance"],
    structure_types=["working_capital_cycle"],
)

declare_formula("fm.asset_turnover",
    expression="sales / capital_employed",
    patterns=[r"\basset turnover\b", r"\bcapital turnover\b", r"\bsales.*capital employed\b"],
    param_names=["sales", "capital_employed"],
    param_kinds=["value", "value"],
    label="Asset turnover (Sales / Capital employed)",
    output_slot="asset_turnover",
    diagnostic_tags=["sales_error", "capital_error"],
    centrality=0.55,
    chapter_refs=["business_finance"],
    structure_types=["working_capital_cycle"],
)
