from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from studyplan.provenance.kernel.performance import timed
from studyplan.provenance.learning.execution_engine import FMExecutionContext
from studyplan.provenance.learning.trace import FMAttemptTrace, compute_mismatch
from studyplan.provenance.learning.student_state import (
    FMStudentState,
    bayesian_mean_update,
    compute_surprise,
    update_error_profile,
    compute_confidence,
)
from studyplan.provenance.learning.events import interpretation_result, belief_state_update, belief_diff
from studyplan.provenance.learning.event_bus import EventBus
from studyplan.provenance.knowledge_ir import FMFormula


# ====================================================================
# Interpretation layer — pedagogical derivations from raw traces
# ====================================================================


@dataclass(frozen=True)
class TraceInterpretation:
    """Pedagogical interpretation of a raw observation.

    This layer sits between observation and belief update.
    It converts raw trace data into semantically meaningful features
    that the transition function consumes.

    Unlike FMAttemptTrace, this is NOT frozen across the pipeline —
    interpretation strategies can change without modifying the trace format.
    """

    error_label: str
    error_magnitude: float
    mismatch_vector: dict[str, float]
    step_analysis: tuple[dict[str, Any], ...]


@timed("transition", "interpret_trace")
def interpret_trace(
    trace: FMAttemptTrace,
    formula: FMFormula,
    ctx: FMExecutionContext,
    bus: EventBus | None = None,
) -> TraceInterpretation:
    """Convert a raw observation into pedagogical features.

    This is the boundary between observation and inference.
    """
    if trace.student_result is None:
        return TraceInterpretation(
            error_label="no_attempt",
            error_magnitude=1.0,
            mismatch_vector={"absolute_difference": float("inf"), "relative_error": 1.0},
            step_analysis=(),
        )

    mismatch = compute_mismatch(trace.student_result, trace.correct_result)
    steps = _analyze_steps(list(trace.step_texts))

    error_label = classify_error(
        formula,
        ctx,
        trace.student_result,
        trace.correct_result,
        steps,
    )

    error_mag = mismatch.get("relative_error", 1.0)
    if error_mag == float("inf") or error_mag > 100:
        error_mag = 1.0

    interp = TraceInterpretation(
        error_label=error_label,
        error_magnitude=error_mag,
        mismatch_vector=mismatch,
        step_analysis=tuple(steps),
    )
    if bus is not None:
        misconceptions = [error_label] if error_label != "none" else []
        bus.emit(
            interpretation_result(
                error_type=error_label,
                severity=error_mag,
                misconceptions=misconceptions,
                confidence=1.0 - error_mag if error_mag < 1.0 else 0.0,
                mismatch_vector=mismatch,
                session_id=bus.session_id,
            )
        )
    return interp


# ------------------------------------------------------------------
# Error classification functions (pedagogical, not observational)
# ------------------------------------------------------------------


@timed("transition", "classify_error")
def classify_error(
    formula: FMFormula,
    ctx: FMExecutionContext,
    student_result: float | None,
    correct_result: float,
    steps: list[dict[str, Any]],
) -> str:
    if student_result is None:
        return "no_attempt"
    if abs(student_result - correct_result) < 1e-4:
        return "none"
    if math.isnan(student_result) or math.isinf(student_result):
        return "invalid_input"
    if correct_result != 0 and student_result == -correct_result:
        return "sign_error"
    if correct_result != 0:
        ratio = student_result / correct_result
        if 9.5 <= ratio <= 10.5 or 0.095 <= ratio <= 0.105:
            return "order_of_magnitude_error"
        if 1.5 <= ratio <= 2.5:
            return "scaling_error"
    for tag in formula.diagnostic_tags:
        if _matches_tag(tag, student_result, correct_result, ctx, steps):
            return tag
    rel = abs(student_result - correct_result) / abs(correct_result) if correct_result != 0 else float("inf")
    if rel < 0.15:
        return "slight_deviation"
    if rel < 0.5:
        return "partial_computation_error"
    return "conceptual_error"


def _matches_tag(
    tag: str,
    student: float,
    correct: float,
    ctx: FMExecutionContext,
    steps: list[dict[str, Any]],
) -> bool:
    if tag == "sign_error":
        return correct != 0 and abs(student) == abs(correct) and student * correct < 0
    if tag == "omit_initial":
        if "initial" in ctx.params:
            return abs(student - (correct + abs(ctx.params["initial"]))) < 1e-4
        return False
    if tag == "wrong_discount_rate" and "rate" in ctx.params:
        alt = correct * (1 + ctx.params["rate"])
        return abs(student - alt) / abs(correct) < 0.2
    if tag == "interpolation_error" and steps:
        return any("interpolat" in str(s.get("text", "")) for s in steps)
    if tag == "cumulative_error" and steps:
        return any("cumul" in str(s.get("text", "")).lower() for s in steps)
    return False


