from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from studyplan_ui_runtime import UIFaultReport, UIRefreshScheduler, UIDialogLifecycle


def test_ui_fault_report_build_sets_metadata():
    report = UIFaultReport.build("dashboard", "RenderError", "boom", recoverable=True)
    assert report.section_id == "dashboard"
    assert report.error == "RenderError"
    assert report.details == "boom"
    assert report.recoverable is True
    assert isinstance(report.timestamp_iso, str)
    assert report.timestamp_iso


def test_ui_refresh_scheduler_coalesces_by_key():
    scheduled: dict[int, Callable[[], bool]] = {}
    source_counter = {"value": 0}

    def _schedule_timeout(delay_ms: int, cb):
        source_counter["value"] += 1
        scheduled[source_counter["value"]] = cb
        return source_counter["value"]

    def _schedule_idle(cb):
        source_counter["value"] += 1
        scheduled[source_counter["value"]] = cb
        return source_counter["value"]

    def _cancel(source_id: int):
        scheduled.pop(int(source_id), None)

    scheduler = UIRefreshScheduler(_schedule_timeout, _schedule_idle, _cancel)
    calls = {"count": 0}

    def _cb() -> bool:
        calls["count"] += 1
        return False

    assert scheduler.schedule("dashboard", _cb, delay_ms=50) is True
    assert scheduler.schedule("dashboard", _cb, delay_ms=50) is False
    assert len(scheduled) == 1

    _source_id, callback = next(iter(scheduled.items()))
    assert callback() is False
    assert scheduler.is_scheduled("dashboard") is False

    assert scheduler.schedule("dashboard", _cb, delay_ms=50) is True
    assert calls["count"] == 1


def test_dialog_lifecycle_close_all_calls_destroy():
    lifecycle = UIDialogLifecycle()

    @dataclass
    class _Dialog:
        closed: bool = False

        def destroy(self) -> None:
            self.closed = True

    one = _Dialog()
    two = _Dialog()
    lifecycle.register(one)
    lifecycle.register(two)
    assert lifecycle.count() == 2
    lifecycle.close_all()
    assert one.closed is True
    assert two.closed is True
    assert lifecycle.count() == 0
