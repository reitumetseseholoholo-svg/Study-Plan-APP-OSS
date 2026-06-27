"""Tests for the performance integration layer."""

from typing import Any

from studyplan.performance_integration import (
    PerformanceIntegration,
    initialize_performance_services,
    cache_result,
    profile_operation,
    optimize_function,
    get_performance_cache,
    get_performance_profiler,
    get_performance_stats,
    clear_performance_cache,
    reset_performance_profiler,
)
from studyplan import performance_integration as pi_mod


BASE_CONFIG = {
    "PERFORMANCE_CACHE_ENABLED": True,
    "PERFORMANCE_CACHE_MAX_SIZE": 100,
    "PERFORMANCE_CACHE_DEFAULT_TTL_SECONDS": 300,
    "PERFORMANCE_CACHE_TTL_CONFIG": {
        "cognitive_state": 300,
        "hint_strategy": 600,
        "ui_render": 30,
    },
    "PERF_MONITOR_ENABLED": True,
    "PERF_THRESHOLDS": {
        "test_op": 50.0,
    },
}


def _apply_config(monkeypatch, overrides: dict[str, Any]) -> None:
    merged = dict(BASE_CONFIG)
    merged.update(overrides)
    for k, v in merged.items():
        monkeypatch.setattr(pi_mod.Config, k, v, raising=False)


