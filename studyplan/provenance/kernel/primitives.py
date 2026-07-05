"""Kernel primitives — atomic operations over ViewState graph.

Protocol observation H-K-02 (Class A, Jul 2026):
    Kernel primitives should operate over indexed graph representations
    rather than reconstructing graph structure on each call.

    The current implementation scans ALL transforms per frontier element
    (for t in all_transforms). Building adjacency maps (output_to_inputs,
    consumes_map) at instantiation would reduce O(V×E) to O(V+E). This
    is deferred until the kernel API stabilizes — the principle to record
    is "indexed representation," not "use adjacency dicts."

    See execution.py:_precompute() for the existing adjacency map pattern
    that this principle would generalize.
"""

from __future__ import annotations
from typing import Any, Callable, Literal
from studyplan.provenance.kernel.types import (
    ViewState,
    QueryResult,
    QueryTraceEntry,
    ProjectionRule,
    Artifact,
    Transformation,
    EvaluationContext,
    EDGE_SEMANTICS_HIERARCHY,
    EQUIVALENCE_RELATIONS,
)


# --- Constraint inheritance (provenance completeness) ---


def collect_inherited_constraints(vs: ViewState, artifact_id: str) -> set[tuple[str, str]]:
    """Return all constraints inherited by an artifact via transitive dependency.

    Collects constraints from every transformation on any path that feeds into
    the target artifact. This is purely graph-theoretic: traverse backwards
    (output -> input), collect constraints along the way. No domain knowledge
    about what the constraints mean.

    Confirms the P0 hypothesis: constraint inheritance IS traversal.
    effective_constraints(X) = constraints(X) U constraints(all provenance ancestors).
    Used by Tutor, Debugger, and Lab from the same code path.
    """
    all_transforms: set[Transformation] = set(vs.transform_space)
    visited: set[str] = set()
    frontier: set[str] = {artifact_id}
    collected: set[tuple[str, str]] = set()

    while frontier:
        current = frontier.pop()
        if current in visited:
            continue
        visited.add(current)
        for t in all_transforms:
            if t.output_artifact_id != current:
                continue
            collected.update(t.constraints)
            frontier.add(t.input_artifact_id)
            for c_key, c_val in t.constraints:
                if c_key == "consumes":
                    frontier.add(c_val)

    return collected


# --- Primitive signatures ---
# Each primitive: (ViewState, EvaluationContext, **kwargs) -> (QueryResult, ViewState)


def identity(vs: ViewState, ec: EvaluationContext) -> tuple[QueryResult, ViewState]:
    """No-op morphism. Returns ViewState unchanged. No provenance entry."""
    return QueryResult(), vs


def projection(
    vs: ViewState,
    ec: EvaluationContext,
    filter_type: Literal["artifact", "transformation"],
    predicate: Callable[[Artifact | Transformation], bool],
    note: str | None = None,
) -> tuple[QueryResult, ViewState]:
    """Select subset of artifacts or transforms matching predicate."""
    if filter_type == "artifact":
        matched_artifacts = frozenset(a for a in vs.artifact_space if predicate(a))
        result = QueryResult(artifacts=matched_artifacts, transforms=frozenset())
        new_artifact_space = matched_artifacts
        new_transform_space = vs.transform_space
    else:
        matched_transforms = frozenset(t for t in vs.transform_space if predicate(t))
        result = QueryResult(artifacts=frozenset(), transforms=matched_transforms)
        new_artifact_space = vs.artifact_space
        new_transform_space = matched_transforms

    new_proj = ProjectionRule(
        "filter",
        {"type": filter_type, "note": note or ""},
    )

    new_vs = ViewState(
        artifact_space=new_artifact_space,
        transform_space=new_transform_space,
        projection=new_proj,
        provenance=vs.provenance
        + (
            QueryTraceEntry(
                primitive="projection",
                args={
                    "filter_type": filter_type,
                    "predicate": predicate.__name__ if hasattr(predicate, "__name__") else str(predicate),
                },
                input_hash=vs.content_hash,
                output_hash=ViewState(
                    artifact_space=new_artifact_space,
                    transform_space=new_transform_space,
                    projection=new_proj,
                ).content_hash,
                result=result,
            ),
        ),
    )

    return result, new_vs


