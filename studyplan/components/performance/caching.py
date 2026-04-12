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
        _rag_chunk_cap = config.get('rag_doc_chunk_budget', 3600)
        try:
            self.rag_doc_chunk_budget = max(0, int(_rag_chunk_cap))
        except (TypeError, ValueError):
            self.rag_doc_chunk_budget = 3600
        
        # Thread-safe cache storage
        self._cache: Dict[str, CacheEntry[Any]] = {}
        self._access_order: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.RLock()
        
        # Cache statistics
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'total_requests': 0,
            'rag_doc_evictions': 0,
            'rag_doc_doc_cap_evictions': 0,
            'rag_doc_chunk_budget_evictions': 0,
            'rag_doc_cache_max_evictions': 0,
            'rag_doc_evicted_chunks': 0,
            'rag_doc_evicted_bytes': 0,
        }

    def _estimate_rag_doc_payload(self, value: Any) -> tuple[int, int]:
        """Return approximate (chunk_count, byte_count) for in-memory rag_doc payloads."""
        if not isinstance(value, dict):
            return 0, 0
        rows = value.get("chunks", [])
        if not isinstance(rows, list) or not rows:
            return 0, 0
        byte_count = 0
        for row in rows:
            if isinstance(row, dict):
                text = str(row.get("text", "") or "")
            else:
                text = str(row or "")
            byte_count += len(text.encode("utf-8", errors="ignore"))
        return len(rows), byte_count

    def _rag_doc_live_totals(self) -> tuple[int, int, int]:
        """Return current (entry_count, chunk_count, byte_count) for in-memory rag_doc payloads."""
        rag_entry_count = 0
        rag_chunk_count = 0
        rag_byte_count = 0
        for key in self._access_order:
            if not key.startswith("rag_doc:"):
                continue
            entry = self._cache.get(key)
            if entry is None:
                continue
            rag_entry_count += 1
            chunks, bytes_count = self._estimate_rag_doc_payload(entry.value)
            rag_chunk_count += int(chunks)
            rag_byte_count += int(bytes_count)
        return rag_entry_count, rag_chunk_count, rag_byte_count

    def _remove_cache_key(self, key: str, *, count_eviction: bool = False, reason: str = "") -> bool:
        """Remove a cache key and optionally attribute eviction metrics."""
        entry = self._cache.pop(key, None)
        self._access_order.pop(key, None)
        if entry is None:
            return False
        if count_eviction:
            self._stats['evictions'] += 1
            if key.startswith("rag_doc:"):
                chunks, bytes_count = self._estimate_rag_doc_payload(entry.value)
                self._stats['rag_doc_evictions'] += 1
                self._stats['rag_doc_evicted_chunks'] += int(chunks)
                self._stats['rag_doc_evicted_bytes'] += int(bytes_count)
                if reason == "doc_cap":
                    self._stats['rag_doc_doc_cap_evictions'] += 1
                elif reason == "chunk_budget":
                    self._stats['rag_doc_chunk_budget_evictions'] += 1
                elif reason == "cache_max":
                    self._stats['rag_doc_cache_max_evictions'] += 1
        return True
    
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
        """Remove oldest rag_doc:* entries until doc-count and chunk-budget caps are satisfied."""
        with self._lock:
            while True:
                rag_doc_count, rag_chunk_count, _rag_byte_count = self._rag_doc_live_totals()
                over_doc_cap = self.rag_doc_memory_max > 0 and rag_doc_count > self.rag_doc_memory_max
                over_chunk_cap = self.rag_doc_chunk_budget > 0 and rag_chunk_count > self.rag_doc_chunk_budget
                if not (over_doc_cap or over_chunk_cap):
                    break
                victim = None
                for k in self._access_order:
                    if k.startswith("rag_doc:"):
                        victim = k
                        break
                if victim is None:
                    break
                reason = "chunk_budget" if over_chunk_cap else "doc_cap"
                self._remove_cache_key(victim, count_eviction=True, reason=reason)

    def _evict_lru(self) -> None:
        """Evict least recently used entries when cache is full"""
        with self._lock:
            # Handle zero-size cache case
            if self.max_size <= 0:
                # Clear all entries immediately
                count = len(self._cache)
                self._cache.clear()
                self._access_order.clear()
                self._stats['evictions'] += count
                return
            
            while len(self._cache) >= self.max_size:
                if not self._access_order:
                    break
                # Remove least recently used entry (first item in OrderedDict)
                lru_key = next(iter(self._access_order))
                self._remove_cache_key(lru_key, count_eviction=True, reason="cache_max")
    
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

            # Replacement updates should not artificially consume capacity.
            if key in self._cache:
                self._remove_cache_key(key, count_eviction=False)
            
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
            return self._remove_cache_key(key, count_eviction=False)
    
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
            rag_doc_entries, rag_doc_chunks, rag_doc_bytes = self._rag_doc_live_totals()
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'evictions': self._stats['evictions'],
                'hit_rate': hit_rate,
                'total_requests': self._stats['total_requests'],
                'rag_doc_memory_max': self.rag_doc_memory_max,
                'rag_doc_chunk_budget': self.rag_doc_chunk_budget,
                'rag_doc_entries': rag_doc_entries,
                'rag_doc_chunks': rag_doc_chunks,
                'rag_doc_bytes': rag_doc_bytes,
                'rag_doc_evictions': self._stats['rag_doc_evictions'],
                'rag_doc_doc_cap_evictions': self._stats['rag_doc_doc_cap_evictions'],
                'rag_doc_chunk_budget_evictions': self._stats['rag_doc_chunk_budget_evictions'],
                'rag_doc_cache_max_evictions': self._stats['rag_doc_cache_max_evictions'],
                'rag_doc_evicted_chunks': self._stats['rag_doc_evicted_chunks'],
                'rag_doc_evicted_bytes': self._stats['rag_doc_evicted_bytes'],
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
    'rag_doc_chunk_budget': {
        'type': 'integer',
        'default': 3600,
        'description': 'Global in-memory rag_doc:* chunk budget across cached PDFs; 0 = no separate cap',
    },
}
