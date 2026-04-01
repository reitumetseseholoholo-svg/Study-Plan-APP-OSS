"""
Performance optimization modules for the ACCA Study Plan application.

This package provides high-performance caching, optimization middleware,
and performance profiling services to improve application responsiveness
and user experience.

Modules:
    caching: High-performance caching service for cognitive state and computations
    optimization: Middleware to optimize expensive operations
    profiler: Real-time performance monitoring and alerting
"""

from .caching import PerformanceCacheService, create_performance_cache_service
from .optimization import PerformanceMiddleware
from .profiler import PerformanceProfiler

__all__ = [
    'PerformanceCacheService',
    'create_performance_cache_service',
    'PerformanceMiddleware', 
    'PerformanceProfiler'
]