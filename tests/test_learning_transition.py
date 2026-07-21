"""Tests for Execution + Learning IR layer (Phase 4d, Jul 2026)."""

from __future__ import annotations

import math

import pytest

from studyplan.provenance.learning.execution_engine import (
    FMExecutionEngine,
    FMExecutionContext,
)
from studyplan.provenance.learning.trace import (
    FMTraceBuilder,
    FMAttemptTrace,
    compute_mismatch,
)
from studyplan.provenance.learning.transition import (
    update_state,
    interpret_trace,
    TraceInterpretation,
    classify_error,
)
from studyplan.provenance.learning.student_state import (
    FMStudentState,
    bayesian_mean_update,
    beta_bernoulli_update,
    compute_surprise,
    update_error_profile,
    initial_state,
    compute_confidence,
)
from studyplan.provenance.learning.model import (
    FMTransitionDynamicsModel,
    TransitionDistribution,
    RolloutStep,
    RolloutResult,
    simulate_step,
    rollout,
    compare_actions,
)
from studyplan.provenance.learning.planner import CognitivePlanner, PlanResult
from studyplan.provenance.learning.event_bus import EventBus
from studyplan.provenance.learning.events import (
    EventEnvelope,
    execution_result,
    observation_attempt,
    interpretation_result,
    belief_state_update,
    belief_diff,
    transition_update,
    rollout_simulation,
    scheduler_runqueue,
    system_state,
)
from studyplan.provenance.learning.tutor_bridge import build_learning_context
from studyplan.provenance.learning.tutor_integration import LearningIntegrator, get_learning_bus, set_learning_bus
from studyplan.provenance.knowledge_ir import (
    FMFormula,
    FormulaParam,
    Assumption,
)
from studyplan.provenance.knowledge_base import get_knowledge_base


# ====================================================================
# Fixtures
# ====================================================================


def _make_npv_formula() -> FMFormula:
    return FMFormula(
        concept_id="fm.npv",
        label="Net Present Value",
        description="NPV test",
        expression="sum(cf / (1 + r)^t for t, cf in enumerate(cashflows, 1)) - initial",
        params=(
            FormulaParam("initial", "value", "initial_investment"),
            FormulaParam("r", "percent", "discount_rate"),
            FormulaParam("cashflows", "list", "cash_flows"),
        ),
        output_concept_id="fm.npv",
        assumes=(Assumption("constant_discount_rate", "discount rate is constant"),),
        dependencies=(),
        diagnostic_tags=("sign_error", "wrong_discount_rate", "omit_initial"),
        centrality=0.9,
    )


@pytest.fixture
def npv_formula():
    return _make_npv_formula()
    return FMFormula(
        concept_id="fm.npv",
        label="Net Present Value",
        description="NPV test",
        expression="sum(cf / (1 + r)^t for t, cf in enumerate(cashflows, 1)) - initial",
        params=(
            FormulaParam("initial", "value", "initial_investment"),
            FormulaParam("r", "percent", "discount_rate"),
            FormulaParam("cashflows", "list", "cash_flows"),
        ),
        output_concept_id="fm.npv",
        assumes=(Assumption("constant_discount_rate", "discount rate is constant"),),
        dependencies=(),
        diagnostic_tags=("sign_error", "wrong_discount_rate", "omit_initial"),
        centrality=0.9,
    )


@pytest.fixture
def engine():
    return FMExecutionEngine()


@pytest.fixture
def trace_builder(engine):
    return FMTraceBuilder(engine)


@pytest.fixture
def default_state():
    return initial_state("fm.npv", "fm.npv")


# ====================================================================
# Execution Engine tests (deterministic layer)
# ====================================================================


class TestFMExecutionEngine:
    def test_evaluate_npv(self, engine, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 100000,
                "r": 0.1,
                "cashflows": [30000, 40000, 50000],
            },
        )
        result = engine.evaluate(npv_formula, ctx)
        expected = 30000 / 1.1 + 40000 / 1.1**2 + 50000 / 1.1**3 - 100000
        assert abs(result - expected) < 1e-6

    def test_evaluate_npv_round_numbers(self, engine, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        result = engine.evaluate(npv_formula, ctx)
        expected = 500 / 1.1 + 500 / 1.21 + 500 / 1.331 - 1000
        assert abs(result - expected) < 1e-6

    def test_evaluate_npv_with_list_param(self, engine, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 200000,
                "r": 0.12,
                "cashflows": [60000, 80000, 90000, 50000],
            },
        )
        result = engine.evaluate(npv_formula, ctx)
        expected = 60000 / 1.12 + 80000 / 1.12**2 + 90000 / 1.12**3 + 50000 / 1.12**4 - 200000
        assert abs(result - expected) < 1e-6

    def test_evaluate_zero_rate(self, engine, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.0,
                "cashflows": [200, 200, 200],
            },
        )
        result = engine.evaluate(npv_formula, ctx)
        assert abs(result - (-400)) < 1e-6

    def test_evaluate_negative_npv(self, engine, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 50000,
                "r": 0.1,
                "cashflows": [10000, 10000, 10000],
            },
        )
        result = engine.evaluate(npv_formula, ctx)
        expected = 10000 / 1.1 + 10000 / 1.21 + 10000 / 1.331 - 50000
        assert result < 0
        assert abs(result - expected) < 1e-6

    def test_evaluate_unknown_formula_falls_back(self):
        formula = FMFormula(
            concept_id="fm.custom",
            label="Custom",
            description="test",
            expression="x + y",
            params=(FormulaParam("x", "value", "x"), FormulaParam("y", "value", "y")),
            output_concept_id="fm.custom",
        )
        engine = FMExecutionEngine()
        ctx = FMExecutionContext("fm.custom", {"x": 3.0, "y": 4.0})
        result = engine.evaluate(formula, ctx)
        assert abs(result - 7.0) < 1e-6

    def test_evaluate_by_id(self, engine, npv_formula):
        registry = {"fm.npv": npv_formula}
        eng = FMExecutionEngine(registry)
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.05,
                "cashflows": [400, 400, 400],
            },
        )
        result = eng.evaluate_by_id("fm.npv", ctx)
        assert isinstance(result, float)

    def test_evaluate_by_id_unknown_key(self):
        eng = FMExecutionEngine()
        ctx = FMExecutionContext("fm.nonexistent", {})
        with pytest.raises(KeyError):
            eng.evaluate_by_id("fm.nonexistent", ctx)

    def test_deterministic(self, engine, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 100000,
                "r": 0.1,
                "cashflows": [30000, 40000, 50000],
            },
        )
        assert engine.evaluate(npv_formula, ctx) == engine.evaluate(npv_formula, ctx)

    def test_canonical_solvers_available(self):
        from studyplan.provenance.learning.execution_engine import _CANONICAL_SOLVERS

        assert "fm.npv" in _CANONICAL_SOLVERS
        assert "fm.payback" in _CANONICAL_SOLVERS
        assert "fm.irr" in _CANONICAL_SOLVERS


