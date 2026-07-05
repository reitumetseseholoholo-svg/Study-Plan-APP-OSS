from __future__ import annotations

import uuid
import time
from dataclasses import dataclass
from typing import Any


# ====================================================================
# Envelope — wraps every kernel→UI message
# ====================================================================

LAYER_EXECUTION = "execution"
LAYER_OBSERVATION = "observation"
LAYER_INTERPRETATION = "interpretation"
LAYER_BELIEF = "belief"
LAYER_DYNAMICS = "dynamics"
LAYER_ROLLOUT = "rollout"
LAYER_SCHEDULER = "scheduler"
LAYER_SYSTEM = "system"
LAYER_COMPILER = "compiler"

ALL_LAYERS = frozenset(
    {
        LAYER_EXECUTION,
        LAYER_OBSERVATION,
        LAYER_INTERPRETATION,
        LAYER_BELIEF,
        LAYER_DYNAMICS,
        LAYER_ROLLOUT,
        LAYER_SCHEDULER,
        LAYER_SYSTEM,
        LAYER_COMPILER,
    }
)


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    session_id: str
    timestamp: float
    type: str
    layer: str
    payload_version: str
    payload: dict[str, Any]


def _meta(session_id: str = "") -> tuple[str, str, float]:
    return (
        str(uuid.uuid4()),
        session_id or str(uuid.uuid4()),
        time.time(),
    )


# ====================================================================
# Event builders — each family returns an EventEnvelope
# ====================================================================

# --- 2.1 Execution events ---


def execution_result(
    formula_id: str,
    inputs: dict[str, float],
    output: float,
    evaluation_trace: list[str],
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="execution.result",
        layer=LAYER_EXECUTION,
        payload_version="1.0",
        payload={
            "formula_id": formula_id,
            "inputs": inputs,
            "output": output,
            "evaluation_trace": evaluation_trace,
        },
    )


# --- 2.2 Observation events ---


def observation_attempt(
    formula_id: str,
    params: dict[str, float],
    student_answer: float | None,
    step_trace: list[str],
    correct_answer: float,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="observation.attempt",
        layer=LAYER_OBSERVATION,
        payload_version="1.0",
        payload={
            "formula_id": formula_id,
            "params": params,
            "student_answer": student_answer,
            "step_trace": step_trace,
            "correct_answer": correct_answer,
        },
    )


# --- 2.3 Interpretation events ---


def interpretation_result(
    error_type: str,
    severity: float,
    misconceptions: list[str],
    confidence: float,
    mismatch_vector: dict[str, float] | None = None,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    payload: dict[str, Any] = {
        "error_type": error_type,
        "severity": severity,
        "misconceptions": misconceptions,
        "confidence": confidence,
    }
    if mismatch_vector is not None:
        payload["mismatch_vector"] = mismatch_vector
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="interpretation.result",
        layer=LAYER_INTERPRETATION,
        payload_version="1.0",
        payload=payload,
    )


# --- 2.4 Belief state events ---


def belief_state_update(
    concept_id: str,
    mastery_mean: float,
    mastery_variance: float,
    error_beliefs: dict[str, float],
    dependency_beliefs: dict[str, dict[str, float]],
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="belief.state_update",
        layer=LAYER_BELIEF,
        payload_version="1.0",
        payload={
            "concept_id": concept_id,
            "mastery_mean": mastery_mean,
            "mastery_variance": mastery_variance,
            "error_beliefs": error_beliefs,
            "dependency_beliefs": dependency_beliefs,
        },
    )


def belief_diff(
    concept_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
    delta: dict[str, float],
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="belief.diff",
        layer=LAYER_BELIEF,
        payload_version="1.0",
        payload={
            "concept_id": concept_id,
            "before": before,
            "after": after,
            "delta": delta,
        },
    )


# --- 2.5 Transition events ---


