"""E3 — Provenance Observatory Bridge (Phase II Construction Experiment)

Hypothesis
----------
The AlgebraObservatory can profile provenance kernel query patterns *without
modification*, producing meaningful algebraic signatures.  If true, the two
worlds (CognitiveRuntime traces and Provenance Kernel queries) share a common
observable structure — strengthening the claim that CCI is a universal protocol.

More precisely: provenancing operations (projection, traversal, constraint
collection) are themselves cognitive computations in the CCI sense.  They have
state, produce transitions, and carry conserved quantities that the observatory
can detect.

If true: World 1 and World 2 are observationally compatible.  The observatory
is domain-independent.  A future Debugger can trace both reasoning outcomes
(World 1) and their provenance lineage (World 2) in a unified UI.

If false: Provenance queries are not cognitive computations.  The two worlds
are fundamentally different structures that cannot share an observation
framework.  This would justify keeping them as separate systems permanently.

Predictions
-----------
P1 — Valid trace: A ProvenanceQueryExecutor wrapping ViewState queries produces
a valid ExecutionTrace acceptable to AlgebraObservatory.profile_trace().

P2 — High key persistence: The profile will show key_persistence = 1.0 (same
state keys on every step) and no structural mutation (keys never grow/shrink).

P3 — linear_plan topology: Provenance query traces classify as ``linear_plan``
topology (stable state, sequential query-plan apply) with confidence > 0.5.
All 6 pre-existing topology classes (tree_traversal, probability_distribution,
score_vector, constraint_graph, expanding_graph, support_network) will each
have confidence < 0.5.

P4 — dispatch dynamics: Provenance query traces classify as ``dispatch``
dynamics (select-and-apply different query primitives) with confidence > 0.5.
All 6 pre-existing dynamics classes (traverse, reweight, aggregate, propagate,
expand, support_retract) will each have confidence < 0.5.

P5 — Differentiable from all 6 algebras: The provenance profile's feature
vector (key_persistence, has_value_mutation, has_inside_growth, coherence, etc.)
will form a distinct cluster separable from all 6 existing algebra profiles.

Three-level failure taxonomy
-----------------------------
- Vocabulary: provenance terms map to existing Observatory features (→ rename)
- Encoding: provenance traces are valid but classification is random (→ new
  topology/dynamics/conserved categories justified by evidence)
- Ontology: provenance queries cannot produce valid ExecutionTraces (→ world
  separation is fundamental, not accidental)

Experimental protocol
---------------------
Phase 1 — ProvenanceQueryExecutor: Implement a CognitiveExecutor that wraps
ViewState queries (projection, traversal, collect_inherited_constraints) as
cognitive computation steps.

Phase 2 — Observation: Run each query type individually AND a mixed query
pipeline through the AlgebraObservatory.  Record profiles.

Phase 3 — Classification: Compare provenance profiles against the 6 known
algebra profiles.  Measure separation.

Phase 4 — Conclusion: If P1-P5 hold, the observatory generalizes.
If any prediction fails, document the specific falsification.

Reference
---------
- tools/algebra_observatory.py — AlgebraObservatory, TraceProfile, ConfidenceDistribution
- studyplan/provenance/kernel/primitives.py — projection, traversal, collect_inherited_constraints
- studyplan/cci/executor.py — CognitiveExecutor lifecycle contract
"""

from __future__ import annotations

from typing import Any, Callable

from studyplan.cci import (
    CognitiveExecutor,
    CognitiveRuntime,
    ExecutionTrace,
)
from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    Transformation,
    QueryResult,
    projection,
    traversal,
    collect_inherited_constraints,
    PREDEFINED_CONTEXTS,
)

# ──────────────────────────────────────────────────────────────────────
# Phase 1 — ProvenanceQueryExecutor
# ──────────────────────────────────────────────────────────────────────

EC = PREDEFINED_CONTEXTS["default_optimizer"]

QueryPlan = list[tuple[str, dict[str, Any]]]
"""A query plan: list of (primitive_name, kwargs) tuples.

Each tuple specifies one provenance query to execute as a cognitive step.
primitive_name must match a method on ProvenanceQueryExecutor.
"""


