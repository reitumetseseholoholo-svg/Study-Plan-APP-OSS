"""Tests for the CPU monitor module (cpu_monitor.py).

Covers: _collapse_python_stack, _thread_name, _thread_cpu_time,
and CPUMonitor construction.
"""

from __future__ import annotations

import os


from studyplan.components.performance.cpu_monitor import (
    _collapse_python_stack,
    _thread_name,
    _thread_cpu_time,
    CPUMonitor,
    _ENABLED,
)


# ---------------------------------------------------------------------------
# _collapse_python_stack
# ---------------------------------------------------------------------------


def test_collapse_python_stack_empty() -> None:
    assert _collapse_python_stack("") == "?"
    assert _collapse_python_stack(None) == "?"


def test_collapse_python_stack_whitespace() -> None:
    assert _collapse_python_stack("   ") == "?"


def test_collapse_python_stack_extracts_file_line() -> None:
    stack = (
        '  File "/home/user/app.py", line 42, in my_func\n'
        "    result = do_something()\n"
        '  File "/home/user/utils.py", line 10, in do_something\n'
        "    return x + y\n"
    )
    result = _collapse_python_stack(stack)
    assert "app.py" in result or "utils.py" in result
    assert len(result) <= 120


def test_collapse_python_stack_truncates_long_lines() -> None:
    stack = '  File "' + "/x" * 200 + '", line 1, in f\n    pass\n'
    result = _collapse_python_stack(stack)
    assert len(result) <= 120


# ---------------------------------------------------------------------------
# _thread_name (via /proc/self/task/)
# ---------------------------------------------------------------------------


def test_thread_name_known() -> None:
    name = _thread_name(os.getpid())
    if name is not None:
        assert isinstance(name, str)
        assert len(name) > 0


def test_thread_name_nonexistent_tid() -> None:
    name = _thread_name(999999999)
    assert name is None


# ---------------------------------------------------------------------------
# _thread_cpu_time
# ---------------------------------------------------------------------------


def test_thread_cpu_time_returns_dict() -> None:
    result = _thread_cpu_time()
    assert isinstance(result, dict)
    if result:
        for tid, cpu_sec in result.items():
            assert isinstance(tid, int)
            assert isinstance(cpu_sec, float) and cpu_sec >= 0


def test_thread_cpu_time_includes_main_thread() -> None:
    result = _thread_cpu_time()
    assert len(result) > 0


# ---------------------------------------------------------------------------
# CPUMonitor
# ---------------------------------------------------------------------------


def test_cpu_monitor_init() -> None:
    monitor = CPUMonitor(interval_s=2.0)
    assert monitor.interval == 2.0
    assert monitor._stop_event is not None
    assert monitor._thread is None
    assert monitor._sample_count == 0


def test_cpu_monitor_clamps_interval() -> None:
    monitor = CPUMonitor(interval_s=0.1)
    assert monitor.interval >= 1.0  # clamped to min


def test_cpu_monitor_start_stop_disabled() -> None:
    """When _ENABLED is False, start() is a no-op."""
    monitor = CPUMonitor()
    monitor.start()
    assert monitor._thread is None or not monitor._thread.is_alive()
    monitor.stop()


def test_cpu_monitor_stop_without_start() -> None:
    """stop() should not crash if never started."""
    monitor = CPUMonitor()
    monitor.stop()  # no-op


# ---------------------------------------------------------------------------
# _ENABLED constant
# ---------------------------------------------------------------------------


def test_enabled_is_bool() -> None:
    assert isinstance(_ENABLED, bool)
