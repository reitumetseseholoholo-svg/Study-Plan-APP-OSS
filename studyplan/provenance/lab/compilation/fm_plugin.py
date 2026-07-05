"""FMPlugin — FrontendPlugin for ACCA FM formulas.

Wraps the existing frontend compiler functions into the FrontendPlugin
protocol so the CIRBuilder can discover and invoke it.
"""

from __future__ import annotations

from typing import Any

from studyplan.provenance.cir import Identity, Artifact, Relation
from studyplan.provenance.knowledge_ir import FMFormula, FMKnowledgeBase
from studyplan.provenance.lab.compilation.plugin import FrontendPlugin
from studyplan.provenance.lab.compilation.fragment import CIRFragment, FragmentProvenance
from studyplan.provenance.lab.cir_frontend import (
    compile_formula,
    compile_knowledge_base,
    compile_pedagogical_set,
)


class FMFormulaPlugin(FrontendPlugin):
    """FrontendPlugin that compiles a single FMFormula into CIR."""

    @property
    def source_kind(self) -> str:
        return "fm_formula"

    def parse(self, source: Any) -> FMFormula:
        if isinstance(source, FMFormula):
            return source
        raise TypeError(f"FMFormulaPlugin expects FMFormula, got {type(source).__name__}")

    def extract_identities(self, parsed: FMFormula) -> list[Identity]:
        ir = compile_formula(parsed)
        return list(ir.identities)

    def extract_artifacts(self, parsed: FMFormula) -> list[Artifact]:
        ir = compile_formula(parsed)
        return list(ir.artifacts)

    def extract_relations(self, parsed: FMFormula) -> list[Relation]:
        ir = compile_formula(parsed)
        return list(ir.relations)


class FMKnowledgeBasePlugin(FrontendPlugin):
    """FrontendPlugin that compiles an entire FMKnowledgeBase into CIR."""

    @property
    def source_kind(self) -> str:
        return "fm_knowledge_base"

    def parse(self, source: Any) -> FMKnowledgeBase:
        if isinstance(source, FMKnowledgeBase):
            return source
        raise TypeError(f"FMKnowledgeBasePlugin expects FMKnowledgeBase, got {type(source).__name__}")

    def extract_identities(self, parsed: FMKnowledgeBase) -> list[Identity]:
        return list(compile_knowledge_base(parsed).identities)

    def extract_artifacts(self, parsed: FMKnowledgeBase) -> list[Artifact]:
        return list(compile_knowledge_base(parsed).artifacts)

    def extract_relations(self, parsed: FMKnowledgeBase) -> list[Relation]:
        return list(compile_knowledge_base(parsed).relations)

    def compile_to_cir(self, source: Any, source_id: str = "") -> CIRFragment:
        kb = self.parse(source)

        merged = compile_knowledge_base(kb)

        for cid, pset in kb.pedagogical.items():
            ped_ir = compile_pedagogical_set(pset, cid)
            from studyplan.provenance.lab.cir_frontend import _merge_ir

            merged = _merge_ir(merged, ped_ir)

        return CIRFragment(
            identities=merged.identities,
            artifacts=merged.artifacts,
            relations=merged.relations,
            provenance=FragmentProvenance(
                source_kind=self.source_kind,
                source_id=source_id,
            ),
        )
