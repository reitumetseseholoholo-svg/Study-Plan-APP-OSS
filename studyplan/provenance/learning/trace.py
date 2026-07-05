from __future__ import annotations

import math
from dataclasses import dataclass

from studyplan.provenance.learning.execution_engine import FMExecutionContext, FMExecutionEngine
from studyplan.provenance.learning.events import observation_attempt
from studyplan.provenance.learning.event_bus import EventBus
from studyplan.provenance.knowledge_ir import FMFormula


@dataclass(frozen=True)
class FMAttemptTrace:
    """Raw observation of a student's attempt.

    Pure observation artifact — zero pedagogical interpretation.
    All derived quantities (error label, mismatch vector, etc.)
    live in TraceInterpretation (transition layer).
    """

    formula_id: str
    context: FMExecutionContext
    student_result: float | None
    correct_result: float
    step_texts: tuple[str, ...] = ()
    timestamp: float = 0.0


class FMTraceBuilder:
    """Builds raw observation traces.

    Only computes ground-truth correct answer.
    No error classification — that belongs in the interpretation layer.
    """

    def __init__(self, engine: FMExecutionEngine, bus: EventBus | None = None):
        self._engine = engine
        self._bus = bus

    def build(
        self,
        formula: FMFormula,
        ctx: FMExecutionContext,
        student_result: float | None,
        student_steps: list[str] | None = None,
        timestamp: float = 0.0,
    ) -> FMAttemptTrace:
        correct = self._engine.evaluate(formula, ctx)
        trace = FMAttemptTrace(
            formula_id=formula.concept_id,
            context=ctx,
            student_result=student_result,
            correct_result=correct,
            step_texts=tuple(student_steps or []),
            timestamp=timestamp,
        )
        self._emit_observation(formula.concept_id, ctx.params, student_result, student_steps or [], correct)
        return trace

    def _emit_observation(
        self, formula_id: str, params: dict[str, float], student_answer: float | None, steps: list[str], correct: float
    ) -> None:
        if self._bus is not None:
            self._bus.emit(
                observation_attempt(
                    formula_id=formula_id,
                    params=params,
                    student_answer=student_answer,
                    step_trace=steps,
                    correct_answer=correct,
                    session_id=self._bus.session_id,
                )
            )


def compute_mismatch(student: float, correct: float) -> dict[str, float]:
    """Pure mathematical comparison of two floats.

    Belongs in the trace layer — it is arithmetic, not pedagogy.
    """
    if correct == 0.0:
        rel = 1.0 if student != 0 else 0.0
    else:
        rel = abs(student - correct) / abs(correct)
    return {
        "absolute_difference": round(abs(student - correct), 6),
        "relative_error": round(rel, 6),
        "sign_match": 1.0 if student * correct >= 0 else 0.0,
        "exact_match": 1.0 if abs(student - correct) < 1e-4 else 0.0,
        "log10_difference": round(abs(_safe_log10(abs(student)) - _safe_log10(abs(correct))), 4)
        if student != 0 and correct != 0
        else float("inf"),
    }


def _safe_log10(x: float) -> float:
    if x <= 0:
        return 0.0
    return math.log10(x)
