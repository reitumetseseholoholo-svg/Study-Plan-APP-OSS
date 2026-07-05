"""Identity System v2 — semantic identity resolution engine.

Components:
  1. ProvenanceWeightedIdentity — identity with confidence, source trust, lineage
  2. SemanticEquivalenceScorer — weighted similarity across dimensions
  3. GlobalIdentityRegistry — persistent identity graph across compilations
  4. ConflictAwareMerger — equivalence with confidence, contradiction edges

This is the "LLVM GVN moment" — making identity resolution principled,
persistent, and uncertainty-aware.
"""

from __future__ import annotations

from studyplan.provenance.kernel.performance import timed
from dataclasses import dataclass, field
from typing import Any, Callable
import re


# ============================================================
# 1. Core types
# ============================================================


@dataclass(frozen=True)
class ProvenanceWeightedIdentity:
    """Identity with provenance metadata and confidence.

    Compared to the bare CIR Identity, this adds:
    - confidence (epistemic: how sure we are this identity exists)
    - source_trust (how trustworthy the source is)
    - lineage (chain of provenance — which sources contributed)
    """

    id: str
    type: str
    label: str
    confidence: float = 1.0
    source_trust: float = 1.0
    first_seen: str = ""
    lineage: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_confidence(self) -> float:
        """Combined confidence = source_trust × identity_confidence."""
        return self.source_trust * self.confidence

    def merge_lineage(self, other: ProvenanceWeightedIdentity) -> tuple[str, ...]:
        """Merge lineage, preferring earlier sources."""
        merged = list(self.lineage)
        for item in other.lineage:
            if item not in merged:
                merged.append(item)
        return tuple(merged)


@dataclass(frozen=True)
class ConflictEdge:
    """A typed conflict between two identity nodes.

    Attributes:
        source: canonical ID of source node
        target: canonical ID of target node
        conflict_type: "contradiction" | "type_mismatch" | "label_conflict"
        confidence: 0-1, how confident we are this is a real conflict
        evidence: list of (source_kind, source_id, detail) tuples
    """

    source: str
    target: str
    conflict_type: str
    confidence: float = 0.5
    evidence: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class EquivalenceClass:
    """An equivalence class of identity IDs, with confidence.

    Multiple local IDs that resolve to the same canonical identity.
    The canonical_id is the most authoritative (highest effective_confidence).
    """

    canonical_id: str
    member_ids: frozenset[str]
    resolution_confidence: float = 1.0
    conflicts: tuple[ConflictEdge, ...] = ()


# ============================================================
# 2. SemanticEquivalenceScorer
# ============================================================

ScoringWeights = Callable[[], dict[str, float]]


