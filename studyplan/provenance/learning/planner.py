from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from studyplan.provenance.kernel.performance import timed
from studyplan.provenance.learning.student_state import FMStudentState
from studyplan.provenance.learning.model import (
    FMTransitionDynamicsModel,
    RolloutResult,
    rollout,
)
from studyplan.provenance.learning.events import scheduler_runqueue
from studyplan.provenance.learning.event_bus import EventBus


@dataclass(frozen=True)
class PlanResult:
    """Output of a planning step.

    Contains the selected intervention, the expected trajectory,
    and diagnostics for the planner's decision.
    """

    selected_intervention: str
    expected_trajectory: RolloutResult
    runner_up: tuple[str, RolloutResult] | None = None
    beam_depth: int = 1


class CognitivePlanner:
    """Trajectory optimizer over learned belief dynamics.

    Searches over intervention sequences to find the optimal
    learning path. Uses beam search over the learned transition
    model's predictions. Never touches the execution engine.

    This is the planner-as-optimizer — the system's decision layer.
    """

    def __init__(
        self,
        model: FMTransitionDynamicsModel,
        horizon: int = 3,
        beam_width: int = 5,
        bus: EventBus | None = None,
    ):
        self._model = model
        self._horizon = max(1, horizon)
        self._beam_width = max(1, beam_width)
        self._bus = bus

    @property
    def horizon(self) -> int:
        return self._horizon

    @property
    def beam_width(self) -> int:
        return self._beam_width

    @timed("planner", "plan")
    def plan(
        self,
        state: FMStudentState,
        available_interventions: list[str],
    ) -> PlanResult:
        """Select the best first intervention.

        Uses beam search up to horizon depth to find the optimal
        trajectory, then returns the first intervention of that
        trajectory. This enables re-planning at each step.
        """
        if not available_interventions:
            return PlanResult(
                selected_intervention="EXPLAIN",
                expected_trajectory=rollout(self._model, state, [], bus=self._bus),
                beam_depth=0,
            )

        best_seq, best_traj, runner_up = self._beam_search(
            state,
            available_interventions,
        )

        selected = best_seq[0] if best_seq else available_interventions[0]

        result = PlanResult(
            selected_intervention=selected,
            expected_trajectory=best_traj,
            runner_up=runner_up,
            beam_depth=len(best_seq),
        )

        self._emit_scheduler(selected, best_seq, best_traj)
        return result

    @timed("planner", "plan_sequence")
    def plan_sequence(
        self,
        state: FMStudentState,
        available_interventions: list[str],
    ) -> list[str]:
        """Return the full optimal intervention sequence.

        Unlike plan() which only returns the first step, this
        returns the entire planned trajectory. Use for curriculum
        planning rather than reactive step-by-step control.
        """
        if not available_interventions:
            return []

        best_seq, _, _ = self._beam_search(
            state,
            available_interventions,
        )
        return best_seq

    @timed("planner", "beam_search")
    def _beam_search(
        self,
        state: FMStudentState,
        available: list[str],
    ) -> tuple[list[str], RolloutResult, tuple[str, RolloutResult] | None]:
        """Beam search over intervention sequences.

        At each step, expand every candidate in the beam with every
        available intervention, evaluate via rollout, keep top-k.
        """
        if self._horizon == 1:
            return self._greedy_search(state, available)

        beam: list[tuple[list[str], float]] = [([], 0.0)]

        for depth in range(self._horizon):
            candidates: list[tuple[list[str], float]] = []

            for seq, base_score in beam:
                remaining = self._horizon - depth
                for interv in available:
                    new_seq = seq + [interv]
                    result = rollout(self._model, state, new_seq, bus=self._bus)
                    score = result.cumulative_mastery_gain + result.final_confidence * 0.1 - 0.05 * remaining
                    candidates.append((new_seq, score))

            candidates.sort(key=lambda x: x[1], reverse=True)
            beam = candidates[: self._beam_width]

        if not beam:
            return [], rollout(self._model, state, [], bus=self._bus), None

        best_seq, _ = beam[0]
        best_traj = rollout(self._model, state, best_seq, bus=self._bus)

        runner_up: tuple[str, RolloutResult] | None = None
        if len(beam) > 1:
            runner_seq, _ = beam[1]
            if runner_seq:
                runner_up = (
                    runner_seq[0],
                    rollout(self._model, state, runner_seq[:1], bus=self._bus),
                )

        return best_seq, best_traj, runner_up

    @timed("planner", "greedy_search")
    def _greedy_search(
        self,
        state: FMStudentState,
        available: list[str],
    ) -> tuple[list[str], RolloutResult, tuple[str, RolloutResult] | None]:
        """Single-step greedy selection (horizon=1)."""
        scored: list[tuple[str, RolloutResult]] = []
        for interv in available:
            result = rollout(self._model, state, [interv], bus=self._bus)
            scored.append((interv, result))

        scored.sort(key=lambda x: x[1].cumulative_mastery_gain, reverse=True)

        if not scored:
            return [], rollout(self._model, state, [], bus=self._bus), None

        best = scored[0]
        runner = scored[1] if len(scored) > 1 else None

        return [best[0]], best[1], runner

    def _emit_scheduler(self, selected: str, best_seq: list[str], best_traj: RolloutResult) -> None:
        if self._bus is None:
            return
        queue: list[dict[str, Any]] = []
        for i, interv in enumerate(best_seq):
            gain = best_traj.cumulative_mastery_gain / max(len(best_seq), 1)
            priority = max(0.0, min(1.0, 0.5 + gain))
            queue.append(
                {
                    "intervention": interv,
                    "priority": round(priority, 4),
                    "expected_gain": round(gain, 4),
                    "step": i + 1,
                }
            )
        self._bus.emit(
            scheduler_runqueue(
                queue=queue,
                session_id=self._bus.session_id,
            )
        )
