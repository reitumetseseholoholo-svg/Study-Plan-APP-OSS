"""CanonicalTraceReconstructor — deterministic causal graph from event provenance.

This module answers the central structural question::

    Is ExecutionTrace a *sufficient encoding* of a partial-order graph
    under a canonical reconstruction function?

It does NOT infer, interpolate, or interpret.  Every edge is derived from
explicit provenance fields (``state_hash_before`` / ``state_hash_after``)
stamped by the runtime at event-creation time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from studyplan.cci.event import ExecutionTrace


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ReconstructedGraph:
    """Structural graph reconstructed from an ExecutionTrace.

    ``temporal_edges`` — execution order (always present, linear).
    ``causal_edges`` — decision lineage derived from state-hash matching.
    ``branches`` — explicit divergence points (matched_condition).
    ``collapse_points`` — final label / result resolutions.
    ``decision_depth`` — maximum number of substeps across any transition;
        1 for trivial single-step processes, >1 for composite processes.
    """

    nodes: list[dict[str, Any]] = field(default_factory=list)
    temporal_edges: list[dict[str, Any]] = field(default_factory=list)
    causal_edges: list[dict[str, Any]] = field(default_factory=list)
    branches: list[dict[str, Any]] = field(default_factory=list)
    collapse_points: list[dict[str, Any]] = field(default_factory=list)
    decision_depth: int = 0


# ---------------------------------------------------------------------------
# Canonical reconstructor
# ---------------------------------------------------------------------------


class CanonicalTraceReconstructor:
    """Deterministic structural reconstruction from causal provenance.

    Rules (no heuristics):
        1. Every event → one node, identified by trace position + type.
        2. Temporal edge: event i-1 → event i (execution ordering).
        3. Causal edge: event A → event B iff
           ``A.state_hash_after == B.state_hash_before``.
        4. Branch: any event whose payload contains ``matched_condition``.
        5. Collapse: any terminate event or event whose payload contains
           ``final_label`` or ``result`` at termination time.
    """

    def _decision_depth(self, trace: ExecutionTrace) -> int:
        depth = 0
        for ev in trace.events:
            if ev.type != "step":
                continue
            d = (ev.payload.get("transition", {}) or {}).get("depth", 0)
            if isinstance(d, (int, float)):
                depth = max(depth, int(d))
        return depth

    def _process_event(
        self,
        event: Any,
        index: int,
        nodes: list[dict[str, Any]],
        hash_index: dict[str, list[str]],
        temporal_edges: list[dict[str, Any]],
        causal_edges: list[dict[str, Any]],
        branches: list[dict[str, Any]],
        collapse_points: list[dict[str, Any]],
    ) -> None:
        node_id = f"node_{index}_{event.type}"

        node: dict[str, Any] = {
            "id": node_id,
            "type": event.type,
            "payload": event.payload,
            "index": index,
            "transition_id": event.transition_id,
            "state_hash_before": event.state_hash_before,
            "state_hash_after": event.state_hash_after,
        }
        nodes.append(node)

        if index > 0:
            prev = nodes[index - 1]
            temporal_edges.append(
                {
                    "from": prev["id"],
                    "to": node_id,
                    "kind": "temporal",
                }
            )

        hb = event.state_hash_before
        if hb and hb not in ("init", "unhashable"):
            for cause_id in hash_index.get(hb, []):
                if cause_id != node_id:
                    causal_edges.append(
                        {
                            "from": cause_id,
                            "to": node_id,
                            "kind": "causal",
                            "reason": event.payload.get("matched_condition"),
                        }
                    )

        ha = event.state_hash_after
        if ha and ha not in ("unhashable",):
            hash_index.setdefault(ha, []).append(node_id)

        if "matched_condition" in event.payload:
            branches.append(
                {
                    "node": node_id,
                    "condition": event.payload.get("matched_condition"),
                    "alternatives": event.payload.get("alternatives", []),
                    "index": index,
                }
            )

        if event.type == "terminate" or "final_label" in event.payload:
            label = event.payload.get("final_label") or event.payload.get("result")
            collapse_points.append(
                {
                    "node": node_id,
                    "label": label,
                    "index": index,
                }
            )

    def reconstruct(self, trace: ExecutionTrace) -> ReconstructedGraph:
        nodes: list[dict[str, Any]] = []
        temporal_edges: list[dict[str, Any]] = []
        causal_edges: list[dict[str, Any]] = []
        branches: list[dict[str, Any]] = []
        collapse_points: list[dict[str, Any]] = []

        hash_index: dict[str, list[str]] = {}

        for i, event in enumerate(trace.events):
            self._process_event(event, i, nodes, hash_index, temporal_edges, causal_edges, branches, collapse_points)

        decision_depth = self._decision_depth(trace)

        return ReconstructedGraph(
            nodes=nodes,
            temporal_edges=temporal_edges,
            causal_edges=causal_edges,
            branches=branches,
            collapse_points=collapse_points,
            decision_depth=decision_depth,
        )


# ---------------------------------------------------------------------------
# Structural probes
# ---------------------------------------------------------------------------


def is_linearly_representable(graph: ReconstructedGraph) -> bool:
    """True iff the causal structure can be flattened into a total order.

    A topological sort over *causal* (not temporal) edges.  If every node
    can be ordered without violating causal dependencies, the graph is
    linearly representable — meaning execution-order reconstruction
    is sufficient to capture all decision structure.

    Use this as the core invariant probe for DAG non-collapsibility:
    if this returns ``True`` for a hierarchical process, the trace is
    *under-encoding* the decision topology.
    """
    deps: dict[str, set[str]] = {}
    for edge in graph.causal_edges:
        deps.setdefault(edge["to"], set()).add(edge["from"])

    visited: set[str] = set()
    ordering: list[str] = []

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        for dep in deps.get(node_id, []):
            visit(dep)
        visited.add(node_id)
        ordering.append(node_id)

    for n in graph.nodes:
        visit(n["id"])

    return len(ordering) == len(graph.nodes)


def _lists_match_by_key(
    a: list[dict[str, Any]],
    b: list[dict[str, Any]],
    key: str,
) -> bool:
    """True if all elements in a and b have equal values for *key*."""
    return all(n1[key] == n2[key] for n1, n2 in zip(a, b, strict=True))


def structurally_equivalent(g1: ReconstructedGraph, g2: ReconstructedGraph) -> bool:
    """Compare graph *topology only* — ignores payload values and state hashes.

    Two graphs are structurally equivalent iff they have identical:

    - number of nodes
    - event type sequence (ordered by trace position)
    - temporal edge count
    - causal edge count (with matching ``kind``)
    - branch count
    - collapse point count
    - decision depth (max substep count across any transition)

    This is intentionally *structural*, not semantic.  Payload values,
    state hashes, ``matched_condition`` strings, and labels are NOT
    compared.  The purpose is to detect whether different execution
    strategies collapse into the same graph *shape*.
    """
    if (
        len(g1.nodes) != len(g2.nodes)
        or len(g1.temporal_edges) != len(g2.temporal_edges)
        or len(g1.causal_edges) != len(g2.causal_edges)
        or len(g1.branches) != len(g2.branches)
        or len(g1.collapse_points) != len(g2.collapse_points)
        or g1.decision_depth != g2.decision_depth
    ):
        return False
    if not _lists_match_by_key(g1.nodes, g2.nodes, "type"):
        return False
    if not _lists_match_by_key(g1.causal_edges, g2.causal_edges, "kind"):
        return False
    return True
