"""Tests for the performance optimization middleware (optimization.py).

Covers: PerformanceMiddleware with a mock cache service,
optimize_cognitive_update, optimize_hint_generation, optimize_ui_render,
throttling, cache miss/hit, clear_cache, get_cache_stats, and decorator.
"""

from __future__ import annotations

import time
from typing import Any


from studyplan.components.performance.optimization import (
    PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA,
    PerformanceMiddleware,
    create_performance_middleware,
    performance_optimized,
)


# ---------------------------------------------------------------------------
# Mock cache service
# ---------------------------------------------------------------------------


class MockCacheService:
    """Minimal in-memory implementation of PerformanceCacheService API."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._calls: list[str] = []

    def get_cognitive_state(self, key: str) -> Any | None:
        self._calls.append(f"get:{key}")
        return self._store.get(f"cognitive_state:{key}")

    def set_cognitive_state(self, key: str, value: Any, ttl_minutes: int = 5) -> None:
        self._calls.append(f"set:{key}")
        self._store[f"cognitive_state:{key}"] = value

    def get_hint_strategy(self, key: str) -> Any | None:
        self._calls.append(f"hint_get:{key}")
        return self._store.get(f"hint_strategy:{key}")

    def set_hint_strategy(self, key: str, value: Any, ttl_minutes: int = 10) -> None:
        self._calls.append(f"hint_set:{key}")
        self._store[f"hint_strategy:{key}"] = value

    def get_ui_render_cache(self, widget_id: str) -> Any | None:
        self._calls.append(f"ui_get:{widget_id}")
        return self._store.get(f"ui_render:{widget_id}")

    def set_ui_render_cache(self, widget_id: str, value: Any, ttl_seconds: int = 30) -> None:
        self._calls.append(f"ui_set:{widget_id}")
        self._store[f"ui_render:{widget_id}"] = value

    def clear(self) -> None:
        self._calls.append("clear:all")
        self._store.clear()

    def clear_prefix(self, prefix: str) -> None:
        self._calls.append(f"clear_prefix:{prefix}")
        for k in list(self._store):
            if k.startswith(prefix):
                del self._store[k]

    def get_stats(self) -> dict:
        self._calls.append("get_stats")
        return {"size": len(self._store)}


# ---------------------------------------------------------------------------
# PerformanceMiddleware — construction
# ---------------------------------------------------------------------------


def test_middleware_init() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)
    assert mw.cache is cache
    assert mw._throttle_window == 0.1


def test_middleware_create_factory() -> None:
    cache = MockCacheService()
    mw = create_performance_middleware(cache)
    assert isinstance(mw, PerformanceMiddleware)


# ---------------------------------------------------------------------------
# optimize_cognitive_update
# ---------------------------------------------------------------------------


def test_cognitive_update_cache_miss() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    def compute(x: int) -> int:
        return x * 2

    result = mw.optimize_cognitive_update(compute, 21)
    assert result == 42


def test_cognitive_update_cache_hit() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    def compute(x: int) -> int:
        return x * 2  # would give 42 for 21

    # First call — cache miss, compute
    mw.optimize_cognitive_update(compute, 21)
    # Second call — should hit cache
    result = mw.optimize_cognitive_update(compute, 21)
    assert result == 42  # same result from cache


def test_cognitive_update_different_args_bypass_cache() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)
    call_count: list[int] = [0]

    def compute(x: int) -> int:
        call_count[0] += 1
        return x * 2

    mw.optimize_cognitive_update(compute, 10)
    mw.optimize_cognitive_update(compute, 20)
    assert call_count[0] == 2  # both are cache misses (different keys)


# ---------------------------------------------------------------------------
# optimize_hint_generation
# ---------------------------------------------------------------------------


def test_hint_generation_cache_miss() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    def generate_hint(topic: str) -> str:
        return f"hint for {topic}"

    result = mw.optimize_hint_generation(generate_hint, "npv")
    assert result == "hint for npv"


def test_hint_generation_cache_hit() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)
    call_count: list[int] = [0]

    def generate_hint(topic: str) -> str:
        call_count[0] += 1
        return f"hint for {topic}"

    mw.optimize_hint_generation(generate_hint, "npv")
    mw.optimize_hint_generation(generate_hint, "npv")
    assert call_count[0] == 1  # cached on second call


# ---------------------------------------------------------------------------
# optimize_ui_render
# ---------------------------------------------------------------------------


def test_ui_render_first_call() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    def render() -> str:
        return "rendered"

    result = mw.optimize_ui_render("widget_a", render)
    assert result == "rendered"


def test_ui_render_throttle_reuses_cache() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)
    call_count: list[int] = [0]

    def render() -> str:
        call_count[0] += 1
        return "rendered"

    # First call — executes and caches
    mw.optimize_ui_render("widget_a", render)
    # Second call within throttle window — should return cached result
    result = mw.optimize_ui_render("widget_a", render)
    assert result == "rendered"
    assert call_count[0] == 1  # render only called once


def test_ui_render_after_throttle_expiry() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)
    mw._throttle_window = 0.01  # 10ms
    call_count: list[int] = [0]

    def render() -> str:
        call_count[0] += 1
        return "rendered"

    mw.optimize_ui_render("widget_b", render)
    time.sleep(0.02)
    mw.optimize_ui_render("widget_b", render)
    assert call_count[0] == 2


def test_ui_render_different_widgets() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)
    call_count: list[int] = [0]

    def render() -> str:
        call_count[0] += 1
        return "rendered"

    mw.optimize_ui_render("widget_1", render)
    mw.optimize_ui_render("widget_2", render)
    assert call_count[0] == 2


# ---------------------------------------------------------------------------
# _generate_cache_key
# ---------------------------------------------------------------------------


def test_cache_key_different_args() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    def fn_a() -> None:
        pass

    k1 = mw._generate_cache_key("type", fn_a, (1,), {})
    k2 = mw._generate_cache_key("type", fn_a, (2,), {})
    assert k1 != k2


def test_cache_key_different_types() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    def fn_a() -> None:
        pass

    k1 = mw._generate_cache_key("type_a", fn_a, (), {})
    k2 = mw._generate_cache_key("type_b", fn_a, (), {})
    assert k1 != k2


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------


def test_clear_cache_all() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    def noop() -> None:
        pass

    mw.optimize_cognitive_update(noop)
    mw.clear_cache()
    assert "clear:all" in cache._calls


def test_clear_cache_cognitive() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    mw.clear_cache("cognitive")
    assert any("cognitive_state:" in c for c in cache._calls)


def test_clear_cache_hint() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    mw.clear_cache("hint")
    assert any("hint_strategy:" in c for c in cache._calls)


def test_clear_cache_ui() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    mw.clear_cache("ui")
    assert any("ui_render:" in c for c in cache._calls)


def test_clear_cache_invalid_type() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    mw.clear_cache("invalid")
    # Should not call anything — only 'all' calls clear:all
    assert "clear:all" not in cache._calls


# ---------------------------------------------------------------------------
# get_cache_stats
# ---------------------------------------------------------------------------


def test_get_cache_stats() -> None:
    cache = MockCacheService()
    mw = PerformanceMiddleware(cache)

    stats = mw.get_cache_stats()
    assert isinstance(stats, dict)
    assert "get_stats" in cache._calls


# ---------------------------------------------------------------------------
# performance_optimized decorator
# ---------------------------------------------------------------------------


def test_decorator_cognitive_update() -> None:
    cache = MockCacheService()

    @performance_optimized(cache, "cognitive_update")
    def compute(x: int) -> int:
        return x + 1

    assert compute(41) == 42


def test_decorator_hint_generation() -> None:
    cache = MockCacheService()

    @performance_optimized(cache, "hint_generation")
    def hint(topic: str) -> str:
        return f"hint:{topic}"

    result = hint("npv")
    assert result == "hint:npv"


def test_decorator_ui_render() -> None:
    cache = MockCacheService()

    @performance_optimized(cache, "ui_render")
    def render(widget_id: str) -> str:
        return f"render:{widget_id}"

    result = render("widget_x")
    assert result == "render:widget_x"


def test_decorator_fallback() -> None:
    cache = MockCacheService()

    @performance_optimized(cache, "unknown_type")
    def op() -> str:
        return "fallback"

    assert op() == "fallback"


# ---------------------------------------------------------------------------
# PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA
# ---------------------------------------------------------------------------


def test_config_schema_structure() -> None:
    assert isinstance(PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA, dict)
    assert "throttle_window_seconds" in PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA
    assert "cache_ttl_cognitive_state" in PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA
    assert "cache_ttl_hint_strategy" in PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA
    assert "cache_ttl_ui_render" in PERFORMANCE_MIDDLEWARE_CONFIG_SCHEMA
