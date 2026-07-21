"""Invariance probes for Classification collapse.

These are NOT unit tests.  They are *invariance probes* — designed to
force the architecture into corners where flat event logs or hidden
semantics usually appear.

Each test targets a specific failure mode:

    1. Decision-path preservation    — trace records decision context
    2. Branching distinguishability  — different branches → different steps
    3. Label emergence               — label flows through trace, not from input
    4. Trace sufficiency inversion   — process independence
    5. Multiple interpreters         — trace read-only property

If all 5 pass on the current implementation, they define the baseline
that MUST continue to pass AFTER the collapse.  Any failure post-collapse
reveals a semantic gap introduced by the elimination.

NOTE: The current ``ClassificationTemplate._traverse_children`` does
NOT add to ``classification_path`` — only the root ``_traverse`` does.
This means multi-level trees produce a single-entry path.  This is a
known limitation of the current system.  The probes test what IS
recorded: ``matched_condition`` in ``steps`` for branch distinguishability,
and the root question in ``classification_path``.
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
    ClassificationStepEvaluator,
)
from studyplan.frontends.finance import ClassificationProcess

# =========================================================================
# Helpers
# =========================================================================


def _run_classification(
    template: ClassificationTemplate,
    inputs: dict[str, Any],
) -> tuple[Any, Any, Any]:
    """Run both legacy and runtime paths, return (legacy, trace, interpreter_result)."""
    legacy = template.solve(inputs)

    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)

    interpreter = ClassificationResultInterpreter()
    reconstructed = interpreter.interpret(trace, concept_id=template.concept_id)

    return legacy, trace, reconstructed


def _convergent_tree() -> ClassificationTemplate:
    """Two different branches produce the same label.

    Structure::

        Risk assessment
          score > 80 → high_risk
          volatility > 0.5 → high_risk
          True → low_risk
    """
    root = ClassificationNode(
        question="Risk assessment",
        branches=[
            Branch(condition="score > 80", result="high_risk"),
            Branch(condition="volatility > 0.5", result="high_risk"),
            Branch(condition="True", result="low_risk"),
        ],
    )
    return ClassificationTemplate(
        "probe.convergent",
        ClassificationConfig(tree=root, output_slot="risk"),
    )


def _simple_tree(result_a: str, result_b: str) -> ClassificationTemplate:
    """Single-level tree with two named result branches."""
    root = ClassificationNode(
        question="Choose",
        branches=[
            Branch(condition="value > 50", result=result_a),
            Branch(condition="True", result=result_b),
        ],
    )
    return ClassificationTemplate(
        "probe.simple",
        ClassificationConfig(tree=root, output_slot="choice"),
    )


# =========================================================================
# Probe 1 — Decision-path preservation
# =========================================================================


def test_collapse_decision_path_preserved() -> None:
    """Probe 1: Decision context preserved in trace.

    The ``steps`` array must record the root question and which
    branch condition was matched.  The ``classification_path``
    must contain the root question text.

    Failure mode: trace/steps lose decision context, producing
    only a bare label with no trace of how it was reached.
    """
    template = _convergent_tree()

    # score > 80 → high_risk
    _, _, r = _run_classification(template, {"score": 90})
    assert r["result"] == "high_risk"
    assert r["classification_path"] == ["Risk assessment"]
    assert len(r["steps"]) >= 1
    assert r["steps"][0].get("question") == "Risk assessment"
    assert r["steps"][0].get("matched_condition") == "score > 80"

    # volatility > 0.5 → high_risk (different branch)
    _, _, r2 = _run_classification(template, {"score": 50, "volatility": 0.8})
    assert r2["result"] == "high_risk"
    assert r2["steps"][0].get("matched_condition") == "volatility > 0.5"


# =========================================================================
# Probe 2 — Branching distinguishability
# =========================================================================


def test_collapse_branching_distinguishability() -> None:
    """Probe 2: Same label via different branches → distinguishable steps.

    Two inputs reaching ``high_risk`` via different branch conditions
    must produce different ``matched_condition`` in ``steps``.

    Failure mode: trace collapses branching to a single entry,
    losing which condition was matched.
    """
    template = _convergent_tree()

    # score > 80 → high_risk
    _, _, r1 = _run_classification(template, {"score": 90})

    # volatility > 0.5 → high_risk
    _, _, r2 = _run_classification(template, {"score": 50, "volatility": 0.8})

    assert r1["result"] == r2["result"] == "high_risk"
    mc1 = r1["steps"][0].get("matched_condition")
    mc2 = r2["steps"][0].get("matched_condition")
    assert mc1 != mc2, f"Same label via different branches but matched_condition is identical: {mc1}"


# =========================================================================
# Probe 3 — Label emergence
# =========================================================================


def test_collapse_label_emergence() -> None:
    """Probe 3: Label emerges from tree traversal, captured in trace.

    The label is NOT present in the input dict — it is constructed by
    the classification tree.  The trace must record this construction:
    the decision step (with question + matched_condition) and the
    final resolved label.

    Failure mode: trace records only the final result, losing the
    reasoning chain that produced the label.
    """
    # Creates label "result_a" when value > 50
    template = _simple_tree("result_a", "result_b")
    inputs = {"value": 100}

    legacy, trace, reconstructed = _run_classification(template, inputs)

    # Label not in inputs
    assert "result_a" not in str(inputs)
    assert "result_b" not in str(inputs)

    # Steps contain decision + final result
    assert len(reconstructed["steps"]) == len(legacy["steps"]) == 2
    assert reconstructed["steps"][0].get("question") == "Choose"
    assert reconstructed["steps"][0].get("matched_condition") == "value > 50"
    assert reconstructed["steps"][1]["value"] == "result_a"

    # Trace must contain step events
    step_events = [e for e in trace.events if e.type == "step"]
    assert len(step_events) >= 1


# =========================================================================
# Probe 4 — Trace sufficiency inversion
# =========================================================================


def test_collapse_trace_sufficiency_inversion() -> None:
    """Probe 4: Interpreter reconstructs output from trace alone.

    After execution, the process object is discarded.  The interpreter
    must reconstruct from the trace only:
    - result (label)
    - classification_path (decision chain)
    - steps (reasoning graph)
    - is_nan (validity flag)
    - inputs (provenance)

    No access to ClassificationTemplate, ClassificationProcess, or
    CognitiveRuntime is permitted.

    Failure mode: interpreter silently depends on process internals
    that are not present in the trace.
    """
    template = _convergent_tree()
    inputs = {"score": 90}

    # Execute
    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)

    # Discard — trace is the only survivor
    del process
    del runtime
    del template

    # Reconstruct from trace alone
    interpreter = ClassificationResultInterpreter()
    reconstructed = interpreter.interpret(trace, concept_id="probe.convergent")

    assert reconstructed["result"] == "high_risk"
    assert reconstructed["classification_path"] == ["Risk assessment"]
    assert len(reconstructed["steps"]) >= 2
    assert reconstructed["is_nan"] is False
    assert "score" in reconstructed["inputs"]
    assert reconstructed["inputs"]["score"] == 90


# =========================================================================
# Probe 5 — Multiple interpreters, same trace
# =========================================================================


def test_collapse_multiple_interpreters_same_trace() -> None:
    """Probe 5: One trace feeds N interpreters independently.

    An immutable causal log must support multiple independent readers.
    Each interpreter produces correct output without mutating the trace.

    Failure mode: interpreter mutates shared state in the trace,
    corrupting subsequent reads.
    """
    template = _convergent_tree()
    inputs = {"score": 90}

    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)

    # Two readers, same trace
    result_interp = ClassificationResultInterpreter()
    step_interp = ClassificationStepEvaluator()

    result = result_interp.interpret(trace, concept_id=template.concept_id)
    evals = step_interp.interpret(
        trace,
        learner_steps=[
            {"step_id": "risk", "value": "high_risk"},
            {"step_id": "wrong", "value": "low_risk"},
        ],
    )

    assert result["result"] == "high_risk"
    assert evals[0]["match"] is True
    assert evals[1]["match"] is False
    assert evals[0]["expected"] == "high_risk"

    # Trace unchanged
    assert len(trace) == 3


# =========================================================================
# Edge case: no branch matches
# =========================================================================


def test_collapse_no_match_produces_nan() -> None:
    """Edge: no branch matches → is_nan=True, result=None."""
    root = ClassificationNode(
        question="Check magnitude",
        branches=[
            Branch(condition="x > 100", result="large"),
            Branch(condition="x < 0", result="negative"),
        ],
    )
    template = ClassificationTemplate(
        "probe.no_catch",
        ClassificationConfig(tree=root, output_slot="size"),
    )
    inputs = {"x": 50}  # 0 < 50 < 100 — no branch matches

    legacy, trace, reconstructed = _run_classification(template, inputs)

    assert reconstructed["result"] is None
    assert reconstructed["is_nan"] is True
    assert legacy["result"] is None
    assert legacy["is_nan"] is True
    # Steps should still contain the decision entry
    assert len(reconstructed["steps"]) >= 1
    assert reconstructed["steps"][0].get("value") is None
    assert "matched_condition" not in reconstructed["steps"][0]