class ProvenanceQueryExecutor(CognitiveExecutor):
    """Wrap a sequence of provenance queries as a cognitive computation.

    Each query becomes one ``step()`` transition.  The executor tracks
    query type, parameters, and result cardinality as state features
    that the AlgebraObservatory can extract.

    Usage::

        plan = [
            ("projection", {"filter_type": "artifact",
                            "predicate_name": "is_config_value"}),
            ("traversal", {"seed_id": "a", "edge_semantics": "data_flow",
                           "depth_limit": "transitive"}),
            ("collect_constraints", {"artifact_id": "b"}),
        ]
        executor = ProvenanceQueryExecutor(vs, plan)
        runtime = CognitiveRuntime()
        trace = runtime.execute(executor, {})

    The executor is stateless by contract — every ``execute()`` call
    creates fresh state via ``initialize()``.
    """

    def __init__(self, viewstate: ViewState, query_plan: QueryPlan) -> None:
        self._vs = viewstate
        self._plan = query_plan
        self._idx: int = 0

    # ── Lifecycle hooks ──────────────────────────────────────────────

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self._idx = 0
        return {
            "phase": "ready",
            "query_index": 0,
            "query_count": len(self._plan),
            "completed_primitives": [],
            "result_cardinalities": [],
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._idx >= len(self._plan):
            return {
                "next_state": {**state, "phase": "complete"},
                "transition": {
                    "action": "noop",
                    "type": "provenance_query",
                    "primitive": "none",
                    "result_cardinality": 0,
                },
            }

        primitive_name, kwargs = self._plan[self._idx]
        self._idx += 1

        result = self._execute_primitive(primitive_name, kwargs)
        rcard = _result_cardinality(result)

        next_state = {
            "phase": "stepping",
            "query_index": self._idx,
            "query_count": state["query_count"],
            "completed_primitives": state["completed_primitives"] + [primitive_name],
            "result_cardinalities": state["result_cardinalities"] + [rcard],
        }

        return {
            "next_state": next_state,
            "transition": {
                "action": primitive_name,
                "type": "provenance_query",
                "primitive": primitive_name,
                "result_cardinality": rcard,
                "kwargs": str(kwargs),
            },
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return state.get("phase") == "complete" or self._idx >= len(self._plan)

    def result(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "query_count": state["query_count"],
            "completed_primitives": state["completed_primitives"],
            "result_cardinalities": state["result_cardinalities"],
        }

    # ── Primitive dispatch ───────────────────────────────────────────

    def _execute_primitive(self, name: str, kwargs: dict[str, Any]) -> QueryResult:
        dispatch: dict[str, Callable[..., QueryResult]] = {
            "projection": self._exec_projection,
            "traversal": self._exec_traversal,
            "collect_constraints": self._exec_collect_constraints,
        }
        fn = dispatch.get(name)
        if fn is None:
            raise ValueError(f"Unknown primitive: {name}")
        return fn(**kwargs)

    def _exec_projection(
        self,
        filter_type: str,
        predicate_name: str = "",
        **kwargs: Any,
    ) -> QueryResult:
        pred = _resolve_predicate(predicate_name)
        result, _new_vs = projection(
            self._vs,
            EC,
            filter_type=filter_type,  # type: ignore[arg-type]
            predicate=pred,
        )
        return result

    def _exec_traversal(
        self,
        seed_id: str = "",
        seed_set: set[str] | None = None,
        edge_semantics: str = "data_flow",
        depth_limit: int | str = "transitive",
        **kwargs: Any,
    ) -> QueryResult:
        seeds = seed_set if seed_set is not None else {seed_id}
        result, _new_vs = traversal(self._vs, EC, seeds, edge_semantics, depth_limit)
        return result

    def _exec_collect_constraints(
        self,
        artifact_id: str = "",
        **kwargs: Any,
    ) -> QueryResult:
        constraints = collect_inherited_constraints(self._vs, artifact_id)
        constraint_artifacts = frozenset(
            Artifact(
                id=f"c:{k}:{v}",
                type="config_value",
                target=f"constraint:{k}={v}",
                metadata=(("constraint_key", k), ("constraint_value", v)),
            )
            for k, v in constraints
        )
        return QueryResult(artifacts=constraint_artifacts)


# ── Helpers ──────────────────────────────────────────────────────────

_ARTIFACT_PREDICATES: dict[str, Callable[[Artifact | Transformation], bool]] = {
    "is_config_value": lambda a: isinstance(a, Artifact) and a.type == "config_value",
    "is_ast_node": lambda a: isinstance(a, Artifact) and a.type == "ast_node",
    "has_semantic_role": lambda a: isinstance(a, Artifact) and any(k == "semantic_role" for k, _ in a.metadata),
}


def _resolve_predicate(name: str) -> Callable[[Artifact | Transformation], bool]:
    if name in _ARTIFACT_PREDICATES:
        return _ARTIFACT_PREDICATES[name]
    return _ARTIFACT_PREDICATES.get("is_config_value", lambda _: True)


def _result_cardinality(result: QueryResult) -> int:
    return len(result.artifacts) + len(result.transforms)


# ── Test fixtures ────────────────────────────────────────────────────


def build_test_viewstate() -> ViewState:
    """Build a minimal ViewState with diverse artifact types for query testing."""
    a1 = Artifact(id="a", type="config_value", target="input param", metadata=(("semantic_role", "Parameter"),))
    a2 = Artifact(id="b", type="config_value", target="intermediate", metadata=(("semantic_role", "Intermediate"),))
    a3 = Artifact(id="c", type="config_value", target="output", metadata=(("semantic_role", "Result"),))
    a4 = Artifact(id="d", type="ast_node", target="external_ref", metadata=(("semantic_role", "Reference"),))

    t1 = Transformation(
        id="t1",
        input_artifact_id="a",
        output_artifact_id="b",
        transformation_type="generative_mapping",
        rule_spec="f(x) = x + 1",
        constraints=(("assumption", "deterministic"),),
    )
    t2 = Transformation(
        id="t2",
        input_artifact_id="b",
        output_artifact_id="c",
        transformation_type="data_flow",
        rule_spec="g(y) = y * 2",
        constraints=(
            ("assumption", "monotonic"),
            ("consumes", "a"),
        ),
    )
    t3 = Transformation(
        id="t3",
        input_artifact_id="d",
        output_artifact_id="a",
        transformation_type="equivalence_mapping",
        rule_spec="d == a.map(source)",
        constraints=(("assumption", "bidirectional"),),
    )

    return ViewState(
        artifact_space=frozenset({a1, a2, a3, a4}),
        transform_space=frozenset({t1, t2, t3}),
    )


def build_query_plan(primitive: str = "projection") -> QueryPlan:
    """Build a sample query plan for the given primitive type.

    Returns a 3-step plan testing different parameters of the same primitive.
    For a mixed plan, call with the explicit tuple list.
    """
    plans: dict[str, QueryPlan] = {
        "projection": [
            ("projection", {"filter_type": "artifact", "predicate_name": "is_config_value"}),
            ("projection", {"filter_type": "artifact", "predicate_name": "is_ast_node"}),
            ("projection", {"filter_type": "artifact", "predicate_name": "has_semantic_role"}),
        ],
        "traversal": [
            ("traversal", {"seed_id": "a", "edge_semantics": "generative_mapping", "depth_limit": 1}),
            ("traversal", {"seed_id": "a", "edge_semantics": "generative_mapping", "depth_limit": "transitive"}),
            ("traversal", {"seed_id": "d", "edge_semantics": "equivalence_mapping", "depth_limit": "transitive"}),
        ],
        "collect_constraints": [
            ("collect_constraints", {"artifact_id": "c"}),
            ("collect_constraints", {"artifact_id": "b"}),
            ("collect_constraints", {"artifact_id": "a"}),
        ],
    }
    return plans.get(primitive, plans["projection"])


def build_mixed_query_plan() -> QueryPlan:
    """Build a mixed query plan exercising all three primitive types."""
    return [
        ("projection", {"filter_type": "artifact", "predicate_name": "is_config_value"}),
        ("traversal", {"seed_id": "a", "edge_semantics": "data_flow", "depth_limit": "transitive"}),
        ("collect_constraints", {"artifact_id": "c"}),
    ]


# ── Phase 2 — Observation ────────────────────────────────────────────


def run_provenance_executor(vs: ViewState, plan: QueryPlan) -> ExecutionTrace:
    """Run a ProvenanceQueryExecutor through the CognitiveRuntime.

    Returns the full ExecutionTrace for observatory analysis.
    """
    runtime = CognitiveRuntime()
    executor = ProvenanceQueryExecutor(vs, plan)
    return runtime.execute(executor, {})


def profile_provenance_trace(
    obs: Any,
    trace: ExecutionTrace,
    name: str,
) -> Any:
    """Profile a provenance trace using the AlgebraObservatory.

    ``obs`` is an AlgebraObservatory instance (imported lazily to
    avoid hard dependency on tools/).
    """
    return obs.profile_trace(trace, name=name)