def _resolve_edge_semantics(semantics: str) -> set[str]:
    """Resolve edge semantics to set of leaf types.

    Supports: parent type name (e.g. "structural"), leaf type (e.g. "call"),
    or path syntax (e.g. "structural/call").
    """
    # Path syntax: "structural/call" → split and check
    if "/" in semantics:
        parts = semantics.split("/", 1)
        parent, child = parts[0], parts[1]
        if parent in EDGE_SEMANTICS_HIERARCHY and child in EDGE_SEMANTICS_HIERARCHY[parent]:
            return {child}
        raise ValueError(f"Unknown edge semantics path: {semantics}")

    if semantics in EDGE_SEMANTICS_HIERARCHY:
        return set(EDGE_SEMANTICS_HIERARCHY[semantics])
    # Check if it's a leaf type
    for _parent, subtypes in EDGE_SEMANTICS_HIERARCHY.items():
        if semantics in subtypes:
            return {semantics}
    raise ValueError(f"Unknown edge semantics: {semantics}")


def _follow_edges(
    seed_ids: set[str],
    transforms: frozenset[Transformation],
    edge_types: set[str],
    depth_limit: int,
) -> set[str]:
    """BFS traversal over transformation edges. Returns set of reachable artifact IDs."""
    reached: set[str] = set(seed_ids)
    frontier: set[str] = set(seed_ids)
    depth = 0

    while frontier and (depth_limit < 0 or depth < depth_limit):
        next_frontier: set[str] = set()
        for t in transforms:
            if t.transformation_type not in edge_types:
                continue
            if t.input_artifact_id in frontier and t.output_artifact_id not in reached:
                next_frontier.add(t.output_artifact_id)
                reached.add(t.output_artifact_id)
            if t.output_artifact_id in frontier and t.input_artifact_id not in reached:
                next_frontier.add(t.input_artifact_id)
                reached.add(t.input_artifact_id)
        frontier = next_frontier
        depth += 1

    return reached


def traversal(
    vs: ViewState,
    ec: EvaluationContext,
    seed_set: set[str],
    edge_semantics: str,
    depth_limit: int | str = -1,
) -> tuple[QueryResult, ViewState]:
    """Follow edges from seed set to reach connected entities.

    depth_limit: int (max steps) or "transitive" (unlimited).
    """
    resolved_depth: int
    if depth_limit == "transitive":
        resolved_depth = -1
    else:
        assert isinstance(depth_limit, int)
        resolved_depth = depth_limit
    edge_types = _resolve_edge_semantics(edge_semantics)
    reached_ids = _follow_edges(seed_set, vs.transform_space, edge_types, resolved_depth)

    # Build artifact set: use existing artifacts where available, create stubs for new IDs
    existing_by_id = {a.id: a for a in vs.artifact_space}
    # Infer types for stub artifacts from the transform_space endpoints
    artifact_types: dict[str, str] = {}
    for t in vs.transform_space:
        artifact_types[t.input_artifact_id] = artifact_types.get(t.input_artifact_id, "ast_node")
        artifact_types[t.output_artifact_id] = artifact_types.get(t.output_artifact_id, "ast_node")
    for a in vs.artifact_space:
        artifact_types[a.id] = a.type

    reached_artifact_list: list[Artifact] = []
    for rid in reached_ids:
        if rid in existing_by_id:
            reached_artifact_list.append(existing_by_id[rid])
        else:
            atype = artifact_types.get(rid, "ast_node")
            reached_artifact_list.append(
                Artifact(
                    id=rid,
                    type=atype,
                    target=f"reached:{rid}",
                    metadata=(("source", "traversal_stub"),),
                )
            )
    reached_artifacts = frozenset(reached_artifact_list)
    # Transforms whose endpoints are both in reached set
    reached_transforms = frozenset(
        t for t in vs.transform_space if t.input_artifact_id in reached_ids and t.output_artifact_id in reached_ids
    )

    new_proj = ProjectionRule(
        "trace",
        {"seed": str(seed_set), "edge_type": edge_semantics, "depth": depth_limit},
    )

    result = QueryResult(
        artifacts=reached_artifacts,
        transforms=reached_transforms,
    )

    new_vs = ViewState(
        artifact_space=reached_artifacts,
        transform_space=reached_transforms,
        projection=new_proj,
        provenance=vs.provenance
        + (
            QueryTraceEntry(
                primitive="traversal",
                args={"seed_set": str(seed_set), "edge_semantics": edge_semantics, "depth_limit": depth_limit},
                input_hash=vs.content_hash,
                output_hash=ViewState(
                    artifact_space=reached_artifacts,
                    transform_space=reached_transforms,
                    projection=new_proj,
                ).content_hash,
                result=result,
            ),
        ),
    )

    return result, new_vs


