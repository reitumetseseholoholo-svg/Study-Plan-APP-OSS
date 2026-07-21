"""CIR Compilation Runtime — multi-frontend compilation pipeline.

This is the LLVM-moment for the CIR platform.

Pipeline::

    Source → FrontendPlugin → CIRFragment → CIRMerger → CognitiveIR
                ↑               ↑               ↑
           parse/extract    fragment format   identity resolution
                                              + dedup + conflict handling

All knowledge sources (FM formulas, PDFs, notes, Q&A) must compile
through this pipeline. CIR is the system of record.
"""

from studyplan.provenance.lab.compilation.fragment import CIRFragment, FragmentProvenance
from studyplan.provenance.lab.compilation.plugin import FrontendPlugin
from studyplan.provenance.lab.compilation.resolver import IdentityResolver, LookalikeStrategy
from studyplan.provenance.lab.compilation.merger import CIRMerger, MergeReport
from studyplan.provenance.lab.compilation.orchestration import CIRBuilder
from studyplan.provenance.lab.compilation.fm_plugin import FMFormulaPlugin, FMKnowledgeBasePlugin
from studyplan.provenance.lab.compilation.notes_plugin import NotesFrontendPlugin, parse_notes, ParsedNoteBlock
from studyplan.provenance.lab.compilation.pdf_plugin import PDFFrontendPlugin, parse_pdf_chunks, PdfChunk
from studyplan.provenance.lab.compilation.identity_v2 import (
    ProvenanceWeightedIdentity,
    SemanticEquivalenceScorer,
    GlobalIdentityRegistry,
    ConflictAwareMerger,
    ConflictEdge,
    EquivalenceClass,
    make_weighted,
)

__all__ = [
    "CIRFragment",
    "FragmentProvenance",
    "FrontendPlugin",
    "IdentityResolver",
    "LookalikeStrategy",
    "CIRMerger",
    "MergeReport",
    "CIRBuilder",
    "FMFormulaPlugin",
    "FMKnowledgeBasePlugin",
    "NotesFrontendPlugin",
    "parse_notes",
    "ParsedNoteBlock",
    "PDFFrontendPlugin",
    "parse_pdf_chunks",
    "PdfChunk",
    "ProvenanceWeightedIdentity",
    "SemanticEquivalenceScorer",
    "GlobalIdentityRegistry",
    "ConflictAwareMerger",
    "ConflictEdge",
    "EquivalenceClass",
    "make_weighted",
]
