"""CIRFragment — partial CIR output from a single frontend.

A fragment is to CIR what an object file is to a linked executable.
Each frontend produces one fragment. The merger links them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.cir import Identity, Artifact, Relation, CIRVersion, CIR_CURRENT_VERSION


@dataclass(frozen=True)
class FragmentProvenance:
    """Provenance metadata attached to every fragment.

    Tracks where the fragment came from, confidence, and version.
    Used by the merger for conflict resolution and auditing.
    """

    source_kind: str  # "fm_formula", "pdf", "notes", "qa", etc.
    source_id: str  # unique identifier within that kind
    confidence: float = 1.0  # 0-1, used for conflict resolution
    version: str = "1.0"  # frontend version
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CIRFragment:
    """Partial CIR output from a single frontend.

    Each frontend produces one fragment per source unit.
    The merger combines fragments into a canonical CognitiveIR.

    A fragment is NOT required to be self-validating — references
    may cross fragment boundaries. The merger resolves these.
    """

    identities: tuple[Identity, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    relations: tuple[Relation, ...] = ()
    provenance: FragmentProvenance = field(
        default_factory=lambda: FragmentProvenance(
            source_kind="unknown",
            source_id="unknown",
        )
    )
    cir_version: CIRVersion = CIR_CURRENT_VERSION

    def identity_count(self) -> int:
        return len(self.identities)

    def artifact_count(self) -> int:
        return len(self.artifacts)

    def relation_count(self) -> int:
        return len(self.relations)

    @property
    def identity_ids(self) -> frozenset[str]:
        return frozenset(i.id for i in self.identities)

    @property
    def artifact_ids(self) -> frozenset[str]:
        return frozenset(a.id for a in self.artifacts)

    @property
    def all_ids(self) -> frozenset[str]:
        return self.identity_ids | self.artifact_ids
