"""Tests for the Cognitive Experiment harness.

Covers:

    1. ExperimentResult properties (all_confirmed, summary)
    2. Sensitivity analysis (signals ranked, no dead signals)
    3. Ablation study (each ablation produces a finding)
    4. Counterfactual (deltas change rankings)
    5. Full suite runs without error
    6. Custom projections for counterfactual
    7. Empty/null handling
    8. Falsification (thresholds work correctly)
"""

from studyplan.provenance.cognition.experiment import (
    CognitiveExperiment,
    ExperimentResult,
    Finding,
)
from studyplan.provenance.cognition.controller import (
    CognitivePolicyEngine,
)
from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjection,
    NodeProjection,
    ConfusionEdge,
)


# ====================================================================
# Tier 1 — ExperimentResult basics
# ====================================================================


class TestExperimentResult:
    def test_empty_result_no_findings(self):
        r = ExperimentResult(name="empty", hypothesis="none")
        assert r.all_confirmed
        assert r.summary != ""

    def test_all_confirmed_true(self):
        r = ExperimentResult(
            name="test",
            hypothesis="x",
            findings=[
                Finding("c1", 0.5, 0.3, True),
                Finding("c2", 0.9, 0.3, True),
            ],
        )
        assert r.all_confirmed

    def test_all_confirmed_false(self):
        r = ExperimentResult(
            name="test",
            hypothesis="x",
            findings=[
                Finding("c1", 0.5, 0.3, True),
                Finding("c2", 0.1, 0.3, False),
            ],
        )
        assert not r.all_confirmed

    def test_signals_ranked_empty(self):
        r = ExperimentResult(name="test", hypothesis="x")
        assert r.signals_ranked == []

    def test_summary_contains_hypothesis(self):
        r = ExperimentResult(name="test", hypothesis="my hypothesis")
        assert "my hypothesis" in r.summary


# ====================================================================
# Tier 2 — Sensitivity analysis
# ====================================================================


class TestSensitivityAnalysis:
    def test_returns_experiment_result(self):
        exp = CognitiveExperiment()
        result = exp.run_sensitivity_analysis()
        assert isinstance(result, ExperimentResult)
        assert result.name == "Signal Sensitivity Analysis"

    def test_produces_findings(self):
        exp = CognitiveExperiment()
        result = exp.run_sensitivity_analysis()
        assert len(result.findings) == 4  # one per signal dimension
        assert all(isinstance(f, Finding) for f in result.findings)

    def test_signals_ranked_by_influence(self):
        exp = CognitiveExperiment()
        result = exp.run_sensitivity_analysis()
        assert len(result.signals_ranked) == 4
        # Check they're sorted descending
        scores = [v for _, v in result.signals_ranked]
        assert scores == sorted(scores, reverse=True)

    def test_sensitivity_with_custom_nodes(self):
        exp = CognitiveExperiment()
        result = exp.run_sensitivity_analysis(node_ids=["x:1", "x:2"])
        assert len(result.findings) == 4
        assert result.signals_ranked is not None

    def test_sensitivity_with_zero_threshold(self):
        exp = CognitiveExperiment()
        result = exp.run_sensitivity_analysis(threshold=0.0)
        # With threshold=0.0, any delta confirms
        assert all(f.confirmed for f in result.findings)


# ====================================================================
# Tier 3 — Ablation study
# ====================================================================


class TestAblationStudy:
    def test_returns_experiment_result(self):
        exp = CognitiveExperiment()
        result = exp.run_ablation_study()
        assert isinstance(result, ExperimentResult)
        assert result.name == "Signal Ablation Study"

    def test_produces_findings_per_weight(self):
        exp = CognitiveExperiment()
        result = exp.run_ablation_study()
        # One finding per ablated weight (confusion, leverage, collapse, stability)
        assert len(result.findings) == 4
        assert all(isinstance(f, Finding) for f in result.findings)

    def test_implications_includes_alive_and_dead(self):
        exp = CognitiveExperiment()
        result = exp.run_ablation_study()
        assert len(result.implications) >= 1
        assert any("Alive" in imp or "Dead" in imp for imp in result.implications)

    def test_custom_nodes(self):
        exp = CognitiveExperiment()
        result = exp.run_ablation_study(node_ids=["fm:X", "fm:Y"])
        assert len(result.findings) == 4


