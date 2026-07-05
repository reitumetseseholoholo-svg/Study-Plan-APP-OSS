"""CognitiveExecutor — the invariant lifecycle contract.

Every cognitive process is a transition system::

    S₀ → δ → S₁ → δ → S₂ → … → Terminal

The runtime drives any executor through this lifecycle without knowing
what the executor does or what domain it belongs to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Transition:
    """One atomic state change emitted by an executor step.

    ``action``
        What happened (e.g. ``"evaluate_condition"``, ``"commit_result"``).
        This is the primary signal for canonicalization.

    ``rationale``
        Why it happened (e.g. ``"score > 50 was True"``).

    ``evidence``
        Supporting data (e.g. ``{"matched_condition": "score > 50"}``).
    """

    action: str
    rationale: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class CognitiveExecutor(ABC):
    """A cognitive algebra as an executable transition system.

    Each executor defines four lifecycle hooks.  The runtime calls these
    in a deterministic loop::

        state = executor.initialize(inputs)
        while not executor.finished(state):
            result = executor.step(state)
            state = result["next_state"]
        output = executor.result(state)

    Every call to ``step()`` must return a dict with at least
    ``"next_state"``.  The runtime consumes only that key — all
    additional keys (``"transition"``, ``"metadata"``, etc.) are
    recorded in the trace but never read by the runtime.

    An executor is *stateless by contract* — every invocation of
    ``execute()`` creates fresh state via ``initialize()``.
    """

    @abstractmethod
    def initialize(self, inputs: dict[str, Any]) -> Any:
        """Build initial executor state from raw inputs.

        Returns an opaque state object passed to ``step()`` and ``finished()``.
        """
        ...

    @abstractmethod
    def step(self, state: Any) -> dict[str, Any]:
        """Advance state by one atomic transition.

        Returns a dict with at least ``"next_state"``.
        The ``"transition"`` key, if present, is recorded in the trace
        as structured metadata for downstream analysis.
        """
        ...

    @abstractmethod
    def finished(self, state: Any) -> bool:
        """Return ``True`` when the executor has converged."""
        ...

    def result(self, state: Any) -> Any:
        """Extract the final output from terminal state.

        Default returns *state* unchanged.  Override when the executor
        needs to map internal state to a public result value.
        """
        return state

    @property
    def concept_id(self) -> str:
        """Human-readable identifier (overridable)."""
        return self.__class__.__name__
