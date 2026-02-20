from __future__ import annotations

import math
from typing import Any


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return max(int(minimum), min(int(maximum), int(parsed)))


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    return max(float(minimum), min(float(maximum), float(parsed)))


def evaluate_latency_slo(
    latencies_ms: list[int],
    *,
    p50_target_ms: int,
    p90_target_ms: int,
    spread_target_ratio: float,
    min_samples: int,
) -> dict[str, Any]:
    cleaned = sorted(max(0, int(v)) for v in list(latencies_ms or []) if int(v) > 0)
    samples = int(len(cleaned))
    if not cleaned:
        return {
            "status": "insufficient",
            "samples": 0,
            "p50_latency_ms": 0.0,
            "p90_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "latency_spread_ratio": 1.0,
            "p50_target_ms": int(p50_target_ms),
            "p90_target_ms": int(p90_target_ms),
            "spread_target_ratio": float(spread_target_ratio),
            "min_samples": int(min_samples),
        }
    p50_idx = max(0, min(samples - 1, int(math.ceil(0.50 * samples)) - 1))
    p90_idx = max(0, min(samples - 1, int(math.ceil(0.90 * samples)) - 1))
    p95_idx = max(0, min(samples - 1, int(math.ceil(0.95 * samples)) - 1))
    p50 = float(cleaned[p50_idx])
    p90 = float(cleaned[p90_idx])
    p95 = float(cleaned[p95_idx])
    spread = float(p90 / max(1.0, p50))

    p50_target = _clamp_int(p50_target_ms, 25000, 5000, 180000)
    p90_target = _clamp_int(p90_target_ms, 60000, 10000, 240000)
    spread_target = _clamp_float(spread_target_ratio, 2.4, 1.1, 10.0)
    min_required = _clamp_int(min_samples, 8, 3, 120)

    status = "insufficient"
    if samples >= min_required:
        if p50 <= p50_target and p90 <= p90_target and spread <= spread_target:
            status = "pass"
        elif p50 <= (p50_target * 1.20) and p90 <= (p90_target * 1.25) and spread <= (spread_target * 1.20):
            status = "warn"
        else:
            status = "fail"

    return {
        "status": str(status),
        "samples": int(samples),
        "p50_latency_ms": float(p50),
        "p90_latency_ms": float(p90),
        "p95_latency_ms": float(p95),
        "latency_spread_ratio": float(spread),
        "p50_target_ms": int(p50_target),
        "p90_target_ms": int(p90_target),
        "spread_target_ratio": float(spread_target),
        "min_samples": int(min_required),
    }
