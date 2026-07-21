"""Falsification probes — testing representational adequacy under pressure.

These are *invariance diagnostics*: each test asserts a claim about the
representation layer.  When a probe triggers, the representation is
demonstrating a structural blind spot.

Claims under test::

    Probe A — Reconstruction injectivity
        Different execution strategies → different causal graphs
        (trace is faithful to execution identity)

    Probe B — Strategy identifiability
        Same label, different reasoning strategies → distinguishable traces
        (trace is injective over reasoning process space, not just outputs)
"""

from __future__ import annotations

from typing import Any

from studyplan.domain_reasoning.concept_types.classification_concept import (
    Branch,
    ClassificationConfig,
    ClassificationNode,
    ClassificationTemplate,
)

from studyplan.cci import (
    CognitiveRuntime,
    ClassificationResultInterpreter,
    CanonicalTraceReconstructor,
    structurally_equivalent,
)
from studyplan.frontends.finance import ClassificationProcess


# =========================================================================
# Strategy definitions — two different trees that classify the same input
# to the same label via structurally distinct reasoning paths.
# =========================================================================


def _shallow_tree(label: str) -> ClassificationTemplate:
    """One-level tree: direct condition → result.

    Structure::

        Assess
          cond → label
          True → "other"
    """
    root = ClassificationNode(
        question="Assess",
        branches=[
            Branch(condition="score > 50", result=label),
            Branch(condition="True", result="other"),
        ],
    )
    return ClassificationTemplate(
        "probe.shallow",
        ClassificationConfig(tree=root, output_slot="result"),
    )


def _deep_tree(label: str) -> ClassificationTemplate:
    """Three-level tree: same label reached through nested conditions.

    Structure::

        Assess
          score > 0 →
            score > 30 →
              score > 50 → label
              True → "medium"
            True → "low"
          True → "invalid"
    """
    root = ClassificationNode(
        question="Assess",
        branches=[
            Branch(
                condition="score > 0",
                children=[
                    Branch(
                        condition="score > 30",
                        children=[
                            Branch(condition="score > 50", result=label),
                            Branch(condition="True", result="medium"),
                        ],
                    ),
                    Branch(condition="True", result="low"),
                ],
            ),
            Branch(condition="True", result="invalid"),
        ],
    )
    return ClassificationTemplate(
        "probe.deep",
        ClassificationConfig(tree=root, output_slot="result"),
    )


def _print_finding(title: str, detail: str = "") -> None:
    """Print a structured finding for diagnostic visibility."""
    print()
    print("=" * 72)
    print(f"  FINDING: {title}")
    if detail:
        print("-" * 72)
        for line in detail.strip().split("\n"):
            print(f"  {line}")
    print("=" * 72)


def _run_strategy(
    template: ClassificationTemplate,
    inputs: dict[str, Any],
) -> tuple[Any, Any]:
    """Execute a strategy and return (trace, reconstructed_graph)."""
    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)
    graph = CanonicalTraceReconstructor().reconstruct(trace)
    return trace, graph


# =========================================================================
# Probe A — Reconstruction Injectivity
# =========================================================================


