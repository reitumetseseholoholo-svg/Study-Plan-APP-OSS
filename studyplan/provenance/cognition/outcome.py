"""PredictionOutcome comparator — closes the cognitive control loop.

Essentialist question:
    What phenomenon does this comparator exist to preserve?
Answer:
    Falsifiability of teaching actions — the property that every
    intervention produces a measurable delta, and every predicted
    delta can be compared against observed reality.

This module bridges the gap between:
    - ForwardModel.predict_delta(intervention)    (prediction)
    - project(bus.history() after action)         (observation)

The outcome is the feedback signal that makes the loop closed:
    action → outcome → comparison → policy adjustment

Rule 2 (Necessary Existence):
    No new state.  The comparator is a pure function over two
    CognitiveProjections (pre and post).  It produces ephemeral
    PredictionOutcome records — they must be written to the event
    bus via action_outcome() to persist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.cognition.controller import (
    ActionType,
    ForwardModel,
    Intervention,
)
from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjection,
)


@dataclass(frozen=True)
class PredictionOutcome:
    """The feedback signal that closes the control loop.

    Attributes:
        action_type:       Which intervention was taken
        target_id:         Primary concept identity acted upon
        predicted_deltas:  What ForwardModel expected {"uncertainty_change": ...}
        observed_deltas:   What actually changed in projection
        prediction_error:  Absolute error per dimension
        successful:        True if mean_abs_error < threshold (default 0.20)
        event_count_delta: How many new events were generated in the interval
    """

    action_type: ActionType | str
    target_id: str
    predicted_deltas: dict[str, float] = field(default_factory=dict)
    observed_deltas: dict[str, float] = field(default_factory=dict)
    prediction_error: dict[str, float] = field(default_factory=dict)
    successful: bool = False
    event_count_delta: int = 0
    notes: str = ""

    @property
    def mean_abs_error(self) -> float:
        if not self.prediction_error:
            return 0.0
        values = [abs(v) for v in self.prediction_error.values()]
        return sum(values) / len(values) if values else 0.0

    @property
    def max_error(self) -> float:
        if not self.prediction_error:
            return 0.0
        return max(abs(v) for v in self.prediction_error.values())


# ── Delta computation (pure functions) ──────────────────────────


def compute_uncertainty_delta(
    pre: CognitiveProjection,
    post: CognitiveProjection,
    node_id: str,
) -> float:
    """Return observed uncertainty change (post - pre), -1 to 1."""
    pre_node = pre.nodes.get(node_id)
    post_node = post.nodes.get(node_id)
    pre_val = pre_node.uncertainty_score if pre_node else 0.0
    post_val = post_node.uncertainty_score if post_node else 0.0
    return round(post_val - pre_val, 4)


def compute_stability_delta(
    pre: CognitiveProjection,
    post: CognitiveProjection,
    node_id: str,
) -> float:
    """Return observed stability change (post - pre), -1 to 1."""
    pre_node = pre.nodes.get(node_id)
    post_node = post.nodes.get(node_id)
    pre_val = pre_node.stability_score if pre_node else 1.0
    post_val = post_node.stability_score if post_node else 1.0
    return round(post_val - pre_val, 4)


def compute_confusion_reduction(
    pre: CognitiveProjection,
    post: CognitiveProjection,
    node_id: str,
) -> float:
    """Return observed confusion reduction for a node (0 to 1).

    Measures reduction in total confusion edge weight incident on node_id.
    """

    def _incident_weight(proj: CognitiveProjection, nid: str) -> float:
        total = 0.0
        for e in proj.confusion_edges:
            if e.source_id == nid or e.target_id == nid:
                total += e.weight
        return total

    pre_w = _incident_weight(pre, node_id)
    post_w = _incident_weight(post, node_id)
    reduction = max(0.0, pre_w - post_w)
    return round(min(1.0, reduction), 4)


# ── Comparator ──────────────────────────────────────────────────


class PredictionOutcomeComparator:
    """Compares predicted deltas against observed projection deltas.

    Usage::

        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(
            intervention=best,
            pre_projection=pre,
            post_projection=post,
        )
        bus.emit(action_outcome(
            action_event_id=taken_event_id,
            action_type=outcome.action_type,
            target_id=outcome.target_id,
            observed_deltas=outcome.observed_deltas,
            prediction_error=outcome.prediction_error,
            successful=outcome.successful,
            notes=str(outcome.mean_abs_error),
        ))
    """

    def __init__(self, forward_model: ForwardModel | None = None):
        self._fm = forward_model or ForwardModel()
        self._success_threshold = 0.20

    def compare(
        self,
        intervention: Intervention,
        pre_projection: CognitiveProjection,
        post_projection: CognitiveProjection,
    ) -> PredictionOutcome:
        """Compare predicted vs observed deltas for an intervention.

        Args:
            intervention:  The intervention that was taken.
            pre_projection:  CognitiveProjection before the action.
            post_projection: CognitiveProjection after the action.

        Returns:
            PredictionOutcome with observed deltas and prediction error.
        """
        target_id = intervention.target_id or intervention.label

        predicted = self._fm.predict_delta(intervention, pre_projection)

        uncertainty_obs = compute_uncertainty_delta(pre_projection, post_projection, target_id)
        stability_obs = compute_stability_delta(pre_projection, post_projection, target_id)
        confusion_obs = compute_confusion_reduction(pre_projection, post_projection, target_id)

        observed = {
            "uncertainty_change": uncertainty_obs,
            "stability_change": stability_obs,
            "confusion_reduction": confusion_obs,
        }

        prediction_error = {}
        for key in predicted:
            predicted_val = predicted.get(key, 0.0)
            observed_val = observed.get(key, 0.0)
            prediction_error[key] = round(abs(observed_val - predicted_val), 4)

        error_values = list(prediction_error.values())
        mean_error = sum(error_values) / len(error_values) if error_values else 0.0
        successful = mean_error <= self._success_threshold

        event_count_delta = max(0, post_projection.event_count - pre_projection.event_count)

        return PredictionOutcome(
            action_type=intervention.action_type,
            target_id=target_id,
            predicted_deltas=predicted,
            observed_deltas=observed,
            prediction_error=prediction_error,
            successful=successful,
            event_count_delta=event_count_delta,
            notes=f"mean_error={mean_error:.4f}" if not successful else "",
        )

    def compare_from_history(
        self,
        intervention: Intervention,
        pre_projection: CognitiveProjection,
        post_projection: CognitiveProjection,
        taken_event_id: str = "",
    ) -> tuple[PredictionOutcome, dict[str, Any]]:
        """Same as compare(), but also builds the action_outcome event payload.

        Returns (PredictionOutcome, event_payload_kwargs).
        """
        outcome = self.compare(intervention, pre_projection, post_projection)
        event_kwargs = {
            "action_event_id": taken_event_id,
            "action_type": outcome.action_type,
            "target_id": outcome.target_id,
            "observed_deltas": outcome.observed_deltas,
            "prediction_error": outcome.prediction_error,
            "successful": outcome.successful,
            "notes": outcome.notes,
        }
        return outcome, event_kwargs


# ── Self-consuming loop helper ──────────────────────────────────


def compute_closed_loop_outcomes(
    events: list,
    pre_projection: CognitiveProjection | None = None,
    comparator: PredictionOutcomeComparator | None = None,
) -> list[PredictionOutcome]:
    """Compute PredictionOutcomes for every action_taken in an event list.

    Uses CognitiveProjectionEngine to re-project after each action_taken,
    compares against the pre-action projection, and collects outcomes.

    This is the "self-consuming loop" — the controller reads its own
    past action outcomes as evidence for the next policy decision.

    Args:
        events: Full event history (including action_taken events).
        pre_projection: Projection before any actions. If None, computed
            from events before the first action_taken.
        comparator: PredictionOutcomeComparator instance.

    Returns:
        List of PredictionOutcome, one per action_taken event.  Empty if
        no action_taken events exist.
    """
    from studyplan.provenance.learning.cognitive_projection import (
        CognitiveProjectionEngine,
    )

    engine = CognitiveProjectionEngine()
    comp = comparator or PredictionOutcomeComparator()

    outcomes: list[PredictionOutcome] = []
    action_indices = [i for i, e in enumerate(events) if getattr(e, "type", "") == "cognition.action_taken"]

    if not action_indices:
        return outcomes

    current_pre = pre_projection

    for idx in action_indices:
        action_ev = events[idx]

        if current_pre is None:
            prefix = events[:idx]
            current_pre = engine.project(prefix)

        post = engine.project(events[: idx + 1])

        action_type_raw = action_ev.payload.get("action_type", "explain")
        try:
            at = ActionType(action_type_raw)
        except ValueError:
            at = ActionType.EXPLAIN

        intervention = Intervention(
            action_type=at,
            target_id=action_ev.payload.get("target_id", ""),
            secondary_id=action_ev.payload.get("secondary_id", ""),
            rationale=action_ev.payload.get("rationale", ""),
            score=action_ev.payload.get("score", 0.0),
            component_scores=action_ev.payload.get("predicted_deltas", {}),
        )

        outcome = comp.compare(intervention, current_pre, post)
        outcomes.append(outcome)

        current_pre = post

    return outcomes
