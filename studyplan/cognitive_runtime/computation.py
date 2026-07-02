"""ComputationProcess — proof that the runtime can drive a pure-function algebra.

This is the simplest cognitive algebra: a single-step function evaluation.
The process initialises with inputs, evaluates exactly one expression,
and terminates.  No loop, no branching, no accumulation.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from studyplan.cognitive_runtime.process import CognitiveProcess


class ComputationProcess(CognitiveProcess):
    """Single-step expression evaluation.

    Wraps a solver function (typically produced by
    ``_make_expression_solver()``) and optional expression string.

    State is a dict with::

        {concept_id, inputs, solver, expression, done, result}
    """

    def __init__(
        self,
        concept_id: str,
        solver_fn: Callable[..., float],
        expression: str | None = None,
    ) -> None:
        self._concept_id = concept_id
        self._solver = solver_fn
        self._expression = expression

    @property
    def concept_id(self) -> str:
        return self._concept_id

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "concept_id": self._concept_id,
            "inputs": dict(inputs),
            "solver": self._solver,
            "expression": self._expression,
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        result = self._solver(**state["inputs"])
        return {
            "next_state": {
                **state,
                "done": True,
                "result": result,
            },
            "transition": {
                "type": "evaluate",
                "result": result,
                "is_nan": isinstance(result, float) and math.isnan(result),
            },
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> Any:
        return state.get("result")