def test_probe_a_reconstruction_injectivity() -> None:
    """Claim: different execution strategies → structurally different graphs.

    Two classification trees (shallow vs deep) classify the same input.
    If the trace model is structurally adequate, the reconstructed graphs
    must differ in topology (node count, edge count, branching structure).

    FALSIFIED if: both strategies produce the same graph topology.
    → Diagnostic: trace collapses different execution structures into
      a single topological type — representational under-specification.
    """
    label = "high_risk"
    inputs = {"score": 80}

    trace_shallow, graph_shallow = _run_strategy(_shallow_tree(label), inputs)
    trace_deep, graph_deep = _run_strategy(_deep_tree(label), inputs)

    # Both must produce the same label
    interp = ClassificationResultInterpreter()
    r1 = interp.interpret(trace_shallow, concept_id="probe.shallow")
    r2 = interp.interpret(trace_deep, concept_id="probe.deep")
    assert r1["result"] == label
    assert r2["result"] == label

    # ---------------------
    # THE INVARIANT PROBE
    # ---------------------

    # Different tree depths must produce different reconstructed graphs.
    # decision_depth captures the max substep count across any transition:
    #   shallow: depth=1 (single condition)
    #   deep:    depth=3 (nested conditions)
    if structurally_equivalent(graph_shallow, graph_deep):
        _print_finding(
            "PROBE A COLLAPSED: shallow and deep trees produce structurally identical graphs",
            detail=(
                f"Shallow: {len(graph_shallow.nodes)} nodes, "
                f"{len(graph_shallow.causal_edges)} causal edges, "
                f"{len(graph_shallow.branches)} branches, "
                f"depth={graph_shallow.decision_depth}\n"
                f"Deep:   {len(graph_deep.nodes)} nodes, "
                f"{len(graph_deep.causal_edges)} causal edges, "
                f"{len(graph_deep.branches)} branches, "
                f"depth={graph_deep.decision_depth}\n"
                f"Both classify input {{{repr(inputs)}}} → '{label}' "
                f"via different internal paths, but graph topology is invariant."
            ),
        )

    assert not structurally_equivalent(graph_shallow, graph_deep), (
        f"RECONSTRUCTION NON-INJECTIVE: shallow vs deep trees produce "
        f"structurally identical graphs\n"
        f"Both: {len(graph_shallow.nodes)} nodes, "
        f"{len(graph_shallow.causal_edges)} causal edges\n"
        f"Shallow depth: {graph_shallow.decision_depth}, "
        f"Deep depth: {graph_deep.decision_depth}\n"
        f"→ Decision depth metric should distinguish these."
    )


# =========================================================================
# Probe B — Strategy Identifiability
# =========================================================================


def test_probe_b_strategy_identifiability() -> None:
    """Claim: same label, different strategies → distinguishable traces.

    Two strategies that produce the same output label via different
    internal reasoning must leave distinguishable structural fingerprints
    in the trace.

    FALSIFIED if: traces are structurally equivalent despite different
    reasoning paths.
    → Diagnostic: trace is blind to internal reasoning variation;
      output-equivalent projections are indistinguishable.
    """
    label = "approved"
    inputs = {"score": 75}

    # Strategy A: forward chain — shallow tree, direct
    # Strategy B: backtracking — deep tree, nested conditions
    trace_fwd, graph_fwd = _run_strategy(_shallow_tree(label), inputs)
    trace_bwd, graph_bwd = _run_strategy(_deep_tree(label), inputs)

    # Both produce the same label
    interp = ClassificationResultInterpreter()
    r1 = interp.interpret(trace_fwd, concept_id="probe.shallow")
    r2 = interp.interpret(trace_bwd, concept_id="probe.deep")
    assert r1["result"] == label
    assert r2["result"] == label

    # Different reasoning strategies SHOULD produce different paths
    assert r1["classification_path"] != r2["classification_path"], (
        f"Strategies are indistinguishable at interpreter level: both produce path {r1['classification_path']}"
    )

    # ---------------------
    # THE INVARIANT PROBE
    # ---------------------

    # The trace topology must differ for different strategies
    if structurally_equivalent(graph_fwd, graph_bwd):
        _print_finding(
            "PROBE B COLLAPSED: different reasoning strategies produce structurally identical graphs",
            detail=(
                f"Forward chain path: {r1['classification_path']}\n"
                f"Backtracking path:  {r2['classification_path']}\n"
                f"Graph topology: "
                f"{len(graph_fwd.nodes)} nodes, "
                f"{len(graph_fwd.causal_edges)} edges, "
                f"fwd depth={graph_fwd.decision_depth}, "
                f"bwd depth={graph_bwd.decision_depth}\n"
                f"→ Interpreter sees the difference, "
                f"reconstructor now sees it too via decision_depth."
            ),
        )

    assert not structurally_equivalent(graph_fwd, graph_bwd), (
        f"STRATEGY IDENTIFIABILITY FAILED: forward chain and backtracking "
        f"produce structurally identical graphs despite different "
        f"classification paths\n"
        f"Forward path: {r1['classification_path']}\n"
        f"Backtrack path: {r2['classification_path']}\n"
        f"Forward depth: {graph_fwd.decision_depth}, "
        f"Backtrack depth: {graph_bwd.decision_depth}\n"
        f"→ Decision depth should distinguish these strategies."
    )
