"""Tests for the performance profiler (profiler.py).

Covers: PerformanceMetric, PerformanceAlert, PerformanceProfiler
profile_operation, alerts, reports, percentiles, recommendations,
disabled mode, and the decorator.
"""

from __future__ import annotations

import time

import pytest

from studyplan.components.performance.profiler import (
    PerformanceAlert,
    PerformanceMetric,
    PerformanceProfiler,
    create_performance_profiler,
    profiled_operation,
)


# ---------------------------------------------------------------------------
# PerformanceMetric
# ---------------------------------------------------------------------------


def test_metric_defaults() -> None:
    m = PerformanceMetric(operation_name="op", duration_ms=10.0, timestamp=100.0, success=True)
    assert m.error_message is None
    assert m.metadata == {}


def test_metric_with_error() -> None:
    m = PerformanceMetric(operation_name="op", duration_ms=10.0, timestamp=100.0, success=False, error_message="fail")
    assert m.error_message == "fail"


# ---------------------------------------------------------------------------
# PerformanceAlert
# ---------------------------------------------------------------------------


def test_alert_defaults() -> None:
    a = PerformanceAlert(
        operation_name="op",
        threshold_ms=100.0,
        actual_duration_ms=200.0,
        timestamp=100.0,
        severity="warning",
        message="slow",
    )
    assert a.severity == "warning"


# ---------------------------------------------------------------------------
# PerformanceProfiler — basic
# ---------------------------------------------------------------------------


def test_profiler_default_config() -> None:
    p = PerformanceProfiler({})
    assert p.enabled is True
    assert p.alert_thresholds == {}
    assert p.metrics_window_size == 100
    assert p.alert_window_size == 50


def test_profiler_custom_config() -> None:
    config = {
        "enabled": True,
        "alert_thresholds": {"op_a": 100.0},
        "metrics_window_size": 10,
        "alert_window_size": 5,
    }
    p = PerformanceProfiler(config)
    assert p.alert_thresholds == {"op_a": 100.0}
    assert p.metrics_window_size == 10
    assert p.alert_window_size == 5


# ---------------------------------------------------------------------------
# profile_operation
# ---------------------------------------------------------------------------


def test_profile_operation_success() -> None:
    p = PerformanceProfiler({})

    def add(a: int, b: int) -> int:
        return a + b

    result = p.profile_operation("add", add, 3, 4)
    assert result == 7


def test_profile_operation_records_metric() -> None:
    p = PerformanceProfiler({})

    def add(a: int, b: int) -> int:
        return a + b

    p.profile_operation("add", add, 1, 2)
    stats = p.get_operation_stats("add")
    assert stats is not None
    assert stats["total_calls"] == 1
    assert stats["success_rate"] == 1.0


def test_profile_operation_failure() -> None:
    p = PerformanceProfiler({})

    def fail() -> None:
        raise ValueError("oops")

    with pytest.raises(ValueError, match="oops"):
        p.profile_operation("fail", fail)

    stats = p.get_operation_stats("fail")
    assert stats is not None
    assert stats["total_calls"] == 1
    assert stats["success_rate"] == 0.0
    assert stats["error_count"] == 1


def test_profile_operation_disabled() -> None:
    p = PerformanceProfiler({"enabled": False})

    def add(a: int, b: int) -> int:
        return a + b

    result = p.profile_operation("add", add, 2, 3)
    assert result == 5
    stats = p.get_operation_stats("add")
    assert stats is None  # no metrics recorded


def test_profile_operation_re_exception_records_metric() -> None:
    """Even though exception re-raises, metric should be recorded first."""
    p = PerformanceProfiler({})

    def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        p.profile_operation("boom", fail)

    stats = p.get_operation_stats("boom")
    assert stats is not None
    assert stats["error_count"] == 1


# ---------------------------------------------------------------------------
# get_operation_stats
# ---------------------------------------------------------------------------


def test_get_operation_stats_nonexistent() -> None:
    p = PerformanceProfiler({})
    assert p.get_operation_stats("nonexistent") is None


def test_get_operation_stats_multiple_calls() -> None:
    p = PerformanceProfiler({})

    def noop() -> None:
        pass

    for _ in range(5):
        p.profile_operation("noop", noop)

    stats = p.get_operation_stats("noop")
    assert stats is not None
    assert stats["total_calls"] == 5


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def test_alert_threshold_triggered() -> None:
    p = PerformanceProfiler({"alert_thresholds": {"slow_op": 10.0}})

    def slow() -> None:
        time.sleep(0.02)

    p.profile_operation("slow_op", slow)
    alerts = p.get_recent_alerts()
    assert len(alerts) == 1
    assert alerts[0].operation_name == "slow_op"
    assert alerts[0].severity in ("warning", "error", "critical")


def test_alert_threshold_not_triggered() -> None:
    p = PerformanceProfiler({"alert_thresholds": {"fast_op": 10000.0}})

    def fast() -> None:
        pass

    p.profile_operation("fast_op", fast)
    assert len(p.get_recent_alerts()) == 0


def test_alert_threshold_not_set() -> None:
    p = PerformanceProfiler({})

    def op() -> None:
        time.sleep(0.01)

    p.profile_operation("no_threshold", op)
    assert len(p.get_recent_alerts()) == 0


# ---------------------------------------------------------------------------
# _determine_severity
# ---------------------------------------------------------------------------


