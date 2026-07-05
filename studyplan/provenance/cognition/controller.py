"""Cognitive Controller — intervention space, forward model, policy, and closed-loop control.

Essentialist question:
    What phenomenon does this controller exist to preserve?
Answer:
    The property that *action follows from observation without stored state*.
    The controller is a pure function over the current cognitive projection.
    It does not remember past recommendations — only the event bus does.

Rule 2 (Necessary Existence):
    No new persistent state.  The controller reads projection, produces
    ranked interventions, and emits nothing.  Interventions become events
    only when *acted upon* by the workspace (future: emit as action events).
"""

from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass, field

from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjection,
    NodeProjection,
    ConfusionEdge,
)


# ====================================================================
# 1. Intervention space — six action types over the knowledge graph
# ====================================================================


class ActionType(str, enum.Enum):
    """Teaching actions the controller can recommend.

    Each action type modifies cognitive state along different axes:

    EXPLAIN          → reduces uncertainty, increases stability
    COMPARE          → reduces confusion edge weight between two nodes
    TEST             → reveals true stability (measurement, not change)
    REVISIT          → increases familiarity + stability for decaying nodes
    CONTRAST         → stronger edge reduction than COMPARE (ambiguity focus)
    REPAIR_CONFUSION → cluster-level intervention on all edges in a group
    """

    EXPLAIN = "explain"
    COMPARE = "compare"
    TEST = "test"
    REVISIT = "revisit"
    CONTRAST = "contrast"
    REPAIR_CONFUSION = "repair_confusion"


@dataclass(frozen=True)
class Intervention:
    """A ranked teaching action.

    Attributes:
        action_type:   Which intervention to apply
        target_id:     Primary concept/identity to act on
        label:         Human-readable label of the concept (optional)
        secondary_id:  Second concept for compare/contrast
        rationale:     Human-readable explanation of why this action ranks high
        score:         Composite policy score (0–1)
        component_scores: Per-dimension breakdown for interpretability
    """

    action_type: ActionType
    target_id: str = ""
    label: str = ""
    secondary_id: str = ""
    rationale: str = ""
    score: float = 0.0
    component_scores: dict[str, float] = field(default_factory=dict)


# ====================================================================
# 2. Forward model — predicts cognitive state deltas from interventions
# ====================================================================


