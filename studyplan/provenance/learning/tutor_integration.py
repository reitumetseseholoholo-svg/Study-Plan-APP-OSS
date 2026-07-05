from __future__ import annotations


from studyplan.provenance.learning.event_bus import EventBus
from studyplan.provenance.learning.tutor_bridge import build_learning_context


_DEFAULT_BUS: EventBus | None = None


def get_learning_bus() -> EventBus:
    global _DEFAULT_BUS
    if _DEFAULT_BUS is None:
        _DEFAULT_BUS = EventBus(session_id="learning-session")
    return _DEFAULT_BUS


def set_learning_bus(bus: EventBus) -> None:
    global _DEFAULT_BUS
    _DEFAULT_BUS = bus


class LearningIntegrator:
    """App-facing facade for kernel learning intelligence.

    Wraps the EventBus and provides a formatted learning context
    block for the tutor prompt. Mirrors ProvenanceIntegrator's pattern.
    """

    def __init__(self, bus: EventBus | None = None):
        self._bus = bus or get_learning_bus()

    @property
    def bus(self) -> EventBus:
        return self._bus

    def tutor_context(self) -> str | None:
        """Return a formatted learning-context block for the tutor prompt."""
        return build_learning_context(self._bus)

    def clear(self) -> None:
        self._bus.clear()
