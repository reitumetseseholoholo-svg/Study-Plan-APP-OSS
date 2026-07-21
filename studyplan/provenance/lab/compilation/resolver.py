"""IdentityResolver — cross-source identity resolution.

Resolves identities across CIRFragment boundaries using:
1. Exact match (same ID → union)
2. Lookalike match (same label, different source → candidate union)
3. Semantic similarity (TF-IDF on labels + descriptions)

Uses a DSU (Union-Find) structure to track equivalence classes.
"""

from __future__ import annotations

from dataclasses import dataclass

from studyplan.provenance.cir import Identity
from studyplan.provenance.lab.compilation.fragment import CIRFragment


# ============================================================
# Lookalike strategy — controls how aggressive resolution is
# ============================================================


@dataclass(frozen=True)
class LookalikeStrategy:
    """Strategy for fuzzy identity resolution.

    Attributes:
        exact_match: Match on ID only (default True)
        label_match: Match on label text (default True)
        semantic_match: Use TF-IDF similarity on labels (default False)
        semantic_threshold: Similarity threshold for semantic match (0-1)
    """

    exact_match: bool = True
    label_match: bool = True
    semantic_match: bool = False
    semantic_threshold: float = 0.8


# ============================================================
# DSU-based identity resolution
# ============================================================


class IdentityResolver:
    """Resolve identities across fragments using DSU.

    Usage::

        resolver = IdentityResolver()
        resolver.ingest(fragment_a)
        resolver.ingest(fragment_b)
        mapping = resolver.resolve()
        # mapping: {local_id → canonical_id}
    """

    def __init__(self, strategy: LookalikeStrategy | None = None):
        self.strategy = strategy or LookalikeStrategy()
        self._fragments: list[CIRFragment] = []
        self._all_identities: dict[str, Identity] = {}

    def ingest(self, fragment: CIRFragment) -> None:
        """Add a fragment's identities to the resolver."""
        self._fragments.append(fragment)
        for identity in fragment.identities:
            if identity.id not in self._all_identities:
                self._all_identities[identity.id] = identity

    def reset(self) -> None:
        """Clear all ingested identities."""
        self._fragments.clear()
        self._all_identities.clear()

    @property
    def identity_count(self) -> int:
        return len(self._all_identities)

    def resolve(self) -> dict[str, str]:
        """Build mapping from local_id → canonical_id.

        Returns a dict where every identity ID maps to its canonical
        representative. Canonical IDs are the first-seen ID in each
        equivalence class.
        """
        ids = list(self._all_identities.keys())
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

        identities = self._all_identities

        # Phase 1: exact match on ID (trivial — IDs are unique by definition)
        # (DSU already has each ID mapped to itself)

        # Phase 2: exact cross-source match on label + type
        if self.strategy.label_match:
            seen: dict[tuple[str, str], str] = {}
            for iid in ids:
                ident = identities[iid]
                key = (ident.type, ident.label)
                if key in seen:
                    union(seen[key], iid)
                else:
                    seen[key] = iid

        # Phase 3: semantic similarity (TF-IDF on labels)
        if self.strategy.semantic_match and len(ids) >= 2:
            self._semantic_resolve(identities, parent)

        # Build output mapping
        mapping: dict[str, str] = {}
        for iid in ids:
            mapping[iid] = find(iid)

        return mapping

    def _semantic_resolve(
        self,
        identities: dict[str, Identity],
        parent: dict[str, str],
    ) -> None:
        """TF-IDF similarity on identity labels."""
        id_list = list(identities.keys())
        labels = [identities[i].label for i in id_list]

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            vec = TfidfVectorizer(stop_words="english").fit_transform(labels)
            sim = cosine_similarity(vec)

            threshold = self.strategy.semantic_threshold
            for i in range(len(id_list)):
                for j in range(i + 1, len(id_list)):
                    if sim[i, j] >= threshold:
                        self._union(parent, id_list[i], id_list[j])
        except ImportError:
            pass  # sklearn not available — skip semantic resolution

    @staticmethod
    def _union(parent: dict[str, str], x: str, y: str) -> None:
        rx, ry = x, y
        while parent[rx] != rx:
            parent[rx] = parent[parent[rx]]
            rx = parent[rx]
        while parent[ry] != ry:
            parent[ry] = parent[parent[ry]]
            ry = parent[ry]
        if rx != ry:
            parent[ry] = rx
