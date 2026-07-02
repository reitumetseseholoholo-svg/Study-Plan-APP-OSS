"""EvaluationProcess — proof the runtime drives weighted-judgement algebra."""

from __future__ import annotations

from typing import Any

from studyplan.cognitive_runtime.process import CognitiveProcess
from studyplan.domain_reasoning.process import EvaluationTemplate


class EvaluationProcess(CognitiveProcess):
    """Wraps EvaluationTemplate as a single-step CognitiveProcess.

    The process delegates the full weighted-scoring pipeline to
    ``EvaluationTemplate.solve()`` in one step.  The trace records
    the judgment, scores, ranked candidates, confidence, justification,
    contributions, and entropy for downstream interpreters.
    """

    def __init__(self, template: EvaluationTemplate) -> None:
        self._template = template

    @property
    def concept_id(self) -> str:
        return self._template.concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "concept_id": self._template.concept_id,
            "inputs": dict(inputs),
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        result_dict = self._template.solve(state["inputs"])
        return {
            "next_state": {
                **state,
                "done": True,
                "result": result_dict,
            },
            "transition": {
                "type": "evaluation",
                "judgment": result_dict.get("judgment"),
                "scores": result_dict.get("scores"),
                "ranked": result_dict.get("ranked"),
                "confidence": result_dict.get("confidence"),
                "justification": result_dict.get("justification"),
                "contributions": result_dict.get("contributions"),
                "entropy": result_dict.get("entropy"),
                "is_nan": False,
            },
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        return state.get("result")
