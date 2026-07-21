"""P1 — ArtifactStore Protocol (Phase II Construction Experiment)

Hypothesis
----------
ViewState is a complete snapshot — serialization captures all algebra-relevant
state. A persistent ArtifactStore can be a pure IO layer with zero kernel changes.

This is not a claim about *convenience*. It is a claim about *architectural
boundary*: the kernel's data model (ViewState, Artifact, Transformation) is
sufficiently self-contained that persistence is a mechanical translation to/from
bytes, not a kernel concern.

If true: the kernel has a clean architectural boundary. Storage is a decorator,
not an intrinsic capability.

If false: ViewState leaks implementation details. The kernel and storage layer
are more coupled than the ontology predicts.

Predictions
-----------
1. ViewState remains immutable — no mutation added to kernel types.
2. Algebra APIs unchanged — projection/traversal/reduction/compose signatures
   stay identical.
3. Cross-session queries work — save a ViewState, load in new process, answer
   the same query with identical content_hash.
4. Tutor code becomes simpler — does not rebuild domains from scratch.
5. No ontology changes — no new Artifact types, edge semantics, or types.

Falsification
-------------
The hypothesis is partially refuted if serialization requires:
- Custom JSON encoders with domain knowledge
- Schema versioning or migration
- Kernel type changes (new fields, serialization hooks, __getstate__/__setstate__)
- New kernel imports in the store layer

Any of these indicates the kernel data model is not a clean persistence boundary.

Design
------
The store is a directory of JSON files. Each ViewState is saved as one file
named by content_hash[0:16].

Interface:
    store = ArtifactStore(path="/tmp/cci_store")
    store.save(vs) -> str  (returns hash, used as filename)
    store.load(vs_hash) -> ViewState | None
    store.contains(vs_hash) -> bool

No in-memory cache (keep it simple). No indexing. No schema versioning.
If the data model needs to evolve, that's evidence against the hypothesis.

Experiment
----------
1. Build a ViewState from PG optimizer data.
2. Run content_hash on original.
3. Save to store.
4. Load from store in same process.
5. Verify content_hash matches.
6. Run projection + traversal queries on loaded ViewState.
7. Assert results match original.
8. Repeat with a second domain.
"""

from dataclasses import dataclass
from typing import Any
import json
import os

from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    Transformation,
    ProjectionRule,
    QueryTraceEntry,
    QueryResult,
)


# ============================================================
# Section A: The store itself (null hypothesis implementation)
# ============================================================
# If serialization requires anything beyond standard library + kernel types,
# the hypothesis is under threat. Track every deviation.


@dataclass
class ArtifactStore:
    """Minimal persistent store for ViewState data.

    Pure IO layer. Zero kernel imports beyond types.
    If this file needs to import from kernel primitives,
    the architectural boundary has been violated.
    """

    path: str = "/tmp/cci_artifact_store"

    def __post_init__(self):
        os.makedirs(self.path, exist_ok=True)

    def save(self, vs: ViewState) -> str:
        """Serialize ViewState to JSON. Returns content_hash as filename key."""
        key = vs.content_hash
        filepath = os.path.join(self.path, f"{key}.json")
        data = _viewstate_to_dict(vs)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=_json_fallback)
        return key

    def load(self, key: str) -> ViewState | None:
        """Deserialize ViewState from JSON by content hash key."""
        filepath = os.path.join(self.path, f"{key}.json")
        if not os.path.exists(filepath):
            return None
        with open(filepath) as f:
            data = json.load(f)
        return _dict_to_viewstate(data)

    def contains(self, key: str) -> bool:
        return os.path.exists(os.path.join(self.path, f"{key}.json"))


# ============================================================
# Section B: Serialization helpers
# ============================================================
# These MUST be pure data translation — no kernel imports, no domain logic,
# no schema awareness beyond the type definitions.


def _to_json_compat(obj: Any) -> Any:
    """Recursively convert an object to JSON-compatible form.

    Handles: dataclasses → dict, frozenset → list, tuple → list, dict → dict.
    Primitives (str, int, float, bool, None) pass through.
    No domain knowledge of what the types mean — purely structural.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (frozenset, tuple)):
        return [_to_json_compat(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_json_compat(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return {f: _to_json_compat(getattr(obj, f)) for f in obj.__dataclass_fields__}
    raise TypeError(f"Cannot serialize: {type(obj)}: {obj}")


def _json_fallback(obj: Any) -> Any:
    """json.dump default handler — delegates to recursive converter."""
    return _to_json_compat(obj)


def _viewstate_to_dict(vs: ViewState) -> dict:
    """Convert ViewState to JSON-compatible dict.

    Recursively translates all nested types (dataclasses, frozensets, tuples)
    into plain dicts/lists/primitives. No domain knowledge.
    """
    return _to_json_compat(vs)


def _dict_to_viewstate(data: dict) -> ViewState:
    """Reconstruct ViewState from dict.

    This is the ONLY function that needs to know about kernel type constructors.
    It is the inverse of _viewstate_to_dict + json serialization.

    Note: JSON converts tuples to lists. We must convert list→tuple for fields
    that must be hashable (metadata, constraints). This is a structural
    impedance match, not domain-specific logic.
    """
    return ViewState(
        artifact_space=frozenset(
            Artifact(
                id=a["id"],
                type=a["type"],
                target=a["target"],
                metadata=tuple(tuple(m) for m in a.get("metadata", [])),
            )
            for a in data.get("artifact_space", [])
        ),
        transform_space=frozenset(
            Transformation(
                id=t["id"],
                input_artifact_id=t["input_artifact_id"],
                output_artifact_id=t["output_artifact_id"],
                transformation_type=t["transformation_type"],
                rule_spec=t["rule_spec"],
                constraints=tuple(tuple(c) for c in t.get("constraints", [])),
            )
            for t in data.get("transform_space", [])
        ),
        projection=_reconstruct_projection(data.get("projection", {})),
        provenance=tuple(_reconstruct_trace_entry(e) for e in data.get("provenance", [])),
    )


def _reconstruct_projection(p: dict) -> ProjectionRule:
    return ProjectionRule(kind=p.get("kind", "identity"), params=p.get("params", {}))


def _reconstruct_trace_entry(e: dict) -> QueryTraceEntry:
    """Reconstruct a QueryTraceEntry, handling the optional QueryResult field."""
    result_data = e.get("result")
    result = None
    if result_data is not None:
        result = QueryResult(
            artifacts=frozenset(
                Artifact(
                    id=a["id"],
                    type=a["type"],
                    target=a["target"],
                    metadata=tuple(tuple(m) for m in a.get("metadata", [])),
                )
                for a in result_data.get("artifacts", [])
            ),
            transforms=frozenset(
                Transformation(
                    id=t["id"],
                    input_artifact_id=t["input_artifact_id"],
                    output_artifact_id=t["output_artifact_id"],
                    transformation_type=t["transformation_type"],
                    rule_spec=t["rule_spec"],
                    constraints=tuple(tuple(c) for c in t.get("constraints", [])),
                )
                for t in result_data.get("transforms", [])
            ),
            metadata=result_data.get("metadata", {}),
        )
    return QueryTraceEntry(
        primitive=e["primitive"],
        args=e.get("args", {}),
        input_hash=e["input_hash"],
        output_hash=e["output_hash"],
        result=result,
    )
