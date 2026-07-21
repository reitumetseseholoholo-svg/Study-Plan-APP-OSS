"""Execution Layer — Composes kernel primitives into structured reasoning.

Given a compiled ViewState, executes kernel query plans that answer questions
about dependency, provenance, and constraint membership. No domain-specific
logic, no LLM calls, no kernel changes.

Hypothesis H-E-01:
    A deterministic kernel query plan (composition of projection, traversal,
    reduction, collect_inherited_constraints) can produce structured reasoning
    traces from compiled ViewStates without any domain-specific logic, LLM
    calls, or kernel changes.

Usage:
    from studyplan.provenance.execution import ExecutionContext
    from studyplan.provenance.compiler import DomainCompiler
    from studyplan.provenance.compiler_spec import NPV

    vs = DomainCompiler.compile_one(NPV)
    ctx = ExecutionContext(vs)
    trace = ctx.inherited_assumptions("NPV")
    print(trace["assumptions"])
"""

from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.kernel import (
    ViewState,
    QueryResult,
    PREDEFINED_CONTEXTS,
    EvaluationContext,
    projection,
    traversal,
)
from studyplan.provenance.runtime_index import (
    PerArtifactIndex,
    RuntimeIndex,
    build_runtime_index,
)


# ============================================================
# Reasoning trace types
# ============================================================


@dataclass
class KernelStep:
    """A single kernel operation in a query plan."""

    primitive: str
    args: dict[str, Any]
    result: QueryResult = field(default_factory=QueryResult)
    input_hash: str = ""
    output_hash: str = ""


@dataclass
class ReasoningTrace:
    """Structured output of an execution query.

    Every trace captures:
    - question: the query that was asked
    - target: the artifact/concept being queried
    - steps: the kernel operations executed
    - result: the structured answer
    - assumptions: all assumptions discovered along the way
    - dependency_path: artifact IDs in dependency order (where applicable)
    """

    question: str
    target: str
    steps: tuple[KernelStep, ...]
    result: dict[str, Any]
    assumptions: frozenset[tuple[str, str]] = frozenset()
    dependency_path: tuple[str, ...] = ()


# ============================================================
# Execution Context
# ============================================================


