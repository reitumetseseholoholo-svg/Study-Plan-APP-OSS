"""Lightweight circuit breaker for remote LLM backends.

Tracks consecutive failures per backend and temporarily skips backends
that have failed repeatedly, preventing cascading timeouts.

Usage::

    from studyplan.ai.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(threshold=3, cooldown_seconds=30.0)
    if cb.allow("cloud_endpoint"):
        try:
            response = call_cloud_endpoint()
            cb.record_success("cloud_endpoint")
        except Exception:
            cb.record_failure("cloud_endpoint")
    else:
        response = fallback_to_ollama()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class _BreakerState:
    consecutive_failures: int = 0
    last_failure_ts: float = 0.0
    tripped_until: float = 0.0


@dataclass
class CircuitBreaker:
    """Track per-backend circuit state.

    Parameters
    ----------
    threshold:
        Consecutive failures before the circuit opens (trips).
    cooldown_seconds:
        How long the circuit stays open before allowing a retry.
    """

    threshold: int = 3
    cooldown_seconds: float = 30.0
    _state: dict[str, _BreakerState] = field(default_factory=dict, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def allow(self, backend: str) -> bool:
        """Return True if *backend* is allowed to receive requests."""
        with self._lock:
            s = self._state.get(backend)
            if s is None:
                return True
            now = time.monotonic()
            if s.tripped_until > 0 and now < s.tripped_until:
                return False
            if s.tripped_until > 0 and now >= s.tripped_until:
                s.tripped_until = 0.0
                s.consecutive_failures = 0
            return True

    def record_success(self, backend: str) -> None:
        """Reset failure count for *backend* on success."""
        with self._lock:
            s = self._state.get(backend)
            if s is not None:
                s.consecutive_failures = 0
                s.tripped_until = 0.0

    def record_failure(self, backend: str) -> None:
        """Increment failure count; trip circuit if threshold reached."""
        with self._lock:
            s = self._state.setdefault(backend, _BreakerState())
            s.consecutive_failures += 1
            s.last_failure_ts = time.monotonic()
            if s.consecutive_failures >= self.threshold:
                s.tripped_until = s.last_failure_ts + self.cooldown_seconds

    def status(self, backend: str) -> dict:
        """Return diagnostic state for *backend*."""
        with self._lock:
            s = self._state.get(backend)
            if s is None:
                return {"backend": backend, "state": "closed", "consecutive_failures": 0}
            now = time.monotonic()
            if s.tripped_until > 0 and now < s.tripped_until:
                remaining = s.tripped_until - now
                return {
                    "backend": backend,
                    "state": "open",
                    "consecutive_failures": s.consecutive_failures,
                    "cooldown_remaining_s": round(remaining, 1),
                }
            return {
                "backend": backend,
                "state": "closed",
                "consecutive_failures": s.consecutive_failures,
            }

    def reset(self, backend: str) -> None:
        """Manually reset circuit for *backend*."""
        with self._lock:
            self._state.pop(backend, None)
