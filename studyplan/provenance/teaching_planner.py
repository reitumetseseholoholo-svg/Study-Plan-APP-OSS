"""Teaching Planner — chooses a pedagogical strategy, then moves.

Strategy selection based on student mastery:
  mastery < 0.3 → REMEDIATE (teach prerequisites)
  mastery < 0.6 → INTRODUCE (define → illustrate → test)
  mastery < 0.8 → REINFORCE (test → correct → test again)
  mastery >= 0.8 → EXTEND (synthesize with related concepts)

Each strategy selects artifacts from FMPedagogicalSet.
The planner produces a TeachingPlan: a sequence of moves with evidence.
"""

from dataclasses import dataclass
from enum import Enum

from studyplan.provenance.knowledge_ir import (
    FMKnowledgeBase,
    FMFormula,
    PedagogicalArtifact,
)


class Strategy(Enum):
    REMEDIATE = "remediate"
    INTRODUCE = "introduce"
    REINFORCE = "reinforce"
    EXTEND = "extend"


class Move(Enum):
    DEFINE = "define"
    ILLUSTRATE = "illustrate"
    TEST = "test"
    CORRECT = "correct"
    SYNTHESIZE = "synthesize"


@dataclass(frozen=True)
class TeachingStep:
    move: Move
    artifact: PedagogicalArtifact | None
    rationale: str


@dataclass(frozen=True)
class TeachingPlan:
    objective_id: str
    objective_label: str
    strategy: Strategy
    steps: tuple[TeachingStep, ...]
    weak_prerequisites: tuple[str, ...]


