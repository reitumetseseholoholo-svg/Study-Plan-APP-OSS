from __future__ import annotations


from studyplan.provenance.learning.event_bus import EventBus


_DEFAULT_BUS: EventBus | None = None


def get_compiler_bus() -> EventBus:
    global _DEFAULT_BUS
    if _DEFAULT_BUS is None:
        _DEFAULT_BUS = EventBus(session_id="compiler-session")
    return _DEFAULT_BUS


def set_compiler_bus(bus: EventBus) -> None:
    global _DEFAULT_BUS
    _DEFAULT_BUS = bus
