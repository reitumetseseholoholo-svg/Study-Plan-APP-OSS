"""
Performance optimization integration for the studyplan app.

This module provides the integration points for the PerformanceCacheService,
PerformanceProfiler, and PerformanceMiddleware to be used throughout the
studyplan application.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, Optional, TypeVar, cast

from .config import Config
from .components.performance.caching import PerformanceCacheService, create_performance_cache_service
from .components.performance.optimization import PerformanceMiddleware
from .components.performance.profiler import PerformanceProfiler

logger = logging.getLogger(__name__)

# Type variable for generic function wrapping
F = TypeVar('F', bound=Callable[..., Any])


class PerformanceIntegration:
    """Central performance optimization integration for the studyplan app."""
    
    def __init__(self):
        self._cache_service: Optional[PerformanceCacheService] = None
        self._profiler: Optional[PerformanceProfiler] = None
        self._middleware: Optional[PerformanceMiddleware] = None
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize all performance optimization services."""
        if self._initialized:
            return
        
        try:
            # Initialize cache service
            if Config.PERFORMANCE_CACHE_ENABLED:
                try:
                    rag_cap = int(str(os.environ.get("STUDYPLAN_RAG_MEMORY_DOC_CAP", "") or "32").strip() or "32")
                except ValueError:
                    rag_cap = 32
                rag_cap = max(0, min(512, rag_cap))
                cache_config = {
                    'cache_max_size': Config.PERFORMANCE_CACHE_MAX_SIZE,
                    'default_ttl_seconds': Config.PERFORMANCE_CACHE_DEFAULT_TTL_SECONDS,
                    'cache_ttl': Config.PERFORMANCE_CACHE_TTL_CONFIG,
                    'rag_doc_memory_max': rag_cap,
                }
                self._cache_service = create_performance_cache_service(cache_config)
                logger.info("Performance cache service initialized")
            else:
                logger.info("Performance cache service disabled")
            
            # Initialize profiler
            profiler_config = {
                'enabled': Config.PERF_MONITOR_ENABLED,
                'alert_thresholds': Config.PERF_THRESHOLDS,
                'metrics_window_size': 100,
                'alert_window_size': 50
            }
            self._profiler = PerformanceProfiler(profiler_config)
            logger.info("Performance profiler initialized")
            
            # Initialize middleware
            if self._cache_service:
                self._middleware = PerformanceMiddleware(self._cache_service)
                logger.info("Performance middleware initialized")
            else:
                logger.info("Performance middleware disabled (no cache service)")
            
            self._initialized = True
            logger.info("Performance integration fully initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize performance integration: {e}")
            self._initialized = True  # Mark initialized to avoid retry loops
    
    def get_cache_service(self) -> Optional[PerformanceCacheService]:
        """Get the performance cache service."""
        return self._cache_service
    
    def get_profiler(self) -> Optional[PerformanceProfiler]:
        """Get the performance profiler."""
        return self._profiler
    
    def get_middleware(self) -> Optional[PerformanceMiddleware]:
        """Get the performance middleware."""
        return self._middleware
    
    def cache_method(self, cache_key_prefix: str = "", ttl_minutes: int = 5):
        """
        Decorator to cache method results using the performance cache service.
        
        Args:
            cache_key_prefix: Prefix for the cache key
            ttl_minutes: Time to live in minutes
        """
        def decorator(func: F) -> F:
            def wrapper(*args, **kwargs):
                if not self._cache_service:
                    return func(*args, **kwargs)
                
                # Generate cache key
                cache_key = self._generate_cache_key(func, cache_key_prefix, args, kwargs)
                
                # Try to get from cache
                cached_result = self._cache_service.get(cache_key)
                if cached_result is not None:
                    logger.debug(f"Cache hit for {cache_key}")
                    return cached_result
                
                # Execute function and cache result
                result = func(*args, **kwargs)
                self._cache_service.set(
                    cache_key, 
                    result, 
                    ttl_seconds=ttl_minutes * 60
                )
                logger.debug(f"Cached result for {cache_key}")
                return result
            
            return cast(F, wrapper)
        return decorator
    
    def profile_method(self, operation_name: str = ""):
        """
        Decorator to profile method execution using the performance profiler.
        
        Args:
            operation_name: Name for the operation being profiled
        """
        def decorator(func: F) -> F:
            def wrapper(*args, **kwargs):
                if not self._profiler:
                    return func(*args, **kwargs)
                
                op_name = operation_name or f"{func.__module__}.{func.__name__}"
                
                # Use the profiler's profile_operation method
                def execute_operation():
                    return func(*args, **kwargs)
                
                return self._profiler.profile_operation(op_name, execute_operation)
            
            return cast(F, wrapper)
        return decorator
    
    def optimize_method(self, cache_key_prefix: str = "", ttl_minutes: int = 5, operation_name: str = ""):
        """
        Combined decorator that applies both caching and profiling.
        
        Args:
            cache_key_prefix: Prefix for the cache key
            ttl_minutes: Time to live in minutes
            operation_name: Name for the operation being profiled
        """
        def decorator(func: F) -> F:
            # Apply caching first, then profiling
            cached_func = self.cache_method(cache_key_prefix, ttl_minutes)(func)
            return self.profile_method(operation_name)(cached_func)
        
        return decorator
    
    def _generate_cache_key(self, func: Callable, prefix: str, args: tuple, kwargs: dict) -> str:
        """Generate a cache key for the given function and arguments."""
        import hashlib
        
        # Create a key based on function name and arguments
        key_parts = [prefix, func.__module__, func.__name__]
        
        # Add positional arguments
        for arg in args:
            if hasattr(arg, '__dict__'):
                # For objects, use a hash of their string representation
                key_parts.append(str(hash(str(arg.__dict__))))
            else:
                key_parts.append(str(arg))
        
        # Add keyword arguments
        for key, value in sorted(kwargs.items()):
            if hasattr(value, '__dict__'):
                key_parts.append(f"{key}={hash(str(value.__dict__))}")
            else:
                key_parts.append(f"{key}={value}")
        
        # Create hash of the key parts
        key_string = ":".join(key_parts)
        return f"{prefix}{hashlib.md5(key_string.encode()).hexdigest()}"
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics from all services."""
        stats = {
            'initialized': self._initialized,
            'cache_service': None,
            'profiler': None,
            'middleware': None
        }
        
        if self._cache_service:
            stats['cache_service'] = self._cache_service.get_stats()
        
        if self._profiler:
            stats['profiler'] = self._profiler.get_performance_report()
        
        if self._middleware:
            stats['middleware'] = {
                'cache_service_enabled': self._middleware.cache is not None
            }
        
        return stats
    
    def clear_cache(self) -> None:
        """Clear all cached data."""
        if self._cache_service:
            self._cache_service.clear()
            logger.info("Performance cache cleared")
    
    def reset_profiler(self) -> None:
        """Reset profiler statistics."""
        if self._profiler:
            self._profiler.clear_metrics()
            logger.info("Performance profiler reset")


# Global performance integration instance
performance_integration = PerformanceIntegration()


def initialize_performance_services() -> None:
    """Initialize all performance optimization services."""
    performance_integration.initialize()


def get_performance_cache() -> Optional[PerformanceCacheService]:
    """Get the performance cache service."""
    return performance_integration.get_cache_service()


def get_performance_profiler() -> Optional[PerformanceProfiler]:
    """Get the performance profiler."""
    return performance_integration.get_profiler()


def get_performance_middleware() -> Optional[PerformanceMiddleware]:
    """Get the performance middleware."""
    return performance_integration.get_middleware()


# Convenience decorators
def cache_result(cache_key_prefix: str = "", ttl_minutes: int = 5):
    """Cache the result of a function."""
    return performance_integration.cache_method(cache_key_prefix, ttl_minutes)


def profile_operation(operation_name: str = ""):
    """Profile the execution of a function."""
    return performance_integration.profile_method(operation_name)


def optimize_function(cache_key_prefix: str = "", ttl_minutes: int = 5, operation_name: str = ""):
    """Apply both caching and profiling to a function."""
    return performance_integration.optimize_method(cache_key_prefix, ttl_minutes, operation_name)


def get_performance_stats() -> Dict[str, Any]:
    """Get performance statistics."""
    return performance_integration.get_performance_stats()


def clear_performance_cache() -> None:
    """Clear all cached data."""
    performance_integration.clear_cache()


def reset_performance_profiler() -> None:
    """Reset profiler statistics."""
    performance_integration.reset_profiler()