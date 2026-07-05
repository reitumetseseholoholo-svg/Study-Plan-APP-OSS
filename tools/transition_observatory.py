#!/usr/bin/env python3
"""Transition Observatory — collect, classify, and report transition actions.

Usage::

    python tools/transition_observatory.py

Scans all CognitiveExecutor implementations, runs each through multiple
representative scenarios, collects every emitted ``action`` value, and
produces a structured report with:

- Unique actions per executor
- Cross-executor action sharing (which actions appear in 2+ executors)
- Suggested action families (semantic groupings)
- Action vocabulary statistics

This is the empirical basis for designing the Cognitive IR canonical form.
No action family enters the IR until at least 3 executors emit it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from studyplan.cci import CognitiveRuntime
from studyplan.frontends.finance import (
    ClassificationExecutor,
    DiagnosticExecutor,
    EvaluationExecutor,
)

from studyplan.domain_reasoning.concept_types.classification_concept import (
    Branch,
    ClassificationConfig,
    ClassificationNode,
    ClassificationTemplate,
)
from studyplan.domain_reasoning.process.diagnostic import (
    DiagnosticConfig,
    DiagnosticTemplate,
    ProcessHypothesis,
    ProcessFeature,
)
from studyplan.domain_reasoning.process.evaluation import (
    EvaluationConfig,
    EvaluationCriterion,
    EvaluationTemplate,
)
from studyplan.frontends.csp import CspConstraint, CspExecutor, CspTemplate, CspVariable
from studyplan.frontends.growing_graph import (
    ExpansionRule,
    GrowingGraphExecutor,
    GrowingGraphTemplate,
)


# =========================================================================
# Executive summary line
# =========================================================================

LINE = "─" * 72


# =========================================================================
# Scenario definitions — one per executor class, covering varied inputs
# =========================================================================


def _classification_scenarios() -> list[tuple[ClassificationExecutor, str, dict[str, Any]]]:
    """Return (executor, scenario_name, inputs) for varied classification runs."""
    scenarios: list[tuple[ClassificationExecutor, str, dict[str, Any]]] = []

    # Shallow tree (1 level)
    shallow = ClassificationTemplate(
        "test.shallow",
        ClassificationConfig(
            tree=ClassificationNode(
                question="Assess",
                branches=[
                    Branch(condition="score > 50", result="high"),
                    Branch(condition="score > 20", result="medium"),
                    Branch(condition="True", result="low"),
                ],
            ),
            output_slot="result",
        ),
    )

    scenarios.append((ClassificationExecutor(shallow), "shallow-high", {"score": 80}))
    scenarios.append((ClassificationExecutor(shallow), "shallow-medium", {"score": 35}))
    scenarios.append((ClassificationExecutor(shallow), "shallow-low", {"score": 5}))
    scenarios.append((ClassificationExecutor(shallow), "shallow-missing-score", {"score": -1}))

    # Deep tree (3 levels)
    deep = ClassificationTemplate(
        "test.deep",
        ClassificationConfig(
            tree=ClassificationNode(
                question="Deep assess",
                branches=[
                    Branch(
                        condition="score > 0",
                        children=[
                            Branch(
                                condition="score > 30",
                                children=[
                                    Branch(condition="score > 60", result="high"),
                                    Branch(condition="True", result="medium"),
                                ],
                            ),
                            Branch(condition="True", result="low"),
                        ],
                    ),
                    Branch(condition="True", result="invalid"),
                ],
            ),
            output_slot="result",
        ),
    )

    scenarios.append((ClassificationExecutor(deep), "deep-high", {"score": 80}))
    scenarios.append((ClassificationExecutor(deep), "deep-medium", {"score": 45}))
    scenarios.append((ClassificationExecutor(deep), "deep-low", {"score": 15}))
    scenarios.append((ClassificationExecutor(deep), "deep-invalid", {"score": -5}))

    return scenarios


def _diagnostic_scenarios() -> list[tuple[DiagnosticExecutor, str, dict[str, Any]]]:
    """Return (executor, scenario_name, inputs) for varied diagnostic runs."""
    scenarios: list[tuple[DiagnosticExecutor, str, dict[str, Any]]] = []

    template = DiagnosticTemplate(
        "test.diag",
        DiagnosticConfig(
            hypotheses=[
                ProcessHypothesis(id="hyp_a", prior=0.5, label="Hypothesis A"),
                ProcessHypothesis(id="hyp_b", prior=0.5, label="Hypothesis B"),
            ],
            features=[
                ProcessFeature(id="feat_x", type="categorical", values=["pos", "neg"]),
            ],
            likelihoods={
                "hyp_a": {"feat_x": {"pos": 0.9, "neg": 0.2}},
                "hyp_b": {"feat_x": {"pos": 0.3, "neg": 0.8}},
            },
        ),
    )

    # Single observation
    scenarios.append((DiagnosticExecutor(template), "single-pos", {"feat_x": "pos"}))
    scenarios.append((DiagnosticExecutor(template), "single-neg", {"feat_x": "neg"}))

    # Multiple observations
    scenarios.append((DiagnosticExecutor(template), "multi-agree", {"feat_x": ["pos", "pos"]}))
    scenarios.append((DiagnosticExecutor(template), "multi-disagree", {"feat_x": ["pos", "neg"]}))
    scenarios.append((DiagnosticExecutor(template), "triple-evidence", {"feat_x": ["pos", "pos", "neg"]}))

    # Empty observation
    scenarios.append((DiagnosticExecutor(template), "no-observations", {}))

    return scenarios


def _evaluation_scenarios() -> list[tuple[EvaluationExecutor, str, dict[str, Any]]]:
    """Return (executor, scenario_name, inputs) for varied evaluation runs."""
    scenarios: list[tuple[EvaluationExecutor, str, dict[str, Any]]] = []

    # 2 criteria, 2 candidates
    two_criteria = EvaluationTemplate(
        "test.eval.2c",
        EvaluationConfig(
            criteria=[
                EvaluationCriterion(id="cost", weight=0.6, score_range=(0, 10)),
                EvaluationCriterion(id="quality", weight=0.4, score_range=(0, 10)),
            ],
            candidates=["option_a", "option_b"],
        ),
    )
    scenarios.append(
        (
            EvaluationExecutor(two_criteria),
            "2crit-a-wins",
            {
                "cost": {"option_a": 8, "option_b": 3},
                "quality": {"option_a": 6, "option_b": 7},
            },
        )
    )
    scenarios.append(
        (
            EvaluationExecutor(two_criteria),
            "2crit-b-wins",
            {
                "cost": {"option_a": 2, "option_b": 9},
                "quality": {"option_a": 3, "option_b": 8},
            },
        )
    )

    # 5 criteria, 3 candidates
    three_candidates = EvaluationTemplate(
        "test.eval.5c",
        EvaluationConfig(
            criteria=[
                EvaluationCriterion(id="c_speed", weight=0.2, score_range=(0, 10)),
                EvaluationCriterion(id="c_cost", weight=0.25, score_range=(0, 10)),
                EvaluationCriterion(id="c_quality", weight=0.3, score_range=(0, 10)),
                EvaluationCriterion(id="c_risk", weight=0.15, score_range=(0, 10)),
                EvaluationCriterion(id="c_support", weight=0.1, score_range=(0, 10)),
            ],
            candidates=["vendor_x", "vendor_y", "vendor_z"],
        ),
    )
    scenarios.append(
        (
            EvaluationExecutor(three_candidates),
            "5crit-vendor-x",
            {
                "c_speed": {"vendor_x": 9, "vendor_y": 5, "vendor_z": 3},
                "c_cost": {"vendor_x": 4, "vendor_y": 7, "vendor_z": 6},
                "c_quality": {"vendor_x": 8, "vendor_y": 6, "vendor_z": 4},
                "c_risk": {"vendor_x": 5, "vendor_y": 5, "vendor_z": 8},
                "c_support": {"vendor_x": 7, "vendor_y": 6, "vendor_z": 5},
            },
        )
    )

    # Single candidate, 2 criteria
    single_cand = EvaluationTemplate(
        "test.eval.1c",
        EvaluationConfig(
            criteria=[
                EvaluationCriterion(id="pass", weight=1.0, score_range=(0, 10)),
            ],
            candidates=["sole"],
        ),
    )
    scenarios.append(
        (
            EvaluationExecutor(single_cand),
            "1crit-solo",
            {
                "pass": {"sole": 7},
            },
        )
    )

    # Missing criteria (partial inputs)
    scenarios.append(
        (
            EvaluationExecutor(two_criteria),
            "2crit-partial",
            {
                "cost": {"option_a": 5, "option_b": 5},
            },
        )
    )

    return scenarios


def _csp_scenarios() -> list[tuple[CspExecutor, str, dict[str, Any]]]:
    """Return (executor, scenario_name, inputs) for varied CSP runs."""
    scenarios: list[tuple[CspExecutor, str, dict[str, Any]]] = []

    # Simple solvable: 2 vars, binary_not_equal
    simple = CspTemplate(
        "csp.simple",
        [
            CspVariable("A", frozenset({1, 2})),
            CspVariable("B", frozenset({1, 2})),
        ],
        [CspConstraint("binary_not_equal", ["A", "B"])],
    )
    scenarios.append((CspExecutor(simple), "simple-2var", {}))

    # All-different solvable: 3 vars, 3 values
    alldiff = CspTemplate(
        "csp.alldiff",
        [CspVariable(k, frozenset({1, 2, 3})) for k in ("A", "B", "C")],
        [CspConstraint("all_different", ["A", "B", "C"])],
    )
    scenarios.append((CspExecutor(alldiff), "alldiff-3var", {}))

    # All-different impossible: 4 vars, 2 values (pigeonhole)
    impossible = CspTemplate(
        "csp.impossible",
        [CspVariable(k, frozenset({1, 2})) for k in ("A", "B", "C", "D")],
        [CspConstraint("all_different", ["A", "B", "C", "D"])],
    )
    scenarios.append((CspExecutor(impossible), "impossible-4var", {}))

    # Mixed constraints: A != B, B != C (unary allowed)
    mixed = CspTemplate(
        "csp.mixed",
        [
            CspVariable("A", frozenset({1, 2, 3})),
            CspVariable("B", frozenset({1, 2, 3})),
            CspVariable("C", frozenset({1, 2, 3})),
        ],
        [
            CspConstraint("binary_not_equal", ["A", "B"]),
            CspConstraint("binary_not_equal", ["B", "C"]),
            CspConstraint("unary_allowed", ["A"], {"allowed": frozenset({2})}),
        ],
    )
    scenarios.append((CspExecutor(mixed), "mixed-constraints", {}))

    return scenarios


def _growing_graph_scenarios() -> list[tuple[GrowingGraphExecutor, str, dict[str, Any]]]:
    """Return (executor, scenario_name, inputs) for varied growing graph runs."""
    scenarios: list[tuple[GrowingGraphExecutor, str, dict[str, Any]]] = []

    # Single leaf
    leaf = GrowingGraphTemplate("gg.leaf", initial_goal_type="leaf")
    scenarios.append((GrowingGraphExecutor(leaf), "single-leaf", {}))

    # Simple chain: A → B → C
    chain = GrowingGraphTemplate(
        "gg.chain",
        initial_goal_type="A",
        expansion_rules=[
            ExpansionRule("A", [("B", "Step B")]),
            ExpansionRule("B", [("C", "Step C")]),
        ],
    )
    scenarios.append((GrowingGraphExecutor(chain), "chain-3deep", {}))

    # Wide tree: root → 4 leaves
    wide = GrowingGraphTemplate(
        "gg.wide",
        initial_goal_type="root",
        expansion_rules=[
            ExpansionRule(
                "root",
                [
                    ("leaf_a", "Leaf A"),
                    ("leaf_b", "Leaf B"),
                    ("leaf_c", "Leaf C"),
                    ("leaf_d", "Leaf D"),
                ],
            ),
        ],
    )
    scenarios.append((GrowingGraphExecutor(wide), "wide-4leaves", {}))

    # Complex multi-level (trip planning)
    complex_plan = GrowingGraphTemplate(
        "gg.complex",
        initial_goal_type="plan_trip",
        expansion_rules=[
            ExpansionRule(
                "plan_trip",
                [
                    ("book_flights", "Book flights"),
                    ("book_hotel", "Book hotel"),
                ],
            ),
            ExpansionRule(
                "book_flights",
                [
                    ("find_flights", "Find flights"),
                    ("choose_flight", "Choose flight"),
                    ("pay", "Payment"),
                ],
            ),
            ExpansionRule(
                "book_hotel",
                [
                    ("find_hotel", "Find hotel"),
                    ("reserve", "Reserve"),
                ],
            ),
        ],
    )
    scenarios.append((GrowingGraphExecutor(complex_plan), "complex-trip", {}))

    return scenarios


# =========================================================================
# Collection
# =========================================================================

ActionRecord = dict[str, Any]  # {action, executor, scenario, count, rationale_summary}


def _collect(runtime: CognitiveRuntime) -> list[ActionRecord]:
    """Run all scenarios across all executors and return collected actions."""
    records: list[ActionRecord] = []

    for executor, scenario, inputs in _classification_scenarios():
        trace = runtime.execute(executor, inputs)
        for event in trace.events:
            if event.type == "step":
                trans = event.payload.get("transition", {})
                if trans.get("action"):
                    records.append(
                        {
                            "action": trans["action"],
                            "executor": "ClassificationExecutor",
                            "scenario": scenario,
                            "rationale": trans.get("rationale", ""),
                        }
                    )

    for executor, scenario, inputs in _diagnostic_scenarios():
        trace = runtime.execute(executor, inputs)
        for event in trace.events:
            if event.type == "step":
                trans = event.payload.get("transition", {})
                if trans.get("action"):
                    records.append(
                        {
                            "action": trans["action"],
                            "executor": "DiagnosticExecutor",
                            "scenario": scenario,
                            "rationale": trans.get("rationale", ""),
                        }
                    )

    for executor, scenario, inputs in _evaluation_scenarios():
        trace = runtime.execute(executor, inputs)
        for event in trace.events:
            if event.type == "step":
                trans = event.payload.get("transition", {})
                if trans.get("action"):
                    records.append(
                        {
                            "action": trans["action"],
                            "executor": "EvaluationExecutor",
                            "scenario": scenario,
                            "rationale": trans.get("rationale", ""),
                        }
                    )

    for executor, scenario, inputs in _csp_scenarios():
        trace = runtime.execute(executor, inputs)
        for event in trace.events:
            if event.type == "step":
                trans = event.payload.get("transition", {})
                if trans.get("action"):
                    records.append(
                        {
                            "action": trans["action"],
                            "executor": "CspExecutor",
                            "scenario": scenario,
                            "rationale": trans.get("rationale", ""),
                        }
                    )

    for executor, scenario, inputs in _growing_graph_scenarios():
        trace = runtime.execute(executor, inputs)
        for event in trace.events:
            if event.type == "step":
                trans = event.payload.get("transition", {})
                if trans.get("action"):
                    records.append(
                        {
                            "action": trans["action"],
                            "executor": "GrowingGraphExecutor",
                            "scenario": scenario,
                            "rationale": trans.get("rationale", ""),
                        }
                    )

    return records


# =========================================================================
# Classification — action families
# =========================================================================

# Heuristic families based on the action name's prefix / suffix pattern.
# These are *observations*, not canonical definitions.  When a 4th executor
# arrives, the families should be revised against the new data.
_FAMILY_RULES: list[tuple[str, str, str]] = [
    # (pattern, family_name, family_description)
    ("evaluate_condition", "decision_condition", "Evaluate a branch condition against context"),
    ("no_match", "decision_condition", "No branch condition matched"),
    ("descend", "structural_navigate", "Descend into a sub-structure (tree level, sub-goal, etc.)"),
    ("score_criterion", "scoring", "Score candidates on a single criterion"),
    ("criteria_exhausted", "phase_transition", "Transition between processing phases (scoring → resolving)"),
    ("observations_exhausted", "phase_transition", "Transition between processing phases (observation → commit)"),
    ("commit_result", "commit_outcome", "Commit a result / output value"),
    ("commit_diagnosis", "commit_outcome", "Commit a MAP hypothesis as the diagnosis"),
    ("resolve_judgment", "commit_outcome", "Resolve a judgment from accumulated scores"),
    ("bayesian_update", "probabilistic_inference", "Update beliefs via Bayes rule from one observation"),
    # CSP topology actions
    ("select_variable", "selection", "Choose the next variable to assign"),
    ("assign_value", "mutation", "Bind a value to a variable — structural state change"),
    ("propagate", "propagation", "Reduce domains of connected variables via forward checking"),
    ("domain_wipeout", "failure_detection", "A domain became empty — search must backtrack"),
    ("no_values_remaining", "failure_detection", "No untried values remain for a variable"),
    ("backtrack", "structural_undo", "Undo a previous assignment and restore domain snapshot"),
    ("search_exhausted", "termination", "Entire search space explored — no solution"),
    ("all_vars_assigned", "completion", "All variables have been assigned a value"),
    ("commit_solution", "commit_outcome", "Solution found and committed"),
    ("commit_plan", "commit_outcome", "Plan committed as solution"),
    # Growing graph topology actions
    ("activate_goal", "activation", "Mark a pending goal as active"),
    ("expand_goal", "graph_expansion", "Create child nodes for an active goal — graph grows"),
    ("complete_leaf", "completion", "Mark a leaf goal as satisfied"),
    ("descend", "structural_navigate", "Move focus to a child node"),
    ("sibling_pending", "selection", "Check for pending siblings before ascending"),
    ("ascend", "structural_navigate", "Return focus to parent node"),
    ("root_satisfied", "completion", "Root goal satisfied — entire plan complete"),
    ("no_pending_child", "failure_detection", "No pending children found during descent"),
    ("search_exhausted", "termination", "Entire search space explored — no solution"),
]


def _classify(action: str) -> tuple[str, str]:
    """Return (family_name, family_description) for a given action string."""
    for pattern, family, desc in _FAMILY_RULES:
        if action == pattern:
            return family, desc
    return ("unclassified", "No family rule matched")


# =========================================================================
# Report
# =========================================================================


def _report(records: list[ActionRecord]) -> None:
    """Print the structured observatory report."""

    # --- 1. Overview ---
    print(f"\n  TRANSITION OBSERVATORY REPORT\n{LINE}")
    print(f"  Total transition events collected: {len(records)}")
    unique_actions = sorted({r["action"] for r in records})
    print(f"  Unique action types: {len(unique_actions)}")
    executors_observed = sorted({r["executor"] for r in records})
    print(f"  Executors observed: {', '.join(executors_observed)}")

    # --- 2. Per-executor action table ---
    print(f"\n  1. ACTIONS BY EXECUTOR\n{LINE}")

    by_executor: dict[str, Counter[str]] = defaultdict(Counter)
    executor_scenario_counts: dict[str, int] = defaultdict(int)
    for r in records:
        by_executor[r["executor"]][r["action"]] += 1
    for r in records:
        executor_scenario_counts[r["executor"]] += 1

    for exec_name in sorted(by_executor):
        cnt = by_executor[exec_name]
        total = sum(cnt.values())
        print(f"\n  [{exec_name}]  ({total} transitions, {len(cnt)} unique actions)")
        for action in sorted(cnt):
            pct = 100.0 * cnt[action] / total
            bar = "█" * max(1, int(pct // 5))
            print(f"    {action:<28s}  {cnt[action]:>4d}  ({pct:5.1f}%)  {bar}")

    # --- 3. Cross-executor sharing ---
    print(f"\n  2. CROSS-EXECUTOR ACTION SHARING\n{LINE}")

    action_to_executors: dict[str, set[str]] = defaultdict(set)
    for r in records:
        action_to_executors[r["action"]].add(r["executor"])

    for action in sorted(unique_actions):
        execs = action_to_executors[action]
        sharing = " + ".join(sorted(execs))
        families = _classify(action)
        print(f"    {action:<28s}  [{sharing:<55s}]  family={families[0]}")

    # --- 4. Suggested action families ---
    print(f"\n  3. SUGGESTED ACTION FAMILIES\n{LINE}")

    family_executors: dict[str, set[str]] = defaultdict(set)
    family_actions: dict[str, set[str]] = defaultdict(set)
    for r in records:
        family, _ = _classify(r["action"])
        family_executors[family].add(r["executor"])
        family_actions[family].add(r["action"])

    for family in sorted(family_executors):
        execs = sorted(family_executors[family])
        actions = sorted(family_actions[family])
        _, desc = _classify(actions[0])
        print(f"\n    {family}")
        print(f"      Description: {desc}")
        print(f"      Executors:   {', '.join(execs)}")
        print(f"      Actions:     {', '.join(actions)}")
        if len(execs) >= 3:
            eligible = "✓ ELIGIBLE for IR canonical form (≥3 executors)"
            print(f"      IR status:   {eligible}")
        else:
            print("      IR status:   2 or fewer executors — wait for more data")

    # --- 4b. Unclassified actions ---
    unclassified_actions = [a for a in unique_actions if _classify(a)[0] == "unclassified"]
    if unclassified_actions:
        print(f"\n    ⚠ UNCLASSIFIED ACTIONS\n{LINE}")
        for action in unclassified_actions:
            print(f"      {action}")

    # --- 5. Action vocabulary growth ---
    print(f"\n  4. VOCABULARY STATISTICS\n{LINE}")
    print(f"    Total unique action types: {len(unique_actions)}")
    print(f"    Action families:            {len(family_executors)}")
    print(f"    Shared (2+ executors):      {sum(1 for v in action_to_executors.values() if len(v) >= 2)}")
    print(f"    Exclusive (1 executor):     {sum(1 for v in action_to_executors.values() if len(v) == 1)}")
    print(f"    IR-eligible families (≥3):  {sum(1 for v in family_executors.values() if len(v) >= 3)}")
    print()


# =========================================================================
# Main
# =========================================================================


def main() -> None:
    runtime = CognitiveRuntime()
    records = _collect(runtime)
    _report(records)


if __name__ == "__main__":
    main()
