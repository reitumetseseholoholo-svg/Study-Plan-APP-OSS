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
import itertools
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
# Registry validation
# ---------------------------------------------------------------------------

class RegistryValidationError(Exception):
    """Raised when the formula registry has structural errors."""


def validate_registry() -> list[str]:
    """Check the registry for structural issues.

    Returns a list of warning/error messages (empty = clean).
    """
    messages: list[str] = []
    concept_ids = set(_registry.keys())

    for cid, decl in _registry.items():
        for dep in decl.dependencies:
            if dep not in concept_ids and dep not in BUILTIN_CONCEPT_IDS:
                messages.append(f"{cid}: dependency '{dep}' not found in registry or builtins")
        if cid.startswith("fm."):
            fname = cid[3:]
            if fname != decl.formula_name:
                messages.append(f"{cid}: formula_name mismatch ({decl.formula_name})")

    # Circular dependency check
    _visited: set[str] = set()
    _in_progress: set[str] = set()

    def _visit(node: str, path: list[str]) -> None:
        if node in _in_progress:
            cycle = " → ".join(path + [node])
            messages.append(f"Circular dependency: {cycle}")
            return
        if node in _visited or node not in concept_ids:
            return
        _in_progress.add(node)
        decl = _registry.get(node)
        if decl:
            for dep in decl.dependencies:
                _visit(dep, path + [node])
        _in_progress.discard(node)
        _visited.add(node)

    for cid in _registry:
        _visit(cid, [])

    return messages


BUILTIN_CONCEPT_IDS: set[str] = set()


def _init_builtin_ids() -> None:
    """Populate BUILTIN_CONCEPT_IDS from concepts module."""
    global BUILTIN_CONCEPT_IDS
    try:
        from studyplan.domain_reasoning.concepts import BUILTIN_CONCEPTS as _bc
        BUILTIN_CONCEPT_IDS = set(_bc.keys())
    except ImportError:
        BUILTIN_CONCEPT_IDS = set()


_init_builtin_ids()


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

    locals_dict: dict[str, float] = {}
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        raise ValueError(f"Invalid expression: {expr}")

    collector = _NameCollector()
    collector.visit(tree)

    for name in collector.names:
        if name in env:
            locals_dict[name] = float(env[name])
        elif name in safe_builtins:
            pass
        else:
            raise NameError(f"Variable '{name}' not provided in env")

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
    """Return a function that substitutes params into *expr* and evaluates.

    All keyword arguments are forwarded to the expression environment,
    enabling intermediate values from prior chain steps to be available.
    """
    def solver(**kwargs: Any) -> float:
        env: dict[str, float] = {}
        # Required params — if any are missing, return nan
        for name in param_names:
            val = kwargs.get(name)
            if val is None:
                return float("nan")
            if isinstance(val, (int, float)):
                env[name] = float(val)
            else:
                return float("nan")
        # Forward all kwargs (includes intermediate chain values)
        for k, v in kwargs.items():
            if k not in env and isinstance(v, (int, float)):
                env[k] = float(v)
        try:
            result = _substitute_and_eval(expr, env)
            if result is None:
                return float("nan")
            return float(result)
        except Exception:
            return float("nan")

    return solver


# ---------------------------------------------------------------------------
# Auto-candidate generation — permutation-aware
# ---------------------------------------------------------------------------

