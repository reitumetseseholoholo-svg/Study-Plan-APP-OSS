"""CognitiveRuntime — drives any CognitiveProcess through the invariant lifecycle.

The runtime is deliberately minimal.  It owns exactly one responsibility:
drive state evolution and emit an immutable event trace.  All
interpretation (diagnostics, explanation, adaptation) happens downstream.
"""

from __future__ import annotations

from typing import Any

from studyplan.cognitive_runtime.event import ExecutionTrace
from studyplan.cognitive_runtime.process import CognitiveProcess


class CognitiveRuntime:
    """Extremely small: only state evolution.

    Usage::

        runtime = CognitiveRuntime()
        trace = runtime.execute(my_process, {"input": 42})
    """

    def execute(
        self,
        process: CognitiveProcess,
        inputs: dict[str, Any],
    ) -> ExecutionTrace:
        """Drive *process* through its lifecycle and return the event trace.

        The lifecycle is::

            initialize → [step → step → … → step] → terminate

        Every transition is recorded as an immutable event in the trace.
        No interpretation or result extraction happens here.
        """
        trace = ExecutionTrace()

        state = process.initialize(inputs)
        trace.record("initialize", {"state": _safe_state(state)})

        while not process.finished(state):
            step_result = process.step(state)
            state = step_result["next_state"]
            transition = step_result.get("transition")
            trace.record(
                "step",
                {
                    "transition": _safe_state(transition),
                    "new_state": _safe_state(state),
                },
            )

        final_result = process.result(state)
        trace.record(
            "terminate",
            {
                "final_state": _safe_state(state),
                "result": _safe_state(final_result),
            },
        )

        return trace


def _safe_state(state: Any) -> Any:
    """Ensure state is JSON-serializable for trace storage."""
    if state is None or isinstance(state, (str, int, float, bool)):
        return state
    if isinstance(state, dict):
        return {k: _safe_state(v) for k, v in state.items() if not k.startswith("_")}
    if isinstance(state, (list, tuple)):
        return [_safe_state(v) for v in state]
    # Fallback: string repr for opaque objects
    return repr(state)
