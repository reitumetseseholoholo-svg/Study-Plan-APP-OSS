"""
Tests for the PerformanceCacheService.

This module provides comprehensive tests for the high-performance caching service
that handles cognitive state, hint strategies, and UI rendering optimization.
"""

import time
import threading
import pytest
from typing import Any, Dict
from studyplan.components.performance.caching import (
    PerformanceCacheService,
    CacheEntry,
    create_performance_cache_service,
    PERFORMANCE_CACHE_CONFIG_SCHEMA
)


class TestCacheEntry:
    """Test the CacheEntry data structure."""
    
    def test_cache_entry_creation(self):
        """Test that CacheEntry can be created with required fields."""
        value = {"test": "data"}
        created_at = time.time()
        ttl_seconds = 300.0
        
        entry = CacheEntry(
            value=value,
            created_at=created_at,
            ttl_seconds=ttl_seconds
        )
        
        assert entry.value == value
        assert entry.created_at == created_at
        assert entry.ttl_seconds == ttl_seconds
        assert entry.access_count == 0
        assert entry.last_access > 0
    
    def test_cache_entry_with_custom_access_count(self):
        """Test CacheEntry with custom access count."""
        entry = CacheEntry(
            value="test",
            created_at=time.time(),
            ttl_seconds=300.0,
            access_count=5
        )
        
        assert entry.access_count == 5