class ForwardModel:
    """Calibratable cognitive state transition predictor.

    Given an intervention and current cognitive projection, predicts
    expected deltas in uncertainty, stability, and confusion reduction.

    All predictions are *falsifiable*: after emitting the intervention
    as an event and re-projecting, the observed deltas can be compared
    against predictions.  When the observed outcome is fed back via
    ``update_from_outcome()``, the model adjusts its deltas toward
    empirical values — this is the parameter update that closes the
    adaptive learning loop.

    Default deltas encode pedagogical theory as deterministic heuristics:
        EXPLAIN:          uncertainty -40%, stability +20%
        COMPARE:          confusion edge -50%, uncertainty +10% (both nodes)
        TEST:             no change (measures existing state)
        REVISIT:          familiarity +30%, stability +10%
        CONTRAST:         confusion edge -70%, uncertainty +15% (both nodes)
        REPAIR_CONFUSION: all edges in cluster -30%
    """

    # Default expected deltas — preserved as class constant for reference
    _DEFAULT_DELTAS: dict[ActionType, tuple[float, float, float]] = {
        ActionType.EXPLAIN: (-0.40, 0.20, 0.0),
        ActionType.COMPARE: (0.10, 0.0, -0.50),
        ActionType.TEST: (0.0, 0.0, 0.0),
        ActionType.REVISIT: (0.0, 0.10, 0.0),
        ActionType.CONTRAST: (0.15, 0.0, -0.70),
        ActionType.REPAIR_CONFUSION: (0.0, 0.0, -0.30),
    }

    # Mapping from delta dict keys to tuple indices
    _DELTA_KEYS = ("uncertainty_change", "stability_change", "confusion_reduction")

    def __init__(self, learning_rate: float = 0.1):
        self._learning_rate = learning_rate
        self._deltas: dict[ActionType, dict[str, float]] = {
            at: {
                "uncertainty_change": v[0],
                "stability_change": v[1],
                "confusion_reduction": abs(v[2]),
            }
            for at, v in self._DEFAULT_DELTAS.items()
        }
        self._update_counts: dict[ActionType, int] = {}
        self._accumulated_error: dict[ActionType, dict[str, float]] = {}

    @property
    def calibration_confidence(self) -> dict[str, float]:
        """Per-action-type confidence in the learned delta estimates.

        Starts at 0.0 (pure theory), converges toward 1.0 as more
        outcomes are observed.  Formula: min(1.0, count / 10).
        """
        result: dict[str, float] = {}
        for at in ActionType:
            count = self._update_counts.get(at, 0)
            result[at.value] = round(min(1.0, count / 10.0), 4)
        return result

    @property
    def total_updates(self) -> int:
        return sum(self._update_counts.values())

    def predict_delta(
        self,
        intervention: Intervention,
        projection: CognitiveProjection | None = None,
    ) -> dict[str, float]:
        """Predict expected cognitive state delta for an intervention.

        Returns dict with keys:
            uncertainty_change   — expected change in uncertainty (-1 to 1)
            stability_change     — expected change in stability (-1 to 1)
            confusion_reduction  — expected reduction in confusion edge weight (0 to 1)
        """
        base = self._deltas.get(
            intervention.action_type,
            {"uncertainty_change": 0.0, "stability_change": 0.0, "confusion_reduction": 0.0},
        )

        delta = dict(base)

        if projection is not None and intervention.target_id in projection.nodes:
            node = projection.nodes[intervention.target_id]
            modulate = self._compute_modulation(intervention.action_type, node)
            if modulate is not None:
                for key in ("uncertainty_change", "stability_change"):
                    delta[key] = round(delta[key] * modulate, 4)

        return delta

    def update_from_outcome(
        self,
        outcome: PredictionOutcome,
    ) -> dict[str, float]:
        """Adjust delta estimates toward empirically observed values.

        Uses signed error (observed − predicted) scaled by learning rate::

            delta[k] += learning_rate × (observed[k] − predicted[k])

        Returns the signed errors (what was added to each delta).
        Empty dict if the action type is not recognised.

        The system converges when observed deltas consistently match
        predictions — i.e. when the model has learned the empirical
        transition dynamics of the environment.
        """
        try:
            at = ActionType(outcome.action_type)
        except ValueError:
            return {}

        if at not in self._deltas:
            return {}

        deltas = self._deltas[at]
        signed_errors: dict[str, float] = {}

        for key in ("uncertainty_change", "stability_change", "confusion_reduction"):
            predicted = outcome.predicted_deltas.get(key, 0.0)
            observed = outcome.observed_deltas.get(key, 0.0)
            signed_error = round(observed - predicted, 4)
            signed_errors[key] = signed_error

            adjusted = round(deltas[key] + self._learning_rate * signed_error, 4)
            deltas[key] = adjusted

        self._update_counts[at] = self._update_counts.get(at, 0) + 1

        acc = self._accumulated_error.setdefault(
            at,
            {
                "uncertainty_change": 0.0,
                "stability_change": 0.0,
                "confusion_reduction": 0.0,
            },
        )
        for key, err in signed_errors.items():
            acc[key] = round(acc[key] + abs(err), 4)

        return signed_errors

    def reset_calibration(self) -> None:
        """Reset all learned deltas back to default heuristics."""
        self._deltas = {
            at: {
                "uncertainty_change": v[0],
                "stability_change": v[1],
                "confusion_reduction": abs(v[2]),
            }
            for at, v in self._DEFAULT_DELTAS.items()
        }
        self._update_counts.clear()
        self._accumulated_error.clear()

    def _compute_modulation(
        self,
        action: ActionType,
        node: NodeProjection,
    ) -> float | None:
        """Return modulation factor based on node state for a given action.

        Returns None if no modulation applies (use default).
        """
        if action == ActionType.EXPLAIN:
            if node.uncertainty_score > 0.7:
                return 1.3
            if node.stability_score < 0.3:
                return 0.7
            return None

        return None


# ====================================================================
# 3. Policy engine — ranks interventions by composite scoring
# ====================================================================


@dataclass(frozen=True)
class InterventionRanking:
    """Ordered list of interventions with metadata."""

    interventions: tuple[Intervention, ...] = ()
    total_evaluated: int = 0

    @property
    def best(self) -> Intervention | None:
        return self.interventions[0] if self.interventions else None

    @property
    def is_empty(self) -> bool:
        return not self.interventions


