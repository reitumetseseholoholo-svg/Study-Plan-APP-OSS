from __future__ import annotations

from collections import defaultdict

from studyplan.provenance.kernel.performance import timed
from studyplan.provenance.cir.types import Identity, Artifact, Relation
from studyplan.provenance.cir.container import CognitiveIR


# ====================================================================
# IR Passes — each takes CognitiveIR and returns a new CognitiveIR
# ====================================================================


@timed("compiler_pass", "resolve_identity_equivalence")
def resolve_identity_equivalence(ir: CognitiveIR) -> CognitiveIR:
    """Resolve equivalent_to chains into canonical identity IDs.

    Merges identities connected by equivalent_to relations:
    - All references to the merged identity are updated to the canonical ID.
    - The canonical ID is the alphabetically first ID in each equivalence class.
    - Equivalent_to relations are removed after resolution.

    This pass MUST run before other normalizations.
    """
    parent: dict[str, str] = {}

    def _find(x: str) -> str:
        while x in parent and parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for r in ir.relations:
        if r.type == "equivalent_to":
            if r.source not in parent:
                parent[r.source] = r.source
            if r.target not in parent:
                parent[r.target] = r.target
            _union(r.source, r.target)

    if not parent:
        return CognitiveIR(
            version=ir.version,
            identities=ir.identities,
            artifacts=ir.artifacts,
            relations=ir.relations,
            metadata={**ir.metadata, "pass_resolve_identity_equivalence": True},
        )

    canonical: dict[str, str] = {}
    eq_classes: dict[str, list[str]] = defaultdict(list)
    for node in parent:
        root = _find(node)
        eq_classes[root].append(node)

    for root, members in eq_classes.items():
        canon = min(members)
        for m in members:
            canonical[m] = canon

    merged_ids = set(canonical.keys()) - {v for v in canonical.values()}

    def _remap_id(old_id: str) -> str:
        return canonical.get(old_id, old_id)

    new_identities: list[Identity] = []
    seen_canonical: set[str] = set()
    for i in ir.identities:
        cid = _remap_id(i.id)
        if cid in merged_ids:
            continue
        if i.id in canonical and canonical[i.id] != i.id:
            cid = canonical[i.id]
        if cid not in seen_canonical:
            new_identities.append(Identity(id=cid, type=i.type, label=i.label))
            seen_canonical.add(cid)

    new_artifacts: list[Artifact] = []
    for a in ir.artifacts:
        new_tid = _remap_id(a.target_identity)
        new_id = _remap_id(a.id)
        if new_id in merged_ids:
            continue
        new_artifacts.append(
            Artifact(
                id=new_id,
                type=a.type,
                target_identity=new_tid,
                source_id=a.source_id,
                content_preview=a.content_preview,
            )
        )

    new_relations: list[Relation] = []
    for r in ir.relations:
        if r.type == "equivalent_to":
            continue
        ns = _remap_id(r.source)
        nt = _remap_id(r.target)
        if ns == nt:
            continue
        if ns in merged_ids or nt in merged_ids:
            continue
        new_relations.append(Relation(type=r.type, source=ns, target=nt))

    return CognitiveIR(
        version=ir.version,
        identities=tuple(new_identities),
        artifacts=tuple(new_artifacts),
        relations=tuple(new_relations),
        metadata={**ir.metadata, "pass_resolve_identity_equivalence": True},
    )


