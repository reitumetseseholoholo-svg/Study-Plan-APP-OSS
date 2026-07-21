"""ComputationProcess — proof that the runtime can drive a pure-function algebra.

This is the simplest cognitive algebra: a single-step function evaluation.
The process initialises with inputs, evaluates exactly one expression,
and terminates.  No loop, no branching, no accumulation.

The process stores only *transition data* in state — configuration
(concept_id, solver_fn, expression) lives on the instance.
No semantic leakage: state is ``{inputs, done, result}`` — nothing more.
"""

from __future__ import annotations

from typing import Any, Callable

from studyplan.cci.process import CognitiveProcess


class ComputationProcess(CognitiveProcess):
    """Single-step expression evaluation.

    Wraps a solver function (typically produced by
    ``_make_expression_solver()``) and optional expression string.

    State is: ``{inputs, done, result}`` — only what changes during execution.
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
            "inputs": dict(inputs),
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
                "depth": 1,
            },
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> Any:
        return state.get("result")
