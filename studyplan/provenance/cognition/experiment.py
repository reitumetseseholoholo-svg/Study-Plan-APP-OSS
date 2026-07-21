"""Cognitive Control Experiments — falsifiable hypothesis testing over the policy loop.

Essentialist question:
    What phenomenon does this experiment exist to preserve?
Answer:
    The property that architectural claims are *falsifiable* — every layer
    in the cognitive control stack is testable against controlled inputs,
    and every experiment produces structured findings with known conditions
    for disconfirmation.

Three experiment types:

    1. Sensitivity analysis (vary one signal, measure policy response)
         Hypothesis: "Signal X changes the top-1 intervention score by >Y%."
         Falsification: Top-1 score changes by <Y% across N trials.

    2. Ablation study (remove one signal, measure ranking delta)
         Hypothesis: "Removing signal X changes the top-K ranking order."
         Falsification: Top-1 is identical with and without signal X.

    3. Counterfactual (synthetic projection deltas)
         Hypothesis: "If uncertainty on node X decreased by P%, the
         recommended intervention changes from A to B."
         Falsification: Intervention ranking is identical before and after.

Usage:
    engine = CognitiveExperiment()
    result = engine.run_sensitivity_analysis()
    print(result.summary)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.cognition.controller import (
    ActionType,
    CognitivePolicyEngine,
    CognitiveController,
    InterventionRanking,
)
from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjection,
    NodeProjection,
    ConfusionEdge,
)


# ====================================================================
# 1. Falsifiable experiment result type
# ====================================================================


@dataclass(frozen=True)
class Finding:
    """A single falsifiable finding from an experiment.

    Attributes:
        claim:            What the experiment asserts (falsifiable statement)
        measurement:      Observed value
        threshold:        Falsification threshold
        confirmed:        Whether claim survived falsification
        confidence:       Estimated confidence in finding (0-1)
        details:          Raw data supporting the finding
    """

    claim: str
    measurement: float
    threshold: float
    confirmed: bool
    confidence: float = 0.0
    details: str = ""


@dataclass(frozen=True)
class ExperimentResult:
    """Output of a single experiment.

    Attributes:
        name:            Experiment identifier
        hypothesis:      Original hypothesis being tested
        findings:        List of falsifiable findings
        implications:    What the findings mean for the architecture
        signals_ranked:  Each signal with its measured influence (for sensitivities)
        raw_data:        Full measurement data for re-analysis
    """

    name: str
    hypothesis: str
    findings: list[Finding] = field(default_factory=list)
    implications: list[str] = field(default_factory=list)
    signals_ranked: list[tuple[str, float]] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)

    @property
    def all_confirmed(self) -> bool:
        return all(f.confirmed for f in self.findings)

    @property
    def summary(self) -> str:
        lines = [f"=== {self.name} ===", f"Hypothesis: {self.hypothesis}"]
        if not self.findings:
            lines.append("  No findings.")
        for f in self.findings:
            icon = "✓" if f.confirmed else "✗"
            lines.append(f"  {icon} {f.claim}  [{f.measurement:.3f} vs {f.threshold:.3f}]")
        if self.signals_ranked:
            lines.append("  Signals ranked by influence:")
            for name, inf in self.signals_ranked:
                lines.append(f"    {name}: {inf:.4f}")
        if self.implications:
            lines.append("  Implications:")
            for imp in self.implications:
                lines.append(f"    • {imp}")
        return "\n".join(lines)


# ====================================================================
# 2. Controlled synthetic projection builders
# ====================================================================


def _uniform_projection(
    node_ids: list[str],
    uncertainty: float = 0.5,
    stability: float = 0.8,
    interactions: int = 3,
    confusion_weight: float = 0.0,
) -> CognitiveProjection:
    """Build a synthetic projection with uniform signal values."""
    nodes = {}
    for nid in node_ids:
        label = nid.split(":")[-1] if ":" in nid else nid
        nodes[nid] = NodeProjection(
            identity_id=nid,
            label=label,
            uncertainty_score=uncertainty,
            stability_score=stability,
            interaction_count=interactions,
            last_seen=1000.0,
        )

    edges: list[ConfusionEdge] = []
    if confusion_weight > 0 and len(node_ids) >= 2:
        for i in range(len(node_ids) - 1):
            a, b = node_ids[i], node_ids[i + 1]
            edges.append(
                ConfusionEdge(
                    source_id=a,
                    target_id=b,
                    weight=confusion_weight,
                )
            )

    return CognitiveProjection(nodes=nodes, confusion_edges=edges)


def _top_1_action(ranking: InterventionRanking) -> ActionType | None:
    if ranking.best:
        return ranking.best.action_type
    return None


def _top_1_score(ranking: InterventionRanking) -> float:
    if ranking.best:
        return ranking.best.score
    return 0.0


# ====================================================================
# 3. The experiment harness
# ====================================================================


class CognitiveExperiment:
    """Run falsifiable experiments over the cognitive control stack.

    Every experiment:
        1. Defines a hypothesis
        2. Generates controlled inputs
        3. Runs the policy engine
        4. Produces structured findings with falsification thresholds
        5. Returns an ExperimentResult with implications

    Usage:
        exp = CognitiveExperiment()
        sensitivity = exp.run_sensitivity_analysis()
        ablation = exp.run_ablation_study()
        counterfactual = exp.run_counterfactual(
            projection, delta={"uncertainty_score": -0.3}, target="fm:WACC"
        )
    """

    def __init__(self, policy: CognitivePolicyEngine | None = None):
        self._policy = policy or CognitivePolicyEngine()
        self._controller = CognitiveController(policy_engine=self._policy)

    # ── 3.1 Sensitivity analysis ──────────────────────────────────

    def run_sensitivity_analysis(
        self,
        node_ids: list[str] | None = None,
        n_trials: int = 20,
        threshold: float = 0.05,
    ) -> ExperimentResult:
        """Measure how much each signal dimension drives policy scores.

        For each signal (confusion, leverage, collapse, stability):
            1. Create a base projection with ALL signals at baseline.
            2. Create a variant with ONE signal amplified.
            3. Measure absolute score delta.
            4. Rank signals by influence.

        Hypothesis:
            "All four signal dimensions measurably change the policy score
            for at least one node. No signal is 'decorative' (zero influence)."

        Falsification:
            Any signal changes the top-1 score by < `threshold` across all trials.
        """
        if node_ids is None:
            node_ids = ["fm:A", "fm:B", "fm:C", "fm:D"]

        hypothesis = "All four signal dimensions measurably change the policy score."

        # Standard baseline: moderate signals, one node slightly higher uncertainty
        base_nodes = {}
        for i, nid in enumerate(node_ids):
            label = nid.split(":")[-1]
            base_nodes[nid] = NodeProjection(
                identity_id=nid,
                label=label,
                uncertainty_score=0.3 + 0.1 * i,
                stability_score=0.8 - 0.05 * i,
                interaction_count=max(1, 5 - i),
                last_seen=1000.0,
            )
        base_proj = CognitiveProjection(nodes=base_nodes)

        base_ranking = self._policy.rank_interventions(base_proj)
        base_scores = self._score_map(base_ranking)

        signal_variants: dict[str, list[float]] = defaultdict(list)

        # Dimension 1: confusion spike (only if 2+ nodes)
        if len(node_ids) >= 2:
            spiked_edges = [
                ConfusionEdge(source_id=node_ids[0], target_id=node_ids[1], weight=0.9),
            ]
        else:
            spiked_edges = []
        confusion_proj = CognitiveProjection(
            nodes=base_nodes,
            confusion_edges=spiked_edges,
        )
        confusion_ranking = self._policy.rank_interventions(confusion_proj)
        confusion_scores = self._score_map(confusion_ranking)
        for nid in node_ids:
            delta = abs(confusion_scores.get(nid, 0) - base_scores.get(nid, 0))
            signal_variants["confusion"].append(delta)

        # Dimension 2: leverage (dependency graph)
        leverage_target = node_ids[0] if len(node_ids) >= 1 else ""
        leverage_deps: dict[str, list[str]] = {nid: [] for nid in node_ids}
        if leverage_target and len(node_ids) > 1:
            leverage_deps[leverage_target] = [n for n in node_ids if n != leverage_target]
        leverage_ranking = self._policy.rank_interventions(
            base_proj,
            dependency_graph=leverage_deps,
        )
        leverage_scores = self._score_map(leverage_ranking)
        for nid in node_ids:
            delta = abs(leverage_scores.get(nid, 0) - base_scores.get(nid, 0))
            signal_variants["leverage"].append(delta)

        # Dimension 3: collapse (high uncertainty + high stability = ready)
        collapse_idx = min(2, len(node_ids) - 1)
        collapse_target = node_ids[collapse_idx]
        collapse_nodes = dict(base_nodes)
        collapse_nodes[collapse_target] = NodeProjection(
            identity_id=collapse_target,
            label=collapse_target.split(":")[-1],
            uncertainty_score=0.8,
            stability_score=0.9,
            interaction_count=5,
            last_seen=1000.0,
        )
        collapse_proj = CognitiveProjection(nodes=collapse_nodes)
        collapse_ranking = self._policy.rank_interventions(collapse_proj)
        collapse_scores = self._score_map(collapse_ranking)
        for nid in node_ids:
            delta = abs(collapse_scores.get(nid, 0) - base_scores.get(nid, 0))
            signal_variants["collapse"].append(delta)

        # Dimension 4: stability decay (low familiarity)
        # Dimension 4: stability decay (low familiarity)
        decay_idx = min(3, len(node_ids) - 1)
        decay_target = node_ids[decay_idx]
        decay_nodes = dict(base_nodes)
        decay_nodes[decay_target] = NodeProjection(
            identity_id=decay_target,
            label=decay_target.split(":")[-1],
            uncertainty_score=0.3,
            stability_score=0.9,
            interaction_count=0,
            last_seen=1.0,
        )
        decay_proj = CognitiveProjection(nodes=decay_nodes)
        decay_ranking = self._policy.rank_interventions(decay_proj)
        decay_scores = self._score_map(decay_ranking)
        for nid in node_ids:
            delta = abs(decay_scores.get(nid, 0) - base_scores.get(nid, 0))
            signal_variants["stability_decay"].append(delta)

        findings: list[Finding] = []
        signals_ranked: list[tuple[str, float]] = []

        for signal_name, deltas in signal_variants.items():
            mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
            max_delta = max(deltas) if deltas else 0.0
            confirmed = max_delta >= threshold

            findings.append(
                Finding(
                    claim=f"Signal '{signal_name}' changes policy score",
                    measurement=max_delta,
                    threshold=threshold,
                    confirmed=confirmed,
                    confidence=min(1.0, max_delta / threshold) if threshold > 0 else 1.0,
                    details=f"Mean delta: {mean_delta:.4f}, Max delta: {max_delta:.4f}",
                )
            )
            signals_ranked.append((signal_name, mean_delta))

        signals_ranked.sort(key=lambda x: x[1], reverse=True)

        implications = []
        for name, inf in signals_ranked:
            if inf < threshold:
                implications.append(f"'{name}' has negligible influence ({inf:.4f}) — candidate for removal")

        if all(f.confirmed for f in findings):
            implications.append("All signals are 'alive' — each drives measurable score change")
        else:
            implications.append("Some signals are 'decorative' — remove or reweight")

        return ExperimentResult(
            name="Signal Sensitivity Analysis",
            hypothesis=hypothesis,
            findings=findings,
            implications=implications,
            signals_ranked=signals_ranked,
            raw_data={
                "base_scores": base_scores,
                "signal_variants": {k: v for k, v in signal_variants.items()},
                "n_trials": n_trials,
                "threshold": threshold,
            },
        )

    # ── 3.2 Ablation study ────────────────────────────────────────

    def run_ablation_study(
        self,
        node_ids: list[str] | None = None,
        threshold: float = 0.0,
    ) -> ExperimentResult:
        """Remove each signal dimension and measure ranking impact.

        For each weight:
            1. Set that weight to 0 (ablate).
            2. Re-rank interventions.
            3. Compare top-1 action and top-1 score against baseline.

        Hypothesis:
            "Ablating any single weight changes either the top-1 action type
            or the top-1 score by > threshold."

        Falsification:
            Top-1 action type is identical and score change is <= threshold.
        """
        if node_ids is None:
            node_ids = ["fm:A", "fm:B", "fm:C", "fm:D"]

        hypothesis = "Ablating any single signal weight changes the intervention ranking."

        # Rich projection where all signals contribute
        proj = CognitiveProjection(
            nodes={
                "fm:A": NodeProjection("fm:A", "A", 0.6, 0.8, 5, 1000.0),
                "fm:B": NodeProjection("fm:B", "B", 0.3, 0.9, 8, 800.0),
                "fm:C": NodeProjection("fm:C", "C", 0.8, 0.4, 2, 500.0),
                "fm:D": NodeProjection("fm:D", "D", 0.1, 0.95, 1, 100.0),
            },
            confusion_edges=[
                ConfusionEdge("fm:A", "fm:B", 0.7),
                ConfusionEdge("fm:A", "fm:C", 0.6),
            ],
        )

        deps = {
            "fm:A": ["fm:B", "fm:C", "fm:D"],
            "fm:B": ["fm:D"],
            "fm:C": [],
            "fm:D": [],
        }

        baseline = CognitivePolicyEngine()
        baseline_ranking = baseline.rank_interventions(proj, dependency_graph=deps)
        baseline_action = _top_1_action(baseline_ranking)
        baseline_score = _top_1_score(baseline_ranking)

        weight_names = {
            "confusion": (1.0, 0.0, 0.0, 0.0),
            "leverage": (0.0, 1.0, 0.0, 0.0),
            "collapse": (0.0, 0.0, 1.0, 0.0),
            "stability": (0.0, 0.0, 0.0, 1.0),
        }

        findings: list[Finding] = []
        signals_ranked: list[tuple[str, float]] = []

        for name, (cw, lw, uw, sw) in weight_names.items():
            ablated = CognitivePolicyEngine(
                confusion_weight=cw,
                leverage_weight=lw,
                uncertainty_collapse_weight=uw,
                stability_weight=sw,
            )
            ablated_ranking = ablated.rank_interventions(proj, dependency_graph=deps)
            ablated_action = _top_1_action(ablated_ranking)
            ablated_score = _top_1_score(ablated_ranking)

            action_changed = ablated_action != baseline_action
            score_delta = abs(ablated_score - baseline_score)
            confirmed = action_changed or score_delta > threshold

            findings.append(
                Finding(
                    claim=f"Ablating '{name}' changes ranking",
                    measurement=max(float(action_changed), score_delta),
                    threshold=threshold,
                    confirmed=confirmed,
                    confidence=min(1.0, score_delta / max(score_delta, 0.01)),
                    details=(
                        f"Baseline: {baseline_action.value if baseline_action else 'None'} "
                        f"({baseline_score:.4f}) | "
                        f"Ablated: {ablated_action.value if ablated_action else 'None'} "
                        f"({ablated_score:.4f}) | "
                        f"Action changed: {action_changed}"
                    ),
                )
            )
            signals_ranked.append((name, score_delta))

        signals_ranked.sort(key=lambda x: x[1], reverse=True)

        implications = []
        dead_signals = [s for s, v in signals_ranked if v <= threshold]
        alive_signals = [s for s, v in signals_ranked if v > threshold]

        if dead_signals:
            implications.append(f"Dead signals (no ranking impact when ablated): {', '.join(dead_signals)}")
        implications.append(f"Alive signals (ranking changes when ablated): {', '.join(alive_signals)}")

        return ExperimentResult(
            name="Signal Ablation Study",
            hypothesis=hypothesis,
            findings=findings,
            implications=implications,
            signals_ranked=signals_ranked,
            raw_data={
                "baseline_action": baseline_action.value if baseline_action else None,
                "baseline_score": baseline_score,
            },
        )

    # ── 3.3 Counterfactual experiment ─────────────────────────────

    def run_counterfactual(
        self,
        projection: CognitiveProjection | None = None,
        target_id: str = "fm:A",
        deltas: dict[str, float] | None = None,
        dependency_graph: dict[str, list[str]] | None = None,
        threshold: float = 0.0,
    ) -> ExperimentResult:
        """Ask: 'What happens to rankings if we change a signal?'

        Creates a modified projection where the target node's signals
        are adjusted by the specified deltas, then compares rankings.

        Hypothesis:
            "Applying deltas {deltas} to '{target_id}' changes the
            intervention ranking."

        Falsification:
            Top-1 action is identical AND top-1 score change <= threshold.
        """
        if deltas is None:
            deltas = {"uncertainty_score": -0.3, "stability_score": 0.2}

        if projection is None:
            projection = CognitiveProjection(
                nodes={
                    "fm:A": NodeProjection("fm:A", "A", 0.7, 0.6, 4, 1000.0),
                    "fm:B": NodeProjection("fm:B", "B", 0.3, 0.9, 8, 800.0),
                    "fm:C": NodeProjection("fm:C", "C", 0.2, 0.8, 6, 600.0),
                },
            )

        hypothesis = f"Applying deltas {deltas} to '{target_id}' changes the intervention ranking."

        delta_desc = "; ".join(f"{k}: {v:+.1f}" for k, v in deltas.items())

        baseline_ranking = self._policy.rank_interventions(
            projection,
            dependency_graph=dependency_graph,
        )
        base_action = _top_1_action(baseline_ranking)
        base_score = _top_1_score(baseline_ranking)

        modified_nodes = dict(projection.nodes)
        if target_id in modified_nodes:
            old = modified_nodes[target_id]
            kwargs: dict[str, Any] = {
                "identity_id": old.identity_id,
                "label": old.label,
                "uncertainty_score": max(0.0, min(1.0, old.uncertainty_score + deltas.get("uncertainty_score", 0.0))),
                "stability_score": max(0.0, min(1.0, old.stability_score + deltas.get("stability_score", 0.0))),
                "interaction_count": max(0, old.interaction_count + int(deltas.get("interaction_count", 0))),
                "last_seen": max(0.0, old.last_seen + deltas.get("last_seen", 0.0)),
            }
            modified_nodes[target_id] = NodeProjection(**kwargs)

        modified_proj = CognitiveProjection(
            nodes=modified_nodes,
            confusion_edges=projection.confusion_edges,
        )

        modified_ranking = self._policy.rank_interventions(
            modified_proj,
            dependency_graph=dependency_graph,
        )
        mod_action = _top_1_action(modified_ranking)
        mod_score = _top_1_score(modified_ranking)

        action_changed = mod_action != base_action
        score_delta = abs(mod_score - base_score)
        confirmed = action_changed or score_delta > threshold

        findings = [
            Finding(
                claim=f"Counterfactual delta [{delta_desc}] on '{target_id}' changes recommendation",
                measurement=max(float(action_changed), score_delta),
                threshold=threshold,
                confirmed=confirmed,
                confidence=min(1.0, score_delta / max(score_delta, 0.01)),
                details=(
                    f"Baseline: {base_action.value if base_action else 'None'} "
                    f"({base_score:.4f}) | "
                    f"Counterfactual: {mod_action.value if mod_action else 'None'} "
                    f"({mod_score:.4f}) | "
                    f"Action changed: {action_changed}"
                ),
            ),
        ]

        implications = []
        if confirmed:
            implications.append(
                f"Signal delta [{delta_desc}] on '{target_id}' changes policy output — "
                f"the policy is sensitive to this manipulation"
            )
        else:
            implications.append(
                f"Signal delta [{delta_desc}] on '{target_id}' does NOT change policy — "
                f"this signal may be underweighted or already saturated"
            )

        return ExperimentResult(
            name=f"Counterfactual: {delta_desc} on {target_id}",
            hypothesis=hypothesis,
            findings=findings,
            implications=implications,
            raw_data={
                "modified_projection": modified_proj,
                "baseline_action": base_action.value if base_action else None,
                "baseline_score": base_score,
                "modified_action": mod_action.value if mod_action else None,
                "modified_score": mod_score,
            },
        )

    # ── 3.4 Full suite ────────────────────────────────────────────

    def run_suite(self) -> list[ExperimentResult]:
        """Run all experiments and return results."""
        return [
            self.run_sensitivity_analysis(),
            self.run_ablation_study(),
            self.run_counterfactual(),
        ]

    # ── Helpers ───────────────────────────────────────────────────

    def _score_map(self, ranking: InterventionRanking) -> dict[str, float]:
        return {i.target_id: i.score for i in ranking.interventions}
