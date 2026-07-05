"""Tests for PredictionOutcome comparator and closed-loop outcome helpers."""

from __future__ import annotations

from studyplan.provenance.cognition.controller import (
    ActionType,
    ForwardModel,
    Intervention,
)
from studyplan.provenance.cognition.outcome import (
    PredictionOutcome,
    PredictionOutcomeComparator,
    compute_closed_loop_outcomes,
    compute_confusion_reduction,
    compute_stability_delta,
    compute_uncertainty_delta,
)
from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjection,
    CognitiveProjectionEngine,
    ConfusionEdge,
    NodeProjection,
)
from studyplan.provenance.learning.events import (
    action_outcome,
    action_taken,
    review_decision,
)


# ── Fixtures ────────────────────────────────────────────────────


def _make_node(
    nid: str,
    label: str = "",
    unc: float = 0.0,
    stab: float = 1.0,
    count: int = 0,
    last_seen: float = 0.0,
) -> NodeProjection:
    return NodeProjection(
        identity_id=nid,
        label=label or nid,
        uncertainty_score=unc,
        stability_score=stab,
        interaction_count=count,
        last_seen=last_seen,
    )


def _empty_projection() -> CognitiveProjection:
    return CognitiveProjection(nodes={}, confusion_edges=[], event_count=0, computed_at=0.0)


# ── Tests: PredictionOutcome dataclass ──────────────────────────


class TestPredictionOutcome:
    def test_mean_abs_error_empty(self):
        o = PredictionOutcome(action_type="explain", target_id="x")
        assert o.mean_abs_error == 0.0

    def test_mean_abs_error_computed(self):
        o = PredictionOutcome(
            action_type="explain",
            target_id="x",
            prediction_error={"a": 0.1, "b": 0.3},
        )
        assert o.mean_abs_error == 0.2

    def test_max_error(self):
        o = PredictionOutcome(
            action_type="explain",
            target_id="x",
            prediction_error={"a": 0.1, "b": 0.5, "c": 0.2},
        )
        assert o.max_error == 0.5

    def test_successful_default_threshold(self):
        o = PredictionOutcome(
            action_type="explain",
            target_id="x",
            prediction_error={"a": 0.1, "b": 0.29},
            successful=True,
        )
        assert o.successful
        assert o.mean_abs_error == 0.195

    def test_unsuccessful(self):
        o = PredictionOutcome(
            action_type="explain",
            target_id="x",
            prediction_error={"a": 0.4, "b": 0.5},
            successful=False,
        )
        assert not o.successful


# ── Tests: Delta computation ────────────────────────────────────


class TestDeltaComputation:
    def test_uncertainty_delta_positive(self):
        pre = CognitiveProjection(nodes={"x": _make_node("x", unc=0.3)})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.7)})
        assert compute_uncertainty_delta(pre, post, "x") == 0.4

    def test_uncertainty_delta_negative(self):
        pre = CognitiveProjection(nodes={"x": _make_node("x", unc=0.8)})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.3)})
        assert compute_uncertainty_delta(pre, post, "x") == -0.5

    def test_uncertainty_delta_missing_pre(self):
        pre = CognitiveProjection(nodes={})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.5)})
        assert compute_uncertainty_delta(pre, post, "x") == 0.5

    def test_uncertainty_delta_missing_both(self):
        pre = CognitiveProjection(nodes={})
        post = CognitiveProjection(nodes={})
        assert compute_uncertainty_delta(pre, post, "x") == 0.0

    def test_stability_delta(self):
        pre = CognitiveProjection(nodes={"x": _make_node("x", stab=0.8)})
        post = CognitiveProjection(nodes={"x": _make_node("x", stab=0.9)})
        assert compute_stability_delta(pre, post, "x") == 0.1

    def test_stability_delta_missing_pre(self):
        pre = CognitiveProjection(nodes={})
        post = CognitiveProjection(nodes={"x": _make_node("x", stab=0.7)})
        assert compute_stability_delta(pre, post, "x") == -0.3

    def test_confusion_reduction(self):
        pre = CognitiveProjection(
            nodes={"a": _make_node("a"), "b": _make_node("b")},
            confusion_edges=[ConfusionEdge(source_id="a", target_id="b", weight=0.8)],
        )
        post = CognitiveProjection(
            nodes={"a": _make_node("a"), "b": _make_node("b")},
            confusion_edges=[ConfusionEdge(source_id="a", target_id="b", weight=0.3)],
        )
        assert compute_confusion_reduction(pre, post, "a") == 0.5

    def test_confusion_reduction_no_change(self):
        pre = CognitiveProjection(
            nodes={"a": _make_node("a")},
            confusion_edges=[],
        )
        post = CognitiveProjection(
            nodes={"a": _make_node("a")},
            confusion_edges=[],
        )
        assert compute_confusion_reduction(pre, post, "a") == 0.0