def _compute_equivalence_classes(
    artifacts: frozenset[Artifact],
    relation: str,
    ec: EvaluationContext,
) -> dict[str, frozenset[str]]:
    """Partition artifact IDs into equivalence classes under the given relation + context.

    This is a simplified implementation — real equivalence detection requires
    semantic analysis of artifact structure. Here we use a labeled equivalence
    demonstrated by annotation.
    """
    # In a full implementation, this would inspect artifact structure.
    # For now, return singleton classes (each artifact is its own class).
    return {a.id: frozenset({a.id}) for a in artifacts}


def reduction(
    vs: ViewState,
    ec: EvaluationContext,
    relation: str,
    note: str | None = None,
) -> tuple[QueryResult, ViewState]:
    """Collapse artifacts into equivalence classes under a relation + context."""
    if relation not in EQUIVALENCE_RELATIONS:
        raise ValueError(f"Unknown equivalence relation: {relation}")

    classes = _compute_equivalence_classes(vs.artifact_space, relation, ec)

    # Build equivalence-class artifacts
    class_artifacts: set[Artifact] = set()
    for class_id, member_ids in classes.items():
        members = [a for a in vs.artifact_space if a.id in member_ids]
        if members:
            combined_meta_pairs: list[tuple[str, Any]] = []
            seen_keys: set[str] = set()
            for m in members:
                for k, v in m.metadata:
                    if k not in seen_keys:
                        combined_meta_pairs.append((k, v))
                        seen_keys.add(k)
            class_artifacts.add(
                Artifact(
                    id=f"eq:{class_id}",
                    type="ast_node",
                    target=f"equivalence_class:{relation}:{class_id}",
                    metadata=(
                        ("members", tuple(member_ids)),
                        ("relation", relation),
                    )
                    + tuple(combined_meta_pairs),
                )
            )

    new_proj = ProjectionRule(
        "collapse_by",
        {"relation": relation, "context": ec.regime, "note": note or ""},
    )

    result = QueryResult(
        artifacts=frozenset(class_artifacts),
        metadata={"relation": relation, "context": ec.regime, "num_classes": len(classes)},
    )

    new_vs = ViewState(
        artifact_space=frozenset(class_artifacts),
        transform_space=frozenset(),  # transformations need recomputation after reduction
        projection=new_proj,
        provenance=vs.provenance
        + (
            QueryTraceEntry(
                primitive="reduction",
                args={"relation": relation, "context": ec.regime},
                input_hash=vs.content_hash,
                output_hash=ViewState(
                    artifact_space=frozenset(class_artifacts),
                    transform_space=frozenset(),
                    projection=new_proj,
                ).content_hash,
                result=result,
            ),
        ),
    )

    return result, new_vs


# --- Composite query ---


def compose(
    vs: ViewState,
    ec: EvaluationContext,
    steps: list[tuple[str, dict]],
) -> tuple[QueryResult, ViewState]:
    """Execute a chain of primitives, threading ViewState through each step.

    Each step is (primitive_name, kwargs). Returns final result and ViewState.
    """
    current_vs = vs
    final_result = QueryResult()

    for primitive_name, kwargs in steps:
        if primitive_name == "projection":
            result, current_vs = projection(current_vs, ec, **kwargs)
        elif primitive_name == "traversal":
            result, current_vs = traversal(current_vs, ec, **kwargs)
        elif primitive_name == "reduction":
            result, current_vs = reduction(current_vs, ec, **kwargs)
        elif primitive_name == "identity":
            result, current_vs = identity(current_vs, ec)
        else:
            raise ValueError(f"Unknown primitive: {primitive_name}")
        final_result = result

    return final_result, current_vs
