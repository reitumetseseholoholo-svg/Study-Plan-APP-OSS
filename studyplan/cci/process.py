"""CognitiveProcess — the algebra contract for a cognitive process."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CognitiveProcess(ABC):
    """A cognitive algebra — defines legal state evolution for one cognitive class.

    Each process defines three required hooks (``initialize``, ``step``,
    ``finished``) and one optional hook (``result``).  The runtime calls
    these in a loop::

        state = process.initialize(inputs)
        while not process.finished(state):
            state = process.step(state)["next_state"]
        output = process.result(state)

    A process is *stateless* — every invocation of ``execute()`` creates
    fresh state via ``initialize()``.
    """

    @abstractmethod
    def initialize(self, inputs: dict[str, Any]) -> Any:
        """Build initial process state from raw inputs.

        Returns an opaque state object that will be passed to ``step()``
        and ``finished()``.
        """
        ...

    @abstractmethod
    def step(self, state: Any) -> dict[str, Any]:
        """Advance state by one transition.

        Returns a dict with at least ``"next_state"``.  The runtime
        consumes only ``"next_state"`` — any additional keys are ignored.
        This means ``step()`` MUST NOT leak semantic metadata into the
        return value; all interpretation lives in downstream interpreters.
        """
        ...

    @abstractmethod
    def finished(self, state: Any) -> bool:
        """Return ``True`` when the process has converged and should stop."""
        ...

    def result(self, state: Any) -> Any:
        """Extract the final output from terminal state.

        The default returns *state* unchanged.  Override when the process
        needs to map internal state to a public result value.
        """
        return state

    @property
    def concept_id(self) -> str:
        """Human-readable identifier for this process (overridable)."""
        return self.__class__.__name__
