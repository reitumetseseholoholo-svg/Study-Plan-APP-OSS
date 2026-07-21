"""CIR frontend compiler — multi-modality → CognitiveIR.

Each frontend compiler produces CIR from a different modality:
- FM formula frontend: FMFormula → CIR
- PDF frontend: PDF text chunks → CIR
- Notes frontend: structured text notes → CIR

All frontends produce valid, mergeable CIR containers.
"""

from __future__ import annotations

from typing import Any

from studyplan.provenance.cir import (
    Identity as CIRIdentity,
    Artifact as CIRArtifact,
    Relation as CIRRelation,
    CognitiveIR,
    assert_valid_ir,
)
from studyplan.provenance.knowledge_ir import (
    FMFormula,
    FMKnowledgeBase,
    PedagogicalArtifact,
    FMPedagogicalSet,
)
# PDFFrontendPlugin imported lazily inside compile_pdf_rag_to_cir
# to avoid circular import (fm_plugin.py imports from this module)


def compile_formula(formula: FMFormula) -> CognitiveIR:
    """Compile a single FMFormula into Cognitive IR.

    Produces:
    - Identity nodes: concept_id (type=formula), concept_id.concept (type=concept)
    - Artifact nodes: description, params, assumptions
    - Relation nodes: produces, assumes for dependencies
    """
    identities: list[CIRIdentity] = [
        CIRIdentity(id=formula.concept_id, type="formula", label=formula.label),
        CIRIdentity(
            id=f"{formula.concept_id}.concept",
            type="concept",
            label=f"{formula.label} concept",
        ),
    ]

    if formula.concept_id != formula.output_concept_id:
        identities.append(
            CIRIdentity(
                id=formula.output_concept_id,
                type="concept",
                label=f"{formula.label} result",
            )
        )

    seen_ids = {i.id for i in identities}

    def _ensure_identity(dep_id: str) -> None:
        if dep_id not in seen_ids:
            identities.append(CIRIdentity(id=dep_id, type="formula", label=dep_id))
            seen_ids.add(dep_id)

    artifacts: list[CIRArtifact] = []

    if formula.description:
        artifacts.append(
            CIRArtifact(
                id=f"{formula.concept_id}.desc",
                type="definition",
                target_identity=formula.concept_id,
                source_id="",
                content_preview=formula.description[:200],
            )
        )

    for i, param in enumerate(formula.params):
        artifacts.append(
            CIRArtifact(
                id=f"{formula.concept_id}.param.{param.name}",
                type="definition",
                target_identity=formula.concept_id,
                content_preview=f"{param.name}: {param.role}",
            )
        )

    for assump in formula.assumes:
        artifacts.append(
            CIRArtifact(
                id=f"{formula.concept_id}.assumption.{assump.condition}",
                type="definition",
                target_identity=formula.concept_id,
                content_preview=assump.condition,
            )
        )

    relations: list[CIRRelation] = []

    if formula.concept_id != formula.output_concept_id:
        relations.append(
            CIRRelation(
                type="produces",
                source=formula.concept_id,
                target=formula.output_concept_id,
            )
        )

    for dep in formula.dependencies:
        _ensure_identity(dep)
        relations.append(
            CIRRelation(
                type="assumes",
                source=formula.concept_id,
                target=dep,
            )
        )

    ir = CognitiveIR(
        identities=tuple(identities),
        artifacts=tuple(artifacts),
        relations=tuple(relations),
        metadata={
            "frontend": "fm_formula",
            "concept_id": formula.concept_id,
        },
    )

    assert_valid_ir(ir)
    return ir


def compile_knowledge_base(kb: FMKnowledgeBase) -> CognitiveIR:
    """Compile an entire FMKnowledgeBase into Cognitive IR.

    Merges all formulas into a single CIR container.
    """
    merged = CognitiveIR()
    for formula in kb.formulas.values():
        ir = compile_formula(formula)
        merged = _merge_ir(merged, ir)
    return merged


