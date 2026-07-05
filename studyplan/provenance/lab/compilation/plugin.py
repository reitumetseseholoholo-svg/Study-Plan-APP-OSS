"""FrontendPlugin protocol — contract for all CIR frontends.

Every knowledge source (FM formula, PDF, notes, Q&A) must implement
this interface. The CIRBuilder orchestrator discovers and invokes
plugins through this protocol.

A frontend is a compiler from a source format to CIRFragment.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from studyplan.provenance.cir import Identity, Artifact, Relation
from studyplan.provenance.lab.compilation.fragment import CIRFragment, FragmentProvenance


class FrontendPlugin(ABC):
    """Contract for all CIR frontends.

    Subclasses must implement:
    - ``source_kind`` — unique identifier (e.g., "fm_formula")
    - ``parse()`` — parse source into an intermediate form
    - ``extract_identities()`` — identities from parsed form
    - ``extract_artifacts()`` — artifacts from parsed form
    - ``extract_relations()`` — relations from parsed form

    The default ``compile_to_cir()`` calls these in sequence.
    """

    @property
    @abstractmethod
    def source_kind(self) -> str:
        """Unique identifier for this frontend type."""
        ...

    @abstractmethod
    def parse(self, source: Any) -> Any:
        """Parse raw source into an intermediate representation.

        Returns a parsed structure that the extract_* methods consume.
        """
        ...

    @abstractmethod
    def extract_identities(self, parsed: Any) -> list[Identity]:
        """Extract identity nodes from parsed source."""
        ...

    @abstractmethod
    def extract_artifacts(self, parsed: Any) -> list[Artifact]:
        """Extract artifact nodes from parsed source."""
        ...

    @abstractmethod
    def extract_relations(self, parsed: Any) -> list[Relation]:
        """Extract relation edges from parsed source."""
        ...

    def compile_to_cir(self, source: Any, source_id: str = "") -> CIRFragment:
        """Compile source into a CIRFragment.

        Default implementation calls parse → extract_* in sequence.
        Override for custom compilation logic.
        """
        parsed = self.parse(source)
        identities = self.extract_identities(parsed)
        artifacts = self.extract_artifacts(parsed)
        relations = self.extract_relations(parsed)

        return CIRFragment(
            identities=tuple(identities),
            artifacts=tuple(artifacts),
            relations=tuple(relations),
            provenance=FragmentProvenance(
                source_kind=self.source_kind,
                source_id=source_id,
            ),
        )

    def __repr__(self) -> str:
        return f"FrontendPlugin('{self.source_kind}')"