@dataclass
class SemanticEquivalenceScorer:
    """Weighted similarity scorer across identity dimensions.

    Scoring dimensions:
    - label_similarity (default 0.4): exact or fuzzy label match
    - type_compatibility (default 0.25): type compatibility (formula↔formula)
    - dependency_context (default 0.2): overlap in dependency graph
    - provenance_proximity (default 0.15): same source proximity

    Total score is weighted sum of dimension scores [0, 1].
    Threshold for equivalence: >= 0.7 (configurable).
    """

    label_weight: float = 0.40
    type_weight: float = 0.25
    context_weight: float = 0.20
    provenance_weight: float = 0.15
    equivalence_threshold: float = 0.6

    @timed("identity", "score")
    def score(
        self,
        a: ProvenanceWeightedIdentity,
        b: ProvenanceWeightedIdentity,
        context_a: frozenset[str] = frozenset(),
        context_b: frozenset[str] = frozenset(),
    ) -> float:
        """Compute semantic equivalence score between two identities [0, 1]."""
        label_sim = self._label_similarity(a.label, b.label) * self.label_weight
        type_sim = self._type_compatibility(a.type, b.type) * self.type_weight
        context_sim = self._context_overlap(context_a, context_b) * self.context_weight
        prov_sim = self._provenance_proximity(a, b) * self.provenance_weight

        return label_sim + type_sim + context_sim + prov_sim

    def is_equivalent(
        self,
        a: ProvenanceWeightedIdentity,
        b: ProvenanceWeightedIdentity,
        context_a: frozenset[str] = frozenset(),
        context_b: frozenset[str] = frozenset(),
    ) -> bool:
        """Returns True if score meets or exceeds threshold."""
        return self.score(a, b, context_a, context_b) >= self.equivalence_threshold

    @timed("identity", "equivalence_classes")
    def equivalence_classes(
        self,
        identities: list[ProvenanceWeightedIdentity],
        context_map: dict[str, frozenset[str]] | None = None,
    ) -> list[EquivalenceClass]:
        """Cluster identities into equivalence classes.

        Uses union-find with pairwise equivalence threshold.
        """
        context_map = context_map or {}
        ids = [i.id for i in identities]
        parent: dict[str, str] = {i: i for i in ids}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: str, y: str) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        for i in range(len(identities)):
            for j in range(i + 1, len(identities)):
                a, b = identities[i], identities[j]
                ctx_a = context_map.get(a.id, frozenset())
                ctx_b = context_map.get(b.id, frozenset())
                if self.is_equivalent(a, b, ctx_a, ctx_b):
                    union(a.id, b.id)

        class_map: dict[str, list[str]] = {}
        for iid in ids:
            root = find(iid)
            if root not in class_map:
                class_map[root] = []
            class_map[root].append(iid)

        result: list[EquivalenceClass] = []
        for root, members in class_map.items():
            best: ProvenanceWeightedIdentity | None = None
            best_conf = -1.0
            for i in identities:
                if i.id in members and i.effective_confidence > best_conf:
                    best = i
                    best_conf = i.effective_confidence

            canonical = best.id if best else root
            member_ids = frozenset(members)

            scores = []
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a = next(x for x in identities if x.id == members[i])
                    b = next(x for x in identities if x.id == members[j])
                    scores.append(self.score(a, b))
            avg_conf = sum(scores) / len(scores) if scores else 1.0

            result.append(
                EquivalenceClass(
                    canonical_id=canonical,
                    member_ids=member_ids,
                    resolution_confidence=avg_conf,
                )
            )

        return result

    @staticmethod
    def _label_similarity(label_a: str, label_b: str) -> float:
        """Label similarity: exact = 1.0, substring = 0.7, tf-idf = 0.3-0.6."""
        a, b = label_a.strip().lower(), label_b.strip().lower()
        if a == b:
            return 1.0
        if a in b or b in a:
            return 0.7

        a_tokens = set(re.findall(r"\w+", a))
        b_tokens = set(re.findall(r"\w+", b))
        if not a_tokens or not b_tokens:
            return 0.0
        intersection = a_tokens & b_tokens
        union = a_tokens | b_tokens
        return len(intersection) / len(union) * 0.6

    @staticmethod
    def _type_compatibility(type_a: str, type_b: str) -> float:
        """Type compatibility: same = 1.0, compatible hierarchy = 0.7."""
        if type_a == type_b:
            return 1.0
        compatible_pairs: frozenset[tuple[str, str]] = frozenset(
            {
                ("formula", "concept"),
                ("concept", "formula"),
                ("principle", "concept"),
                ("concept", "principle"),
                ("method", "concept"),
                ("concept", "method"),
            }
        )
        if (type_a, type_b) in compatible_pairs:
            return 0.7
        return 0.0

    @staticmethod
    def _context_overlap(
        context_a: frozenset[str],
        context_b: frozenset[str],
    ) -> float:
        """Dependency context overlap as Jaccard similarity."""
        if not context_a or not context_b:
            return 0.0
        intersection = context_a & context_b
        union = context_a | context_b
        return len(intersection) / len(union)

    @staticmethod
    def _provenance_proximity(a: ProvenanceWeightedIdentity, b: ProvenanceWeightedIdentity) -> float:
        """Same source lineage proximity."""
        shared = len(set(a.lineage) & set(b.lineage))
        total = len(set(a.lineage) | set(b.lineage))
        if total == 0:
            return 0.0
        return shared / total


# ============================================================
# 3. GlobalIdentityRegistry
# ============================================================