# ── Tests: PredictionOutcomeComparator ──────────────────────────


class TestPredictionOutcomeComparator:
    def test_compare_explain_perfect_match(self):
        inter = Intervention(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            label="test concept",
        )
        pre = CognitiveProjection(nodes={"x": _make_node("x", unc=0.5, stab=0.6)})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.1, stab=0.8)})
        # EXPLAIN predicts: unc -0.40, stab +0.20
        # Observed: unc -0.40, stab +0.20 → perfect match
        fm = ForwardModel()
        comparator = PredictionOutcomeComparator(fm)
        outcome = comparator.compare(inter, pre, post)
        assert outcome.action_type == ActionType.EXPLAIN
        assert outcome.target_id == "x"
        assert outcome.predicted_deltas["uncertainty_change"] == -0.40
        assert outcome.observed_deltas["uncertainty_change"] == -0.4
        assert outcome.prediction_error["uncertainty_change"] == 0.0
        assert outcome.prediction_error["stability_change"] == 0.0
        assert outcome.successful

    def test_compare_explain_partial_mismatch(self):
        inter = Intervention(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            label="test",
        )
        pre = CognitiveProjection(nodes={"x": _make_node("x", unc=0.5, stab=0.6)})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.4, stab=0.65)})
        # Predicted: unc -0.40, stab +0.20
        # Observed:  unc -0.10, stab +0.05
        # Error:     unc 0.30, stab 0.15, confusion 0.0 → mean 0.15 ≤ 0.20
        # This is within threshold — add a large confusion error to push over
        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(inter, pre, post)
        assert outcome.successful  # within default threshold of 0.20

    def test_compare_explain_large_error(self):
        inter = Intervention(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            label="test",
        )
        pre = CognitiveProjection(nodes={"x": _make_node("x", unc=0.5, stab=0.9)})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.9, stab=0.1)})
        # Predicted: unc -0.40, stab +0.20
        # Observed:  unc +0.40, stab -0.80
        # Error:     unc 0.80, stab 1.00, confusion 0.0 → mean 0.60 > 0.20 → unsuccessful
        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(inter, pre, post)
        assert not outcome.successful
        assert outcome.prediction_error["uncertainty_change"] == 0.80
        assert outcome.prediction_error["stability_change"] == 1.00

    def test_compare_compare_action(self):
        inter = Intervention(
            action_type=ActionType.COMPARE,
            target_id="a",
            secondary_id="b",
        )
        pre = CognitiveProjection(
            nodes={
                "a": _make_node("a", unc=0.3),
                "b": _make_node("b", unc=0.3),
            },
            confusion_edges=[ConfusionEdge("a", "b", weight=0.8)],
        )
        post = CognitiveProjection(
            nodes={
                "a": _make_node("a", unc=0.4),
                "b": _make_node("b", unc=0.4),
            },
            confusion_edges=[ConfusionEdge("a", "b", weight=0.3)],
        )
        # COMPARE predicts: unc +0.10, confusion -0.50
        # Observed: unc +0.10, confusion reduction 0.5 → match
        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(inter, pre, post)
        assert outcome.predicted_deltas["uncertainty_change"] == 0.10
        assert outcome.predicted_deltas["confusion_reduction"] == 0.50
        assert outcome.observed_deltas["confusion_reduction"] == 0.5
        assert outcome.successful

    def test_compare_with_event_count_delta(self):
        inter = Intervention(action_type=ActionType.EXPLAIN, target_id="x")
        pre = CognitiveProjection(nodes={"x": _make_node("x")}, event_count=10)
        post = CognitiveProjection(nodes={"x": _make_node("x")}, event_count=15)
        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(inter, pre, post)
        assert outcome.event_count_delta == 5

    def test_compare_from_history_builds_event_kwargs(self):
        inter = Intervention(action_type=ActionType.EXPLAIN, target_id="x")
        pre = CognitiveProjection(nodes={"x": _make_node("x", unc=0.5)})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.1)})
        comparator = PredictionOutcomeComparator()
        outcome, kwargs = comparator.compare_from_history(
            inter,
            pre,
            post,
            taken_event_id="ev-001",
        )
        assert kwargs["action_event_id"] == "ev-001"
        assert kwargs["action_type"] == ActionType.EXPLAIN
        assert kwargs["target_id"] == "x"
        assert "observed_deltas" in kwargs
        assert "prediction_error" in kwargs
        assert "successful" in kwargs

    def test_compare_target_id_falls_back_to_label(self):
        inter = Intervention(
            action_type=ActionType.REVISIT,
            target_id="",
            label="fallback_concept",
        )
        pre = CognitiveProjection(nodes={"fallback_concept": _make_node("fallback_concept", unc=0.5)})
        post = CognitiveProjection(nodes={"fallback_concept": _make_node("fallback_concept", unc=0.5)})
        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(inter, pre, post)
        assert outcome.target_id == "fallback_concept"

    def test_compare_empty_projection(self):
        inter = Intervention(action_type=ActionType.TEST, target_id="x")
        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(inter, _empty_projection(), _empty_projection())
        # All-zero deltas → zero prediction error → successful
        assert outcome.successful

    def test_forward_model_modulation_reflected(self):
        """EXPLAIN on high-uncertainty node gets 1.3 modulation."""
        inter = Intervention(action_type=ActionType.EXPLAIN, target_id="x")
        pre = CognitiveProjection(nodes={"x": _make_node("x", unc=0.8, stab=0.5)})
        post = CognitiveProjection(nodes={"x": _make_node("x", unc=0.28, stab=0.76)})
        # Predicted: unc -0.40 * 1.3 = -0.52, stab +0.20 * 1.3 = +0.26
        # Observed:  unc 0.28-0.8 = -0.52, stab 0.76-0.5 = +0.26 → perfect
        comparator = PredictionOutcomeComparator()
        outcome = comparator.compare(inter, pre, post)
        assert outcome.predicted_deltas["uncertainty_change"] == -0.52
        assert outcome.predicted_deltas["stability_change"] == 0.26
        assert outcome.successful


