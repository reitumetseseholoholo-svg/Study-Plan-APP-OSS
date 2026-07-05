# pyright: reportArgumentType=false

import json
import os
import threading
import time
import types
import unittest.mock as _mock

from studyplan_app import StudyPlanGUI


def _fake_glib():
    """Return a fake GLib module that runs idle_add callbacks immediately."""

    class _FakeGLib:
        PRIORITY_LOW = 300

        @staticmethod
        def idle_add(cb, priority=300):
            cb()
            return 0

        @staticmethod
        def timeout_add(interval_ms, cb, *args):
            cb(*args) if args else cb()
            return 99

        @staticmethod
        def timeout_add_seconds(interval, cb):
            return 99

        @staticmethod
        def source_remove(sid):
            return True

    return _FakeGLib


# =====================================================================
# Slow action dispatch (gap_drill_generate) — background thread routing
# =====================================================================


def _slow_action_dummy(action="gap_drill_generate"):
    """Build a dummy with fields needed by the slow-action dispatch."""
    now_base = float(time.monotonic())
    executed = []
    background_spawned = []
    metrics_calls = []

    def _fake_execute(action_plan):
        executed.append(True)
        return True, f"{action} completed"

    dummy = types.SimpleNamespace(
        _ai_tutor_pending_suggestion={"action": action, "topic": "", "source": "autopilot"},
        _ai_tutor_global_autopilot_last_action_at=now_base - 30.0,
        _ai_tutor_recent_action_log=[],
        _ai_tutor_autopilot_stats={},
        _ai_tutor_global_autopilot_action_window=[],
        _ai_tutor_global_quiet_until=0.0,
        _executed=executed,
        _metrics_calls=metrics_calls,
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: None,
        _record_ai_tutor_recent_action=lambda *a, **kw: None,
        _record_ai_tutor_action_budget_use=lambda _ts: None,
        send_notification=lambda *a, **kw: None,
        _refresh_ai_tutor_autopilot_surface=lambda: None,
        _start_managed_background_thread=lambda target, **kw: background_spawned.append(target),
    )
    dummy._execute_ai_tutor_action = _fake_execute
    dummy._finish_accept_suggestion = lambda *a, **kw: None
    dummy._sanitize_ai_tutor_recent_action_log = lambda rows, limit=10: list(rows or [])[-limit:]

    def _record_metrics(updates, persist=False):
        metrics_calls.append(dict(updates or {}))

    dummy._record_ai_tutor_autopilot_metrics = _record_metrics
    dummy._background_spawned = background_spawned
    return dummy


def test_accept_slow_action_dispatches_to_background():
    """gap_drill_generate must be dispatched to a background thread, not executed synchronously."""
    dummy = _slow_action_dummy("gap_drill_generate")
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)
    assert len(dummy._background_spawned) == 1
    assert len(dummy._executed) == 0


def test_accept_slow_action_fast_actions_stay_synchronous():
    """Non-slow actions like focus_start must execute synchronously."""
    dummy = _slow_action_dummy("focus_start")
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)
    assert len(dummy._background_spawned) == 0
    assert len(dummy._executed) == 1


def test_accept_slow_action_worker_calls_finish_on_success():
    """The background worker must call _finish_accept_suggestion when execution succeeds."""
    dummy = _slow_action_dummy("gap_drill_generate")
    finish_called = []
    dummy._finish_accept_suggestion = lambda *a, **kw: finish_called.append((a, kw))

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)
        # Run the background worker — GLib.idle_add inside it will run finish synchronously
        dummy._background_spawned[0]()

    assert len(finish_called) == 1
    # finish_called = [(a, kw)] where a = (action_plan, source, now_ts, message)
    assert finish_called[0][0][0].get("action") == "gap_drill_generate"


def test_accept_slow_action_worker_skips_finish_on_failure():
    """The background worker must NOT call _finish_accept_suggestion when execution fails."""
    dummy = _slow_action_dummy("gap_drill_generate")
    finish_called = []
    dummy._finish_accept_suggestion = lambda *a, **kw: finish_called.append((a, kw))
    dummy._execute_ai_tutor_action = lambda action_plan: (False, "blocked")

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)
        dummy._background_spawned[0]()

    assert len(finish_called) == 0