class TestPerformanceCacheService:
    """Test the PerformanceCacheService implementation."""
    
    @pytest.fixture
    def cache_service(self):
        """Create a PerformanceCacheService instance for testing."""
        config = {
            'cache_max_size': 100,
            'default_ttl_seconds': 300,
            'cache_ttl': {
                'cognitive_state': 300,
                'hint_strategy': 600,
                'ui_render': 30
            }
        }
        return PerformanceCacheService(config)
    
    def test_service_initialization(self, cache_service):
        """Test that the cache service initializes correctly."""
        assert cache_service.max_size == 100
        assert cache_service.default_ttl == 300
        assert cache_service.ttl_config['cognitive_state'] == 300
        assert cache_service.ttl_config['hint_strategy'] == 600
        assert cache_service.ttl_config['ui_render'] == 30
        assert len(cache_service._cache) == 0
        assert len(cache_service._access_order) == 0
    
    def test_basic_set_and_get(self, cache_service):
        """Test basic set and get operations."""
        cache_service.set("test_key", "test_value")
        result = cache_service.get("test_key")
        
        assert result == "test_value"
    
    def test_get_nonexistent_key(self, cache_service):
        """Test getting a key that doesn't exist."""
        result = cache_service.get("nonexistent_key")
        assert result is None
    
    def test_ttl_expiration(self, cache_service):
        """Test that entries expire after TTL."""
        # Set a very short TTL
        cache_service.set("short_key", "short_value", ttl_seconds=0.1)
        
        # Should be available immediately
        result = cache_service.get("short_key")
        assert result == "short_value"
        
        # Wait for expiration
        time.sleep(0.2)
        
        # Should be expired
        result = cache_service.get("short_key")
        assert result is None
    
    def test_lru_eviction(self, cache_service):
        """Test LRU eviction when cache is full."""
        # Fill cache to capacity
        for i in range(100):
            cache_service.set(f"key_{i}", f"value_{i}")
        
        # Cache should be full
        assert len(cache_service._cache) == 100
        
        # Access some keys to update their LRU order
        cache_service.get("key_0")
        cache_service.get("key_1")
        
        # Add one more item, should evict the least recently used
        cache_service.set("new_key", "new_value")
        
        # Should have evicted key_2 (the oldest non-accessed key)
        assert "key_2" not in cache_service._cache
        assert "new_key" in cache_service._cache
        assert len(cache_service._cache) == 100
    
    def test_delete_operation(self, cache_service):
        """Test explicit deletion of cache entries."""
        cache_service.set("delete_key", "delete_value")
        assert cache_service.get("delete_key") == "delete_value"
        
        result = cache_service.delete("delete_key")
        assert result is True
        assert cache_service.get("delete_key") is None
        
        # Delete non-existent key
        result = cache_service.delete("nonexistent_key")
        assert result is False
    
    def test_clear_operation(self, cache_service):
        """Test clearing the entire cache."""
        cache_service.set("key1", "value1")
        cache_service.set("key2", "value2")
        
        assert len(cache_service._cache) == 2
        cache_service.clear()
        assert len(cache_service._cache) == 0
    
    def test_cache_statistics(self, cache_service):
        """Test cache statistics tracking."""
        stats = cache_service.get_stats()
        
        assert stats['size'] == 0
        assert stats['max_size'] == 100
        assert stats['hits'] == 0
        assert stats['misses'] == 0
        assert stats['total_requests'] == 0
        assert stats['hit_rate'] == 0.0
        
        # Perform some operations
        cache_service.set("test_key", "test_value")
        cache_service.get("test_key")  # Hit
        cache_service.get("missing_key")  # Miss
        
        stats = cache_service.get_stats()
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert stats['total_requests'] == 2
        assert stats['hit_rate'] == 0.5
    
    def test_cognitive_state_methods(self, cache_service):
        """Test cognitive state specific caching methods."""
        state_data = {
            "topic": "WACC",
            "confidence": 0.8,
            "last_practice": "2024-01-01"
        }
        
        # Set cognitive state
        cache_service.set_cognitive_state("wacc_topic", state_data, ttl_minutes=5)
        
        # Get cognitive state
        result = cache_service.get_cognitive_state("wacc_topic")
        assert result == state_data
        
        # Test expiration
        cache_service.set_cognitive_state("wacc_topic2", state_data, ttl_minutes=0)
        time.sleep(0.1)
        result = cache_service.get_cognitive_state("wacc_topic2")
        assert result is None
    
    def test_hint_strategy_methods(self, cache_service):
        """Test hint strategy specific caching methods."""
        strategy = {
            "approach": "step_by_step",
            "difficulty": "medium",
            "hints": ["hint1", "hint2"]
        }
        
        # Set hint strategy
        cache_service.set_hint_strategy("wacc_topic", strategy, ttl_minutes=10)
        
        # Get hint strategy
        result = cache_service.get_hint_strategy("wacc_topic")
        assert result == strategy
    
    def test_ui_render_methods(self, cache_service):
        """Test UI rendering specific caching methods."""
        render_result = {
            "widget_type": "practice_session",
            "render_time": 0.05,
            "content": "rendered_html"
        }
        
        # Set UI render cache
        cache_service.set_ui_render_cache("practice_widget_123", render_result, ttl_seconds=30)
        
        # Get UI render cache
        result = cache_service.get_ui_render_cache("practice_widget_123")
        assert result == render_result
    
    def test_thread_safety(self, cache_service):
        """Test that cache operations are thread-safe."""
        results = []
        
        def worker(thread_id):
            for i in range(10):
                key = f"thread_{thread_id}_key_{i}"
                value = f"thread_{thread_id}_value_{i}"
                cache_service.set(key, value)
                retrieved = cache_service.get(key)
                results.append((key, retrieved == value))
        
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All operations should have succeeded
        assert all(success for _, success in results)
    
    def test_custom_ttl_configuration(self, cache_service):
        """Test custom TTL configuration per cache type."""
        # Test cognitive state TTL
        cache_service.set_cognitive_state("test_topic", {"data": "test"}, ttl_minutes=1)
        
        # Test hint strategy TTL
        cache_service.set_hint_strategy("test_topic", {"strategy": "test"}, ttl_minutes=2)
        
        # Test UI render TTL
        cache_service.set_ui_render_cache("test_widget", {"render": "test"}, ttl_seconds=30)
        
        # Verify all were set successfully
        assert cache_service.get_cognitive_state("test_topic") is not None
        assert cache_service.get_hint_strategy("test_topic") is not None
        assert cache_service.get_ui_render_cache("test_widget") is not None
    
    def test_eviction_statistics(self, cache_service):
        """Test that eviction statistics are tracked correctly."""
        stats = cache_service.get_stats()
        initial_evictions = stats['evictions']
        
        # Fill cache beyond capacity to trigger eviction
        for i in range(110):
            cache_service.set(f"evict_test_{i}", f"value_{i}")
        
        stats = cache_service.get_stats()
        assert stats['evictions'] > initial_evictions
        assert stats['size'] <= cache_service.max_size
    
    def test_access_order_tracking(self):
        """Test that access order is properly maintained for LRU."""
        config = {
            'cache_max_size': 5,
            'default_ttl_seconds': 300,
            'cache_ttl': {}
        }
        small_cache = PerformanceCacheService(config)
        for i in range(5):
            small_cache.set(f"order_test_{i}", f"value_{i}")
        
        # Access items in a specific order to bump their LRU position
        small_cache.get("order_test_1")
        small_cache.get("order_test_3")
        small_cache.get("order_test_0")
        
        # Adding a new item should evict the least recently used (order_test_2 or order_test_4)
        small_cache.set("new_item", "new_value")
        
        assert "new_item" in small_cache._cache
        assert len(small_cache._cache) == 5
    
    def test_cleanup_expired_entries(self, cache_service):
        """Test that expired entries are cleaned up periodically."""
        # Set some entries with very short TTL
        cache_service.set("expiring_1", "value1", ttl_seconds=0.05)
        cache_service.set("expiring_2", "value2", ttl_seconds=0.05)
        
        # Set some entries with longer TTL
        cache_service.set("long_1", "value3", ttl_seconds=300)
        
        # Wait for short-lived entries to expire
        time.sleep(0.1)
        
        # Trigger cleanup by getting stats (happens every 100 requests)
        for _ in range(100):
            cache_service.get("nonexistent")
        
        stats = cache_service.get_stats()
        assert stats['size'] == 1  # Only long_1 should remain
        assert cache_service.get("expiring_1") is None
        assert cache_service.get("expiring_2") is None
        assert cache_service.get("long_1") is not None