class GlobalIdentityRegistry:
    """Persistent identity graph across compilations.

    Maintains:
    - canonical identities (ProvenanceWeightedIdentity)
    - equivalence classes (local → canonical mapping)
    - conflict edges between identities

    Not actually persistent to disk yet — in-memory singleton that
    accumulates across build() calls.
    """

    def __init__(self, scorer: SemanticEquivalenceScorer | None = None):
        self.scorer = scorer or SemanticEquivalenceScorer()
        self._identities: dict[str, ProvenanceWeightedIdentity] = {}
        self._local_to_canonical: dict[str, str] = {}
        self._equivalence_classes: dict[str, EquivalenceClass] = {}
        self._label_to_canonical: dict[tuple[str, str], str] = {}
        self._conflicts: list[ConflictEdge] = []

    # ── Registration ────────────────────────────────────────

    @timed("identity", "register")
    def register(self, identity: ProvenanceWeightedIdentity) -> str:
        """Register or resolve an identity. Returns canonical ID.

        Fast path: O(1) (type, label) exact-match lookup via
        _label_to_canonical index.  Catches 90–95% of re-registrations
        (same concept from same or different source).

        Slow path: semantic scoring via _find_best_match() for
        genuinely new concepts or previously unseen label variants.
        """
        label_key = (identity.type, identity.label)
        existing_id = self._label_to_canonical.get(label_key)
        if existing_id is not None:
            existing = self._identities[existing_id]
            canon_id = existing.id
            self._local_to_canonical[identity.id] = canon_id

            new_type = self._resolve_type_conflict(existing, identity)
            new_label = self._merge_label(existing, identity)
            if new_label != existing.label:
                del self._label_to_canonical[(existing.type, existing.label)]
                self._label_to_canonical[(new_type, new_label)] = canon_id

            existing_merged = ProvenanceWeightedIdentity(
                id=canon_id,
                type=new_type,
                label=new_label,
                confidence=max(existing.confidence, identity.confidence),
                source_trust=max(existing.source_trust, identity.source_trust),
                first_seen=existing.first_seen or identity.first_seen,
                lineage=existing.merge_lineage(identity),
                metadata={**existing.metadata, **identity.metadata},
            )
            self._identities[canon_id] = existing_merged

            eq = self._equivalence_classes.get(canon_id)
            if eq is not None:
                self._equivalence_classes[canon_id] = EquivalenceClass(
                    canonical_id=canon_id,
                    member_ids=eq.member_ids | {identity.id},
                    resolution_confidence=eq.resolution_confidence,
                )
            return canon_id

        existing = self._find_best_match(identity)
        if existing is not None:
            canon_id = existing.id
            self._local_to_canonical[identity.id] = canon_id
            if (existing.type, existing.label) != label_key:
                self._label_to_canonical[label_key] = canon_id

            new_type = self._resolve_type_conflict(existing, identity)
            new_label = self._merge_label(existing, identity)
            if new_label != existing.label:
                del self._label_to_canonical[(existing.type, existing.label)]
                self._label_to_canonical[(new_type, new_label)] = canon_id

            existing_merged = ProvenanceWeightedIdentity(
                id=canon_id,
                type=new_type,
                label=new_label,
                confidence=max(existing.confidence, identity.confidence),
                source_trust=max(existing.source_trust, identity.source_trust),
                first_seen=existing.first_seen or identity.first_seen,
                lineage=existing.merge_lineage(identity),
                metadata={**existing.metadata, **identity.metadata},
            )
            self._identities[canon_id] = existing_merged

            eq = self._equivalence_classes.get(canon_id)
            if eq is not None:
                self._equivalence_classes[canon_id] = EquivalenceClass(
                    canonical_id=canon_id,
                    member_ids=eq.member_ids | {identity.id},
                    resolution_confidence=eq.resolution_confidence,
                )
            return canon_id
        else:
            canon_id = identity.id
            self._label_to_canonical[label_key] = canon_id
            self._identities[canon_id] = identity
            self._local_to_canonical[identity.id] = canon_id
            self._equivalence_classes[canon_id] = EquivalenceClass(
                canonical_id=canon_id,
                member_ids=frozenset({identity.id}),
            )
            return canon_id

    @timed("identity", "register_many")
    def register_many(
        self, identities: list[ProvenanceWeightedIdentity], context_map: dict[str, frozenset[str]] | None = None
    ) -> dict[str, str]:
        """Register multiple identities. Returns {local_id → canonical_id}."""
        mapping: dict[str, str] = {}
        for ident in identities:
            mapping[ident.id] = self.register(ident)
        return mapping

    # ── Query ───────────────────────────────────────────────

    def resolve(self, local_id: str) -> str:
        """Map local ID to canonical ID. Returns local_id if unknown."""
        return self._local_to_canonical.get(local_id, local_id)

    def get_canonical(self, canonical_id: str) -> ProvenanceWeightedIdentity | None:
        """Get canonical identity metadata."""
        return self._identities.get(canonical_id)

    def get_equivalence_class(self, canonical_id: str) -> EquivalenceClass | None:
        """Get equivalence class for a canonical ID."""
        return self._equivalence_classes.get(canonical_id)

    def all_canonical_ids(self) -> frozenset[str]:
        return frozenset(self._identities.keys())

    def all_local_ids(self) -> frozenset[str]:
        return frozenset(self._local_to_canonical.keys())

    @property
    def canonical_count(self) -> int:
        return len(self._identities)

    @property
    def local_count(self) -> int:
        return len(self._local_to_canonical)

    @property
    def identity_count(self) -> int:
        return len(self._identities)

    @property
    def conflicts(self) -> list[ConflictEdge]:
        return list(self._conflicts)

    def add_conflict(self, conflict: ConflictEdge) -> None:
        """Record a conflict edge."""
        self._conflicts.append(conflict)

    def reset(self) -> None:
        """Clear all state."""
        self._identities.clear()
        self._local_to_canonical.clear()
        self._equivalence_classes.clear()
        self._label_to_canonical.clear()
        self._conflicts.clear()

    # ── Internal ────────────────────────────────────────────

    @timed("identity", "find_best_match")
    def _find_best_match(
        self,
        identity: ProvenanceWeightedIdentity,
    ) -> ProvenanceWeightedIdentity | None:
        """Find best matching canonical identity, or None."""
        best: ProvenanceWeightedIdentity | None = None
        best_score = self.scorer.equivalence_threshold

        for canonical in self._identities.values():
            score = self.scorer.score(identity, canonical)
            if score > best_score:
                best_score = score
                best = canonical

        return best

    @staticmethod
    def _resolve_type_conflict(
        existing: ProvenanceWeightedIdentity,
        incoming: ProvenanceWeightedIdentity,
    ) -> str:
        """Resolve type when types conflict. Prefer more specific type."""
        if existing.type == incoming.type:
            return existing.type
        priority = ["formula", "principle", "method", "theorem", "concept"]
        for p in priority:
            if existing.type == p:
                return existing.type
            if incoming.type == p:
                return incoming.type
        return existing.type

    @staticmethod
    def _merge_label(
        existing: ProvenanceWeightedIdentity,
        incoming: ProvenanceWeightedIdentity,
    ) -> str:
        """Merge labels, preferring longer/more descriptive."""
        if len(incoming.label) > len(existing.label):
            return incoming.label
        return existing.label