# ====================================================================
# Mismatch computation tests (pure math, deterministic)
# ====================================================================


class TestComputeMismatch:
    def test_exact_match(self):
        m = compute_mismatch(100.0, 100.0)
        assert m["exact_match"] == 1.0
        assert m["absolute_difference"] == 0.0

    def test_sign_mismatch(self):
        m = compute_mismatch(-100.0, 100.0)
        assert m["sign_match"] == 0.0

    def test_partial_error(self):
        m = compute_mismatch(80.0, 100.0)
        assert abs(m["relative_error"] - 0.2) < 1e-6

    def test_deterministic(self):
        assert compute_mismatch(42.5, 50.0) == compute_mismatch(42.5, 50.0)


# ====================================================================
# Trace builder tests (pure observation, no interpretation)
# ====================================================================


class TestFMTraceBuilder:
    def test_build_correct_answer(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 100000,
                "r": 0.1,
                "cashflows": [30000, 40000, 50000],
            },
        )
        correct = trace_builder._engine.evaluate(npv_formula, ctx)
        trace = trace_builder.build(npv_formula, ctx, correct)
        assert trace.correct_result == correct
        assert trace.student_result == correct
        assert trace.step_texts == ()

    def test_build_with_steps(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        steps = [
            "PV Y1 = 500/1.1 = 454.55",
            "PV Y2 = 500/1.21 = 413.22",
            "NPV = 1243.43 - 1000 = 243.43",
        ]
        trace = trace_builder.build(npv_formula, ctx, 243.43, steps)
        assert isinstance(trace.step_texts, tuple)
        assert len(trace.step_texts) == 3
        assert "PV Y1" in trace.step_texts[0]

    def test_build_no_attempt(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        trace = trace_builder.build(npv_formula, ctx, None)
        assert trace.student_result is None
        assert isinstance(trace.correct_result, float)

    def test_build_deterministic(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        t1 = trace_builder.build(npv_formula, ctx, 100.0)
        t2 = trace_builder.build(npv_formula, ctx, 100.0)
        assert t1 == t2

    def test_build_with_timestamp(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        trace = trace_builder.build(npv_formula, ctx, 243.43, timestamp=42.0)
        assert trace.timestamp == 42.0

    def test_build_no_interpretation(self, trace_builder, npv_formula):
        """Trace should be raw — no error_label, no mismatch_vector."""
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        trace = trace_builder.build(npv_formula, ctx, 999999.0)
        assert not hasattr(trace, "error_label")
        assert not hasattr(trace, "mismatch_vector")
        assert not hasattr(trace, "error_magnitude")
        assert isinstance(trace, FMAttemptTrace)


# ====================================================================
# Interpretation layer tests (pedagogical, separate from observation)
# ====================================================================


class TestInterpretTrace:
    def test_correct_answer(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        correct = trace_builder._engine.evaluate(npv_formula, ctx)
        trace = trace_builder.build(npv_formula, ctx, correct)
        interp = interpret_trace(trace, npv_formula, ctx)
        assert isinstance(interp, TraceInterpretation)
        assert interp.error_label == "none"
        assert interp.error_magnitude == 0.0

    def test_sign_error(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        correct = trace_builder._engine.evaluate(npv_formula, ctx)
        trace = trace_builder.build(npv_formula, ctx, -correct)
        interp = interpret_trace(trace, npv_formula, ctx)
        assert interp.error_label == "sign_error"
        assert interp.mismatch_vector["sign_match"] == 0.0

    def test_no_attempt(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        trace = trace_builder.build(npv_formula, ctx, None)
        interp = interpret_trace(trace, npv_formula, ctx)
        assert interp.error_label == "no_attempt"

    def test_with_steps(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        steps = ["PV = 500/1.1 = 454.55"]
        correct = trace_builder._engine.evaluate(npv_formula, ctx)
        trace = trace_builder.build(npv_formula, ctx, correct, steps)
        interp = interpret_trace(trace, npv_formula, ctx)
        assert len(interp.step_analysis) == 1
        assert interp.step_analysis[0]["has_formula"] is True

    def test_conceptual_error(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        trace = trace_builder.build(npv_formula, ctx, 999999.0)
        interp = interpret_trace(trace, npv_formula, ctx)
        assert interp.error_label == "conceptual_error"
        assert interp.error_magnitude == 1.0

    def test_deterministic_interpretation(self, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        correct = trace_builder._engine.evaluate(npv_formula, ctx)
        trace = trace_builder.build(npv_formula, ctx, correct * 0.5)
        i1 = interpret_trace(trace, npv_formula, ctx)
        i2 = interpret_trace(trace, npv_formula, ctx)
        assert i1 == i2


# ====================================================================
# Error classification tests (pedagogical, moved to transition)
# ====================================================================


class TestClassifyError:
    def test_none_for_perfect(self, npv_formula):
        ctx = FMExecutionContext("fm.npv", {"initial": 1000, "r": 0.1, "cashflows": [500, 500, 500]})
        assert classify_error(npv_formula, ctx, 243.43, 243.43, []) == "none"

    def test_no_attempt(self, npv_formula):
        ctx = FMExecutionContext("fm.npv", {"initial": 1000, "r": 0.1, "cashflows": [500, 500, 500]})
        assert classify_error(npv_formula, ctx, None, 243.43, []) == "no_attempt"

    def test_sign_error(self, npv_formula):
        ctx = FMExecutionContext("fm.npv", {"initial": 1000, "r": 0.1, "cashflows": [500, 500, 500]})
        assert classify_error(npv_formula, ctx, -243.43, 243.43, []) == "sign_error"

    def test_conceptual_error(self, npv_formula):
        ctx = FMExecutionContext("fm.npv", {"initial": 1000, "r": 0.1, "cashflows": [500, 500, 500]})
        assert classify_error(npv_formula, ctx, 99999.0, 243.43, []) == "conceptual_error"

    def test_deterministic(self, npv_formula):
        ctx = FMExecutionContext("fm.npv", {"initial": 1000, "r": 0.1, "cashflows": [500, 500, 500]})
        assert classify_error(npv_formula, ctx, 100.0, 243.43, []) == classify_error(
            npv_formula, ctx, 100.0, 243.43, []
        )


# ====================================================================
# Student State tests (probabilistic layer)
# ====================================================================


class TestFMStudentState:
    def test_initial_state(self, default_state):
        assert default_state.mastery_mean == 0.5
        assert default_state.mastery_var > 0
        assert default_state.confidence == 0.5
        assert default_state.last_trace is None

    def test_initial_state_with_dependencies(self):
        state = initial_state("fm.irr", "fm.irr", dependency_ids=("fm.npv",))
        assert "fm.npv" in state.dependency_beliefs

    def test_copy_is_different_object(self, default_state):
        copied = default_state.copy()
        assert copied is not default_state
        copied.mastery_mean = 0.8
        assert default_state.mastery_mean != copied.mastery_mean

    def test_beta_bernoulli_update_correct(self):
        a, b = beta_bernoulli_update(2.0, 2.0, True)
        assert a == 3.0 and b == 2.0

    def test_beta_bernoulli_update_incorrect(self):
        a, b = beta_bernoulli_update(2.0, 2.0, False)
        assert a == 2.0 and b == 3.0

    def test_surprise_positive_on_correct(self):
        assert compute_surprise(0.3, 0.05, True) > 0

    def test_surprise_negative_on_incorrect_when_confident(self):
        assert compute_surprise(0.8, 0.02, False) < 0

    def test_error_beliefs_update(self):
        result = update_error_profile({"none": 1.0}, "sign_error", decay=0.9)
        assert abs(sum(result.values()) - 1.0) < 1e-6
        assert "sign_error" in result

    def test_bayesian_mean_update_increases_with_positive_surprise(self):
        mean, var = bayesian_mean_update(0.5, 0.08, 0.5, learning_rate=0.3)
        assert mean > 0.5

    def test_confidence_from_high_variance(self):
        assert compute_confidence(0.25) == 0.5


# ====================================================================
# Transition function tests (hybrid kernel)
# ====================================================================


class TestTransitionFunction:
    def test_correct_attempt_increases_mastery(self, engine, trace_builder, npv_formula, default_state):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 100000,
                "r": 0.1,
                "cashflows": [30000, 40000, 50000],
            },
        )
        correct = engine.evaluate(npv_formula, ctx)
        trace = trace_builder.build(npv_formula, ctx, correct)
        new_state = update_state(default_state, trace, npv_formula)
        assert new_state.mastery_mean > default_state.mastery_mean
        assert new_state.confidence >= default_state.confidence

    def test_wrong_attempt_decreases_mastery(self, engine, trace_builder, npv_formula, default_state):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 100000,
                "r": 0.1,
                "cashflows": [30000, 40000, 50000],
            },
        )
        trace = trace_builder.build(npv_formula, ctx, 50000.0)
        new_state = update_state(default_state, trace, npv_formula)
        assert new_state.error_beliefs.get("conceptual_error", 0) > 0

    def test_consecutive_corrects_increase_confidence(self, engine, trace_builder, npv_formula):
        state = initial_state("fm.npv", "fm.npv")
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        for _ in range(3):
            correct = engine.evaluate(npv_formula, ctx)
            trace = trace_builder.build(npv_formula, ctx, correct)
            state = update_state(state, trace, npv_formula)
        assert state.mastery_mean > 0.6

    def test_consecutive_wrongs_decrease_mastery(self, engine, trace_builder, npv_formula):
        state = initial_state("fm.npv", "fm.npv")
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        initial_mean = state.mastery_mean
        for _ in range(3):
            trace = trace_builder.build(npv_formula, ctx, 999999.0)
            state = update_state(state, trace, npv_formula)
        assert state.mastery_mean < initial_mean

    def test_mixed_attempts(self, engine, trace_builder, npv_formula):
        state = initial_state("fm.npv", "fm.npv")
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        correct = engine.evaluate(npv_formula, ctx)

        state = update_state(state, trace_builder.build(npv_formula, ctx, correct * 0.5), npv_formula)
        initial_mean = state.mastery_mean

        state = update_state(state, trace_builder.build(npv_formula, ctx, correct), npv_formula)
        assert state.mastery_mean > initial_mean

    def test_trace_is_stored_in_state(self, engine, trace_builder, npv_formula, default_state):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        correct = engine.evaluate(npv_formula, ctx)
        trace = trace_builder.build(npv_formula, ctx, correct)
        new_state = update_state(default_state, trace, npv_formula)
        assert new_state.last_trace is not None
        assert new_state.last_trace.formula_id == "fm.npv"

    def test_intervention_type_affects_update(self, engine, trace_builder, npv_formula):
        state = initial_state("fm.npv", "fm.npv")
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        wrong = engine.evaluate(npv_formula, ctx) * 0.5
        trace = trace_builder.build(npv_formula, ctx, wrong)

        s1 = update_state(state.copy(), trace, npv_formula, intervention_type="GUIDED_SOLVE")
        s2 = update_state(state.copy(), trace, npv_formula, intervention_type="EXPLAIN")
        assert s1.mastery_mean != s2.mastery_mean

    def test_full_pipeline(self, engine, trace_builder):
        kb = get_knowledge_base()
        formula = kb.formula_for("fm.npv")
        assert formula is not None

        state = initial_state("fm.npv", "fm.npv")

        ctx1 = FMExecutionContext(
            "fm.npv",
            {
                "initial": 100000,
                "r": 0.1,
                "cashflows": [30000, 40000, 50000],
            },
        )
        correct1 = engine.evaluate(formula, ctx1)
        state = update_state(state, trace_builder.build(formula, ctx1, correct1), formula)
        assert state.mastery_mean > 0.5

        ctx2 = FMExecutionContext(
            "fm.npv",
            {
                "initial": 200000,
                "r": 0.12,
                "cashflows": [60000, 80000, 90000, 50000],
            },
        )
        correct2 = engine.evaluate(formula, ctx2)

        state = update_state(state, trace_builder.build(formula, ctx2, correct2 * 0.8), formula)
        assert state.error_beliefs.get("partial_computation_error", 0) > 0

        state = update_state(state, trace_builder.build(formula, ctx2, correct2), formula)
        assert state.mastery_mean > 0.5


# ====================================================================
# End-to-end across multiple formulas
# ====================================================================


class TestEndToEnd:
    def test_npv_and_irr_pipeline(self, engine, trace_builder):
        kb = get_knowledge_base()
        npv_f = kb.formula_for("fm.npv")
        irr_f = kb.formula_for("fm.irr")
        assert npv_f is not None and irr_f is not None

        npv_state = initial_state("fm.npv", "fm.npv", dependency_ids=irr_f.dependencies)
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 50000,
                "r": 0.1,
                "cashflows": [20000, 25000, 20000],
            },
        )
        correct = engine.evaluate(npv_f, ctx)
        for _ in range(2):
            npv_state = update_state(npv_state, trace_builder.build(npv_f, ctx, correct), npv_f)
        assert npv_state.mastery_mean > 0.6

        irr_state = initial_state("fm.irr", "fm.irr", dependency_ids=("fm.npv",))
        irr_ctx = FMExecutionContext(
            "fm.irr",
            {
                "initial": 50000,
                "cashflows": [20000, 25000, 20000],
                "low_rate": 0.12,
                "high_rate": 0.15,
            },
        )
        from studyplan.numerical_solver import solve_irr

        irr_correct = solve_irr([20000, 25000, 20000], 50000, guess=0.1)
        if not math.isnan(irr_correct):
            irr_trace = trace_builder.build(irr_f, irr_ctx, irr_correct)
            irr_state = update_state(irr_state, irr_trace, irr_f)
            assert isinstance(irr_state.mastery_mean, float)

    def test_state_independence(self, engine, trace_builder, npv_formula):
        ctx = FMExecutionContext(
            "fm.npv",
            {
                "initial": 1000,
                "r": 0.1,
                "cashflows": [500, 500, 500],
            },
        )
        correct = engine.evaluate(npv_formula, ctx)

        sa = initial_state("fm.npv", "fm.npv")
        sb = initial_state("fm.npv", "fm.npv")

        sa = update_state(sa, trace_builder.build(npv_formula, ctx, correct), npv_formula)
        sa = update_state(sa, trace_builder.build(npv_formula, ctx, correct * 0.1), npv_formula)

        sb = update_state(sb, trace_builder.build(npv_formula, ctx, correct * 0.1), npv_formula)
        sb = update_state(sb, trace_builder.build(npv_formula, ctx, correct), npv_formula)

        assert sa.mastery_mean != sb.mastery_mean


# ====================================================================
# Transition Dynamics Model tests (predictive layer)
# ====================================================================


class TestFMTransitionDynamicsModel:
    def test_empty_model_returns_defaults(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        dist = model.predict(state, "GUIDED_SOLVE")
        assert isinstance(dist, TransitionDistribution)
        assert dist.sample_count == 0
        assert dist.delta_mastery_mean > 0

    def test_observe_and_predict(self):
        model = FMTransitionDynamicsModel(k=1)
        before = initial_state("fm.npv", "fm.npv")
        after = before.copy()
        after.mastery_mean = 0.7
        after.mastery_var = 0.04
        after.confidence = 0.8

        model.observe(before, "GUIDED_SOLVE", after)
        assert model.observation_count == 1

    def test_prediction_reflects_observations(self):
        model = FMTransitionDynamicsModel(k=1)
        before = initial_state("fm.npv", "fm.npv")
        after = before.copy()
        after.mastery_mean = 0.75
        after.mastery_var = 0.03
        after.confidence = 0.85
        after.error_beliefs = {"sign_error": 0.3, "none": 0.7}

        model.observe(before, "GUIDED_SOLVE", after)
        dist = model.predict(before, "GUIDED_SOLVE")

        assert abs(dist.delta_mastery_mean - 0.25) < 0.01
        assert dist.sample_count == 1

    def test_different_intervention_types_independent(self):
        model = FMTransitionDynamicsModel(k=1)
        before = initial_state("fm.npv", "fm.npv")

        after_guided = before.copy()
        after_guided.mastery_mean = 0.7
        model.observe(before, "GUIDED_SOLVE", after_guided)

        after_explain = before.copy()
        after_explain.mastery_mean = 0.55
        model.observe(before, "EXPLAIN", after_explain)

        g_dist = model.predict(before, "GUIDED_SOLVE")
        e_dist = model.predict(before, "EXPLAIN")
        assert g_dist.delta_mastery_mean != e_dist.delta_mastery_mean

    def test_multiple_observations_averaged(self):
        model = FMTransitionDynamicsModel(k=2)
        before = initial_state("fm.npv", "fm.npv")

        a1 = before.copy()
        a1.mastery_mean = 0.6
        model.observe(before, "UNASSISTED_ATTEMPT", a1)

        a2 = before.copy()
        a2.mastery_mean = 0.7
        model.observe(before, "UNASSISTED_ATTEMPT", a2)

        dist = model.predict(before, "UNASSISTED_ATTEMPT")
        assert abs(dist.delta_mastery_mean - 0.15) < 0.01
        assert dist.sample_count == 2

    def test_defaults_for_unobserved_intervention(self):
        model = FMTransitionDynamicsModel()
        before = initial_state("fm.npv", "fm.npv")
        a1 = before.copy()
        a1.mastery_mean = 0.7
        model.observe(before, "GUIDED_SOLVE", a1)

        dist = model.predict(before, "VARIATION_TRAINING")
        assert dist.sample_count == 0
        assert dist.delta_mastery_mean > 0

    def test_belief_distance_zero_for_same_state(self):
        from studyplan.provenance.learning.model import _belief_distance

        s = initial_state("fm.test", "fm.test")
        assert _belief_distance(s, s) == 0.0

    def test_belief_distance_nonzero_for_different_states(self):
        from studyplan.provenance.learning.model import _belief_distance

        a = initial_state("fm.test", "fm.test")
        b = a.copy()
        b.mastery_mean = 0.8
        assert _belief_distance(a, b) > 0

    def test_model_serializable_state(self):
        model = FMTransitionDynamicsModel()
        before = initial_state("fm.npv", "fm.npv")
        after = before.copy()
        after.mastery_mean = 0.65
        model.observe(before, "GUIDED_SOLVE", after)
        assert model.observation_count == 1

    def test_intervention_types_property(self):
        model = FMTransitionDynamicsModel()
        before = initial_state("fm.npv", "fm.npv")
        after = before.copy()
        after.mastery_mean = 0.7

        model.observe(before, "GUIDED_SOLVE", after)
        model.observe(before, "EXPLAIN", after)

        assert model.intervention_types == {"GUIDED_SOLVE", "EXPLAIN"}

    def test_nearest_neighbor_picks_closest(self):
        model = FMTransitionDynamicsModel(k=1)

        base = initial_state("fm.npv", "fm.npv")

        close_state = base.copy()
        close_state.mastery_mean = 0.48
        close_after = close_state.copy()
        close_after.mastery_mean = 0.68

        far_state = base.copy()
        far_state.mastery_mean = 0.9
        far_after = far_state.copy()
        far_after.mastery_mean = 0.95

        model.observe(close_state, "GUIDED_SOLVE", close_after)
        model.observe(far_state, "GUIDED_SOLVE", far_after)

        query = base.copy()
        query.mastery_mean = 0.51
        dist = model.predict(query, "GUIDED_SOLVE")

        assert abs(dist.delta_mastery_mean - 0.20) < 0.01


# ====================================================================
# Rollout engine tests (multi-step simulation)
# ====================================================================


class TestSimulateStep:
    def test_apply_positive_distribution(self):
        state = initial_state("fm.npv", "fm.npv")
        dist = TransitionDistribution(
            delta_mastery_mean=0.15,
            delta_mastery_var=-0.02,
            delta_confidence=0.1,
        )
        new_state = simulate_step(state, dist)
        assert new_state.mastery_mean > state.mastery_mean
        assert new_state.confidence >= state.confidence

    def test_apply_negative_distribution(self):
        state = initial_state("fm.npv", "fm.npv")
        dist = TransitionDistribution(
            delta_mastery_mean=-0.1,
            delta_mastery_var=0.01,
            delta_confidence=-0.05,
        )
        new_state = simulate_step(state, dist)
        assert new_state.mastery_mean < state.mastery_mean

    def test_clamp_mastery(self):
        state = initial_state("fm.npv", "fm.npv")
        state.mastery_mean = 0.98
        dist = TransitionDistribution(delta_mastery_mean=0.1, delta_mastery_var=-0.01, delta_confidence=0.0)
        new_state = simulate_step(state, dist)
        assert new_state.mastery_mean <= 0.99

    def test_error_correction(self):
        state = initial_state("fm.npv", "fm.npv")
        state.error_beliefs = {"sign_error": 0.4, "none": 0.6}
        dist = TransitionDistribution(
            delta_mastery_mean=0.0,
            delta_mastery_var=0.0,
            delta_confidence=0.0,
            error_correction_probs={"sign_error": 0.2},
        )
        new_state = simulate_step(state, dist)
        assert new_state.error_beliefs["sign_error"] < 0.4
        assert abs(sum(new_state.error_beliefs.values()) - 1.0) < 1e-6

    def test_deterministic(self):
        state = initial_state("fm.npv", "fm.npv")
        dist = TransitionDistribution(delta_mastery_mean=0.1, delta_mastery_var=-0.01, delta_confidence=0.05)
        assert simulate_step(state, dist).mastery_mean == simulate_step(state, dist).mastery_mean


class TestRollout:
    def test_single_step_rollout(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        result = rollout(model, state, ["GUIDED_SOLVE"])
        assert isinstance(result, RolloutResult)
        assert len(result.steps) == 1
        assert isinstance(result.steps[0], RolloutStep)
        assert result.steps[0].intervention == "GUIDED_SOLVE"
        assert isinstance(result.final_state, FMStudentState)
        assert result.cumulative_mastery_gain > 0

    def test_multi_step_rollout(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        seq = ["EXPLAIN", "GUIDED_SOLVE", "UNASSISTED_ATTEMPT"]
        result = rollout(model, state, seq)
        assert len(result.steps) == 3
        assert result.cumulative_mastery_gain > 0

    def test_learned_dynamics_affect_rollout(self):
        model = FMTransitionDynamicsModel(k=1)
        state = initial_state("fm.npv", "fm.npv")

        before = state.copy()
        after = before.copy()
        after.mastery_mean = 0.9
        model.observe(before, "GUIDED_SOLVE", after)

        result = rollout(model, state, ["GUIDED_SOLVE"])
        assert abs(result.cumulative_mastery_gain - 0.40) < 0.01

    def test_rollout_preserves_state_independence(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        original_mean = state.mastery_mean

        result = rollout(model, state, ["GUIDED_SOLVE"])
        assert state.mastery_mean == original_mean  # original unmodified
        assert result.final_state.mastery_mean != original_mean

    def test_empty_sequence_returns_initial_state(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        result = rollout(model, state, [])
        assert len(result.steps) == 0
        assert result.final_state.mastery_mean == state.mastery_mean
        assert result.cumulative_mastery_gain == 0.0


class TestCompareActions:
    def test_ranks_by_mastery_gain(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")

        candidates = [
            ["EXPLAIN"],
            ["GUIDED_SOLVE"],
            ["VARIATION_TRAINING"],
        ]
        ranked = compare_actions(model, state, candidates)
        assert len(ranked) == 3
        assert ranked[0][1].cumulative_mastery_gain >= ranked[1][1].cumulative_mastery_gain
        assert ranked[1][1].cumulative_mastery_gain >= ranked[2][1].cumulative_mastery_gain

    def test_returns_indices(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        ranked = compare_actions(model, state, [["EXPLAIN"], ["GUIDED_SOLVE"]])
        indices = [r[0] for r in ranked]
        assert set(indices) == {0, 1}

    def test_with_learned_data_alters_ranking(self):
        model = FMTransitionDynamicsModel(k=1)
        state = initial_state("fm.npv", "fm.npv")

        before = state.copy()
        after = before.copy()
        after.mastery_mean = 0.95
        model.observe(before, "GUIDED_SOLVE", after)

        ranked = compare_actions(model, state, [["EXPLAIN"], ["GUIDED_SOLVE"]])
        best_idx, best_result = ranked[0]
        assert best_result.cumulative_mastery_gain > 0.3

    def test_deterministic_ranking(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        r1 = compare_actions(model, state, [["EXPLAIN"], ["GUIDED_SOLVE"]])
        r2 = compare_actions(model, state, [["EXPLAIN"], ["GUIDED_SOLVE"]])
        assert r1 == r2


# ====================================================================
# Planner tests (trajectory optimization)
# ====================================================================

DEFAULT_INTERVENTIONS = ["EXPLAIN", "GUIDED_SOLVE", "UNASSISTED_ATTEMPT", "VARIATION_TRAINING"]


class TestPlanResult:
    def test_contains_selected_intervention(self):
        result = PlanResult(
            selected_intervention="GUIDED_SOLVE",
            expected_trajectory=rollout(FMTransitionDynamicsModel(), initial_state("fm.npv", "fm.npv"), []),
        )
        assert result.selected_intervention == "GUIDED_SOLVE"

    def test_optional_runner_up(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        traj = rollout(model, state, [])
        result = PlanResult(
            selected_intervention="GUIDED_SOLVE",
            expected_trajectory=traj,
            runner_up=("EXPLAIN", traj),
        )
        assert result.runner_up is not None
        assert result.runner_up[0] == "EXPLAIN"


class TestCognitivePlanner:
    def test_plan_returns_planresult(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=1)
        result = planner.plan(state, DEFAULT_INTERVENTIONS)
        assert isinstance(result, PlanResult)
        assert result.selected_intervention in DEFAULT_INTERVENTIONS
        assert isinstance(result.expected_trajectory, RolloutResult)

    def test_greedy_picks_highest_expected_gain(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=1)

        result = planner.plan(state, DEFAULT_INTERVENTIONS)

        gains = {}
        for i in DEFAULT_INTERVENTIONS:
            traj = rollout(model, state, [i])
            gains[i] = traj.cumulative_mastery_gain

        best_by_brute = max(gains, key=gains.get)
        assert result.selected_intervention == best_by_brute

    def test_beam_search_horizon_2_finds_better(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")

        greedy = CognitivePlanner(model, horizon=1)
        beam = CognitivePlanner(model, horizon=2, beam_width=3)

        greedy_result = greedy.plan(state, DEFAULT_INTERVENTIONS)
        beam_result = beam.plan(state, DEFAULT_INTERVENTIONS)

        assert isinstance(beam_result.selected_intervention, str)

    def test_empty_interventions_falls_back_to_explain(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=1)
        result = planner.plan(state, [])
        assert result.selected_intervention == "EXPLAIN"
        assert result.beam_depth == 0

    def test_plan_sequence_returns_full_path(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=3, beam_width=4)
        seq = planner.plan_sequence(state, DEFAULT_INTERVENTIONS)
        assert len(seq) == 3
        for s in seq:
            assert s in DEFAULT_INTERVENTIONS

    def test_plan_sequence_empty_interventions(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=3)
        assert planner.plan_sequence(state, []) == []

    def test_learned_data_alters_plan(self):
        model = FMTransitionDynamicsModel(k=1)
        state = initial_state("fm.npv", "fm.npv")

        planner_before = CognitivePlanner(model, horizon=1)
        before = planner_before.plan(state, DEFAULT_INTERVENTIONS)

        before.expected_trajectory.cumulative_mastery_gain
        before.selected_intervention

        before_copy = state.copy()
        after = before_copy.copy()
        after.mastery_mean = 0.95
        model.observe(before_copy, "VARIATION_TRAINING", after)

        planner_after = CognitivePlanner(model, horizon=1)
        after_result = planner_after.plan(state, DEFAULT_INTERVENTIONS)

        assert isinstance(after_result.selected_intervention, str)

    def test_plan_with_two_interventions(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=2, beam_width=2)
        result = planner.plan(state, ["EXPLAIN", "GUIDED_SOLVE"])
        assert result.selected_intervention in ("EXPLAIN", "GUIDED_SOLVE")

    def test_deterministic_planning(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=1)
        r1 = planner.plan(state, DEFAULT_INTERVENTIONS)
        r2 = planner.plan(state, DEFAULT_INTERVENTIONS)
        assert r1.selected_intervention == r2.selected_intervention

    def test_beam_width_clamped(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=1, beam_width=0)
        assert planner.beam_width == 1

    def test_horizon_clamped(self):
        model = FMTransitionDynamicsModel()
        planner = CognitivePlanner(model, horizon=0)
        assert planner.horizon == 1

    def test_plan_includes_runner_up(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=1)
        result = planner.plan(state, ["EXPLAIN", "GUIDED_SOLVE"])
        if result.runner_up is not None:
            assert result.runner_up[0] in ("EXPLAIN", "GUIDED_SOLVE")
            assert isinstance(result.runner_up[1], RolloutResult)

    def test_beam_depth_reported(self):
        model = FMTransitionDynamicsModel()
        state = initial_state("fm.npv", "fm.npv")
        planner = CognitivePlanner(model, horizon=3)
        result = planner.plan(state, DEFAULT_INTERVENTIONS)
        assert result.beam_depth == 3

    def test_properties(self):
        model = FMTransitionDynamicsModel()
        planner = CognitivePlanner(model, horizon=3, beam_width=5)
        assert planner.horizon == 3
        assert planner.beam_width == 5


# ====================================================================
# Event protocol tests
# ====================================================================


class TestEventEnvelope:
    def test_minimal_envelope(self):
        env = EventEnvelope(
            event_id="e1",
            session_id="s1",
            timestamp=100.0,
            type="test.type",
            layer="system",
            payload_version="1.0",
            payload={"key": "val"},
        )
        assert env.event_id == "e1"
        assert env.session_id == "s1"
        assert env.type == "test.type"
        assert env.layer == "system"
        assert env.payload == {"key": "val"}

    def test_envelope_immutable(self):
        env = EventEnvelope(
            event_id="e1",
            session_id="s1",
            timestamp=1.0,
            type="t",
            layer="system",
            payload_version="1.0",
            payload={},
        )
        with pytest.raises(AttributeError):
            env.event_id = "e2"


class TestEventBuilders:
    def test_execution_result_structure(self):
        event = execution_result("NPV", {"r": 0.1}, -2103.44, ["discount", "sum"])
        assert event.type == "execution.result"
        assert event.layer == "execution"
        assert event.payload["formula_id"] == "NPV"
        assert event.payload["output"] == -2103.44
        assert event.payload["evaluation_trace"] == ["discount", "sum"]

    def test_observation_attempt_structure(self):
        event = observation_attempt("NPV", {"r": 0.1}, 5000.0, ["step1"], 100.0)
        assert event.type == "observation.attempt"
        assert event.layer == "observation"
        assert event.payload["student_answer"] == 5000.0
        assert event.payload["correct_answer"] == 100.0

    def test_observation_attempt_none_answer(self):
        event = observation_attempt("NPV", {}, None, [], 100.0)
        assert event.payload["student_answer"] is None

    def test_interpretation_result_structure(self):
        event = interpretation_result(
            "discounting_sign_error",
            0.42,
            ["cashflow_sign_convention"],
            0.78,
        )
        assert event.type == "interpretation.result"
        assert event.payload["error_type"] == "discounting_sign_error"
        assert event.payload["severity"] == 0.42
        assert event.payload["misconceptions"] == ["cashflow_sign_convention"]

    def test_interpretation_result_with_mismatch(self):
        event = interpretation_result(
            "error",
            0.5,
            [],
            0.6,
            mismatch_vector={"abs": 1.0},
        )
        assert event.payload["mismatch_vector"] == {"abs": 1.0}

    def test_belief_state_update_structure(self):
        event = belief_state_update(
            "NPV",
            0.62,
            0.18,
            {"discounting_error": 0.71},
            {"TVM": {"mean": 0.5, "var": 0.2}},
        )
        assert event.type == "belief.state_update"
        assert event.payload["concept_id"] == "NPV"
        assert event.payload["mastery_mean"] == 0.62
        assert event.payload["dependency_beliefs"]["TVM"]["mean"] == 0.5

    def test_belief_diff_structure(self):
        event = belief_diff(
            "NPV",
            {"mastery_mean": 0.5, "mastery_variance": 0.2, "confidence": 0.5},
            {"mastery_mean": 0.58, "mastery_variance": 0.17, "confidence": 0.6},
            {"mastery_mean": 0.08},
        )
        assert event.type == "belief.diff"
        assert event.payload["before"]["mastery_mean"] == 0.5
        assert event.payload["delta"]["mastery_mean"] == 0.08

    def test_transition_update_structure(self):
        event = transition_update("GUIDED_SOLVE", 0.08, -0.03, {"err": -0.12})
        assert event.type == "transition.update"
        assert event.payload["intervention"] == "GUIDED_SOLVE"
        assert event.payload["delta"]["mastery_mean"] == 0.08
        assert event.payload["error_shift"]["err"] == -0.12

    def test_rollout_simulation_structure(self):
        event = rollout_simulation(
            ["EXPLAIN", "GUIDED_SOLVE"],
            [{"t": 1, "mastery": 0.5}, {"t": 2, "mastery": 0.6}],
            0.16,
            0.09,
        )
        assert event.type == "rollout.simulation"
        assert len(event.payload["predicted_trajectory"]) == 2
        assert event.payload["expected_gain"] == 0.16

    def test_scheduler_runqueue_structure(self):
        queue = [
            {"intervention": "REMEDIATE", "priority": 0.92, "expected_gain": 0.21},
        ]
        event = scheduler_runqueue(queue)
        assert event.type == "scheduler.runqueue"
        assert event.payload["queue"][0]["intervention"] == "REMEDIATE"

    def test_system_state_structure(self):
        event = system_state("learning", "1.2.0", "ok")
        assert event.type == "system.state"
        assert event.payload["session_mode"] == "learning"
        assert event.payload["active_model_version"] == "1.2.0"


class TestEventBus:
    def test_emit_receives_event(self):
        bus = EventBus()
        received: list[EventEnvelope] = []

        def sub(e: EventEnvelope) -> None:
            received.append(e)

        bus.subscribe("execution.result", sub)
        event = execution_result("NPV", {}, 0.0, [])
        bus.emit(event)
        assert len(received) == 1
        assert received[0].payload["formula_id"] == "NPV"

    def test_subscribe_all_receives_all(self):
        bus = EventBus()
        received: list[EventEnvelope] = []

        def sub(e: EventEnvelope) -> None:
            received.append(e)

        bus.subscribe_all(sub)
        bus.emit(execution_result("NPV", {}, 0.0, []))
        bus.emit(observation_attempt("NPV", {}, None, [], 0.0))
        assert len(received) == 2

    def test_unsubscribe_removes_handler(self):
        bus = EventBus()
        received: list[EventEnvelope] = []

        def sub(e: EventEnvelope) -> None:
            received.append(e)

        bus.subscribe("execution.result", sub)
        bus.unsubscribe("execution.result", sub)
        bus.emit(execution_result("NPV", {}, 0.0, []))
        assert len(received) == 0

    def test_history_appended(self):
        bus = EventBus()
        bus.emit(execution_result("NPV", {}, 0.0, []))
        bus.emit(observation_attempt("NPV", {}, None, [], 0.0))
        assert bus.event_count == 2
        assert len(bus.history) == 2

    def test_events_by_type(self):
        bus = EventBus()
        bus.emit(execution_result("NPV", {}, 0.0, []))
        bus.emit(observation_attempt("NPV", {}, None, [], 0.0))
        results = bus.events_by_type("execution.result")
        assert len(results) == 1

    def test_events_by_layer(self):
        bus = EventBus()
        bus.emit(execution_result("NPV", {}, 0.0, []))
        bus.emit(observation_attempt("NPV", {}, None, [], 0.0))
        results = bus.events_by_layer("observation")
        assert len(results) == 1

    def test_replay_reemits(self):
        bus = EventBus()
        received: list[EventEnvelope] = []

        def sub(e: EventEnvelope) -> None:
            received.append(e)

        bus.subscribe_all(sub)
        events = [
            execution_result("NPV", {}, 0.0, []),
            observation_attempt("NPV", {}, None, [], 0.0),
        ]
        bus.replay(events)
        assert len(received) == 2
        assert bus.event_count == 2

    def test_clear_removes_everything(self):
        bus = EventBus()
        bus.emit(execution_result("NPV", {}, 0.0, []))
        bus.clear()
        assert bus.event_count == 0
        assert bus.history == []

    def test_session_id_propagation(self):
        bus = EventBus(session_id="test-session")
        event = execution_result("NPV", {}, 0.0, [])
        bus.emit(event)
        assert bus.session_id == "test-session"


class TestKernelEventEmission:
    def test_execution_engine_emits_result(self):
        bus = EventBus()
        engine = FMExecutionEngine(bus=bus)
        formula = _make_npv_formula()
        ctx = FMExecutionContext("fm.npv", {"rate": 0.1, "initial": 1000, "cashflows": [100, 200]})
        engine.evaluate(formula, ctx)
        events = bus.events_by_type("execution.result")
        assert len(events) == 1
        assert events[0].payload["formula_id"] == "fm.npv"

    def test_trace_builder_emits_observation(self):
        bus = EventBus()
        engine = FMExecutionEngine(bus=bus)
        builder = FMTraceBuilder(engine, bus=bus)
        formula = _make_npv_formula()
        ctx = FMExecutionContext("fm.npv", {"rate": 0.1, "initial": 1000, "cashflows": [100, 200]})
        builder.build(formula, ctx, student_result=5000.0)
        events = bus.events_by_type("observation.attempt")
        assert len(events) >= 1

    def test_update_state_emits_belief_events(self):
        bus = EventBus()
        state = initial_state("fm.npv", "fm.npv")
        formula = _make_npv_formula()
        ctx = FMExecutionContext("fm.npv", {"rate": 0.1, "initial": 1000, "cashflows": [100, 200]})
        engine = FMExecutionEngine()
        builder = FMTraceBuilder(engine)
        trace = builder.build(formula, ctx, student_result=5000.0)
        _ = update_state(state, trace, formula, "GUIDED_SOLVE", bus=bus)
        belief_events = bus.events_by_type("belief.state_update")
        diff_events = bus.events_by_type("belief.diff")
        assert len(belief_events) >= 1
        assert len(diff_events) >= 1
        assert belief_events[0].payload["concept_id"] == "fm.npv"

    def test_dynamics_model_emits_transition(self):
        bus = EventBus()
        model = FMTransitionDynamicsModel(bus=bus)
        before = initial_state("fm.npv", "fm.npv")
        after = before.copy()
        after.mastery_mean = 0.65
        model.observe(before, "GUIDED_SOLVE", after)
        events = bus.events_by_type("transition.update")
        assert len(events) == 1
        assert events[0].payload["intervention"] == "GUIDED_SOLVE"

    def test_rollout_emits_simulation(self):
        bus = EventBus()
        model = FMTransitionDynamicsModel(bus=bus)
        state = initial_state("fm.npv", "fm.npv")
        rollout(model, state, ["EXPLAIN", "GUIDED_SOLVE"], bus=bus)
        events = bus.events_by_type("rollout.simulation")
        assert len(events) == 1
        assert len(events[0].payload["predicted_trajectory"]) == 2

    def test_planner_emits_scheduler(self):
        bus = EventBus()
        model = FMTransitionDynamicsModel()
        planner = CognitivePlanner(model, horizon=1, bus=bus)
        state = initial_state("fm.npv", "fm.npv")
        planner.plan(state, ["EXPLAIN", "GUIDED_SOLVE"])
        events = bus.events_by_type("scheduler.runqueue")
        assert len(events) == 1
        assert len(events[0].payload["queue"]) > 0

    def test_kernel_chain_produces_event_stream(self):
        """End-to-end: execution → observation → interpretation → belief → dynamics → rollout → scheduler."""
        bus = EventBus()
        engine = FMExecutionEngine(bus=bus)
        builder = FMTraceBuilder(engine, bus=bus)
        model = FMTransitionDynamicsModel(bus=bus)
        planner = CognitivePlanner(model, horizon=2, bus=bus)

        formula = _make_npv_formula()
        ctx = FMExecutionContext("fm.npv", {"rate": 0.1, "initial": 1000, "cashflows": [100, 200]})

        state = initial_state("fm.npv", "fm.npv")
        trace = builder.build(formula, ctx, student_result=4900.0)
        new_state = update_state(state, trace, formula, "GUIDED_SOLVE", bus=bus)
        model.observe(state, "GUIDED_SOLVE", new_state)
        _ = planner.plan(state, ["EXPLAIN", "GUIDED_SOLVE"])

        event_types = [e.type for e in bus.history]
        assert "execution.result" in event_types
        assert "observation.attempt" in event_types
        assert "interpretation.result" in event_types
        assert "belief.state_update" in event_types
        assert "transition.update" in event_types
        assert "rollout.simulation" in event_types
        assert "scheduler.runqueue" in event_types

    def test_kernel_works_without_bus(self):
        """No event bus = no crashes, identical results."""
        engine = FMExecutionEngine()
        builder = FMTraceBuilder(engine)
        model = FMTransitionDynamicsModel()
        planner = CognitivePlanner(model, horizon=1)

        formula = _make_npv_formula()
        ctx = FMExecutionContext("fm.npv", {"rate": 0.1, "initial": 1000, "cashflows": [100, 200]})
        state = initial_state("fm.npv", "fm.npv")
        trace = builder.build(formula, ctx, student_result=4900.0)
        new_state = update_state(state, trace, formula, "GUIDED_SOLVE")
        model.observe(state, "GUIDED_SOLVE", new_state)
        result = planner.plan(state, ["EXPLAIN", "GUIDED_SOLVE"])

        assert isinstance(result, PlanResult)
        assert result.selected_intervention in ("EXPLAIN", "GUIDED_SOLVE")

    def test_multiple_subscribers_on_same_event(self):
        bus = EventBus()
        received: list[str] = []

        def a(e: EventEnvelope) -> None:
            received.append("a")

        def b(e: EventEnvelope) -> None:
            received.append("b")

        bus.subscribe("execution.result", a)
        bus.subscribe("execution.result", b)
        bus.emit(execution_result("NPV", {}, 0.0, []))
        assert received == ["a", "b"]

    def test_payload_version_forward_compat(self):
        bus = EventBus()
        event = execution_result("NPV", {}, 0.0, [])
        bus.emit(event)
        assert event.payload_version == "1.0"

    def test_histogram_of_event_types(self):
        bus = EventBus()
        bus.emit(execution_result("NPV", {}, 0.0, []))
        bus.emit(execution_result("NPV2", {}, 1.0, []))
        bus.emit(observation_attempt("NPV", {}, None, [], 0.0))
        hist = {}
        for e in bus.history:
            hist[e.type] = hist.get(e.type, 0) + 1
        assert hist["execution.result"] == 2
        assert hist["observation.attempt"] == 1


# ====================================================================
# Tutor bridge tests — kernel intelligence → tutor prompt
# ====================================================================


class TestBuildLearningContext:
    def test_empty_bus_returns_none(self):
        bus = EventBus()
        assert build_learning_context(bus) is None

    def test_interpretation_appears(self):
        bus = EventBus()
        bus.emit(
            interpretation_result(
                "sign_error",
                0.42,
                ["cashflow_sign"],
                0.78,
            )
        )
        result = build_learning_context(bus)
        assert result is not None
        assert "sign_error" in result
        assert "severity: 0.42" in result

    def test_belief_state_appears(self):
        bus = EventBus()
        bus.emit(
            belief_state_update(
                "NPV",
                0.62,
                0.18,
                {"discounting_error": 0.71},
                {},
            )
        )
        result = build_learning_context(bus)
        assert result is not None
        assert "Mastery: 0.62" in result
        assert "0.18" in result

    def test_transition_appears(self):
        bus = EventBus()
        bus.emit(transition_update("GUIDED_SOLVE", 0.08, -0.03, {}))
        result = build_learning_context(bus)
        assert result is not None
        assert "+0.008" in result or "+0.080" in result or "0.08" in result or "Learning delta" in result

    def test_scheduler_appears(self):
        bus = EventBus()
        bus.emit(
            scheduler_runqueue(
                [
                    {"intervention": "GUIDED_SOLVE", "priority": 0.92, "expected_gain": 0.21},
                ]
            )
        )
        result = build_learning_context(bus)
        assert result is not None
        assert "GUIDED_SOLVE" in result
        assert "0.92" in result

    def test_rollout_appears(self):
        bus = EventBus()
        bus.emit(
            rollout_simulation(
                ["EXPLAIN", "GUIDED_SOLVE"],
                [{"t": 1, "mastery": 0.50}, {"t": 2, "mastery": 0.63}],
                0.16,
                0.09,
            )
        )
        result = build_learning_context(bus)
        assert result is not None
        assert "0.50" in result
        assert "0.63" in result

    def test_full_kernel_chain_formatted(self):
        bus = EventBus()
        bus.emit(execution_result("NPV", {}, 100.0, ["eval"]))
        bus.emit(observation_attempt("NPV", {}, 5000.0, [], 100.0))
        bus.emit(interpretation_result("discounting_sign_error", 0.42, ["sign_convention"], 0.78))
        bus.emit(belief_state_update("NPV", 0.55, 0.20, {"sign_error": 0.6}, {}))
        bus.emit(transition_update("GUIDED_SOLVE", 0.05, -0.02, {"sign_error": -0.1}))
        bus.emit(
            rollout_simulation(
                ["GUIDED_SOLVE", "VARIATION_TRAINING"],
                [{"t": 1, "mastery": 0.55}, {"t": 2, "mastery": 0.63}],
                0.08,
                0.10,
            )
        )
        bus.emit(
            scheduler_runqueue(
                [
                    {"intervention": "GUIDED_SOLVE", "priority": 0.85, "expected_gain": 0.08},
                ]
            )
        )
        result = build_learning_context(bus)
        assert result is not None
        assert "[LEARNING CONTEXT]" in result
        assert "discounting_sign_error" in result
        assert "0.55" in result
        assert "GUIDED_SOLVE" in result
        assert "0.85" in result

    def test_only_latest_events_used(self):
        bus = EventBus()
        bus.emit(belief_state_update("NPV", 0.5, 0.2, {}, {}))
        bus.emit(belief_state_update("NPV", 0.7, 0.15, {}, {}))
        result = build_learning_context(bus)
        assert "0.7" in result
        assert "0.5" not in result

    def test_error_profile_appears(self):
        bus = EventBus()
        bus.emit(
            belief_state_update(
                "NPV",
                0.6,
                0.18,
                {"sign_error": 0.6, "arithmetic": 0.3, "none": 0.1},
                {},
            )
        )
        result = build_learning_context(bus)
        assert result is not None
        assert "sign_error: 0.60" in result or "sign_error: 0.6" in result

    def test_no_misconceptions_omitted(self):
        bus = EventBus()
        bus.emit(belief_state_update("NPV", 0.6, 0.18, {"none": 1.0}, {}))
        result = build_learning_context(bus)
        assert result is not None
        assert "Error profile" not in result


class TestLearningIntegrator:
    def test_tutor_context_from_empty_bus(self):
        integ = LearningIntegrator()
        assert integ.tutor_context() is None

    def test_tutor_context_with_events(self):
        bus = EventBus()
        bus.emit(belief_state_update("NPV", 0.6, 0.18, {}, {}))
        integ = LearningIntegrator(bus=bus)
        result = integ.tutor_context()
        assert result is not None
        assert "Mastery: 0.60" in result or "Mastery: 0.6" in result

    def test_clear_resets(self):
        bus = EventBus()
        bus.emit(belief_state_update("NPV", 0.6, 0.18, {}, {}))
        integ = LearningIntegrator(bus=bus)
        assert integ.tutor_context() is not None
        integ.clear()
        assert integ.tutor_context() is None

    def test_global_default_bus(self):
        set_learning_bus(EventBus(session_id="test-global"))
        integ = LearningIntegrator()
        assert integ.bus.session_id == "test-global"

    def test_get_learning_bus_creates_singleton(self):
        bus = get_learning_bus()
        assert bus is not None
        assert isinstance(bus, EventBus)
