"""Tests for studyplan.performance_monitor module."""
import time

import pytest

from studyplan.performance_monitor import PerformanceMetric, PerformanceMonitor


# ---------------------------------------------------------------------------
# PerformanceMetric
# ---------------------------------------------------------------------------


def test_metric_exceeded_true_when_over_threshold():
    m = PerformanceMetric(operation="op", duration_ms=150.0, timestamp="t", threshold_ms=100.0)
    assert m.exceeded is True


def test_metric_exceeded_false_when_under_threshold():
    m = PerformanceMetric(operation="op", duration_ms=50.0, timestamp="t", threshold_ms=100.0)
    assert m.exceeded is False


def test_metric_exceeded_false_exactly_at_threshold():
    m = PerformanceMetric(operation="op", duration_ms=100.0, timestamp="t", threshold_ms=100.0)
    assert m.exceeded is False


# ---------------------------------------------------------------------------
# PerformanceMonitor.record
# ---------------------------------------------------------------------------


def test_record_stores_metric():
    mon = PerformanceMonitor()
    mon.record("assess", 10.0, "2024-01-01T00:00:00")
    assert len(mon.metrics) == 1
    assert mon.metrics[0].operation == "assess"


def test_record_disabled_monitor_ignores():
    mon = PerformanceMonitor(enabled=False)
    mon.record("assess", 10.0, "ts")
    assert mon.metrics == []


def test_record_uses_known_threshold_for_operation():
    mon = PerformanceMonitor()
    # "state_validation" has threshold 10ms — 5ms should NOT exceed
    mon.record("state_validation", 5.0, "ts")
    assert not mon.metrics[0].exceeded


def test_record_uses_default_threshold_for_unknown_operation():
    mon = PerformanceMonitor()
    # Unknown op uses 100ms threshold
    mon.record("unknown_op", 50.0, "ts")
    assert not mon.metrics[0].exceeded
    mon.record("unknown_op", 150.0, "ts")
    assert mon.metrics[1].exceeded


# ---------------------------------------------------------------------------
# PerformanceMonitor.report
# ---------------------------------------------------------------------------


def test_report_empty_when_no_metrics():
    mon = PerformanceMonitor()
    assert mon.report() == {}


def test_report_counts_total_and_exceeded():
    mon = PerformanceMonitor()
    mon.record("assess", 5.0, "ts")   # under threshold (20ms)
    mon.record("assess", 500.0, "ts")  # over threshold
    report = mon.report()
    assert report["total_recorded"] == 2
    assert report["budget_exceeded"] == 1
    assert len(report["exceeded_ops"]) == 1
    assert report["exceeded_ops"][0][0] == "assess"


def test_report_no_exceeded_ops():
    mon = PerformanceMonitor()
    mon.record("assess", 1.0, "ts")
    report = mon.report()
    assert report["budget_exceeded"] == 0
    assert report["exceeded_ops"] == []


# ---------------------------------------------------------------------------
# PerformanceMonitor.context (context manager)
# ---------------------------------------------------------------------------


def test_context_manager_records_metric():
    mon = PerformanceMonitor()
    with mon.context("state_persistence"):
        time.sleep(0.001)
    assert len(mon.metrics) == 1
    assert mon.metrics[0].operation == "state_persistence"
    assert mon.metrics[0].duration_ms > 0


def test_context_manager_disabled_does_not_record():
    mon = PerformanceMonitor(enabled=False)
    with mon.context("assess"):
        pass
    assert mon.metrics == []


def test_context_manager_records_on_exception():
    """Even if the body raises, the metric should be recorded."""
    mon = PerformanceMonitor()
    with pytest.raises(ValueError):
        with mon.context("assess"):
            raise ValueError("boom")
    assert len(mon.metrics) == 1
