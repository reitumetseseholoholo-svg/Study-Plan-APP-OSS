"""Diagnostic process template — Bayesian belief updating over hypotheses.

A diagnostic process maintains a belief state (posterior distribution over
hypotheses) that evolves as evidence arrives.  It can also recommend the
next investigation with the highest expected information gain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from studyplan.domain_reasoning.process.base import ProcessTemplate


# ---------------------------------------------------------------------------
# Configuration data structures
# ---------------------------------------------------------------------------


@dataclass
class ProcessHypothesis:
    """One candidate explanation in the diagnostic hypothesis space."""

    id: str
    label: str = ""
    prior: float = 0.5


@dataclass
class ProcessFeature:
    """An observable feature that provides evidence for/against hypotheses."""

    id: str
    type: str = "categorical"  # "categorical" | "continuous"
    values: list[str] | None = None
    unit: str = ""
    range: tuple[float, float] | None = None


@dataclass
class ProcessAction:
    """An investigation the process can recommend to gather more evidence."""

    id: str
    label: str = ""
    cost: float = 0.5
    risk: float = 0.0


@dataclass
class DiagnosticConfig:
    """Configuration for a ``type="diagnostic"`` process declaration."""

    hypotheses: list[ProcessHypothesis] = field(default_factory=list)
    features: list[ProcessFeature] = field(default_factory=list)
    likelihoods: dict[str, dict[str, Any]] = field(default_factory=dict)
    update: str = "bayesian"
    stop_when: str = "max_posterior > 0.95"
    investigations: list[ProcessAction] = field(default_factory=list)
    output: str = "primary_diagnosis"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class DiagnosticTemplate(ProcessTemplate):
    """Bayesian belief-updating template for diagnostic reasoning.

    Usage::

        config = DiagnosticConfig(
            hypotheses=[ProcessHypothesis(id="stemi", prior=0.10), ...],
            features=[ProcessFeature(id="ecg", type="categorical", ...), ...],
            likelihoods={"stemi": {"ecg": {"st_elevation": 0.95, ...}}, ...},
        )
        template = DiagnosticTemplate("med.chest_pain_ddx", config)
        result = template.solve({"ecg": "st_elevation", "troponin": 15.0})
    """

    def __init__(self, concept_id: str, config: DiagnosticConfig) -> None:
        self.concept_id = concept_id
        self.config = config
        self._normalize_priors()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run one pass of the diagnostic process with all available evidence.

        Args:
            inputs: ``{feature_id: observed_value | list[observed_value]}``

        Returns a dict with posteriors, MAP hypothesis, entropy, evidence
        trail, and recommended next investigations.
        """
        posteriors = {h.id: h.prior for h in self.config.hypotheses}
        evidence_trail: list[dict[str, Any]] = []

        observations = self._extract_observations(inputs)
        for obs in observations:
            fid = obs["feature"]
            val = obs["value"]

            likes: dict[str, float] = {}
            for h in self.config.hypotheses:
                likes[h.id] = self._compute_likelihood(h.id, fid, val)

            unnorm = {h.id: likes[h.id] * posteriors[h.id] for h in self.config.hypotheses}
            norm = sum(unnorm.values())
            if norm > 0:
                for hid in unnorm:
                    posteriors[hid] = unnorm[hid] / norm

            evidence_trail.append(
                {
                    "step": len(evidence_trail),
                    "feature": fid,
                    "value": val,
                    "likelihoods": likes,
                    "posteriors": dict(posteriors),
                }
            )

        entropy = self._compute_entropy(posteriors)
        map_hid = max(posteriors, key=lambda k: posteriors[k]) if posteriors else None
        map_prob = posteriors[map_hid] if map_hid else 0.0

        return {
            "concept_id": self.concept_id,
            "result": {
                "primary_diagnosis": map_hid,
                "confidence": map_prob,
                "posterior_distribution": dict(posteriors),
                "entropy": entropy,
                "evidence_count": len(evidence_trail),
            },
            "inputs": dict(inputs),
            "is_nan": False,
            "steps": evidence_trail,
            "posterior_distribution": dict(posteriors),
            "map_hypothesis": map_hid,
            "map_probability": map_prob,
            "entropy": entropy,
            "recommended_investigations": self._recommend_investigations(posteriors, entropy),
        }

    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not learner_steps or not truth:
            return []
        truth_dx = truth.get("map_hypothesis") or (truth.get("result") or {}).get("primary_diagnosis")
        results: list[dict[str, Any]] = []
        for step in learner_steps:
            step_val = step.get("diagnosis") or step.get("value")
            match = False
            if isinstance(step_val, str) and isinstance(truth_dx, str):
                match = step_val.strip().lower() == truth_dx.strip().lower()
            results.append(
                {
                    "step_id": step.get("step_id", ""),
                    "expected": truth_dx,
                    "actual": step_val,
                    "match": match,
                }
            )
        return results

    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]:
        tags: list[str] = []
        if not learner_steps or not truth:
            return tags
        truth_dx = truth.get("map_hypothesis") or (truth.get("result") or {}).get("primary_diagnosis")

        hypotheses_considered: set[str] = set()
        final_answer: str | None = None
        for step in learner_steps:
            sv = step.get("diagnosis") or step.get("value")
            if isinstance(sv, str):
                svn = sv.strip().lower()
                hypotheses_considered.add(svn)
                final_answer = svn
                if truth_dx and isinstance(truth_dx, str) and svn == truth_dx.strip().lower():
                    pass

        truth_lower = truth_dx.strip().lower() if truth_dx and isinstance(truth_dx, str) else None
        if truth_lower and final_answer and final_answer != truth_lower:
            if truth_lower not in hypotheses_considered:
                tags.append("hypothesis_not_considered")
            else:
                tags.append("wrong_diagnosis")

        evidence_count = sum(1 for s in learner_steps if s.get("type") == "observation" or s.get("feature"))
        if evidence_count < 2:
            tags.append("insufficient_evidence")

        return tags

    def expected_information_gain(
        self,
        posteriors: dict[str, float],
        feature_id: str,
        possible_values: list[Any] | None = None,
        outcome_probs: list[float] | None = None,
    ) -> float:
        """Expected Information Gain (in bits) for observing a feature.

        Computes ``H(current) - E[H(posterior | evidence)]`` over the
        possible outcomes of observing *feature_id*.

        Args:
            posteriors: Current posterior distribution ``{hyp_id: prob}``.
            feature_id: The feature whose observation would reduce uncertainty.
            possible_values: Possible observed values for the feature.
                Defaults to the feature's declared ``values`` if categorical,
                or ``[True, False]`` if not declared.
            outcome_probs: Prior probability of each value being observed.
                Defaults to uniform.

        Returns:
            Expected information gain in bits (>= 0).
        """
        if not posteriors:
            return 0.0

        # Resolve possible values from config if not provided
        if possible_values is None:
            for feat in self.config.features:
                if feat.id == feature_id and feat.type == "categorical" and feat.values:
                    possible_values = feat.values
                    break
            if possible_values is None:
                possible_values = [True, False]

        n = len(possible_values)
        if outcome_probs is None:
            outcome_probs = [1.0 / n] * n
        elif len(outcome_probs) != n:
            outcome_probs = [1.0 / n] * n

        current_entropy = self._compute_entropy(posteriors)
        expected_posterior_entropy = 0.0

        for value, prob in zip(possible_values, outcome_probs, strict=True):
            # Compute posterior after observing this value
            unnorm = {}
            for h in self.config.hypotheses:
                likes = self._compute_likelihood(h.id, feature_id, value)
                unnorm[h.id] = likes * posteriors.get(h.id, 0.0)
            norm = sum(unnorm.values())
            if norm > 0:
                simulated = {hid: unnorm[hid] / norm for hid in unnorm}
            else:
                simulated = dict(posteriors)  # no update
            expected_posterior_entropy += prob * self._compute_entropy(simulated)

        return max(0.0, current_entropy - expected_posterior_entropy)

    def _recommend_investigations(
        self,
        posteriors: dict[str, float],
        current_entropy: float,
    ) -> list[dict[str, Any]]:
        """Score candidate investigations by expected information gain / cost."""
        if not self.config.investigations:
            return []
        if current_entropy < 0.1:
            return []
        scored: list[dict[str, Any]] = []
        for act in self.config.investigations:
            fid = act.id if not act.id.startswith("investigate_") else act.id
            eig = self.expected_information_gain(posteriors, fid)
            net_value = eig - (act.cost * 0.3) - (act.risk * 0.5)
            scored.append(
                {
                    "action_id": act.id,
                    "label": act.label,
                    "cost": act.cost,
                    "risk": act.risk,
                    "expected_gain": round(eig, 4),
                    "score": round(max(net_value, 0.0), 4),
                }
            )
        scored.sort(key=lambda x: -x["score"])
        return scored[:3]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_priors(self) -> None:
        total = sum(h.prior for h in self.config.hypotheses)
        if total <= 0.0:
            n = max(len(self.config.hypotheses), 1)
            for h in self.config.hypotheses:
                h.prior = 1.0 / n
        elif abs(total - 1.0) > 1e-9:
            for h in self.config.hypotheses:
                h.prior = h.prior / total

    @staticmethod
    def _extract_observations(inputs: dict[str, Any]) -> list[dict[str, Any]]:
        obs: list[dict[str, Any]] = []
        for key, value in inputs.items():
            if key.startswith("_"):
                continue
            if isinstance(value, list):
                for v in value:
                    obs.append({"feature": key, "value": v})
            else:
                obs.append({"feature": key, "value": value})
        return obs

    def _compute_likelihood(
        self,
        h_id: str,
        feature_id: str,
        value: Any,
    ) -> float:
        h_likes = (self.config.likelihoods or {}).get(h_id, {})
        feat_likes = h_likes.get(feature_id, {})
        if not isinstance(feat_likes, dict):
            return 0.5

        if "distribution" in feat_likes:
            return self._continuous_likelihood(feat_likes, value)
        return self._categorical_likelihood(feat_likes, value)

    @staticmethod
    def _continuous_likelihood(params: dict[str, Any], value: Any) -> float:
        if not isinstance(value, (int, float)):
            return 0.5
        dist = params.get("distribution", "normal")
        mean = float(params.get("mean", 0))
        sd = float(params.get("sd", 1))
        if sd <= 0.0:
            sd = 0.1
        if dist == "log_normal":
            if value <= 0:
                return 1e-9
            lnx = math.log(value)
            pdf = (1.0 / (value * sd * math.sqrt(2.0 * math.pi))) * math.exp(-((lnx - mean) ** 2) / (2.0 * sd**2))
        else:
            pdf = (1.0 / (sd * math.sqrt(2.0 * math.pi))) * math.exp(-((value - mean) ** 2) / (2.0 * sd**2))
        return max(pdf, 1e-9)

    @staticmethod
    def _categorical_likelihood(lookup: dict[str, Any], value: Any) -> float:
        str_val = str(value).strip().lower()
        for k, v in lookup.items():
            if str(k).strip().lower() == str_val:
                return float(v)
        return 0.01  # unknown value — small uniform probability

    @staticmethod
    def _compute_entropy(posteriors: dict[str, float]) -> float:
        h_val = 0.0
        for p in posteriors.values():
            if p > 0.0:
                h_val -= p * math.log2(p)
        return h_val


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_diagnostic_template(
    concept_id: str,
    config: DiagnosticConfig,
) -> DiagnosticTemplate:
    return DiagnosticTemplate(concept_id=concept_id, config=config)
