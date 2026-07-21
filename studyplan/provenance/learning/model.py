from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.kernel.performance import timed
from studyplan.provenance.learning.student_state import FMStudentState, compute_confidence
from studyplan.provenance.learning.events import transition_update, rollout_simulation
from studyplan.provenance.learning.event_bus import EventBus


@dataclass(frozen=True)
class TransitionDistribution:
    """Predicted outcome distribution of an intervention.

    This is the output of the transition dynamics model —
    what the planner uses to compute expected value.
    """

    delta_mastery_mean: float
    delta_mastery_var: float
    delta_confidence: float
    error_correction_probs: dict[str, float] = field(default_factory=dict)
    sample_count: int = 0


class FMTransitionDynamicsModel:
    """Predictive model of learning dynamics.

    Given (state, intervention), predicts the expected distribution
    over next states. Accumulates empirical observations and improves
    predictions over time via nearest-neighbor regression over belief space.

    This is the "physics model" of learning — the critical layer that
    enables the planner to simulate interventions before executing them.
    """

    def __init__(self, k: int = 3, bus: EventBus | None = None):
        self._history: list[tuple[FMStudentState, str, FMStudentState]] = []
        self._k = k
        self._bus = bus

    @property
    def observation_count(self) -> int:
        return len(self._history)

    @property
    def intervention_types(self) -> set[str]:
        return {interv for _, interv, _ in self._history}

    @timed("model", "observe")
    def observe(self, before: FMStudentState, intervention: str, after: FMStudentState) -> None:
        """Record an empirical transition for learning."""
        self._history.append((before, intervention, after))
        if self._bus is not None:
            delta_mean = round(after.mastery_mean - before.mastery_mean, 4)
            delta_var = round(after.mastery_var - before.mastery_var, 4)
            error_shift: dict[str, float] = {}
            for err_type in set(list(before.error_beliefs.keys()) + list(after.error_beliefs.keys())):
                shift = after.error_beliefs.get(err_type, 0.0) - before.error_beliefs.get(err_type, 0.0)
                if abs(shift) > 0.001:
                    error_shift[err_type] = round(shift, 4)
            self._bus.emit(
                transition_update(
                    intervention=intervention,
                    delta_mastery_mean=delta_mean,
                    delta_mastery_variance=delta_var,
                    error_shift=error_shift,
                    sample_count=len(self._history),
                    session_id=self._bus.session_id,
                )
            )

    @timed("model", "predict")
    def predict(self, state: FMStudentState, intervention: str) -> TransitionDistribution:
        """Predict expected transition distribution.

        Finds the k-nearest past states (by belief-space distance) that
        received the same intervention and returns their average deltas.
        Falls back to intervention-specific defaults when no data exists.
        """
        candidates = self._find_candidates(state, intervention)

        if not candidates:
            return self._default_distribution(intervention)

        delta_means: list[float] = []
        delta_vars: list[float] = []
        delta_confs: list[float] = []
        error_deltas: dict[str, list[float]] = {}

        for before, after in candidates:
            delta_means.append(after.mastery_mean - before.mastery_mean)
            delta_vars.append(after.mastery_var - before.mastery_var)
            delta_confs.append(after.confidence - before.confidence)
            for err_type, prob in after.error_beliefs.items():
                before_prob = before.error_beliefs.get(err_type, 0.0)
                error_deltas.setdefault(err_type, []).append(prob - before_prob)

        n = len(delta_means)
        avg_delta_mean = sum(delta_means) / n
        avg_delta_var = sum(delta_vars) / n
        avg_delta_conf = sum(delta_confs) / n

        correction_probs: dict[str, float] = {}
        if error_deltas:
            all_types = set(error_deltas.keys())
            for err_type in all_types:
                deltas = error_deltas[err_type]
                avg_delta = sum(deltas) / len(deltas)
                if avg_delta < 0:
                    correction_probs[err_type] = abs(avg_delta)

        return TransitionDistribution(
            delta_mastery_mean=round(avg_delta_mean, 4),
            delta_mastery_var=round(avg_delta_var, 4),
            delta_confidence=round(avg_delta_conf, 4),
            error_correction_probs=correction_probs,
            sample_count=n,
        )

    @timed("model", "find_candidates")
    def _find_candidates(
        self,
        state: FMStudentState,
        intervention: str,
    ) -> list[tuple[FMStudentState, FMStudentState]]:
        """Find k-nearest past transitions with the same intervention."""
        matched: list[tuple[float, int]] = []

        for i, (before, interv, after) in enumerate(self._history):
            if interv != intervention:
                continue
            dist = _belief_distance(state, before)
            matched.append((dist, i))

        matched.sort(key=lambda x: x[0])
        nearest = matched[: self._k]

        return [(self._history[idx][0], self._history[idx][2]) for _, idx in nearest]

    def _default_distribution(self, intervention: str) -> TransitionDistribution:
        """Reasonable defaults when no empirical data exists."""
        defaults: dict[str, tuple[float, float, float]] = {
            "GUIDED_SOLVE": (0.12, -0.01, 0.08),
            "EXPLAIN": (0.05, -0.005, 0.03),
            "UNASSISTED_ATTEMPT": (0.08, -0.008, 0.05),
            "ERROR_DIAGNOSIS": (0.10, -0.012, 0.06),
            "VARIATION_TRAINING": (0.15, -0.015, 0.10),
        }
        dm, dv, dc = defaults.get(intervention, (0.05, -0.005, 0.03))
        return TransitionDistribution(
            delta_mastery_mean=dm,
            delta_mastery_var=dv,
            delta_confidence=dc,
            sample_count=0,
        )


