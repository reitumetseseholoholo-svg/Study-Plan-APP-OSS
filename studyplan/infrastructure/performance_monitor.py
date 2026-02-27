from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time
from typing import Any, Iterator


@dataclass
class _OperationStats:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0
    error_count: int = 0


class PerformanceMonitor:
    """Thread-safe lightweight operation timing monitor."""

    def __init__(self, *, enabled: bool = False, max_operations: int = 512) -> None:
        self.enabled = bool(enabled)
        self.max_operations = max(8, int(max_operations))
        self._stats: dict[str, _OperationStats] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    @contextmanager
    def track(self, operation: str) -> Iterator[dict[str, Any]]:
        if not self.enabled:
            yield {"operation": str(operation or "").strip(), "elapsed_ms": 0.0, "ok": True}
            return
        name = str(operation or "").strip() or "unknown"
        started = float(time.monotonic())
        payload: dict[str, Any] = {"operation": name, "elapsed_ms": 0.0, "ok": True}
        try:
            yield payload
        except Exception:
            payload["ok"] = False
            raise
        finally:
            elapsed_ms = max(0.0, (float(time.monotonic()) - started) * 1000.0)
            payload["elapsed_ms"] = elapsed_ms
            self.record(name, elapsed_ms, ok=bool(payload.get("ok", True)))

    def record(self, operation: str, elapsed_ms: float, *, ok: bool = True) -> None:
        if not self.enabled:
            return
        name = str(operation or "").strip() or "unknown"
        ms = max(0.0, float(elapsed_ms or 0.0))
        with self._lock:
            stat = self._stats.get(name)
            if stat is None:
                stat = _OperationStats()
                self._stats[name] = stat
                self._order.append(name)
            stat.count += 1
            stat.total_ms += ms
            stat.last_ms = ms
            if ms > stat.max_ms:
                stat.max_ms = ms
            if not bool(ok):
                stat.error_count += 1
            if len(self._order) > self.max_operations:
                stale = self._order.pop(0)
                self._stats.pop(stale, None)

    def snapshot(self, *, limit: int = 32) -> dict[str, Any]:
        with self._lock:
            names = list(self._order)[-max(1, int(limit)) :]
            rows: dict[str, dict[str, float | int]] = {}
            for name in names:
                stat = self._stats.get(name)
                if stat is None:
                    continue
                avg = (float(stat.total_ms) / float(max(1, stat.count)))
                rows[name] = {
                    "count": int(stat.count),
                    "avg_ms": float(avg),
                    "max_ms": float(stat.max_ms),
                    "last_ms": float(stat.last_ms),
                    "error_count": int(stat.error_count),
                }
        return {
            "enabled": bool(self.enabled),
            "tracked_operations": int(len(rows)),
            "operations": rows,
        }

