"""Concrete executors — state machines for each cognitive algebra.

Each executor implements ``CognitiveExecutor`` as a literal transition
system.  Every call to ``step()`` advances state by exactly one atomic
operation (evaluate one condition, follow one branch, etc.), producing
one trace event per operation.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from studyplan.cci.executor import CognitiveExecutor, Transition
from studyplan.domain_reasoning.concept_types.classification_concept import (
    ClassificationTemplate,
)
from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
from studyplan.domain_reasoning.process.diagnostic import DiagnosticTemplate
from studyplan.domain_reasoning.process.evaluation import EvaluationTemplate


def _tr(
    action: str,
    rationale: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serializable transition dict (shortcut)."""
    return asdict(Transition(action=action, rationale=rationale, evidence=evidence or {}))


class ClassificationExecutor(CognitiveExecutor):
    """Decision-tree walker — one condition per step.

    State machine::

        evaluate → matched_condition → evaluate | commit → terminate

    Each ``step()`` evaluates exactly one branch condition:

    * **match + leaf branch** → commit result (``done=True``)
    * **match + child branches** → descend into children (same phase)
    * **no match + more branches** → advance to next branch
    * **no match + no more branches** → no match (``done=True``)
    """

    def __init__(self, template: ClassificationTemplate) -> None:
        self._template = template

    @property
    def concept_id(self) -> str:
        return self._template.concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ctx: dict[str, float] = {}
        for k, v in inputs.items():
            if isinstance(v, (int, float)):
                ctx[str(k)] = float(v)

        tree = self._template._tree
        return {
            "phase": "evaluate",
            "branches": tree.branches,
            "branch_index": 0,
            "question": tree.question,
            "path": [],
            "ctx": ctx,
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["done"]:
            return {"next_state": state}

        if state["phase"] != "evaluate":
            return {"next_state": state}

        # No more branches to try → no match
        if state["branch_index"] >= len(state["branches"]):
            state["done"] = True
            return {
                "next_state": state,
                "transition": _tr(
                    action="no_match",
                    rationale="No branch condition matched",
                    evidence={"branches_tried": len(state["branches"])},
                ),
            }

        branch = state["branches"][state["branch_index"]]
        cond_matches = _condition_matches(branch.condition, state["ctx"])

        if not cond_matches:
            # Try next branch
            state["branch_index"] += 1
            return {
                "next_state": state,
                "transition": _tr(
                    action="evaluate_condition",
                    rationale=f"{branch.condition} was False",
                    evidence={"condition": branch.condition, "matched": False},
                ),
            }

        # Condition matched
        step_entry: dict[str, Any] = {
            "step_id": "decision",
            "matched_condition": branch.condition,
            "question": state.get("question"),
        }

        if branch.result is not None:
            # Leaf → commit
            step_entry["value"] = branch.result
            state["path"].append(step_entry)
            state["done"] = True
            state["result"] = branch.result
            return {
                "next_state": state,
                "transition": _tr(
                    action="commit_result",
                    rationale=f"{branch.condition} → {branch.result}",
                    evidence={"condition": branch.condition, "result": branch.result},
                ),
            }

        if branch.children:
            # Internal node → descend
            step_entry["value"] = None
            state["path"].append(step_entry)
            state["branches"] = branch.children
            state["branch_index"] = 0
            state["question"] = None
            return {
                "next_state": state,
                "transition": _tr(
                    action="descend",
                    rationale=f"{branch.condition} → enter sub-tree",
                    evidence={"condition": branch.condition},
                ),
            }

        # Branch matched but has no result and no children
        state["done"] = True
        return {
            "next_state": state,
            "transition": _tr(
                action="no_match",
                rationale="Matched branch has no result or children",
                evidence={"condition": branch.condition},
            ),
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("done") or state.get("result") is None:
            return None
        return {
            "concept_id": self._template.concept_id,
            "result": state["result"],
            "inputs": dict(state.get("ctx", {})),
            "is_nan": False,
            "steps": list(state.get("path", [])),
            "classification_path": [
                p.get("matched_condition", "") or p.get("question", "") for p in state.get("path", [])
            ],
        }


# =========================================================================
# DiagnosticExecutor
# =========================================================================


class DiagnosticExecutor(CognitiveExecutor):
    """Bayesian belief updating — one observation per step.

    State machine::

        initialize → bayesian_update → … → commit_diagnosis → terminate

    Each ``step()`` incorporates exactly one observation via Bayes' rule.
    After all observations are processed, the executor commits to the
    MAP hypothesis.
    """

    def __init__(self, template: DiagnosticTemplate) -> None:
        self._template = template

    @property
    def concept_id(self) -> str:
        return self._template.concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        observations = DiagnosticTemplate._extract_observations(inputs)
        posteriors = {h.id: h.prior for h in self._template.config.hypotheses}
        return {
            "phase": "observation",
            "observations": observations,
            "obs_index": 0,
            "hypotheses": list(self._template.config.hypotheses),
            "posteriors": posteriors,
            "evidence_trail": [],
            "entropy": 0.0,
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["done"]:
            return {"next_state": state}

        # --- Phase: commit ---
        if state["phase"] == "commit":
            posteriors = state["posteriors"]
            map_hid = max(posteriors, key=lambda k: posteriors[k]) if posteriors else None
            map_prob = posteriors[map_hid] if map_hid else 0.0
            entropy = self._template._compute_entropy(posteriors)

            state["done"] = True
            state["result"] = {
                "primary_diagnosis": map_hid,
                "confidence": map_prob,
                "posterior_distribution": dict(posteriors),
                "entropy": entropy,
                "evidence_count": len(state["evidence_trail"]),
            }

            rec = self._template._recommend_investigations(posteriors, entropy)
            return {
                "next_state": state,
                "transition": _tr(
                    action="commit_diagnosis",
                    rationale=f"MAP hypothesis: {map_hid} (p={map_prob:.3f})",
                    evidence={
                        "map_hypothesis": map_hid,
                        "map_probability": map_prob,
                        "entropy": entropy,
                        "recommended_investigations": rec,
                    },
                ),
            }

        # --- Phase: observation ---
        obs_idx = state["obs_index"]
        if obs_idx >= len(state["observations"]):
            state["phase"] = "commit"
            return {
                "next_state": state,
                "transition": _tr(
                    action="observations_exhausted",
                    rationale=f"Processed all {len(state['evidence_trail'])} observations",
                    evidence={"observation_count": len(state["evidence_trail"])},
                ),
            }

        obs = state["observations"][obs_idx]
        fid = obs["feature"]
        val = obs["value"]
        posteriors = state["posteriors"]
        hypotheses = state["hypotheses"]

        likes: dict[str, float] = {}
        for h in hypotheses:
            likes[h.id] = self._template._compute_likelihood(h.id, fid, val)

        unnorm = {h.id: likes[h.id] * posteriors.get(h.id, 0.0) for h in hypotheses}
        norm = sum(unnorm.values())
        if norm > 0:
            for hid in unnorm:
                posteriors[hid] = unnorm[hid] / norm

        entropy = self._template._compute_entropy(posteriors)
        state["entropy"] = entropy

        state["evidence_trail"].append(
            {
                "step": obs_idx,
                "feature": fid,
                "value": val,
                "likelihoods": likes,
                "posteriors": dict(posteriors),
            }
        )
        state["obs_index"] = obs_idx + 1

        return {
            "next_state": state,
            "transition": _tr(
                action="bayesian_update",
                rationale=f"Observed {fid}={val} → entropy={entropy:.3f}",
                evidence={
                    "feature": fid,
                    "value": val,
                    "likelihoods": likes,
                    "entropy": entropy,
                },
            ),
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("done"):
            return None
        return {
            "concept_id": self._template.concept_id,
            "result": state["result"],
            "inputs": {},
            "is_nan": state["result"] is None,
            "steps": list(state.get("evidence_trail", [])),
            "posterior_distribution": dict(state.get("posteriors", {})),
            "map_hypothesis": (state.get("result") or {}).get("primary_diagnosis"),
            "map_probability": (state.get("result") or {}).get("confidence", 0.0),
            "entropy": state.get("entropy", 0.0),
        }


# =========================================================================
# EvaluationExecutor
# =========================================================================


class EvaluationExecutor(CognitiveExecutor):
    """Multi-criteria scoring — one criterion per step.

    State machine::

        initialize → score_criterion → … → resolve_judgment → terminate

    Each ``step()`` scores all candidates on exactly one criterion and
    accumulates the weighted result.  After all criteria are processed,
    the executor ranks candidates and commits a judgment.
    """

    def __init__(self, template: EvaluationTemplate) -> None:
        self._template = template

    @property
    def concept_id(self) -> str:
        return self._template.concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        config = self._template.config
        return {
            "phase": "scoring",
            "criteria": list(config.criteria),
            "criterion_index": 0,
            "candidates": list(config.candidates),
            "total_weight": sum(c.weight for c in config.criteria) or 1.0,
            "accumulated": dict.fromkeys(config.candidates, 0.0),
            "contributions": [],
            "inputs": dict(inputs),
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["done"]:
            return {"next_state": state}

        # --- Phase: resolve ---
        if state["phase"] == "resolve":
            acc = state["accumulated"]
            ranked = sorted(acc.items(), key=lambda x: -x[1])
            judgment = ranked[0][0] if ranked else None
            top_score = ranked[0][1] if ranked else 0.0
            runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
            confidence = top_score - runner_up_score

            state["done"] = True
            state["result"] = {
                "judgment": judgment,
                "confidence": round(confidence, 4),
            }

            return {
                "next_state": state,
                "transition": _tr(
                    action="resolve_judgment",
                    rationale=f"{judgment} ({top_score:.3f}) vs runner-up ({runner_up_score:.3f})",
                    evidence={
                        "judgment": judgment,
                        "top_score": top_score,
                        "confidence": round(confidence, 4),
                        "ranked": ranked,
                    },
                ),
            }

        # --- Phase: scoring ---
        crit_idx = state["criterion_index"]
        if crit_idx >= len(state["criteria"]):
            state["phase"] = "resolve"
            return {
                "next_state": state,
                "transition": _tr(
                    action="criteria_exhausted",
                    rationale=f"Scored all {len(state['criteria'])} criteria",
                    evidence={"criterion_count": len(state["criteria"])},
                ),
            }

        criterion = state["criteria"][crit_idx]
        inputs = state["inputs"]
        candidates = state["candidates"]
        acc = state["accumulated"]

        criterion_scores = inputs.get(criterion.id, {})
        norm_weight = criterion.weight / state["total_weight"]

        for candidate in candidates:
            raw = float(criterion_scores.get(candidate, 0.0))
            lo, hi = criterion.score_range
            clamped = max(lo, min(hi, raw))
            acc[candidate] += norm_weight * clamped

        if criterion_scores:
            for candidate, raw in criterion_scores.items():
                if candidate in candidates:
                    state["contributions"].append(
                        {
                            "criterion": criterion.id,
                            "candidate": candidate,
                            "weight": norm_weight,
                            "score": float(raw),
                            "weighted_contribution": round(norm_weight * float(raw), 4),
                        }
                    )

        state["criterion_index"] = crit_idx + 1

        return {
            "next_state": state,
            "transition": _tr(
                action="score_criterion",
                rationale=f"Scored '{criterion.id}' (weight={criterion.weight})",
                evidence={
                    "criterion": criterion.id,
                    "weight": criterion.weight,
                    "scores": {c: acc[c] for c in candidates},
                },
            ),
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("done"):
            return None
        acc = state.get("accumulated", {})
        ranked = sorted(acc.items(), key=lambda x: -x[1])
        return {
            "concept_id": self._template.concept_id,
            "judgment": (state.get("result") or {}).get("judgment"),
            "scores": dict(acc),
            "ranked": ranked,
            "confidence": (state.get("result") or {}).get("confidence", 0.0),
            "justification": [],
            "contributions": state.get("contributions", []),
            "is_nan": False,
        }


def _condition_matches(
    condition: str | bool,
    ctx: dict[str, float],
) -> bool:
    """Evaluate a single branch condition against the context."""
    if isinstance(condition, bool):
        return condition
    try:
        return bool(_eval_rule_expression(condition, ctx))
    except (ValueError, NameError):
        return False