def test_accept_slow_action_worker_exception_logged():
    """Exceptions in the background worker must be caught and logged."""
    dummy = _slow_action_dummy("gap_drill_generate")
    dummy._execute_ai_tutor_action = lambda action_plan: (_ for _ in ()).throw(RuntimeError("boom"))

    captured = []

    import studyplan_app as _appmod

    original_log = _appmod.log
    _appmod.log = type("_Log", (), {"warning": lambda self, msg, **kw: captured.append(msg)})()
    try:
        with _mock.patch("studyplan_app.GLib", _fake_glib()):
            StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)
            dummy._background_spawned[0]()  # should not raise
    finally:
        _appmod.log = original_log

    assert len(captured) >= 1
    assert any("background action execution failed" in str(c) for c in captured)


def test_accept_slow_action_sends_notification_on_start():
    """A notification must be sent immediately when dispatching a slow action."""
    dummy = _slow_action_dummy("gap_drill_generate")
    notifications = []
    dummy.send_notification = lambda title, msg: notifications.append((title, msg))

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)

    assert len(notifications) == 1
    assert "Starting" in str(notifications[0][1])


# =====================================================================
# _finish_accept_suggestion
# =====================================================================


def test_finish_accept_suggestion_updates_all_state():
    """Must record actions, update stats, set quiet window, clear pending."""
    now_base = float(time.monotonic())
    recent_action_kwargs = []
    stats_calls = []
    budget_used = []
    pending_cleared = []

    dummy = types.SimpleNamespace(
        _ai_tutor_autopilot_stats={"autopilot_suggestion_accepted_count": 2, "autopilot_action_executed_count": 5},
        _ai_tutor_global_autopilot_last_action_at=0.0,
        _ai_tutor_global_quiet_until=0.0,
        _ai_tutor_global_autopilot_action_window=[],
        _record_ai_tutor_recent_action=lambda *a, **kw: recent_action_kwargs.append(kw),
        _record_ai_tutor_autopilot_metrics=lambda updates, persist=False: stats_calls.append((updates, persist)),
        _record_ai_tutor_action_budget_use=lambda ts: budget_used.append(ts),
        send_notification=lambda title, message: None,
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: pending_cleared.append(True),
    )

    StudyPlanGUI._finish_accept_suggestion(dummy, {"action": "focus_start"}, "autopilot", "Started focus session.")

    # Recent action recorded twice (suggested_accepted + executed)
    assert len(recent_action_kwargs) == 2
    assert recent_action_kwargs[0].get("outcome") == "suggested_accepted"
    assert recent_action_kwargs[1].get("outcome") == "executed"

    # Stats incremented
    assert len(stats_calls) == 1
    upd = stats_calls[0][0]
    assert upd["autopilot_suggestion_accepted_count"] == 3
    assert upd["autopilot_action_executed_count"] == 6
    assert upd["autopilot_last_block_reason"] == ""

    # Budget recorded
    assert len(budget_used) == 1

    # Last action timestamp updated
    assert dummy._ai_tutor_global_autopilot_last_action_at > now_base - 1.0

    # Quiet window set (at least 30s)
    assert dummy._ai_tutor_global_quiet_until > float(time.monotonic()) + 25.0

    # Pending cleared
    assert len(pending_cleared) == 1


def test_finish_accept_suggestion_sends_notification():
    """Must send a notification with the action message."""
    notifications = []
    dummy = types.SimpleNamespace(
        _ai_tutor_autopilot_stats={},
        _ai_tutor_global_autopilot_last_action_at=0.0,
        _ai_tutor_global_quiet_until=0.0,
        _ai_tutor_global_autopilot_action_window=[],
        _record_ai_tutor_recent_action=lambda *a, **kw: None,
        _record_ai_tutor_autopilot_metrics=lambda updates, persist=False: None,
        _record_ai_tutor_action_budget_use=lambda ts: None,
        send_notification=lambda title, message: notifications.append((title, message)),
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: None,
    )

    StudyPlanGUI._finish_accept_suggestion(dummy, {}, "", "Done!")
    assert len(notifications) == 1
    assert "Done!" in str(notifications[0])


