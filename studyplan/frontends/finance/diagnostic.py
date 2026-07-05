"""DiagnosticProcess — Bayesian belief updating as a CognitiveProcess.

Wraps ``DiagnosticTemplate`` (from domain_reasoning/process/diagnostic.py)
as a single-step ``CognitiveProcess``.  The trace records posterior
distribution, MAP hypothesis, entropy, evidence trail, and recommended
investigations for downstream interpreters.
"""

from __future__ import annotations

from typing import Any

from studyplan.cci.process import CognitiveProcess
from studyplan.domain_reasoning.process.diagnostic import DiagnosticTemplate


class DiagnosticProcess(CognitiveProcess):
    """Wraps DiagnosticTemplate as a single-step CognitiveProcess.

    The process delegates the full Bayesian belief-updating pipeline to
    ``DiagnosticTemplate.solve()`` in one step.  The trace records the
    posterior distribution, MAP hypothesis, entropy, evidence trail, and
    recommended investigations.
    """

    def __init__(self, template: DiagnosticTemplate) -> None:
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
                "depth": max(
                    len(result_dict.get("steps", [])),
                    len(result_dict.get("recommended_investigations", [])),
                    1,
                ),
                "type": "diagnostic",
                "map_hypothesis": result_dict.get("map_hypothesis"),
                "map_probability": result_dict.get("map_probability"),
                "entropy": result_dict.get("entropy"),
                "posterior_distribution": result_dict.get("posterior_distribution"),
                "recommended_investigations": result_dict.get("recommended_investigations"),
                "steps": result_dict.get("steps", []),
                "is_nan": result_dict.get("is_nan", True),
            },
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        return state.get("result")
