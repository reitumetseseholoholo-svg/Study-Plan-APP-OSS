from __future__ import annotations

from collections.abc import Callable

from studyplan.provenance.learning.events import EventEnvelope


SubscriberFn = Callable[[EventEnvelope], None]


class EventBus:
    """Typed event bus for kernel→UI communication.

    The kernel emits events; subscribers receive immutable projections.
    The bus enforces zero state mutation — it only dispatches.
    """

    def __init__(self, session_id: str = ""):
        self._session_id = session_id
        self._subscribers: dict[str, list[SubscriberFn]] = {}
        self._wildcards: list[SubscriberFn] = []
        self._history: list[EventEnvelope] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def event_count(self) -> int:
        return len(self._history)

    @property
    def history(self) -> list[EventEnvelope]:
        return list(self._history)

    def subscribe(self, event_type: str, fn: SubscriberFn) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(fn)

    def subscribe_all(self, fn: SubscriberFn) -> None:
        self._wildcards.append(fn)

    def unsubscribe(self, event_type: str, fn: SubscriberFn) -> None:
        subs = self._subscribers.get(event_type, [])
        if fn in subs:
            subs.remove(fn)

    def emit(self, event: EventEnvelope) -> None:
        self._history.append(event)
        for fn in self._wildcards:
            fn(event)
        for fn in self._subscribers.get(event.type, []):
            fn(event)

    def clear(self) -> None:
        self._history.clear()
        self._subscribers.clear()
        self._wildcards.clear()

    def events_by_type(self, event_type: str) -> list[EventEnvelope]:
        return [e for e in self._history if e.type == event_type]

    def events_by_layer(self, layer: str) -> list[EventEnvelope]:
        return [e for e in self._history if e.layer == layer]

    def replay(self, events: list[EventEnvelope]) -> None:
        for event in events:
            self.emit(event)
