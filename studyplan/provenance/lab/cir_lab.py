"""CIRLab — unified Lab API for Cognitive IR queries.

Mirrors ProvenanceLab but wraps CognitiveIR instead of ViewState.
Identical pattern: execute → ask → query, plus layer extraction.

Usage::

    from studyplan.provenance.lab.cir_lab import CIRLab
    from studyplan.provenance.cir import CognitiveIR

    lab = CIRLab(ir)

    # Raw plan-style query
    result = lab.query("concept_dependencies", concept_id="WACC")

    # Named template
    result = lab.ask("assumptions_impacting", concept_id="WACC")

    # Layer extraction
    from studyplan.provenance.lab.cir_layers import extract_cir_layer
    result = extract_cir_layer(lab, "CIRL0")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from studyplan.provenance.cir import CognitiveIR, Identity, Artifact, Relation


# ============================================================
# CIRResult
# ============================================================


@dataclass
class CIRResult:
    """Result of a CIRLab query — wraps query output with metadata."""

    question: str
    target: str
    data: Any
    summary: dict[str, Any] = field(default_factory=dict)
    annotations: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"CIRResult(question='{self.question}', target='{self.target}')"


# ============================================================
# CIR query templates
# ============================================================


class CIRQueryTemplates:
    """Reusable CIR query templates.

    Each template is a static method that takes (ir, **params)
    and returns (data, summary_dict).
    """

    @staticmethod
    def concept_dependencies(
        ir: CognitiveIR,
        concept_id: str,
    ) -> tuple[list[str], dict[str, Any]]:
        """Find all direct dependencies of a concept."""
        deps = []
        for r in ir.relations:
            if r.type == "assumes" and r.source == concept_id:
                deps.append(r.target)
        return deps, {
            "concept_id": concept_id,
            "dependency_count": len(deps),
            "dependencies": sorted(deps),
        }

    @staticmethod
    def dependent_concepts(
        ir: CognitiveIR,
        concept_id: str,
    ) -> tuple[list[str], dict[str, Any]]:
        """Find all concepts that depend on a given concept."""
        dependents = []
        for r in ir.relations:
            if r.type == "assumes" and r.target == concept_id:
                dependents.append(r.source)
        return dependents, {
            "concept_id": concept_id,
            "dependent_count": len(dependents),
            "dependents": sorted(dependents),
        }

    @staticmethod
    def artifact_coverage(
        ir: CognitiveIR,
        concept_id: str,
    ) -> tuple[list[Artifact], dict[str, Any]]:
        """Find all pedagogical artifacts targeting a concept."""
        artifacts = list(ir.artifacts_targeting(concept_id))
        types = frozenset(a.type for a in artifacts)
        return artifacts, {
            "concept_id": concept_id,
            "artifact_count": len(artifacts),
            "artifact_types": sorted(types),
        }

    @staticmethod
    def dependency_closure(
        ir: CognitiveIR,
        concept_id: str,
    ) -> tuple[frozenset[str], dict[str, Any]]:
        """Transitive closure via assumes relations (BFS)."""
        seen: set[str] = set()
        queue = [concept_id]
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            for r in ir.relations:
                if r.type == "assumes" and r.source == current and r.target not in seen:
                    queue.append(r.target)
        closure = frozenset(seen - {concept_id})
        return closure, {
            "concept_id": concept_id,
            "closure_size": len(closure),
            "closure": sorted(closure),
        }

    @staticmethod
    def dependent_closure(
        ir: CognitiveIR,
        concept_id: str,
    ) -> tuple[frozenset[str], dict[str, Any]]:
        """Transitive dependents via assumes relations (reverse BFS)."""
        seen: set[str] = set()
        queue = [concept_id]
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            for r in ir.relations:
                if r.type == "assumes" and r.target == current and r.source not in seen:
                    queue.append(r.source)
        closure = frozenset(seen - {concept_id})
        return closure, {
            "concept_id": concept_id,
            "dependent_closure_size": len(closure),
            "dependent_closure": sorted(closure),
        }

    @staticmethod
    def contradictions(
        ir: CognitiveIR,
    ) -> tuple[list[tuple[str, str, str]], dict[str, Any]]:
        """Find all contradictions in the IR.

        Returns list of (source_id, target_id, metadata).
        """
        results: list[tuple[str, str, str]] = []
        for r in ir.relations:
            if r.type == "contradicts":
                md = ""
                if r.metadata:
                    import json

                    try:
                        md = json.dumps(r.metadata, sort_keys=True)
                    except Exception:
                        md = str(r.metadata)
                results.append((r.source, r.target, md))

        md_items = [a for a in results if a[2]]
        return results, {
            "contradiction_count": len(results),
            "with_metadata": len(md_items),
        }

    @staticmethod
    def concept_inventory(
        ir: CognitiveIR,
    ) -> tuple[list[Identity], dict[str, Any]]:
        """List all identity nodes."""
        ids = list(ir.identities)
        types = frozenset(i.type for i in ids)
        return ids, {
            "identity_count": len(ids),
            "identity_types": sorted(types),
        }

    @staticmethod
    def relation_inventory(
        ir: CognitiveIR,
    ) -> tuple[list[Relation], dict[str, Any]]:
        """List all relations."""
        rels = list(ir.relations)
        types = frozenset(r.type for r in rels)
        return rels, {
            "relation_count": len(rels),
            "relation_types": sorted(types),
        }

    @staticmethod
    def artifact_inventory(
        ir: CognitiveIR,
    ) -> tuple[list[Artifact], dict[str, Any]]:
        """List all artifact nodes."""
        arts = list(ir.artifacts)
        types = frozenset(a.type for a in arts)
        return arts, {
            "artifact_count": len(arts),
            "artifact_types": sorted(types),
        }


# ============================================================
# CIRLab
# ============================================================


class CIRLab:
    """Unified Lab API for Cognitive IR queries.

    Three ways to query:
    1. ``query(method, **params)`` — pass-through to named CIR template
    2. ``ask(question, **params)`` — same as query (alias for consistency)
    3. ``execute(fn, **params)`` — execute an arbitrary callable over the IR

    The templates mirror ProvenanceLab's query templates but operate
    on CognitiveIR instead of ViewState.
    """

    def __init__(self, ir: CognitiveIR):
        self.ir = ir
        self.templates = CIRQueryTemplates()

    def query(self, method: str, **params: Any) -> CIRResult:
        """Run a named CIR query template.

        Supported methods: concept_dependencies, dependent_concepts,
        artifact_coverage, dependency_closure, dependent_closure,
        contradictions, concept_inventory, relation_inventory,
        artifact_inventory.
        """
        template_map: dict[str, Callable[..., tuple[Any, dict[str, Any]]]] = {
            "concept_dependencies": self.templates.concept_dependencies,
            "dependent_concepts": self.templates.dependent_concepts,
            "artifact_coverage": self.templates.artifact_coverage,
            "dependency_closure": self.templates.dependency_closure,
            "dependent_closure": self.templates.dependent_closure,
            "contradictions": self.templates.contradictions,
            "concept_inventory": self.templates.concept_inventory,
            "relation_inventory": self.templates.relation_inventory,
            "artifact_inventory": self.templates.artifact_inventory,
        }
        fn = template_map.get(method)
        if fn is None:
            valid = sorted(template_map.keys())
            raise ValueError(f"Unknown CIR query: '{method}'. Valid: {valid}")
        data, summary = fn(self.ir, **params)
        target = params.get("concept_id", "") or params.get("artifact_id", "") or ""
        return CIRResult(question=method, target=target, data=data, summary=summary)

    def ask(self, question: str, **params: Any) -> CIRResult:
        """Alias for query — same interface as ProvenanceLab.ask()."""
        return self.query(question, **params)

    def execute(self, fn: Callable[[CognitiveIR], Any], **params: Any) -> CIRResult:
        """Execute an arbitrary callable over the IR."""
        data = fn(self.ir, **params) if params else fn(self.ir)
        return CIRResult(
            question="custom",
            target="",
            data=data,
            summary={"custom_fn": fn.__name__ if hasattr(fn, "__name__") else "lambda"},
        )
