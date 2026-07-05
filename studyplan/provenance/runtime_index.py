"""RuntimeIndex — prepared execution image derived from a compiled ViewState.

Essentialist Question:
    Is indexing a property of execution, or of the compiled representation?
Answer:
    Of the compiled representation. A RuntimeIndex is a pure derivation
    from an immutable ViewState — adjacency maps, closure tables, type
    lookups. It contains zero execution state (no traces, no debugger
    state, no query results). Therefore it is shareable across all
    execution consumers (Tutor, Lab, Debugger, Observatory).

Construction Experiment H-RT-01 (Jul 2026):
    Every immutable ViewState can be transformed into a reusable
    RuntimeIndex that contains all derived execution structures
    required by kernel primitives.

    Predictions:
    - Multiple ExecutionContexts share one RuntimeIndex.
    - Kernel primitives no longer derive graph structure.
    - All consumers (Debugger, Observatory, Lab, Tutor) use the
      same RuntimeIndex for the same ViewState.

    Falsification:
    - If different consumers require incompatible derived structures,
      RuntimeIndex is not the correct abstraction.
    - If RuntimeIndex requires mutable execution state, its boundary
      is incorrect.
    - If primitives still rebuild execution structures, the preparation
      layer is incomplete.

Architectural layer:
    ViewState (immutable, compiled)
        |  (build_runtime_index)
        v
    RuntimeIndex (immutable, prepared)
        |  (consumed by ExecutionContext, DebugExecutor, etc.)
        v
    Execution (live session, traces, results)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    collect_inherited_constraints,
)


# ============================================================
# Per-artifact derived data
# ============================================================


@dataclass(frozen=True)
class PerArtifactIndex:
    """All derived data for a single artifact.

    Built once during RuntimeIndex construction. All fields are
    derived purely from the ViewState graph structure — no
    execution state, no mutable references.
    """

    inherited: frozenset[tuple[str, str]] = frozenset()
    assumptions_sorted: tuple[str, ...] = ()
    consumes_sorted: tuple[str, ...] = ()
    base_prereqs: tuple[str, ...] = ()
    base_upstream: tuple[str, ...] = ()
    reachable: int = 0
    dep_path: tuple[str, ...] = ()


# ============================================================
# RuntimeIndex — the prepared execution image
# ============================================================


@dataclass(frozen=True)
class RuntimeIndex:
    """Prepared execution image derived from a compiled ViewState.

    Owns:
    - adj_forward:    output_artifact_id → set of input_artifact_ids
    - adj_reverse:    input_artifact_id → set of output_artifact_ids
    - consumes_map:   output_artifact_id → set of consumed artifact IDs
    - by_id:          artifact_id → PerArtifactIndex
    - vs_hash:        content_hash of the source ViewState

    Does not own:
    - Execution state (traces, snapshots, query results)
    - Debugger state (breakpoints, step controllers)
    - Live query results

    Immutable. Shareable across all execution consumers for the
    same ViewState.
    """

    adj_forward: dict[str, set[str]] = field(default_factory=dict)
    adj_reverse: dict[str, set[str]] = field(default_factory=dict)
    consumes_map: dict[str, set[str]] = field(default_factory=dict)
    edge_forward: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    edge_reverse: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    by_id: dict[str, PerArtifactIndex] = field(default_factory=dict)
    artifact_lookup: dict[str, Artifact] = field(default_factory=dict)
    type_lookup: dict[str, str] = field(default_factory=dict)
    vs_hash: str = ""

    @property
    def artifact_ids(self) -> frozenset[str]:
        return frozenset(self.by_id.keys())


# ============================================================
# Index builder — disposable one-shot construction
# ============================================================


def build_runtime_index(vs: ViewState) -> RuntimeIndex:
    """Build a RuntimeIndex from a compiled ViewState.

    The builder is disposable. The RuntimeIndex is persistent
    and shareable.
    """
    arts = {a.id: a for a in vs.artifact_space}

    # --- Adjacency maps ---
    adj_forward: dict[str, set[str]] = {}
    adj_reverse: dict[str, set[str]] = {}
    consumes_map: dict[str, set[str]] = {}
    # Per-edge-type adjacency for O(1) lookup in _bfs_shortest_path
    edge_forward: dict[str, dict[str, set[str]]] = {}
    edge_reverse: dict[str, dict[str, set[str]]] = {}
    for t in vs.transform_space:
        out_id = t.output_artifact_id
        in_id = t.input_artifact_id
        etype = t.transformation_type

        adj_forward.setdefault(out_id, set()).add(in_id)
        adj_reverse.setdefault(in_id, set()).add(out_id)

        ef = edge_forward.setdefault(etype, {})
        ef.setdefault(in_id, set()).add(out_id)
        er = edge_reverse.setdefault(etype, {})
        er.setdefault(out_id, set()).add(in_id)

        for ck, cv in t.constraints:
            if ck == "consumes":
                consumes_map.setdefault(out_id, set()).add(cv)
                adj_reverse.setdefault(cv, set()).add(out_id)
                ef.setdefault(cv, set()).add(out_id)
                er.setdefault(out_id, set()).add(cv)

    # --- Output map for dependency path ---
    output_map: dict[str, list[tuple[str, frozenset[tuple[str, str]]]]] = {}
    for t in vs.transform_space:
        output_map.setdefault(t.output_artifact_id, []).append((t.input_artifact_id, frozenset(t.constraints)))

    # --- Type lookup ---
    type_lookup: dict[str, str] = {}
    for a in vs.artifact_space:
        type_lookup[a.id] = a.type

    # --- Per-artifact computation ---
    by_id: dict[str, PerArtifactIndex] = {}
    all_transform_set: set = set(vs.transform_space)

    for aid in arts:
        inherited = collect_inherited_constraints(vs, aid)

        # Upstream BFS
        visited: set[str] = set()
        frontier: set[str] = {aid}
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            frontier.update(adj_forward.get(current, set()))
            frontier.update(consumes_map.get(current, set()))

        prereqs = sorted(a for a in visited if a in arts and arts[a].type == "config_value")
        ass_filtered = tuple(c[1] for c in sorted(inherited) if c[0] == "assumption")
        cons_filtered = tuple(c[1] for c in sorted(inherited) if c[0] == "consumes")

        by_id[aid] = PerArtifactIndex(
            inherited=frozenset(inherited),
            assumptions_sorted=ass_filtered,
            consumes_sorted=cons_filtered,
            base_prereqs=tuple(prereqs),
            base_upstream=tuple(sorted(visited)),
            reachable=len(visited),
            dep_path=(aid,),
        )

    # --- Dependency path computation ---
    config_values = frozenset(a.id for a in vs.artifact_space if a.type == "config_value")

    for aid in arts:
        if aid in config_values:
            by_id[aid] = _patch_dep_path(by_id[aid], (aid,))
            continue

        _visited: dict[str, str | None] = {aid: None}
        queue: list[str] = [aid]
        found_base: str | None = None
        while queue and found_base is None:
            current = queue.pop(0)
            if current in config_values:
                found_base = current
                break
            for inp_id, cons in output_map.get(current, []):
                if inp_id not in _visited:
                    _visited[inp_id] = current
                    queue.append(inp_id)
                for ck, cv in cons:
                    if ck == "consumes" and cv not in _visited:
                        _visited[cv] = current
                        queue.append(cv)

        if found_base is None:
            by_id[aid] = _patch_dep_path(by_id[aid], (aid,))
        else:
            path: list[str] = [found_base]
            cur = found_base
            while cur != aid:
                for t in vs.transform_space:
                    if (
                        t.input_artifact_id == cur or any(ck == "consumes" and cv == cur for ck, cv in t.constraints)
                    ) and t.output_artifact_id in _visited:
                        nxt = t.output_artifact_id
                        if nxt not in path:
                            path.append(nxt)
                            cur = nxt
                            break
                else:
                    break
            by_id[aid] = _patch_dep_path(by_id[aid], tuple(path))

    return RuntimeIndex(
        adj_forward=adj_forward,
        adj_reverse=adj_reverse,
        consumes_map=consumes_map,
        edge_forward=edge_forward,
        edge_reverse=edge_reverse,
        by_id=by_id,
        artifact_lookup=arts,
        type_lookup=type_lookup,
        vs_hash=vs.content_hash,
    )


def _patch_dep_path(idx: PerArtifactIndex, dep_path: tuple[str, ...]) -> PerArtifactIndex:
    """Return a copy of PerArtifactIndex with an updated dep_path."""
    return PerArtifactIndex(
        inherited=idx.inherited,
        assumptions_sorted=idx.assumptions_sorted,
        consumes_sorted=idx.consumes_sorted,
        base_prereqs=idx.base_prereqs,
        base_upstream=idx.base_upstream,
        reachable=idx.reachable,
        dep_path=dep_path,
    )