def compile_pedagogical_set(
    pset: FMPedagogicalSet,
    concept_id: str,
) -> CognitiveIR:
    """Compile a pedagogical set into CIR artifact nodes.

    Each pedagogical artifact becomes a CIR artifact linked to the
    target concept identity.
    """
    artifacts: list[CIRArtifact] = []
    relations: list[CIRRelation] = []

    kind_map = {
        "definitions": "definition",
        "formulas": "explanation",
        "worked_examples": "example",
        "misconceptions": "misconception_note",
        "exam_questions": "exam_question",
        "examiner_guidance": "explanation",
    }

    for field_name, cir_kind in kind_map.items():
        items: tuple[PedagogicalArtifact, ...] = getattr(pset, field_name, ())
        for pa in items:
            aid = pa.id or f"{concept_id}.{field_name}.{len(artifacts)}"
            artifacts.append(
                CIRArtifact(
                    id=aid,
                    type=cir_kind,
                    target_identity=concept_id,
                    source_id=pa.source_id,
                    content_preview=pa.content[:200] if pa.content else "",
                )
            )
            relations.append(
                CIRRelation(
                    type="illustrates",
                    source=aid,
                    target=concept_id,
                )
            )

    identities: list[CIRIdentity] = [
        CIRIdentity(id=concept_id, type="concept", label=concept_id),
    ]

    ir = CognitiveIR(
        identities=tuple(identities),
        artifacts=tuple(artifacts),
        relations=tuple(relations),
        metadata={"frontend": "pedagogical", "concept_id": concept_id},
    )

    assert_valid_ir(ir)
    return ir


def _merge_ir(a: CognitiveIR, b: CognitiveIR) -> CognitiveIR:
    seen_ids: set[str] = set(a.identity_ids | a.artifact_ids)
    identities = list(a.identities)
    for i in b.identities:
        if i.id not in seen_ids:
            identities.append(i)
            seen_ids.add(i.id)
    seen_art_ids: set[str] = set(a.artifact_ids)
    artifacts = list(a.artifacts)
    for art in b.artifacts:
        if art.id not in seen_art_ids:
            artifacts.append(art)
            seen_art_ids.add(art.id)
    return CognitiveIR(
        version=a.version,
        identities=tuple(identities),
        artifacts=tuple(artifacts),
        relations=a.relations + b.relations,
        metadata={**a.metadata, **b.metadata},
    )


# ── PDF RAG compilation ────────────────────────────────────


def compile_pdf_rag_to_cir(
    chunks: list[dict[str, Any]],
    source_id: str = "",
) -> CognitiveIR:
    """Compile PDF text chunks (from the RAG pipeline) into CIR.

    Args:
        chunks: list of {chunk_index, text} dicts from _load_ai_tutor_rag_doc
        source_id: optional provenance source identifier

    Returns:
        A CIR fragment containing identities, artifacts, and relations
        extracted from the PDF text via heuristic pattern matching.
    """
    # Lazy imports to avoid circular dependency (fm_plugin ⮕ cir_frontend)
    from studyplan.provenance.lab.compilation import CIRBuilder
    from studyplan.provenance.lab.compilation.pdf_plugin import PDFFrontendPlugin

    builder = CIRBuilder()
    builder.register_frontend("pdf", PDFFrontendPlugin())
    ir = builder.build(
        {"pdf": chunks},
        source_ids={"pdf": source_id} if source_id else None,
    )
    return ir


# ── Multi-source convenience ───────────────────────────────


def build_all_sources(
    sources: dict[str, Any],
    source_ids: dict[str, str] | None = None,
) -> CognitiveIR:
    """Build CIR from any combination of registered source frontends.

    Auto-registers all available frontends (FM, Notes, PDF) and compiles
    the provided sources into a single canonical CIR.

    Args:
        sources: {source_kind: source_data}
                 e.g. {"fm_knowledge_base": FMKnowledgeBase, "pdf": [...chunks]}
        source_ids: optional {source_kind: source_id} for provenance

    Returns:
        Canonical, validated, pass-optimized CognitiveIR.
    """
    from studyplan.provenance.lab.compilation import (
        CIRBuilder,
        FMKnowledgeBasePlugin,
        NotesFrontendPlugin,
    )
    from studyplan.provenance.lab.compilation.pdf_plugin import PDFFrontendPlugin

    builder = CIRBuilder()
    builder.register_frontend("fm_knowledge_base", FMKnowledgeBasePlugin())
    builder.register_frontend("notes", NotesFrontendPlugin())
    builder.register_frontend("pdf", PDFFrontendPlugin())
    return builder.build(sources, source_ids)