# =====================================================================
# Accept/dismiss suggestion — edge cases
# =====================================================================


def _basic_dummy():
    now_base = float(time.monotonic())
    return types.SimpleNamespace(
        _ai_tutor_pending_suggestion={"action": "focus_start", "topic": "", "source": "autopilot"},
        _ai_tutor_global_autopilot_last_action_at=now_base - 30.0,
        _ai_tutor_recent_action_log=[],
        _ai_tutor_autopilot_stats={},
        _ai_tutor_global_autopilot_action_window=[],
        _ai_tutor_global_quiet_until=0.0,
        _record_ai_tutor_autopilot_metrics=lambda *a, **kw: None,
        _sanitize_ai_tutor_recent_action_log=lambda rows, limit=10: list(rows or [])[-limit:],
        _execute_ai_tutor_action=lambda *a: (True, "done"),
        _record_ai_tutor_recent_action=lambda *a, **kw: None,
        _record_ai_tutor_action_budget_use=lambda _ts: None,
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: None,
        send_notification=lambda *a, **kw: None,
        _refresh_ai_tutor_autopilot_surface=lambda: None,
        _finish_accept_suggestion=lambda *a, **kw: None,
        _start_managed_background_thread=lambda *a, **kw: None,
    )


def test_accept_suggestion_noop_when_no_pending():
    """_accept_ai_tutor_pending_suggestion must silently return when no pending."""
    dummy = _basic_dummy()
    dummy._ai_tutor_pending_suggestion = None
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)


def test_accept_suggestion_noop_when_pending_not_dict():
    """_accept_ai_tutor_pending_suggestion must silently return when pending is not a dict."""
    dummy = _basic_dummy()
    dummy._ai_tutor_pending_suggestion = "invalid"
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)


def test_accept_suggestion_cooldown_blocks():
    """<20s cooldown blocks synchronous accept."""
    now_base = float(time.monotonic())
    metrics_calls = []
    dummy = _basic_dummy()
    dummy._ai_tutor_global_autopilot_last_action_at = now_base - 5.0
    dummy._record_ai_tutor_autopilot_metrics = lambda updates, persist=False: metrics_calls.append(updates)

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)

    reasons = [m.get("autopilot_last_block_reason") for m in metrics_calls if m.get("autopilot_last_block_reason")]
    assert "action_cooldown" in reasons


def test_accept_suggestion_duplicate_guard_blocks():
    """<60s same action+topic blocks synchronous accept."""
    now_base = float(time.monotonic())
    metrics_calls = []
    dummy = _basic_dummy()
    dummy._ai_tutor_global_autopilot_last_action_at = now_base - 30.0
    dummy._ai_tutor_recent_action_log = [
        {
            "action": "focus_start",
            "topic": "",
            "outcome": "executed",
            "monotonic_at": now_base - 5.0,
            "source": "autopilot",
            "reason": "",
            "at": "",
        }
    ]
    dummy._record_ai_tutor_autopilot_metrics = lambda updates, persist=False: metrics_calls.append(updates)

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._accept_ai_tutor_pending_suggestion(dummy)

    reasons = [m.get("autopilot_last_block_reason") for m in metrics_calls if m.get("autopilot_last_block_reason")]
    assert "action_duplicate_guard" in reasons


def test_dismiss_suggestion_noop_when_no_pending():
    """_dismiss_ai_tutor_pending_suggestion must silently return when no pending."""
    dummy = types.SimpleNamespace(
        _ai_tutor_pending_suggestion=None,
        _ai_tutor_recent_action_log=[],
        _ai_tutor_autopilot_stats={},
        _record_ai_tutor_recent_action=lambda *a, **kw: None,
        _record_ai_tutor_autopilot_metrics=lambda *a, **kw: None,
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: None,
        _refresh_ai_tutor_autopilot_surface=lambda: None,
    )
    StudyPlanGUI._dismiss_ai_tutor_pending_suggestion(dummy)