class TeachingPlanner:
    """Chooses strategy and selects artifacts based on student mastery."""

    def __init__(self, kb: FMKnowledgeBase):
        self._kb = kb

    def plan(
        self,
        concept_id: str,
        mastery: dict[str, float] | None = None,
    ) -> TeachingPlan:
        mastery = mastery or {}
        formula = self._kb.formula_for(concept_id)
        if formula is None:
            raise ValueError(f"Unknown concept: {concept_id}")

        student_score = mastery.get(concept_id, 0.0)
        strategy = self._choose_strategy(student_score, concept_id, mastery)

        if strategy == Strategy.REMEDIATE:
            steps = self._remediate(concept_id, formula, mastery)
        elif strategy == Strategy.INTRODUCE:
            steps = self._introduce(concept_id)
        elif strategy == Strategy.REINFORCE:
            steps = self._reinforce(concept_id)
        else:
            steps = self._extend(concept_id)

        # Detect weak prerequisites regardless of strategy
        weak = tuple(dep for dep in formula.dependencies if mastery.get(dep, 0.0) < 0.6)

        return TeachingPlan(
            objective_id=concept_id,
            objective_label=formula.label,
            strategy=strategy,
            steps=tuple(steps),
            weak_prerequisites=weak,
        )

    # ------------------------------------------------------------------
    # Strategy selection
    # ------------------------------------------------------------------

    def _choose_strategy(
        self,
        student_score: float,
        concept_id: str,
        mastery: dict[str, float],
    ) -> Strategy:
        """Select strategy based on mastery of this concept and its prereqs."""
        formula = self._kb.formula_for(concept_id)
        if formula is None:
            return Strategy.INTRODUCE

        # Any weak prerequisites?
        for dep in formula.dependencies:
            if mastery.get(dep, 0.0) < 0.6:
                return Strategy.REMEDIATE

        if student_score < 0.3:
            return Strategy.REMEDIATE
        if student_score < 0.6:
            return Strategy.INTRODUCE
        if student_score < 0.8:
            return Strategy.REINFORCE
        return Strategy.EXTEND

    # ------------------------------------------------------------------
    # Move implementations
    # ------------------------------------------------------------------

    def _remediate(
        self,
        concept_id: str,
        formula: FMFormula,
        mastery: dict[str, float],
    ) -> list[TeachingStep]:
        steps: list[TeachingStep] = []
        # Teach weak prerequisites first
        for dep_id in formula.dependencies:
            if mastery.get(dep_id, 0.0) < 0.6:
                dep_formula = self._kb.formula_for(dep_id)
                dep_ped = self._kb.pedagogical_for(dep_id)
                if dep_formula:
                    steps.append(
                        TeachingStep(
                            Move.DEFINE,
                            self._first_or_none(dep_ped.definitions if dep_ped else ()),
                            f"Prerequisite: {dep_formula.label} needs reinforcement",
                        )
                    )
                    steps.append(
                        TeachingStep(
                            Move.ILLUSTRATE,
                            self._first_or_none(dep_ped.worked_examples if dep_ped else ()),
                            f"Example of {dep_formula.label}",
                        )
                    )
        # Then introduce target
        steps.extend(self._introduce(concept_id))
        return steps

    def _introduce(self, concept_id: str) -> list[TeachingStep]:
        ped = self._kb.pedagogical_for(concept_id)
        if ped is None:
            return [TeachingStep(Move.DEFINE, None, f"Teach {concept_id}")]

        steps: list[TeachingStep] = []

        # 1. Define
        if ped.definitions:
            steps.append(TeachingStep(Move.DEFINE, ped.definitions[0], f"Definition of {concept_id}"))

        # 2. Show formula
        if ped.formulas:
            steps.append(TeachingStep(Move.DEFINE, ped.formulas[0], f"Formula for {concept_id}"))

        # 3. Illustrate
        if ped.worked_examples:
            steps.append(TeachingStep(Move.ILLUSTRATE, ped.worked_examples[0], f"Worked example of {concept_id}"))

        # 4. Correct likely misconceptions
        if ped.misconceptions:
            steps.append(
                TeachingStep(Move.CORRECT, ped.misconceptions[0], f"Common mistake to avoid with {concept_id}")
            )

        # 5. Test
        if ped.exam_questions:
            steps.append(TeachingStep(Move.TEST, ped.exam_questions[0], f"Check understanding of {concept_id}"))

        return steps

    def _reinforce(self, concept_id: str) -> list[TeachingStep]:
        ped = self._kb.pedagogical_for(concept_id)
        if ped is None:
            return [TeachingStep(Move.TEST, None, f"Test {concept_id}")]

        steps: list[TeachingStep] = []

        # 1. Test first (find the gap)
        if ped.exam_questions:
            steps.append(TeachingStep(Move.TEST, ped.exam_questions[0], f"Diagnostic: test {concept_id}"))

        # 2. Correct if misconceptions exist
        if ped.misconceptions:
            steps.append(TeachingStep(Move.CORRECT, ped.misconceptions[0], "Reinforce: address common mistake"))

        # 3. Re-test
        if len(ped.exam_questions) > 1:
            steps.append(TeachingStep(Move.TEST, ped.exam_questions[1], f"Verify understanding of {concept_id}"))
        elif ped.worked_examples:
            steps.append(TeachingStep(Move.ILLUSTRATE, ped.worked_examples[0], f"Additional example of {concept_id}"))

        return steps

    def _extend(self, concept_id: str) -> list[TeachingStep]:
        steps: list[TeachingStep] = []
        formula = self._kb.formula_for(concept_id)
        if formula is None:
            return steps

        # Synthesize: connect to related concepts
        related = list(formula.dependencies)
        for other_id, other_f in self._kb.formulas.items():
            if other_id != concept_id and concept_id in other_f.dependencies:
                related.append(other_id)

        if related:
            steps.append(TeachingStep(Move.SYNTHESIZE, None, f"Connect {formula.label} to {', '.join(related)}"))

        # Advanced: examiner guidance
        ped = self._kb.pedagogical_for(concept_id)
        if ped and ped.examiner_guidance:
            steps.append(TeachingStep(Move.CORRECT, ped.examiner_guidance[0], f"Examiner guidance on {concept_id}"))

        return steps

    @staticmethod
    def _first_or_none(artifacts: tuple) -> PedagogicalArtifact | None:
        return artifacts[0] if artifacts else None


def format_plan(plan: TeachingPlan) -> str:
    lines = [
        f"Objective: {plan.objective_label} ({plan.objective_id})",
        f"Strategy: {plan.strategy.value}",
    ]
    if plan.weak_prerequisites:
        lines.append(f"Weak prereqs: {', '.join(plan.weak_prerequisites)}")
    lines.append("")
    for i, step in enumerate(plan.steps, 1):
        aid = f" [{step.artifact.id}]" if step.artifact else ""
        content = ""
        if step.artifact:
            c = step.artifact.content[:150].replace("\n", " | ")
            content = f"\n       {c}"
        lines.append(f"{i}. {step.move.value.upper()}{aid}: {step.rationale}{content}")
    return "\n".join(lines)
