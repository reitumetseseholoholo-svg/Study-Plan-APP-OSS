"""Immutable event records produced during cognitive process execution."""

from __future__ import annotations

import time
from typing import Any


class CognitiveEvent:
    """One atomic occurrence during the execution of a cognitive process.

    Immutable after creation.  The ``type`` labels *what* happened
    (``"initialize"``, ``"step"``, ``"terminate"``, etc.) and ``payload``
    carries the domain-free details.
    """

    __slots__ = ("type", "payload", "timestamp")

    def __init__(
        self,
        type: str,
        payload: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        self.type = type
        self.payload = payload
        self.timestamp = timestamp if timestamp is not None else time.time()

    def __repr__(self) -> str:
        return (
            f"CognitiveEvent(type={self.type!r}, "
            f"payload_keys={list(self.payload.keys())}, "
            f"timestamp={self.timestamp:.3f})"
        )


class ExecutionTrace:
    """Append-only, immutable sequence of cognitive events.

    Usage::

        trace = ExecutionTrace()
        trace.record("initialize", {"state": ...})
        trace.record("step", {"transition": ..., "new_state": ...})
        trace.record("terminate", {"final_state": ...})
    """

    def __init__(self) -> None:
        self._events: list[CognitiveEvent] = []

    @property
    def events(self) -> list[CognitiveEvent]:
        return list(self._events)

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append one event to the trace."""
        self._events.append(CognitiveEvent(event_type, dict(payload)))

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        return f"ExecutionTrace({len(self._events)} events)"
