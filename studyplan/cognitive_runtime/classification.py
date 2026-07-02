"""ClassificationProcess — proof the runtime drives decision-tree algebra."""

from __future__ import annotations

from typing import Any

from studyplan.cognitive_runtime.process import CognitiveProcess
from studyplan.domain_reasoning.concept_types.classification_concept import (
    ClassificationTemplate,
)


class ClassificationProcess(CognitiveProcess):
    """Wraps ClassificationTemplate as a single-step CognitiveProcess.

    The process delegates the full tree traversal to
    ``ClassificationTemplate.solve()`` in one step.  The trace records
    the complete decision path, result, and classification_path for downstream
    interpreters.
    """

    def __init__(self, template: ClassificationTemplate) -> None:
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
                "type": "classification",
                "result": result_dict.get("result"),
                "is_nan": result_dict.get("is_nan", True),
                "steps": result_dict.get("steps", []),
                "classification_path": result_dict.get("classification_path", []),
            },
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        return state.get("result")
