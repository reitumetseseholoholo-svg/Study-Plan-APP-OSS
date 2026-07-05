"""Knowledge IR — structured domain representation.

Not a flat graph. The graph is DERIVED from structured types.

Two node kinds (the user's insight):
  - Identity: a concept (WACC, CAPM, NPV)
  - Artifact: information about a concept

But the KNOWLEDGE IR is organized by:
  Chapter → LearningObjective → Formula (executable)
                                  → PedagogicalSet (teachable)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


BloomLevel = Literal["remember", "understand", "apply", "analyze", "evaluate"]
Difficulty = Literal["easy", "medium", "hard"]
SourceKind = Literal["study_text", "examiner_report", "past_paper", "formulae_sheet", "revision_kit"]
ParamKind = Literal["value", "percent"]


# ====================================================================
# Sources (first-class, not strings)
# ====================================================================


@dataclass(frozen=True)
class FMSource:
    id: str
    title: str
    kind: SourceKind
    authority: float = 0.5  # 0-1, used for ranking evidence


# ====================================================================
# Formulas (the executable layer)
# ====================================================================


@dataclass(frozen=True)
class FormulaParam:
    name: str
    kind: ParamKind = "value"
    role: str = ""  # semantic role, e.g. "discount_rate", "initial_investment"


@dataclass(frozen=True)
class Assumption:
    condition: str  # e.g. "constant_discount_rate"
    description: str  # e.g. "discount rate is constant across all periods"


@dataclass(frozen=True)
class FMFormula:
    """One formula in the domain. Self-contained, structured, compilable."""

    concept_id: str
    label: str
    description: str
    expression: str
    params: tuple[FormulaParam, ...]
    output_concept_id: str  # what identity this produces
    assumes: tuple[Assumption, ...] = ()
    dependencies: tuple[str, ...] = ()  # prerequisite concept_ids
    diagnostic_tags: tuple[str, ...] = ()
    centrality: float = 0.5
    source_ids: tuple[str, ...] = ()


# ====================================================================
# Pedagogical artifacts (the teachable layer)
# ====================================================================


@dataclass(frozen=True)
class PedagogicalArtifact:
    """A piece of teaching content about one concept."""

    id: str
    kind: str  # "definition" | "worked_example" | "misconception" | "exam_question" | "examiner_guidance"
    content: str
    source_id: str = ""
    bloom_level: BloomLevel = "understand"
    difficulty: Difficulty = "medium"


@dataclass(frozen=True)
class FMPedagogicalSet:
    """All teaching content for one concept, grouped for easy access."""

    concept_id: str
    definitions: tuple[PedagogicalArtifact, ...] = ()
    formulas: tuple[PedagogicalArtifact, ...] = ()
    worked_examples: tuple[PedagogicalArtifact, ...] = ()
    misconceptions: tuple[PedagogicalArtifact, ...] = ()
    exam_questions: tuple[PedagogicalArtifact, ...] = ()
    examiner_guidance: tuple[PedagogicalArtifact, ...] = ()


# ====================================================================
# Learning objectives
# ====================================================================


@dataclass(frozen=True)
class LearningObjective:
    id: str
    description: str
    bloom_level: BloomLevel = "apply"
    target_concept_ids: tuple[str, ...] = ()


# ====================================================================
# Chapter — top-level structure
# ====================================================================


@dataclass(frozen=True)
class FMChapter:
    id: str
    title: str
    learning_objectives: tuple[LearningObjective, ...] = ()


# ====================================================================
# FM Knowledge Base — structured container, NOT a flat graph
# ====================================================================


@dataclass(frozen=True)
class FMKnowledgeBase:
    """Canonical Knowledge IR for ACCA FM.

    This is the compiler frontend's output. It feeds two consumers:
      1. Domain Compiler (formulas → ViewState)
      2. Teaching Planner (pedagogical sets → teaching strategy)

    The dependency graph and artifact-index are DERIVED (see below).
    """

    chapter: FMChapter
    formulas: dict[str, FMFormula] = field(default_factory=dict)
    pedagogical: dict[str, FMPedagogicalSet] = field(default_factory=dict)
    sources: dict[str, FMSource] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived query helpers (O(1) after first call)
    # ------------------------------------------------------------------

    def formula_for(self, concept_id: str) -> FMFormula | None:
        return self.formulas.get(concept_id)

    def pedagogical_for(self, concept_id: str) -> FMPedagogicalSet | None:
        return self.pedagogical.get(concept_id)

    def depends_on(self, concept_id: str) -> list[str]:
        """Prerequisite concept IDs."""
        f = self.formulas.get(concept_id)
        return list(f.dependencies) if f else []

    def assumed_by(self, concept_id: str) -> list[Assumption]:
        f = self.formulas.get(concept_id)
        return list(f.assumes) if f else []

    def source(self, source_id: str) -> FMSource | None:
        return self.sources.get(source_id)
