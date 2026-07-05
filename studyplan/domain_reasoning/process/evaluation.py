"""Evaluation process template — multi-criteria weighted judgement.

An evaluation process assesses candidates against weighted criteria to
produce a judgement (top-ranked candidate), confidence (score gap), and
justification (which criteria drove the decision).  It corresponds to
Class V (Evaluation / Argumentation) in the cognitive hierarchy.
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
class EvaluationCriterion:
    """One dimension on which candidates are scored."""

    id: str
    label: str = ""
    weight: float = 1.0
    score_range: tuple[float, float] = (0.0, 1.0)


@dataclass
class EvaluationConfig:
    """Configuration for a ``type="evaluation"`` process declaration."""

    criteria: list[EvaluationCriterion] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    ideal: dict[str, float] | None = None
    output: str = "judgment"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class EvaluationTemplate(ProcessTemplate):
    """Weighted multi-criteria judgment template.

    Usage::

        config = EvaluationConfig(
            criteria=[
                EvaluationCriterion(id="financial", weight=0.4),
                EvaluationCriterion(id="governance", weight=0.3),
            ],
            candidates=["going_concern", "break_up"],
        )
        template = EvaluationTemplate("audit.gc", config)
        result = template.solve({
            "financial": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.6, "break_up": 0.4},
        })
    """

    def __init__(self, concept_id: str, config: EvaluationConfig) -> None:
        self.concept_id = concept_id
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Score all candidates and return a judgment.

        Args:
            inputs: ``{criterion_id: {candidate: score, ...}, ...}``

        Returns:
            Dict with judgment, scores, confidence gap, justification,
            entropy, and per-criterion contributions.
        """
        total_weight = sum(c.weight for c in self.config.criteria) or 1.0

        # Aggregate weighted scores per candidate
        scores: dict[str, float] = dict.fromkeys(self.config.candidates, 0.0)
        contributions: list[dict[str, Any]] = []

        for criterion in self.config.criteria:
            criterion_scores = inputs.get(criterion.id, {})
            norm_weight = criterion.weight / total_weight

            for candidate in self.config.candidates:
                raw = float(criterion_scores.get(candidate, 0.0))
                # Clamp to score range
                lo, hi = criterion.score_range
                clamped = max(lo, min(hi, raw))
                scores[candidate] += norm_weight * clamped

            # Contribution detail for justification
            if criterion_scores and any(c in criterion_scores for c in self.config.candidates):
                for candidate, raw in criterion_scores.items():
                    if candidate in self.config.candidates:
                        contributions.append(
                            {
                                "criterion": criterion.id,
                                "candidate": candidate,
                                "weight": norm_weight,
                                "score": float(raw),
                                "weighted_contribution": round(norm_weight * float(raw), 4),
                            }
                        )

        # Rank candidates
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        judgment = ranked[0][0] if ranked else None
        top_score = ranked[0][1] if ranked else 0.0
        runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = top_score - runner_up_score

        # Justification: criteria where top candidate outscored runner-up
        justification = self._build_justification(
            inputs,
            ranked,
            total_weight,
        )

        # Entropy of the normalized score distribution
        entropy = self._score_entropy(scores)

        return {
            "concept_id": self.concept_id,
            "judgment": judgment,
            "scores": scores,
            "ranked": ranked,
            "confidence": round(confidence, 4),
            "justification": justification,
            "contributions": contributions,
            "entropy": round(entropy, 4),
            "result": {
                self.config.output: judgment,
                "confidence": round(confidence, 4),
            },
            "inputs": dict(inputs),
            "is_nan": False,
        }

    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Check learner-provided steps against the ground-truth judgment."""
        if not learner_steps or not truth:
            return []
        truth_judgment = truth.get("judgment") or (truth.get("result") or {}).get(
            truth.get("result", {}).get(self.config.output, "")
        )

        results: list[dict[str, Any]] = []
        for step in learner_steps:
            step_val = step.get("judgment") or step.get("value")
            match = False
            if isinstance(step_val, str) and isinstance(truth_judgment, str):
                match = step_val.strip().lower() == truth_judgment.strip().lower()
            results.append(
                {
                    "step_id": step.get("step_id", ""),
                    "expected": truth_judgment,
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
        """Tag errors in the learner's reasoning."""
        tags: list[str] = []
        if not learner_steps or not truth:
            return tags

        truth_judgment = truth.get("judgment")

        # Check final judgment
        final_judgment: str | None = None
        considered_criteria: set[str] = set()
        learner_scores: dict[str, dict[str, float]] = {}

        for step in learner_steps:
            sv = step.get("judgment") or step.get("value")
            if isinstance(sv, str):
                final_judgment = sv.strip().lower()

            cid = step.get("criterion")
            if cid:
                considered_criteria.add(cid)
                cand = step.get("candidate")
                sc = step.get("score")
                if cand is not None and sc is not None:
                    learner_scores.setdefault(cid, {})[cand] = float(sc)

        truth_lower = truth_judgment.strip().lower() if isinstance(truth_judgment, str) else None

        if truth_lower and final_judgment and final_judgment != truth_lower:
            tags.append("wrong_judgment")

        # Missing criteria
        declared_ids = {c.id for c in self.config.criteria}
        missing = declared_ids - considered_criteria
        if missing:
            tags.append("missing_criterion")

        # Score misalignment per criterion (compare raw scores, not weighted)
        truth_inputs = truth.get("inputs", {})
        for criterion in self.config.criteria:
            lscores = learner_scores.get(criterion.id, {})
            if not lscores:
                continue
            # Truth's raw scores for this criterion from the original inputs
            truth_raw = truth_inputs.get(criterion.id, {})
            for candidate in self.config.candidates:
                lv = lscores.get(candidate)
                tv = truth_raw.get(candidate)
                if lv is not None and tv is not None and abs(lv - tv) > 0.3:
                    if lv > tv:
                        tags.append("over_weighted_criterion")
                    else:
                        tags.append("under_weighted_criterion")

        return tags

    def expected_information_gain(
        self,
        scores: dict[str, float],
        criterion_id: str,
        outcome_vectors: list[dict[str, float]] | None = None,
        outcome_probs: list[float] | None = None,
    ) -> float:
        """Expected Information Gain (in bits) for learning a criterion's scores.

        Models discovering how each candidate scores on *criterion_id*.
        Each outcome vector maps ``{candidate: raw_score}`` for that criterion.

        Args:
            scores: Current aggregated scores ``{candidate: score}``.
            criterion_id: Which criterion's scores to simulate.
            outcome_vectors: Possible raw-score vectors for this criterion.
                Defaults to three scenarios: all-high, mixed, all-low relative
                to the candidate count.
            outcome_probs: Prior probability of each outcome.
                Defaults to uniform.

        Returns:
            Expected information gain in bits (>= 0).
        """
        if not scores or len(scores) < 2:
            return 0.0

        # Build default outcome vectors if none provided
        if outcome_vectors is None:
            candidates = list(scores.keys())
            outcome_vectors = [
                dict.fromkeys(candidates, 0.9),  # all high
                dict.fromkeys(candidates, 0.5),  # all mid
                dict.fromkeys(candidates, 0.1),  # all low
                {candidates[0]: 0.9, candidates[1]: 0.1},  # first wins
                {candidates[0]: 0.1, candidates[1]: 0.9},  # second wins
            ]

        n = len(outcome_vectors)
        if outcome_probs is None:
            outcome_probs = [1.0 / n] * n
        elif len(outcome_probs) != n:
            outcome_probs = [1.0 / n] * n

        current_entropy = self._score_entropy(scores)

        # Find the criterion's normalised weight
        norm_weight = 0.0
        total_w = sum(c.weight for c in self.config.criteria) or 1.0
        for c in self.config.criteria:
            if c.id == criterion_id:
                norm_weight = c.weight / total_w
                break

        if norm_weight <= 0.0:
            return 0.0

        # Base = aggregate scores MINUS this criterion's contribution
        # (we don't have this in solve() output, so we assume scores are
        #  the current aggregate from all *other* criteria for simulation)
        expected_posterior_entropy = 0.0
        for vector, prob in zip(outcome_vectors, outcome_probs, strict=True):
            simulated: dict[str, float] = {}
            for cand, base in scores.items():
                raw = vector.get(cand, 0.5)
                simulated[cand] = base * (1.0 - norm_weight) + norm_weight * raw
            # Normalize to probability distribution for entropy
            sim_total = sum(simulated.values()) or 1.0
            simulated_dist = {k: v / sim_total for k, v in simulated.items()}
            expected_posterior_entropy += prob * self._score_entropy(simulated_dist)

        return max(0.0, round(current_entropy - expected_posterior_entropy, 4))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_justification(
        self,
        inputs: dict[str, Any],
        ranked: list[tuple[str, float]],
        total_weight: float,
    ) -> list[dict[str, Any]]:
        """Identify which criteria most influenced the top choice."""
        if len(ranked) < 2:
            return []
        top_candidate = ranked[0][0]
        runner_up = ranked[1][0]

        drivers: list[dict[str, Any]] = []
        for criterion in self.config.criteria:
            c_scores = inputs.get(criterion.id, {})
            top_raw = float(c_scores.get(top_candidate, 0.0))
            runner_raw = float(c_scores.get(runner_up, 0.0))
            diff = top_raw - runner_raw
            if abs(diff) > 0.01:
                norm_weight = criterion.weight / total_weight
                drivers.append(
                    {
                        "criterion": criterion.id,
                        "label": criterion.label,
                        "top_score": round(top_raw, 3),
                        "runner_up_score": round(runner_raw, 3),
                        "difference": round(diff, 3),
                        "weighted_impact": round(norm_weight * diff, 4),
                    }
                )

        drivers.sort(key=lambda x: -abs(x["weighted_impact"]))
        return drivers[:5]

    @staticmethod
    def _score_entropy(scores: dict[str, float]) -> float:
        """Shannon entropy of the score distribution (treated as probabilities)."""
        total = sum(scores.values()) or 1.0
        h_val = 0.0
        for v in scores.values():
            p = v / total
            if p > 0.0:
                h_val -= p * math.log2(p)
        return h_val
