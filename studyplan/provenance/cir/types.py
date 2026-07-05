from __future__ import annotations

from dataclasses import dataclass

# ====================================================================
# CIR version — compact tuple (major, minor, patch)
# ====================================================================

CIRVersion = tuple[int, int, int]

CIR_CURRENT_VERSION: CIRVersion = (1, 0, 0)

# ====================================================================
# Valid type literals (schema-locked, not extensible per instance)
# ====================================================================

IDENTITY_TYPES: tuple[str, ...] = (
    "concept",
    "formula",
    "principle",
    "method",
    "theorem",
)

ARTIFACT_TYPES: tuple[str, ...] = (
    "definition",
    "example",
    "proof",
    "exam_question",
    "misconception_note",
    "explanation",
    "exercise",
)

RELATION_TYPES: tuple[str, ...] = (
    "produces",
    "assumes",
    "equivalent_to",
    "defines",
    "illustrates",
    "tests",
    "contradicts",
)


# ====================================================================
# Core CIR types — frozen, versioned
# ====================================================================


@dataclass(frozen=True)
class Identity:
    """A semantic node in the knowledge graph.

    Identities are concepts, formulas, principles, methods, or theorems.
    They have no executable semantics — they are labels for nodes.
    """

    id: str
    type: str  # one of IDENTITY_TYPES
    label: str = ""

    def __post_init__(self) -> None:
        if self.type not in IDENTITY_TYPES:
            raise ValueError(f"Invalid identity type: {self.type!r}. Must be one of {IDENTITY_TYPES}")


@dataclass(frozen=True)
class Artifact:
    """Knowledge about an identity.

    Artifacts are definitions, examples, proofs, exam questions, etc.
    They always reference a target identity and carry a source_id for provenance.
    """

    id: str
    type: str  # one of ARTIFACT_TYPES
    target_identity: str
    source_id: str = ""
    content_preview: str = ""

    def __post_init__(self) -> None:
        if self.type not in ARTIFACT_TYPES:
            raise ValueError(f"Invalid artifact type: {self.type!r}. Must be one of {ARTIFACT_TYPES}")


@dataclass(frozen=True)
class Relation:
    """A typed edge between two CIR nodes (identities or artifacts).

    The three identity→identity relationships are:
      - produces:  source identity produces target identity
      - assumes:   source identity depends on target identity
      - equivalent_to: source and target are semantically equivalent

    The artifact→identity relationships are:
      - defines:       artifact defines target identity
      - illustrates:   artifact illustrates target identity
      - tests:         artifact tests knowledge of target identity
      - contradicts:   artifact contradicts target identity
    """

    type: str  # one of RELATION_TYPES
    source: str
    target: str

    def __post_init__(self) -> None:
        if self.type not in RELATION_TYPES:
            raise ValueError(f"Invalid relation type: {self.type!r}. Must be one of {RELATION_TYPES}")
        if self.source == self.target:
            raise ValueError(f"Self-referencing relation: {self.source} → {self.target}")
