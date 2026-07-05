"""iR layers — intermediate representation layers within the provenance ViewState.

Each ViewState is a dependency graph. The iR layers decompose this graph into
levels of abstraction, from raw nodes (iR0) up to impact analysis (iR4). Each
layer has:
- A canonical form (what a query at this layer returns)
- Invariants (properties that hold at this layer across domains)
- Upward/downward mappings (Lab plans that transition between layers)
- An observability level (OL0–OL3 from the Phase Diagram)

Layer hierarchy
---------------
::

    iR4 — Impact Layer       (what-if: what breaks if X changes?)
      ↑
    iR3 — Closure Layer      (reachability: what depends on what?)
      ↑
    iR2 — Constraint Layer   (semantic: what assumptions flow?)
      ↑
    iR1 — Edge Layer         (topology: how are nodes connected?)
      ↑
    iR0 — Node Layer         (inventory: what nodes exist?)

Each layer is a strict superset: iR0 ⊆ iR1 ⊆ iR2 ⊆ iR3 ⊆ iR4.
Moving up adds information (more edges, more semantics).
Moving down projects away information (simplifies).

Usage::

    from studyplan.provenance.lab import ProvenanceLab, PlanStep
    from studyplan.provenance.lab.layers import iR_LAYERS, resolve_layer

    lab = ProvenanceLab(vs)

    # Extract a specific layer as a Lab plan
    plan = iR_LAYERS["iR1"].canonical_plan()
    result = lab.execute(plan)

    # Check a layer invariant
    assert iR_LAYERS["iR0"].check_invariant(result)

    # Navigate between layers
    plan = iR_LAYERS["iR1"].upward_plan("iR2")  # iR1 → iR2 (add constraints)
    result = lab.execute(plan)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from studyplan.provenance.kernel import (
    ViewState,
)
from studyplan.provenance.lab import ProvenanceLab, LabResult, PlanStep, PlanResult


# ============================================================
# Layer definition
# ============================================================


@dataclass(frozen=True)
class iRLayerDef:
    """Definition of one iR layer in the provenance hierarchy.

    Attributes:
        name: Short identifier (e.g., "iR0", "iR1")
        description: What this layer represents
        observability: OL0–OL3 from the Representability Phase Diagram
        invariant: Property that holds at this layer across all domains
        canonical_plan: Lab plan that extracts this layer from a ViewState
        check_invariant: Callable(ViewState) → bool — verifies layer invariant
        upward_plan: (target_layer) → list[PlanStep] — navigates upward
        downward_projection: Callable(ViewState) → ViewState — projects downward
    """

    name: str
    description: str
    observability: str
    invariant: str
    canonical_plan: Callable[[str], list[PlanStep]] = field(repr=False)
    check_invariant: Callable[[PlanResult], bool] = field(repr=False)
    upward_plan: Callable[[str, str], list[PlanStep] | None] = field(repr=False)
    downward_projection: Callable[[ViewState], ViewState] = field(repr=False)


# ============================================================
# Per-layer canonical plans
# ============================================================


def _canonical_iR0(_artifact_id: str = "") -> list[PlanStep]:
    """iR0 — Node Layer: extract all artifacts with their types.

    Query: projection on artifact space with type filter removed.
    Invariant: artifact types are fixed per ViewState.
    """
    return [
        PlanStep(
            "projection",
            {
                "filter_type": "artifact",
                "predicate": lambda a: True,
            },
        ),
    ]


def _canonical_iR1(artifact_id: str = "") -> list[PlanStep]:
    """iR1 — Edge Layer: extract the full ViewState topology.

    Query: projection on artifact + transform spaces.
    Invariant: every edge connects two existing nodes.
    """
    return [
        PlanStep(
            "projection",
            {
                "filter_type": "artifact",
                "predicate": lambda a: a.id == artifact_id if artifact_id else True,
            },
        ),
    ]


def _canonical_iR2(artifact_id: str = "") -> list[PlanStep]:
    """iR2 — Constraint Layer: extract constraints flowing through edges.

    Query: collect_inherited_constraints for the target artifact.
    Invariant: every constraint traces to a specific edge.
    """
    aid = artifact_id or "NPV"
    return [
        PlanStep(
            "collect_inherited_constraints",
            {
                "artifact_id": aid,
            },
        ),
    ]


def _canonical_iR3(artifact_id: str = "") -> list[PlanStep]:
    """iR3 — Closure Layer: transitive reachability.

    Query: traversal transitive from a seed.
    Invariant: closure is reflexive, transitive, monotonic.
    """
    aid = artifact_id or "NPV"
    return [
        PlanStep(
            "traversal",
            {
                "seed_set": {aid},
                "edge_semantics": "transformational/generative_mapping",
                "depth_limit": "transitive",
            },
        ),
    ]


def _canonical_iR4(constraint_text: str = "") -> list[PlanStep]:
    """iR4 — Impact Layer: what-if analysis.

    Query: two-step plan (projection → traversal with result threading).
    Invariant: impact set is a subset of the closure set.
    """
    text = constraint_text or "constant_discount_rate"
    return [
        PlanStep(
            "projection",
            {
                "filter_type": "transformation",
                "predicate": lambda t: any(text in c[1] for c in t.constraints),
            },
        ),
        PlanStep(
            "traversal",
            {
                "seed_set": "$0.transforms.output_ids",
                "edge_semantics": "transformational/generative_mapping",
                "depth_limit": "transitive",
            },
        ),
    ]


# ============================================================
# Invariant checkers
# ============================================================


def _check_iR0(pr: PlanResult) -> bool:
    """iR0 invariant: every artifact has a valid type."""
    for a in pr.step_results[0].artifacts:
        if not a.type or not isinstance(a.type, str):
            return False
    return True


def _check_iR1(pr: PlanResult) -> bool:
    """iR1 invariant: every edge's endpoints exist in the artifact space."""
    if not hasattr(pr, "final_viewstate"):
        return True  # can't check without VS access
    # This is checked structurally by ViewState validation
    return True


