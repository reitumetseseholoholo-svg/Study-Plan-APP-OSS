"""Tests for studyplan.state_locking module."""
import threading

import pytest

from studyplan.cognitive_state import CognitiveState
from studyplan.state_locking import (
    bind_cognitive_state_lock,
    get_cognitive_state_lock,
    locked_cognitive_state,
    snapshot_cognitive_state,
    STATE_LOCK_ATTR,
)


def _make_state() -> CognitiveState:
    return CognitiveState()


# ---------------------------------------------------------------------------
# bind_cognitive_state_lock
# ---------------------------------------------------------------------------


def test_bind_creates_rlock_when_no_lock_given():
    state = _make_state()
    lock = bind_cognitive_state_lock(state)
    assert lock is not None
    assert isinstance(lock, type(threading.RLock()))


def test_bind_attaches_lock_to_state():
    state = _make_state()
    lock = bind_cognitive_state_lock(state)
    assert getattr(state, STATE_LOCK_ATTR, None) is lock


def test_bind_returns_existing_lock_if_already_bound():
    state = _make_state()
    first_lock = bind_cognitive_state_lock(state)
    second_lock = bind_cognitive_state_lock(state)
    assert first_lock is second_lock


def test_bind_uses_provided_lock():
    state = _make_state()
    custom_lock = threading.RLock()
    returned = bind_cognitive_state_lock(state, custom_lock)
    assert returned is custom_lock


def test_bind_returns_fallback_when_state_is_none():
    fallback = threading.RLock()
    result = bind_cognitive_state_lock(None, fallback)
    assert result is fallback


def test_bind_returns_none_when_state_and_lock_are_none():
    result = bind_cognitive_state_lock(None)
    assert result is None


# ---------------------------------------------------------------------------
# get_cognitive_state_lock
# ---------------------------------------------------------------------------


def test_get_returns_none_for_non_state():
    assert get_cognitive_state_lock(None) is None
    assert get_cognitive_state_lock("not a state") is None  # type: ignore[arg-type]


def test_get_creates_lock_if_not_present():
    state = _make_state()
    lock = get_cognitive_state_lock(state)
    assert lock is not None


def test_get_returns_same_lock_twice():
    state = _make_state()
    lock1 = get_cognitive_state_lock(state)
    lock2 = get_cognitive_state_lock(state)
    assert lock1 is lock2


# ---------------------------------------------------------------------------
# locked_cognitive_state context manager
# ---------------------------------------------------------------------------


def test_locked_cognitive_state_yields_state():
    state = _make_state()
    with locked_cognitive_state(state) as s:
        assert s is state


def test_locked_cognitive_state_with_none_yields_none():
    with locked_cognitive_state(None) as s:
        assert s is None


def test_locked_cognitive_state_with_explicit_lock():
    state = _make_state()
    lock = threading.RLock()
    with locked_cognitive_state(state, lock) as s:
        assert s is state


# ---------------------------------------------------------------------------
# snapshot_cognitive_state
# ---------------------------------------------------------------------------


def test_snapshot_returns_empty_dict_for_none():
    result = snapshot_cognitive_state(None)
    assert result == {}


def test_snapshot_returns_dict_for_valid_state():
    state = _make_state()
    snap = snapshot_cognitive_state(state)
    assert isinstance(snap, dict)
    assert "schema_version" in snap


def test_snapshot_is_frozen_copy():
    state = _make_state()
    snap1 = snapshot_cognitive_state(state)
    state.quiz_active = True
    snap2 = snapshot_cognitive_state(state)
    # First snapshot should reflect original value
    assert snap1["quiz_active"] is False
    assert snap2["quiz_active"] is True
