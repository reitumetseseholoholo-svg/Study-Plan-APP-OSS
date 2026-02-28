"""
Performance optimization middleware for expensive operations.

Based on existing service patterns in the codebase, this module provides
middleware to optimize cognitive state updates, hint generation, and UI rendering
through caching and throttling mechanisms.
"""

import time
import threading
from typing import Any, Callable, Optional, TypeVar, Generic, Dict
from functools import wraps

from .caching import PerformanceCacheService

T = TypeVar('T')

class PerformanceMiddleware:
    """
    Middleware to intercept and optimize expensive operations.
    
    Based on existing service patterns in studyplan/services.py.
    """
    
    def __init__(self, cache_service: PerformanceCacheService):
        """
        Initialize middleware with caching service.
        
        Args:
            cache_service: PerformanceCacheService instance
        """
        self.cache = cache_service
        self._throttle_cache: Dict[str, float] = {}
        self._throttle_lock = threading.RLock()
        self._throttle_window = 0.1  # 100ms throttle window for UI operations
    
    def optimize_cognitive_update(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Optimize cognitive state updates with caching and throttling.
        
        Args:
            operation: The expensive operation to optimize
            *args: Positional arguments for the operation
            **kwargs: Keyword arguments for the operation
            
        Returns:
            The result of the operation
        """
        # Create cache key based on operation and arguments
        cache_key = self._generate_cache_key("cognitive_update", operation, args, kwargs)
        
        # Try to get cached result first
        cached_result = self.cache.get_cognitive_state(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Execute operation and cache result
        result = operation(*args, **kwargs)
        self.cache.set_cognitive_state(cache_key, result, ttl_minutes=5)
        
        return result
    
    def optimize_hint_generation(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Optimize hint generation with strategy caching.
        
        Args:
            operation: The hint generation operation
            *args: Positional arguments for the operation
            **kwargs: Keyword arguments for the operation
            
        Returns:
            The result of the operation
        """
        # Create cache key for hint strategy
        cache_key = self._generate_cache_key("hint_strategy", operation, args, kwargs)
        
        # Try to get cached strategy first
        cached_strategy = self.cache.get_hint_strategy(cache_key)
        if cached_strategy is not None:
            return cached_strategy
        
        # Execute operation and cache result
        result = operation(*args, **kwargs)
        self.cache.set_hint_strategy(cache_key, result, ttl_minutes=10)
        
        return result
    
    def optimize_ui_render(self, widget_id: str, render_func: Callable, *args, **kwargs) -> Any:
        """
        Optimize GTK4 widget rendering with throttling and caching.
        
        Args:
            widget_id: Unique identifier for the widget
            render_func: The rendering function
            *args: Positional arguments for the render function
            **kwargs: Keyword arguments for the render function
            
        Returns:
            The result of the render function
        """
        # Throttle rapid UI updates
        with self._throttle_lock:
            last_update = self._throttle_cache.get(widget_id, 0.0)
            now = time.time()
            
            if now - last_update < self._throttle_window:
                # Return cached result if available
                cached_result = self.cache.get_ui_render_cache(widget_id)
                if cached_result is not None:
                    return cached_result
            
            # Execute render function
            result = render_func(*args, **kwargs)
            
            # Cache result and update throttle timestamp
            self.cache.set_ui_render_cache(widget_id, result, ttl_seconds=30)
            self._throttle_cache[widget_id] = now
            
            return result
    
    def _generate_cache_key(self, operation_type: str, operation: Callable, args: tuple, kwargs: dict) -> str:
        """
        Generate a cache key for the operation.
        
        Args:
            operation_type: Type of operation (e.g., 'cognitive_update', 'hint_strategy')
            operation: The operation function
            args: Positional arguments
            kwargs: Keyword arguments
            
        Returns:
            A string cache key
        """
        import hashlib
        
        # Create a hash of the operation and arguments
        key_data = f"{operation_type}:{operation.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        
        return f"{operation_type}:{key_hash}"
    
    def clear_cache(self, cache_type: Optional[str] = None) -> None:
        """
        Clear cached data.
        
        Args:
            cache_type: Optional cache type to clear ('cognitive', 'hint', 'ui', or None for all)
        """
        if cache_type is None:
            self.cache.clear()
        elif cache_type == 'cognitive':
            # Clear cognitive state cache (implementation would need to be added to cache service)
            pass
        elif cache_type == 'hint':
            # Clear hint strategy cache (implementation would need to be added to cache service)
            pass
        elif cache_type == 'ui':
            # Clear UI render cache (implementation would need to be added to cache service)
            pass
    
    def get_cache_stats(self) -> dict:
        """
        Get cache statistics and performance metrics.
        
        Returns:
            Dictionary containing cache statistics
        """
        return self.cache.get_stats()


def performance_optimized(cache_service: PerformanceCacheService, operation_type: str):
    """
    Decorator to apply performance optimization to functions.
    
    Args:
        cache_service: PerformanceCacheService instance
        operation_type: Type of operation to optimize
        
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            middleware = PerformanceMiddleware(cache_service)
            
            if operation_type == 'cognitive_update':
                return middleware.optimize_cognitive_update(func, *args, **kwargs)
            elif operation_type == 'hint_generation':
                return middleware.optimize_hint_generation(func, *args, **kwargs)
            elif operation_type == 'ui_render':
                # For UI rendering, we need the widget_id as first argument
                if args:
                    widget_id = str(args[0])
                    return middleware.optimize_ui_render(widget_id, func, *args, **kwargs)
                return func(*args, **kwargs)
            else:
                # Fallback to regular execution
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# Factory function for service registration
def create_performance_middleware(cache_service: PerformanceCacheService) -> PerformanceMiddleware:
    """Create and configure performance middleware"""
    return PerformanceMiddleware(cache_service)


# Configuration schema for middleware
PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA = {
    'throttle_window_seconds': {
        'type': 'number',
        'default': 0.1,
        'description': 'Throttle window for UI operations in seconds'
    },
    'cache_ttl_cognitive_state': {
        'type': 'integer',
        'default': 300,
        'description': 'TTL for cognitive state cache in seconds'
    },
    'cache_ttl_hint_strategy': {
        'type': 'integer',
        'default': 600,
        'description': 'TTL for hint strategy cache in seconds'
    },
    'cache_ttl_ui_render': {
        'type': 'integer',
        'default': 30,
        'description': 'TTL for UI render cache in seconds'
    }
}