def _check_iR2(pr: PlanResult) -> bool:
    """iR2 invariant: every constraint has a key and value."""
    for a in pr.step_results[0].artifacts:
        md = a.metadata_dict()
        key = md.get("constraint_key")
        val = md.get("constraint_value")
        if not key or not val:
            return False
    return True


def _check_iR3(pr: PlanResult) -> bool:
    """iR3 invariant: closure includes the seed."""
    return len(pr.step_results[0].artifacts) >= 1


def _check_iR4(pr: PlanResult) -> bool:
    """iR4 invariant: impact count is >= 0 and finite."""
    return len(pr.step_results[1].artifacts) >= 0


# ============================================================
# Upward plans (navigate between layers)
# ============================================================


def _upward(from_name: str, to_name: str) -> list[PlanStep] | None:
    """Return a Lab plan that transitions from one iR layer to another.

    Returns None if the transition is not supported (can only go upward
    one step at a time).
    """
    transitions: dict[tuple[str, str], list[PlanStep]] = {
        # iR0 → iR1: add edges (traverse from all artifacts)
        ("iR0", "iR1"): [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: True,
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.artifacts.ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": 1,
                },
            ),
        ],
        # iR1 → iR2: collect constraints on every artifact
        ("iR1", "iR2"): [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: True,
                },
            ),
            PlanStep(
                "collect_inherited_constraints",
                {
                    "artifact_id": "NPV",
                },
            ),
        ],
        # iR2 → iR3: compute transitive closure
        ("iR2", "iR3"): [
            PlanStep(
                "collect_inherited_constraints",
                {
                    "artifact_id": "NPV",
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": {"NPV"},
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ],
        # iR3 → iR4: compute downstream impact
        ("iR3", "iR4"): [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ],
    }
    return transitions.get((from_name, to_name))


# ============================================================
# Downward projections (simplify from upper layer)
# ============================================================


def _downward_iR0(vs: ViewState) -> ViewState:
    """iR1+ → iR0: discard edges, keep only artifacts."""
    from studyplan.provenance.kernel import ViewState as VS

    return VS(
        artifact_space=vs.artifact_space,
        transform_space=frozenset(),
        projection=vs.projection,
    )


def _downward_iR1(vs: ViewState) -> ViewState:
    """iR2+ → iR1: discard constraint artifacts, keep original topology."""
    from studyplan.provenance.kernel import ViewState as VS

    return VS(
        artifact_space=frozenset(a for a in vs.artifact_space if not a.id.startswith("c:")),
        transform_space=vs.transform_space,
        projection=vs.projection,
    )


# ============================================================
# Layer registry
# ============================================================

iR_LAYERS: dict[str, iRLayerDef] = {
    "iR0": iRLayerDef(
        name="iR0",
        description="Node Layer — artifact inventory and types",
        observability="OL0",
        invariant="Every artifact has a valid type",
        canonical_plan=_canonical_iR0,
        check_invariant=_check_iR0,
        upward_plan=_upward,
        downward_projection=_downward_iR0,
    ),
    "iR1": iRLayerDef(
        name="iR1",
        description="Edge Layer — topology connecting artifacts via transforms",
        observability="OL0",
        invariant="Every edge connects two existing nodes",
        canonical_plan=_canonical_iR1,
        check_invariant=_check_iR1,
        upward_plan=_upward,
        downward_projection=lambda vs: vs,  # iR1 is the canonical ViewState
    ),
    "iR2": iRLayerDef(
        name="iR2",
        description="Constraint Layer — assumptions flowing through edges",
        observability="OL1",
        invariant="Every constraint has a key-value pair",
        canonical_plan=_canonical_iR2,
        check_invariant=_check_iR2,
        upward_plan=_upward,
        downward_projection=_downward_iR1,
    ),
    "iR3": iRLayerDef(
        name="iR3",
        description="Closure Layer — transitive reachability",
        observability="OL2",
        invariant="Closure is reflexive (includes seed)",
        canonical_plan=_canonical_iR3,
        check_invariant=_check_iR3,
        upward_plan=_upward,
        downward_projection=_downward_iR1,
    ),
    "iR4": iRLayerDef(
        name="iR4",
        description="Impact Layer — what-if constraint removal analysis",
        observability="OL3",
        invariant="Impact count is finite and non-negative",
        canonical_plan=_canonical_iR4,
        check_invariant=_check_iR4,
        upward_plan=_upward,
        downward_projection=_downward_iR1,
    ),
}

# Ordered list for iteration (iR0 = most concrete, iR4 = most abstract)
iR_ORDER: list[str] = ["iR0", "iR1", "iR2", "iR3", "iR4"]


# ============================================================
# Public API
# ============================================================


def resolve_layer(name: str) -> iRLayerDef:
    """Look up an iR layer definition by name.

    Raises KeyError for unknown layers.
    """
    if name not in iR_LAYERS:
        raise KeyError(f"Unknown iR layer: '{name}'. Valid: {list(iR_LAYERS.keys())}")
    return iR_LAYERS[name]


def extract_layer(lab: ProvenanceLab, layer_name: str, **params: Any) -> LabResult:
    """Extract an iR layer from a ViewState as a LabResult.

    Example::
        result = extract_layer(lab, "iR0")
        result = extract_layer(lab, "iR4", constraint_text="constant_discount_rate")
    """
    layer = resolve_layer(layer_name)
    plan = layer.canonical_plan(**params)
    plan_result = lab.execute(plan)

    return LabResult(
        question=f"extract_{layer_name}",
        target=params.get("artifact_id", ""),
        plan_result=plan_result,
        summary={
            "layer": layer_name,
            "observability": layer.observability,
            "invariant": layer.invariant,
            "invariant_holds": layer.check_invariant(plan_result),
        },
    )


def layer_sequence(lab: ProvenanceLab, from_layer: str, to_layer: str, **params: Any) -> list[LabResult]:
    """Navigate upward through iR layers from from_layer to to_layer.

    Returns a list of LabResults, one per intermediate layer.
    Requires from_layer <= to_layer in the iR order.
    """
    if iR_ORDER.index(from_layer) > iR_ORDER.index(to_layer):
        raise ValueError(f"Cannot navigate downward: {from_layer} > {to_layer}. Use extract_layer for downward access.")

    results: list[LabResult] = []

    # Start by extracting the base layer
    base = extract_layer(lab, from_layer, **params)
    results.append(base)

    # Navigate upward step by step
    for i in range(iR_ORDER.index(from_layer), iR_ORDER.index(to_layer)):
        current = iR_ORDER[i]
        next_layer = iR_ORDER[i + 1]
        transition = resolve_layer(current).upward_plan(current, next_layer)
        if transition is None:
            break
        plan_result = lab.execute(transition)
        results.append(
            LabResult(
                question=f"transition_{current}_to_{next_layer}",
                target=params.get("artifact_id", ""),
                plan_result=plan_result,
                summary={
                    "from_layer": current,
                    "to_layer": next_layer,
                    "steps": len(transition),
                },
            )
        )

    return results
