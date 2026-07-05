#!/usr/bin/env python3
"""Algebra Observatory — scientific instrument for algebraic structure inference.

The observatory takes a cognitive execution *trace* (not an executor) and
produces falsifiable hypotheses about its algebra::

    Topology      — the shape of the state space (tree, graph, …)
    Dynamics      — how state changes (traverse, propagate, …)
    Conserved Qty — what stays invariant across every transition

Every hypothesis is a **confidence distribution** over known labels plus
``Unknown``.  This makes the observatory a *scientific instrument* — it
can be wrong, and it knows when it doesn't know.

Usage
─────

    >>> from studyplan.cci import CognitiveRuntime
    >>> from studyplan.frontends.csp import CspExecutor, CspTemplate, CspVariable, CspConstraint
    >>> obs = AlgebraObservatory()
    >>> trace = CognitiveRuntime().execute(
    ...     CspExecutor(CspTemplate("test", variables=[...], constraints=[...])), {})
    >>> profile = obs.profile_trace(trace)
    >>> profile.topology.best
    'constraint_graph'
    >>> profile.topology.confidence
    0.87
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from studyplan.cci import CognitiveRuntime, ExecutionTrace


# ═══════════════════════════════════════════════════════════════════
# Confidence distribution
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ConfidenceDistribution:
    """Probability distribution over discrete labels.

    ``values`` maps each label to a probability (sum ≈ 1.0).
    ``Unknown`` is a first-class label — the instrument explicitly
    reports when no known category fits with sufficient confidence.
    """

    values: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.values:
            total = sum(self.values.values())
            if abs(total - 1.0) > 0.001:
                self.values = {k: v / total for k, v in self.values.items()}

    @property
    def best(self) -> str:
        """Label with highest probability."""
        if not self.values:
            return "Unknown"
        return max(self.values, key=self.values.get)

    @property
    def confidence(self) -> float:
        """Probability of the best label."""
        if not self.values:
            return 0.0
        return self.values[self.best]

    @property
    def entropy(self) -> float:
        """Shannon entropy — measures uncertainty across the distribution."""
        h = 0.0
        for p in self.values.values():
            if p > 0:
                h -= p * math.log2(p)
        return h

    def top_k(self, k: int = 3) -> list[tuple[str, float]]:
        """Return the top-*k* (label, probability) pairs sorted descending."""
        sorted_items = sorted(self.values.items(), key=lambda x: -x[1])
        return sorted_items[:k]

    def __str__(self) -> str:
        lines = []
        for label, prob in sorted(self.values.items(), key=lambda x: -x[1]):
            bar = "█" * int(prob * 20)
            lines.append(f"  {label:30s} {prob:.3f} {bar}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# Trace profile
# ═══════════════════════════════════════════════════════════════════

KNOWN_TOPOLOGIES = [
    "tree_traversal",
    "probability_distribution",
    "score_vector",
    "constraint_graph",
    "expanding_graph",
    "support_network",
]

KNOWN_DYNAMICS = [
    "traverse",
    "reweight",
    "aggregate",
    "propagate",
    "expand",
    "support_retract",
]

KNOWN_CONSERVED = [
    "path_uniqueness",
    "probability_mass",
    "weight_budget",
    "constraint_closure",
    "parent_uniqueness",
    "justification_closure",
]


@dataclass
class TraceProfile:
    """Fully-observed analysis of one execution trace."""

    # ── Identity ──────────────────────────────────────────────────
    name: str = "?"

    # ── Raw observations ──────────────────────────────────────────
    step_count: int = 0
    unique_actions: list[str] = field(default_factory=list)
    action_sequence: list[str] = field(default_factory=list)

    # ── State features ────────────────────────────────────────────
    state_keys: set[str] = field(default_factory=set)
    state_cardinality: int = 0
    max_nesting_depth: int = 0
    key_persistence: float = 0.0
    has_growing_keys: bool = False
    has_shrinking_keys: bool = False
    has_value_mutation: bool = False
    has_structural_mutation: bool = False
    has_inside_growth: bool = False
    has_inside_shrink: bool = False
    is_traversal: bool = False
    value_hints: list[str] = field(default_factory=list)
    has_normalized_sum: bool = False
    has_non_negative_values: bool = False

    # ── Derived from transition metadata ──────────────────────────
    has_classification_path: bool = False
    has_posterior: bool = False
    has_score_vector: bool = False
    has_constraint_vars: bool = False
    has_expanding_nodes: bool = False
    has_justification_network: bool = False
    has_status_tracking: bool = False

    # ── Trace coherence ────────────────────────────────────────────
    coherence: float = 1.0

    # ── Hypotheses (confidence distributions) ─────────────────────
    topology: ConfidenceDistribution = field(default_factory=ConfidenceDistribution)
    dynamics: ConfidenceDistribution = field(default_factory=ConfidenceDistribution)
    conserved: ConfidenceDistribution = field(default_factory=ConfidenceDistribution)


# ═══════════════════════════════════════════════════════════════════
# Feature extraction
# ═══════════════════════════════════════════════════════════════════


def _state_from(payload: dict, key: str) -> dict:
    s = payload.get(key, {})
    return s if isinstance(s, dict) else {}


def _collect_all_states(trace: ExecutionTrace) -> list[dict]:
    states = []
    for ev in trace.events:
        if ev.type == "initialize":
            states.append(_state_from(ev.payload, "state"))
        elif ev.type == "step":
            states.append(_state_from(ev.payload, "new_state"))
        elif ev.type == "terminate":
            states.append(_state_from(ev.payload, "final_state"))
    return states


def _all_transitions(trace: ExecutionTrace) -> list[dict]:
    """Collect all step transition dicts from a trace."""
    transitions = []
    for ev in trace.events:
        if ev.type == "step":
            t = ev.payload.get("transition", {})
            if isinstance(t, dict):
                transitions.append(t)
    return transitions


def _nesting_depth(obj: Any, depth: int = 0) -> int:
    if isinstance(obj, dict):
        if not obj:
            return depth + 1
        return max(_nesting_depth(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return depth + 1
        return max(_nesting_depth(v, depth + 1) for v in obj)
    return depth


def _all_keys(obj: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            full = f"{prefix}.{k}" if prefix else str(k)
            keys.add(full)
            keys |= _all_keys(v, full)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            keys |= _all_keys(v, f"{prefix}[{i}]")
    return keys


def _detect_traversal_pattern(all_states: list[dict]) -> bool:
    branch_changes = 0
    has_branch_idx = False
    has_path = False
    path_grows = False

    for s in all_states:
        if "branch_index" in s:
            has_branch_idx = True
        if "path" in s and isinstance(s["path"], list):
            has_path = True

    if len(all_states) >= 2 and has_branch_idx:
        indices = [s.get("branch_index") for s in all_states if "branch_index" in s]
        if len(indices) >= 2 and any(i != indices[0] for i in indices[1:]):
            branch_changes += 1

    if has_path and len(all_states) >= 2:
        path_lens = [len(s.get("path", [])) for s in all_states if isinstance(s.get("path"), list)]
        if len(path_lens) >= 2 and path_lens[-1] > path_lens[0]:
            path_grows = True

    return branch_changes > 0 or (has_path and path_grows)


def _classify_value_structure(state: dict) -> list[str]:
    hints: list[str] = []
    for key, value in state.items():
        if isinstance(value, dict):
            keys = list(value.keys())
            vals = list(value.values())

            if all(isinstance(v, (int, float)) for v in vals):
                total = sum(vals)
                if abs(total - 1.0) < 0.01 and total > 0:
                    hints.append(f"{key}:distribution")
                elif len(keys) >= 2:
                    hints.append(f"{key}:score_vector")
                else:
                    hints.append(f"{key}:scalar_map")

            elif all(isinstance(v, dict) for v in vals):
                sub_keys: set[str] = set()
                for v in vals:
                    sub_keys |= v.keys()
                depth = _nesting_depth(value)
                if depth >= 4:
                    hints.append(f"{key}:deep_tree")
                elif "status" in sub_keys:
                    hints.append(f"{key}:node_graph")
                elif "domain" in sub_keys:
                    hints.append(f"{key}:variable_domain")
                else:
                    hints.append(f"{key}:nested_dict")

            else:
                hints.append(f"{key}:mixed_dict")

        elif isinstance(value, list):
            if not value:
                hints.append(f"{key}:empty_list")
            elif isinstance(value[0], dict):
                item_keys: set[str] = set()
                for item in value:
                    item_keys |= item.keys()
                if "domain" in item_keys:
                    hints.append(f"{key}:variable_list")
                elif "children" in item_keys:
                    hints.append(f"{key}:node_list")
                elif "id" in item_keys or "label" in item_keys:
                    hints.append(f"{key}:named_item_list")
                else:
                    hints.append(f"{key}:dict_list")
            else:
                hints.append(f"{key}:scalar_list")

        elif isinstance(value, str):
            hints.append(f"{key}:string")

        elif isinstance(value, (int, float)):
            hints.append(f"{key}:scalar")

    return hints


def _extract_transition_metadata(transitions: list[dict]) -> dict[str, Any]:
    """Extract signals from transition metadata across all steps.

    Types are inferred from action names because executors do not set
    a ``type`` field in their transition dicts.  The inference is a
    heuristic — it can false-positive but penalties will be mild.
    """
    meta: dict[str, Any] = {
        "has_classification_path": False,
        "has_posterior": False,
        "has_score_vector": False,
        "has_constraint_vars": False,
        "has_expanding_nodes": False,
        "has_justification_network": False,
        "has_status_tracking": False,
        "has_backtrack": False,
        "has_domain_ops": False,
        "has_nodes_key": False,
        "has_focus_key": False,
        "max_depth": 0,
    }

    for t in transitions:
        action = t.get("action", "")

        # Infer type from action names (executors don't set ``type`` field)
        if action in ("descend", "ascend", "commit_result", "evaluate_condition", "no_match"):
            meta["has_classification_path"] = True
        if action in ("bayesian_update", "commit_diagnosis", "observations_exhausted"):
            meta["has_posterior"] = True
        if action in ("score_criterion", "resolve_judgment", "criteria_exhausted"):
            meta["has_score_vector"] = True
        if action in (
            "propagate",
            "select_variable",
            "assign_value",
            "domain_wipeout",
            "backtrack",
            "commit_solution",
            "all_vars_assigned",
            "no_values_remaining",
            "search_exhausted",
        ):
            meta["has_domain_ops"] = True
        if action in ("expand_goal", "activate_goal"):
            meta["has_expanding_nodes"] = True
        if action in ("belief_derived", "belief_lost", "belief_retracted"):
            meta["has_justification_network"] = True
        if action in (
            "check_justification",
            "belief_network_stable",
            "evaluation_quiescent",
            "commit_belief_set",
            "retract_skipped",
        ):
            meta["has_status_tracking"] = True

        meta["has_backtrack"] = meta["has_backtrack"] or (action == "backtrack")
        meta["has_nodes_key"] = meta["has_nodes_key"] or "node_id" in t.get("evidence", {})
        meta["has_focus_key"] = meta["has_focus_key"] or action in ("descend", "ascend", "sibling_pending")

        if action in ("commit_solution", "commit_plan", "commit_belief_set"):
            meta["commit_action"] = action

    return meta


def _extract_state_features(states: list[dict]) -> dict[str, Any]:
    if not states:
        return {}

    flat_keys_across: list[set[str]] = [set(s.keys()) for s in states]

    every_key = set.union(*flat_keys_across) if flat_keys_across else set()
    persistent_keys = set.intersection(*flat_keys_across) if flat_keys_across else set()

    key_persistence = len(persistent_keys) / max(len(every_key), 1)

    seen_so_far: set[str] = set()
    ever_shrunk = False
    has_grown = False
    for i, ks in enumerate(flat_keys_across):
        if i == 0:
            seen_so_far = set(ks)
            continue
        newly_seen = ks - seen_so_far
        newly_gone = seen_so_far - ks
        if newly_seen:
            has_grown = True
        if newly_gone:
            ever_shrunk = True
        seen_so_far |= ks

    has_value_mut = False
    if len(states) >= 2 and persistent_keys:
        for key in persistent_keys:
            vals = [s.get(key) for s in states]
            if any(v != vals[0] for v in vals[1:] if v is not None):
                has_value_mut = True
                break

    has_inside_growth = False
    has_inside_shrink = False
    for key in persistent_keys:
        sizes = []
        for s in states:
            v = s.get(key)
            if isinstance(v, dict):
                sizes.append(len(v))
            elif isinstance(v, list):
                sizes.append(len(v))
        if len(sizes) >= 2:
            if sizes[-1] > sizes[0]:
                has_inside_growth = True
            if sizes[-1] < sizes[0]:
                has_inside_shrink = True

    first_state = states[0]
    card = len(first_state)
    ndepth = max(_nesting_depth(s) for s in states)

    value_hints = _classify_value_structure(first_state)

    has_norm = False
    has_nonneg = False
    for s in states:
        for v in s.values():
            if isinstance(v, dict) and all(isinstance(x, (int, float)) for x in v.values()):
                vals = list(v.values())
                total = sum(vals)
                if abs(total - 1.0) < 0.01 and total > 0:
                    has_norm = True
                if all(x >= 0 for x in vals):
                    has_nonneg = True

    is_traversal = _detect_traversal_pattern(states)

    return {
        "state_keys": every_key,
        "state_cardinality": card,
        "max_nesting_depth": ndepth,
        "key_persistence": key_persistence,
        "has_growing_keys": has_grown,
        "has_shrinking_keys": ever_shrunk,
        "has_value_mutation": has_value_mut,
        "has_structural_mutation": ever_shrunk or any(len(ks) != len(flat_keys_across[0]) for ks in flat_keys_across),
        "has_inside_growth": has_inside_growth,
        "has_inside_shrink": has_inside_shrink,
        "is_traversal": is_traversal,
        "value_hints": value_hints,
        "has_normalized_sum": has_norm,
        "has_non_negative_values": has_nonneg,
    }


def _extract_action_features(trace: ExecutionTrace) -> dict[str, Any]:
    actions: list[str] = []
    for ev in trace.events:
        if ev.type == "step":
            trans = ev.payload.get("transition", {})
            if isinstance(trans, dict):
                action = trans.get("action", "") or trans.get("type", "") or ""
                if action:  # Skip empty/absent transitions
                    actions.append(action)
    counts = Counter(actions)
    return {
        "unique_actions": sorted(set(actions)),
        "action_sequence": actions,
        "action_frequencies": dict(counts),
        "step_count": len(actions),
    }


# ═══════════════════════════════════════════════════════════════════
# Trace coherence (anomaly detection for mixed traces)
# ═══════════════════════════════════════════════════════════════════

_ACTION_FAMILIES: dict[str, set[str]] = {
    "traversal": {"evaluate_condition", "descend", "ascend", "commit_result", "no_match"},
    "reweight": {"bayesian_update", "commit_diagnosis", "observations_exhausted"},
    "aggregate": {"score_criterion", "resolve_judgment", "criteria_exhausted"},
    "propagate": {
        "select_variable",
        "assign_value",
        "propagate",
        "backtrack",
        "commit_solution",
        "domain_wipeout",
        "all_vars_assigned",
        "no_values_remaining",
        "search_exhausted",
    },
    "expand": {
        "activate_goal",
        "expand_goal",
        "complete_leaf",
        "descend",
        "ascend",
        "commit_plan",
        "sibling_pending",
        "root_satisfied",
        "no_pending_child",
    },
    "support": {
        "check_justification",
        "belief_derived",
        "belief_lost",
        "belief_retracted",
        "evaluation_quiescent",
        "commit_belief_set",
        "belief_network_stable",
        "retract_skipped",
    },
    "dispatch": {
        "projection",
        "traversal",
        "collect_constraints",
        "project",
        "filter",
        "map",
        "reduce",
        "collect",
        "query",
        "select",
        "join",
        "aggregate",
    },
}


def _compute_coherence(actions: list[str]) -> float:
    """Measure action coherence across algebra families.

    Only **non-shared** actions (belonging to exactly one family)
    contribute.  Shared actions (e.g. ``descend`` in both
    ``traversal`` and ``expand``) are ignored — they are vocabulary
    that real algebras legitimately share.

    Coherence = fraction of non-shared actions that belong to the
    majority family.  Pure traces score 1.0.  Evenly mixed traces
    score ~0.5.  Three-way mixes score ~0.33.
    """
    if not actions:
        return 1.0

    pure_family_counts: Counter = Counter()

    for action in actions:
        families_for: list[str] = []
        for family, members in _ACTION_FAMILIES.items():
            if action in members:
                families_for.append(family)
        if len(families_for) == 1:
            pure_family_counts[families_for[0]] += 1

    total_pure = sum(pure_family_counts.values())
    if total_pure == 0:
        return 0.5  # All actions shared or novel — moderate coherence

    max_family = max(pure_family_counts.values())
    return max_family / total_pure


# ═══════════════════════════════════════════════════════════════════
# Confidence-based inference
# ═══════════════════════════════════════════════════════════════════


def _softmax(scores: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    """Convert raw scores to probabilities via softmax."""
    if not scores:
        return {}
    values = list(scores.values())
    max_s = max(values)
    exps = {k: math.exp((v - max_s) / temperature) for k, v in scores.items()}
    total = sum(exps.values())
    if total == 0:
        return {k: 1.0 / len(scores) for k in scores}
    return {k: v / total for k, v in exps.items()}


def _to_distribution(
    scores: dict[str, float],
    unknown_threshold: float = 0.35,
    coherence: float = 1.0,
) -> ConfidenceDistribution:
    """Convert raw scores to a confidence distribution with Unknown detection.

    Parameters
    ----------
    scores:
        Raw (unbounded) scores for each known label.
    unknown_threshold:
        If the max raw score is below this, ``Unknown`` is boosted above all
        known labels.
    coherence:
        Trace coherence in [0, 1] from ``_compute_coherence``.  Low coherence
        attenuates the entire distribution, routing probability mass to
        ``Unknown``.  This makes the instrument report "I don't know" when
        the trace is anomalous (e.g. mixed from two executors).
    """
    if not scores:
        return ConfidenceDistribution({"Unknown": 1.0})

    max_score = max(scores.values())

    # Step 1: if no known label has sufficient evidence, add Unknown
    if max_score < unknown_threshold:
        scores["Unknown"] = unknown_threshold * 1.5

    # Step 2: compute softmax distribution
    probs = _softmax(scores, temperature=0.5)

    # Step 3: attenuate by coherence — route probability mass to Unknown
    # Squared coherence creates a sharper transition:
    #   coherence 1.0 → no change
    #   coherence 0.7 → 0.49 mass stays on known, 0.51 on Unknown
    #   coherence 0.5 → 0.25 known, 0.75 Unknown
    #   coherence 0.0 → all Unknown
    if coherence < 1.0:
        attenuation = coherence * coherence
        for label in list(probs.keys()):
            probs[label] = probs[label] * attenuation
        probs["Unknown"] = 1.0 - attenuation

    return ConfidenceDistribution(probs)


# ── Topology scoring ──────────────────────────────────────────────


def _score_tree_traversal(features: dict[str, Any], meta: dict[str, Any], actions: list[str]) -> float:
    """Score for tree / cursor-traversal topology."""
    score = 0.0

    if features.get("is_traversal"):
        score += 3.0

    if meta.get("has_classification_path"):
        score += 3.0
        path_len = meta.get("classification_path_len", 0)
        if path_len >= 2:
            score += 2.0

    hints = features.get("value_hints", [])
    if any("deep_tree" in h for h in hints):
        score += 2.0
    if any("node_list" in h for h in hints):
        score += 1.0

    if "evaluate_condition" in actions:
        score += 2.0
    if "commit_result" in actions:
        score += 2.0
    if "descend" in actions or "ascend" in actions:
        score += 1.5

    if features.get("has_structural_mutation") is False:
        score += 0.5

    return score


def _score_probability_distribution(features: dict[str, Any], meta: dict[str, Any], actions: list[str]) -> float:
    """Score for probability-distribution topology."""
    score = 0.0

    if features.get("has_normalized_sum"):
        score += 4.0
    if features.get("has_non_negative_values"):
        score += 1.0

    if meta.get("has_posterior"):
        score += 4.0

    hints = features.get("value_hints", [])
    if any("distribution" in h for h in hints):
        score += 3.0

    if "bayesian_update" in actions:
        score += 3.0

    return score


def _score_score_vector(features: dict[str, Any], meta: dict[str, Any], actions: list[str]) -> float:
    """Score for score-vector topology."""
    score = 0.0

    if meta.get("has_score_vector"):
        score += 4.0

    hints = features.get("value_hints", [])
    if any("score_vector" in h for h in hints):
        score += 3.0

    if "score_criterion" in actions:
        score += 3.0

    return score


def _score_constraint_graph(features: dict[str, Any], meta: dict[str, Any], actions: list[str]) -> float:
    """Score for constraint-graph topology."""
    score = 0.0

    hints = features.get("value_hints", [])
    if any("variable_list" in h for h in hints):
        score += 3.0
    if any("variable_domain" in h for h in hints):
        score += 3.0

    if meta.get("has_domain_ops"):
        score += 4.0
    if meta.get("has_backtrack"):
        score += 3.0

    if "propagate" in actions:
        score += 3.0
    if "backtrack" in actions:
        score += 2.0

    state_keys = features.get("state_keys", set())
    if "constraints" in state_keys or "variables" in state_keys:
        score += 2.0
    if "assignment_stack" in state_keys:
        score += 2.0

    return score


def _score_expanding_graph(features: dict[str, Any], meta: dict[str, Any], actions: list[str]) -> float:
    """Score for expanding-graph topology."""
    score = 0.0

    if features.get("has_inside_growth") and not features.get("has_inside_shrink"):
        score += 2.0

    if meta.get("has_expanding_nodes"):
        score += 3.0
    if meta.get("has_focus_key"):
        score += 2.0
    if meta.get("has_nodes_key"):
        score += 1.0

    if "expand_goal" in actions:
        score += 3.0
    if "descend" in actions:
        score += 1.0

    state_keys = features.get("state_keys", set())
    if "nodes" in state_keys:
        score += 2.0
    if "focus" in state_keys:
        score += 1.5

    return score


def _score_support_network(features: dict[str, Any], meta: dict[str, Any], actions: list[str]) -> float:
    """Score for support-network (justification) topology."""
    score = 0.0

    if meta.get("has_justification_network"):
        score += 4.0
    if meta.get("has_status_tracking"):
        score += 2.0

    if "belief_derived" in actions:
        score += 3.0
    if "belief_lost" in actions:
        score += 2.0
    if "belief_retracted" in actions:
        score += 2.0

    if features.get("has_inside_shrink") and not features.get("has_inside_growth"):
        score += 1.0

    hints = features.get("value_hints", [])
    if any("node_graph" in h for h in hints):
        score += 2.0

    state_keys = features.get("state_keys", set())
    if "justifications" in state_keys:
        score += 3.0
    if "pending_queue" in state_keys:
        score += 2.0

    return score


def _score_linear_plan(features: dict[str, Any], meta: dict[str, Any], actions: list[str]) -> float:
    """Score for linear-plan topology: sequential queries over stable state.

    Pattern: perfectly stable keys, NO value mutation (read-only),
    NO structural mutation, NO inside growth, NO inside shrink.

    This is the signature of provenance query execution (projection,
    traversal, collect_constraints) applied as a plan over an
    unchanging ViewState.  The ViewState is read-only — values don't
    change, containers don't grow or shrink.
    """
    kp = features.get("key_persistence", 0)
    no_value = not features.get("has_value_mutation", True)
    no_structure = not features.get("has_structural_mutation", True)
    no_inside_grow = not features.get("has_inside_growth", False)
    no_inside_shrink = not features.get("has_inside_shrink", False)

    # Query verbs are the distinguishing signal — no existing algebra
    # uses these action names.  Without them, there's no evidence of
    # query-plan execution.
    query_verbs = {
        "projection",
        "traversal",
        "collect_constraints",
        "project",
        "filter",
        "map",
        "reduce",
        "collect",
        "query",
        "select",
        "join",
        "aggregate",
    }
    action_set = set(actions)
    has_query_verbs = bool(action_set & query_verbs)
    has_multi_verb = len(action_set & query_verbs) >= 2

    # Gate: no query verbs → not a query plan.  Even with stable keys
    # and no mutation, this is just a bare computation.
    if not has_query_verbs:
        return 0.0

    score = 0.0

    # Core pattern: read-only provenance signature.
    # All 6 existing algebras mutate values, so they never match.
    is_read_only = kp >= 0.95 and no_value and no_structure and no_inside_grow and no_inside_shrink
    if is_read_only:
        score += 8.0

    # Stable key sets amplify the read-only signal
    if kp >= 0.95:
        score += 1.0
    if not features.get("has_growing_keys", True):
        score += 1.0
    if not features.get("has_shrinking_keys", True):
        score += 1.0

    # Query verbs are the primary signal
    score += 3.0
    if has_multi_verb:
        score += 2.0  # Multiple query types = stronger signal

    # Strong penalty for any executor-specific pattern
    if meta.get("has_classification_path") or meta.get("has_posterior"):
        score -= 4.0
    if meta.get("has_score_vector"):
        score -= 4.0
    if meta.get("has_domain_ops") or meta.get("has_backtrack"):
        score -= 4.0
    if meta.get("has_expanding_nodes") or meta.get("has_focus_key"):
        score -= 4.0
    if meta.get("has_justification_network"):
        score -= 4.0

    return max(0.0, score)


def _infer_topology(
    features: dict[str, Any], meta: dict[str, Any], actions: list[str], coherence: float = 1.0
) -> ConfidenceDistribution:
    """Compute confidence distribution over topology classes."""
    scores: dict[str, float] = {}

    scores["tree_traversal"] = _score_tree_traversal(features, meta, actions)
    scores["probability_distribution"] = _score_probability_distribution(features, meta, actions)
    scores["score_vector"] = _score_score_vector(features, meta, actions)
    scores["constraint_graph"] = _score_constraint_graph(features, meta, actions)
    scores["expanding_graph"] = _score_expanding_graph(features, meta, actions)
    scores["support_network"] = _score_support_network(features, meta, actions)
    scores["linear_plan"] = _score_linear_plan(features, meta, actions)

    return _to_distribution(scores, unknown_threshold=0.35, coherence=coherence)


# ── Dynamics scoring ──────────────────────────────────────────────


def _score_traverse_dynamics(actions: list[str], meta: dict[str, Any], features: dict[str, Any]) -> float:
    """Score for traversal dynamics: cursor moving step by step."""
    score = 0.0

    if meta.get("has_classification_path"):
        score += 3.0

    if "evaluate_condition" in actions:
        score += 3.0

    if features.get("is_traversal"):
        score += 2.0

    descend_ascend = sum(1 for a in actions if a in ("descend", "ascend", "sibling_pending"))
    score += descend_ascend * 0.5

    return score


def _score_reweight_dynamics(actions: list[str], meta: dict[str, Any], features: dict[str, Any]) -> float:
    """Score for reweight dynamics: probability mass redistribution."""
    score = 0.0

    if features.get("has_normalized_sum"):
        score += 3.0

    if meta.get("has_posterior"):
        score += 3.0

    if "bayesian_update" in actions:
        score += 4.0

    return score


def _score_aggregate_dynamics(actions: list[str], meta: dict[str, Any], features: dict[str, Any]) -> float:
    """Score for aggregate dynamics: combining scores into judgment."""
    score = 0.0

    if meta.get("has_score_vector"):
        score += 3.0

    if "score_criterion" in actions:
        score += 4.0

    return score


def _score_propagate_dynamics(actions: list[str], meta: dict[str, Any], features: dict[str, Any]) -> float:
    """Score for propagate dynamics: constraint propagation through graph."""
    score = 0.0

    if "propagate" in actions:
        score += 4.0
    if "backtrack" in actions:
        score += 2.0
    if "assign_value" in actions:
        score += 2.0
    if "select_variable" in actions:
        score += 2.0

    if meta.get("has_domain_ops"):
        score += 3.0

    propagate_count = sum(1 for a in actions if a == "propagate")
    if propagate_count >= 2:
        score += 2.0

    return score


def _score_expand_dynamics(actions: list[str], meta: dict[str, Any], features: dict[str, Any]) -> float:
    """Score for expand dynamics: graph growth at frontier."""
    score = 0.0

    if "expand_goal" in actions:
        score += 4.0
    if "activate_goal" in actions:
        score += 2.0
    if "complete_leaf" in actions:
        score += 1.5

    expand_count = sum(1 for a in actions if a == "expand_goal")
    if expand_count >= 2:
        score += 2.0

    descend_count = sum(1 for a in actions if a == "descend")
    score += min(descend_count * 0.5, 2.0)

    return score


def _score_support_retract_dynamics(actions: list[str], meta: dict[str, Any], features: dict[str, Any]) -> float:
    """Score for support/retract dynamics: justification activation/deactivation."""
    score = 0.0

    if "belief_derived" in actions:
        score += 4.0
    if "belief_lost" in actions:
        score += 3.0
    if "belief_retracted" in actions:
        score += 3.0
    if "check_justification" in actions:
        score += 2.0
    if "evaluation_quiescent" in actions:
        score += 1.0

    belief_count = sum(1 for a in actions if a in ("belief_derived", "belief_lost", "belief_retracted"))
    if belief_count >= 2:
        score += 2.0

    return score


def _score_dispatch_dynamics(actions: list[str], meta: dict[str, Any], features: dict[str, Any]) -> float:
    """Score for dispatch dynamics: select-and-apply different primitives.

    Pattern: each step dispatches a different query primitive
    (projection, traversal, collect) against a stable ViewState.
    The executor selects which operation to apply but the underlying
    data does not grow or shrink structurally.

    Coherence attenuation is handled by ``_to_distribution``, not here.
    """
    query_verbs = {
        "projection",
        "traversal",
        "collect_constraints",
        "project",
        "filter",
        "map",
        "reduce",
        "collect",
        "query",
        "select",
        "join",
        "aggregate",
    }
    action_set = set(actions)
    query_hits = action_set & query_verbs

    # Gate: no query verbs → no dispatch evidence
    if not query_hits:
        return 0.0

    score = 3.0
    if len(query_hits) >= 2:
        score += 2.0  # Multiple dispatch types = stronger signal

    # Stable state with value changes supports dispatch
    if features.get("key_persistence", 0) >= 0.95:
        score += 1.0
    if features.get("has_value_mutation", False):
        score += 1.0
    if not features.get("has_structural_mutation", True):
        score += 1.0

    # Penalty if existing dynamics match
    if meta.get("has_classification_path"):
        score -= 3.0
    if meta.get("has_posterior"):
        score -= 3.0
    if meta.get("has_domain_ops"):
        score -= 3.0
    if meta.get("has_justification_network"):
        score -= 3.0

    return max(0.0, score)


def _infer_dynamics(
    features: dict[str, Any], meta: dict[str, Any], actions: list[str], coherence: float = 1.0
) -> ConfidenceDistribution:
    """Compute confidence distribution over dynamics classes."""
    scores: dict[str, float] = {}

    scores["traverse"] = _score_traverse_dynamics(actions, meta, features)
    scores["reweight"] = _score_reweight_dynamics(actions, meta, features)
    scores["aggregate"] = _score_aggregate_dynamics(actions, meta, features)
    scores["propagate"] = _score_propagate_dynamics(actions, meta, features)
    scores["expand"] = _score_expand_dynamics(actions, meta, features)
    scores["support_retract"] = _score_support_retract_dynamics(actions, meta, features)
    scores["dispatch"] = _score_dispatch_dynamics(actions, meta, features)

    return _to_distribution(scores, unknown_threshold=0.35, coherence=coherence)


# ── Conserved quantity scoring ────────────────────────────────────


def _score_path_uniqueness(features: dict[str, Any], meta: dict[str, Any], topology: str | None) -> float:
    """Score for path_uniqueness conserved quantity."""
    score = 0.0

    if topology == "tree_traversal":
        score += 4.0
    if meta.get("has_classification_path"):
        score += 3.0
    if features.get("is_traversal"):
        score += 2.0

    return score


def _score_probability_mass(features: dict[str, Any], meta: dict[str, Any], topology: str | None) -> float:
    """Score for probability_mass conserved quantity."""
    score = 0.0

    if topology == "probability_distribution":
        score += 4.0
    if features.get("has_normalized_sum"):
        score += 4.0
    if meta.get("has_posterior"):
        score += 3.0

    return score


def _score_weight_budget(features: dict[str, Any], meta: dict[str, Any], topology: str | None) -> float:
    """Score for weight_budget conserved quantity."""
    score = 0.0

    if topology == "score_vector":
        score += 4.0
    if meta.get("has_score_vector"):
        score += 3.0

    return score


def _score_constraint_closure(features: dict[str, Any], meta: dict[str, Any], topology: str | None) -> float:
    """Score for constraint_closure conserved quantity."""
    score = 0.0

    if topology == "constraint_graph":
        score += 4.0
    if meta.get("has_domain_ops"):
        score += 3.0
    if "propagate" in meta.get("commit_action", "") or meta.get("has_backtrack"):
        score += 2.0

    return score


def _score_parent_uniqueness(features: dict[str, Any], meta: dict[str, Any], topology: str | None) -> float:
    """Score for parent_uniqueness conserved quantity."""
    score = 0.0

    if topology == "expanding_graph":
        score += 4.0
    if features.get("has_inside_growth") and not features.get("has_inside_shrink"):
        score += 2.0
    if meta.get("has_expanding_nodes"):
        score += 2.0

    return score


def _score_justification_closure(features: dict[str, Any], meta: dict[str, Any], topology: str | None) -> float:
    """Score for justification_closure conserved quantity."""
    score = 0.0

    if topology == "support_network":
        score += 4.0
    if meta.get("has_justification_network"):
        score += 3.0
    if meta.get("has_status_tracking"):
        score += 2.0

    return score


def _score_plan_fidelity(features: dict[str, Any], meta: dict[str, Any], topology: str | None) -> float:
    """Score for plan_fidelity conserved quantity.

    Pattern: executing the same query plan against the same ViewState
    always produces the same results. Captured by perfect key persistence,
    no structural mutation, and linear index advancement.

    This is the algebraic dual of projection/traversal/collection:
    the ViewState is invariant under query execution.
    """
    score = 0.0

    if topology == "linear_plan":
        score += 4.0

    kp = features.get("key_persistence", 0)
    if kp >= 0.95:
        score += 2.0
    if not features.get("has_structural_mutation", True):
        score += 2.0
    if not features.get("has_growing_keys", True) and not features.get("has_shrinking_keys", True):
        score += 2.0

    if features.get("has_value_mutation", False) and features.get("has_inside_growth", False):
        score += 2.0

    # Penalty for backtracking — violates plan fidelity
    if meta.get("has_backtrack", False):
        score -= 3.0

    return max(0.0, score)


def _infer_conserved(
    features: dict[str, Any], meta: dict[str, Any], topology_dist: ConfidenceDistribution, coherence: float = 1.0
) -> ConfidenceDistribution:
    """Compute confidence distribution over conserved quantities.

    Uses the topology distribution as a strong prior — each conserved
    quantity is tightly coupled to its corresponding topology.
    """
    best_topology = topology_dist.best
    top_conf = topology_dist.confidence

    scores: dict[str, float] = {}

    scores["path_uniqueness"] = _score_path_uniqueness(features, meta, best_topology)
    scores["probability_mass"] = _score_probability_mass(features, meta, best_topology)
    scores["weight_budget"] = _score_weight_budget(features, meta, best_topology)
    scores["constraint_closure"] = _score_constraint_closure(features, meta, best_topology)
    scores["parent_uniqueness"] = _score_parent_uniqueness(features, meta, best_topology)
    scores["justification_closure"] = _score_justification_closure(features, meta, best_topology)
    scores["plan_fidelity"] = _score_plan_fidelity(features, meta, best_topology)

    # Amplify the top topology's conserved quantity by confidence
    topo_to_conserved = {
        "tree_traversal": "path_uniqueness",
        "probability_distribution": "probability_mass",
        "score_vector": "weight_budget",
        "constraint_graph": "constraint_closure",
        "expanding_graph": "parent_uniqueness",
        "support_network": "justification_closure",
        "linear_plan": "plan_fidelity",
    }
    expected = topo_to_conserved.get(best_topology)
    if expected and top_conf > 0.4:
        scores[expected] = scores.get(expected, 0) + top_conf * 3.0

    return _to_distribution(scores, unknown_threshold=0.35, coherence=coherence)


# ═══════════════════════════════════════════════════════════════════
# Principal API
# ═══════════════════════════════════════════════════════════════════


class AlgebraObservatory:
    """Scientific instrument that infers algebraic structure from traces.

    Usage
    ─────

        obs = AlgebraObservatory()
        profile = obs.profile_trace(trace)

        profile.topology.best          # "constraint_graph"
        profile.topology.confidence    # 0.87
        profile.topology.top_k(3)      # [("constraint_graph", 0.87), ...]
        profile.dynamics.best          # "propagate"
        profile.conserved.best         # "constraint_closure"
    """

    def profile_trace(self, trace: ExecutionTrace, name: str = "?") -> TraceProfile:
        """Analyse a trace and produce hypotheses with confidence distributions.

        This is the primary API — it operates on traces only, without
        access to the executor class or template.  The observatory is
        *blind* to provenance.
        """
        states = _collect_all_states(trace)
        state_features = _extract_state_features(states)
        action_features = _extract_action_features(trace)
        transitions = _all_transitions(trace)
        meta = _extract_transition_metadata(transitions)

        actions = action_features.get("action_sequence", [])
        coherence = _compute_coherence(actions)

        topology_dist = _infer_topology(state_features, meta, actions, coherence=coherence)
        dynamics_dist = _infer_dynamics(state_features, meta, actions, coherence=coherence)
        conserved_dist = _infer_conserved(state_features, meta, topology_dist, coherence=coherence)

        return TraceProfile(
            name=name,
            step_count=action_features.get("step_count", 0),
            unique_actions=action_features.get("unique_actions", []),
            action_sequence=actions,
            state_keys=state_features.get("state_keys", set()),
            state_cardinality=state_features.get("state_cardinality", 0),
            max_nesting_depth=state_features.get("max_nesting_depth", 0),
            key_persistence=state_features.get("key_persistence", 0.0),
            has_growing_keys=state_features.get("has_growing_keys", False),
            has_shrinking_keys=state_features.get("has_shrinking_keys", False),
            has_value_mutation=state_features.get("has_value_mutation", False),
            has_structural_mutation=state_features.get("has_structural_mutation", False),
            has_inside_growth=state_features.get("has_inside_growth", False),
            has_inside_shrink=state_features.get("has_inside_shrink", False),
            is_traversal=state_features.get("is_traversal", False),
            value_hints=state_features.get("value_hints", []),
            has_normalized_sum=state_features.get("has_normalized_sum", False),
            has_non_negative_values=state_features.get("has_non_negative_values", False),
            has_classification_path=meta.get("has_classification_path", False),
            has_posterior=meta.get("has_posterior", False),
            has_score_vector=meta.get("has_score_vector", False),
            has_constraint_vars=meta.get("has_constraint_vars", False),
            has_expanding_nodes=meta.get("has_expanding_nodes", False),
            has_justification_network=meta.get("has_justification_network", False),
            has_status_tracking=meta.get("has_status_tracking", False),
            coherence=coherence,
            topology=topology_dist,
            dynamics=dynamics_dist,
            conserved=conserved_dist,
        )

    def profile_executor(
        self,
        name: str,
        executor_cls: type,
        template_factory: callable,
        inputs: dict[str, Any] | None = None,
    ) -> TraceProfile:
        """Convenience: instantiate, run, and profile an executor in one call.

        Equivalent to::

            runtime = CognitiveRuntime()
            executor = executor_cls(template_factory())
            trace = runtime.execute(executor, inputs or {})
            obs.profile_trace(trace, name=name)
        """
        runtime = CognitiveRuntime()
        executor = executor_cls(template_factory())
        trace = runtime.execute(executor, inputs or {})
        return self.profile_trace(trace, name=name)


# ═══════════════════════════════════════════════════════════════════
# Pretty-printing
# ═══════════════════════════════════════════════════════════════════


def _fmt_dist(dist: ConfidenceDistribution, label: str) -> str:
    lines = [f"  {label}:"]
    for lab, prob in sorted(dist.values.items(), key=lambda x: -x[1]):
        bar = "█" * int(prob * 25)
        marker = " ←" if lab == dist.best else ""
        lines.append(f"    {lab:30s} {prob:.3f} {bar}{marker}")
    return "\n".join(lines)


def print_profile(profile: TraceProfile) -> None:
    """Print a detailed profile showing confidence distributions."""
    print(f"\n{'─' * 60}")
    print(f"  Algebra:  {profile.name}")
    print(f"{'─' * 60}")
    print(f"  Steps:    {profile.step_count}")
    print(f"  Actions:  {profile.unique_actions}")
    print(f"  Sequence: {profile.action_sequence}")
    print()

    # Confidence distributions
    print(_fmt_dist(profile.topology, "Topology"))
    print()
    print(_fmt_dist(profile.dynamics, "Dynamics"))
    print()
    print(_fmt_dist(profile.conserved, "Conserved"))

    # Details
    print(f"\n  State: {profile.state_cardinality} top-level keys, depth {profile.max_nesting_depth}")
    print(f"  Key persistence: {profile.key_persistence:.0%}")
    print(f"  Value hints:     {profile.value_hints[:5]}...")

    if profile.conserved.entropy < 1.0:
        print(f"  🎯 Strong conserved quantity signal (entropy={profile.conserved.entropy:.2f})")
    else:
        print(f"  ⚠  Weak conserved quantity signal (entropy={profile.conserved.entropy:.2f})")


def print_summary_table(profiles: list[TraceProfile]) -> None:
    """Print a compact comparison table across all algebras.

    Shows the best hypothesis and its confidence for each dimension.
    """
    headers = ["Algebra", "Steps", "Topology", "T_conf", "Dynamics", "D_conf", "Conserved", "C_conf"]
    col_widths = [max(len(p.name) for p in profiles), 5, 18, 6, 14, 6, 22, 6]
    col_widths[0] = max(col_widths[0], len(headers[0]))
    sep = " │ "

    def row(cells: list[str]) -> str:
        padded = []
        for cell, w in zip(cells, col_widths):
            padded.append(cell.ljust(w))
        return sep.join(padded)

    header_line = row(headers)
    rule = "─" * len(header_line)
    print(f"\n  {rule}")
    print(f"  {header_line}")
    print(f"  {rule}")
    for p in profiles:
        cells = [
            p.name,
            str(p.step_count),
            p.topology.best,
            f"{p.topology.confidence:.2f}",
            p.dynamics.best,
            f"{p.dynamics.confidence:.2f}",
            p.conserved.best,
            f"{p.conserved.confidence:.2f}",
        ]
        print(f"  {row(cells)}")
    print(f"  {rule}")


# ═══════════════════════════════════════════════════════════════════
# Demo / self-test
# ═══════════════════════════════════════════════════════════════════


def _make_classification_template():
    from studyplan.domain_reasoning.concept_types.classification_concept import (
        Branch,
        ClassificationConfig,
        ClassificationNode,
        ClassificationTemplate,
    )

    root = ClassificationNode(
        question="Assess",
        branches=[
            Branch(
                condition="score > 0",
                children=[
                    Branch(
                        condition="score > 30",
                        children=[
                            Branch(condition="score > 50", result="high_risk"),
                            Branch(condition="True", result="medium"),
                        ],
                    ),
                    Branch(condition="True", result="low"),
                ],
            ),
            Branch(condition="True", result="invalid"),
        ],
    )
    return ClassificationTemplate("test.class", ClassificationConfig(tree=root, output_slot="result"))


def _make_diagnosis_template():
    from studyplan.domain_reasoning.process.diagnostic import (
        DiagnosticConfig,
        DiagnosticTemplate,
        ProcessHypothesis,
        ProcessFeature,
    )

    return DiagnosticTemplate(
        "test.diag",
        DiagnosticConfig(
            hypotheses=[
                ProcessHypothesis(id="hyp_a", prior=0.5, label="A"),
                ProcessHypothesis(id="hyp_b", prior=0.5, label="B"),
            ],
            features=[ProcessFeature(id="feat_x", type="categorical", values=["pos", "neg"])],
            likelihoods={
                "hyp_a": {"feat_x": {"pos": 0.9, "neg": 0.2}},
                "hyp_b": {"feat_x": {"pos": 0.3, "neg": 0.8}},
            },
        ),
    )


def _make_evaluation_template():
    from studyplan.domain_reasoning.process.evaluation import EvaluationConfig, EvaluationCriterion, EvaluationTemplate

    return EvaluationTemplate(
        "test.eval",
        EvaluationConfig(
            criteria=[
                EvaluationCriterion(id="criterion_a", weight=0.5, score_range=(0, 10)),
                EvaluationCriterion(id="criterion_b", weight=0.5, score_range=(0, 10)),
            ],
            candidates=["x", "y"],
        ),
    )


def _make_csp_template():
    from studyplan.frontends.csp import CspConstraint, CspTemplate, CspVariable

    return CspTemplate(
        "test.csp",
        variables=[
            CspVariable(id="A", domain=frozenset({1, 2, 3})),
            CspVariable(id="B", domain=frozenset({1, 2, 3})),
            CspVariable(id="C", domain=frozenset({1, 2, 3})),
        ],
        constraints=[
            CspConstraint(type="all_different", variables=["A", "B", "C"]),
        ],
    )


def _make_gg_template():
    from studyplan.frontends.growing_graph import ExpansionRule, GrowingGraphTemplate

    return GrowingGraphTemplate(
        "test.gg",
        initial_goal_type="root",
        expansion_rules=[
            ExpansionRule("root", [("leaf_a", "Leaf A"), ("leaf_b", "Leaf B")]),
        ],
    )


def _make_just_template():
    from studyplan.frontends.justification import Justification, JustificationBelief, JustificationTemplate

    return JustificationTemplate(
        "test.just",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise", is_premise=True),
            JustificationBelief(id="B", label="Derived"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["A"]),
        ],
    )


def _run_demo():
    from studyplan.frontends.finance import (
        ClassificationExecutor,
        DiagnosticExecutor,
        EvaluationExecutor,
    )
    from studyplan.frontends.csp import CspExecutor
    from studyplan.frontends.growing_graph import GrowingGraphExecutor
    from studyplan.frontends.justification import JustificationExecutor

    executors = [
        ("Classification", ClassificationExecutor, _make_classification_template, {"score": 80}),
        ("Diagnosis", DiagnosticExecutor, _make_diagnosis_template, {"feat_x": "pos"}),
        (
            "Evaluation",
            EvaluationExecutor,
            _make_evaluation_template,
            {
                "criterion_a": {"x": 8, "y": 3},
                "criterion_b": {"x": 4, "y": 7},
            },
        ),
        ("CSP", CspExecutor, _make_csp_template, {}),
        ("GrowingGraph", GrowingGraphExecutor, _make_gg_template, {}),
        ("Justification", JustificationExecutor, _make_just_template, {}),
    ]

    obs = AlgebraObservatory()
    profiles: list[TraceProfile] = []
    for name, cls, factory, inputs in executors:
        profile = obs.profile_executor(name, cls, factory, inputs)
        profiles.append(profile)
        print_profile(profile)

    print_summary_table(profiles)


if __name__ == "__main__":
    _run_demo()
