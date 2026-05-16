from __future__ import annotations

import types

import studyplan_app as appmod
from studyplan_app import StudyPlanGUI


def _bind_tracking_helpers(dummy: types.SimpleNamespace) -> types.SimpleNamespace:
    dummy._register_glib_source = types.MethodType(StudyPlanGUI._register_glib_source, dummy)
    dummy._schedule_tracked_timeout = types.MethodType(StudyPlanGUI._schedule_tracked_timeout, dummy)
    dummy._schedule_tracked_idle = types.MethodType(StudyPlanGUI._schedule_tracked_idle, dummy)
    dummy._consume_tracked_glib_source_attr = types.MethodType(StudyPlanGUI._consume_tracked_glib_source_attr, dummy)
    return dummy


def test_schedule_tracked_sources_register_and_consume(monkeypatch):
    class _FakeGLib:
        timeout_calls = []
        idle_calls = []

        @staticmethod
        def timeout_add(delay_ms, callback):
            _FakeGLib.timeout_calls.append((delay_ms, callback))
            return 41

        @staticmethod
        def idle_add(callback):
            _FakeGLib.idle_calls.append(callback)
            return 42

    monkeypatch.setattr(appmod, "GLib", _FakeGLib)
    dummy = _bind_tracking_helpers(
        types.SimpleNamespace(
            _core_runtime_shutdown=False,
            _glib_sources=set(),
            timeout_id=None,
            idle_id=None,
        )
    )

    timeout_id = StudyPlanGUI._schedule_tracked_timeout(dummy, "timeout_id", 120, lambda: False)
    idle_id = StudyPlanGUI._schedule_tracked_idle(dummy, "idle_id", lambda: False)

    assert timeout_id == 41
    assert idle_id == 42
    assert dummy.timeout_id == 41
    assert dummy.idle_id == 42
    assert dummy._glib_sources == {41, 42}

    StudyPlanGUI._consume_tracked_glib_source_attr(dummy, "timeout_id")
    StudyPlanGUI._consume_tracked_glib_source_attr(dummy, "idle_id")

    assert dummy.timeout_id is None
    assert dummy.idle_id is None
    assert dummy._glib_sources == set()


def test_update_recommendations_fallback_registers_timeout(monkeypatch):
    class _FakeGLib:
        @staticmethod
        def timeout_add(delay_ms, callback):
            assert delay_ms == 120
            assert callable(callback)
            return 77

        @staticmethod
        def idle_add(callback):
            return 0

    monkeypatch.setattr(appmod, "GLib", _FakeGLib)
    dummy = _bind_tracking_helpers(
        types.SimpleNamespace(
            _core_runtime_shutdown=False,
            _glib_sources=set(),
            _rec_debounce_id=None,
            _schedule_ui_refresh=lambda *args, **kwargs: False,
            _debounced_recommendations_refresh=lambda: False,
        )
    )

    StudyPlanGUI.update_recommendations(dummy)

    assert dummy._rec_debounce_id == 77
    assert dummy._glib_sources == {77}


def test_debounced_recommendations_skips_idle_when_shutdown(monkeypatch):
    class _FakeGLib:
        @staticmethod
        def timeout_add(delay_ms, callback):
            return 0

        @staticmethod
        def idle_add(callback):
            raise AssertionError("idle_add should not run during shutdown")

    monkeypatch.setattr(appmod, "GLib", _FakeGLib)
    dummy = _bind_tracking_helpers(
        types.SimpleNamespace(
            _core_runtime_shutdown=True,
            _glib_sources={55},
            _rec_debounce_id=55,
            _rec_update_source=None,
        )
    )

    result = StudyPlanGUI._debounced_recommendations_refresh(dummy)

    assert result is False
    assert dummy._rec_debounce_id is None
    assert dummy._glib_sources == set()
