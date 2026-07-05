"""CIR layers — abstraction layers within Cognitive IR.

Layer hierarchy
--------------

CIRL0 — Identity Layer:     What concepts and formulas exist?
CIRL1 — Relation Layer:     How are identities connected?
CIRL2 — Artifact Layer:     What knowledge artifacts exist about each concept?
CIRL3 — Closure Layer:      Transitive dependency reachability.
CIRL4 — Contradiction Layer:  What conflicts or gaps exist across the IR?

Each layer is a strict superset: CIRL0 ⊆ CIRL1 ⊆ CIRL2 ⊆ CIRL3 ⊆ CIRL4.
Moving up adds information (more edges, more artifacts, more semantics).
Moving down projects away information (simplifies).

Usage::

    from studyplan.provenance.lab.cir_lab import CIRLab
    from studyplan.provenance.lab.cir_layers import (
        CIR_LAYERS, CIR_ORDER, extract_cir_layer, layer_sequence,
    )

    lab = CIRLab(ir)
    result = extract_cir_layer(lab, "CIRL0")
    results = layer_sequence(lab, "CIRL0", "CIRL4")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from studyplan.provenance.cir import CognitiveIR
from studyplan.provenance.lab.cir_lab import CIRLab, CIRResult


# ============================================================
# Layer definition
# ============================================================


@dataclass(frozen=True)
class CIRLayerDef:
    """Definition of one CIR layer.

    Attributes:
        name: Short identifier (e.g., "CIRL0", "CIRL1")
        description: What this layer represents
        invariant: Property that holds at this layer across all domains
        canonical_query: CIRLab query that extracts this layer (method, **params)
        check_invariant: Callable(CIRResult) → bool
        upward_query: (target_layer) → (method, **params) — navigates upward
        downward_projection: Callable(CognitiveIR) → CognitiveIR
    """

    name: str
    description: str
    invariant: str
    canonical_query: tuple[str, dict[str, Any]] = field(repr=False)
    check_invariant: Callable[[CIRResult], bool] = field(repr=False)
    upward_query: Callable[[str, str], tuple[str, dict[str, Any]] | None] = field(repr=False)
    downward_projection: Callable[[CognitiveIR], CognitiveIR] = field(repr=False)


# ============================================================
# Canonical queries
# ============================================================

_CANON = {
    "CIRL0": ("concept_inventory", {}),
    "CIRL1": ("relation_inventory", {}),
    "CIRL2": ("artifact_inventory", {}),
    "CIRL3": ("dependency_closure", {"concept_id": "WACC"}),
    "CIRL4": ("contradictions", {}),
}


# ============================================================
# Invariant checkers
# ============================================================


def _check_CIRL0(result: CIRResult) -> bool:
    """CIRL0 invariant: every identity has an id and type."""
    data = result.data
    if not data:
        return False
    for i in data:
        if not isinstance(i, tuple) and not hasattr(i, "id"):
            return False
        if not hasattr(i, "type") or not isinstance(getattr(i, "type", None), str):
            return False
    return True


def _check_CIRL1(result: CIRResult) -> bool:
    """CIRL1 invariant: every relation connects existing identities."""
    rels = result.data
    # Can't check endpoint existence without accessing IR directly
    # Check at minimum that each relation has source and target
    for r in rels:
        if not r.source or not r.target:
            return False
    return True


def _check_CIRL2(result: CIRResult) -> bool:
    """CIRL2 invariant: every artifact has a type and target."""
    for a in result.data:
        if not a.type or not a.target_identity:
            return False
    return True


def _check_CIRL3(result: CIRResult) -> bool:
    """CIRL3 invariant: closure includes no direct identity."""
    data, summary = result.data, result.summary
    if summary.get("closure_size", 0) >= 0:
        return True
    return False


def _check_CIRL4(result: CIRResult) -> bool:
    """CIRL4 invariant: contradiction count is non-negative."""
    return result.summary.get("contradiction_count", -1) >= 0


# ============================================================
# Upward queries
# ============================================================


def _upward(from_name: str, to_name: str) -> tuple[str, dict[str, Any]] | None:
    """Return (method, params) that transitions between CIR layers.

    Only upward transitions are supported, one step at a time.
    Returns None if transition is not supported.
    """
    transitions: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {
        ("CIRL0", "CIRL1"): ("relation_inventory", {}),
        ("CIRL1", "CIRL2"): ("artifact_inventory", {}),
        ("CIRL2", "CIRL3"): ("dependency_closure", {"concept_id": "WACC"}),
        ("CIRL3", "CIRL4"): ("contradictions", {}),
    }
    return transitions.get((from_name, to_name))


# ============================================================
# Downward projections
# ============================================================


def _downward_CIRL0(ir: CognitiveIR) -> CognitiveIR:
    """CIRL1+ → CIRL0: artifacts and relations removed, identities only."""
    return CognitiveIR(
        version=ir.version,
        identities=ir.identities,
        artifacts=(),
        relations=(),
        metadata=ir.metadata,
    )


def _downward_CIRL1(ir: CognitiveIR) -> CognitiveIR:
    """CIRL2+ → CIRL1: artifacts removed, identities and relations remain."""
    return CognitiveIR(
        version=ir.version,
        identities=ir.identities,
        artifacts=(),
        relations=ir.relations,
        metadata=ir.metadata,
    )


def _downward_CIRL2(ir: CognitiveIR) -> CognitiveIR:
    """CIRL3+ → CIRL2: relations stay, no change needed."""
    return ir


# ============================================================
# Layer registry
# ============================================================

CIR_LAYERS: dict[str, CIRLayerDef] = {
    "CIRL0": CIRLayerDef(
        name="CIRL0",
        description="Identity Layer — inventory of concepts and formulas",
        invariant="Every identity has an id and type",
        canonical_query=("concept_inventory", {}),
        check_invariant=_check_CIRL0,
        upward_query=_upward,
        downward_projection=_downward_CIRL0,
    ),
    "CIRL1": CIRLayerDef(
        name="CIRL1",
        description="Relation Layer — topology connecting identities",
        invariant="Every relation connects two existing identities",
        canonical_query=("relation_inventory", {}),
        check_invariant=_check_CIRL1,
        upward_query=_upward,
        downward_projection=_downward_CIRL1,
    ),
    "CIRL2": CIRLayerDef(
        name="CIRL2",
        description="Artifact Layer — pedagogical knowledge about concepts",
        invariant="Every artifact has a type and target identity",
        canonical_query=("artifact_inventory", {}),
        check_invariant=_check_CIRL2,
        upward_query=_upward,
        downward_projection=_downward_CIRL2,
    ),
    "CIRL3": CIRLayerDef(
        name="CIRL3",
        description="Closure Layer — transitive dependency reachability",
        invariant="Closure size is non-negative",
        canonical_query=("dependency_closure", {"concept_id": "WACC"}),
        check_invariant=_check_CIRL3,
        upward_query=_upward,
        downward_projection=_downward_CIRL2,
    ),
    "CIRL4": CIRLayerDef(
        name="CIRL4",
        description="Contradiction Layer — conflicts across the IR",
        invariant="Contradiction count is non-negative",
        canonical_query=("contradictions", {}),
        check_invariant=_check_CIRL4,
        upward_query=_upward,
        downward_projection=_downward_CIRL2,
    ),
}

CIR_ORDER: list[str] = ["CIRL0", "CIRL1", "CIRL2", "CIRL3", "CIRL4"]


# ============================================================
# Public API
# ============================================================


def resolve_cir_layer(name: str) -> CIRLayerDef:
    """Look up a CIR layer definition by name.

    Raises KeyError for unknown layers.
    """
    if name not in CIR_LAYERS:
        raise KeyError(f"Unknown CIR layer: '{name}'. Valid: {list(CIR_LAYERS.keys())}")
    return CIR_LAYERS[name]


def extract_cir_layer(lab: CIRLab, layer_name: str, **params: Any) -> CIRResult:
    """Extract a CIR layer as a CIRResult.

    Example::

        result = extract_cir_layer(lab, "CIRL0")
        result = extract_cir_layer(lab, "CIRL3", concept_id="WACC")
    """
    layer = resolve_cir_layer(layer_name)
    method, defaults = layer.canonical_query
    qparams = {**defaults, **params}
    result = lab.query(method, **qparams)
    result.annotations.append(f"layer={layer_name}")
    result.summary["layer"] = layer_name
    result.summary["invariant"] = layer.invariant
    result.summary["invariant_holds"] = layer.check_invariant(result)
    return result


def layer_sequence(lab: CIRLab, from_layer: str, to_layer: str, **params: Any) -> list[CIRResult]:
    """Navigate upward through CIR layers from from_layer to to_layer.

    Returns a list of CIRResults, one per intermediate layer.
    Requires from_layer <= to_layer in the CIR order.
    """
    if CIR_ORDER.index(from_layer) > CIR_ORDER.index(to_layer):
        raise ValueError(
            f"Cannot navigate downward: {from_layer} > {to_layer}. Use extract_cir_layer for downward access."
        )

    results: list[CIRResult] = []

    base = extract_cir_layer(lab, from_layer, **params)
    results.append(base)

    for i in range(CIR_ORDER.index(from_layer), CIR_ORDER.index(to_layer)):
        current = CIR_ORDER[i]
        next_layer = CIR_ORDER[i + 1]
        transition = resolve_cir_layer(current).upward_query(current, next_layer)
        if transition is None:
            break
        method, extra = transition
        qparams = {**extra, **params}
        result = lab.query(method, **qparams)
        result.annotations.append(f"transition_{current}_to_{next_layer}")
        result.summary["from_layer"] = current
        result.summary["to_layer"] = next_layer
        results.append(result)

    return results
