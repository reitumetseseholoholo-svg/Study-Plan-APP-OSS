"""Immutable event records produced during cognitive process execution.

Each event carries *causal provenance* in addition to its payload:

- ``transition_id`` — identifies which process transition produced this event
- ``state_hash_before``/``state_hash_after`` — deterministic digests of the
  process state before and after the transition, enabling canonical
  causal-graph reconstruction without heuristics.
"""

from __future__ import annotations

import time
from typing import Any


class CognitiveEvent:
    """One atomic occurrence during the execution of a cognitive process.

    Immutable after creation.  The ``type`` labels *what* happened
    (``"initialize"``, ``"step"``, ``"terminate"``, etc.) and ``payload``
    carries the domain-free details.

    Provenance fields (``transition_id``, ``state_hash_before``,
    ``state_hash_after``) support deterministic causal-graph
    reconstruction — see ``CanonicalTraceReconstructor``.
    """

    __slots__ = (
        "type",
        "payload",
        "timestamp",
        "transition_id",
        "state_hash_before",
        "state_hash_after",
    )

    def __init__(
        self,
        type: str,
        payload: dict[str, Any],
        timestamp: float | None = None,
        transition_id: str = "",
        state_hash_before: str = "",
        state_hash_after: str = "",
    ) -> None:
        self.type = type
        self.payload = payload
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.transition_id = transition_id
        self.state_hash_before = state_hash_before
        self.state_hash_after = state_hash_after

    def __repr__(self) -> str:
        return (
            f"CognitiveEvent(type={self.type!r}, "
            f"transition_id={self.transition_id!r}, "
            f"payload_keys={list(self.payload.keys())}, "
            f"timestamp={self.timestamp:.3f})"
        )


CCI_TRACE_VERSION = 1
"""Trace format version for forward compatibility.

Increment this when the trace schema changes (new event types, changed
payload structure, new provenance fields). Tools consuming serialized
traces can use ``trace_version`` to detect mismatches.
"""


class ExecutionTrace:
    """Append-only, immutable sequence of cognitive events.

    Usage::

        trace = ExecutionTrace()
        trace.record("initialize", {"state": ...})
        trace.record("step", {"transition": ..., "new_state": ...},
                     transition_id="classify")
        trace.record("terminate", {"final_state": ...})
    """

    def __init__(self) -> None:
        self._events: list[CognitiveEvent] = []
        self.trace_version: int = CCI_TRACE_VERSION

    @property
    def events(self) -> list[CognitiveEvent]:
        return list(self._events)

    def record(
        self,
        event_type: str,
        payload: dict[str, Any],
        transition_id: str = "",
        state_hash_before: str = "",
        state_hash_after: str = "",
    ) -> None:
        """Append one event with optional causal provenance."""
        self._events.append(
            CognitiveEvent(
                event_type,
                dict(payload),
                transition_id=transition_id,
                state_hash_before=state_hash_before,
                state_hash_after=state_hash_after,
            )
        )

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        return f"ExecutionTrace({len(self._events)} events)"