def transition_update(
    intervention: str,
    delta_mastery_mean: float,
    delta_mastery_variance: float,
    error_shift: dict[str, float],
    sample_count: int = 0,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="transition.update",
        layer=LAYER_DYNAMICS,
        payload_version="1.0",
        payload={
            "intervention": intervention,
            "delta": {
                "mastery_mean": delta_mastery_mean,
                "mastery_variance": delta_mastery_variance,
            },
            "error_shift": error_shift,
            "sample_count": sample_count,
        },
    )


# --- 2.6 Rollout events ---


def rollout_simulation(
    intervention_sequence: list[str],
    predicted_trajectory: list[dict[str, Any]],
    expected_gain: float,
    uncertainty: float,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="rollout.simulation",
        layer=LAYER_ROLLOUT,
        payload_version="1.0",
        payload={
            "intervention_sequence": intervention_sequence,
            "predicted_trajectory": predicted_trajectory,
            "expected_gain": expected_gain,
            "uncertainty": uncertainty,
        },
    )


# --- 2.7 Scheduler events ---


def scheduler_runqueue(
    queue: list[dict[str, Any]],
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="scheduler.runqueue",
        layer=LAYER_SCHEDULER,
        payload_version="1.0",
        payload={"queue": queue},
    )


# --- 2.8 System events ---


def system_state(
    session_mode: str,
    active_model_version: str,
    kernel_health: str,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="system.state",
        layer=LAYER_SYSTEM,
        payload_version="1.0",
        payload={
            "session_mode": session_mode,
            "active_model_version": active_model_version,
            "kernel_health": kernel_health,
        },
    )


# ====================================================================
# 3.0 Compiler events — knowledge engineering observability
# ====================================================================


def source_imported(
    source_id: str,
    source_kind: str,
    source_name: str,
    chunk_count: int,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.source_imported",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "source_id": source_id,
            "source_kind": source_kind,
            "source_name": source_name,
            "chunk_count": chunk_count,
        },
    )


def compilation_started(
    source_id: str,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.compilation_started",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={"source_id": source_id},
    )


def extraction_completed(
    source_id: str,
    identity_count: int,
    artifact_count: int,
    relation_count: int,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.extraction_completed",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "source_id": source_id,
            "identity_count": identity_count,
            "artifact_count": artifact_count,
            "relation_count": relation_count,
        },
    )


def ambiguity_detected(
    source_id: str,
    candidate_ids: list[str],
    candidate_labels: list[str],
    similarity_scores: list[float],
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.ambiguity_detected",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "source_id": source_id,
            "candidate_ids": candidate_ids,
            "candidate_labels": candidate_labels,
            "similarity_scores": similarity_scores,
        },
    )


def merge_candidate(
    source_id: str,
    identity_id: str,
    label: str,
    candidate_match_id: str,
    candidate_match_label: str,
    similarity: float,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.merge_candidate",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "source_id": source_id,
            "identity_id": identity_id,
            "label": label,
            "candidate_match_id": candidate_match_id,
            "candidate_match_label": candidate_match_label,
            "similarity": similarity,
        },
    )


def review_decision(
    candidate_ids: list[str],
    candidate_labels: list[str],
    chosen_id: str,
    alternatives: list[str],
    decision: str,
    confidence: float,
    decision_latency_ms: int,
    evidence_viewed: list[str],
    manual_notes: str,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.review_decision",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "candidate_ids": candidate_ids,
            "candidate_labels": candidate_labels,
            "chosen_id": chosen_id,
            "alternatives": alternatives,
            "decision": decision,
            "confidence": confidence,
            "decision_latency_ms": decision_latency_ms,
            "evidence_viewed": evidence_viewed,
            "manual_notes": manual_notes,
        },
    )


def publish_completed(
    source_id: str,
    identity_count: int,
    artifact_count: int,
    relation_count: int,
    review_decisions: int,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.publish_completed",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "source_id": source_id,
            "identity_count": identity_count,
            "artifact_count": artifact_count,
            "relation_count": relation_count,
            "review_decisions": review_decisions,
        },
    )


