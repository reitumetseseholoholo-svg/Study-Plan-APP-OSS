"""
Real-time performance monitoring and alerting service.

Based on existing telemetry patterns in the codebase, this module provides
real-time performance monitoring, profiling, and alerting for expensive operations.
"""

import time
import threading
import statistics
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from collections import defaultdict, deque
import traceback

@dataclass
class PerformanceMetric:
    """Performance metric for a specific operation."""
    operation_name: str
    duration_ms: float
    timestamp: float
    success: bool
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PerformanceAlert:
    """Performance alert for operations exceeding thresholds."""
    operation_name: str
    threshold_ms: float
    actual_duration_ms: float
    timestamp: float
    severity: str  # 'warning', 'error', 'critical'
    message: str

class PerformanceProfiler:
    """
    Real-time performance monitoring and alerting service.
    
    Based on existing telemetry patterns in studyplan/telemetry/slo.py.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize profiler with configuration.
        
        Args:
            config: Configuration dict with profiling settings
        """
        self.config = config
        self.enabled = config.get('enabled', True)
        self.alert_thresholds = config.get('alert_thresholds', {})
        self.metrics_window_size = config.get('metrics_window_size', 100)
        self.alert_window_size = config.get('alert_window_size', 50)
        
        # Thread-safe storage
        self._metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.metrics_window_size))
        self._alerts: deque = deque(maxlen=self.alert_window_size)
        self._lock = threading.RLock()
        
        # Performance statistics
        self._stats: Dict[str, Dict[str, float]] = {}
        
    def profile_operation(self, operation_name: str, func: Callable, *args, **kwargs) -> Any:
        """
        Profile an expensive operation and track performance metrics.
        
        Args:
            operation_name: Name of the operation being profiled
            func: The function to execute and profile
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            The result of the function execution
        """
        if not self.enabled:
            return func(*args, **kwargs)
        
        start_time = time.perf_counter()
        success = True
        error_message = None
        
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            error_message = str(e)
            # Re-raise the exception to maintain original behavior
            raise
        finally:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000.0
            
            # Record metric
            metric = PerformanceMetric(
                operation_name=operation_name,
                duration_ms=duration_ms,
                timestamp=time.time(),
                success=success,
                error_message=error_message
            )
            
            self._record_metric(metric)
            
            # Check for alerts
            self._check_alerts(metric)
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        Generate performance optimization recommendations.
        
        Returns:
            Dictionary containing performance report and recommendations
        """
        if not self.enabled:
            return {"status": "disabled", "message": "Performance profiling is disabled"}
        
        with self._lock:
            report = {
                "status": "active",
                "timestamp": time.time(),
                "operations": {},
                "alerts": list(self._alerts),
                "recommendations": []
            }
            
            # Calculate statistics for each operation
            for operation_name, metrics in self._metrics.items():
                if not metrics:
                    continue
                
                durations = [m.duration_ms for m in metrics]
                success_rates = [1.0 if m.success else 0.0 for m in metrics]
                
                stats = {
                    "total_calls": len(metrics),
                    "avg_duration_ms": statistics.mean(durations),
                    "median_duration_ms": statistics.median(durations),
                    "p95_duration_ms": self._percentile(durations, 95),
                    "p99_duration_ms": self._percentile(durations, 99),
                    "min_duration_ms": min(durations),
                    "max_duration_ms": max(durations),
                    "success_rate": statistics.mean(success_rates),
                    "error_count": sum(1 for m in metrics if not m.success)
                }
                
                report["operations"][operation_name] = stats
                
                # Generate recommendations
                recommendations = self._generate_recommendations(operation_name, stats)
                report["recommendations"].extend(recommendations)
            
            return report
    
    def get_operation_stats(self, operation_name: str) -> Optional[Dict[str, float]]:
        """
        Get statistics for a specific operation.
        
        Args:
            operation_name: Name of the operation
            
        Returns:
            Dictionary containing operation statistics, or None if no data
        """
        with self._lock:
            metrics = self._metrics.get(operation_name, [])
            if not metrics:
                return None
            
            durations = [m.duration_ms for m in metrics]
            success_rates = [1.0 if m.success else 0.0 for m in metrics]
            
            return {
                "total_calls": len(metrics),
                "avg_duration_ms": statistics.mean(durations),
                "median_duration_ms": statistics.median(durations),
                "p95_duration_ms": self._percentile(durations, 95),
                "p99_duration_ms": self._percentile(durations, 99),
                "min_duration_ms": min(durations),
                "max_duration_ms": max(durations),
                "success_rate": statistics.mean(success_rates),
                "error_count": sum(1 for m in metrics if not m.success)
            }
    
    def get_recent_alerts(self, limit: int = 10) -> List[PerformanceAlert]:
        """
        Get recent performance alerts.
        
        Args:
            limit: Maximum number of alerts to return
            
        Returns:
            List of recent performance alerts
        """
        with self._lock:
            return list(self._alerts)[-limit:]
    
    def clear_metrics(self) -> None:
        """Clear all performance metrics."""
        with self._lock:
            self._metrics.clear()
            self._alerts.clear()
    
    def _record_metric(self, metric: PerformanceMetric) -> None:
        """Record a performance metric."""
        with self._lock:
            self._metrics[metric.operation_name].append(metric)
    
    def _check_alerts(self, metric: PerformanceMetric) -> None:
        """Check if metric exceeds alert thresholds and create alerts."""
        threshold = self.alert_thresholds.get(metric.operation_name)
        if threshold is None:
            return
        
        if metric.duration_ms > threshold:
            severity = self._determine_severity(metric.duration_ms, threshold)
            message = f"Operation '{metric.operation_name}' took {metric.duration_ms:.2f}ms, exceeding threshold of {threshold}ms"
            
            alert = PerformanceAlert(
                operation_name=metric.operation_name,
                threshold_ms=threshold,
                actual_duration_ms=metric.duration_ms,
                timestamp=metric.timestamp,
                severity=severity,
                message=message
            )
            
            with self._lock:
                self._alerts.append(alert)
    
    def _determine_severity(self, duration: float, threshold: float) -> str:
        """Determine alert severity based on how much threshold is exceeded."""
        ratio = duration / threshold
        
        if ratio >= 5.0:
            return "critical"
        elif ratio >= 2.0:
            return "error"
        else:
            return "warning"
    
    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile of a list of values."""
        if not data:
            return 0.0
        
        sorted_data = sorted(data)
        index = int((percentile / 100.0) * len(sorted_data))
        index = max(0, min(index, len(sorted_data) - 1))
        return sorted_data[index]
    
    def _generate_recommendations(self, operation_name: str, stats: Dict[str, float]) -> List[str]:
        """Generate performance optimization recommendations."""
        recommendations = []
        
        # Check for high latency
        if stats["avg_duration_ms"] > 100.0:
            recommendations.append(f"Operation '{operation_name}' has high average latency ({stats['avg_duration_ms']:.2f}ms). Consider caching or optimization.")
        
        # Check for high p95 latency
        if stats["p95_duration_ms"] > 500.0:
            recommendations.append(f"Operation '{operation_name}' has high p95 latency ({stats['p95_duration_ms']:.2f}ms). Investigate outliers.")
        
        # Check for low success rate
        if stats["success_rate"] < 0.95:
            recommendations.append(f"Operation '{operation_name}' has low success rate ({stats['success_rate']:.2%}). Check for error patterns.")
        
        # Check for high error count
        if stats["error_count"] > 10:
            recommendations.append(f"Operation '{operation_name}' has high error count ({stats['error_count']}). Review error logs.")
        
        return recommendations


