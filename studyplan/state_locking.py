from __future__ import annotations

import contextlib
import threading
from typing import Any, Iterator

from .cognitive_state import CognitiveState


STATE_LOCK_ATTR = "_studyplan_state_lock"


def bind_cognitive_state_lock(state: CognitiveState | None, lock: Any | None = None) -> Any | None:
    """Attach or retrieve a shared runtime lock for a cognitive state object."""
    if not isinstance(state, CognitiveState):
        return lock
    existing = getattr(state, STATE_LOCK_ATTR, None)
    if existing is not None:
        return existing
    resolved = lock if lock is not None else threading.RLock()
    try:
        setattr(state, STATE_LOCK_ATTR, resolved)
    except Exception:
        pass
    return resolved


def get_cognitive_state_lock(state: CognitiveState | None) -> Any | None:
    if not isinstance(state, CognitiveState):
        return None
    lock = getattr(state, STATE_LOCK_ATTR, None)
    if lock is None:
        lock = bind_cognitive_state_lock(state)
    return lock


@contextlib.contextmanager
def locked_cognitive_state(state: CognitiveState | None, lock: Any | None = None) -> Iterator[CognitiveState | None]:
    resolved = lock if lock is not None else get_cognitive_state_lock(state)
    if resolved is None:
        yield state
        return
    with resolved:
        yield state


def snapshot_cognitive_state(state: CognitiveState | None) -> dict[str, Any]:
    """Take one frozen snapshot of the live state under its runtime lock."""
    if not isinstance(state, CognitiveState):
        return {}
    with locked_cognitive_state(state):
        return state.to_json_snapshot()
