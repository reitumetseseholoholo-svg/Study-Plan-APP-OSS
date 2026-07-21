"""CIRMerger — cross-fragment merge with identity resolution and conflict handling.

Merges multiple CIRFragments into a single canonical CognitiveIR by:
1. Resolving identity equivalence classes across fragments (DSU)
2. Rewriting relation targets from local → canonical IDs
3. Deduplicating artifacts by (type, target_identity, content_preview)
4. Detecting and annotating contradictions
5. Running the unified pass pipeline
"""

from __future__ import annotations

from dataclasses import dataclass, field

from studyplan.provenance.cir import (
    CognitiveIR,
    Identity,
    Artifact,
    Relation,
    assert_valid_ir,
)
from studyplan.provenance.cir.passes import run_passes
from studyplan.provenance.lab.compilation.fragment import CIRFragment, FragmentProvenance
from studyplan.provenance.lab.compilation.resolver import IdentityResolver, LookalikeStrategy


@dataclass
class MergeReport:
    """Report produced by every merge operation.

    Tracks what was resolved, deduplicated, and what conflicts remain.
    """

    fragment_count: int = 0
    total_identities: int = 0
    total_artifacts: int = 0
    total_relations: int = 0
    identity_equivalence_classes: int = 0
    identity_remapped: int = 0
    artifacts_deduplicated: int = 0
    contradictions_detected: int = 0
    fragments: list[FragmentProvenance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class CIRMerger:
    """Merge multiple CIRFragments into a single canonical CognitiveIR.

    Usage::

        merger = CIRMerger()
        result = merger.merge([fragment_a, fragment_b])
        # result.ir is the canonical CognitiveIR
        # result.report has merge statistics
    """

    def __init__(self, strategy: LookalikeStrategy | None = None):
        self.strategy = strategy or LookalikeStrategy()
        self.resolver = IdentityResolver(self.strategy)

    def merge(self, fragments: list[CIRFragment]) -> CognitiveIR:
        """Merge fragments into canonical CognitiveIR."""
        self.resolver.reset()
        for f in fragments:
            self.resolver.ingest(f)

        mapping = self.resolver.resolve()
        equivalence_classes = self._count_classes(mapping)
        remapped = sum(1 for local, canon in mapping.items() if local != canon)

        all_ids: set[str] = set()
        merged_identities: list[Identity] = []
        for local_id in mapping:
            canon_id = mapping[local_id]
            ident = self.resolver._all_identities[local_id]
            if canon_id not in {i.id for i in merged_identities}:
                merged_identities.append(
                    Identity(
                        id=canon_id,
                        type=ident.type,
                        label=ident.label,
                    )
                )
            all_ids.add(canon_id)

        merged_artifacts: list[Artifact] = []
        artifact_keys: set[tuple[str, str, str]] = set()
        artifact_id_counter: dict[str, int] = {}
        for f in fragments:
            for a in f.artifacts:
                canon_target = mapping.get(a.target_identity, a.target_identity)
                key = (a.type, canon_target, a.content_preview or "")
                if key not in artifact_keys:
                    artifact_keys.add(key)
                    base_id = _remap_id(a.id, mapping)
                    if base_id in artifact_id_counter:
                        suffix = artifact_id_counter[base_id] + 1
                        artifact_id_counter[base_id] = suffix
                        final_id = f"{base_id}_{suffix}"
                    else:
                        artifact_id_counter[base_id] = 0
                        final_id = base_id
                    merged_artifacts.append(
                        Artifact(
                            id=final_id,
                            type=a.type,
                            target_identity=canon_target,
                            source_id=a.source_id,
                            content_preview=a.content_preview,
                        )
                    )

        merged_relations: list[Relation] = []
        relation_keys: set[tuple[str, str, str]] = set()
        for f in fragments:
            for r in f.relations:
                canon_source = mapping.get(r.source, r.source)
                canon_target = mapping.get(r.target, r.target)
                key = (r.type, canon_source, canon_target)
                if key in relation_keys:
                    continue
                relation_keys.add(key)

                if canon_source not in all_ids or canon_target not in all_ids:
                    continue

                merged_relations.append(
                    Relation(
                        type=r.type,
                        source=canon_source,
                        target=canon_target,
                    )
                )

        merged_artifacts, contra_count = self._detect_contradictions(
            merged_relations,
            merged_artifacts,
        )

        ir = CognitiveIR(
            identities=tuple(merged_identities),
            artifacts=tuple(merged_artifacts),
            relations=tuple(merged_relations),
            metadata={
                "merged": True,
                "fragment_count": len(fragments),
                "merger_version": "1.0",
            },
        )

        ir = run_passes(ir)
        assert_valid_ir(ir)

        total_art_in = sum(len(f.artifacts) for f in fragments)
        self._last_report = MergeReport(
            fragment_count=len(fragments),
            total_identities=len(merged_identities),
            total_artifacts=len(merged_artifacts),
            total_relations=len(merged_relations),
            identity_equivalence_classes=equivalence_classes,
            identity_remapped=remapped,
            artifacts_deduplicated=max(0, total_art_in - len(merged_artifacts)),
            contradictions_detected=contra_count,
            fragments=[f.provenance for f in fragments],
        )

        return ir

    @property
    def last_report(self) -> MergeReport | None:
        return getattr(self, "_last_report", None)

    @staticmethod
    def _count_classes(mapping: dict[str, str]) -> int:
        return len(set(mapping.values()))

    @staticmethod
    def _detect_contradictions(
        relations: list[Relation],
        artifacts: list[Artifact],
    ) -> tuple[list[Artifact], int]:
        """Annotate contradiction artifacts for each contradict relation."""
        contra_pairs: set[frozenset[str]] = set()
        for r in relations:
            if r.type == "contradicts":
                contra_pairs.add(frozenset([r.source, r.target]))

        contra_artifacts = list(artifacts)
        contra_count = 0
        for pair in contra_pairs:
            a, b = tuple(pair)
            contra_artifacts.append(
                Artifact(
                    id=f"contradiction.{a}.vs.{b}",
                    type="misconception_note",
                    target_identity=a,
                    content_preview=f"Contradiction between {a} and {b}",
                    source_id="merger",
                )
            )
            contra_count += 1

        return contra_artifacts, contra_count


def _remap_id(local_id: str, mapping: dict[str, str]) -> str:
    """Remap an artifact ID if it matches a mapped identity."""
    for old, new in mapping.items():
        if local_id.startswith(old):
            return local_id.replace(old, new, 1)
    return local_id