def profiled_operation(profiler: PerformanceProfiler, operation_name: str):
    """
    Decorator to profile operations.
    
    Args:
        profiler: PerformanceProfiler instance
        operation_name: Name of the operation to profile
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            return profiler.profile_operation(operation_name, func, *args, **kwargs)
        return wrapper
    return decorator


# Factory function for service registration
def create_performance_profiler(config: Dict[str, Any]) -> PerformanceProfiler:
    """Create and configure performance profiler"""
    return PerformanceProfiler(config)


# Configuration schema for profiler
PERFORMANCE_PROFILER_CONFIG_SCHEMA = {
    'enabled': {
        'type': 'boolean',
        'default': True,
        'description': 'Enable performance profiling'
    },
    'alert_thresholds': {
        'type': 'object',
        'properties': {
            'cognitive_update_ms': {'type': 'integer', 'default': 100},
            'hint_generation_ms': {'type': 'integer', 'default': 50},
            'ui_render_ms': {'type': 'integer', 'default': 16},
            'state_validation_ms': {'type': 'integer', 'default': 10},
            'state_persistence_ms': {'type': 'integer', 'default': 50}
        },
        'description': 'Alert thresholds for different operations'
    },
    'metrics_window_size': {
        'type': 'integer',
        'default': 100,
        'description': 'Number of metrics to keep for each operation'
    },
    'alert_window_size': {
        'type': 'integer',
        'default': 50,
        'description': 'Number of alerts to keep in memory'
    }
}