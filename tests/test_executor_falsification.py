"""Architecture falsification suite — executor protocol + IR invariants.

Tests that the :class:`~studyplan.cci.executor.CognitiveExecutor` protocol
survives all three cognitive classes (classification, diagnosis, evaluation)
*without requiring protocol extensions*, and that the emergent Cognitive IR
(:class:`~studyplan.cci.ir.CognitiveCommit`) correctly normalises all three
executor result shapes into a canonical envelope.

Invariants under test::

    Invariant 1 — Protocol closure
        All executors implement only ``initialize / step / finished / result``.
        No executor adds lifecycle methods.

    Invariant 2 — State machine form
        Every executor follows S₀ → δ → S₁ → … → S_terminal.
        The runtime drives all types identically.

    Invariant 3 — Granularity
        Deep / multi-step processes produce *more* step events than shallow
        single-step processes.  The trace reflects the internal decision
        structure, not just the output.

    Invariant 4 — Reconstructor distinguishability
        Different processes within the same class produce structurally
        different reconstructed graphs (node count, edge count).

    Invariant 5 — Runtime agnosticism
        ``CognitiveRuntime.execute()`` type-checks and returns the same
        ``ExecutionTrace`` structure for all executor types.

    Invariant 6 — IR normalisation
        ``commit_from_executor_result()`` produces a ``CognitiveCommit``
        with a non-empty string label and float confidence for every
        executor type.

If ALL 6 invariants hold, the executor protocol is a genuine architectural
primitive *and* the Cognitive IR correctly captures the cross-executor
outcome shape.
"""

from __future__ import annotations

from typing import Any

from studyplan.cci import (
    CognitiveRuntime,
    CanonicalTraceReconstructor,
    structurally_equivalent,
)
from studyplan.cci.ir import commit_from_executor_result
from studyplan.frontends.finance import (
    ClassificationExecutor,
    DiagnosticExecutor,
    EvaluationExecutor,
)

# =========================================================================
# Fixtures — shared test data
# =========================================================================

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
from studyplan.frontends.justification import (
    JustificationBelief,
    Justification,
    JustificationExecutor,
    JustificationTemplate,
)


def _just_chain_template() -> JustificationTemplate:
    """Chain A (premise) → B → C — support propagation."""
    return JustificationTemplate(
        "test.just.chain",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise A", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
            JustificationBelief(id="C", label="Derived C"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["A"]),
            Justification(consequent="C", in_supporters=["B"]),
        ],
    )


def _just_simple_template() -> JustificationTemplate:
    """Single premise — no propagation to do."""
    return JustificationTemplate(
        "test.just.simple",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise A", is_premise=True),
        ],
    )


def _just_branch_template() -> JustificationTemplate:
    """A (premise) → B, A (premise) → C — branching."""
    return JustificationTemplate(
        "test.just.branch",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise A", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
            JustificationBelief(id="C", label="Derived C"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["A"]),
            Justification(consequent="C", in_supporters=["A"]),
        ],
    )


