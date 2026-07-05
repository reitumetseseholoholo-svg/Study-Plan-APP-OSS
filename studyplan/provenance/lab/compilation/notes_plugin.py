"""NotesFrontendPlugin — parses structured text notes into CIR fragments.

Demonstrates the FrontendPlugin protocol for a non-FM source.
Each note block is a mini knowledge unit::

    # WACC
    type: formula
    description: Weighted Average Cost of Capital
    depends: CAPM
    depends: CostOfDebt
    param: E (equity_value)
    param: D (debt_value)

    # NPV
    type: formula
    description: Net Present Value
    depends: WACC
    param: r (discount_rate)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from studyplan.provenance.cir import Identity, Artifact, Relation
from studyplan.provenance.lab.compilation.plugin import FrontendPlugin

# Valid CIR identity/artifact/relation types
_IDENTITY_TYPES = frozenset({"concept", "formula", "principle", "method", "theorem"})
_ARTIFACT_TYPES = frozenset(
    {
        "definition",
        "example",
        "proof",
        "exam_question",
        "misconception_note",
        "explanation",
        "exercise",
    }
)


@dataclass
class ParsedNoteBlock:
    """One parsed note block (a single concept/formula)."""

    heading: str
    properties: dict[str, list[str]]


def parse_notes(text: str) -> list[ParsedNoteBlock]:
    """Parse structured text notes into blocks.

    Format::

        # ConceptName
        key: value
        key: value

    Multiple keys with same name become lists.
    """
    blocks: list[ParsedNoteBlock] = []
    current_heading = ""
    current_props: dict[str, list[str]] = {}

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Heading line
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            if current_heading:
                blocks.append(
                    ParsedNoteBlock(
                        heading=current_heading,
                        properties=dict(current_props),
                    )
                )
            current_heading = m.group(1).strip()
            current_props = {}
            continue
        # Key: value line
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*(.+)$", line)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            if key not in current_props:
                current_props[key] = []
            current_props[key].append(value)

    if current_heading:
        blocks.append(
            ParsedNoteBlock(
                heading=current_heading,
                properties=dict(current_props),
            )
        )

    return blocks


class NotesFrontendPlugin(FrontendPlugin):
    """FrontendPlugin that compiles structured text notes into CIR.

    Accepts plain text with the format::

        # ConceptName
        type: formula|concept|principle|method|theorem
        description: free text
        depends: DependencyName
        param: name (role)
    """

    @property
    def source_kind(self) -> str:
        return "notes"

    def parse(self, source: Any) -> list[ParsedNoteBlock]:
        if isinstance(source, str):
            return parse_notes(source)
        if isinstance(source, list):
            return source  # already parsed
        raise TypeError(f"NotesFrontendPlugin expects str or list[ParsedNoteBlock], got {type(source).__name__}")

    def extract_identities(self, parsed: list[ParsedNoteBlock]) -> list[Identity]:
        identities: list[Identity] = []
        seen: set[str] = set()

        for block in parsed:
            heading = block.heading
            props = block.properties
            itype = self._resolve_type(props.get("type", ["concept"])[0])

            if heading not in seen:
                identities.append(Identity(id=heading, type=itype, label=heading))
                seen.add(heading)

            for dep_key in ("depends", "prerequisite", "requires"):
                for dep in props.get(dep_key, []):
                    if dep not in seen:
                        id_type = "formula" if itype == "formula" else "concept"
                        identities.append(Identity(id=dep, type=id_type, label=dep))
                        seen.add(dep)

        return identities

    def extract_artifacts(self, parsed: list[ParsedNoteBlock]) -> list[Artifact]:
        artifacts: list[Artifact] = []
        seen: set[str] = set()

        for block in parsed:
            heading = block.heading
            props = block.properties

            # Description → definition artifact
            for desc in props.get("description", []):
                aid = f"{heading}.note.desc"
                if aid not in seen:
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="definition",
                            target_identity=heading,
                            content_preview=desc[:200],
                        )
                    )
                    seen.add(aid)

            # Params → explanation artifacts
            for param in props.get("param", []):
                aid = f"{heading}.note.param.{len(seen)}"
                if aid not in seen:
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="explanation",
                            target_identity=heading,
                            content_preview=param[:200],
                        )
                    )
                    seen.add(aid)

            # Examples → example artifacts
            for example in props.get("example", []):
                aid = f"{heading}.note.example.{len(seen)}"
                if aid not in seen:
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="example",
                            target_identity=heading,
                            content_preview=example[:200],
                        )
                    )
                    seen.add(aid)

            # Misconception notes
            for mis in props.get("misconception", []):
                aid = f"{heading}.note.mis.{len(seen)}"
                if aid not in seen:
                    artifacts.append(
                        Artifact(
                            id=aid,
                            type="misconception_note",
                            target_identity=heading,
                            content_preview=mis[:200],
                        )
                    )
                    seen.add(aid)

        return artifacts

    def extract_relations(self, parsed: list[ParsedNoteBlock]) -> list[Relation]:
        relations: list[Relation] = []
        seen: set[tuple[str, str, str]] = set()

        for block in parsed:
            heading = block.heading
            props = block.properties

            for dep_key in ("depends", "prerequisite", "requires"):
                for dep in props.get(dep_key, []):
                    key = ("assumes", heading, dep)
                    if key not in seen:
                        relations.append(Relation(type="assumes", source=heading, target=dep))
                        seen.add(key)

        return relations

    @staticmethod
    def _resolve_type(raw: str) -> str:
        raw_lower = raw.strip().lower()
        if raw_lower in _IDENTITY_TYPES:
            return raw_lower
        if raw_lower in ("concept", "topic", "idea", "notion"):
            return "concept"
        if raw_lower in ("formula", "equation", "expression"):
            return "formula"
        if raw_lower in ("principle", "rule", "law"):
            return "principle"
        if raw_lower in ("method", "technique", "approach"):
            return "method"
        if raw_lower in ("theorem", "lemma", "corollary"):
            return "theorem"
        return "concept"
