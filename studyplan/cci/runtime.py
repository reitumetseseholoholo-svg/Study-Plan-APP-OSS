"""CognitiveRuntime — drives any CognitiveProcess through the invariant lifecycle.

The runtime is deliberately minimal.  It owns exactly one responsibility:
drive state evolution and emit an immutable event trace.  All
interpretation (diagnostics, explanation, adaptation) happens downstream.

Each event is stamped with causal provenance (``transition_id``,
``state_hash_before``/``state_hash_after``) enabling deterministic
reconstruction of the causal graph — see ``CanonicalTraceReconstructor``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from studyplan.cci.event import ExecutionTrace
from studyplan.cci.executor import CognitiveExecutor
from studyplan.cci.process import CognitiveProcess

# Accept either a CognitiveProcess (legacy) or CognitiveExecutor (new).
# The two protocols have identical lifecycle signatures.
_Executable = CognitiveProcess | CognitiveExecutor


class CognitiveRuntime:
    """Extremely small: only state evolution.

    Usage::

        runtime = CognitiveRuntime()
        trace = runtime.execute(my_process, {"input": 42})
    """

    def execute(
        self,
        process: _Executable,
        inputs: dict[str, Any],
    ) -> ExecutionTrace:
        """Drive *process* through its lifecycle and return the event trace.

        The lifecycle is::

            initialize → [step → step → … → step] → terminate

        Every transition is recorded as an immutable event in the trace.
        No interpretation or result extraction happens here.

        Each event carries deterministic state hashes that allow
        ``CanonicalTraceReconstructor`` to derive causal edges without
        heuristics or process access.
        """
        trace = ExecutionTrace()
        step_count = 0

        state = process.initialize(inputs)
        state_hash = _state_hash(state)

        trace.record(
            "initialize",
            {"state": _safe_state(state)},
            transition_id="init",
            state_hash_before="init",
            state_hash_after=state_hash,
        )

        while not process.finished(state):
            step_result = process.step(state)
            state_hash_before = state_hash
            state = step_result["next_state"]
            state_hash = _state_hash(state)
            step_count += 1

            trace.record(
                "step",
                {
                    "transition": _safe_state(step_result.get("transition")),
                    "new_state": _safe_state(state),
                },
                transition_id=f"step_{step_count}",
                state_hash_before=state_hash_before,
                state_hash_after=state_hash,
            )

        final_result = process.result(state)
        trace.record(
            "terminate",
            {
                "final_state": _safe_state(state),
                "result": _safe_state(final_result),
            },
            transition_id="terminate",
            state_hash_before=state_hash,
            state_hash_after=state_hash,
        )

        return trace


def _state_hash(state: Any) -> str:
    """Deterministic SHA-1 digest of a state dict for causal provenance.

    Uses the same ``json.dumps(sort_keys=True, default=str)`` pattern
    established across the codebase for deterministic identity.
    """
    safe = _safe_state(state)
    try:
        serialized = json.dumps(safe, sort_keys=True, ensure_ascii=True, default=str)
        return hashlib.sha1(serialized.encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return "unhashable"


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
