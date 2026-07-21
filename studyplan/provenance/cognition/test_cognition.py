"""Tests for the Cognitive Control Layer.

Covers:

    Tier 1 — Core types (ActionType, Intervention)
        action_type_values
        intervention_construction
        intervention_frozen

    Tier 2 — Forward model
        forward_model_default_deltas
        forward_model_explain_modulation
        forward_model_test_no_change
        forward_model_repair_confusion_default
        forward_model_without_projection

    Tier 3 — Policy engine scoring
        policy_empty_projection
        policy_single_node_no_confusion
        policy_confusion_edge_increases_score
        policy_leverage_from_dependency_graph
        policy_uncertainty_collapse
        policy_familiarity_decay
        policy_action_type_selection_various_states
        policy_top_n_filtering
        policy_no_double_zero_score

    Tier 4 — Controller integration
        controller_empty_projection
        controller_annotates_rationale
        controller_evaluate_produces_ranking
        controller_pure_function

    Tier 5 — Edge cases
        very_high_uncertainty_node
        all_scores_zero
        dependency_graph_mismatch
"""

from studyplan.provenance.cognition.controller import (
    ActionType,
    Intervention,
    ForwardModel,
    CognitivePolicyEngine,
    CognitiveController,
)
from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjection,
    NodeProjection,
    ConfusionEdge,
)
from studyplan.provenance.cognition.outcome import (
    PredictionOutcome,
    PredictionOutcomeComparator,
)


# ====================================================================
# Tier 1 — Core types
# ====================================================================


class TestActionType:
    def test_action_type_values(self):
        assert ActionType.EXPLAIN.value == "explain"
        assert ActionType.COMPARE.value == "compare"
        assert ActionType.TEST.value == "test"
        assert ActionType.REVISIT.value == "revisit"
        assert ActionType.CONTRAST.value == "contrast"
        assert ActionType.REPAIR_CONFUSION.value == "repair_confusion"

    def test_all_six_types_present(self):
        assert len(ActionType) == 6


class TestIntervention:
    def test_intervention_construction(self):
        inv = Intervention(
            action_type=ActionType.EXPLAIN,
            target_id="fm:WACC",
            rationale="High uncertainty",
            score=0.85,
            component_scores={"confusion": 0.0, "leverage": 0.9},
        )
        assert inv.action_type == ActionType.EXPLAIN
        assert inv.target_id == "fm:WACC"
        assert inv.score == 0.85

    def test_intervention_frozen(self):
        inv = Intervention(action_type=ActionType.TEST, target_id="x")
        import dataclasses

        assert dataclasses.is_dataclass(inv)
        assert inv.secondary_id == ""
        assert inv.rationale == ""


# ====================================================================
# Tier 2 — Forward model
# ====================================================================