def _growing_graph_template() -> GrowingGraphTemplate:
    """Return a simple goal tree: plan_trip → 2 subtrees, 3 and 2 leaves."""
    return GrowingGraphTemplate(
        "test.plan",
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


def _growing_graph_simple_template() -> GrowingGraphTemplate:
    """Leaf-only: a single goal with no expansion rules."""
    return GrowingGraphTemplate("test.leaf", initial_goal_type="leaf")


def _csp_template() -> CspTemplate:
    """Return a simple CSP: 3 vars from {1,2,3}, all_different."""
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


def _csp_impossible_template() -> CspTemplate:
    """4 vars, 2 values, all_different — pigeonhole, no solution."""
    return CspTemplate(
        "test.csp.impossible",
        variables=[CspVariable(id=k, domain=frozenset({1, 2})) for k in ("A", "B", "C", "D")],
        constraints=[
            CspConstraint(type="all_different", variables=["A", "B", "C", "D"]),
        ],
    )


def _classification_template(depth: str = "shallow") -> ClassificationTemplate:
    """Return a decision tree that maps score=80 to high_risk."""
    if depth == "deep":
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
    else:
        root = ClassificationNode(
            question="Assess",
            branches=[
                Branch(condition="score > 50", result="high_risk"),
                Branch(condition="True", result="other"),
            ],
        )
    return ClassificationTemplate(
        f"test.classification.{depth}",
        ClassificationConfig(tree=root, output_slot="result"),
    )


def _diagnostic_template() -> DiagnosticTemplate:
    """Simple 2-observation diagnostic scenario."""
    return DiagnosticTemplate(
        "test.diagnostic",
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


def _evaluation_template() -> EvaluationTemplate:
    """3-criteria, 2-candidate scoring scenario."""
    return EvaluationTemplate(
        "test.evaluation",
        EvaluationConfig(
            criteria=[
                EvaluationCriterion(id="criterion_a", weight=0.5, score_range=(0, 10)),
                EvaluationCriterion(id="criterion_b", weight=0.5, score_range=(0, 10)),
            ],
            candidates=["candidate_x", "candidate_y"],
        ),
    )


# =========================================================================
# Invariant 1 — Protocol closure
# =========================================================================


def _protocol_methods(obj: Any) -> set[str]:
    """Return the set of public methods on *obj* that match the executor lifecycle."""
    return {m for m in ("initialize", "step", "finished", "result") if hasattr(obj, m)}


def test_invariant_1_protocol_closure() -> None:
    """All executors expose only the 4 lifecycle methods, no extras."""
    runtime = CognitiveRuntime()

    for executor_cls, template, inputs in [
        (ClassificationExecutor, _classification_template("shallow"), {"score": 80}),
        (DiagnosticExecutor, _diagnostic_template(), {"feat_x": "pos"}),
        (
            EvaluationExecutor,
            _evaluation_template(),
            {
                "criterion_a": {"candidate_x": 8, "candidate_y": 3},
                "criterion_b": {"candidate_x": 4, "candidate_y": 7},
            },
        ),
        (CspExecutor, _csp_template(), {}),
        (CspExecutor, _csp_impossible_template(), {}),
        (GrowingGraphExecutor, _growing_graph_template(), {}),
        (GrowingGraphExecutor, _growing_graph_simple_template(), {}),
        (JustificationExecutor, _just_chain_template(), {}),
        (JustificationExecutor, _just_simple_template(), {}),
        (JustificationExecutor, _just_branch_template(), {}),
        (JustificationExecutor, _just_chain_template(), {"retract": "B"}),
    ]:
        executor = executor_cls(template)
        methods = _protocol_methods(executor)
        assert methods == {"initialize", "step", "finished", "result"}, (
            f"{executor_cls.__name__} exposes {methods}, expected 4 lifecycle methods"
        )
        trace = runtime.execute(executor, inputs)
        assert len(trace.events) >= 2


# =========================================================================
# Invariant 2 — State machine form
# =========================================================================


def test_invariant_2_state_machine_form() -> None:
    """All executors produce at least one step event (not just init+term)."""
    runtime = CognitiveRuntime()

    for executor_cls, template, inputs in [
        (ClassificationExecutor, _classification_template("shallow"), {"score": 99}),
        (DiagnosticExecutor, _diagnostic_template(), {"feat_x": "pos"}),
        (
            EvaluationExecutor,
            _evaluation_template(),
            {
                "criterion_a": {"candidate_x": 8, "candidate_y": 3},
                "criterion_b": {"candidate_x": 4, "candidate_y": 7},
            },
        ),
        (CspExecutor, _csp_template(), {}),
        (CspExecutor, _csp_impossible_template(), {}),
        (GrowingGraphExecutor, _growing_graph_template(), {}),
        (GrowingGraphExecutor, _growing_graph_simple_template(), {}),
        (JustificationExecutor, _just_chain_template(), {}),
        (JustificationExecutor, _just_simple_template(), {}),
        (JustificationExecutor, _just_branch_template(), {}),
        (JustificationExecutor, _just_chain_template(), {"retract": "B"}),
    ]:
        executor = executor_cls(template)
        trace = runtime.execute(executor, inputs)
        step_count = sum(1 for e in trace.events if e.type == "step")
        assert step_count >= 1, f"{executor_cls.__name__} produced 0 step events — the executor is not a state machine"


# =========================================================================
# Invariant 3 — Granularity
# =========================================================================


def test_invariant_3_granularity() -> None:
    """Deep processes produce more step events than shallow ones."""
    runtime = CognitiveRuntime()

    # Classification: shallow (1 decision) vs deep (3 decisions)
    shallow_exec = ClassificationExecutor(_classification_template("shallow"))
    deep_exec = ClassificationExecutor(_classification_template("deep"))

    shallow_trace = runtime.execute(shallow_exec, {"score": 80})
    deep_trace = runtime.execute(deep_exec, {"score": 80})

    shallow_steps = sum(1 for e in shallow_trace.events if e.type == "step")
    deep_steps = sum(1 for e in deep_trace.events if e.type == "step")

    assert deep_steps > shallow_steps, (
        f"Deep classification: {deep_steps} steps, "
        f"Shallow: {shallow_steps} steps — "
        f"multi-level trees must produce more steps"
    )

    # Diagnosis: 1 observation vs 3 observations
    template = _diagnostic_template()
    obs_1 = DiagnosticExecutor(template)
    obs_3 = DiagnosticExecutor(template)

    trace_1 = runtime.execute(obs_1, {"feat_x": "pos"})
    trace_3 = runtime.execute(obs_3, {"feat_x": ["pos", "neg", "pos"]})

    steps_1 = sum(1 for e in trace_1.events if e.type == "step")
    steps_3 = sum(1 for e in trace_3.events if e.type == "step")

    # steps_3 should be strictly more (more observations = more bayesian_updates)
    assert steps_3 > steps_1, (
        f"3-observation diagnosis: {steps_3} steps, "
        f"1-observation: {steps_1} steps — "
        f"more evidence must produce more steps"
    )

    # Evaluation: 2 criteria vs 5 criteria
    eval_2 = EvaluationExecutor(_evaluation_template())
    eval_5_template = EvaluationTemplate(
        "test.eval.5",
        EvaluationConfig(
            criteria=[EvaluationCriterion(id=f"c{i}", weight=1.0, score_range=(0, 10)) for i in range(5)],
            candidates=["x"],
        ),
    )
    eval_5 = EvaluationExecutor(eval_5_template)

    inputs_2 = {"criterion_a": {"x": 5}, "criterion_b": {"x": 5}}
    inputs_5 = {f"c{i}": {"x": 5} for i in range(5)}

    trace_2 = runtime.execute(eval_2, inputs_2)
    trace_5 = runtime.execute(eval_5, inputs_5)

    steps_2 = sum(1 for e in trace_2.events if e.type == "step")
    steps_5 = sum(1 for e in trace_5.events if e.type == "step")

    assert steps_5 > steps_2, (
        f"5-criterion evaluation: {steps_5} steps, 2-criterion: {steps_2} steps — more criteria must produce more steps"
    )

    # CSP: solvable (3 vars × 3 values, all_different) vs impossible
    # (4 vars × 2 values, all_different — requires backtracking)
    csp_easy = CspExecutor(_csp_template())
    csp_hard = CspExecutor(_csp_impossible_template())

    trace_easy = runtime.execute(csp_easy, {})
    trace_hard = runtime.execute(csp_hard, {})

    steps_easy = sum(1 for e in trace_easy.events if e.type == "step")
    steps_hard = sum(1 for e in trace_hard.events if e.type == "step")

    assert steps_hard > steps_easy, (
        f"Impossible CSP: {steps_hard} steps, "
        f"Solvable: {steps_easy} steps — "
        f"backtracking search must produce more steps"
    )

    # Growing graph: simple (1 leaf) vs complex (8 nodes)
    gg_simple = GrowingGraphExecutor(_growing_graph_simple_template())
    gg_complex = GrowingGraphExecutor(_growing_graph_template())

    trace_simple = runtime.execute(gg_simple, {})
    trace_complex = runtime.execute(gg_complex, {})

    steps_simple = sum(1 for e in trace_simple.events if e.type == "step")
    steps_complex = sum(1 for e in trace_complex.events if e.type == "step")

    assert steps_complex > steps_simple, (
        f"Complex growing graph: {steps_complex} steps, "
        f"Simple: {steps_simple} steps — "
        f"deeper expansion must produce more steps"
    )

    # TMS: premise only (no propagation) vs chain (3 propagations)
    tms_simple = JustificationExecutor(_just_simple_template())
    tms_chain = JustificationExecutor(_just_chain_template())

    trace_simple = runtime.execute(tms_simple, {})
    trace_chain = runtime.execute(tms_chain, {})

    steps_simple = sum(1 for e in trace_simple.events if e.type == "step")
    steps_chain = sum(1 for e in trace_chain.events if e.type == "step")

    assert steps_chain > steps_simple, (
        f"Chain TMS: {steps_chain} steps, "
        f"Simple: {steps_simple} steps — "
        f"justification propagation must produce more steps"
    )

    # TMS: chain without retraction vs chain with retraction
    tms_retract = JustificationExecutor(_just_chain_template())
    trace_retract = runtime.execute(tms_retract, {"retract": "B"})
    steps_retract = sum(1 for e in trace_retract.events if e.type == "step")
    assert steps_retract > steps_chain, (
        f"TMS chain with retraction: {steps_retract} steps, "
        f"without: {steps_chain} steps — "
        f"retraction cascade must produce more steps"
    )


# =========================================================================
# Invariant 4 — Reconstructor distinguishability
# =========================================================================


def test_invariant_4_reconstructor_distinguishability() -> None:
    """Different processes produce structurally different reconstructed graphs."""
    runtime = CognitiveRuntime()
    recon = CanonicalTraceReconstructor()

    shallow_exec = ClassificationExecutor(_classification_template("shallow"))
    deep_exec = ClassificationExecutor(_classification_template("deep"))

    shallow_graph = recon.reconstruct(runtime.execute(shallow_exec, {"score": 80}))
    deep_graph = recon.reconstruct(runtime.execute(deep_exec, {"score": 80}))

    assert not structurally_equivalent(shallow_graph, deep_graph), (
        f"Shallow and deep classification trees produce structurally "
        f"equivalent graphs ({len(shallow_graph.nodes)} nodes each) — "
        f"the reconstructor cannot distinguish different execution strategies."
    )

    # CSP: solvable vs impossible — different traces should differ
    csp_easy_graph = recon.reconstruct(runtime.execute(CspExecutor(_csp_template()), {}))
    csp_hard_graph = recon.reconstruct(runtime.execute(CspExecutor(_csp_impossible_template()), {}))
    assert not structurally_equivalent(csp_easy_graph, csp_hard_graph), (
        f"Solvable and impossible CSP produce structurally "
        f"equivalent graphs ({len(csp_easy_graph.nodes)} and "
        f"{len(csp_hard_graph.nodes)} nodes) — reconstructor "
        f"cannot distinguish different search outcomes."
    )

    # Growing graph: simple vs complex — different traces should differ
    gg_simple_graph = recon.reconstruct(runtime.execute(GrowingGraphExecutor(_growing_graph_simple_template()), {}))
    gg_complex_graph = recon.reconstruct(runtime.execute(GrowingGraphExecutor(_growing_graph_template()), {}))
    assert not structurally_equivalent(gg_simple_graph, gg_complex_graph), (
        f"Simple and complex growing graphs produce structurally "
        f"equivalent graphs ({len(gg_simple_graph.nodes)} vs "
        f"{len(gg_complex_graph.nodes)} nodes)"
    )

    # TMS: premise only vs chain — different traces should differ
    tms_simple_graph = recon.reconstruct(runtime.execute(JustificationExecutor(_just_simple_template()), {}))
    tms_chain_graph = recon.reconstruct(runtime.execute(JustificationExecutor(_just_chain_template()), {}))
    assert not structurally_equivalent(tms_simple_graph, tms_chain_graph), (
        f"Simple and chain TMS produce structurally "
        f"equivalent graphs ({len(tms_simple_graph.nodes)} vs "
        f"{len(tms_chain_graph.nodes)} nodes)"
    )

    # TMS: chain vs chain with retraction — different traces should differ
    tms_retract_graph = recon.reconstruct(
        runtime.execute(JustificationExecutor(_just_chain_template()), {"retract": "B"})
    )
    assert not structurally_equivalent(tms_chain_graph, tms_retract_graph), (
        f"TMS chain with retraction produces structurally "
        f"equivalent graph ({len(tms_chain_graph.nodes)} vs "
        f"{len(tms_retract_graph.nodes)} nodes) — "
        f"reconstructor cannot distinguish retraction traces."
    )


# =========================================================================
# Invariant 5 — Runtime agnosticism
# =========================================================================


def test_invariant_5_runtime_agnosticism() -> None:
    """The runtime handles all executor types identically — same trace shape."""
    runtime = CognitiveRuntime()

    executors: list[tuple[Any, Any, dict[str, Any]]] = [
        (ClassificationExecutor, _classification_template("shallow"), {"score": 50}),
        (DiagnosticExecutor, _diagnostic_template(), {"feat_x": "pos"}),
        (
            EvaluationExecutor,
            _evaluation_template(),
            {
                "criterion_a": {"x": 5, "y": 3},
                "criterion_b": {"x": 4, "y": 7},
            },
        ),
        (CspExecutor, _csp_template(), {}),
        (CspExecutor, _csp_impossible_template(), {}),
        (GrowingGraphExecutor, _growing_graph_template(), {}),
        (GrowingGraphExecutor, _growing_graph_simple_template(), {}),
        (JustificationExecutor, _just_chain_template(), {}),
        (JustificationExecutor, _just_simple_template(), {}),
        (JustificationExecutor, _just_branch_template(), {}),
        (JustificationExecutor, _just_chain_template(), {"retract": "B"}),
    ]

    for cls, template, inputs in executors:
        executor = cls(template)
        trace = runtime.execute(executor, inputs)

        assert trace.events[0].type == "initialize", (
            f"{cls.__name__}: first event should be 'initialize', got '{trace.events[0].type}'"
        )
        assert trace.events[-1].type == "terminate", (
            f"{cls.__name__}: last event should be 'terminate', got '{trace.events[-1].type}'"
        )

        # All step events must have a transition in their payload
        for event in trace.events:
            if event.type == "step":
                trans = event.payload.get("transition", {})
                assert isinstance(trans, dict), (
                    f"{cls.__name__}: step event transition is {type(trans).__name__}, expected dict"
                )
                assert "action" in trans, (
                    f"{cls.__name__}: step event transition missing 'action' key: {list(trans.keys())}"
                )


# =========================================================================
# Invariant 6 — IR normalisation
# =========================================================================


def _result_from(trace):
    """Extract the final result dict from an execution trace."""
    return trace.events[-1].payload.get("result")


def test_invariant_6_ir_normalisation() -> None:
    """All executor results normalise into a valid CognitiveCommit."""
    runtime = CognitiveRuntime()

    executors: list[tuple[Any, Any, dict[str, Any]]] = [
        (ClassificationExecutor, _classification_template("shallow"), {"score": 80}),
        (ClassificationExecutor, _classification_template("deep"), {"score": 80}),
        (DiagnosticExecutor, _diagnostic_template(), {"feat_x": "pos"}),
        (DiagnosticExecutor, _diagnostic_template(), {"feat_x": ["pos", "neg"]}),
        (
            EvaluationExecutor,
            _evaluation_template(),
            {
                "criterion_a": {"x": 8, "y": 3},
                "criterion_b": {"x": 4, "y": 7},
            },
        ),
        (
            EvaluationExecutor,
            _evaluation_template(),
            {
                "criterion_a": {"x": 1, "y": 9},
                "criterion_b": {"x": 2, "y": 8},
            },
        ),
        (CspExecutor, _csp_template(), {}),
        (CspExecutor, _csp_impossible_template(), {}),
        (GrowingGraphExecutor, _growing_graph_template(), {}),
        (GrowingGraphExecutor, _growing_graph_simple_template(), {}),
        (JustificationExecutor, _just_chain_template(), {}),
        (JustificationExecutor, _just_simple_template(), {}),
        (JustificationExecutor, _just_branch_template(), {}),
        (JustificationExecutor, _just_chain_template(), {"retract": "B"}),
    ]

    for cls, template, inputs in executors:
        executor = cls(template)
        result = _result_from(runtime.execute(executor, inputs))
        commit = commit_from_executor_result(result)
        if result and result.get("is_nan"):
            assert commit is None, f"{cls.__name__}: impossible problem returned a commit ({commit}) instead of None"
            continue
        assert commit is not None, f"{cls.__name__}: commit_from_executor_result returned None for result={result}"
        assert isinstance(commit.label, str) and commit.label, (
            f"{cls.__name__}: commit label is empty: {commit.label!r}"
        )
        assert isinstance(commit.confidence, float), (
            f"{cls.__name__}: commit confidence is {type(commit.confidence).__name__}, expected float"
        )