# ── Tests: Event builder integration ────────────────────────────


class TestActionEventBuilders:
    def test_action_taken_event(self):
        ev = action_taken(
            action_type="explain",
            target_id="fm:WACC",
            rationale="high uncertainty",
            predicted_deltas={"uncertainty_change": -0.4},
            score=0.85,
        )
        assert ev.type == "cognition.action_taken"
        assert ev.layer == "cognition"
        assert ev.payload["action_type"] == "explain"
        assert ev.payload["target_id"] == "fm:WACC"
        assert ev.payload["rationale"] == "high uncertainty"
        assert ev.payload["predicted_deltas"]["uncertainty_change"] == -0.4
        assert ev.payload["score"] == 0.85
        assert len(ev.event_id) > 0  # UUID format

    def test_action_taken_defaults(self):
        ev = action_taken(action_type="test", target_id="x")
        assert ev.payload["predicted_deltas"] == {}
        assert ev.payload["score"] == 0.0
        assert ev.payload["secondary_id"] == ""

    def test_action_outcome_event(self):
        ev = action_outcome(
            action_event_id="ev-001",
            action_type="explain",
            target_id="fm:WACC",
            observed_deltas={"uncertainty_change": -0.35},
            prediction_error={"uncertainty_change": 0.05},
            successful=True,
        )
        assert ev.type == "cognition.action_outcome"
        assert ev.layer == "cognition"
        assert ev.payload["action_event_id"] == "ev-001"
        assert ev.payload["successful"] is True
        assert ev.payload["observed_deltas"]["uncertainty_change"] == -0.35
        assert ev.payload["prediction_error"]["uncertainty_change"] == 0.05

    def test_action_outcome_with_notes(self):
        ev = action_outcome(
            action_event_id="ev-002",
            action_type="contrast",
            target_id="x",
            observed_deltas={},
            prediction_error={"uncertainty_change": 0.42},
            successful=False,
            notes="mean_error=0.42",
        )
        assert ev.payload["notes"] == "mean_error=0.42"
        assert ev.payload["successful"] is False


# ── Tests: Closed-loop helper ───────────────────────────────────