class TestForwardModel:
    def test_forward_model_default_deltas(self):
        fm = ForwardModel()
        for at in ActionType:
            inv = Intervention(action_type=at, target_id="fm:X")
            delta = fm.predict_delta(inv)

            assert "uncertainty_change" in delta
            assert "stability_change" in delta
            assert "confusion_reduction" in delta

            assert isinstance(delta["uncertainty_change"], float)
            assert isinstance(delta["stability_change"], float)
            assert isinstance(delta["confusion_reduction"], float)

    def test_forward_model_explain_reduces_uncertainty(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.EXPLAIN, target_id="fm:X")
        delta = fm.predict_delta(inv)
        assert delta["uncertainty_change"] == -0.40
        assert delta["stability_change"] == 0.20

    def test_forward_model_compare_reduces_confusion(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.COMPARE, target_id="fm:A")
        delta = fm.predict_delta(inv)
        assert delta["confusion_reduction"] == 0.50

    def test_forward_model_test_no_change(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.TEST, target_id="fm:X")
        delta = fm.predict_delta(inv)
        assert delta["uncertainty_change"] == 0.0
        assert delta["stability_change"] == 0.0
        assert delta["confusion_reduction"] == 0.0

    def test_forward_model_revisit_increases_stability(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.REVISIT, target_id="fm:X")
        delta = fm.predict_delta(inv)
        assert delta["stability_change"] == 0.10

    def test_forward_model_contrast_strong_reduction(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.CONTRAST, target_id="fm:X")
        delta = fm.predict_delta(inv)
        assert delta["confusion_reduction"] == 0.70

    def test_forward_model_repair_confusion_cluster(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.REPAIR_CONFUSION, target_id="fm:X")
        delta = fm.predict_delta(inv)
        assert delta["confusion_reduction"] == 0.30

    def test_forward_model_without_projection(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.EXPLAIN, target_id="fm:X")
        delta = fm.predict_delta(inv, projection=None)
        assert delta["uncertainty_change"] == -0.40

    def test_forward_model_modulation_high_uncertainty(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.EXPLAIN, target_id="fm:X")
        proj = CognitiveProjection(
            nodes={
                "fm:X": NodeProjection(
                    identity_id="fm:X",
                    label="X",
                    uncertainty_score=0.85,
                    stability_score=0.6,
                ),
            },
        )
        delta = fm.predict_delta(inv, projection=proj)
        assert delta["uncertainty_change"] < -0.40

    def test_forward_model_modulation_low_stability(self):
        fm = ForwardModel()
        inv = Intervention(action_type=ActionType.EXPLAIN, target_id="fm:X")
        proj = CognitiveProjection(
            nodes={
                "fm:X": NodeProjection(
                    identity_id="fm:X",
                    label="X",
                    uncertainty_score=0.5,
                    stability_score=0.2,
                ),
            },
        )
        # Low stability reduces EXPLAIN effectiveness
        delta = fm.predict_delta(inv, projection=proj)
        assert delta["uncertainty_change"] > -0.40


# ====================================================================
# Tier 3 — Policy engine scoring
# ====================================================================


