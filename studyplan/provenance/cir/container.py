from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.cir.types import (
    CIRVersion,
    CIR_CURRENT_VERSION,
    Identity,
    Artifact,
    Relation,
)


@dataclass(frozen=True)
class CognitiveIR:
    """Canonical container for Cognitive IR data.

    All frontends compile into this representation.
    All backends consume this representation.

    The container is frozen — modifications require IR passes
    that produce new containers.
    """

    version: CIRVersion = CIR_CURRENT_VERSION
    identities: tuple[Identity, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    relations: tuple[Relation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def identity_ids(self) -> frozenset[str]:
        return frozenset(i.id for i in self.identities)

    @property
    def artifact_ids(self) -> frozenset[str]:
        return frozenset(a.id for a in self.artifacts)

    @property
    def all_ids(self) -> frozenset[str]:
        return self.identity_ids | self.artifact_ids

    def get_identity(self, id: str) -> Identity | None:
        for i in self.identities:
            if i.id == id:
                return i
        return None

    def get_artifact(self, id: str) -> Artifact | None:
        for a in self.artifacts:
            if a.id == id:
                return a
        return None

    def relations_for(self, node_id: str) -> list[Relation]:
        return [r for r in self.relations if r.source == node_id or r.target == node_id]

    def relations_by_type(self, rtype: str) -> list[Relation]:
        return [r for r in self.relations if r.type == rtype]

    def identities_by_type(self, itype: str) -> list[Identity]:
        return [i for i in self.identities if i.type == itype]

    def artifacts_by_type(self, atype: str) -> list[Artifact]:
        return [a for a in self.artifacts if a.type == atype]

    def artifacts_targeting(self, identity_id: str) -> list[Artifact]:
        return [a for a in self.artifacts if a.target_identity == identity_id]


# ====================================================================
# Validation — structural and referential integrity
# ====================================================================


@dataclass(frozen=True)
class IRValidationError:
    rule: str
    message: str
    node_id: str = ""


@dataclass(frozen=True)
class IRValidationResult:
    valid: bool
    errors: tuple[IRValidationError, ...] = ()
    warnings: tuple[IRValidationError, ...] = ()

    def __bool__(self) -> bool:
        return self.valid


def validate_ir(ir: CognitiveIR) -> IRValidationResult:
    """Validate structural and referential integrity of a CIR container.

    Rules:
    V1 — No duplicate identity IDs
    V2 — No duplicate artifact IDs
    V3 — All artifact target_identity references exist
    V4 — Relation source exists
    V5 — Relation target exists
    V6 — No self-referencing relations (enforced by Relation.__post_init__)
    V7 — Identity type is valid (enforced by Identity.__post_init__)
    V8 — Artifact type is valid (enforced by Artifact.__post_init__)
    V9 — Relation type is valid (enforced by Relation.__post_init__)
    V10 — Version is parseable
    V11 — No redundant equivalent_to cycles (warning)
    """
    errors: list[IRValidationError] = []
    warnings: list[IRValidationError] = []

    _check_version(ir.version, errors)

    identity_ids = ir.identity_ids
    artifact_ids = ir.artifact_ids
    all_ids = ir.all_ids

    seen_ids: set[str] = set()

    for i in ir.identities:
        if i.id in seen_ids:
            errors.append(IRValidationError("V1", f"Duplicate identity ID: {i.id}", i.id))
        seen_ids.add(i.id)

    for a in ir.artifacts:
        if a.id in seen_ids:
            errors.append(IRValidationError("V2", f"Duplicate artifact ID: {a.id}", a.id))
        seen_ids.add(a.id)

    for a in ir.artifacts:
        if a.target_identity not in identity_ids:
            errors.append(
                IRValidationError(
                    "V3",
                    f"Artifact {a.id} targets unknown identity: {a.target_identity}",
                    a.id,
                )
            )

    for r in ir.relations:
        if r.source not in all_ids:
            errors.append(IRValidationError("V4", f"Relation source not found: {r.source}", r.source))
        if r.target not in all_ids:
            errors.append(IRValidationError("V5", f"Relation target not found: {r.target}", r.target))

    eq_seen: set[tuple[str, str]] = set()
    for r in ir.relations:
        if r.type == "equivalent_to":
            pair = (r.source, r.target)
            reverse = (r.target, r.source)
            if pair in eq_seen or reverse in eq_seen:
                warnings.append(
                    IRValidationError(
                        "V11",
                        f"Redundant equivalent_to: {r.source} ~ {r.target}",
                        r.source,
                    )
                )
            eq_seen.add(pair)

    return IRValidationResult(
        valid=len(errors) == 0,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _check_version(version: CIRVersion, errors: list[IRValidationError]) -> None:
    if not isinstance(version, tuple) or len(version) != 3:
        errors.append(IRValidationError("V10", f"Invalid version format: {version}"))
        return
    if not all(isinstance(v, int) and v >= 0 for v in version):
        errors.append(IRValidationError("V10", f"Version components must be non-negative ints: {version}"))


def assert_valid_ir(ir: CognitiveIR) -> None:
    """Raise ValueError if IR is invalid."""
    result = validate_ir(ir)
    if not result.valid:
        msg = "; ".join(f"[{e.rule}] {e.message}" for e in result.errors)
        raise ValueError(f"CIR validation failed: {msg}")