class TestClosedLoopOutcomes:
    def test_empty_events(self):
        outcomes = compute_closed_loop_outcomes([])
        assert outcomes == []

    def test_no_action_events(self):
        ev = review_decision(
            candidate_ids=["a", "b"],
            candidate_labels=["A", "B"],
            chosen_id="a",
            alternatives=["b"],
            decision="merged",
            confidence=0.8,
            decision_latency_ms=100,
            evidence_viewed=[],
            manual_notes="",
        )
        outcomes = compute_closed_loop_outcomes([ev])
        assert outcomes == []

    def test_single_action_taken(self):
        pre_ev = review_decision(
            candidate_ids=["x", "y"],
            candidate_labels=["X", "Y"],
            chosen_id="x",
            alternatives=["y"],
            decision="merged",
            confidence=0.6,
            decision_latency_ms=500,
            evidence_viewed=[],
            manual_notes="",
        )
        action_ev = action_taken(
            action_type="explain",
            target_id="x",
            rationale="test action",
            predicted_deltas={"uncertainty_change": -0.4, "stability_change": 0.2},
            score=0.85,
        )
        events = [pre_ev, action_ev]
        outcomes = compute_closed_loop_outcomes(events)
        assert len(outcomes) == 1
        assert outcomes[0].action_type == ActionType.EXPLAIN
        assert outcomes[0].target_id == "x"

    def test_multiple_actions_loop(self):
        evs = [
            review_decision(
                candidate_ids=["a", "b"],
                candidate_labels=["A", "B"],
                chosen_id="a",
                alternatives=["b"],
                decision="merged",
                confidence=0.7,
                decision_latency_ms=400,
                evidence_viewed=[],
                manual_notes="",
            ),
            action_taken("explain", "a", predicted_deltas={"uncertainty_change": -0.4}),
            review_decision(
                candidate_ids=["a", "c"],
                candidate_labels=["A", "C"],
                chosen_id="a",
                alternatives=["c"],
                decision="merged",
                confidence=0.9,
                decision_latency_ms=200,
                evidence_viewed=[],
                manual_notes="",
            ),
            action_taken("revisit", "a", predicted_deltas={"uncertainty_change": 0.0}),
        ]
        outcomes = compute_closed_loop_outcomes(evs)
        assert len(outcomes) == 2
        assert outcomes[0].action_type == ActionType.EXPLAIN
        assert outcomes[1].action_type == ActionType.REVISIT

    def test_closed_loop_round_trip(self):
        """Simulate full: project → intervene → outcome → compare."""
        pre_ev = review_decision(
            candidate_ids=["x", "y"],
            candidate_labels=["X", "Y"],
            chosen_id="x",
            alternatives=["y"],
            decision="merged",
            confidence=0.5,
            decision_latency_ms=500,
            evidence_viewed=[],
            manual_notes="",
        )
        action_ev = action_taken(
            "explain",
            "x",
            predicted_deltas={"uncertainty_change": -0.4, "stability_change": 0.2},
        )
        # Add a post-action decision that changes the projection
        post_ev = review_decision(
            candidate_ids=["x", "y"],
            candidate_labels=["X", "Y"],
            chosen_id="x",
            alternatives=["y"],
            decision="merged",
            confidence=0.9,
            decision_latency_ms=100,
            evidence_viewed=[],
            manual_notes="",
        )
        events = [pre_ev, action_ev, post_ev]

        engine = CognitiveProjectionEngine()
        pre_proj = engine.project([pre_ev])
        post_proj = engine.project(events)

        from studyplan.provenance.cognition.outcome import PredictionOutcomeComparator

        comparator = PredictionOutcomeComparator()
        inter = Intervention(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            rationale="test",
            score=0.85,
        )
        outcome = comparator.compare(inter, pre_proj, post_proj)
        assert outcome.target_id == "x"
        assert isinstance(outcome.predicted_deltas, dict)
        assert isinstance(outcome.observed_deltas, dict)
        # Uncertainty should have decreased (latency 500→100)
        assert outcome.observed_deltas["uncertainty_change"] < 0

        # Build outcome event
        from studyplan.provenance.learning.events import action_outcome

        outcome_ev = action_outcome(
            action_event_id=action_ev.event_id,
            action_type=str(outcome.action_type),
            target_id=outcome.target_id,
            observed_deltas=outcome.observed_deltas,
            prediction_error=outcome.prediction_error,
            successful=outcome.successful,
        )
        assert outcome_ev.type == "cognition.action_outcome"
        assert outcome_ev.payload["action_event_id"] == action_ev.event_id

    def test_closed_loop_with_custom_comparator(self):
        evs = [
            review_decision(
                candidate_ids=["x", "y"],
                candidate_labels=["X", "Y"],
                chosen_id="x",
                alternatives=["y"],
                decision="merged",
                confidence=0.6,
                decision_latency_ms=300,
                evidence_viewed=[],
                manual_notes="",
            ),
            action_taken("test", "x"),
        ]
        from studyplan.provenance.cognition.outcome import PredictionOutcomeComparator

        comparator = PredictionOutcomeComparator()
        outcomes = compute_closed_loop_outcomes(evs, comparator=comparator)
        assert len(outcomes) == 1