class TestPerformanceCacheServiceFactory:
    """Test the factory function and configuration."""
    
    def test_create_performance_cache_service(self):
        """Test the factory function creates a properly configured service."""
        config = {
            'cache_max_size': 50,
            'default_ttl_seconds': 600,
            'cache_ttl': {
                'cognitive_state': 300,
                'hint_strategy': 600,
                'ui_render': 30
            }
        }
        
        service = create_performance_cache_service(config)
        
        assert isinstance(service, PerformanceCacheService)
        assert service.max_size == 50
        assert service.default_ttl == 600
        assert service.ttl_config['cognitive_state'] == 300
        assert service.ttl_config['hint_strategy'] == 600
        assert service.ttl_config['ui_render'] == 30
    
    def test_configuration_schema(self):
        """Test that the configuration schema is properly defined."""
        schema = PERFORMANCE_CACHE_CONFIG_SCHEMA
        
        assert 'cache_max_size' in schema
        assert 'default_ttl_seconds' in schema
        assert 'cache_ttl' in schema
        
        assert schema['cache_max_size']['type'] == 'integer'
        assert schema['default_ttl_seconds']['type'] == 'integer'
        assert schema['cache_ttl']['type'] == 'object'
        
        assert 'cognitive_state' in schema['cache_ttl']['properties']
        assert 'hint_strategy' in schema['cache_ttl']['properties']
        assert 'ui_render' in schema['cache_ttl']['properties']


class TestPerformanceCacheServiceEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_zero_size_cache(self):
        """Test behavior with zero-size cache."""
        config = {
            'cache_max_size': 0,
            'default_ttl_seconds': 300,
            'cache_ttl': {}
        }
        
        cache_service = PerformanceCacheService(config)
        
        # Should still allow operations but immediately evict
        cache_service.set("test", "value")
        result = cache_service.get("test")
        assert result is None  # Evicted immediately due to zero size
    
    def test_negative_ttl(self):
        """Test behavior with negative TTL."""
        config = {
            'cache_max_size': 100,
            'default_ttl_seconds': 300,
            'cache_ttl': {}
        }
        
        cache_service = PerformanceCacheService(config)
        
        # Negative TTL should be treated as expired immediately
        cache_service.set("test", "value", ttl_seconds=-1)
        result = cache_service.get("test")
        assert result is None
    
    def test_large_cache_operations(self):
        """Test performance with large number of operations."""
        config = {
            'cache_max_size': 1000,
            'default_ttl_seconds': 300,
            'cache_ttl': {}
        }
        
        cache_service = PerformanceCacheService(config)
        
        # Perform many operations
        start_time = time.time()
        for i in range(2000):
            cache_service.set(f"large_test_{i}", f"value_{i}")
            if i % 100 == 0:
                cache_service.get(f"large_test_{i-50}")
        
        end_time = time.time()
        
        # Should complete in reasonable time (less than 1 second for 2000 ops)
        assert end_time - start_time < 1.0
        
        # Cache should be at capacity
        stats = cache_service.get_stats()
        assert stats['size'] <= 1000
    
    def test_memory_usage_with_large_values(self):
        """Test handling of large cached values."""
        config = {
            'cache_max_size': 10,
            'default_ttl_seconds': 300,
            'cache_ttl': {}
        }
        
        cache_service = PerformanceCacheService(config)
        
        # Cache some large values
        large_value = "x" * 10000  # 10KB string
        for i in range(15):
            cache_service.set(f"large_{i}", large_value)
        
        # Should handle large values without issues
        stats = cache_service.get_stats()
        assert stats['size'] <= 10
        assert cache_service.get("large_14") == large_value