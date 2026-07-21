#!/usr/bin/env python3
"""Algebra Experiment Harness — falsify the observatory's hypotheses.

The observatory is a *scientific instrument*.  It makes claims:
    "This trace has tree topology (p=0.97)"
    "This trace has propagation dynamics (p=0.99)"

These claims can be **wrong**.  That is the point.

Each experiment tests a different mode of failure:

    Experiment 1 — Blind classification
        Hide the executor identity.  Can the observatory still classify?
        Measures: accuracy, confusion, confidence calibration.

    Experiment 2 — Noise robustness
        Remove 10/20/40/60% of events from traces.
        Can the observatory still identify the algebra?
        Produces: robustness curve.

    Experiment 3 — Adversarial mixing
        Interleave two different executors into one trace.
        Does the observatory say "Unknown" or hallucinate?
        A scientific instrument must know when it doesn't know.

    Experiment 4 — Zero-shot novelty
        Give the observatory a BFS (Breadth-First Search) trace,
        which is NOT a known algebra.
        Which known algebra is it *closest* to?
        The observatory becomes a metric space.

Usage::

    python tools/algebra_experiments.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from studyplan.cci import CognitiveRuntime, ExecutionTrace

from tools.algebra_observatory import AlgebraObservatory, TraceProfile

random.seed(42)


# ═══════════════════════════════════════════════════════════════════
# Registry: known executors and their templates
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


def _make_bfs_template() -> dict:
    return {
        "adjacency": {
            "A": ["B", "C"],
            "B": ["A", "D", "E"],
            "C": ["A", "F"],
            "D": ["B"],
            "E": ["B", "F"],
            "F": ["C", "E"],
        },
        "start": "A",
    }


EXECUTOR_DEFS: list[tuple[str, type, Callable, dict]] = []


def _register_all():
    from studyplan.frontends.finance import ClassificationExecutor, DiagnosticExecutor, EvaluationExecutor
    from studyplan.frontends.csp import CspExecutor
    from studyplan.frontends.growing_graph import GrowingGraphExecutor
    from studyplan.frontends.justification import JustificationExecutor
    from studyplan.frontends.bfs_executor import BfsExecutor

    EXECUTOR_DEFS.extend(
        [
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
            ("BFS", BfsExecutor, _make_bfs_template, {}),
        ]
    )


EXPECTED = {
    "Classification": {"topology": "tree_traversal", "dynamics": "traverse", "conserved": "path_uniqueness"},
    "Diagnosis": {"topology": "probability_distribution", "dynamics": "reweight", "conserved": "probability_mass"},
    "Evaluation": {"topology": "score_vector", "dynamics": "aggregate", "conserved": "weight_budget"},
    "CSP": {"topology": "constraint_graph", "dynamics": "propagate", "conserved": "constraint_closure"},
    "GrowingGraph": {"topology": "expanding_graph", "dynamics": "expand", "conserved": "parent_uniqueness"},
    "Justification": {
        "topology": "support_network",
        "dynamics": "support_retract",
        "conserved": "justification_closure",
    },
}


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def generate_trace(executor_cls: type, template_factory: Callable, inputs: dict[str, Any]) -> ExecutionTrace:
    """Run an executor and return its trace, discarding the profile."""
    runtime = CognitiveRuntime()
    executor = executor_cls(template_factory())
    return runtime.execute(executor, inputs or {})


def remove_random_events(trace: ExecutionTrace, removal_rate: float) -> ExecutionTrace:
    """Return a new trace with *removal_rate* fraction of events removed.

    The initialize and terminate events are *never* removed — only step
    events are candidates for degradation.
    """
    step_indices = [i for i, ev in enumerate(trace.events) if ev.type == "step"]
    remove_count = max(0, int(len(step_indices) * removal_rate))
    to_remove: set[int] = set(random.sample(step_indices, remove_count))

    new = ExecutionTrace()
    for i, ev in enumerate(trace.events):
        if i not in to_remove:
            new.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new


def interleave_traces(trace_a: ExecutionTrace, trace_b: ExecutionTrace, pattern: str = "alternate") -> ExecutionTrace:
    """Interleave events from two traces into one.

    ``pattern="alternate"``
        Take one event from A, one from B, alternating.
        If one trace runs out, the remaining events from the other
        are appended.

    Always starts with A's initialize and ends with whichever trace's
    terminate comes last.
    """
    events_a = trace_a.events
    events_b = trace_b.events
    merged: list[tuple[int, Any]] = []  # (seq, event)

    if pattern == "alternate":
        i, j = 0, 0
        turn = 0
        while i < len(events_a) and j < len(events_b):
            if turn % 2 == 0:
                merged.append((len(merged), events_a[i]))
                i += 1
            else:
                merged.append((len(merged), events_b[j]))
                j += 1
            turn += 1
        while i < len(events_a):
            merged.append((len(merged), events_a[i]))
            i += 1
        while j < len(events_b):
            merged.append((len(merged), events_b[j]))
            j += 1

    merged.sort(key=lambda x: x[0])

    new = ExecutionTrace()
    for _, ev in merged:
        new.record(
            ev.type,
            dict(ev.payload),
            transition_id=ev.transition_id,
            state_hash_before=ev.state_hash_before,
            state_hash_after=ev.state_hash_after,
        )
    return new


# ═══════════════════════════════════════════════════════════════════
# Channel separation mutation functions
# ═══════════════════════════════════════════════════════════════════


def _copy_trace(trace: ExecutionTrace) -> ExecutionTrace:
    """Deep-copy a trace by reconstructing it from original events."""
    new = ExecutionTrace()
    for ev in trace.events:
        new.record(
            ev.type,
            dict(ev.payload),
            transition_id=ev.transition_id,
            state_hash_before=ev.state_hash_before,
            state_hash_after=ev.state_hash_after,
        )
    return new


CHANNEL_DEFINITIONS: dict[str, str] = {
    "full": "Original trace (all channels)",
    "actions_only": "Only transition.action and event sequence",
    "states_only": "Only new_state (keys + values) and state hashes",
    "state_hashes_only": "Only state_hash_before / state_hash_after",
    "metadata_only": "transition.evidence, rationale, type (no action)",
    "timing_only": "Only timestamps (inter-event intervals)",
    "transition_ids_only": "Only transition_id labels",
}


def channel_mutate(trace: ExecutionTrace, channel: str) -> ExecutionTrace:
    """Return a copy of *trace* with only *channel* preserved."""
    new = ExecutionTrace()
    for ev in trace.events:
        payload: dict[str, Any] = {}

        if channel == "full":
            payload = dict(ev.payload)

        elif channel == "actions_only":
            # Keep only action name and event order
            trans = ev.payload.get("transition", {})
            if isinstance(trans, dict):
                action = trans.get("action", "") or trans.get("type", "") or ""
                payload["transition"] = {"action": action}

        elif channel == "states_only":
            # Keep new_state and state hashes; strip transition entirely
            if "new_state" in ev.payload:
                payload["new_state"] = ev.payload["new_state"]
            # Preserve hashes via the trace event fields

        elif channel == "state_hashes_only":
            pass  # Will rely on state_hash_before/after fields below

        elif channel == "metadata_only":
            # Keep everything in transition EXCEPT action name
            trans = ev.payload.get("transition", {})
            if isinstance(trans, dict):
                stripped = {k: v for k, v in trans.items() if k != "action"}
                payload["transition"] = stripped
            if "new_state" in ev.payload:
                payload["new_state"] = ev.payload["new_state"]

        elif channel == "timing_only":
            # Strip everything; the only signal is event ordering
            pass

        elif channel == "transition_ids_only":
            pass  # Will rely on transition_id field below

        else:
            payload = dict(ev.payload)

        new.record(
            ev.type,
            payload,
            transition_id=ev.transition_id if channel != "transition_ids_only" else "",
            state_hash_before=(ev.state_hash_before if channel in ("full", "states_only", "state_hashes_only") else ""),
            state_hash_after=(ev.state_hash_after if channel in ("full", "states_only", "state_hashes_only") else ""),
        )
    return new


@dataclass
class ExperimentResult:
    name: str
    details: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    matrix: Any = None


# ═══════════════════════════════════════════════════════════════════
# Experiment 1: Blind Classification
# ═══════════════════════════════════════════════════════════════════


def experiment_blind_classification(obs: AlgebraObservatory) -> ExperimentResult:
    """Hide executor identity.  Can the observatory still classify?"""
    result = ExperimentResult("Blind Classification")
    correct = {"topology": 0, "dynamics": 0, "conserved": 0}
    total = 0

    for name, cls, factory, inputs in EXECUTOR_DEFS:
        if name == "BFS":
            continue  # zero-shot is experiment 4
        trace = generate_trace(cls, factory, inputs)
        # Blind: trace only, no name
        profile = obs.profile_trace(trace, name="?")
        exp = EXPECTED[name]

        t_ok = profile.topology.best == exp["topology"]
        d_ok = profile.dynamics.best == exp["dynamics"]
        c_ok = profile.conserved.best == exp["conserved"]

        if t_ok:
            correct["topology"] += 1
        if d_ok:
            correct["dynamics"] += 1
        if c_ok:
            correct["conserved"] += 1
        total += 1

        entry = {
            "executor": name,
            "steps": profile.step_count,
            "topology": (profile.topology.best, profile.topology.confidence, t_ok),
            "dynamics": (profile.dynamics.best, profile.dynamics.confidence, d_ok),
            "conserved": (profile.conserved.best, profile.conserved.confidence, c_ok),
        }
        result.details.append(entry)

    acc_topo = correct["topology"] / total * 100
    acc_dyn = correct["dynamics"] / total * 100
    acc_cons = correct["conserved"] / total * 100
    result.summary = (
        f"Accuracy: topology={acc_topo:.0f}%  dynamics={acc_dyn:.0f}%  conserved={acc_cons:.0f}%  (n={total})"
    )
    return result


# ═══════════════════════════════════════════════════════════════════
# Experiment 2: Noise Robustness
# ═══════════════════════════════════════════════════════════════════

NOISE_RATES = [0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 0.95]


def experiment_noise_robustness(obs: AlgebraObservatory) -> ExperimentResult:
    """Remove events at various rates.  Measure accuracy degradation."""
    result = ExperimentResult("Noise Robustness")

    known = [(n, c, f, i) for n, c, f, i in EXECUTOR_DEFS if n != "BFS"]

    for rate in NOISE_RATES:
        correct = {"topology": 0, "dynamics": 0, "conserved": 0}
        total = 0
        for name, cls, factory, inputs in known:
            trace = generate_trace(cls, factory, inputs)
            noisy = remove_random_events(trace, rate)
            profile = obs.profile_trace(noisy, name="?")
            exp = EXPECTED[name]

            if profile.topology.best == exp["topology"]:
                correct["topology"] += 1
            if profile.dynamics.best == exp["dynamics"]:
                correct["dynamics"] += 1
            if profile.conserved.best == exp["conserved"]:
                correct["conserved"] += 1
            total += 1

        result.details.append(
            {
                "noise_rate": rate,
                "topology_acc": correct["topology"] / total * 100,
                "dynamics_acc": correct["dynamics"] / total * 100,
                "conserved_acc": correct["conserved"] / total * 100,
                "n": total,
            }
        )

    topo_curve = ", ".join(f"{d['noise_rate']:.0%}:{d['topology_acc']:.0f}%" for d in result.details)
    result.summary = f"Topology robustness curve: {topo_curve}"
    return result


# ═══════════════════════════════════════════════════════════════════
# Experiment 3: Adversarial Mixing
# ═══════════════════════════════════════════════════════════════════

MIX_PAIRS = [
    ("Classification", "GrowingGraph"),
    ("CSP", "Justification"),
    ("Diagnosis", "Evaluation"),
    ("Classification", "Justification"),
]


def experiment_adversarial_mixing(obs: AlgebraObservatory) -> ExperimentResult:
    """Interleave two executors.  Does the observatory detect Unknown?"""
    result = ExperimentResult("Adversarial Mixing")
    lookup = {n: (c, f, i) for n, c, f, i in EXECUTOR_DEFS if n != "BFS"}

    for name_a, name_b in MIX_PAIRS:
        cls_a, fac_a, inp_a = lookup[name_a]
        cls_b, fac_b, inp_b = lookup[name_b]

        trace_a = generate_trace(cls_a, fac_a, inp_a)
        trace_b = generate_trace(cls_b, fac_b, inp_b)

        mixed = interleave_traces(trace_a, trace_b, pattern="alternate")
        profile = obs.profile_trace(mixed, name="?")

        # Coherence — measures whether actions belong to a single family
        coherence = profile.coherence
        # Unknown detection — does any dimension report Unknown?
        unknown_detected = any(
            dist.best == "Unknown" for dist in (profile.topology, profile.dynamics, profile.conserved)
        )
        # Best hypotheses
        top_topo = profile.topology.best
        avg_conf = (profile.topology.confidence + profile.dynamics.confidence + profile.conserved.confidence) / 3.0

        # Action split ratio — what fraction of step events come from each
        # executor?  Use action-count approximation.
        a_steps = len([e for e in trace_a.events if e.type == "step"])
        b_steps = len([e for e in trace_b.events if e.type == "step"])
        total = a_steps + b_steps
        split_ratio = min(a_steps, b_steps) / total if total > 0 else 0.0
        balanced = split_ratio >= 0.30  # both sides contribute meaningfully

        # Hallucinating: high confidence for a single label on a BALANCED mix
        hallucinating = balanced and avg_conf >= 0.7 and coherence >= 0.5 and not unknown_detected

        entry = {
            "mix": f"{name_a} + {name_b}",
            "coherence": coherence,
            "unknown_detected": unknown_detected,
            "topology_best": top_topo,
            "topology_conf": profile.topology.confidence,
            "dynamics_best": profile.dynamics.best,
            "dynamics_conf": profile.dynamics.confidence,
            "conserved_best": profile.conserved.best,
            "conserved_conf": profile.conserved.confidence,
            "avg_confidence": round(avg_conf, 3),
            "hallucinating": hallucinating,
            "split_ratio": round(split_ratio, 3),
            "balanced": balanced,
        }
        result.details.append(entry)

    hallucinators = [d for d in result.details if d["hallucinating"]]
    detected_unknown = [d for d in result.details if d["unknown_detected"]]
    balanced_pairs = [d for d in result.details if d["balanced"]]
    lines = [
        f"Mixed pairs: {len(MIX_PAIRS)}",
        f"Balanced (≥30% each): {len(balanced_pairs)}/{len(MIX_PAIRS)}",
        f"Hallucinating on balanced: {len(hallucinators)}/{len(balanced_pairs)} "
        f"(conf≥0.7 & coherence≥0.5 & ¬Unknown & balanced)",
        f"Detected anomalous (coherence<0.5): "
        f"{sum(1 for d in result.details if d['coherence'] < 0.5)}/{len(MIX_PAIRS)}",
        f"Reported Unknown on ≥1 dimension: {len(detected_unknown)}/{len(MIX_PAIRS)}",
    ]
    result.summary = " | ".join(lines)
    return result


# ═══════════════════════════════════════════════════════════════════
# Experiment 4: Zero-shot novelty (BFS)
# ═══════════════════════════════════════════════════════════════════


def experiment_zero_shot(obs: AlgebraObservatory) -> ExperimentResult:
    """BFS is NOT a known algebra.  Which is closest?"""
    result = ExperimentResult("Zero-shot Novelty (BFS)")

    cls, factory, inputs = None, None, None
    for n, c, f, i in EXECUTOR_DEFS:
        if n == "BFS":
            cls, factory, inputs = c, f, i
            break

    assert cls is not None and factory is not None and inputs is not None
    trace = generate_trace(cls, factory, inputs)
    profile = obs.profile_trace(trace, name="BFS")

    result.details.append(
        {
            "executor": "BFS",
            "steps": profile.step_count,
            "actions": profile.unique_actions,
            "coherence": profile.coherence,
            "topology_top3": profile.topology.top_k(3),
            "dynamics_top3": profile.dynamics.top_k(3),
            "conserved_top3": profile.conserved.top_k(3),
            "topology_conf": profile.topology.confidence,
            "dynamics_conf": profile.dynamics.confidence,
            "conserved_conf": profile.conserved.confidence,
        }
    )

    topo_best = profile.topology.best
    dyn_best = profile.dynamics.best
    cons_best = profile.conserved.best

    # Find the closest known algebra
    closest = None
    closest_score = 0.0
    for name, exp in EXPECTED.items():
        score = 0.0
        if exp["topology"] == topo_best:
            score += profile.topology.confidence
        if exp["dynamics"] == dyn_best:
            score += profile.dynamics.confidence
        if exp["conserved"] == cons_best:
            score += profile.conserved.confidence
        if score > closest_score:
            closest_score = score
            closest = name

    result.summary = (
        f"BFS closest known algebra: {closest} "
        f"(match score={closest_score:.2f}, "
        f"coherence={profile.coherence:.2f}, "
        f"topology={topo_best} p={profile.topology.confidence:.2f}, "
        f"dynamics={dyn_best} p={profile.dynamics.confidence:.2f}, "
        f"conserved={cons_best} p={profile.conserved.confidence:.2f})"
    )
    return result


# ═══════════════════════════════════════════════════════════════════
# Experiment 5: Distinguishability Matrix
# ═══════════════════════════════════════════════════════════════════


def experiment_distinguishability(obs: AlgebraObservatory) -> ExperimentResult:
    """Build the 6×6 distinguishability matrix.

    For each executor *A*, run its trace through the observatory, then
    *query* the resulting confidence distributions with each executor
    *B*'s expected label signature.  The match score is the sum of
    probabilities B's expected topology, dynamics, and conserved labels
    receive in A's profile.
    """
    result = ExperimentResult("Distinguishability Matrix")
    known = [(n, c, f, i) for n, c, f, i in EXECUTOR_DEFS if n != "BFS"]
    names = [n for n, *_ in known]

    # Pre-compute profiles for each executor
    profiles: dict[str, TraceProfile] = {}
    for name, cls, factory, inputs in known:
        trace = generate_trace(cls, factory, inputs)
        profiles[name] = obs.profile_trace(trace, name=name)

    # Build matrix
    matrix: dict[str, dict[str, float]] = {}
    for name_a in names:
        p = profiles[name_a]
        row: dict[str, float] = {}
        for name_b in names:
            exp = EXPECTED[name_b]
            score = (
                p.topology.values.get(exp["topology"], 0.0)
                + p.dynamics.values.get(exp["dynamics"], 0.0)
                + p.conserved.values.get(exp["conserved"], 0.0)
            )
            row[name_b] = round(score, 3)
        matrix[name_a] = row

    # Also compute nearest-off-diagonal per executor
    details = []
    for name_a in names:
        row = matrix[name_a]
        self_score = row[name_a]
        other_scores = [(n, s) for n, s in row.items() if n != name_a]
        nearest = max(other_scores, key=lambda x: x[1]) if other_scores else ("", 0.0)
        details.append(
            {
                "executor": name_a,
                "self_score": self_score,
                "nearest": nearest[0],
                "nearest_score": nearest[1],
                "margin": round(self_score - nearest[1], 3),
            }
        )
    result.details = details
    result.matrix = matrix  # stash for printing
    result.summary = (
        f"Min self-score: {min(d['self_score'] for d in details):.3f} | "
        f"Min margin: {min(d['margin'] for d in details):.3f} | "
        f"Nearest confusable: {max(details, key=lambda x: x['nearest_score'])['nearest']} "
        f"({max(details, key=lambda x: x['nearest_score'])['nearest_score']:.2f})"
    )
    return result


# ═══════════════════════════════════════════════════════════════════
# Experiment 6: Identifiability Horizon
# ═══════════════════════════════════════════════════════════════════


def experiment_identifiability_horizon(obs: AlgebraObservatory) -> ExperimentResult:
    """Sweep trace length to find the horizon at which each executor
    crosses confidence thresholds."""
    result = ExperimentResult("Identifiability Horizon")
    known = [(n, c, f, i) for n, c, f, i in EXECUTOR_DEFS if n != "BFS"]

    for name, cls, factory, inputs in known:
        trace = generate_trace(cls, factory, inputs)
        total_steps = len([e for e in trace.events if e.type == "step"])
        expected = EXPECTED[name]

        horizons: dict[str, int | None] = {
            "topo_0.90": None,
            "dyn_0.90": None,
            "cons_0.90": None,
            "topo_0.75": None,
            "all_0.90": None,
        }

        # Sweep from 1 event to full trace
        for n_steps in range(1, total_steps + 1):
            # Build truncated trace: keep initialize + first n_steps steps + terminate
            step_count = 0
            truncated = ExecutionTrace()
            for ev in trace.events:
                if ev.type == "step":
                    if step_count >= n_steps:
                        continue
                    step_count += 1
                truncated.record(
                    ev.type,
                    dict(ev.payload),
                    transition_id=ev.transition_id,
                    state_hash_before=ev.state_hash_before,
                    state_hash_after=ev.state_hash_after,
                )

            profile = obs.profile_trace(truncated, name=f"{name}@{n_steps}")

            topo_ok = profile.topology.best == expected["topology"]
            topo_conf = profile.topology.confidence
            dyn_ok = profile.dynamics.best == expected["dynamics"]
            dyn_conf = profile.dynamics.confidence
            cons_ok = profile.conserved.best == expected["conserved"]
            cons_conf = profile.conserved.confidence

            if horizons["topo_0.90"] is None and topo_ok and topo_conf >= 0.90:
                horizons["topo_0.90"] = n_steps
            if horizons["dyn_0.90"] is None and dyn_ok and dyn_conf >= 0.90:
                horizons["dyn_0.90"] = n_steps
            if horizons["cons_0.90"] is None and cons_ok and cons_conf >= 0.90:
                horizons["cons_0.90"] = n_steps
            if horizons["topo_0.75"] is None and topo_ok and topo_conf >= 0.75:
                horizons["topo_0.75"] = n_steps
            if (
                horizons["all_0.90"] is None
                and topo_ok
                and topo_conf >= 0.90
                and dyn_ok
                and dyn_conf >= 0.90
                and cons_ok
                and cons_conf >= 0.90
            ):
                horizons["all_0.90"] = n_steps

        result.details.append(
            {
                "executor": name,
                "total_steps": total_steps,
                "horizon_topo_0.90": horizons["topo_0.90"],
                "horizon_dyn_0.90": horizons["dyn_0.90"],
                "horizon_cons_0.90": horizons["cons_0.90"],
                "horizon_topo_0.75": horizons["topo_0.75"],
                "horizon_all_0.90": horizons["all_0.90"],
            }
        )

    # Summary
    never_90 = [d for d in result.details if d["horizon_all_0.90"] is None]
    lines = [
        f"n={len(result.details)}",
        f"Never reached 0.90 on all dimensions: "
        f"{len(never_90)}/{len(result.details)} "
        f"({', '.join(d['executor'] for d in never_90) if never_90 else 'none'})",
    ]
    result.summary = " | ".join(lines)
    return result


# ═══════════════════════════════════════════════════════════════════
# Experiment 7: Dominance Threshold
# ═══════════════════════════════════════════════════════════════════


def experiment_dominance_threshold(obs: AlgebraObservatory) -> ExperimentResult:
    """Systematically vary mix ratios between two executors and measure
    where the observatory switches from reporting a known label to
    reporting Unknown."""
    result = ExperimentResult("Dominance Threshold")
    lookup = {n: (c, f, i) for n, c, f, i in EXECUTOR_DEFS if n != "BFS"}

    # Pick one representative pair: Classification (short, shared actions)
    # and GrowingGraph (long, diverse actions)
    pairs = [
        ("Classification", "GrowingGraph", [10, 30, 50, 70, 90]),
        ("Diagnosis", "Evaluation", [10, 30, 50, 70, 90]),
        ("CSP", "Justification", [10, 30, 50, 70, 90]),
    ]

    for name_a, name_b, ratios in pairs:
        cls_a, fac_a, inp_a = lookup[name_a]
        cls_b, fac_b, inp_b = lookup[name_b]

        trace_a = generate_trace(cls_a, fac_a, inp_a)
        trace_b = generate_trace(cls_b, fac_b, inp_b)

        a_step_events = [e for e in trace_a.events if e.type == "step"]
        b_step_events = [e for e in trace_b.events if e.type == "step"]

        for pct_a in ratios:
            # Build trace with pct_a% of step events from A, (100-pct_a)% from B
            n_a = max(1, int(len(a_step_events) * pct_a / 100))
            n_b = max(1, int(len(b_step_events) * (100 - pct_a) / 100))

            # Merge step events in alternating order, then wrap with
            # initialize (from A's first step's source) and terminate
            merged = ExecutionTrace()
            # Include initialize from first trace
            for ev in trace_a.events:
                if ev.type == "initialize":
                    merged.record(
                        ev.type,
                        dict(ev.payload),
                        transition_id=ev.transition_id,
                        state_hash_before=ev.state_hash_before,
                        state_hash_after=ev.state_hash_after,
                    )
                    break
            # Alternating step events
            i, j = 0, 0
            while i < n_a and j < n_b:
                if i <= j:
                    ev = a_step_events[i]
                    merged.record(
                        ev.type,
                        dict(ev.payload),
                        transition_id=ev.transition_id,
                        state_hash_before=ev.state_hash_before,
                        state_hash_after=ev.state_hash_after,
                    )
                    i += 1
                else:
                    ev = b_step_events[j]
                    merged.record(
                        ev.type,
                        dict(ev.payload),
                        transition_id=ev.transition_id,
                        state_hash_before=ev.state_hash_before,
                        state_hash_after=ev.state_hash_after,
                    )
                    j += 1
            while i < n_a:
                ev = a_step_events[i]
                merged.record(
                    ev.type,
                    dict(ev.payload),
                    transition_id=ev.transition_id,
                    state_hash_before=ev.state_hash_before,
                    state_hash_after=ev.state_hash_after,
                )
                i += 1
            while j < n_b:
                ev = b_step_events[j]
                merged.record(
                    ev.type,
                    dict(ev.payload),
                    transition_id=ev.transition_id,
                    state_hash_before=ev.state_hash_before,
                    state_hash_after=ev.state_hash_after,
                )
                j += 1
            # Terminate from second trace (or first if that's all we have)
            src = trace_b if n_b > 0 else trace_a
            for ev in src.events:
                if ev.type == "terminate":
                    merged.record(
                        ev.type,
                        dict(ev.payload),
                        transition_id=ev.transition_id,
                        state_hash_before=ev.state_hash_before,
                        state_hash_after=ev.state_hash_after,
                    )
                    break

            profile = obs.profile_trace(merged, name=f"{name_a}+{name_b}({pct_a})")

            unknown_detected = any(
                dist.best == "Unknown" for dist in (profile.topology, profile.dynamics, profile.conserved)
            )
            avg_conf = (profile.topology.confidence + profile.dynamics.confidence + profile.conserved.confidence) / 3.0

            result.details.append(
                {
                    "pair": f"{name_a}/{name_b}",
                    "pct_a": pct_a,
                    "topo_best": profile.topology.best,
                    "dyn_best": profile.dynamics.best,
                    "cons_best": profile.conserved.best,
                    "avg_conf": round(avg_conf, 3),
                    "unknown_detected": unknown_detected,
                    "coherence": profile.coherence,
                }
            )

    # Summarize: at what % does Unknown first appear for each pair?
    lines = []
    for pair in [f"{a}/{b}" for a, b, _ in pairs]:
        entries = [d for d in result.details if d["pair"] == pair]
        unknown_ratios = [d["pct_a"] for d in entries if d["unknown_detected"]]
        first_unknown = min(unknown_ratios) if unknown_ratios else "never"
        lines.append(f"{pair}: Unknown at {first_unknown}% A")
    result.summary = " | ".join(lines)
    return result


# ═══════════════════════════════════════════════════════════════════
# Experiment 8: Channel Separation
# ═══════════════════════════════════════════════════════════════════


def experiment_channel_separation(obs: AlgebraObservatory) -> ExperimentResult:
    """Split traces into isolated channels.  Which algebraic properties
    survive on each channel?"""
    result = ExperimentResult("Channel Separation")
    channels_order = [
        "full",
        "actions_only",
        "states_only",
        "state_hashes_only",
        "metadata_only",
        "timing_only",
        "transition_ids_only",
    ]

    for name, cls, factory, inputs in EXECUTOR_DEFS:
        if name == "BFS":
            continue  # No ground truth for novel executor

        trace = generate_trace(cls, factory, inputs)
        expected = EXPECTED[name]

        for channel in channels_order:
            mutated = channel_mutate(trace, channel)
            profile = obs.profile_trace(mutated, name=f"{name} ({channel})")

            topo_ok = profile.topology.best == expected["topology"]
            dyn_ok = profile.dynamics.best == expected["dynamics"]
            cons_ok = profile.conserved.best == expected["conserved"]

            result.details.append(
                {
                    "executor": name,
                    "channel": channel,
                    "topology_best": profile.topology.best,
                    "topology_conf": profile.topology.confidence,
                    "topology_correct": topo_ok,
                    "dynamics_best": profile.dynamics.best,
                    "dynamics_conf": profile.dynamics.confidence,
                    "dynamics_correct": dyn_ok,
                    "conserved_best": profile.conserved.best,
                    "conserved_conf": profile.conserved.confidence,
                    "conserved_correct": cons_ok,
                    "coherence": profile.coherence,
                    "step_count": profile.step_count,
                }
            )

    # Compute per-channel accuracy summaries
    from collections import defaultdict

    ch_acc: dict[str, dict[str, float]] = defaultdict(
        lambda: {"topology": 0.0, "dynamics": 0.0, "conserved": 0.0, "n": 0}
    )
    for d in result.details:
        ch = d["channel"]
        ch_acc[ch]["n"] += 1
        if d["topology_correct"]:
            ch_acc[ch]["topology"] += 1.0
        if d["dynamics_correct"]:
            ch_acc[ch]["dynamics"] += 1.0
        if d["conserved_correct"]:
            ch_acc[ch]["conserved"] += 1.0

    lines = []
    for ch in channels_order:
        if ch not in ch_acc:
            continue
        a = ch_acc[ch]
        n = a["n"]
        lines.append(
            f"{ch:20s}: topo={a['topology'] / n:.0%}  dyn={a['dynamics'] / n:.0%}  "
            f"cons={a['conserved'] / n:.0%}  (n={int(n)})"
        )
    result.summary = " | ".join(lines)
    return result


# ═══════════════════════════════════════════════════════════════════
# Mutation resilience — systematic info-loss
# ═══════════════════════════════════════════════════════════════════

_MUTATIONS: list[tuple[str, Callable[[ExecutionTrace], ExecutionTrace]]] = []


def _register_mutation(name: str):
    """Decorator: register a mutation function."""

    def deco(fn):
        _MUTATIONS.append((name, fn))
        return fn

    return deco


@_register_mutation("control (no mutation)")
def _mutate_control(trace: ExecutionTrace) -> ExecutionTrace:
    return trace


@_register_mutation("remove first 50% steps")
def _mutate_remove_first_half(trace: ExecutionTrace) -> ExecutionTrace:
    """Remove the first half of step events."""
    steps = [e for e in trace.events if e.type == "step"]
    keep = len(steps) // 2  # keep only second half
    step_idx = 0
    kept = 0
    new_trace = ExecutionTrace()
    for ev in trace.events:
        if ev.type == "step":
            if step_idx < (len(steps) - keep):
                step_idx += 1
                continue
            step_idx += 1
        new_trace.record(
            ev.type,
            dict(ev.payload),
            transition_id=ev.transition_id,
            state_hash_before=ev.state_hash_before,
            state_hash_after=ev.state_hash_after,
        )
    return new_trace


@_register_mutation("shuffle steps")
def _mutate_shuffle_steps(trace: ExecutionTrace) -> ExecutionTrace:
    """Randomly permute step events, preserving initialize/terminate order."""
    import random

    steps = [e for e in trace.events if e.type == "step"]
    random.shuffle(steps)
    new_trace = ExecutionTrace()
    step_iter = iter(steps)
    for ev in trace.events:
        if ev.type == "step":
            s = next(step_iter)
            new_trace.record(
                s.type,
                dict(s.payload),
                transition_id=s.transition_id,
                state_hash_before=s.state_hash_before,
                state_hash_after=s.state_hash_after,
            )
        else:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new_trace


@_register_mutation("reverse step order")
def _mutate_reverse_steps(trace: ExecutionTrace) -> ExecutionTrace:
    """Reverse all step events (temporal inversion)."""
    steps = [e for e in trace.events if e.type == "step"]
    steps.reverse()
    new_trace = ExecutionTrace()
    step_iter = iter(steps)
    for ev in trace.events:
        if ev.type == "step":
            s = next(step_iter)
            new_trace.record(
                s.type,
                dict(s.payload),
                transition_id=s.transition_id,
                state_hash_before=s.state_hash_before,
                state_hash_after=s.state_hash_after,
            )
        else:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new_trace


@_register_mutation("duplicate each step 3x")
def _mutate_duplicate_steps(trace: ExecutionTrace) -> ExecutionTrace:
    """Each step event appears 3 times consecutively."""
    new_trace = ExecutionTrace()
    for ev in trace.events:
        if ev.type == "step":
            for _ in range(3):
                new_trace.record(
                    ev.type,
                    dict(ev.payload),
                    transition_id=ev.transition_id,
                    state_hash_before=ev.state_hash_before,
                    state_hash_after=ev.state_hash_after,
                )
        else:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new_trace


@_register_mutation("strip action names (50% of steps)")
def _mutate_strip_half_actions(trace: ExecutionTrace) -> ExecutionTrace:
    """Remove transition.action from payload for 50% of step events."""
    steps = [e for e in trace.events if e.type == "step"]
    half = max(1, len(steps) // 2)
    targets = set(id(steps[i]) for i in range(half))
    new_trace = ExecutionTrace()
    for ev in trace.events:
        if ev.type == "step" and id(ev) in targets:
            payload = dict(ev.payload)
            trans = dict(payload.get("transition", {}))
            trans.pop("action", None)
            trans.pop("type", None)
            payload["transition"] = trans
            new_trace.record(
                ev.type,
                payload,
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
        else:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new_trace


@_register_mutation("compress repeated actions")
def _mutate_compress_repeated(trace: ExecutionTrace) -> ExecutionTrace:
    """Collapse consecutive identical action names into one step."""
    new_trace = ExecutionTrace()
    last_action: str | None = None
    for ev in trace.events:
        if ev.type == "step":
            action = ev.payload.get("ACTION_TRIGGER", "")
            if action == last_action:
                continue  # skip duplicate consecutive
            last_action = action
        new_trace.record(
            ev.type,
            dict(ev.payload),
            transition_id=ev.transition_id,
            state_hash_before=ev.state_hash_before,
            state_hash_after=ev.state_hash_after,
        )
    return new_trace


@_register_mutation("add 50% random noise actions")
def _mutate_add_noise_actions(trace: ExecutionTrace) -> ExecutionTrace:
    """Insert 50% random noise action steps (total steps = 1.5x original)."""
    import random

    NOISE_ACTIONS = ["idle", "noop", "reset", "refresh", "poll"]
    steps = [e for e in trace.events if e.type == "step"]
    n_noise = len(steps) // 2
    noise_indices = set(random.sample(range(len(steps) + n_noise), n_noise))
    new_trace = ExecutionTrace()
    step_idx = 0
    insert_pos = 0
    for ev in trace.events:
        if ev.type == "step":
            while insert_pos in noise_indices:
                action = random.choice(NOISE_ACTIONS)
                new_trace.record(
                    "step",
                    {"transition": {"action": action, "rationale": "noise"}},
                )
                insert_pos += 1
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
            step_idx += 1
            insert_pos += 1
        else:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new_trace


@_register_mutation("remove state payload (hashes only)")
def _mutate_remove_state_payload(trace: ExecutionTrace) -> ExecutionTrace:
    """Strip state content from payload, keep transition name and hashes."""
    new_trace = ExecutionTrace()
    for ev in trace.events:
        if ev.type == "step":
            trans = ev.payload.get("transition", {})
            clean_trans = {}
            if isinstance(trans, dict):
                if "action" in trans:
                    clean_trans["action"] = trans["action"]
                if "type" in trans:
                    clean_trans["type"] = trans["type"]
                if "rationale" in trans:
                    clean_trans["rationale"] = trans["rationale"]
            payload = {"transition": clean_trans}
            new_trace.record(
                ev.type,
                payload,
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
        else:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new_trace


@_register_mutation("swap state hashes (50% of steps)")
def _mutate_swap_hashes(trace: ExecutionTrace) -> ExecutionTrace:
    """Swap before/after hashes on 50% of steps (tests direction dependence)."""
    steps = [e for e in trace.events if e.type == "step"]
    half = max(1, len(steps) // 2)
    targets = set(id(steps[i]) for i in range(half))
    new_trace = ExecutionTrace()
    for ev in trace.events:
        if ev.type == "step" and id(ev) in targets:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_after,
                state_hash_after=ev.state_hash_before,
            )
        else:
            new_trace.record(
                ev.type,
                dict(ev.payload),
                transition_id=ev.transition_id,
                state_hash_before=ev.state_hash_before,
                state_hash_after=ev.state_hash_after,
            )
    return new_trace


def experiment_mutation_resilience(obs: AlgebraObservatory) -> ExperimentResult:
    """Apply systematic mutations to each executor's trace and measure
    what survives.  The mutation resilience atlas."""
    result = ExperimentResult("Mutation Resilience Atlas")
    known = [(n, c, f, i) for n, c, f, i in EXECUTOR_DEFS if n in EXPECTED]

    for name, cls, factory, inputs in known:
        trace = generate_trace(cls, factory, inputs)
        expected = EXPECTED[name]

        for mut_name, mut_fn in _MUTATIONS:
            mutated = mut_fn(trace)
            profile = obs.profile_trace(mutated, name=f"{name} ({mut_name})")

            topo_ok = profile.topology.best == expected["topology"]
            dyn_ok = profile.dynamics.best == expected["dynamics"]
            cons_ok = profile.conserved.best == expected["conserved"]

            result.details.append(
                {
                    "executor": name,
                    "mutation": mut_name,
                    "topology_best": profile.topology.best,
                    "topology_conf": profile.topology.confidence,
                    "topology_correct": topo_ok,
                    "dynamics_best": profile.dynamics.best,
                    "dynamics_conf": profile.dynamics.confidence,
                    "dynamics_correct": dyn_ok,
                    "conserved_best": profile.conserved.best,
                    "conserved_conf": profile.conserved.confidence,
                    "conserved_correct": cons_ok,
                    "coherence": profile.coherence,
                    "step_count": profile.step_count,
                    "unknown": profile.topology.best == "Unknown",
                }
            )

    # Compute per-mutation accuracy
    from collections import defaultdict

    mut_acc: dict[str, dict[str, float]] = defaultdict(
        lambda: {"topo": 0.0, "dyn": 0.0, "cons": 0.0, "n": 0, "unknown": 0.0, "avg_coherence": 0.0}
    )
    for d in result.details:
        m = d["mutation"]
        mut_acc[m]["n"] += 1
        mut_acc[m]["avg_coherence"] += d["coherence"]
        if d["topology_correct"]:
            mut_acc[m]["topo"] += 1.0
        if d["dynamics_correct"]:
            mut_acc[m]["dyn"] += 1.0
        if d["conserved_correct"]:
            mut_acc[m]["cons"] += 1.0
        if d["unknown"]:
            mut_acc[m]["unknown"] += 1.0

    lines = []
    for m_name, acc in sorted(mut_acc.items()):
        n = acc["n"]
        coherence = acc["avg_coherence"] / n
        unknown_pct = acc["unknown"] / n
        lines.append(
            f"{m_name:35s} topo={acc['topo'] / n:.0%}  "
            f"dyn={acc['dyn'] / n:.0%}  cons={acc['cons'] / n:.0%}  "
            f"coherence={coherence:.2f}  unknown={unknown_pct:.0%}"
        )
    result.summary = "\n  ".join(lines)
    return result


# ═══════════════════════════════════════════════════════════════════
# Reporting
# ═══════════════════════════════════════════════════════════════════


def print_result(r: ExperimentResult) -> None:
    print(f"\n{'═' * 60}")
    print(f"  Experiment: {r.name}")
    print(f"{'═' * 60}")

    if r.name == "Blind Classification":
        header = f"{'Executor':16s} {'Steps':5s} {'Topology':30s} {'Dynamics':30s} {'Conserved':30s}"
        print(f"  {header}")
        print(f"  {'─' * len(header)}")
        for d in r.details:
            t_label, t_conf, t_ok = d["topology"]
            dy_label, dy_conf, dy_ok = d["dynamics"]
            c_label, c_conf, c_ok = d["conserved"]
            t_mark = "✓" if t_ok else "✗"
            d_mark = "✓" if dy_ok else "✗"
            c_mark = "✓" if c_ok else "✗"
            print(
                f"  {d['executor']:16s} {d['steps']:5d} "
                f"{t_label:20s} {t_conf:.2f} {t_mark:3s}  "
                f"{dy_label:20s} {dy_conf:.2f} {d_mark:3s}  "
                f"{c_label:22s} {c_conf:.2f} {c_mark:3s}"
            )

    elif r.name == "Noise Robustness":
        header = f"{'Noise':8s} {'Topo Acc':10s} {'Dyn Acc':10s} {'Cons Acc':10s}"
        print(f"  {header}")
        print(f"  {'─' * len(header)}")
        for d in r.details:
            print(
                f"  {d['noise_rate']:.0%}     {d['topology_acc']:6.1f}%     "
                f"{d['dynamics_acc']:6.1f}%     {d['conserved_acc']:6.1f}%"
            )

    elif r.name == "Adversarial Mixing":
        header = f"{'Mix':30s} {'Coh':5s} {'Topo':20s} {'Dyn':20s} {'Cons':22s} {'Conf':6s} {'Unknown':8s}"
        print(f"  {header}")
        print(f"  {'─' * len(header)}")
        for d in r.details:
            unknown = "⚠" if d["unknown_detected"] else "✗"
            status = "HALLUC" if d["hallucinating"] else "OK"
            print(
                f"  {d['mix']:30s} {d['coherence']:.2f}  {d['topology_best']:20s} "
                f"{d['dynamics_best']:20s} {d['conserved_best']:22s} "
                f"{d['avg_confidence']:.2f}  {unknown:8s}"
            )

    elif r.name == "Zero-shot Novelty (BFS)":
        for d in r.details:
            print(f"  Executor:  {d['executor']}")
            print(f"  Steps:     {d['steps']}")
            print(f"  Actions:   {d['actions']}")
            print(f"  Coherence: {d.get('coherence', '?')}")
            print()
            print("  Topology top-3:")
            for label, prob in d["topology_top3"]:
                print(f"    {label:30s} {prob:.3f}")
            print("  Dynamics top-3:")
            for label, prob in d["dynamics_top3"]:
                print(f"    {label:30s} {prob:.3f}")
            print("  Conserved top-3:")
            for label, prob in d["conserved_top3"]:
                print(f"    {label:30s} {prob:.3f}")

    elif r.name == "Distinguishability Matrix":
        matrix = getattr(r, "_matrix", None)
        if matrix is None:
            return
        names = list(matrix.keys())
        print("\n  Match scores (sum of topo+dyn+cons probabilities, max=3.0):")
        print(f"\n  {'':16s}", end="")
        for n in names:
            print(f"{n[:12]:12s}", end="")
        print()
        print(f"  {'─' * 16}{'─' * (12 * len(names))}")
        for name_a in names:
            print(f"  {name_a:16s}", end="")
            for name_b in names:
                s = matrix[name_a].get(name_b, 0)
                print(f"{s:6.2f}   ", end="")
            details = [d for d in r.details if d["executor"] == name_a]
            if details:
                d = details[0]
                margin = d.get("margin", 0)
                nearest = d.get("nearest", "")
                nearest_score = d.get("nearest_score", 0)
                print(f" nearest: {nearest} ({nearest_score:.2f})  margin: {margin:.2f}")
            else:
                print()

    elif r.name == "Identifiability Horizon":
        header = (
            f"  {'Executor':20s} {'Steps':6s} {'Topo≥0.90':10s} {'Dyn≥0.90':10s} {'Cons≥0.90':10s} {'All≥0.90':10s}"
        )
        print(f"  {header}")
        print(f"  {'─' * len(header)}")
        for d in r.details:
            t90 = str(d["horizon_topo_0.90"] or "—")
            d90 = str(d["horizon_dyn_0.90"] or "—")
            c90 = str(d["horizon_cons_0.90"] or "—")
            a90 = str(d["horizon_all_0.90"] or "—")
            print(f"  {d['executor']:20s} {d['total_steps']:6d} {t90:>10s} {d90:>10s} {c90:>10s} {a90:>10s}")

    elif r.name == "Dominance Threshold":
        header = f"  {'Pair':30s} {'%A':5s} {'Topo':20s} {'Dyn':20s} {'Cons':22s} {'Conf':6s} {'Coh':5s} {'Unk':5s}"
        print(f"  {header}")
        print(f"  {'─' * len(header)}")
        for d in r.details:
            unk = "⚠" if d["unknown_detected"] else "·"
            print(
                f"  {d['pair']:30s} {d['pct_a']:3d}% "
                f"{d['topo_best']:20s} {d['dyn_best']:20s} {d['cons_best']:22s} "
                f"{d['avg_conf']:.2f}  {d['coherence']:.2f}  {unk:5s}"
            )

    elif r.name == "Channel Separation":
        channels_order = [
            "full",
            "actions_only",
            "states_only",
            "state_hashes_only",
            "metadata_only",
            "timing_only",
            "transition_ids_only",
        ]
        for ch in channels_order:
            entries = [d for d in r.details if d["channel"] == ch]
            if not entries:
                continue
            desc = CHANNEL_DEFINITIONS.get(ch, ch)
            print(f"\n  ── {ch} ──  {desc}")
            header = f"  {'Executor':16s} {'Topo':20s} {'Dyn':20s} {'Cons':22s} {'Coh':5s} {'✓':5s}"
            print(header)
            print(f"  {'─' * len(header)}")
            for d in entries:
                marks = ""
                marks += "T" if d["topology_correct"] else "·"
                marks += "D" if d["dynamics_correct"] else "·"
                marks += "C" if d["conserved_correct"] else "·"
                print(
                    f"  {d['executor']:16s} "
                    f"{d['topology_best']:20s} {d['dynamics_best']:20s} "
                    f"{d['conserved_best']:22s} "
                    f"{d['coherence']:.2f}  {marks:5s}"
                )

    elif r.name == "Mutation Resilience Atlas":
        mutations = [m[0] for m in _MUTATIONS]
        for mut in mutations:
            entries = [d for d in r.details if d["mutation"] == mut]
            if not entries:
                continue
            topo_ok = sum(1 for d in entries if d["topology_correct"])
            dyn_ok = sum(1 for d in entries if d["dynamics_correct"])
            cons_ok = sum(1 for d in entries if d["conserved_correct"])
            n = len(entries)
            unknown = sum(1 for d in entries if d["unknown"])
            avg_coherence = sum(d["coherence"] for d in entries) / n
            print(f"\n  ── {mut} ──")
            header = f"  {'Executor':16s} {'Topo':20s} {'Dyn':20s} {'Cons':22s} {'Coh':5s} {'✓':5s}"
            print(header)
            print(f"  {'─' * len(header)}")
            for d in entries:
                marks = ""
                marks += "T" if d["topology_correct"] else "·"
                marks += "D" if d["dynamics_correct"] else "·"
                marks += "C" if d["conserved_correct"] else "·"
                print(
                    f"  {d['executor']:16s} "
                    f"{d['topology_best']:20s} {d['dynamics_best']:20s} "
                    f"{d['conserved_best']:22s} "
                    f"{d['coherence']:.2f}  {marks:5s}"
                )
            print(f"  {'─' * 60}")
            print(
                f"  acc: topo={topo_ok / n:.0%}  dyn={dyn_ok / n:.0%}  "
                f"cons={cons_ok / n:.0%}  unknown={unknown / n:.0%}  "
                f"coherence={avg_coherence:.2f}"
            )

    print(f"\n  Summary: {r.summary}")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════


def main():
    _register_all()
    obs = AlgebraObservatory()

    print("=" * 60)
    print("  ALGEBRA EXPERIMENT HARNESS")
    print("  Falsifying the observatory's hypotheses")
    print("=" * 60)

    r1 = experiment_blind_classification(obs)
    print_result(r1)

    r2 = experiment_noise_robustness(obs)
    print_result(r2)

    r3 = experiment_adversarial_mixing(obs)
    print_result(r3)

    r4 = experiment_zero_shot(obs)
    print_result(r4)

    r5 = experiment_distinguishability(obs)
    print_result(r5)

    r6 = experiment_identifiability_horizon(obs)
    print_result(r6)

    r7 = experiment_dominance_threshold(obs)
    print_result(r7)

    r8 = experiment_channel_separation(obs)
    print_result(r8)

    r9 = experiment_mutation_resilience(obs)
    print_result(r9)

    print(f"\n{'=' * 60}")
    print("  Summary")
    print(f"{'=' * 60}")
    print(f"  {r1.summary}")
    print(f"  {r2.summary}")
    print(f"  {r3.summary}")
    print(f"  {r4.summary}")
    print(f"  {r5.summary}")
    print(f"  {r6.summary}")
    print(f"  {r7.summary}")
    print(f"  {r8.summary}")
    print(f"  {r9.summary}")
    print()


if __name__ == "__main__":
    main()