def test_dismiss_suggestion_records_dismissed():
    """_dismiss_ai_tutor_pending_suggestion must record suggested_dismissed."""
    recent_outcomes = []
    cleared = []
    dummy = types.SimpleNamespace(
        _ai_tutor_pending_suggestion={"action": "focus_start", "source": "autopilot"},
        _ai_tutor_recent_action_log=[],
        _ai_tutor_autopilot_stats={},
        _record_ai_tutor_recent_action=lambda plan, outcome, source: recent_outcomes.append(outcome),
        _record_ai_tutor_autopilot_metrics=lambda *a, **kw: None,
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: cleared.append(True),
        _refresh_ai_tutor_autopilot_surface=lambda: None,
    )
    StudyPlanGUI._dismiss_ai_tutor_pending_suggestion(dummy)
    assert recent_outcomes == ["suggested_dismissed"]
    assert len(cleared) == 1


def test_dismiss_suggestion_increments_dismissed_count():
    """_dismiss_ai_tutor_pending_suggestion must increment dismissed_count metric."""
    metrics_calls = []
    dummy = types.SimpleNamespace(
        _ai_tutor_pending_suggestion={"action": "focus_start"},
        _ai_tutor_recent_action_log=[],
        _ai_tutor_autopilot_stats={},
        _record_ai_tutor_recent_action=lambda *a, **kw: None,
        _record_ai_tutor_autopilot_metrics=lambda updates, persist=False: metrics_calls.append(updates),
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: None,
        _refresh_ai_tutor_autopilot_surface=lambda: None,
    )
    StudyPlanGUI._dismiss_ai_tutor_pending_suggestion(dummy)
    assert any(m.get("autopilot_suggestion_dismissed_count") == 1 for m in metrics_calls)


# =====================================================================
# Decision gate — edge cases
# =====================================================================


def _decision_dummy():
    """Build a dummy for _should_request_global_ai_tutor_decision tests."""

    def _build_event_sig(snapshot):
        """Simple deterministic hash for testing."""
        raw = json.dumps(snapshot, sort_keys=True, default=str)
        import hashlib

        return hashlib.sha1(raw.encode()).hexdigest()

    dummy = types.SimpleNamespace(
        _ai_tutor_global_last_event_sig="",
        _ai_tutor_global_last_decision_at=0.0,
        _ai_tutor_global_quiet_until=0.0,
        _ai_tutor_recent_action_log=[],
        _ai_tutor_autopilot_stats={},
        _sanitize_ai_tutor_recent_action_log=lambda rows, limit=5: list(rows or [])[-limit:],
    )
    dummy._build_ai_tutor_autopilot_event_signature = types.MethodType(
        StudyPlanGUI._build_ai_tutor_autopilot_event_signature, dummy
    )
    return dummy


def test_decision_gate_first_run_requests():
    """First run (sig=='') must produce (True, 'first_run')."""
    dummy = _decision_dummy()
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    should, reason, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    assert should is True
    assert reason == "first_run"
    assert len(sig) == 40  # SHA-1 hex


def test_decision_gate_state_change_requests():
    """State change must produce (True, 'state_changed')."""
    dummy = _decision_dummy()
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    _, _, sig1 = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    dummy._ai_tutor_global_last_event_sig = sig1
    dummy._ai_tutor_global_last_decision_at = float(time.monotonic())

    snapshot2 = dict(snapshot, current_topic="B")
    should, reason, sig2 = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot2)
    assert should is True
    assert reason == "state_changed"
    assert sig2 != sig1


def test_decision_gate_no_change_suppresses():
    """No state change produces (False, 'no_material_change')."""
    dummy = _decision_dummy()
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    _, _, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    dummy._ai_tutor_global_last_event_sig = sig
    dummy._ai_tutor_global_last_decision_at = float(time.monotonic())

    should, reason, _ = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    assert should is False
    assert reason == "no_material_change"


