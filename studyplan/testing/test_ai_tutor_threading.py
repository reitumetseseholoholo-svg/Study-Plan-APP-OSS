"""Tests for shutdown-aware background scheduling in studyplan_ai_tutor."""

from __future__ import annotations

import threading

from studyplan_ai_tutor import _schedule_gui_background_thread


class _FakeGLib:
    @staticmethod
    def idle_add(fn, *args, **kwargs):
        fn(*args, **kwargs)
        return 1


def test_schedule_uses_managed_starter_and_runs_target():
    calls: list[str] = []

    class App:
        def _start_managed_background_thread(self, target, *, name: str = "x") -> bool:
            calls.append(name)
            target()
            return True

    app = App()

    def target() -> None:
        calls.append("ran")

    assert _schedule_gui_background_thread(app, _FakeGLib, target, name="tutor-test") is True
    assert calls == ["tutor-test", "ran"]


def test_schedule_when_starter_refuses_invokes_idle_callback():
    class App:
        def _start_managed_background_thread(self, target, *, name: str = "x") -> bool:
            return False

    app = App()
    idle_results: list[bool] = []

    def target() -> None:
        raise AssertionError("worker should not run")

    def on_fail() -> bool:
        idle_results.append(True)
        return False

    assert _schedule_gui_background_thread(
        app, _FakeGLib, target, name="tutor-test", on_start_failed=on_fail
    ) is False
    assert idle_results == [True]


def test_schedule_without_starter_uses_daemon_thread():
    class App:
        pass

    done = threading.Event()

    def target() -> None:
        done.set()

    assert _schedule_gui_background_thread(App(), _FakeGLib, target, name="tutor-fallback") is True
    assert done.wait(timeout=2.0), "daemon thread should run target"


def test_schedule_starter_exception_falls_through_to_idle_when_callback_given():
    class App:
        def _start_managed_background_thread(self, target, *, name: str = "x") -> bool:
            raise RuntimeError("boom")

    app = App()
    idle_ran: list[str] = []

    def target() -> None:
        pass

    def on_fail() -> bool:
        idle_ran.append("ok")
        return False

    assert _schedule_gui_background_thread(app, _FakeGLib, target, name="x", on_start_failed=on_fail) is False
    assert idle_ran == ["ok"]
