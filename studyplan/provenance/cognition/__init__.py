"""Cognitive Control Layer — Phase 3 of the epistemic architecture.

Closes the loop: perception → policy → action.

This module completes the transformation from observer to controller.
The four-layer architecture is now:

    CIR           (truth)        — canonical knowledge graph
    Event Bus     (observation)  — interaction traces with latency + confidence
    Projection    (inference)    — latent cognitive state from traces
    Controller    (control)      — ranked interventions to modify cognitive state

Architectural invariant:
    Every layer is a *pure function* over the layers below it.
    Controller is a pure function over Projection (which is a pure function
    over Event Bus, which is a pure function over CIR interactions).

    This makes the entire system *replayable* and *falsifiable*:
    Given the same CIR + same event history → same intervention recommendation.

Key design rule (Rule 2):
    No new state. The controller is stateless — it recomputes on every call.
    The controller does not remember which interventions were recommended,
    only the event bus does (via emitted actions as events in future).
"""

from studyplan.provenance.cognition.controller import (
    ActionType,
    Intervention,
    ForwardModel,
    CognitivePolicyEngine,
    CognitiveController,
    InterventionRanking,
)
from studyplan.provenance.cognition.experiment import (
    CognitiveExperiment,
    ExperimentResult,
)
from studyplan.provenance.cognition.outcome import (
    PredictionOutcome,
    PredictionOutcomeComparator,
    compute_closed_loop_outcomes,
)

__all__ = [
    "ActionType",
    "Intervention",
    "ForwardModel",
    "CognitivePolicyEngine",
    "CognitiveController",
    "InterventionRanking",
    "CognitiveExperiment",
    "ExperimentResult",
    "PredictionOutcome",
    "PredictionOutcomeComparator",
    "compute_closed_loop_outcomes",
]