class CognitivePolicyEngine:
    """Ranks teaching interventions by expected cognitive gain.

    Scoring dimensions (all 0–1, combined as weighted sum):

        confusion_reduction_score:
            Targets nodes involved in confusion edges.  Higher weight
            = higher priority.

        dependency_leverage_score:
            Nodes that many others depend on (via CIR 'assumes' edges)
            get priority — teaching a foundation concept helps everything
            downstream.

        uncertainty_collapse_score:
            Nodes with high uncertainty AND high stability are "ready to
            learn" — uncertainty can be resolved without destabilizing.

        stability_reinforcement_score:
            Nodes with decaying familiarity benefit from revisits.
            Familiarity decay = exp(-time_since_last_interaction / half_life).

    Default weights: (0.55, 0.30, 0.10, 0.05)
    Derived from experiment: sensitivity analysis measured mean influence
    of each signal as: confusion=0.1800, leverage=0.0875, stability=0.0134,
    collapse=0.0006.  The first two dominate the common case (nodes with
    edges + dependencies).  Collapse is retained at low weight for the edge
    case of isolated high-uncertainty nodes with no confusion edges or
    dependency leverage.
    """

    def __init__(
        self,
        confusion_weight: float = 0.55,
        leverage_weight: float = 0.30,
        uncertainty_collapse_weight: float = 0.10,
        stability_weight: float = 0.05,
    ):
        self._weights = {
            "confusion": confusion_weight,
            "leverage": leverage_weight,
            "collapse": uncertainty_collapse_weight,
            "stability": stability_weight,
        }

    def rank_interventions(
        self,
        projection: CognitiveProjection,
        dependency_graph: dict[str, list[str]] | None = None,
        top_n: int = 5,
    ) -> InterventionRanking:
        """Produce ranked interventions from cognitive projection.

        Args:
            projection: Current cognitive projection from the event bus.
            dependency_graph: Optional CIR dependency map {node_id: [dependent_ids]}.
                If None, dependency_leverage_score is 0 for all nodes.
            top_n: Maximum number of interventions to return.

        Returns:
            InterventionRanking with scored interventions in descending order.
        """
        candidates: list[Intervention] = []
        nodes = projection.nodes
        edges = projection.confusion_edges

        if not nodes:
            return InterventionRanking(interventions=(), total_evaluated=0)

        scores = self._compute_node_scores(projection, dependency_graph)

        for nid, node in nodes.items():
            components = scores.get(nid, {})
            total = sum(components.get(k, 0.0) * w for k, w in self._weights.items())
            total = round(min(1.0, total), 4)

            if total <= 0.0:
                continue

            candidates.append(
                Intervention(
                    action_type=self._recommend_action(node, edges, nid),
                    target_id=nid,
                    label=node.label,
                    score=total,
                    component_scores=components,
                )
            )

        candidates.sort(key=lambda x: x.score, reverse=True)
        return InterventionRanking(
            interventions=tuple(candidates[:top_n]),
            total_evaluated=len(candidates),
        )

    def _compute_node_scores(
        self,
        projection: CognitiveProjection,
        dependency_graph: dict[str, list[str]] | None,
    ) -> dict[str, dict[str, float]]:
        """Compute per-dimension scores for each node.

        Returns {node_id: {"confusion": float, "leverage": float,
                            "collapse": float, "stability": float}}
        """
        nodes = projection.nodes
        edge_lookup = self._build_edge_lookup(projection.confusion_edges)
        result: dict[str, dict[str, float]] = {}

        leverage_scores = self._compute_leverage_scores(nodes, dependency_graph)
        max_familiarity = max(
            (n.interaction_count for n in nodes.values()),
            default=1,
        )

        for nid, node in nodes.items():
            confusion = 0.0
            if nid in edge_lookup:
                confusion = min(1.0, sum(edge_lookup[nid]) / max(len(edge_lookup[nid]), 1))

            leverage = leverage_scores.get(nid, 0.0)

            collapse = 0.0
            if node.uncertainty_score > 0.3 and node.stability_score > 0.5:
                collapse = (node.uncertainty_score + node.stability_score) / 2.0

            familiarity_decay = 0.0
            if max_familiarity > 0 and node.last_seen > 0:
                relative_count = node.interaction_count / max_familiarity
                familiarity_decay = max(0.0, 1.0 - relative_count)

            result[nid] = {
                "confusion": round(confusion, 4),
                "leverage": round(leverage, 4),
                "collapse": round(collapse, 4),
                "stability": round(familiarity_decay, 4),
            }

        return result

    def _build_edge_lookup(
        self,
        edges: list[ConfusionEdge],
    ) -> dict[str, list[float]]:
        lookup: dict[str, list[float]] = defaultdict(list)
        for e in edges:
            lookup[e.source_id].append(e.weight)
            lookup[e.target_id].append(e.weight)
        return dict(lookup)

    def _compute_leverage_scores(
        self,
        nodes: dict[str, NodeProjection],
        dependency_graph: dict[str, list[str]] | None,
    ) -> dict[str, float]:
        if not dependency_graph:
            return dict.fromkeys(nodes, 0.0)

        scores: dict[str, float] = {}
        for nid in nodes:
            dependents = dependency_graph.get(nid, [])
            if not dependents:
                scores[nid] = 0.0
            else:
                raw = len(dependents)
                max_deps = max(
                    (len(d) for d in dependency_graph.values()),
                    default=1,
                )
                scores[nid] = round(min(1.0, raw / max_deps), 4)
        return scores

    def _recommend_action(
        self,
        node: NodeProjection,
        edges: list[ConfusionEdge],
        nid: str,
    ) -> ActionType:
        """Choose the best action type for a node based on its cognitive state."""
        in_confusion = any(e.source_id == nid or e.target_id == nid for e in edges)

        high_uncertainty = node.uncertainty_score > 0.6
        low_stability = node.stability_score < 0.4
        low_familiarity = node.interaction_count <= 1

        if low_familiarity and not high_uncertainty:
            return ActionType.REVISIT

        if in_confusion and high_uncertainty:
            return ActionType.CONTRAST

        if high_uncertainty:
            return ActionType.EXPLAIN

        if in_confusion:
            return ActionType.COMPARE

        if low_stability:
            return ActionType.TEST

        return ActionType.REVISIT


