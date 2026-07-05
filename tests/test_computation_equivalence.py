"""Golden equivalence harness for Computation collapse.

This test file is the *specification oracle* for the computation path.
If ALL tests here pass, you may safely delete ``ExpressionTemplate`` and
replace it with ``CognitiveRuntime + ComputationProcess + interpreters``.

No tolerance unless numerically required (float comparison uses
``abs(actual - expected) < 1e-9``).

Equivalence is asserted for all three public methods::

    solve(inputs)           → result dict
    evaluate_steps(steps)   → list of comparisons
    classify_errors(steps)  → list of error tags

Every test runs BOTH the legacy path (``ExpressionTemplate.*``) and the
runtime path (``CognitiveRuntime.execute → interpreter.interpret``)
and asserts byte-level identity within float precision.
"""

import math
from typing import Any

import pytest

from studyplan.domain_reasoning import declare_formula
from studyplan.domain_reasoning.formula_registry import ExpressionTemplate

from studyplan.cci import (
    CognitiveRuntime,
    ComputationResultInterpreter,
    ComputationErrorInterpreter,
    ComputationStepEvaluator,
)
from studyplan.frontends.finance import ComputationProcess

# =========================================================================
# Fixtures — register formulas used by all equivalence tests
# =========================================================================

NPV_CONCEPT = "golden.npv"
WACC_CONCEPT = "golden.wacc"
IRR_CONCEPT = "golden.irr"


def _get_solver_and_expr(concept_id: str) -> tuple[Any, str | None]:
    from studyplan.domain_reasoning.formula_registry import _registry

    decl = _registry[concept_id]
    return decl.template._solver, decl.template._expression


