import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceMetric:
    operation: str
    duration_ms: float
    timestamp: str
    threshold_ms: float = 100.0  # default budget

    @property
    def exceeded(self) -> bool:
        return self.duration_ms > self.threshold_ms


class PerformanceMonitor:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.metrics: list[PerformanceMetric] = []
        self._thresholds = {
            "state_validation": 10.0,
            "state_persistence": 50.0,
            "assess": 20.0,
            "practice_item_build": 30.0,
            "posterior_update": 5.0,
        }

    def record(self, operation: str, duration_ms: float, timestamp: str) -> None:
        if not self.enabled:
            return
        threshold = self._thresholds.get(operation, 100.0)
        metric = PerformanceMetric(operation=operation, duration_ms=duration_ms, timestamp=timestamp, threshold_ms=threshold)
        self.metrics.append(metric)
        if metric.exceeded:
            logger.warning(f"perf_budget_exceeded", extra={"operation": operation, "duration_ms": duration_ms, "threshold_ms": threshold})

    def context(self, operation: str):
        """Context manager for measuring operation latency."""
        return _PerfContext(self, operation)

    def report(self) -> dict[str, Any]:
        """Summary of recorded metrics."""
        if not self.metrics:
            return {}
        exceeded = [m for m in self.metrics if m.exceeded]
        return {
            "total_recorded": len(self.metrics),
            "budget_exceeded": len(exceeded),
            "exceeded_ops": [(m.operation, m.duration_ms) for m in exceeded],
        }


class _PerfContext:
    def __init__(self, monitor: PerformanceMonitor, operation: str):
        self.monitor = monitor
        self.operation = operation
        self.start = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        end = time.perf_counter()
        duration_ms = (end - self.start) * 1000
        timestamp = datetime.now(timezone.utc).isoformat()
        self.monitor.record(self.operation, duration_ms, timestamp)
