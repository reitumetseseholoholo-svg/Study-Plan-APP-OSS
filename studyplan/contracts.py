from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AppStateSnapshot:
    module: str
    current_topic: str
    coach_pick: str
    days_to_exam: int | None
    must_review_due: int
    overdue_srs_count: int
    weak_topics_top3: tuple[str, ...] = ()
    risk_snapshot_top3: tuple[str, ...] = ()
    due_snapshot_top3: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TutorTurnRequest:
    model: str
    prompt: str
    history_fingerprint: str
    context_budget_chars: int
    rag_budget_chars: int


@dataclass(frozen=True)
class TutorTurnResult:
    text: str
    model: str
    latency_ms: int
    error_code: str = ""
    telemetry: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RagQueryRequest:
    query: str
    topic: str
    top_k: int
    char_budget: int
    semantic_enabled: bool


@dataclass(frozen=True)
class RagQueryResult:
    snippets: tuple[dict[str, Any], ...]
    method: str
    source_count: int
    candidate_count: int
    char_used: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AutopilotDecision:
    action: str
    topic: str
    duration_minutes: int
    reason: str
    confidence: float
    requires_confirmation: bool


@dataclass(frozen=True)
class AutopilotExecutionResult:
    executed: bool
    action: str
    reason: str
    blocked_reason: str = ""


@dataclass(frozen=True)
class ModelPerfStats:
    model: str
    samples: int
    success: int
    errors: int
    cancelled: int
    latency_ms_sum: float
    response_tokens_sum: float
    coverage_target_sum: int = 0
    coverage_hit_sum: int = 0


@dataclass(frozen=True)
class SloProfile:
    status: str
    samples: int
    p50_latency_ms: float
    p90_latency_ms: float
    p95_latency_ms: float
    latency_spread_ratio: float
    p50_target_ms: int
    p90_target_ms: int
    spread_target_ratio: float
    min_samples: int