def test_determine_severity_warning() -> None:
    p = PerformanceProfiler({})
    assert p._determine_severity(9.9, 5.0) == "warning"
    assert p._determine_severity(1.0, 5.0) == "warning"


def test_determine_severity_error() -> None:
    p = PerformanceProfiler({})
    assert p._determine_severity(10.0, 5.0) == "error"
    assert p._determine_severity(12.0, 5.0) == "error"
    assert p._determine_severity(24.9, 5.0) == "error"


def test_determine_severity_critical() -> None:
    p = PerformanceProfiler({})
    assert p._determine_severity(25.0, 5.0) == "critical"
    assert p._determine_severity(100.0, 5.0) == "critical"


# ---------------------------------------------------------------------------
# _percentile
# ---------------------------------------------------------------------------


def test_percentile_empty() -> None:
    p = PerformanceProfiler({})
    assert p._percentile([], 95) == 0.0


def test_percentile_single() -> None:
    p = PerformanceProfiler({})
    assert p._percentile([42.0], 50) == 42.0


def test_percentile_basic() -> None:
    p = PerformanceProfiler({})
    data = list(range(100))
    assert p._percentile(data, 50) == 50
    assert p._percentile(data, 95) == 95
    assert p._percentile(data, 99) == 99


def test_percentile_clamps() -> None:
    p = PerformanceProfiler({})
    data = [1.0, 2.0, 3.0]
    assert p._percentile(data, 0) == 1.0
    assert 0.0 <= p._percentile(data, 100) <= 3.0


# ---------------------------------------------------------------------------
# _generate_recommendations
# ---------------------------------------------------------------------------


def test_recommendation_high_latency() -> None:
    p = PerformanceProfiler({})
    recs = p._generate_recommendations(
        "slow_op", {"avg_duration_ms": 200.0, "p95_duration_ms": 50.0, "success_rate": 1.0, "error_count": 0}
    )
    assert any("high average latency" in r for r in recs)


def test_recommendation_high_p95() -> None:
    p = PerformanceProfiler({})
    recs = p._generate_recommendations(
        "spiky_op", {"avg_duration_ms": 50.0, "p95_duration_ms": 600.0, "success_rate": 1.0, "error_count": 0}
    )
    assert any("high p95" in r for r in recs)


def test_recommendation_low_success() -> None:
    p = PerformanceProfiler({})
    recs = p._generate_recommendations(
        "flaky_op", {"avg_duration_ms": 10.0, "p95_duration_ms": 20.0, "success_rate": 0.8, "error_count": 5}
    )
    assert any("low success rate" in r for r in recs)


def test_recommendation_high_error_count() -> None:
    p = PerformanceProfiler({})
    recs = p._generate_recommendations(
        "error_op", {"avg_duration_ms": 10.0, "p95_duration_ms": 20.0, "success_rate": 0.9, "error_count": 15}
    )
    assert any("high error count" in r for r in recs)


def test_recommendation_clean() -> None:
    p = PerformanceProfiler({})
    recs = p._generate_recommendations(
        "healthy", {"avg_duration_ms": 10.0, "p95_duration_ms": 20.0, "success_rate": 1.0, "error_count": 0}
    )
    assert recs == []


# ---------------------------------------------------------------------------
# get_performance_report
# ---------------------------------------------------------------------------


def test_performance_report_disabled() -> None:
    p = PerformanceProfiler({"enabled": False})
    report = p.get_performance_report()
    assert report["status"] == "disabled"


def test_performance_report_empty() -> None:
    p = PerformanceProfiler({})
    report = p.get_performance_report()
    assert report["status"] == "active"
    assert report["total_operations"] == 0


def test_performance_report_with_data() -> None:
    p = PerformanceProfiler({})

    def noop() -> None:
        pass

    p.profile_operation("op1", noop)
    p.profile_operation("op2", noop)
    report = p.get_performance_report()
    assert report["total_operations"] == 2
    assert "op1" in report["operations"]
    assert "op2" in report["operations"]


# ---------------------------------------------------------------------------
# clear_metrics
# ---------------------------------------------------------------------------


def test_clear_metrics() -> None:
    p = PerformanceProfiler({})

    def noop() -> None:
        pass

    p.profile_operation("op", noop)
    assert p.get_operation_stats("op") is not None
    p.clear_metrics()
    assert p.get_operation_stats("op") is None
    assert p.get_recent_alerts() == []


# ---------------------------------------------------------------------------
# profiled_operation decorator
# ---------------------------------------------------------------------------


def test_decorator() -> None:
    p = PerformanceProfiler({})

    @profiled_operation(p, "decorated")
    def compute(x: int, y: int) -> int:
        return x * y

    result = compute(6, 7)
    assert result == 42
    stats = p.get_operation_stats("decorated")
    assert stats is not None
    assert stats["total_calls"] == 1


def test_decorator_exception() -> None:
    p = PerformanceProfiler({})

    @profiled_operation(p, "fail_dec")
    def crash() -> None:
        raise ValueError("decorated crash")

    with pytest.raises(ValueError):
        crash()

    stats = p.get_operation_stats("fail_dec")
    assert stats is not None
    assert stats["error_count"] == 1


# ---------------------------------------------------------------------------
# create_performance_profiler factory
# ---------------------------------------------------------------------------


def test_create_profiler() -> None:
    p = create_performance_profiler({"enabled": True})
    assert isinstance(p, PerformanceProfiler)
    assert p.enabled is True
