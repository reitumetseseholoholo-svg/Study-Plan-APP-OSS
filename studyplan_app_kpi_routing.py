"""
KPI thresholds and quiz gap routing helpers used by studyplan_app.
Extracted so tests can import them without pulling in GTK (gi).
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

# Latency SLO constants (used by SOAK_KPI_THRESHOLDS)
AI_TUTOR_LATENCY_SLO_P50_MS = 25000
AI_TUTOR_LATENCY_SLO_P90_MS = 60000
AI_TUTOR_LATENCY_SLO_SPREAD_RATIO = 2.4
AI_TUTOR_LATENCY_SLO_MIN_SAMPLES = 8

DEFAULT_OUTCOME_GAP_QUIZ_RATIO = 0.5

SMOKE_REPORT_PATH = os.path.expanduser("~/.config/studyplan/smoke_last.json")
SMOKE_KPI_THRESHOLDS: dict[str, dict[str, Any]] = {
    "coach_pick_consistency_rate": {"op": ">=", "value": 0.999},
    "coach_only_toggle_integrity_rate": {"op": "==", "value": 1.0},
    "coach_next_burst_integrity_rate": {"op": "==", "value": 1.0},
    "ui_trigger_integrity_rate": {"op": "==", "value": 1.0},
}

SOAK_REPORT_PATH = os.path.expanduser("~/.config/studyplan/soak_last.json")
SOAK_KPI_THRESHOLDS: dict[str, dict[str, Any]] = {
    "samples": {"op": ">=", "value": float(AI_TUTOR_LATENCY_SLO_MIN_SAMPLES)},
    "p50_latency_ms": {"op": "<=", "value": float(AI_TUTOR_LATENCY_SLO_P50_MS)},
    "p90_latency_ms": {"op": "<=", "value": float(AI_TUTOR_LATENCY_SLO_P90_MS)},
    "latency_spread_ratio": {"op": "<=", "value": float(AI_TUTOR_LATENCY_SLO_SPREAD_RATIO)},
}


def _merge_gap_and_srs_indices(gap_indices: list[int], srs_indices: list[int], total: int) -> list[int]:
    """Return ordered unique indices with gap-first precedence."""
    try:
        target = max(0, int(total))
    except Exception:
        target = 0
    if target <= 0:
        return []
    merged: list[int] = []
    seen: set[int] = set()
    for idx in list(gap_indices or []) + list(srs_indices or []):
        if not isinstance(idx, int):
            continue
        if idx in seen:
            continue
        seen.add(idx)
        merged.append(idx)
        if len(merged) >= target:
            break
    return merged[:target]


def _combine_quiz_indices(kind: str, primary_indices: list[int], total: int, gap_indices: list[int] | None = None) -> list[int]:
    """Combine selector outputs for a quiz session while preserving review semantics."""
    if str(kind or "").strip().lower() == "review":
        try:
            target = max(0, int(total))
        except Exception:
            target = 0
        return [idx for idx in list(primary_indices or [])[:target] if isinstance(idx, int)]
    return _merge_gap_and_srs_indices(list(gap_indices or []), list(primary_indices or []), total)


def _adjust_outcome_gap_ratio(base_ratio: float, capability_hit_rate: float | None) -> float:
    """Adjust outcome-gap quota ratio using recent capability-level KPI hit rate."""
    try:
        ratio = float(base_ratio)
    except Exception:
        ratio = DEFAULT_OUTCOME_GAP_QUIZ_RATIO
    ratio = max(0.0, min(1.0, ratio))
    if capability_hit_rate is None:
        return ratio
    try:
        hit_rate = float(capability_hit_rate)
    except Exception:
        return ratio
    if not math.isfinite(hit_rate):
        return ratio
    hit_rate = max(0.0, min(1.0, hit_rate))
    if hit_rate < 0.45:
        ratio += 0.20
    elif hit_rate < 0.60:
        ratio += 0.10
    elif hit_rate >= 0.85:
        ratio -= 0.10
    return max(0.20, min(0.90, ratio))


def _build_gap_routing_meta(
    kind: str,
    session_indices: list[int],
    gap_indices: list[int],
    requested_quota: int,
    eligible: bool,
    capability: str = "",
    capability_hit_rate: float | None = None,
) -> dict[str, Any]:
    """Build deterministic telemetry for outcome-gap routing quality."""
    kind_norm = str(kind or "").strip().lower()
    requested = max(0, int(requested_quota or 0))
    session_clean = [i for i in list(session_indices or []) if isinstance(i, int)]
    gap_unique: list[int] = []
    seen_gap: set[int] = set()
    for idx in list(gap_indices or []):
        if not isinstance(idx, int):
            continue
        if idx in seen_gap:
            continue
        seen_gap.add(idx)
        gap_unique.append(idx)
    gap_set = set(gap_unique)
    hit = sum(1 for idx in session_clean if idx in gap_set)
    denominator = max(1, requested)
    return {
        "kind": kind_norm,
        "eligible": bool(eligible),
        "requested": requested,
        "available": len(gap_unique),
        "hit": int(hit),
        "selected_total": len(session_clean),
        "hit_ratio": float(hit / denominator),
        "active": kind_norm in {"quiz", "drill", "leech"} and bool(eligible) and requested > 0,
        "capability": str(capability or "").strip().upper(),
        "capability_hit_rate": capability_hit_rate if isinstance(capability_hit_rate, (int, float)) else None,
    }


def _evaluate_smoke_kpi_thresholds(kpi: dict[str, Any]) -> list[dict[str, Any]]:
    """Return threshold failures for smoke KPI metrics."""
    failures: list[dict[str, Any]] = []
    metrics = kpi if isinstance(kpi, dict) else {}
    for metric, rule in SMOKE_KPI_THRESHOLDS.items():
        try:
            actual = float(metrics.get(metric, 0.0) or 0.0)
        except Exception:
            actual = 0.0
        op = str(rule.get("op", ">=") or ">=").strip()
        try:
            expected = float(rule.get("value", 0.0) or 0.0)
        except Exception:
            expected = 0.0
        if op == "==":
            passed = abs(actual - expected) <= 1e-9
        else:
            passed = actual >= expected
        if not passed:
            failures.append(
                {
                    "metric": metric,
                    "actual": actual,
                    "op": op,
                    "threshold": expected,
                }
            )
    return failures


def _compute_strict_smoke_exit_code(report_path: str = SMOKE_REPORT_PATH) -> int:
    """Return process exit code for strict smoke mode."""
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception:
        return 1
    if not isinstance(report, dict):
        return 1
    status = str(report.get("status", "") or "").strip().lower()
    if status != "passed":
        return 1
    failures = _evaluate_smoke_kpi_thresholds(report.get("kpi", {}))
    return 0 if not failures else 1


def _evaluate_soak_kpi_thresholds(kpi: dict[str, Any]) -> list[dict[str, Any]]:
    """Return threshold failures for latency soak KPI metrics."""
    failures: list[dict[str, Any]] = []
    metrics = kpi if isinstance(kpi, dict) else {}
    for metric, rule in SOAK_KPI_THRESHOLDS.items():
        try:
            actual = float(metrics.get(metric, 0.0) or 0.0)
        except Exception:
            actual = 0.0
        op = str(rule.get("op", "<=") or "<=").strip()
        try:
            expected = float(rule.get("value", 0.0) or 0.0)
        except Exception:
            expected = 0.0
        if op == "==":
            passed = abs(actual - expected) <= 1e-9
        elif op == ">=":
            passed = actual >= expected
        else:
            passed = actual <= expected
        if not passed:
            failures.append(
                {
                    "metric": metric,
                    "actual": actual,
                    "op": op,
                    "threshold": expected,
                }
            )
    return failures


def _compute_strict_soak_exit_code(report_path: str = SOAK_REPORT_PATH) -> int:
    """Return process exit code for strict soak mode."""
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except Exception:
        return 1
    if not isinstance(report, dict):
        return 1
    status = str(report.get("status", "") or "").strip().lower()
    if status != "passed":
        return 1
    failures = _evaluate_soak_kpi_thresholds(report.get("kpi", {}))
    return 0 if not failures else 1