def test_decision_gate_repeated_suggestion_backoff_3_suggested():
    """3+ consecutive 'suggested' outcomes for same action must trigger backoff."""
    now_base = float(time.monotonic())
    dummy = _decision_dummy()
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    _, _, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    dummy._ai_tutor_global_last_event_sig = sig
    dummy._ai_tutor_global_last_decision_at = now_base

    dummy._ai_tutor_recent_action_log = [
        {
            "action": "focus_start",
            "topic": "",
            "outcome": "suggested",
            "monotonic_at": now_base - float(30 * i),
            "source": "autopilot",
            "reason": "",
            "at": "",
        }
        for i in [2, 1, 0]
    ]

    should, reason, _ = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    assert should is False
    assert reason == "repeated_suggestion_backoff"


def test_decision_gate_repeated_backoff_2_suggested_does_not_fire():
    """2 consecutive 'suggested' outcomes must NOT trigger backoff (backoff needs 3+)."""
    now_base = float(time.monotonic())
    dummy = _decision_dummy()
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    _, _, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    dummy._ai_tutor_global_last_event_sig = sig
    # Set last_decision_at old enough that periodic_refresh fires
    dummy._ai_tutor_global_last_decision_at = now_base - 300.0

    dummy._ai_tutor_recent_action_log = [
        {
            "action": "focus_start",
            "topic": "",
            "outcome": "suggested",
            "monotonic_at": now_base - 30.0,
            "source": "autopilot",
            "reason": "",
            "at": "",
        },
        {
            "action": "focus_start",
            "topic": "",
            "outcome": "suggested",
            "monotonic_at": now_base - 60.0,
            "source": "autopilot",
            "reason": "",
            "at": "",
        },
    ]

    should, reason, _ = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    assert should is True
    assert reason == "periodic_refresh"


def test_decision_gate_backoff_does_not_fire_for_mixed_outcomes():
    """Non-'suggested' outcomes break the trailing streak, preventing backoff."""
    now_base = float(time.monotonic())
    dummy = _decision_dummy()
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    _, _, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    dummy._ai_tutor_global_last_event_sig = sig
    # Set last_decision_at old enough that periodic_refresh fires after backoff is skipped
    dummy._ai_tutor_global_last_decision_at = now_base - 300.0

    dummy._ai_tutor_recent_action_log = [
        {
            "action": "focus_start",
            "topic": "",
            "outcome": "suggested",
            "monotonic_at": now_base - 30.0,
            "source": "autopilot",
            "reason": "",
            "at": "",
        },
        {
            "action": "focus_start",
            "topic": "",
            "outcome": "suggested_accepted",
            "monotonic_at": now_base - 60.0,
            "source": "autopilot",
            "reason": "",
            "at": "",
        },
        {
            "action": "focus_start",
            "topic": "",
            "outcome": "suggested",
            "monotonic_at": now_base - 90.0,
            "source": "autopilot",
            "reason": "",
            "at": "",
        },
    ]

    should, reason, _ = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    assert should is True
    assert reason == "periodic_refresh"


def test_decision_gate_refresh_seconds_clamped_low():
    """ENV values below 45 must be clamped to 45."""
    os.environ["STUDYPLAN_AI_TUTOR_AUTOPILOT_REFRESH_SECONDS"] = "10"
    try:
        now_base = float(time.monotonic())
        dummy = _decision_dummy()
        snapshot = {
            "current_topic": "A",
            "focus_trend_14d": {},
            "must_review_due": 0,
            "overdue_srs_count": 0,
            "new_srs_count": 0,
            "tutor_dialog_open": False,
            "pomodoro_active": False,
            "pomodoro_paused": False,
        }
        _, _, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
        dummy._ai_tutor_global_last_event_sig = sig
        dummy._ai_tutor_global_last_decision_at = now_base - 50.0  # 50s ago, > 45s clamp

        should, reason, _ = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
        # refresh_seconds clamped to 45, so 50s > 45s should trigger periodic_refresh
        assert should is True
        assert reason == "periodic_refresh"
    finally:
        os.environ.pop("STUDYPLAN_AI_TUTOR_AUTOPILOT_REFRESH_SECONDS", None)