class TestCognitivePolicyEngine:
    def test_policy_empty_projection(self):
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(event_count=0, computed_at=0.0)
        ranking = engine.rank_interventions(proj)
        assert ranking.is_empty
        assert ranking.total_evaluated == 0

    def test_policy_single_node_high_uncertainty(self):
        """A node with high uncertainty and confusion gets an intervention."""
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:X": NodeProjection(
                    identity_id="fm:X",
                    label="X",
                    uncertainty_score=0.9,
                    stability_score=0.7,
                    interaction_count=5,
                    last_seen=1000.0,
                ),
            },
        )
        ranking = engine.rank_interventions(proj)
        assert not ranking.is_empty
        assert ranking.best is not None
        assert ranking.best.target_id == "fm:X"

    def test_policy_confusion_edge_increases_score(self):
        engine = CognitivePolicyEngine()
        base_proj = CognitiveProjection(
            nodes={
                "fm:A": NodeProjection("fm:A", "A", 0.3, 0.9, 3, 1000.0),
                "fm:B": NodeProjection("fm:B", "B", 0.3, 0.9, 3, 1000.0),
            },
        )
        confused_proj = CognitiveProjection(
            nodes={
                "fm:A": NodeProjection("fm:A", "A", 0.3, 0.9, 3, 1000.0),
                "fm:B": NodeProjection("fm:B", "B", 0.3, 0.9, 3, 1000.0),
            },
            confusion_edges=[
                ConfusionEdge(source_id="fm:A", target_id="fm:B", weight=0.9),
            ],
        )

        base_ranking = engine.rank_interventions(base_proj)
        confused_ranking = engine.rank_interventions(confused_proj)

        base_scores = {i.target_id: i.score for i in base_ranking.interventions}
        confused_scores = {i.target_id: i.score for i in confused_ranking.interventions}

        assert confused_scores.get("fm:A", 0) >= base_scores.get("fm:A", 0)

    def test_policy_leverage_from_dependency_graph(self):
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:ROOT": NodeProjection("fm:ROOT", "Root", 0.3, 0.9, 3, 1000.0),
                "fm:LEAF": NodeProjection("fm:LEAF", "Leaf", 0.3, 0.9, 3, 1000.0),
            },
        )
        deps = {
            "fm:ROOT": ["fm:A", "fm:B", "fm:C", "fm:D", "fm:E"],
            "fm:LEAF": [],
        }

        ranking = engine.rank_interventions(proj, dependency_graph=deps)
        root_score = 0.0
        leaf_score = 0.0
        for i in ranking.interventions:
            if i.target_id == "fm:ROOT":
                root_score = i.score
            if i.target_id == "fm:LEAF":
                leaf_score = i.score
        assert root_score > leaf_score

    def test_policy_uncertainty_collapse_score(self):
        engine = CognitivePolicyEngine()
        ready = CognitiveProjection(
            nodes={
                "fm:READY": NodeProjection(
                    "fm:READY",
                    "Ready",
                    uncertainty_score=0.7,
                    stability_score=0.8,
                    interaction_count=5,
                    last_seen=1000.0,
                ),
                "fm:UNSURE": NodeProjection(
                    "fm:UNSURE",
                    "Unsure",
                    uncertainty_score=0.7,
                    stability_score=0.2,
                    interaction_count=5,
                    last_seen=1000.0,
                ),
            },
        )
        ranking = engine.rank_interventions(ready)
        ready_collapse = 0.0
        unsure_collapse = 0.0
        for i in ranking.interventions:
            cs = i.component_scores
            if i.target_id == "fm:READY":
                ready_collapse = cs.get("collapse", 0.0)
            if i.target_id == "fm:UNSURE":
                unsure_collapse = cs.get("collapse", 0.0)
        assert ready_collapse > unsure_collapse

    def test_policy_familiarity_decay_score(self):
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:OLD": NodeProjection(
                    "fm:OLD",
                    "Old",
                    0.3,
                    0.8,
                    interaction_count=1,
                    last_seen=1.0,
                ),
                "fm:NEW": NodeProjection(
                    "fm:NEW",
                    "New",
                    0.3,
                    0.8,
                    interaction_count=10,
                    last_seen=1000.0,
                ),
            },
        )
        ranking = engine.rank_interventions(proj)
        old_stab = 0.0
        new_stab = 0.0
        for i in ranking.interventions:
            cs = i.component_scores
            if i.target_id == "fm:OLD":
                old_stab = cs.get("stability", 0.0)
            if i.target_id == "fm:NEW":
                new_stab = cs.get("stability", 0.0)
        assert old_stab > new_stab

    def test_policy_action_type_selection_various_states(self):
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:UNCERTAIN": NodeProjection(
                    "fm:UNCERTAIN",
                    "Uncertain",
                    uncertainty_score=0.9,
                    stability_score=0.7,
                    interaction_count=5,
                    last_seen=1000.0,
                ),
                "fm:CONFUSED": NodeProjection(
                    "fm:CONFUSED",
                    "Confused",
                    uncertainty_score=0.7,
                    stability_score=0.8,
                    interaction_count=5,
                    last_seen=1000.0,
                ),
                "fm:FRESH": NodeProjection(
                    "fm:FRESH",
                    "Fresh",
                    uncertainty_score=0.2,
                    stability_score=0.9,
                    interaction_count=1,
                    last_seen=500.0,
                ),
            },
            confusion_edges=[
                ConfusionEdge(source_id="fm:CONFUSED", target_id="fm:OTHER", weight=0.8),
            ],
        )
        ranking = engine.rank_interventions(proj)

        action_map = {i.target_id: i.action_type for i in ranking.interventions}

        # High uncertainty should prefer EXPLAIN or CONTRAST
        assert action_map["fm:UNCERTAIN"] in (ActionType.EXPLAIN, ActionType.CONTRAST)

    def test_policy_top_n_filtering(self):
        engine = CognitivePolicyEngine()
        nodes = {}
        for i in range(10):
            nodes[f"fm:N{i}"] = NodeProjection(
                f"fm:N{i}",
                f"N{i}",
                uncertainty_score=0.5,
                stability_score=0.8,
                interaction_count=3,
                last_seen=1000.0,
            )
        proj = CognitiveProjection(nodes=nodes)

        ranking3 = engine.rank_interventions(proj, top_n=3)
        ranking10 = engine.rank_interventions(proj, top_n=10)

        assert len(ranking3.interventions) <= 3
        assert len(ranking10.interventions) <= 10

    def test_policy_no_double_zero_score(self):
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:ZERO": NodeProjection(
                    "fm:ZERO",
                    "Zero",
                    uncertainty_score=0.0,
                    stability_score=1.0,
                    interaction_count=0,
                    last_seen=0.0,
                ),
            },
        )
        ranking = engine.rank_interventions(proj)
        # Zero-score nodes are excluded
        assert ranking.is_empty or ranking.best is None or ranking.best.score == 0.0


