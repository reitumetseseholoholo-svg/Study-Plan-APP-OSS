from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal
import hashlib
import json


# --- Schema-level ontology (frozen) ---

ARTIFACT_TYPES = frozenset(
    {
        "ast_node",
        "file_pattern",
        "module_dependency",
        "call_graph_region",
        "type_hierarchy",
        "api_surface",
        "runtime_trace_event",
        "config_value",
        "control_flow_pattern",
        "data_flow_edge",
        "symbol_table_entry",
    }
)

EDGE_SEMANTICS_HIERARCHY = {
    "structural": frozenset({"import", "call", "parent_child", "data_flow"}),
    "transformational": frozenset(
        {
            "equivalence_mapping",
            "decision_mapping",
            "generative_mapping",
            "ordering_mapping",
        }
    ),
}

EQUIVALENCE_RELATIONS = frozenset(
    {
        "syntactic",
        "semantic_equivalence",
        "algorithmic",
        "observational",
    }
)

# EVALUATION_CONTEXTS removed — regimes are open-ended.
# Any string is valid; see PREDEFINED_CONTEXTS for documentation/examples.


# --- Core types ---


def _dict_to_frozentuples(d: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Convert a dict to a sorted tuple of (key, value) pairs for hashability."""
    return tuple(sorted((k, v) for k, v in d.items()))


@dataclass(frozen=True)
class Artifact:
    id: str
    type: str
    target: str
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.type not in ARTIFACT_TYPES:
            raise ValueError(f"Unknown artifact type: {self.type}")

    @classmethod
    def from_dict(cls, id: str, type: str, target: str, metadata: dict[str, Any] | None = None) -> "Artifact":
        return cls(id=id, type=type, target=target, metadata=_dict_to_frozentuples(metadata or {}))

    def metadata_dict(self) -> dict[str, Any]:
        return dict(self.metadata)


def _all_edge_types() -> set[str]:
    """Return the set of all valid edge semantics types (structural + transformational leaves)."""
    types: set[str] = set()
    for subtypes in EDGE_SEMANTICS_HIERARCHY.values():
        types.update(subtypes)
    return types


@dataclass(frozen=True)
class Transformation:
    id: str
    input_artifact_id: str
    output_artifact_id: str
    transformation_type: str
    rule_spec: str
    constraints: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self):
        valid_types = _all_edge_types()
        if self.transformation_type not in valid_types:
            raise ValueError(f"Unknown transformation type: {self.transformation_type}")


@dataclass(frozen=True)
class ProjectionRule:
    kind: Literal["identity", "filter", "trace", "collapse_by"]
    params: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        if self.kind == "identity":
            return "identity"
        parts = [self.kind]
        for k, v in self.params.items():
            parts.append(f"{k}={v}")
        return ":".join(parts)


@dataclass(frozen=True)
class EvaluationContext:
    regime: str
    constraints: tuple[str, ...] = field(default_factory=tuple)
    objective_function: str = ""
    allowed_transformations: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


PREDEFINED_CONTEXTS: dict[str, EvaluationContext] = {
    "default_optimizer": EvaluationContext(
        regime="default_optimizer",
        objective_function="minimize(total_cost)",
        allowed_transformations=("all",),
        description="Full optimizer — all rewrite rules permitted, cost-based selection",
    ),
    "fast_path": EvaluationContext(
        regime="fast_path",
        constraints=("memory_budget < 1MB",),
        objective_function="minimize(total_cost)",
        allowed_transformations=("hash_join", "nested_loop"),
        description="Constrained optimizer — limited join strategies under memory budget",
    ),
    "geqo_mode": EvaluationContext(
        regime="geqo_mode",
        constraints=("join_count > 12",),
        objective_function="minimize(search_time)",
        allowed_transformations=("genetic_algorithm_only",),
        description="Genetic query optimizer used for large join counts",
    ),
    # FM / domain-agnostic examples
    "tax_regime_standard": EvaluationContext(
        regime="tax_regime",
        constraints=("tax_deductible_interest", "Tc > 0"),
        description="Standard tax regime: interest tax-deductible, positive rate",
    ),
    "tax_regime_exempt": EvaluationContext(
        regime="tax_regime",
        constraints=("Tc = 0",),
        description="Tax-exempt regime: no corporate tax",
    ),
    "assumption_set_market_efficiency": EvaluationContext(
        regime="assumption_set",
        constraints=("market_efficiency", "rational_investors"),
        description="Standard FM assumptions for valuation",
    ),
}


# --- Query result ---


@dataclass(frozen=True)
class QueryResult:
    artifacts: frozenset[Artifact] = field(default_factory=frozenset)
    transforms: frozenset[Transformation] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.artifacts and not self.transforms


# --- ViewState ---


@dataclass(frozen=True)
class ViewState:
    artifact_space: frozenset[Artifact] = field(default_factory=frozenset)
    transform_space: frozenset[Transformation] = field(default_factory=frozenset)
    projection: ProjectionRule = field(default_factory=lambda: ProjectionRule("identity"))
    provenance: tuple[QueryTraceEntry, ...] = field(default_factory=tuple)

    def derive(
        self,
        new_artifacts: frozenset[Artifact] | None = None,
        new_transforms: frozenset[Transformation] | None = None,
        new_projection: ProjectionRule | None = None,
        entry: QueryTraceEntry | None = None,
    ) -> ViewState:
        return ViewState(
            artifact_space=new_artifacts if new_artifacts is not None else self.artifact_space,
            transform_space=new_transforms if new_transforms is not None else self.transform_space,
            projection=new_projection if new_projection is not None else self.projection,
            provenance=self.provenance + ((entry,) if entry else ()),
        )

    @property
    def content_hash(self) -> str:
        """Deterministic hash of ViewState content (not provenance)."""
        a_ids = sorted(a.id for a in self.artifact_space)
        t_ids = sorted(t.id for t in self.transform_space)
        raw = json.dumps(
            {
                "artifacts": a_ids,
                "transforms": t_ids,
                "projection": {"kind": self.projection.kind, "params": self.projection.params},
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# --- Provenance ---


@dataclass(frozen=True)
class QueryTraceEntry:
    primitive: str
    args: dict[str, Any]
    input_hash: str
    output_hash: str
    result: QueryResult | None = None

    def describe(self) -> str:
        args_summary = ", ".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.primitive}({args_summary})  [{self.input_hash} → {self.output_hash}]"
