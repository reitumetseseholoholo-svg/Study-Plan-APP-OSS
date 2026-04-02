"""Tests for studyplan.lifecycle module (ShutdownBarrier)."""
import threading
import time

import pytest

from studyplan.lifecycle import ShutdownBarrier, ShutdownInProgressError


def test_initial_not_shutting_down():
    barrier = ShutdownBarrier()
    assert not barrier.is_shutting_down()


def test_start_work_returns_true_before_shutdown():
    barrier = ShutdownBarrier()
    assert barrier.start_work("job-1") is True


def test_finish_work_removes_id():
    barrier = ShutdownBarrier()
    barrier.start_work("job-1")
    barrier.finish_work("job-1")
    assert barrier.active_work_ids() == []


def test_active_work_ids_lists_started_work():
    barrier = ShutdownBarrier()
    barrier.start_work("a")
    barrier.start_work("b")
    ids = barrier.active_work_ids()
    assert "a" in ids
    assert "b" in ids


def test_start_work_returns_false_after_shutdown_initiated():
    barrier = ShutdownBarrier()
    # Initiate shutdown with no active work — should succeed immediately
    result = barrier.initiate_shutdown(timeout_sec=1.0)
    assert result is True
    # New work should be rejected
    assert barrier.start_work("late-job") is False


def test_work_scope_raises_after_shutdown():
    barrier = ShutdownBarrier()
    barrier.initiate_shutdown(timeout_sec=1.0)
    with pytest.raises(ShutdownInProgressError):
        with barrier.work_scope("some-work"):
            pass


def test_work_scope_yields_work_id():
    barrier = ShutdownBarrier()
    with barrier.work_scope("my-work") as wid:
        assert isinstance(wid, str)
        assert wid  # non-empty
    # After exiting scope, work id should no longer be active
    assert "my-work" not in barrier.active_work_ids()


def test_initiate_shutdown_waits_for_active_work():
    """Shutdown should wait until in-flight work finishes."""
    barrier = ShutdownBarrier()
    barrier.start_work("slow-job")

    def finish_after_delay():
        time.sleep(0.05)
        barrier.finish_work("slow-job")

    t = threading.Thread(target=finish_after_delay, daemon=True)
    t.start()
    result = barrier.initiate_shutdown(timeout_sec=2.0)
    assert result is True
    t.join()


def test_initiate_shutdown_timeout_returns_false():
    """If work never finishes before timeout, return False."""
    barrier = ShutdownBarrier()
    barrier.start_work("stuck-job")
    result = barrier.initiate_shutdown(timeout_sec=0.05)
    assert result is False
    # cleanup
    barrier.finish_work("stuck-job")


def test_finish_work_empty_id_is_safe():
    barrier = ShutdownBarrier()
    # Should not raise
    barrier.finish_work("")


def test_start_work_empty_id_auto_generates():
    barrier = ShutdownBarrier()
    result = barrier.start_work("")
    assert result is True
    ids = barrier.active_work_ids()
    # An auto-generated id should have been added
    assert len(ids) >= 1


def test_is_shutting_down_after_initiate():
    barrier = ShutdownBarrier()
    barrier.initiate_shutdown(timeout_sec=1.0)
    assert barrier.is_shutting_down() is True