# ====================================================================
# Rollout engine — multi-step simulation over learned dynamics
# ====================================================================


@dataclass(frozen=True)
class RolloutStep:
    state: FMStudentState
    intervention: str
    transition: TransitionDistribution


@dataclass(frozen=True)
class RolloutResult:
    steps: tuple[RolloutStep, ...]
    final_state: FMStudentState
    cumulative_mastery_gain: float
    final_confidence: float


@timed("model", "simulate_step")
def simulate_step(
    state: FMStudentState,
    dist: TransitionDistribution,
) -> FMStudentState:
    """Apply predicted transition distribution to produce a simulated next state.

    Pure deterministic function — no randomness.
    The uncertainty is in the distribution, not the step function.
    """
    new_state = state.copy()
    new_state.mastery_mean = max(0.01, min(0.99, state.mastery_mean + dist.delta_mastery_mean))
    new_state.mastery_var = max(0.001, min(0.25, state.mastery_var + dist.delta_mastery_var))
    new_state.confidence = compute_confidence(new_state.mastery_var)

    new_errors = dict(state.error_beliefs)
    for err_type, correction in dist.error_correction_probs.items():
        if err_type in new_errors:
            new_errors[err_type] = max(0.0, new_errors[err_type] - correction)
    total = sum(new_errors.values())
    if total > 0:
        for k in new_errors:
            new_errors[k] = new_errors[k] / total
    new_state.error_beliefs = new_errors

    return new_state


@timed("model", "rollout")
def rollout(
    model: FMTransitionDynamicsModel,
    state: FMStudentState,
    intervention_sequence: list[str],
    bus: EventBus | None = None,
) -> RolloutResult:
    """Simulate a multi-step trajectory over learned dynamics.

    Chains the dynamics model's predictions to produce a sequence
    of simulated belief states. The planner calls this to evaluate
    candidate intervention sequences.
    """
    steps: list[RolloutStep] = []
    current = state
    cumulative_gain = 0.0

    for intervention in intervention_sequence:
        dist = model.predict(current, intervention)
        simulated_next = simulate_step(current, dist)

        steps.append(
            RolloutStep(
                state=current,
                intervention=intervention,
                transition=dist,
            )
        )

        cumulative_gain += dist.delta_mastery_mean
        current = simulated_next

    result = RolloutResult(
        steps=tuple(steps),
        final_state=current,
        cumulative_mastery_gain=round(cumulative_gain, 4),
        final_confidence=round(current.confidence, 4),
    )
    if bus is not None:
        trajectory: list[dict[str, Any]] = []
        for i, s in enumerate(steps):
            trajectory.append(
                {
                    "t": i + 1,
                    "intervention": s.intervention,
                    "mastery": s.state.mastery_mean,
                    "confidence": s.state.confidence,
                }
            )
        uncertainty = 1.0 - abs(result.cumulative_mastery_gain) if result.cumulative_mastery_gain != 0 else 0.5
        bus.emit(
            rollout_simulation(
                intervention_sequence=list(intervention_sequence),
                predicted_trajectory=trajectory,
                expected_gain=result.cumulative_mastery_gain,
                uncertainty=round(uncertainty, 4),
                session_id=bus.session_id,
            )
        )
    return result


@timed("model", "compare_actions")
def compare_actions(
    model: FMTransitionDynamicsModel,
    state: FMStudentState,
    candidates: list[list[str]],
) -> list[tuple[int, RolloutResult]]:
    """Evaluate multiple candidate intervention sequences.

    Returns ranked list of (index, result) sorted by cumulative
    mastery gain descending. This is what the planner will call
    to select the optimal intervention.
    """
    results: list[tuple[int, RolloutResult]] = []
    for i, seq in enumerate(candidates):
        result = rollout(model, state, seq)
        results.append((i, result))

    results.sort(key=lambda x: x[1].cumulative_mastery_gain, reverse=True)
    return results


# ====================================================================
# Belief-space distance metric
# ====================================================================


@timed("model", "belief_distance")
def _belief_distance(a: FMStudentState, b: FMStudentState) -> float:
    """Euclidean distance in belief space.

    Features: mastery_mean, confidence, error_profile (top-3 probabilities).
    """
    dm = a.mastery_mean - b.mastery_mean
    dc = a.confidence - b.confidence

    a_errors = sorted(a.error_beliefs.items(), key=lambda x: -x[1])[:3]
    b_errors = sorted(b.error_beliefs.items(), key=lambda x: -x[1])[:3]

    all_types = list({et for et, _ in a_errors} | {et for et, _ in b_errors})
    err_dist = 0.0
    for et in all_types:
        ap = a.error_beliefs.get(et, 0.0)
        bp = b.error_beliefs.get(et, 0.0)
        err_dist += (ap - bp) ** 2

    return math.sqrt(dm**2 + dc**2 + err_dist)
