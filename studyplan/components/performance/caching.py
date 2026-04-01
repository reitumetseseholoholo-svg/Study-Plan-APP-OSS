"""
High-performance caching service for cognitive state and expensive computations.

Based on existing patterns in the codebase for service registration and configuration.
Provides thread-safe caching with LRU eviction, TTL management, and specialized
methods for cognitive state, hint strategies, and UI rendering optimization.
"""

import time
import threading
from typing import Dict, Any, Optional, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from collections import OrderedDict

T = TypeVar('T')

@dataclass
class CacheEntry(Generic[T]):
    """Cache entry with TTL and metadata"""
    value: T
    created_at: float
    ttl_seconds: float
    access_count: int = field(default=0)
    last_access: float = field(default_factory=time.time)

class PerformanceCacheService:
    """
    High-performance caching service for cognitive state and expensive computations.
    
    Based on existing service patterns in studyplan/services.py and config patterns
    in studyplan/config.py.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize cache service with configuration.
        
        Args:
            config: Configuration dict with cache settings
        """
        self.config = config
        self.max_size = config.get('cache_max_size', 1000)
        self.default_ttl = config.get('default_ttl_seconds', 300)  # 5 minutes
        self.ttl_config = config.get('cache_ttl', {})
        # Large RAG doc payloads: cap in-memory rag_doc:* entries separately from total cache size.
        _rag_cap = config.get('rag_doc_memory_max', 32)
        try:
            self.rag_doc_memory_max = max(0, int(_rag_cap))
        except (TypeError, ValueError):
            self.rag_doc_memory_max = 32
        
        # Thread-safe cache storage
        self._cache: Dict[str, CacheEntry[Any]] = {}
        self._access_order: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.RLock()
        
        # Cache statistics
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_requests': 0
        }
    
    def _get_ttl(self, key: str) -> float:
        """Get TTL for a specific cache key"""
        # Check specific TTL config first
        for pattern, ttl in self.ttl_config.items():
            if pattern in key:
                return float(ttl)
        return float(self.default_ttl)
    
    def _cleanup_expired(self) -> None:
        """Remove expired entries from cache"""
        now = time.time()
        expired_keys = []
        
        with self._lock:
            for key, entry in self._cache.items():
                if now - entry.created_at > entry.ttl_seconds:
                    expired_keys.append(key)
            
            # Remove expired keys from both cache and access order
            for key in expired_keys:
                self._cache.pop(key, None)
                self._access_order.pop(key, None)
    
    def _evict_excess_rag_docs(self) -> None:
        """Remove oldest rag_doc:* entries until at or below rag_doc_memory_max."""
        if self.rag_doc_memory_max <= 0:
            return
        with self._lock:
            rag_keys = [k for k in self._access_order if k.startswith("rag_doc:")]
            while len(rag_keys) > self.rag_doc_memory_max:
                victim = None
                for k in self._access_order:
                    if k.startswith("rag_doc:"):
                        victim = k
                        break
                if victim is None:
                    break
                self._cache.pop(victim, None)
                self._access_order.pop(victim, None)
                self._stats['evictions'] += 1
                rag_keys = [k for k in self._access_order if k.startswith("rag_doc:")]

    def _evict_lru(self) -> None:
        """Evict least recently used entries when cache is full"""
        with self._lock:
            # Handle zero-size cache case
            if self.max_size <= 0:
                # Clear all entries immediately
                self._cache.clear()
                self._access_order.clear()
                self._stats['evictions'] += len(self._cache)
                return
            
            while len(self._cache) >= self.max_size:
                if not self._access_order:
                    break
                # Remove least recently used entry (first item in OrderedDict)
                lru_key = next(iter(self._access_order))
                del self._cache[lru_key]
                self._access_order.pop(lru_key, None)
                self._stats['evictions'] += 1
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value if found and not expired, None otherwise
        """
        with self._lock:
            self._stats['total_requests'] += 1
            
            # Clean up expired entries periodically
            if self._stats['total_requests'] % 100 == 0:
                self._cleanup_expired()
            
            entry = self._cache.get(key)
            if entry is None:
                self._stats['misses'] += 1
                return None
            
            now = time.time()
            if now - entry.created_at > entry.ttl_seconds:
                del self._cache[key]
                self._access_order.pop(key, None)
                self._stats['misses'] += 1
                return None
            
            # Update access statistics
            entry.access_count += 1
            entry.last_access = now
            
            # Update LRU order
            self._access_order.move_to_end(key)
            self._stats['hits'] += 1
            
            return entry.value
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Optional TTL override
        """
        with self._lock:
            # Handle zero-size cache case - immediately return without caching
            if self.max_size <= 0:
                return
            
            if ttl_seconds is None:
                ttl_seconds = self._get_ttl(key)
            
            # Evict if necessary
            if len(self._cache) >= self.max_size:
                self._evict_lru()
            
            entry = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl_seconds=float(ttl_seconds)
            )
            
            self._cache[key] = entry
            self._access_order[key] = time.time()
            self._access_order.move_to_end(key)

            if key.startswith("rag_doc:"):
                self._evict_excess_rag_docs()
    
    def delete(self, key: str) -> bool:
        """Delete entry from cache"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._access_order.pop(key, None)
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._access_order.clear()
            self._stats['evictions'] += count

    def clear_prefix(self, prefix: str) -> int:
        """Remove all entries whose key starts with *prefix*. Returns count removed."""
        with self._lock:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for key in keys:
                self._cache.pop(key, None)
                self._access_order.pop(key, None)
            self._stats['evictions'] += len(keys)
            return len(keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            hit_rate = self._stats['hits'] / max(1, self._stats['total_requests'])
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'evictions': self._stats['evictions'],
                'hit_rate': hit_rate,
                'total_requests': self._stats['total_requests']
            }
    
    # Cognitive State specific methods
    def get_cognitive_state(self, topic: str) -> Optional[Any]:
        """Get cached cognitive state for a topic"""
        key = f"cognitive_state:{topic}"
        return self.get(key)
    
    def set_cognitive_state(self, topic: str, state: Any, ttl_minutes: int = 5) -> None:
        """Cache cognitive state for a topic"""
        key = f"cognitive_state:{topic}"
        self.set(key, state, ttl_seconds=ttl_minutes * 60)
    
    # Hint strategy specific methods
    def get_hint_strategy(self, topic: str) -> Optional[Dict[str, Any]]:
        """Get cached hint generation strategy for a topic"""
        key = f"hint_strategy:{topic}"
        return self.get(key)
    
    def set_hint_strategy(self, topic: str, strategy: Dict[str, Any], ttl_minutes: int = 10) -> None:
        """Cache hint generation strategy for a topic"""
        key = f"hint_strategy:{topic}"
        self.set(key, strategy, ttl_seconds=ttl_minutes * 60)
    
    # UI rendering specific methods
    def get_ui_render_cache(self, widget_id: str) -> Optional[Any]:
        """Get cached UI rendering for a widget"""
        key = f"ui_render:{widget_id}"
        return self.get(key)
    
    def set_ui_render_cache(self, widget_id: str, render_result: Any, ttl_seconds: int = 30) -> None:
        """Cache UI rendering result for a widget"""
        key = f"ui_render:{widget_id}"
        self.set(key, render_result, ttl_seconds=ttl_seconds)

# Factory function for service registration
def create_performance_cache_service(config: Dict[str, Any]) -> PerformanceCacheService:
    """Create and configure performance cache service"""
    return PerformanceCacheService(config)

# Configuration schema (based on existing config patterns)
PERFORMANCE_CACHE_CONFIG_SCHEMA = {
    'cache_max_size': {
        'type': 'integer',
        'default': 1000,
        'description': 'Maximum number of cache entries'
    },
    'default_ttl_seconds': {
        'type': 'integer', 
        'default': 300,
        'description': 'Default TTL for cache entries in seconds'
    },
    'cache_ttl': {
        'type': 'object',
        'properties': {
            'cognitive_state': {'type': 'integer', 'default': 300},
            'hint_strategy': {'type': 'integer', 'default': 600},
            'ui_render': {'type': 'integer', 'default': 30}
        },
        'description': 'TTL configuration per cache type'
    },
    'rag_doc_memory_max': {
        'type': 'integer',
        'default': 32,
        'description': 'Max in-memory rag_doc:* entries (large PDF chunk payloads); 0 = no separate cap',
    },
}