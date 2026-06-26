"""Rule-chain concept — conditional bands, thresholds, and multi-step rules.

A rule chain models concepts like income tax computation, where each step
evaluates a series of conditional rules (e.g. tax bands, allowance tapers)
and the output of one step feeds into the next.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Rule expression evaluator
# ---------------------------------------------------------------------------

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "max": max, "min": min, "round": round,
    "float": float, "int": int, "sum": sum,
}


def _eval_rule_expression(
    expr: str,
    env: dict[str, float],
) -> float:
    """Evaluate a rule expression in *env*, returning a float.

    Supports arithmetic (``+``, ``-``, ``*``, ``/``, ``**``, ``%``),
    comparison operators (``<=``, ``>=``, ``<``, ``>``, ``==``, ``!=``),
    boolean operators (``and``, ``or``, ``not``), ternary (``x if c else y``),
    and the functions ``max()``, ``min()``, ``abs()``, ``round()``.

    Comparison expressions return ``1.0`` (True) or ``0.0`` (False).
    """
    import ast

    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        raise ValueError(f"Invalid rule expression: {expr}")

    # Safety check: only allow known node types
    _validate_safe(tree)

    # Build env from provided values
    locals_dict: dict[str, Any] = dict(_SAFE_BUILTINS)
    collector = _NameCollector()
    collector.visit(tree)
    for name in collector.names:
        if name in env:
            locals_dict[name] = float(env[name])
        elif name in _SAFE_BUILTINS:
            pass
        else:
            raise NameError(f"Variable '{name}' not provided in rule env")

    try:
        code = compile(tree, "<rule_expr>", "eval")
        result = eval(code, {"__builtins__": {}}, locals_dict)
        if isinstance(result, bool):
            return 1.0 if result else 0.0
        if isinstance(result, (int, float)):
            return float(result)
        raise ValueError(f"Expression returned non-numeric: {result!r}")
    except Exception as e:
        if isinstance(e, (ValueError, NameError, ZeroDivisionError)):
            raise
        raise ValueError(f"Rule expression evaluation failed: {e}")


_SAFE_NODES = frozenset({
    ast.Expression, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Pow, ast.Mod, ast.USub, ast.UAdd,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.And, ast.Or, ast.Not,
    ast.Compare, ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq,
    ast.Constant,
    ast.Call, ast.Name, ast.Load,
    ast.IfExp,
})


def _validate_safe(tree: ast.AST) -> None:
    """Raise ``ValueError`` if *tree* contains an unsafe node type."""
    for node in ast.walk(tree):
        if type(node) not in _SAFE_NODES:
            raise ValueError(f"Unsafe node type in expression: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Complex call target")
            if node.func.id not in ("max", "min", "abs", "round", "float", "int"):
                raise ValueError(f"Disallowed function: {node.func.id}")


class _NameCollector:
    """Collect ``ast.Name`` nodes (variable references) from an expression."""
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit(self, node: Any) -> None:
        import ast
        if isinstance(node, ast.Name):
            self.names.add(node.id)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                for arg in node.args:
                    self.visit(arg)
                for kw in node.keywords:
                    self.visit(kw)
        elif isinstance(node, ast.Expr):
            self.visit(node.value)
        elif isinstance(node, ast.Expression):
            self.visit(node.body)
        elif isinstance(node, ast.BinOp):
            self.visit(node.left)
            self.visit(node.right)
        elif isinstance(node, ast.UnaryOp):
            self.visit(node.operand)
        elif isinstance(node, ast.BoolOp):
            for v in node.values:
                self.visit(v)
        elif isinstance(node, ast.Compare):
            self.visit(node.left)
            for c in node.comparators:
                self.visit(c)
        elif isinstance(node, ast.IfExp):
            self.visit(node.test)
            self.visit(node.body)
            self.visit(node.orelse)


# ---------------------------------------------------------------------------
# Rule / step data structures
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    """A single conditional rule within a rule-chain step.

    When ``condition`` evaluates to True, the rule's ``value`` is used.
    ``condition`` can be a boolean expression string or the literal ``True``
    (catch-all / default case).
    """
    condition: str | bool
    value: str | float


@dataclass
class RuleChainStep:
    """One step in a rule-chain concept.

    Each step has a ``slot`` (output name), a list of ordered ``rules``,
    and optional ``param_names`` whose values must be available in the
    execution context.  Rules are evaluated in order; the first matching
    rule's value becomes the step output.
    """
    slot: str
    rules: list[Rule]
    description: str = ""
    param_names: tuple[str, ...] = ()
    expression: str = ""


@dataclass
class RuleChainConfig:
    """Configuration for a ``rule_chain`` type concept.

    Pass this to ``declare_concept(type="rule_chain")`` via the
    ``concept_config`` parameter.
    """
    steps: list[RuleChainStep]
    output_slot: str


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

class RuleChainTemplate:
    """ConceptTemplate implementation for conditional rule chains.

    Executes steps in order.  Within each step, rules are evaluated in
    order; the first matching rule determines the step output.  Step
    outputs are available by slot name to later steps.
    """

    concept_id: str
    template_version: str

    def __init__(
        self,
        concept_id: str,
        steps: list[RuleChainStep],
        version: str = "1.0.0",
    ) -> None:
        self.concept_id = concept_id
        self.template_version = version
        self._steps = steps

    # ------------------------------------------------------------------
    # Public API (ConceptTemplate protocol)
    # ------------------------------------------------------------------

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ctx: dict[str, float] = {}
        for k, v in inputs.items():
            if isinstance(v, (int, float)):
                ctx[str(k)] = float(v)

        step_results: list[dict[str, Any]] = []
        final_value: float | None = None

        for step in self._steps:
            step_env = dict(ctx)
            for pname in step.param_names:
                val = ctx.get(pname)
                if val is not None:
                    step_env[pname] = val

            matched_rule_value: float | None = None
            matched_condition: str = "none"

            for rule in step.rules:
                cond = rule.condition
                if isinstance(cond, bool):
                    if cond:
                        matched_rule_value = self._resolve_value(rule.value, step_env)
                        matched_condition = "True (catch-all)"
                        break
                else:
                    try:
                        cond_val = _eval_rule_expression(cond, step_env)
                        if bool(cond_val):
                            matched_rule_value = self._resolve_value(rule.value, step_env)
                            matched_condition = cond
                            break
                    except (ValueError, NameError, ZeroDivisionError):
                        continue

            if matched_rule_value is None:
                matched_rule_value = 0.0

            step_results.append({
                "step_id": step.slot,
                "description": step.description or f"Step: {step.slot}",
                "value": matched_rule_value,
                "matched_condition": matched_condition,
                "formula": step.expression or matched_condition,
            })

            ctx[step.slot] = matched_rule_value
            final_value = matched_rule_value

        is_nan = final_value is None or (isinstance(final_value, float) and math.isnan(final_value))
        return {
            "concept_id": self.concept_id,
            "result": final_value,
            "inputs": dict(inputs),
            "is_nan": is_nan,
            "steps": step_results,
        }

    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not learner_steps or not truth:
            return []
        truth_result = truth.get("result")
        truth_steps = truth.get("steps", [])
        results: list[dict[str, Any]] = []

        for i, step in enumerate(learner_steps):
            expected_val: Any = None
            if i < len(truth_steps):
                expected_val = truth_steps[i].get("value")
            step_val = step.get("value")
            if step_val is not None and expected_val is not None:
                match = abs(float(step_val) - float(expected_val)) < max(0.01, abs(float(expected_val)) * 0.02)
            else:
                match = False
            results.append({
                "step_id": step.get("step_id", str(i)),
                "expected": expected_val,
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
        truth_steps = truth.get("steps", [])
        for i, step in enumerate(learner_steps):
            expected_val: Any = None
            if i < len(truth_steps):
                expected_val = truth_steps[i].get("value")
            step_val = step.get("value")
            step_id = step.get("step_id", f"step_{i}")
            if step_val is not None and expected_val is not None:
                try:
                    diff = abs(float(step_val) - float(expected_val))
                    tol = max(0.01, abs(float(expected_val)) * 0.02)
                    if diff > tol:
                        tags.append(f"{step_id}_mismatch")
                except (ValueError, TypeError):
                    tags.append(f"{step_id}_value_error")
            elif step_val is None and expected_val is not None:
                tags.append(f"{step_id}_missing")
        return tags

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_value(
        self,
        val: str | float,
        env: dict[str, float],
    ) -> float:
        """Resolve a rule value which may be a literal or expression string."""
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return _eval_rule_expression(val, env)
        except (ValueError, NameError, ZeroDivisionError):
            return float("nan")


# ---------------------------------------------------------------------------
# Candidate extractor for rule chains
# ---------------------------------------------------------------------------

def _make_rule_chain_candidate_fn(
    steps: list[RuleChainStep],
    template: RuleChainTemplate,
) -> Callable[..., list[dict[str, Any]]]:
    """Build a candidate function for rule chains.

    Rule-chain candidate extraction is simpler than expression-based:
    we look for bracketed values, thresholds, and percentage amounts
    in the question text, then try the solver.  The best result is
    determined by plausibility (non-NaN, non-zero, reasonable magnitude).
    """
    def candidate_fn(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        values = [n["value"] for n in nums]
        if not values:
            return []
        candidates: list[dict[str, Any]] = []
        for v in values:
            try:
                result = template.solve({"dummy": v})
                val = result.get("result")
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    candidates.append({"input_value": v, "result": val})
            except Exception:
                continue
        return candidates[:3]

    return candidate_fn


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_rule_template(
    concept_id: str,
    config: RuleChainConfig,
) -> RuleChainTemplate:
    """Factory: build a ``RuleChainTemplate`` from configuration."""
    return RuleChainTemplate(
        concept_id=concept_id,
        steps=config.steps,
    )