# ====================================================================
# 4. Controller — closed-loop perception → policy → action
# ====================================================================


class CognitiveController:
    """Unified closed-loop controller over cognitive state.

    Perception:   reads CognitiveProjection from event bus
    Policy:       ranks interventions via CognitivePolicyEngine
    Action:       produces InterventionRanking

    The controller is *stateless* — every call recomputes from scratch.
    This is the "replayable cognition" invariant in the control layer.

    Usage:

        controller = CognitiveController()
        ranking = controller.evaluate(projection)
        if ranking.best:
            print(ranking.best.rationale)
    """

    def __init__(self, policy_engine: CognitivePolicyEngine | None = None):
        self._policy = policy_engine or CognitivePolicyEngine()

    def evaluate(
        self,
        projection: CognitiveProjection,
        dependency_graph: dict[str, list[str]] | None = None,
        top_n: int = 5,
    ) -> InterventionRanking:
        """Produce ranked interventions from a cognitive projection.

        Pure function: no side effects, no state, no event emission.
        """
        if projection.is_empty:
            return InterventionRanking(interventions=(), total_evaluated=0)

        ranking = self._policy.rank_interventions(
            projection,
            dependency_graph=dependency_graph,
            top_n=top_n,
        )

        annotated = tuple(self._annotate(intervention, projection) for intervention in ranking.interventions)

        return InterventionRanking(
            interventions=annotated,
            total_evaluated=ranking.total_evaluated,
        )

    def _annotate(
        self,
        intervention: Intervention,
        projection: CognitiveProjection,
    ) -> Intervention:
        """Add rationale and component explanation."""
        node = projection.nodes.get(intervention.target_id)
        label = f"'{node.label}'" if node and node.label else intervention.target_id
        components = intervention.component_scores

        conf = components.get("confusion", 0.0)
        lev = components.get("leverage", 0.0)
        col = components.get("collapse", 0.0)
        stab = components.get("stability", 0.0)

        parts = []
        if conf > 0.3:
            parts.append("confusion cluster")
        if lev > 0.3:
            parts.append("high-leverage concept")
        if col > 0.5:
            parts.append("ready to learn")
        if stab > 0.5:
            parts.append("familiarity decaying")

        rationale = f"{intervention.action_type.value} {label}"
        if parts:
            rationale += f" ({', '.join(parts)})"

        return Intervention(
            action_type=intervention.action_type,
            target_id=intervention.target_id,
            secondary_id=intervention.secondary_id,
            rationale=rationale,
            score=intervention.score,
            component_scores=intervention.component_scores,
        )