# ====================================================================
# 3.1 Investigation events — how knowledge engineers explore
# ====================================================================


def review_opened(
    group_id: str,
    candidate_ids: list[str],
    candidate_labels: list[str],
    pending_count: int,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.review_opened",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "group_id": group_id,
            "candidate_ids": candidate_ids,
            "candidate_labels": candidate_labels,
            "pending_count": pending_count,
        },
    )


def provenance_viewed(
    identity_id: str,
    identity_label: str,
    source_kind: str,
    source_id: str,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.provenance_viewed",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "identity_id": identity_id,
            "identity_label": identity_label,
            "source_kind": source_kind,
            "source_id": source_id,
        },
    )


def dependency_graph_viewed(
    identity_id: str,
    identity_label: str,
    edge_count: int,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.dependency_graph_viewed",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "identity_id": identity_id,
            "identity_label": identity_label,
            "edge_count": edge_count,
        },
    )


def candidate_compared(
    group_id: str,
    primary_id: str,
    compared_ids: list[str],
    compared_labels: list[str],
    opened_side_by_side: bool,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.candidate_compared",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "group_id": group_id,
            "primary_id": primary_id,
            "compared_ids": compared_ids,
            "compared_labels": compared_labels,
            "opened_side_by_side": opened_side_by_side,
        },
    )


# ====================================================================
# 3.2 Abandonment signal — evidence insufficient, no resolution
# ====================================================================


def review_abandoned(
    group_id: str,
    candidate_ids: list[str],
    candidate_labels: list[str],
    evidence_viewed: list[str],
    time_spent_ms: int,
    session_id: str = "",
) -> EventEnvelope:
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="compiler.review_abandoned",
        layer=LAYER_COMPILER,
        payload_version="1.0",
        payload={
            "group_id": group_id,
            "candidate_ids": candidate_ids,
            "candidate_labels": candidate_labels,
            "evidence_viewed": evidence_viewed,
            "time_spent_ms": time_spent_ms,
        },
    )


# ====================================================================
# 4. Action outcome events — closed-loop validation (Phase 3)
# ====================================================================
# These events close the cognitive control loop:
#
#   Controller emits action_taken → event bus records it
#   Later, action_outcome is emitted with observed deltas
#   ForwardModel predictions can be compared against observed deltas
#   → the system learns which interventions work
#
# LAYER: "cognition"


def action_taken(
    action_type: str,
    target_id: str,
    secondary_id: str = "",
    rationale: str = "",
    predicted_deltas: dict[str, float] | None = None,
    score: float = 0.0,
    session_id: str = "",
) -> EventEnvelope:
    """Emitted when the controller selects an intervention."""
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="cognition.action_taken",
        layer="cognition",
        payload_version="1.0",
        payload={
            "action_type": action_type,
            "target_id": target_id,
            "secondary_id": secondary_id,
            "rationale": rationale,
            "predicted_deltas": predicted_deltas or {},
            "score": score,
        },
    )


def action_outcome(
    action_event_id: str,
    action_type: str,
    target_id: str,
    observed_deltas: dict[str, float],
    prediction_error: dict[str, float],
    successful: bool,
    notes: str = "",
    session_id: str = "",
) -> EventEnvelope:
    """Emitted after an intervention outcome is observed."""
    eid, sid, ts = _meta(session_id)
    return EventEnvelope(
        event_id=eid,
        session_id=sid,
        timestamp=ts,
        type="cognition.action_outcome",
        layer="cognition",
        payload_version="1.0",
        payload={
            "action_event_id": action_event_id,
            "action_type": action_type,
            "target_id": target_id,
            "observed_deltas": observed_deltas,
            "prediction_error": prediction_error,
            "successful": successful,
            "notes": notes,
        },
    )