@timed("compiler_pass", "collapse_duplicate_identities")
def collapse_duplicate_identities(ir: CognitiveIR) -> CognitiveIR:
    """Remove duplicate identities with identical (type, label) pairs.

    When multiple identities have the same type and label, keep the first
    occurrence and update all references to the removed IDs.
    """
    seen: dict[tuple[str, str], str] = {}
    id_map: dict[str, str] = {}

    new_identities: list[Identity] = []
    for i in ir.identities:
        key = (i.type, i.label.lower()) if i.label else None
        if key is not None and key in seen:
            id_map[i.id] = seen[key]
        else:
            if key is not None:
                seen[key] = i.id
            new_identities.append(i)

    metadata = {**ir.metadata, "pass_collapse_duplicate_identities": True}
    if not id_map:
        return CognitiveIR(
            version=ir.version,
            identities=ir.identities,
            artifacts=ir.artifacts,
            relations=ir.relations,
            metadata=metadata,
        )

    def _remap(old_id: str) -> str:
        return id_map.get(old_id, old_id)

    new_artifacts: list[Artifact] = []
    for a in ir.artifacts:
        new_tid = _remap(a.target_identity)
        new_id = _remap(a.id)
        new_artifacts.append(
            Artifact(
                id=new_id,
                type=a.type,
                target_identity=new_tid,
                source_id=a.source_id,
                content_preview=a.content_preview,
            )
        )

    new_relations: list[Relation] = []
    for r in ir.relations:
        ns = _remap(r.source)
        nt = _remap(r.target)
        if ns != nt:
            new_relations.append(Relation(type=r.type, source=ns, target=nt))

    return CognitiveIR(
        version=ir.version,
        identities=tuple(new_identities),
        artifacts=tuple(new_artifacts),
        relations=tuple(new_relations),
        metadata=metadata,
    )


@timed("compiler_pass", "normalize_artifact_links")
def normalize_artifact_links(ir: CognitiveIR) -> CognitiveIR:
    """Remove artifacts whose target_identity does not exist.

    This pass cleans up dangling references after identity resolution.
    """
    valid_ids = ir.identity_ids
    removed = 0
    new_artifacts: list[Artifact] = []
    for a in ir.artifacts:
        if a.target_identity in valid_ids:
            new_artifacts.append(a)
        else:
            removed += 1

    result = CognitiveIR(
        version=ir.version,
        identities=ir.identities,
        artifacts=tuple(new_artifacts),
        relations=ir.relations,
        metadata={
            **ir.metadata,
            "pass_normalize_artifact_links": True,
            "normalize_artifact_links_removed": removed,
        },
    )
    return result


@timed("compiler_pass", "detect_contradictions")
def detect_contradictions(ir: CognitiveIR) -> CognitiveIR:
    """Find contradictions and annotate them in metadata.

    Identifies contradicting relations between identities and returns
    a list of contradiction pairs in metadata.
    """
    contradictions: list[dict[str, str]] = []
    for r in ir.relations:
        if r.type == "contradicts":
            source_id = ir.get_identity(r.source)
            target_id = ir.get_identity(r.target)
            contradictions.append(
                {
                    "source": r.source,
                    "source_label": source_id.label if source_id else "",
                    "target": r.target,
                    "target_label": target_id.label if target_id else "",
                    "relation_type": r.type,
                }
            )

    return CognitiveIR(
        version=ir.version,
        identities=ir.identities,
        artifacts=ir.artifacts,
        relations=ir.relations,
        metadata={
            **ir.metadata,
            "pass_detect_contradictions": True,
            "contradictions": tuple(contradictions),
            "contradiction_count": len(contradictions),
        },
    )


# ====================================================================
# Pipeline — run all passes in canonical order
# ====================================================================


@timed("compiler_pass", "run_passes")
def run_passes(
    ir: CognitiveIR,
    passes: list[str] | None = None,
) -> CognitiveIR:
    """Run a pipeline of IR passes in order.

    Default passes (in recommended order):
      1. resolve_identity_equivalence
      2. collapse_duplicate_identities
      3. normalize_artifact_links
      4. detect_contradictions
    """
    pass_registry = {
        "resolve_identity_equivalence": resolve_identity_equivalence,
        "collapse_duplicate_identities": collapse_duplicate_identities,
        "normalize_artifact_links": normalize_artifact_links,
        "detect_contradictions": detect_contradictions,
    }

    if passes is None:
        passes = [
            "resolve_identity_equivalence",
            "collapse_duplicate_identities",
            "normalize_artifact_links",
            "detect_contradictions",
        ]

    current = ir
    for pass_name in passes:
        fn = pass_registry.get(pass_name)
        if fn is not None:
            current = fn(current)

    return current