_NUM_PATTERN = re.compile(r"-?\d+\.?\d*")


def _analyze_steps(steps_text: list[str]) -> list[dict[str, Any]]:
    analyzed: list[dict[str, Any]] = []
    for s in steps_text:
        nums = [float(m) for m in _NUM_PATTERN.findall(s)]
        analyzed.append(
            {
                "text": s,
                "numbers": nums,
                "has_formula": "=" in s,
                "is_percent": "%" in s,
            }
        )
    return analyzed


# ====================================================================
# Transition kernel — hybrid state update
# ====================================================================


@timed("transition", "update_state")
def update_state(
    state: FMStudentState,
    trace: FMAttemptTrace,
    formula: FMFormula,
    intervention_type: str = "UNASSISTED_ATTEMPT",
    bus: EventBus | None = None,
) -> FMStudentState:
    interp = interpret_trace(trace, formula, trace.context, bus=bus)

    correct = interp.mismatch_vector.get("exact_match", 0.0) == 1.0

    surprise = compute_surprise(
        state.mastery_mean,
        state.mastery_var,
        correct,
    )

    lr = _intervention_learning_rate(intervention_type)
    new_mean, new_var = bayesian_mean_update(
        state.mastery_mean,
        state.mastery_var,
        surprise,
        learning_rate=lr,
    )

    new_dep_beliefs = dict(state.dependency_beliefs)
    for dep_id in new_dep_beliefs:
        da, db = new_dep_beliefs[dep_id]
        if correct:
            da += 0.3
        elif interp.error_label in ("conceptual_error",):
            db += 0.5
        else:
            da += 0.1
        new_dep_beliefs[dep_id] = (da, db)

    new_error_beliefs = update_error_profile(state.error_beliefs, interp.error_label)

    new_state = state.copy()
    new_state.mastery_mean = new_mean
    new_state.mastery_var = new_var
    new_state.confidence = compute_confidence(new_var)
    new_state.error_beliefs = new_error_beliefs
    new_state.dependency_beliefs = new_dep_beliefs
    new_state.last_trace = trace

    _emit_state_update(state, new_state, formula.concept_id, bus)

    return new_state


def _emit_state_update(before: FMStudentState, after: FMStudentState, concept_id: str, bus: EventBus | None) -> None:
    if bus is None:
        return
    dep_beliefs_out: dict[str, dict[str, float]] = {}
    for dep_id, (alpha, beta) in after.dependency_beliefs.items():
        dep_beliefs_out[dep_id] = {"mean": alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5, "var": 0.0}
    bus.emit(
        belief_state_update(
            concept_id=concept_id,
            mastery_mean=after.mastery_mean,
            mastery_variance=after.mastery_var,
            error_beliefs=after.error_beliefs,
            dependency_beliefs=dep_beliefs_out,
            session_id=bus.session_id,
        )
    )
    delta = {
        "mastery_mean": round(after.mastery_mean - before.mastery_mean, 4),
        "mastery_variance": round(after.mastery_var - before.mastery_var, 4),
    }
    bus.emit(
        belief_diff(
            concept_id=concept_id,
            before={
                "mastery_mean": before.mastery_mean,
                "mastery_variance": before.mastery_var,
                "confidence": before.confidence,
            },
            after={
                "mastery_mean": after.mastery_mean,
                "mastery_variance": after.mastery_var,
                "confidence": after.confidence,
            },
            delta=delta,
            session_id=bus.session_id,
        )
    )


def _intervention_learning_rate(intervention_type: str) -> float:
    rates = {
        "GUIDED_SOLVE": 0.4,
        "EXPLAIN": 0.2,
        "UNASSISTED_ATTEMPT": 0.3,
        "ERROR_DIAGNOSIS": 0.35,
        "VARIATION_TRAINING": 0.45,
    }
    return rates.get(intervention_type, 0.3)


def _state_to_beta(mean: float, var: float) -> tuple[float, float]:
    if var <= 0:
        return (mean * 10, (1.0 - mean) * 10)
    alpha = mean * (mean * (1.0 - mean) / var - 1.0)
    beta = (1.0 - mean) * (mean * (1.0 - mean) / var - 1.0)
    alpha = max(0.1, alpha)
    beta = max(0.1, beta)
    return alpha, beta