class TestPerformanceIntegration:
    """Test the PerformanceIntegration class."""

    def test_initialize_cache_disabled(self, monkeypatch):
        _apply_config(monkeypatch, {"PERFORMANCE_CACHE_ENABLED": False})
        pi = PerformanceIntegration()
        pi.initialize()
        assert pi._initialized is True
        assert pi._cache_service is None
        assert pi._profiler is not None
        assert pi._middleware is None

    def test_initialize_cache_enabled(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()
        assert pi._initialized is True
        assert pi._cache_service is not None
        assert pi._profiler is not None
        assert pi._middleware is not None

    def test_initialize_idempotent(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()
        cache_id = id(pi._cache_service)
        pi.initialize()
        assert id(pi._cache_service) == cache_id

    def test_getters(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        assert pi.get_cache_service() is None
        assert pi.get_profiler() is None
        assert pi.get_middleware() is None
        pi.initialize()
        assert pi.get_cache_service() is pi._cache_service
        assert pi.get_profiler() is pi._profiler
        assert pi.get_middleware() is pi._middleware

    def test_cache_method_hit_miss(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()

        call_count: int = 0

        @pi.cache_method("test_prefix_", ttl_minutes=5)
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = compute(21)
        assert result1 == 42
        assert call_count == 1

        result2 = compute(21)
        assert result2 == 42
        assert call_count == 1

        result3 = compute(99)
        assert result3 == 198
        assert call_count == 2

    def test_cache_method_disabled_when_no_cache(self, monkeypatch):
        _apply_config(monkeypatch, {"PERFORMANCE_CACHE_ENABLED": False})
        pi = PerformanceIntegration()
        pi.initialize()

        call_count: int = 0

        @pi.cache_method("test_prefix_", ttl_minutes=5)
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        compute(1)
        compute(1)
        assert call_count == 2

    def test_profile_method_records_metrics(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()

        @pi.profile_method("test_compute_op")
        def compute(x: int) -> int:
            return x * 2

        compute(21)

        stats = pi._profiler.get_operation_stats("test_compute_op")
        assert stats is not None
        assert stats["total_calls"] == 1
        assert stats["success_rate"] == 1.0

    def test_profile_method_disabled_when_no_profiler(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()

        call_count: int = 0

        @pi.profile_method("test_compute_op")
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        assert compute(5) == 5
        assert call_count == 1

    def test_optimize_method_combines_cache_and_profile(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()

        call_count: int = 0

        @pi.optimize_method("test_opt_prefix_", ttl_minutes=5, operation_name="test_opt_op")
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 3

        r1 = compute(10)
        assert r1 == 30
        assert call_count == 1

        r2 = compute(10)
        assert r2 == 30
        assert call_count == 1

        stats = pi._profiler.get_operation_stats("test_opt_op")
        assert stats is not None
        assert stats["total_calls"] >= 1

    def test_generate_cache_key(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()

        def dummy_func() -> None:
            pass

        key1 = pi._generate_cache_key(dummy_func, "pfx_", (1, "a"), {"b": 2})
        assert key1.startswith("pfx_")

        key2 = pi._generate_cache_key(dummy_func, "pfx_", (1, "a"), {"b": 2})
        assert key1 == key2

        key3 = pi._generate_cache_key(dummy_func, "pfx_", (1, "b"), {"b": 2})
        assert key1 != key3

    def test_clear_cache(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()

        @pi.cache_method("test_clear_", ttl_minutes=5)
        def compute(x: int) -> int:
            return x

        compute(1)
        assert pi._cache_service.get_stats()["size"] == 1

        pi.clear_cache()

        assert pi._cache_service.get_stats()["size"] == 0

    def test_reset_profiler(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        pi.initialize()

        @pi.profile_method("test_reset_op")
        def compute(x: int) -> int:
            return x

        compute(1)
        assert pi._profiler.get_operation_stats("test_reset_op") is not None

        pi.reset_profiler()
        assert pi._profiler.get_operation_stats("test_reset_op") is None

    def test_get_performance_stats(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi = PerformanceIntegration()
        stats = pi.get_performance_stats()
        assert stats["initialized"] is False

        pi.initialize()
        stats = pi.get_performance_stats()
        assert stats["initialized"] is True
        assert stats["cache_service"] is not None
        assert stats["profiler"] is not None
        assert stats["middleware"] is not None

    def test_error_during_initialize_does_not_loop(self, monkeypatch):
        _apply_config(monkeypatch, {})

        def fail_init(self_obj, config):
            raise RuntimeError("init failure")

        monkeypatch.setattr(
            "studyplan.components.performance.caching.PerformanceCacheService.__init__",
            fail_init,
        )

        pi = PerformanceIntegration()
        pi.initialize()
        assert pi._initialized is True


class TestModuleLevelFunctions:
    """Test module-level convenience functions."""

    def _setup(self, monkeypatch):
        _apply_config(monkeypatch, {})
        pi_mod.performance_integration._initialized = False
        pi_mod.performance_integration._cache_service = None
        pi_mod.performance_integration._profiler = None
        pi_mod.performance_integration._middleware = None

    def test_initialize_performance_services(self, monkeypatch):
        self._setup(monkeypatch)
        initialize_performance_services()
        assert get_performance_cache() is not None
        assert get_performance_profiler() is not None

    def test_get_performance_stats(self, monkeypatch):
        self._setup(monkeypatch)
        initialize_performance_services()
        stats = get_performance_stats()
        assert stats["initialized"] is True

    def test_clear_and_reset(self, monkeypatch):
        self._setup(monkeypatch)
        initialize_performance_services()

        @cache_result("test_clear_func_", ttl_minutes=5)
        def compute(x: int) -> int:
            return x

        compute(1)
        cache = get_performance_cache()
        assert cache is not None
        assert cache.get_stats()["size"] >= 1

        clear_performance_cache()
        assert cache.get_stats()["size"] == 0

        profiler = get_performance_profiler()
        assert profiler is not None
        reset_performance_profiler()

    def test_cache_result_decorator(self, monkeypatch):
        self._setup(monkeypatch)
        initialize_performance_services()

        call_count: int = 0

        @cache_result("test_cache_decorator_", ttl_minutes=5)
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        compute(5)
        compute(5)
        assert call_count == 1

    def test_profile_operation_decorator(self, monkeypatch):
        self._setup(monkeypatch)
        initialize_performance_services()

        @profile_operation("test_profile_decorator_op")
        def compute(x: int) -> int:
            return x * 2

        compute(3)

        profiler = get_performance_profiler()
        assert profiler is not None
        stats = profiler.get_operation_stats("test_profile_decorator_op")
        assert stats is not None
        assert stats["total_calls"] == 1

    def test_optimize_function_decorator(self, monkeypatch):
        self._setup(monkeypatch)
        initialize_performance_services()

        call_count: int = 0

        @optimize_function("test_opt_decorator_", ttl_minutes=5, operation_name="test_opt_decorator_op")
        def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 4

        compute(3)
        compute(3)
        assert call_count == 1

        profiler = get_performance_profiler()
        assert profiler is not None
        stats = profiler.get_operation_stats("test_opt_decorator_op")
        assert stats is not None
        assert stats["total_calls"] >= 1