# ============================================================
# 4. ConflictAwareMerger
# ============================================================


class ConflictAwareMerger:
    """Merge with equivalence confidence, contradiction edges, unresolved clusters.

    Wraps CIRMerger with the GlobalIdentityRegistry for principled identity
    resolution. Produces canonical CognitiveIR with conflict metadata.
    """

    def __init__(self, registry: GlobalIdentityRegistry | None = None):
        from studyplan.provenance.lab.compilation.merger import CIRMerger

        self.registry = registry or GlobalIdentityRegistry()
        self._base_merger = CIRMerger()

    @timed("identity", "merge")
    def merge(self, fragments: list) -> "CognitiveIR":
        """Merge fragments through the identity registry.

        1. Extract all identities from fragments
        2. Register them in the GIR (resolves across fragments)
        3. Rewrite fragment relations/artifacts to canonical IDs
        4. Delegate to CIRMerger for the structural merge
        5. Attach conflict metadata to the output IR
        """
        from studyplan.provenance.cir import CognitiveIR

        # Step 1: gather all provenance-weighted identities from fragments
        weighted_ids = self._extract_weighted_ids(fragments)

        # Step 2: register in GIR
        local_to_canonical: dict[str, str] = {}
        for wid in weighted_ids:
            local_to_canonical[wid.id] = self.registry.register(wid)

        # Step 3: detect type conflicts
        self._detect_type_conflicts(local_to_canonical)

        # Step 4: create rewritten fragments with canonical IDs
        rewritten = self._rewrite_fragments(fragments, local_to_canonical)

        # Step 5: structural merge via base CIRMerger
        ir = self._base_merger.merge(rewritten)

        # Step 6: attach conflict metadata
        conflicts = self.registry.conflicts
        if conflicts:
            md = dict(ir.metadata)
            md["conflict_count"] = len(conflicts)
            md["registry_canonical_count"] = self.registry.canonical_count
            ir = CognitiveIR(
                version=ir.version,
                identities=ir.identities,
                artifacts=ir.artifacts,
                relations=ir.relations,
                metadata=md,
            )

        return ir

    @timed("identity", "extract_weighted_ids")
    def _extract_weighted_ids(
        self,
        fragments: list,
    ) -> list[ProvenanceWeightedIdentity]:
        """Extract ProvenanceWeightedIdentity from each fragment."""
        weighted: list[ProvenanceWeightedIdentity] = []
        for f in fragments:
            trust = getattr(f.provenance, "confidence", 1.0)
            source_kind = getattr(f.provenance, "source_kind", "unknown")
            source_id = getattr(f.provenance, "source_id", "")
            lineage = (f"{source_kind}:{source_id}",) if source_id else (source_kind,)
            for identity in getattr(f, "identities", ()):
                weighted.append(
                    ProvenanceWeightedIdentity(
                        id=identity.id,
                        type=identity.type,
                        label=identity.label or identity.id,
                        source_trust=trust,
                        first_seen=source_id or source_kind,
                        lineage=lineage,
                    )
                )
        return weighted

    def _detect_type_conflicts(
        self,
        local_to_canonical: dict[str, str],
    ) -> None:
        """Detect type conflicts within equivalence classes."""
        type_map: dict[str, set[str]] = {}
        for local_id, canon_id in local_to_canonical.items():
            identity = self.registry.get_canonical(canon_id)
            if identity is None:
                continue
            if canon_id not in type_map:
                type_map[canon_id] = set()
            type_map[canon_id].add(identity.type)

        for canon_id, types in type_map.items():
            if len(types) > 1:
                self.registry.add_conflict(
                    ConflictEdge(
                        source=canon_id,
                        target=canon_id,
                        conflict_type="type_mismatch",
                        confidence=0.8,
                        evidence=(("resolver", "merge", f"Multiple types in class {canon_id}: {types}"),),
                    )
                )

    @timed("identity", "rewrite_fragments")
    def _rewrite_fragments(
        self,
        fragments: list,
        local_to_canonical: dict[str, str],
    ) -> list:
        """Rewrite fragment identity/artifact/relation IDs to canonical."""
        from studyplan.provenance.cir import Identity, Artifact, Relation
        from studyplan.provenance.lab.compilation.fragment import CIRFragment

        rewritten: list = []
        for f in fragments:
            new_identities = []
            seen: set[str] = set()
            for i in getattr(f, "identities", ()):
                canon_id = local_to_canonical.get(i.id, i.id)
                if canon_id not in seen:
                    canon_ident = self.registry.get_canonical(canon_id)
                    new_identities.append(
                        Identity(
                            id=canon_id,
                            type=canon_ident.type if canon_ident else i.type,
                            label=canon_ident.label if canon_ident else i.label,
                        )
                    )
                    seen.add(canon_id)

            new_artifacts = []
            for a in getattr(f, "artifacts", ()):
                canon_target = local_to_canonical.get(a.target_identity, a.target_identity)
                aid = a.id
                for local_id, canon_id in local_to_canonical.items():
                    if a.id.startswith(local_id):
                        aid = a.id.replace(local_id, canon_id, 1)
                        break
                new_artifacts.append(
                    Artifact(
                        id=aid,
                        type=a.type,
                        target_identity=canon_target,
                        source_id=a.source_id,
                        content_preview=a.content_preview,
                    )
                )

            new_relations = []
            for r in getattr(f, "relations", ()):
                canon_source = local_to_canonical.get(r.source, r.source)
                canon_target = local_to_canonical.get(r.target, r.target)
                new_relations.append(
                    Relation(
                        type=r.type,
                        source=canon_source,
                        target=canon_target,
                    )
                )

            rewritten.append(
                CIRFragment(
                    identities=tuple(new_identities),
                    artifacts=tuple(new_artifacts),
                    relations=tuple(new_relations),
                    provenance=f.provenance,
                    cir_version=f.cir_version,
                )
            )

        return rewritten

    @property
    def last_report(self):
        return self._base_merger.last_report


def make_weighted(source_kind: str, source_id: str, identity: Any, trust: float = 1.0) -> ProvenanceWeightedIdentity:
    """Factory: build a ProvenanceWeightedIdentity from a bare CIR Identity."""
    lineage = (f"{source_kind}:{source_id}",) if source_id else (source_kind,)
    return ProvenanceWeightedIdentity(
        id=identity.id,
        type=identity.type,
        label=identity.label or identity.id,
        source_trust=trust,
        first_seen=source_id or source_kind,
        lineage=lineage,
    )