def test_decision_gate_no_change_when_last_decision_recent():
    """When no state change and last decision was recent, must return no_material_change."""
    now_base = float(time.monotonic())
    dummy = _decision_dummy()
    # Use the real event signature so no "state_changed" is triggered
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    _, _, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    dummy._ai_tutor_global_last_event_sig = sig
    dummy._ai_tutor_global_last_decision_at = now_base - 10.0  # too recent for periodic_refresh

    should, reason, _ = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    assert should is False
    assert reason == "no_material_change"


def test_decision_gate_periodic_refresh_triggers_after_timeout():
    """periodic_refresh must trigger when last_decision_at is old enough."""
    now_base = float(time.monotonic())
    dummy = _decision_dummy()
    snapshot = {
        "current_topic": "A",
        "focus_trend_14d": {},
        "must_review_due": 0,
        "overdue_srs_count": 0,
        "new_srs_count": 0,
        "tutor_dialog_open": False,
        "pomodoro_active": False,
        "pomodoro_paused": False,
    }
    _, _, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    dummy._ai_tutor_global_last_event_sig = sig
    dummy._ai_tutor_global_last_decision_at = now_base - 300.0  # 5 min ago, > 120s refresh

    should, reason, _ = StudyPlanGUI._should_request_global_ai_tutor_decision(dummy, snapshot)
    assert should is True
    assert reason == "periodic_refresh"


# =====================================================================
# Autopilot tick — edge cases
# =====================================================================


def _tick_base_dummy():
    return types.SimpleNamespace(
        ai_tutor_autopilot_enabled=True,
        ai_tutor_autopilot_paused=False,
        _dialog_smoke_mode=False,
        _ai_tutor_global_autopilot_busy=False,
        _ai_tutor_autopilot_lock=threading.Lock(),
        _ai_tutor_global_last_event_sig="",
        _ai_tutor_global_last_decision_at=0.0,
        _ai_tutor_global_quiet_until=0.0,
        _ai_tutor_global_last_coaching_at=0.0,
        _ai_tutor_recent_action_log=[],
        _ai_tutor_autopilot_stats={},
        _ai_tutor_global_autopilot_action_window=[],
        _effective_ai_tutor_autonomy_mode=lambda: "cockpit",
        _build_ai_tutor_autopilot_snapshot=lambda: {"current_topic": "A"},
        _should_request_global_ai_tutor_decision=lambda *a: (True, "first_run", "abcdef1234"),
        _ai_tutor_user_turn_busy=lambda: False,
        _request_ai_tutor_action_plan=lambda *a: ({"action": "focus_start", "requires_confirmation": False}, None),
        _can_auto_execute_ai_tutor_action=lambda action, mode, confirm: True,
        _consume_global_ai_tutor_action_budget=lambda now_ts: True,
        _normalize_ai_tutor_action_plan=lambda decision, snapshot: (decision, None),
        _execute_ai_tutor_action=lambda *a: (True, "done"),
        _record_ai_tutor_recent_action=lambda *a, **kw: None,
        _record_ai_tutor_action_budget_use=lambda ts: None,
        _record_ai_tutor_autopilot_metrics=lambda updates=None, persist=False: None,
        _record_ai_tutor_autopilot_error=lambda msg, from_worker: None,
        _emit_global_ai_tutor_nudge=lambda severity, message: None,
        _set_ai_tutor_pending_suggestion=lambda action_plan, *, source: None,
        _clear_ai_tutor_pending_suggestion=lambda *a, **kw: None,
        _refresh_ai_tutor_autopilot_surface=lambda: None,
        send_notification=lambda title, message: None,
        _remove_glib_source=lambda sid: None,
        _register_glib_source=lambda sid: None,
        _sanitize_ai_tutor_recent_action_log=lambda *a, **kw: [],
    )


