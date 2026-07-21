from __future__ import annotations

import time
import functools
from collections import defaultdict
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class PerformanceRegistry:
    """Shared singleton for kernel timing metrics.

    Every kernel subsystem writes high-resolution timing data here.
    The Kernel Observatory tab reads from it to display live metrics.
    Zero dependencies — pure dict-based accumulator.
    """

    def __init__(self) -> None:
        self._data: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self._counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def record(self, category: str, operation: str, duration_ms: float) -> None:
        self._data[category][operation].append(duration_ms)
        self._counts[category][operation] += 1

    def stats(self, category: str | None = None) -> dict[str, Any]:
        if category:
            return dict(self._data.get(category, {}))
        return {cat: dict(ops) for cat, ops in self._data.items()}

    def summary(self, category: str | None = None) -> dict[str, dict[str, float]]:
        cats = [category] if category else list(self._data.keys())
        result: dict[str, dict[str, float]] = {}
        for cat in cats:
            ops = self._data.get(cat, {})
            row: dict[str, float] = {}
            for op, vals in ops.items():
                row[f"{op}_calls"] = float(len(vals))
                row[f"{op}_total_ms"] = sum(vals)
                row[f"{op}_avg_ms"] = sum(vals) / max(len(vals), 1)
                row[f"{op}_max_ms"] = max(vals) if vals else 0.0
            result[cat] = row
        return result

    def top_consumers(self, n: int = 5) -> list[tuple[str, str, float]]:
        entries: list[tuple[str, str, float]] = []
        for cat, ops in self._data.items():
            for op, vals in ops.items():
                entries.append((cat, op, sum(vals)))
        entries.sort(key=lambda x: -x[2])
        return entries[:n]

    def reset(self, category: str | None = None) -> None:
        if category:
            self._data.pop(category, None)
            self._counts.pop(category, None)
        else:
            self._data.clear()
            self._counts.clear()

    @property
    def categories(self) -> list[str]:
        return sorted(self._data.keys())

    @property
    def total_calls(self) -> int:
        return sum(sum(c.values()) for c in self._counts.values())

    @property
    def total_time_ms(self) -> float:
        return sum(sum(sum(vals) for vals in ops.values()) for ops in self._data.values())


# ── Singleton ────────────────────────────────────────────────

_GLOBAL_REGISTRY: PerformanceRegistry | None = None


def get_performance_registry() -> PerformanceRegistry:
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = PerformanceRegistry()
    return _GLOBAL_REGISTRY


def set_performance_registry(reg: PerformanceRegistry | None) -> None:
    global _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = reg


# ── Timing decorator ─────────────────────────────────────────


def timed(category: str, operation: str | None = None):
    """Decorator: record execution time to PerformanceRegistry.

    Usage::

        @timed("planner", "plan")
        def plan(self, state, available):
            ...

    If ``operation`` is omitted, the decorated function's name is used.
    """

    def decorator(func: F) -> F:
        op_name = operation or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            reg = get_performance_registry()
            t0 = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - t0) * 1000.0
                reg.record(category, op_name, elapsed)

        return wrapper  # type: ignore[return-value]

    return decorator