# ====================================================================
# Tier 4 — Controller integration
# ====================================================================


class TestCognitiveController:
    def test_controller_empty_projection(self):
        ctrl = CognitiveController()
        proj = CognitiveProjection(event_count=0, computed_at=0.0)
        ranking = ctrl.evaluate(proj)
        assert ranking.is_empty

    def test_controller_annotates_rationale(self):
        ctrl = CognitiveController()
        proj = CognitiveProjection(
            nodes={
                "fm:X": NodeProjection(
                    "fm:X",
                    "WACC",
                    uncertainty_score=0.8,
                    stability_score=0.9,
                    interaction_count=5,
                    last_seen=1000.0,
                ),
            },
        )
        ranking = ctrl.evaluate(proj)
        assert ranking.best is not None
        assert "explain" in ranking.best.rationale.lower() or "WACC" in ranking.best.rationale

    def test_controller_evaluate_produces_ranking(self):
        ctrl = CognitiveController()
        proj = CognitiveProjection(
            nodes={
                "fm:A": NodeProjection("fm:A", "A", 0.3, 0.9, 3, 1000.0),
                "fm:B": NodeProjection("fm:B", "B", 0.5, 0.7, 5, 900.0),
                "fm:C": NodeProjection("fm:C", "C", 0.1, 0.95, 10, 800.0),
            },
        )
        ranking = ctrl.evaluate(proj)
        assert ranking.total_evaluated >= 2  # 2-3 nodes should score above 0
        assert len(ranking.interventions) <= 5

    def test_controller_pure_function(self):
        """Same projection + same policy = same ranking (deterministic)."""
        proj = CognitiveProjection(
            nodes={
                "fm:X": NodeProjection("fm:X", "X", 0.5, 0.8, 3, 1000.0),
            },
        )
        ctrl = CognitiveController()
        r1 = ctrl.evaluate(proj)
        r2 = ctrl.evaluate(proj)
        if r1.best and r2.best:
            assert r1.best.score == r2.best.score
            assert r1.best.action_type == r2.best.action_type
            assert r1.best.target_id == r2.best.target_id


# ====================================================================
# Tier 5 — Edge cases
# ====================================================================


class TestEdgeCases:
    def test_very_high_uncertainty_node(self):
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:MAX": NodeProjection(
                    "fm:MAX",
                    "Max",
                    uncertainty_score=0.99,
                    stability_score=0.99,
                    interaction_count=10,
                    last_seen=1000.0,
                ),
            },
        )
        ranking = engine.rank_interventions(proj)
        assert ranking.best is not None
        assert ranking.best.score > 0.0
        assert ranking.best.action_type == ActionType.EXPLAIN

    def test_all_scores_zero(self):
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:Z": NodeProjection(
                    "fm:Z",
                    "Z",
                    uncertainty_score=0.0,
                    stability_score=1.0,
                    interaction_count=0,
                    last_seen=0.0,
                ),
            },
        )
        ranking = engine.rank_interventions(proj)
        assert ranking.is_empty or ranking.total_evaluated == 0

    def test_dependency_graph_mismatch(self):
        """Dependency graph with extra keys not in projection is handled."""
        engine = CognitivePolicyEngine()
        proj = CognitiveProjection(
            nodes={
                "fm:X": NodeProjection("fm:X", "X", 0.5, 0.8, 3, 1000.0),
            },
        )
        deps = {
            "fm:X": ["fm:A", "fm:B"],
            "fm:MISSING": ["fm:C", "fm:D", "fm:E"],
        }
        ranking = engine.rank_interventions(proj, dependency_graph=deps)
        assert ranking.best is not None
        assert ranking.best.target_id == "fm:X"