def _make_candidate_fn(
    param_names: tuple[str, ...],
    param_kinds: tuple[ParamKind, ...],
    solver_fn: Callable[..., float] | None = None,
) -> Callable[..., list[dict[str, Any]]]:
    """Permutation-aware candidate extractor.

    Tries every assignment of extracted numbers to parameter names and
    picks the assignment(s) that produce the most plausible solver output.
    """
    value_param_indices = [
        i for i, kind in enumerate(param_kinds) if kind == "value"
    ]
    percent_param_indices = [
        i for i, kind in enumerate(param_kinds) if kind == "percent"
    ]

    def _plausible_score(val: float) -> float:
        if math.isnan(val) or math.isinf(val):
            return -1.0
        if val <= 0:
            return 0.1
        if val < 1e-6:
            return 0.2
        if val > 1e12:
            return 0.3
        return 1.0

    def candidate_fn(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        values = [n["value"] for n in nums if not n["is_percent"]]
        pcts = [n["value"] for n in nums if n["is_percent"]]

        if len(values) < len(value_param_indices) or len(pcts) < len(percent_param_indices):
            return []

        scored: list[tuple[float, dict[str, Any]]] = []

        # Try all permutations of values → value params
        val_perms = list(itertools.permutations(values, len(value_param_indices)))

        # Try all permutations of percents → percent params
        pct_perms = list(itertools.permutations(pcts, len(percent_param_indices))) if percent_param_indices else [()]

        for vp in val_perms:
            for pp in pct_perms:
                candidate: dict[str, Any] = {}
                for idx, name in enumerate(param_names):
                    if idx in value_param_indices:
                        vi = value_param_indices.index(idx)
                        candidate[name] = float(vp[vi]) if vi < len(vp) else float(values[-1])
                    elif idx in percent_param_indices:
                        pi = percent_param_indices.index(idx)
                        candidate[name] = float(pp[pi]) if pi < len(pp) else float(pcts[-1])
                    else:
                        candidate[name] = 0.0

                if solver_fn is not None:
                    try:
                        result = solver_fn(**candidate)
                        score = _plausible_score(result)
                    except Exception:
                        score = -1.0
                else:
                    score = 0.5

                scored.append((score, dict(candidate)))

        if not scored:
            return []

        # Sort by plausibility score descending, return top 3
        scored.sort(key=lambda x: -x[0])
        best_score = scored[0][0]
        return [c for s, c in scored[:3] if s >= max(0.0, best_score - 0.5)]

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
# Chain template — multi-step formula declarations
# ---------------------------------------------------------------------------

@dataclass
class ChainStep:
    """One step in a multi-step formula chain."""
    slot: str
    expression: str
    param_names: tuple[str, ...]
    param_kinds: tuple[ParamKind, ...] = ()
    description: str = ""


class ChainTemplate:
    """Multi-step ConceptTemplate that executes expressions sequentially.

    Each step produces an output that can be consumed by subsequent steps
    via its slot name.  The final step's output is the chain result.
    """

    concept_id: str
    template_version: str

    def __init__(
        self,
        concept_id: str,
        steps: list[ChainStep],
        version: str = "1.0.0",
    ) -> None:
        self.concept_id = concept_id
        self.template_version = version
        self._steps = steps
        self._solvers: list[Callable[..., float]] = []
        for step in steps:
            solver = _make_expression_solver(step.expression, step.param_names)
            self._solvers.append(solver)

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ctx: dict[str, Any] = dict(inputs)
        step_results: list[dict[str, Any]] = []
        final_result: float | None = None

        for i, (step, solver) in enumerate(zip(self._steps, self._solvers)):
            step_inputs: dict[str, Any] = {}
            # Step-specific params
            for pname in step.param_names:
                val = ctx.get(pname)
                if val is not None:
                    step_inputs[pname] = val
                else:
                    step_inputs[pname] = 0.0
            # Include intermediate values from prior steps
            for k, v in ctx.items():
                if k not in step_inputs:
                    step_inputs[k] = v

            try:
                result = solver(**step_inputs)
            except Exception:
                result = float("nan")

            # Build display expression
            display = step.expression
            for k, v in step_inputs.items():
                if isinstance(v, (int, float)):
                    display = display.replace(k, f"{v}")

            step_results.append({
                "step_id": step.slot,
                "description": step.description or f"Step {i+1}: {step.slot}",
                "value": result,
                "formula": display,
            })

            if math.isnan(result):
                break

            ctx[step.slot] = result
            final_result = result

        is_nan = final_result is None or math.isnan(final_result)
        result_dict: dict[str, Any] = {
            "concept_id": self.concept_id,
            "result": final_result,
            "inputs": dict(inputs),
            "is_nan": is_nan,
            "steps": step_results,
        }
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
            step_id = step.get("step_id", "")
            if step_val is not None and truth_result is not None:
                match = abs(float(step_val) - float(truth_result)) < max(0.01, abs(float(truth_result)) * 0.005)
            else:
                match = False
            results.append({
                "step_id": step_id,
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
        chain_steps = {s.slot for s in self._steps}
        for step in learner_steps:
            step_val = step.get("value")
            step_id = step.get("step_id", "")
            if step_id in chain_steps and step_val is not None:
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
        candidate_fn = _make_candidate_fn(pnames, pkinds, solver_fn)

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


def declare_formula_chain(
    concept_id: str,
    *,
    steps: list[dict[str, Any]],
    patterns: list[str] | None = None,
    label: str = "",
    output_slot: str | None = None,
    diagnostic_tags: list[str] | tuple[str, ...] | None = None,
    dependencies: list[str] | tuple[str, ...] | None = None,
    centrality: float = 0.5,
    chapter_refs: list[str] | tuple[str, ...] | None = None,
    structure_types: list[str] | tuple[str, ...] | None = None,
) -> FormulaDecl:
    """Declare a multi-step formula chain.

    Each step is a dict with keys:
      - ``slot`` (required): output slot name for this step
      - ``expression`` (required): math expression with variable names
      - ``param_names`` (optional, default []): param names for this step
      - ``param_kinds`` (optional, default all "value"): param kinds
      - ``description`` (optional): step description

    Steps are executed in order.  Each step's output is available by its
    ``slot`` name to all subsequent steps.  The chain's final result is
    the last step's value.

    Example::

        declare_formula_chain("fm.cost_of_equity_and_wacc",
            steps=[
                dict(slot="cost_equity", expression="risk_free + beta * (market_return - risk_free)",
                     param_names=["risk_free", "beta", "market_return"]),
                dict(slot="wacc", expression="cost_equity * equity_weight + cost_debt * (1 - tax) * debt_weight",
                     param_names=["cost_debt", "tax", "equity_weight", "debt_weight"]),
            ],
            patterns=[r"\\bWACC\\b", r"\\bcost of capital\\b"],
            label="Cost of equity → WACC chain",
            output_slot="wacc",
        )
    """
    global _last_priority
    _last_priority += 1
    priority = _last_priority

    formula_name = concept_id.replace("fm.", "", 1) if concept_id.startswith("fm.") else concept_id

    if not steps:
        raise ValueError("At least one step is required for a formula chain")

    # Build ChainStep objects + collect unique named params with kinds
    chain_steps: list[ChainStep] = []
    all_param_names: list[str] = []
    all_param_kinds: list[str] = []
    seen_params: set[str] = set()
    for s in steps:
        slot = s.get("slot", "")
        expr = s.get("expression", "")
        if not slot:
            raise ValueError("Each chain step must have a non-empty 'slot'")
        if not expr:
            raise ValueError("Each chain step must have a non-empty 'expression'")
        pnames = tuple(s.get("param_names", []))
        pkinds = tuple(s.get("param_kinds", ["value"] * len(pnames)))
        desc = s.get("description", "")
        chain_steps.append(ChainStep(
            slot=slot, expression=expr,
            param_names=pnames, param_kinds=pkinds,
            description=desc,
        ))
        for i, p in enumerate(pnames):
            if p not in seen_params:
                seen_params.add(p)
                all_param_names.append(p)
                all_param_kinds.append(pkinds[i] if i < len(pkinds) else "value")

    pnames_tuple = tuple(all_param_names)
    pkinds_tuple = tuple(all_param_kinds)

    # Solver: chain solver that runs all steps
    template = ChainTemplate(concept_id, chain_steps)

    # Chain solver delegates to ChainTemplate.solve
    def _chain_solver(**kwargs: Any) -> float:
        result = template.solve(kwargs)
        val = result.get("result")
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return float("nan")
        return float(val)

    # Candidate: permutation-aware using last-step inputs
    candidate_fn = _make_candidate_fn(pnames_tuple, pkinds_tuple, _chain_solver)

    # Detection
    compiled_patterns: list[re.Pattern] = []
    if patterns:
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

    slot = output_slot or formula_name
    lbl = label or concept_id
    tags = tuple(diagnostic_tags or ())
    deps = tuple(dependencies or ())
    chaps = tuple(chapter_refs or ())
    stypes = tuple(structure_types or ())

    decl = FormulaDecl(
        concept_id=concept_id,
        formula_name=formula_name,
        solver_fn=_chain_solver,
        candidate_fn=candidate_fn,
        compiled_patterns=compiled_patterns,
        template=template,
        expression=None,
        param_names=pnames_tuple,
        param_kinds=pkinds_tuple,
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
# Formula registrations via the DSL
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

# --- Working capital efficiency ratios (common in Section C) ---

declare_formula("fm.receivables_days",
    expression="receivables / credit_sales * 365",
    patterns=[
        r"\breceivable.*day[s]?\b", r"\breceivable.*collection\b",
        r"\bdebtor.*day[s]?\b", r"\breceivable.*period\b",
    ],
    param_names=["receivables", "credit_sales"],
    param_kinds=["value", "value"],
    label="Receivables collection period (days)",
    output_slot="receivables_days",
    diagnostic_tags=["receivables_error", "sales_error"],
    centrality=0.55,
    chapter_refs=["working_capital"],
    structure_types=["working_capital_cycle"],
)

declare_formula("fm.payables_days",
    expression="payables / credit_purchases * 365",
    patterns=[
        r"\bpayable.*day[s]?\b", r"\bpayable.*payment\b",
        r"\bcreditor.*day[s]?\b", r"\bpayable.*period\b",
    ],
    param_names=["payables", "credit_purchases"],
    param_kinds=["value", "value"],
    label="Payables payment period (days)",
    output_slot="payables_days",
    diagnostic_tags=["payables_error", "purchases_error"],
    centrality=0.55,
    chapter_refs=["working_capital"],
    structure_types=["working_capital_cycle"],
)

declare_formula("fm.inventory_days",
    expression="inventory / cost_of_sales * 365",
    patterns=[
        r"\binventory.*day[s]?\b", r"\binventory.*holding\b",
        r"\bstock.*day[s]?\b", r"\binventory.*period\b",
    ],
    param_names=["inventory", "cost_of_sales"],
    param_kinds=["value", "value"],
    label="Inventory holding period (days)",
    output_slot="inventory_days",
    diagnostic_tags=["inventory_error", "cost_error"],
    centrality=0.55,
    chapter_refs=["working_capital"],
    structure_types=["working_capital_cycle"],
)

# --- Multi-step chains ---

declare_formula_chain("fm.cost_equity_capm_to_wacc",
    steps=[
        dict(
            slot="cost_equity",
            expression="risk_free + beta * (market_return - risk_free)",
            param_names=["risk_free", "beta", "market_return"],
            param_kinds=["percent", "value", "percent"],
            description="Cost of equity (CAPM)",
        ),
        dict(
            slot="wacc",
            expression="cost_equity * eq_weight + cost_debt * (1 - tax) * debt_weight",
            param_names=["cost_debt", "tax", "eq_weight", "debt_weight"],
            param_kinds=["percent", "percent", "percent", "percent"],
            description="Weighted average cost of capital",
        ),
    ],
    patterns=[r"\bWACC\b", r"\bweighted average cost\b", r"\bcost of capital\b"],
    label="Cost of equity (CAPM) → WACC",
    output_slot="wacc",
    diagnostic_tags=["capm_error", "weighting_error", "tax_error"],
    centrality=0.85,
    chapter_refs=["cost_of_capital"],
    structure_types=["wacc_optimization"],
)

declare_formula_chain("fm.cost_equity_dvm_to_wacc",
    steps=[
        dict(
            slot="cost_equity",
            expression="dividend * (1 + growth) / market_price + growth",
            param_names=["dividend", "growth", "market_price"],
            param_kinds=["value", "percent", "value"],
            description="Cost of equity (DVM)",
        ),
        dict(
            slot="wacc",
            expression="cost_equity * eq_weight + cost_debt * (1 - tax) * debt_weight",
            param_names=["cost_debt", "tax", "eq_weight", "debt_weight"],
            param_kinds=["percent", "percent", "percent", "percent"],
            description="Weighted average cost of capital",
        ),
    ],
    patterns=[r"\bWACC\b", r"\bdividend.*growth.*model.*wacc\b"],
    label="Cost of equity (DVM) → WACC",
    output_slot="wacc",
    diagnostic_tags=["dvm_error", "weighting_error", "tax_error"],
    centrality=0.85,
    chapter_refs=["cost_of_capital"],
    structure_types=["wacc_optimization"],
)

declare_formula_chain("fm.ungear_regear",
    steps=[
        dict(
            slot="asset_beta",
            expression="equity_beta / (1 + (1 - tax) * debt_equity)",
            param_names=["equity_beta", "tax", "debt_equity"],
            param_kinds=["value", "percent", "percent"],
            description="Ungear equity beta to asset beta",
        ),
        dict(
            slot="new_equity_beta",
            expression="asset_beta * (1 + (1 - tax) * new_debt_new_equity)",
            param_names=["tax", "new_debt_new_equity"],
            param_kinds=["percent", "percent"],
            description="Regear to new equity beta",
        ),
    ],
    patterns=[r"\bungear\b", r"\bregear\b", r"\basset beta\b.*\bnew equity\b"],
    label="Ungear and regear equity beta",
    output_slot="new_equity_beta",
    diagnostic_tags=["ungear_error", "regear_error", "tax_error"],
    centrality=0.7,
    chapter_refs=["business_finance"],
    structure_types=["gearing_financial_risk"],
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

# Run registry validation at module load time.
_validation_messages = validate_registry()
if _validation_messages:
    import logging
    _log = logging.getLogger(__name__)
    for msg in _validation_messages:
        _log.warning("Formula registry: %s", msg)