def test_autopilot_tick_busy_skips():
    """Tick must skip when busy flag is set."""
    dummy = _tick_base_dummy()
    dummy._ai_tutor_global_autopilot_busy = True

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        result = StudyPlanGUI._global_ai_tutor_autopilot_tick(dummy)

    assert result is True  # keep timer alive


def test_autopilot_tick_disabled_stops_timer():
    """Tick must return False (stop timer) when autopilot is disabled."""
    dummy = _tick_base_dummy()
    dummy.ai_tutor_autopilot_enabled = False
    result = StudyPlanGUI._global_ai_tutor_autopilot_tick(dummy)
    assert result is False


def test_autopilot_tick_paused_skips():
    """Tick must return True (keep timer) when paused, without processing."""
    dummy = _tick_base_dummy()
    dummy.ai_tutor_autopilot_paused = True

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        result = StudyPlanGUI._global_ai_tutor_autopilot_tick(dummy)

    assert result is True


def test_autopilot_tick_smoke_mode_skips():
    """Tick must skip when in smoke test mode."""
    dummy = _tick_base_dummy()
    dummy._dialog_smoke_mode = True

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        result = StudyPlanGUI._global_ai_tutor_autopilot_tick(dummy)

    assert result is True


def test_autopilot_tick_records_metrics_on_success():
    """Successful autopilot execution must record metrics with cleared block_reason."""
    metrics_calls = []
    dummy = _tick_base_dummy()
    dummy._record_ai_tutor_autopilot_metrics = lambda updates, persist=False: metrics_calls.append(updates)
    dummy._can_auto_execute_ai_tutor_action = lambda action, mode, confirm: True

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        with _mock.patch.object(StudyPlanGUI, "_start_managed_background_thread", lambda self, target, **kw: target()):
            StudyPlanGUI._global_ai_tutor_autopilot_tick(dummy)

    # The last metrics call should have empty block_reason on success
    assert len(metrics_calls) >= 1
    last = metrics_calls[-1]
    assert last.get("block_reason", "") in ("", None), f"expected empty block_reason, got {last.get('block_reason')}"


def test_autopilot_tick_pending_suggestion_when_not_auto():
    """When action cannot be auto-executed, must set pending suggestion instead."""
    suggestion_set = []
    dummy = _tick_base_dummy()
    dummy._can_auto_execute_ai_tutor_action = lambda action, mode, confirm: False
    dummy._set_ai_tutor_pending_suggestion = lambda action_plan, *, source: suggestion_set.append((action_plan, source))

    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        with _mock.patch.object(StudyPlanGUI, "_start_managed_background_thread", lambda self, target, **kw: target()):
            StudyPlanGUI._global_ai_tutor_autopilot_tick(dummy)

    assert len(suggestion_set) >= 1


# =====================================================================
# Coaching tick — edge cases
# =====================================================================


def _coaching_dummy(**overrides):
    """Build a dummy for coaching tick tests, with overrides for specific fields."""
    notifications_sent = []
    registered = []
    removed = []

    dummy = types.SimpleNamespace(
        ai_tutor_autopilot_enabled=True,
        ai_tutor_nudges_enabled=True,
        local_llm_enabled=True,
        ai_tutor_autopilot_paused=False,
        module_title="FM",
        _ai_tutor_global_coaching_id=77,
        _ai_tutor_global_coaching_last_at=0.0,
        _ai_tutor_global_quiet_until=0.0,
        _remove_glib_source=lambda sid: removed.append(sid),
        _register_glib_source=lambda sid: registered.append(sid),
        _select_local_llm_model=lambda purpose=None: ("test-model", ""),
        _ollama_generate_text=lambda model, prompt, **kw: ("Keep going, you are making steady progress!", None),
        _build_ai_tutor_autopilot_snapshot=lambda: {
            "current_topic": "investment_appraisal",
            "focus_trend_14d": {"integrity_pct": 75},
        },
        engine=types.SimpleNamespace(
            _get_student_bio=lambda: {"study": {"total_minutes": 30}},
        ),
        send_notification=lambda title, message: notifications_sent.append((title, message)),
        _start_managed_background_thread=lambda target: target() or True,
        _registered=registered,
        _removed=removed,
        _notifications_sent=notifications_sent,
    )
    for k, v in overrides.items():
        setattr(dummy, k, v)

    dummy._global_ai_tutor_coaching_tick = types.MethodType(StudyPlanGUI._global_ai_tutor_coaching_tick, dummy)
    dummy._next_coaching_category = types.MethodType(StudyPlanGUI._next_coaching_category, dummy)
    dummy._record_coaching_message = types.MethodType(StudyPlanGUI._record_coaching_message, dummy)
    dummy._recent_coaching_messages = types.MethodType(StudyPlanGUI._recent_coaching_messages, dummy)
    dummy._build_coaching_fallback = types.MethodType(StudyPlanGUI._build_coaching_fallback, dummy)
    return dummy


