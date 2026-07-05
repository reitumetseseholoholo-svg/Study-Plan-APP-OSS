from studyplan.provenance.cir.types import (
    CIRVersion,
    CIR_CURRENT_VERSION,
    IDENTITY_TYPES,
    ARTIFACT_TYPES,
    RELATION_TYPES,
    Identity,
    Artifact,
    Relation,
)
from studyplan.provenance.cir.container import (
    CognitiveIR,
    validate_ir,
    assert_valid_ir,
    IRValidationError,
    IRValidationResult,
)
from studyplan.provenance.cir.passes import (
    resolve_identity_equivalence,
    collapse_duplicate_identities,
    normalize_artifact_links,
    detect_contradictions,
    run_passes,
)

__all__ = [
    "CIRVersion",
    "CIR_CURRENT_VERSION",
    "IDENTITY_TYPES",
    "ARTIFACT_TYPES",
    "RELATION_TYPES",
    "Identity",
    "Artifact",
    "Relation",
    "CognitiveIR",
    "validate_ir",
    "assert_valid_ir",
    "IRValidationError",
    "IRValidationResult",
    "resolve_identity_equivalence",
    "collapse_duplicate_identities",
    "normalize_artifact_links",
    "detect_contradictions",
    "run_passes",
]