# ====================================================================
# Tier 6 — Calibration: parameter update from observed outcomes
# ====================================================================


class TestForwardModelCalibration:
    """ForwardModel now supports online calibration — update_from_outcome()
    adjusts delta estimates toward empirically observed values.

    This is the parameter update rule that transforms the system from
    self-evaluating to self-improving.
    """

    def test_update_from_outcome_adjusts_deltas(self):
        """After one EXPLAIN outcome, uncertainty delta shifts toward observed."""
        fm = ForwardModel(learning_rate=0.5)
        outcome = PredictionOutcome(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            predicted_deltas={"uncertainty_change": -0.40, "stability_change": 0.20},
            observed_deltas={"uncertainty_change": -0.20, "stability_change": 0.10},
        )
        signed = fm.update_from_outcome(outcome)
        # signed error: unc: -0.20 - (-0.40) = +0.20 → delta moves -0.40 → -0.30
        #              stab: 0.10 - 0.20 = -0.10 → delta moves 0.20 → 0.15
        new = fm.predict_delta(Intervention(action_type=ActionType.EXPLAIN, target_id="x"))
        assert new["uncertainty_change"] == -0.30
        assert new["stability_change"] == 0.15

    def test_update_convergence(self):
        """Repeated outcomes move deltas toward empirical values."""
        fm = ForwardModel(learning_rate=0.5)
        empirical_uncertainty = -0.25
        empirical_stability = 0.15

        for _ in range(10):
            outcome = PredictionOutcome(
                action_type=ActionType.EXPLAIN,
                target_id="x",
                predicted_deltas=fm.predict_delta(
                    Intervention(action_type=ActionType.EXPLAIN, target_id="x"),
                ),
                observed_deltas={
                    "uncertainty_change": empirical_uncertainty,
                    "stability_change": empirical_stability,
                },
            )
            fm.update_from_outcome(outcome)

        final = fm.predict_delta(Intervention(action_type=ActionType.EXPLAIN, target_id="x"))
        assert abs(final["uncertainty_change"] - empirical_uncertainty) < 0.01
        assert abs(final["stability_change"] - empirical_stability) < 0.01

    def test_update_returns_signed_errors(self):
        fm = ForwardModel()
        outcome = PredictionOutcome(
            action_type=ActionType.COMPARE,
            target_id="a",
            predicted_deltas={"uncertainty_change": 0.10, "confusion_reduction": 0.50},
            observed_deltas={"uncertainty_change": 0.30, "confusion_reduction": 0.40},
        )
        signed = fm.update_from_outcome(outcome)
        # signed: unc = 0.30 - 0.10 = 0.20, conf = 0.40 - 0.50 = -0.10
        assert signed["uncertainty_change"] == 0.20
        assert signed["confusion_reduction"] == -0.10

    def test_update_does_not_affect_other_action_types(self):
        fm = ForwardModel()
        explain_before = fm.predict_delta(
            Intervention(action_type=ActionType.EXPLAIN, target_id="x"),
        )
        outcome = PredictionOutcome(
            action_type=ActionType.COMPARE,
            target_id="a",
            predicted_deltas={"confusion_reduction": 0.50},
            observed_deltas={"confusion_reduction": 0.30},
        )
        fm.update_from_outcome(outcome)
        explain_after = fm.predict_delta(
            Intervention(action_type=ActionType.EXPLAIN, target_id="x"),
        )
        assert explain_before == explain_after

    def test_calibration_confidence_starts_zero(self):
        fm = ForwardModel()
        conf = fm.calibration_confidence
        for at in ActionType:
            assert conf[at.value] == 0.0

    def test_calibration_confidence_increases(self):
        fm = ForwardModel()
        outcome = PredictionOutcome(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            predicted_deltas={"uncertainty_change": -0.40},
            observed_deltas={"uncertainty_change": -0.30},
        )
        for i in range(5):
            fm.update_from_outcome(outcome)
            expected = round(min(1.0, (i + 1) / 10.0), 4)
            assert fm.calibration_confidence["explain"] == expected

    def test_calibration_confidence_max_one(self):
        fm = ForwardModel()
        outcome = PredictionOutcome(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            predicted_deltas={"uncertainty_change": -0.40},
            observed_deltas={"uncertainty_change": -0.30},
        )
        for _ in range(20):
            fm.update_from_outcome(outcome)
        assert fm.calibration_confidence["explain"] == 1.0

    def test_reset_restores_defaults(self):
        fm = ForwardModel(learning_rate=0.5)
        outcome = PredictionOutcome(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            predicted_deltas={"uncertainty_change": -0.40},
            observed_deltas={"uncertainty_change": -0.20},
        )
        fm.update_from_outcome(outcome)
        before_reset = fm.predict_delta(
            Intervention(action_type=ActionType.EXPLAIN, target_id="x"),
        )
        assert before_reset["uncertainty_change"] != -0.40

        fm.reset_calibration()
        after_reset = fm.predict_delta(
            Intervention(action_type=ActionType.EXPLAIN, target_id="x"),
        )
        assert after_reset["uncertainty_change"] == -0.40
        assert fm.total_updates == 0

    def test_update_unknown_action_type_returns_empty(self):
        fm = ForwardModel()
        outcome = PredictionOutcome(
            action_type="nonexistent",
            target_id="x",
            predicted_deltas={},
            observed_deltas={},
        )
        result = fm.update_from_outcome(outcome)
        assert result == {}

    def test_total_updates_tracks_all_actions(self):
        fm = ForwardModel()
        for at in [ActionType.EXPLAIN, ActionType.COMPARE, ActionType.REVISIT]:
            outcome = PredictionOutcome(
                action_type=at,
                target_id="x",
                predicted_deltas={"uncertainty_change": 0.0},
                observed_deltas={"uncertainty_change": 0.0},
            )
            fm.update_from_outcome(outcome)
        assert fm.total_updates == 3

    def test_modulation_still_applies_after_calibration(self):
        """Modulation is independent of calibration — it applies on top."""
        fm = ForwardModel(learning_rate=0.5)
        outcome = PredictionOutcome(
            action_type=ActionType.EXPLAIN,
            target_id="x",
            predicted_deltas={"uncertainty_change": -0.40, "stability_change": 0.20},
            observed_deltas={"uncertainty_change": -0.10, "stability_change": 0.05},
        )
        fm.update_from_outcome(outcome)

        proj = CognitiveProjection(
            nodes={
                "x": NodeProjection("x", "X", uncertainty_score=0.85, stability_score=0.6),
            }
        )
        inv = Intervention(action_type=ActionType.EXPLAIN, target_id="x")
        delta = fm.predict_delta(inv, projection=proj)
        # Base after calibration: unc=-0.25, stab=0.125 (lr=0.5)
        # With 1.3 modulation: unc=-0.25*1.3 = -0.325, stab=0.125*1.3 = 0.1625
        assert delta["uncertainty_change"] == -0.325
        assert delta["stability_change"] == 0.1625

    def test_prediction_outcome_comparator_uses_forward_model_instance(self):
        """End-to-end: comparator reads from ForwardModel, calibration affects future predictions."""
        fm = ForwardModel(learning_rate=0.5)
        comparator = PredictionOutcomeComparator(forward_model=fm)

        pre = CognitiveProjection(
            nodes={
                "x": NodeProjection("x", "X", uncertainty_score=0.6, stability_score=0.7),
            }
        )
        post = CognitiveProjection(
            nodes={
                "x": NodeProjection("x", "X", uncertainty_score=0.4, stability_score=0.75),
            }
        )
        inter = Intervention(action_type=ActionType.EXPLAIN, target_id="x")

        outcome = comparator.compare(inter, pre, post)
        fm.update_from_outcome(outcome)

        new_prediction = fm.predict_delta(inter)
        default_unc = ForwardModel._DEFAULT_DELTAS[ActionType.EXPLAIN][0]
        assert new_prediction["uncertainty_change"] != default_unc