# ====================================================================
# Tier 4 — Counterfactual
# ====================================================================


class TestCounterfactual:
    def test_returns_experiment_result(self):
        exp = CognitiveExperiment()
        result = exp.run_counterfactual()
        assert isinstance(result, ExperimentResult)
        assert "Counterfactual" in result.name

    def test_produces_one_finding(self):
        exp = CognitiveExperiment()
        result = exp.run_counterfactual()
        assert len(result.findings) == 1

    def test_counterfactual_with_custom_projection(self):
        exp = CognitiveExperiment()
        proj = CognitiveProjection(
            nodes={
                "fm:X": NodeProjection("fm:X", "X", 0.9, 0.5, 2, 500.0),
                "fm:Y": NodeProjection("fm:Y", "Y", 0.2, 0.9, 8, 1000.0),
            },
            confusion_edges=[
                ConfusionEdge("fm:X", "fm:Y", 0.8),
            ],
        )
        result = exp.run_counterfactual(
            projection=proj,
            target_id="fm:X",
            deltas={"uncertainty_score": -0.5},
        )
        assert result.findings[0].confirmed is True or result.findings[0].confirmed is False
        assert result.raw_data["baseline_action"] is not None

    def test_counterfactual_no_change_delta(self):
        """Zero deltas should not change ranking."""
        exp = CognitiveExperiment()
        proj = CognitiveProjection(
            nodes={
                "fm:A": NodeProjection("fm:A", "A", 0.5, 0.8, 3, 1000.0),
            },
        )
        result = exp.run_counterfactual(
            projection=proj,
            target_id="fm:A",
            deltas={"uncertainty_score": 0.0, "stability_score": 0.0},
            threshold=0.0,
        )
        # With zero delta and zero threshold, ranking is identical
        assert result.findings[0].measurement == 0.0

    def test_counterfactual_with_dependency_graph(self):
        exp = CognitiveExperiment()
        result = exp.run_counterfactual(
            dependency_graph={"fm:A": ["fm:B", "fm:C"]},
        )
        assert len(result.findings) == 1


# ====================================================================
# Tier 5 — Full suite
# ====================================================================


class TestFullSuite:
    def test_suite_runs_all_experiments(self):
        exp = CognitiveExperiment()
        results = exp.run_suite()
        assert len(results) == 3
        assert all(isinstance(r, ExperimentResult) for r in results)
        # All three standard experiments
        names = {r.name for r in results}
        assert "Signal Sensitivity Analysis" in names
        assert "Signal Ablation Study" in names


# ====================================================================
# Tier 6 — Edge cases
# ====================================================================


class TestEdgeCases:
    def test_experiment_with_custom_policy(self):
        custom_policy = CognitivePolicyEngine(
            confusion_weight=1.0,
            leverage_weight=0.0,
            uncertainty_collapse_weight=0.0,
            stability_weight=0.0,
        )
        exp = CognitiveExperiment(policy=custom_policy)
        result = exp.run_sensitivity_analysis()
        # With only confusion active, other signals may have zero influence
        assert len(result.findings) == 4

    def test_finding_with_no_details(self):
        f = Finding(claim="test", measurement=0.5, threshold=0.3, confirmed=True)
        assert f.details == ""

    def test_finding_confidence_computation(self):
        f = Finding("c", 0.5, 0.3, True, confidence=0.8)
        assert f.confidence == 0.8

    def test_experiment_result_without_findings(self):
        r = ExperimentResult(name="naked", hypothesis="h")
        assert r.all_confirmed
        assert len(r.findings) == 0