def _run_runtime_path(
    concept_id: str,
    solver: Any,
    expression: str | None,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Execute the runtime path and return the interpret() result dict."""
    runtime = CognitiveRuntime()
    process = ComputationProcess(concept_id, solver, expression)
    trace = runtime.execute(process, inputs)
    return ComputationResultInterpreter(concept_id, expression).interpret(trace)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_results_identical(
    legacy: dict[str, Any],
    runtime: dict[str, Any],
) -> None:
    """Assert two result dicts are identical within float tolerance.

    Checks every field that ``ExpressionTemplate.solve()`` produces.
    Float comparison uses absolute tolerance (1e-9).
    """
    assert legacy["concept_id"] == runtime["concept_id"]
    assert legacy["inputs"] == runtime["inputs"]
    assert legacy["is_nan"] == runtime["is_nan"]

    lr, rr = legacy["result"], runtime["result"]
    if lr is None and rr is None:
        pass
    elif isinstance(lr, float) and math.isnan(lr) and isinstance(rr, float) and math.isnan(rr):
        pass
    else:
        assert lr is not None and rr is not None  # type narrowing
        assert abs(float(lr) - float(rr)) < 1e-9, f"result mismatch: {lr} != {rr}"

    assert len(legacy["steps"]) == len(runtime["steps"])
    for ls, rs in zip(legacy["steps"], runtime["steps"], strict=True):
        assert ls["step_id"] == rs["step_id"]
        assert ls.get("description") == rs.get("description")
        assert abs(ls["value"] - rs["value"]) < 1e-9
        assert ls["formula"] == rs["formula"]


def _assert_evals_identical(
    legacy: list[dict[str, Any]],
    runtime: list[dict[str, Any]],
) -> None:
    """Assert two evaluate_steps outputs are identical."""
    assert len(legacy) == len(runtime)
    for le, re in zip(legacy, runtime, strict=True):
        assert le["step_id"] == re["step_id"]
        assert le["match"] == re["match"]
        le_exp, re_exp = le["expected"], re["expected"]
        if le_exp is None and re_exp is None:
            pass
        elif isinstance(le_exp, float) and math.isnan(le_exp) and isinstance(re_exp, float) and math.isnan(re_exp):
            pass
        else:
            assert le_exp is not None and re_exp is not None  # type narrowing
            assert abs(float(le_exp) - float(re_exp)) < 1e-9
        le_act, re_act = le["actual"], re["actual"]
        if le_act is None and re_act is None:
            pass
        elif isinstance(le_act, float) and math.isnan(le_act) and isinstance(re_act, float) and math.isnan(re_act):
            pass
        else:
            assert le_act is not None and re_act is not None  # type narrowing
            assert abs(float(le_act) - float(re_act)) < 1e-9


def _assert_tags_identical(
    legacy: list[str],
    runtime: list[str],
) -> None:
    """Assert two classify_errors outputs are identical (exact string match)."""
    assert legacy == runtime


# ---------------------------------------------------------------------------
# Module setup / teardown
# ---------------------------------------------------------------------------


def setup_module() -> None:
    declare_formula(
        NPV_CONCEPT,
        expression="cash_flow / (1 + rate) ** years",
        param_names=["cash_flow", "rate", "years"],
        param_kinds=["value", "percent", "value"],
        output_slot="npv",
    )
    declare_formula(
        WACC_CONCEPT,
        expression="ke * eq + kd * (1 - tx) * debt",
        param_names=["ke", "eq", "kd", "tx", "debt"],
        param_kinds=["percent", "percent", "percent", "percent", "percent"],
        output_slot="wacc",
    )
    declare_formula(
        IRR_CONCEPT,
        expression="cash_flow / investment",
        param_names=["cash_flow", "investment"],
        param_kinds=["value", "value"],
        output_slot="irr",
    )


def teardown_module() -> None:
    from studyplan.domain_reasoning.formula_registry import _registry

    for cid in [NPV_CONCEPT, WACC_CONCEPT, IRR_CONCEPT]:
        _registry.pop(cid, None)


# =========================================================================
# Equivalence: solve()
# =========================================================================


class TestSolveEquivalence:
    """Golden gate: runtime ``solve()`` must match ``ExpressionTemplate.solve()``."""

    @pytest.mark.parametrize(
        "concept,inputs",
        [
            (NPV_CONCEPT, {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0}),
            (NPV_CONCEPT, {"cash_flow": 5000.0, "rate": 0.08, "years": 5.0}),
            (NPV_CONCEPT, {"cash_flow": 100.0, "rate": 0.05, "years": 10.0}),
            (NPV_CONCEPT, {"cash_flow": 0.0, "rate": 0.10, "years": 1.0}),
            (WACC_CONCEPT, {"ke": 0.12, "eq": 0.6, "kd": 0.08, "tx": 0.30, "debt": 0.4}),
            (WACC_CONCEPT, {"ke": 0.10, "eq": 0.5, "kd": 0.06, "tx": 0.25, "debt": 0.5}),
            (IRR_CONCEPT, {"cash_flow": 500.0, "investment": 1000.0}),
        ],
    )
    def test_solve(self, concept: str, inputs: dict[str, Any]) -> None:
        solver, expr = _get_solver_and_expr(concept)

        legacy = ExpressionTemplate(concept, solver, expr).solve(inputs)
        runtime = _run_runtime_path(concept, solver, expr, inputs)

        _assert_results_identical(legacy, runtime)

    @pytest.mark.parametrize(
        "concept,inputs",
        [
            (NPV_CONCEPT, {"cash_flow": 1000.0, "rate": 0.10}),  # missing years
            (WACC_CONCEPT, {"ke": 0.12}),  # missing 4 params
            (IRR_CONCEPT, {}),  # empty
        ],
    )
    def test_solve_missing_inputs(self, concept: str, inputs: dict[str, Any]) -> None:
        """Missing inputs produce ``is_nan=True`` and ``result=None`` in both paths."""
        solver, expr = _get_solver_and_expr(concept)

        legacy = ExpressionTemplate(concept, solver, expr).solve(inputs)
        runtime = _run_runtime_path(concept, solver, expr, inputs)

        assert legacy["is_nan"] is True
        assert runtime["is_nan"] is True
        assert legacy["result"] is None or (isinstance(legacy["result"], float) and math.isnan(legacy["result"]))
        assert runtime["result"] is None or (isinstance(runtime["result"], float) and math.isnan(runtime["result"]))


# =========================================================================
# Equivalence: evaluate_steps()
# =========================================================================


class TestEvaluateStepsEquivalence:
    """Golden gate: runtime ``evaluate_steps()`` must match template."""

    @pytest.mark.parametrize(
        "concept,inputs,learner_steps",
        [
            (
                NPV_CONCEPT,
                {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0},
                [{"step_id": "npv", "value": 909.09}],
            ),
            (
                NPV_CONCEPT,
                {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0},
                [
                    {"step_id": "npv", "value": 909.09},
                    {"step_id": "wrong", "value": 1000.0},
                ],
            ),
            (
                WACC_CONCEPT,
                {"ke": 0.12, "eq": 0.6, "kd": 0.08, "tx": 0.30, "debt": 0.4},
                [{"step_id": "wacc", "value": 0.0944}],
            ),
        ],
    )
    def test_evaluate_steps(
        self,
        concept: str,
        inputs: dict[str, Any],
        learner_steps: list[dict[str, Any]],
    ) -> None:
        solver, expr = _get_solver_and_expr(concept)

        truth = ExpressionTemplate(concept, solver, expr).solve(inputs)
        legacy = ExpressionTemplate(concept, solver, expr).evaluate_steps(learner_steps, truth)

        runtime = CognitiveRuntime()
        process = ComputationProcess(concept, solver, expr)
        trace = runtime.execute(process, inputs)
        runtime_evals = ComputationStepEvaluator().interpret(trace, learner_steps=learner_steps)

        _assert_evals_identical(legacy, runtime_evals)

    def test_evaluate_steps_empty(self) -> None:
        """Empty learner steps produce empty eval list."""
        solver, expr = _get_solver_and_expr(NPV_CONCEPT)
        inputs = {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0}

        truth = ExpressionTemplate(NPV_CONCEPT, solver, expr).solve(inputs)
        legacy = ExpressionTemplate(NPV_CONCEPT, solver, expr).evaluate_steps([], truth)

        runtime = CognitiveRuntime()
        process = ComputationProcess(NPV_CONCEPT, solver, expr)
        trace = runtime.execute(process, inputs)
        runtime_evals = ComputationStepEvaluator().interpret(trace, learner_steps=[])

        _assert_evals_identical(legacy, runtime_evals)

    def test_evaluate_steps_nan_truth(self) -> None:
        """NaN truth gracefully produces all-mismatch evals."""
        solver, expr = _get_solver_and_expr(NPV_CONCEPT)
        inputs = {"cash_flow": 1000.0, "rate": 0.10}  # missing years → NaN

        truth = ExpressionTemplate(NPV_CONCEPT, solver, expr).solve(inputs)
        legacy = ExpressionTemplate(NPV_CONCEPT, solver, expr).evaluate_steps(
            [{"step_id": "npv", "value": 909.09}],
            truth,
        )

        runtime = CognitiveRuntime()
        process = ComputationProcess(NPV_CONCEPT, solver, expr)
        trace = runtime.execute(process, inputs)
        runtime_evals = ComputationStepEvaluator().interpret(
            trace,
            learner_steps=[{"step_id": "npv", "value": 909.09}],
        )

        _assert_evals_identical(legacy, runtime_evals)


# =========================================================================
# Equivalence: classify_errors()
# =========================================================================


class TestClassifyErrorsEquivalence:
    """Golden gate: runtime ``classify_errors()`` must match template."""

    @pytest.mark.parametrize(
        "concept,inputs,learner_steps",
        [
            (
                NPV_CONCEPT,
                {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0},
                [{"step_id": "npv", "value": 800.0}],  # wrong
            ),
            (
                NPV_CONCEPT,
                {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0},
                [{"step_id": "npv", "value": 909.09}],  # correct (tolerance)
            ),
            (
                NPV_CONCEPT,
                {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0},
                [{"step_id": "npv", "value": "not_a_number"}],  # parse error
            ),
            (
                WACC_CONCEPT,
                {"ke": 0.12, "eq": 0.6, "kd": 0.08, "tx": 0.30, "debt": 0.4},
                [{"step_id": "wacc", "value": 0.05}],  # wrong
            ),
        ],
    )
    def test_classify_errors(
        self,
        concept: str,
        inputs: dict[str, Any],
        learner_steps: list[dict[str, Any]],
    ) -> None:
        solver, expr = _get_solver_and_expr(concept)

        truth = ExpressionTemplate(concept, solver, expr).solve(inputs)
        legacy = ExpressionTemplate(concept, solver, expr).classify_errors(learner_steps, truth)

        runtime = CognitiveRuntime()
        process = ComputationProcess(concept, solver, expr)
        trace = runtime.execute(process, inputs)
        runtime_tags = ComputationErrorInterpreter().interpret(trace, learner_steps=learner_steps)

        _assert_tags_identical(legacy, runtime_tags)

    def test_classify_errors_nan_truth(self) -> None:
        """NaN truth produces empty tags (no comparison possible)."""
        solver, expr = _get_solver_and_expr(NPV_CONCEPT)
        inputs = {"cash_flow": 1000.0, "rate": 0.10}  # missing years

        truth = ExpressionTemplate(NPV_CONCEPT, solver, expr).solve(inputs)
        legacy = ExpressionTemplate(NPV_CONCEPT, solver, expr).classify_errors(
            [{"step_id": "npv", "value": 800.0}],
            truth,
        )

        runtime = CognitiveRuntime()
        process = ComputationProcess(NPV_CONCEPT, solver, expr)
        trace = runtime.execute(process, inputs)
        runtime_tags = ComputationErrorInterpreter().interpret(
            trace,
            learner_steps=[{"step_id": "npv", "value": 800.0}],
        )

        _assert_tags_identical(legacy, runtime_tags)
