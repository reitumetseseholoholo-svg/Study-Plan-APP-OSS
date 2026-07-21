"""Domain Compiler — Compiles ACCA FM topic specifications into CCI ViewStates.

Given a declarative topic description, emits only Artifacts + Transformations.
No kernel changes. No executable logic. Pure data compilation.

Hypothesis H-DC-01:
    A declarative Domain Compiler can compile an ACCA FM topic into CCI
    artifacts and transformations without requiring any kernel changes.

Usage:
    from studyplan.provenance.compiler import DomainCompiler, TopicSpec, ComputationStep

    spec = TopicSpec(id="CAPM", title="Capital Asset Pricing Model", ...)
    vs = DomainCompiler().compile(spec)

    # Or use one-shot:
    vs = DomainCompiler.compile_one(spec)
"""

from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.kernel import ViewState, Artifact, Transformation


# ============================================================
# Declarative topic specification format
# ============================================================


@dataclass
class ComputationStep:
    """A single computation in a topic's dependency DAG.

    Each step has exactly one primary input (input_artifact_id) and produces
    one output. Additional inputs are declared via 'consumes'.
    """

    id: str
    input_artifact_id: str
    output_artifact_id: str
    rule_spec: str
    transformation_type: str = "generative_mapping"
    consumes: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class TopicSpec:
    """Declarative specification for an ACCA FM topic.

    This is the Domain Specification — a pure data structure with no
    executable logic. The compiler translates this into CCI IR.
    """

    id: str
    title: str
    parameters: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    computations: tuple[ComputationStep, ...] = field(default_factory=tuple)
    outputs: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        assert self.id, "TopicSpec must have an id"
        assert self.parameters or self.computations, "TopicSpec must have parameters or computations"


# ============================================================
# Domain Compiler
# ============================================================


class DomainCompiler:
    """Compiles TopicSpec → ViewState.

    Responsibilities:
    - Translate parameters into config_value Artifacts
    - Translate computations into generative_mapping Transformations
    - Translate outputs into call_graph_region Artifacts
    - Encode assumptions as Transformation constraints
    - Encode multi-input as 'consumes' constraint entries
    - No kernel changes, no new types, no executable logic
    """

    def compile(self, spec: TopicSpec) -> ViewState:
        """Compile a topic specification into a ViewState.

        Returns: ViewState (artifact_space + transform_space)
        Guarantees: No new kernel types, no new edge semantics.
        """
        artifacts: list[Artifact] = []
        transforms: list[Transformation] = []

        # Phase 1: Parameter artifacts — always config_value
        for param in spec.parameters:
            artifacts.append(self._build_artifact(param, default_type="config_value"))

        # Phase 2: Computation steps (generative_mapping)
        for step in spec.computations:
            transforms.append(self._build_transform(step))

        # Phase 3: Output artifacts — always call_graph_region
        for output in spec.outputs:
            artifacts.append(self._build_artifact(output, default_type="call_graph_region"))

        return ViewState(
            artifact_space=frozenset(artifacts),
            transform_space=frozenset(transforms),
        )

    def _build_artifact(self, spec: dict[str, Any], default_type: str | None = None) -> Artifact:
        """Build an Artifact from a specification dict.

        spec must have: id, type, target
        spec may have: metadata (dict of key→value pairs)
        default_type: fallback when spec omits 'type' field.
        """
        meta_dict = spec.get("metadata", {})
        meta_pairs = tuple(sorted((k, v) for k, v in meta_dict.items()))
        artifact_type = spec.get("type")
        if artifact_type is None:
            artifact_type = default_type or self._infer_type(spec)
            if default_type is None:
                log_friction(
                    f"type inference for '{spec['id']}': inferred "
                    f"'{artifact_type}' from semantic_role="
                    f"'{meta_dict.get('semantic_role', '')}'"
                )
        return Artifact(
            id=spec["id"],
            type=artifact_type,
            target=spec.get("target", spec["id"]),
            metadata=meta_pairs,
        )

    def _infer_type(self, spec: dict[str, Any]) -> str:
        """Infer Artifact type from spec context.

        Rule: if semantic_role is Parameter-ish → config_value.
              Otherwise → call_graph_region.
        """
        meta = spec.get("metadata", {})
        role = meta.get("semantic_role", "")
        param_like_roles = {"Parameter", "CashFlow", "TaxRate", "CostOfEquity", "CostOfDebt", "CapitalStructure"}
        if role in param_like_roles:
            return "config_value"
        return "call_graph_region"

    def _build_transform(self, step: ComputationStep) -> Transformation:
        """Build a Transformation from a ComputationStep.

        Encodes assumptions and multi-input dependencies as constraints.
        Constraints are sorted for stable ordering across compilations.
        """
        constraints: list[tuple[str, str]] = []
        for c in step.consumes:
            constraints.append(("consumes", c))
        for a in step.assumptions:
            constraints.append(("assumption", a))
        if not step.assumptions:
            log_friction(
                f"transform '{step.id}' has zero assumptions — no preconditions documented for this computation"
            )
        return Transformation(
            id=step.id,
            input_artifact_id=step.input_artifact_id,
            output_artifact_id=step.output_artifact_id,
            transformation_type=step.transformation_type,
            rule_spec=step.rule_spec,
            constraints=tuple(sorted(constraints)),
        )

    @staticmethod
    def compile_one(spec: TopicSpec) -> ViewState:
        """One-shot convenience: create compiler, compile, return."""
        return DomainCompiler().compile(spec)


# ============================================================
# Friction log (recorded during encoding, not optimized away)
# ============================================================

FRICTION_LOG: list[str] = []


def log_friction(msg: str) -> None:
    FRICTION_LOG.append(msg)


def get_friction_log() -> list[str]:
    return list(FRICTION_LOG)


def clear_friction_log() -> None:
    FRICTION_LOG.clear()