def test_coaching_tick_skips_when_pomodoro_active():
    """Coaching must skip and update last_at when pomodoro is active."""
    dummy = _coaching_dummy()
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": True,
        "active_session_kind": "",
        "idle_seconds": 0,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert dummy._ai_tutor_global_coaching_last_at > 0.0, "last_at must be updated"
    assert len(dummy._notifications_sent) == 0, "no notification should be sent"


def test_coaching_tick_skips_when_quiz_session():
    """Coaching must skip and update last_at when quiz/review session is active."""
    dummy = _coaching_dummy()
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": False,
        "active_session_kind": "quiz",
        "idle_seconds": 0,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert dummy._ai_tutor_global_coaching_last_at > 0.0
    assert len(dummy._notifications_sent) == 0


def test_coaching_tick_skips_when_recall_session():
    """Coaching must skip when recall session is active."""
    dummy = _coaching_dummy()
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": False,
        "active_session_kind": "recall",
        "idle_seconds": 0,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert dummy._ai_tutor_global_coaching_last_at > 0.0
    assert len(dummy._notifications_sent) == 0


def test_coaching_tick_skips_when_section_c_session():
    """Coaching must skip when section_c session is active."""
    dummy = _coaching_dummy()
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": False,
        "active_session_kind": "section_c",
        "idle_seconds": 0,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert dummy._ai_tutor_global_coaching_last_at > 0.0
    assert len(dummy._notifications_sent) == 0


def test_coaching_tick_skips_when_idle_15_min():
    """Coaching must skip when idle >= 900 seconds."""
    dummy = _coaching_dummy()
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": False,
        "active_session_kind": "",
        "idle_seconds": 900,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert dummy._ai_tutor_global_coaching_last_at > 0.0
    assert len(dummy._notifications_sent) == 0


def test_coaching_tick_proceeds_when_idle_below_15_min():
    """Coaching must proceed when idle < 900 seconds."""
    dummy = _coaching_dummy()
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": False,
        "active_session_kind": "",
        "idle_seconds": 10,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert len(dummy._notifications_sent) >= 1, "notification should be sent when not idle"


def test_coaching_tick_falls_back_on_short_llm_response():
    """Coaching must use fallback when LLM response < 10 chars."""
    dummy = _coaching_dummy()
    dummy._ollama_generate_text = lambda model, prompt, **kw: ("Hi", None)  # < 10 chars
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": False,
        "active_session_kind": "",
        "idle_seconds": 10,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert len(dummy._notifications_sent) >= 1, "fallback notification must be sent"


def test_coaching_tick_boundary_idle_899_does_not_skip():
    """Idle seconds = 899 must NOT skip (boundary test)."""
    dummy = _coaching_dummy()
    dummy._build_ai_tutor_autopilot_snapshot = lambda: {
        "current_topic": "A",
        "focus_trend_14d": {"integrity_pct": 75},
        "pomodoro_active": False,
        "active_session_kind": "",
        "idle_seconds": 899,
        "days_to_exam": None,
    }
    with _mock.patch("studyplan_app.GLib", _fake_glib()):
        StudyPlanGUI._global_ai_tutor_coaching_tick(dummy)

    assert len(dummy._notifications_sent) >= 1, "idle 899 should NOT skip coaching"