class ExecutionContext:
    """Executes kernel query plans over compiled ViewStates.

    Consumes a RuntimeIndex (prepared execution image) rather than
    building its own derived structures. Multiple ExecutionContexts
    for the same ViewState share one RuntimeIndex.

    Methods correspond to question types. Each returns a ReasoningTrace
    containing the kernel operations executed, the result, and all
    discovered assumptions and dependency paths.

    The execution layer is deterministic, compositional, and requires
    zero kernel changes.
    """

    def __init__(self, vs: ViewState, ec: EvaluationContext | None = None, index: RuntimeIndex | None = None):
        self.vs = vs
        self.ec = ec or PREDEFINED_CONTEXTS["default_optimizer"]
        self._idx = index or build_runtime_index(vs)

    def _precompute(self) -> dict[str, dict[str, Any]]:
        """Bridge to RuntimeIndex — returns the same dict shape as before.

        Delegates to the pre-built RuntimeIndex. Does not re-compute.
        """
        result: dict[str, dict[str, Any]] = {}
        for aid, p in self._idx.by_id.items():
            result[aid] = {
                "inherited": p.inherited,
                "assumptions_sorted": list(p.assumptions_sorted),
                "consumes_sorted": list(p.consumes_sorted),
                "base_prereqs": list(p.base_prereqs),
                "base_upstream": list(p.base_upstream),
                "reachable": p.reachable,
                "dep_path": p.dep_path,
            }
        return result

    def _per_artifact(self, artifact_id: str) -> dict[str, Any]:
        """Return the per-artifact data as a dict (backward compat)."""
        p = self._idx.by_id.get(artifact_id)
        if p is None:
            return {}
        return {
            "inherited": p.inherited,
            "assumptions_sorted": list(p.assumptions_sorted),
            "consumes_sorted": list(p.consumes_sorted),
            "base_prereqs": list(p.base_prereqs),
            "base_upstream": list(p.base_upstream),
            "reachable": p.reachable,
            "dep_path": p.dep_path,
        }

    def _inherited_assumptions_data(self, artifact_id: str) -> dict[str, Any]:
        """Return lightweight result dict for inherited_assumptions query.

        Fast path — no ReasoningTrace wrapper. O(1) via RuntimeIndex.
        """
        data = self._per_artifact(artifact_id)
        return {
            "artifact": artifact_id,
            "total_constraints": len(data.get("inherited", set())),
            "assumptions": data.get("assumptions_sorted", []),
            "consumes": data.get("consumes_sorted", []),
            "dependency_path": data.get("dep_path", (artifact_id,)),
        }

    def inherited_assumptions_fast(self, artifact_id: str) -> dict[str, Any]:
        """Fast path — returns lightweight result dict, no ReasoningTrace wrapper.

        O(1) lookup from pre-computed cache. Use when only the data values
        are needed (dashboard, tutor) and the full trace is not required.
        """
        return self._inherited_assumptions_data(artifact_id)

    def inherited_assumptions(self, artifact_id: str) -> ReasoningTrace:
        """Which assumptions does this artifact inherit?

        O(1) lookup via RuntimeIndex — pre-computed during index build.
        """
        data = self._inherited_assumptions_data(artifact_id)
        inherited = self._idx.by_id.get(artifact_id, PerArtifactIndex()).inherited

        return ReasoningTrace(
            question="inherited_assumptions",
            target=artifact_id,
            steps=(
                KernelStep(
                    primitive="collect_inherited_constraints",
                    args={"artifact_id": artifact_id},
                    result=QueryResult(metadata={"count": data["total_constraints"]}),
                ),
            ),
            result=data,
            assumptions=frozenset(c for c in inherited if c[0] == "assumption"),
            dependency_path=data["dependency_path"],
        )

    def downstream_impact(self, constraint_text: str) -> ReasoningTrace:
        """Which artifacts become invalid if this constraint is removed?

        Finds all transformations whose constraints contain the given text
        (in any constraint value, regardless of key — domain-independent),
        then traces forward to every artifact that depends on those
        transformations.
        """
        # Step 1: Find transforms whose constraints mention this text
        step1_result, step1_vs = projection(
            self.vs,
            self.ec,
            filter_type="transformation",
            predicate=lambda t: any(constraint_text in c[1] for c in t.constraints),
        )

        # Extract output artifacts from affected transforms
        direct_outputs = frozenset(t.output_artifact_id for t in step1_result.transforms)

        # Step 2: Trace forward to find downstream artifacts
        step2_result, step2_vs = traversal(
            step1_vs if step1_result.artifacts or step1_result.transforms else self.vs,
            self.ec,
            seed_set=direct_outputs,
            edge_semantics="transformational/generative_mapping",
            depth_limit="transitive",
        )

        impacted_ids = frozenset(a.id for a in step2_result.artifacts)

        result = {
            "constraint": constraint_text,
            "affected_transforms": sorted(t.id for t in step1_result.transforms),
            "direct_outputs": sorted(direct_outputs),
            "impacted_artifacts": sorted(impacted_ids),
            "impact_count": len(impacted_ids),
        }

        return ReasoningTrace(
            question="downstream_impact",
            target=constraint_text,
            steps=(
                KernelStep(
                    "projection",
                    {"type": "transformation", "predicate": f"has_constraint({constraint_text})"},
                    result=step1_result,
                ),
                KernelStep(
                    "traversal",
                    {"seed": direct_outputs, "edge": "generative_mapping", "depth": "transitive"},
                    result=step2_result,
                ),
            ),
            result=result,
            dependency_path=tuple(sorted(impacted_ids)),
        )

    def _base_prerequisites_data(self, artifact_id: str) -> dict[str, Any]:
        """Return lightweight result dict for base_prerequisites query.

        Fast path — no ReasoningTrace wrapper. O(1) via RuntimeIndex.
        """
        data = self._per_artifact(artifact_id)
        prereqs = data.get("base_prereqs", [])
        return {
            "artifact": artifact_id,
            "base_prerequisites": prereqs,
            "count": len(prereqs),
            "reachable_artifacts": data.get("reachable", len(prereqs) + 1),
            "dependency_path": data.get("dep_path", (artifact_id,)),
        }

    def base_prerequisites_fast(self, artifact_id: str) -> dict[str, Any]:
        """Fast path — returns lightweight result dict, no ReasoningTrace wrapper."""
        return self._base_prerequisites_data(artifact_id)

    def base_prerequisites(self, artifact_id: str) -> ReasoningTrace:
        """What is the minimal set of base inputs for this artifact?

        O(1) lookup via RuntimeIndex — pre-computed during index build.
        """
        data = self._base_prerequisites_data(artifact_id)
        inherited = self._idx.by_id.get(artifact_id, PerArtifactIndex()).inherited

        return ReasoningTrace(
            question="base_prerequisites",
            target=artifact_id,
            steps=(
                KernelStep(
                    "collect_inherited_constraints",
                    {"artifact_id": artifact_id},
                    result=QueryResult(
                        metadata={
                            "prereq_count": data["count"],
                            "constraint_count": len(inherited),
                        }
                    ),
                ),
            ),
            result=data,
            dependency_path=data["dependency_path"],
            assumptions=frozenset(c for c in inherited if c[0] == "assumption"),
        )

    def _upstream_artifacts_data(self, artifact_id: str) -> dict[str, Any]:
        """All upstream artifacts reachable via backward traversal.

        No type filter — returns every artifact that feeds into the target.
        Suitable for cross-domain use (PG, LLVM, GUI, FM).
        """
        data = self._per_artifact(artifact_id)
        upstream = list(data.get("base_upstream", []))
        return {
            "artifact": artifact_id,
            "upstream_artifacts": upstream,
            "count": len(upstream),
        }

    def upstream_artifacts_fast(self, artifact_id: str) -> dict[str, Any]:
        """Fast path — returns lightweight result dict, no ReasoningTrace wrapper."""
        return self._upstream_artifacts_data(artifact_id)

    def upstream_artifacts(self, artifact_id: str) -> ReasoningTrace:
        """Which artifacts does this artifact depend on?

        Cross-domain equivalent of base_prerequisites. Returns all upstream
        artifacts regardless of type. O(1) after first pre-compute.
        """
        data = self._upstream_artifacts_data(artifact_id)

        return ReasoningTrace(
            question="upstream_artifacts",
            target=artifact_id,
            steps=(
                KernelStep(
                    primitive="collect_inherited_constraints",
                    args={"artifact_id": artifact_id},
                    result=QueryResult(metadata={"count": data["count"]}),
                ),
            ),
            result=data,
        )

    def dependency_path(self, from_id: str, to_id: str, edge_types: set[str] | None = None) -> ReasoningTrace:
        """Why does 'to_id' depend on 'from_id'?

        Finds a dependency path between two artifacts using BFS over
        the transform space. Returns the chain of artifacts and
        transforms that connect them.

        edge_types: set of transformation_type values to follow.
        Defaults to {"generative_mapping"} for backward compatibility.
        Pass {"generative_mapping", "data_flow"} to cross edge types.
        """
        edge_types = edge_types or {"generative_mapping"}
        path = self._bfs_shortest_path(from_id, to_id, edge_types)

        edge_desc = ", ".join(sorted(edge_types))
        result = {
            "from": from_id,
            "to": to_id,
            "edge_types": edge_desc,
            "path_exists": path is not None,
            "path_length": len(path) if path else 0,
            "path": list(path) if path else [],
        }

        # If path exists, collect assumptions along the way
        assumptions: set[tuple[str, str]] = set()
        if path:
            path_artifacts = set(path)
            for t in self.vs.transform_space:
                if t.input_artifact_id in path_artifacts:
                    assumptions.update(c for c in t.constraints if c[0] == "assumption")
                if t.output_artifact_id in path_artifacts:
                    assumptions.update(c for c in t.constraints if c[0] == "assumption")

        return ReasoningTrace(
            question="dependency_path",
            target=f"{from_id} → {to_id}",
            steps=(
                KernelStep(
                    "traversal",
                    {"seed": {from_id}, "edge": edge_desc, "depth": "transitive"},
                    result=QueryResult(
                        metadata={"path_length": len(path) if path else 0},
                    ),
                ),
            ),
            result=result,
            assumptions=frozenset(assumptions),
            dependency_path=tuple(path) if path else (),
        )

    def _compute_dependency_path(self, artifact_id: str) -> tuple[str, ...]:
        """Return the pre-computed dependency path for this artifact.

        O(1) dict lookup — path is pre-computed in RuntimeIndex.
        """
        data = self._per_artifact(artifact_id)
        return data.get("dep_path", (artifact_id,))

    def _bfs_shortest_path(
        self,
        from_id: str,  # noqa: C901
        to_id: str,
        edge_types: set[str] | None = None,
    ) -> tuple[str, ...] | None:
        """BFS shortest path from 'from_id' to 'to_id' following transforms.

        Uses RuntimeIndex per-edge-type adjacency maps — O(1) lookup
        for single-edge-type queries, O(T) for T edge types.

        edge_types: set of transformation_type values to follow.
        Defaults to {"generative_mapping"}.
        """
        if edge_types is None:
            edge_types = {"generative_mapping"}
        if from_id == to_id:
            return (from_id,)

        # Build adjacency from per-edge-type index (pre-built in RuntimeIndex)
        forward: dict[str, set[str]] = {}
        reverse: dict[str, set[str]] = {}
        for etype in edge_types:
            ef = self._idx.edge_forward.get(etype, {})
            for k, v in ef.items():
                forward.setdefault(k, set()).update(v)
            er = self._idx.edge_reverse.get(etype, {})
            for k, v in er.items():
                reverse.setdefault(k, set()).update(v)
        # NOTE: consumed-artifact edges are already included in the
        # per-edge-type maps above — no separate consumes_map loop needed.

        # Bidirectional BFS
        visited_from: dict[str, str | None] = {from_id: None}
        visited_to: dict[str, str | None] = {to_id: None}
        queue_from: list[str] = [from_id]
        queue_to: list[str] = [to_id]

        while queue_from and queue_to:
            # Expand from start
            current = queue_from.pop(0)
            for neighbor in forward.get(current, set()):
                if neighbor not in visited_from:
                    visited_from[neighbor] = current
                    if neighbor in visited_to:
                        return self._reconstruct_bidirectional(neighbor, visited_from, visited_to)
                    queue_from.append(neighbor)
            for neighbor in reverse.get(current, set()):
                if neighbor not in visited_from:
                    visited_from[neighbor] = current
                    if neighbor in visited_to:
                        return self._reconstruct_bidirectional(neighbor, visited_from, visited_to)
                    queue_from.append(neighbor)

            # Expand from target
            current = queue_to.pop(0)
            for neighbor in reverse.get(current, set()):
                if neighbor not in visited_to:
                    visited_to[neighbor] = current
                    if neighbor in visited_from:
                        return self._reconstruct_bidirectional(neighbor, visited_from, visited_to)
                    queue_to.append(neighbor)
            for neighbor in forward.get(current, set()):
                if neighbor not in visited_to:
                    visited_to[neighbor] = current
                    if neighbor in visited_from:
                        return self._reconstruct_bidirectional(neighbor, visited_from, visited_to)
                    queue_to.append(neighbor)

        return None

    def _reconstruct_bidirectional(
        self,
        midpoint: str,
        visited_from: dict[str, str | None],
        visited_to: dict[str, str | None],
    ) -> tuple[str, ...]:
        """Reconstruct path from bidirectional BFS."""
        path_from: list[str] = []
        current: str | None = midpoint
        while current is not None:
            path_from.append(current)
            current = visited_from.get(current)
        path_from.reverse()

        path_to: list[str] = []
        current = visited_to.get(midpoint)
        while current is not None:
            path_to.append(current)
            current = visited_to.get(current)

        return tuple(path_from + path_to)
