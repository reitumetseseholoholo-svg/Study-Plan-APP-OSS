"""Intelligent model selector.

Ranks discovered GGUF models by purpose (latency vs quality) and tracks
historical performance to improve selection over time.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .gguf_registry import GgufModel

log = logging.getLogger(__name__)


class Purpose:
    HINT = "hint"
    ASSESS = "assess"
    TUTOR = "tutor"
    DEEP_REASON = "deep_reason"
    COACH = "coach"
    GENERAL = "general"


_PURPOSE_TIERS: dict[str, str] = {
    Purpose.HINT: "fast",
    Purpose.ASSESS: "balanced",
    Purpose.TUTOR: "balanced",
    Purpose.DEEP_REASON: "quality",
    Purpose.COACH: "balanced",
    Purpose.GENERAL: "balanced",
}


@dataclass(frozen=True)
class ModelRanking:
    model: GgufModel
    score: float
    tier: str
    rationale: str


@dataclass
class PerfSample:
    model_name: str
    latency_ms: int
    tokens_generated: int
    success: bool
    purpose: str
    ts: float = field(default_factory=time.monotonic)


@dataclass
class ModelSelector:
    """Selects the best available GGUF model for a given purpose."""

    ram_budget_bytes: int = field(default=0)
    purpose_tier_overrides: dict[str, str] = field(default_factory=dict)
    _perf_history: list[PerfSample] = field(default_factory=list, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _MAX_HISTORY: int = 200

    def rank(
        self,
        models: list[GgufModel],
        purpose: str = Purpose.GENERAL,
    ) -> list[ModelRanking]:
        """Return models ranked best-first for the given purpose."""
        if not models:
            return []

        tier = self._resolve_tier(purpose)
        rankings = [self._score_model(m, tier, purpose) for m in models]
        rankings.sort(key=lambda r: -r.score)
        return rankings

    def pick_best(
        self,
        models: list[GgufModel],
        purpose: str = Purpose.GENERAL,
    ) -> GgufModel | None:
        ranked = self.rank(models, purpose)
        return ranked[0].model if ranked else None

    def record_outcome(
        self,
        model_name: str,
        *,
        latency_ms: int,
        tokens_generated: int = 0,
        success: bool = True,
        purpose: str = Purpose.GENERAL,
    ) -> None:
        sample = PerfSample(
            model_name=model_name,
            latency_ms=latency_ms,
            tokens_generated=tokens_generated,
            success=success,
            purpose=purpose,
        )
        with self._lock:
            self._perf_history.append(sample)
            if len(self._perf_history) > self._MAX_HISTORY:
                self._perf_history = self._perf_history[-self._MAX_HISTORY:]

    def get_model_stats(self, model_name: str) -> dict[str, Any]:
        with self._lock:
            samples = [s for s in self._perf_history if s.model_name == model_name]
        if not samples:
            return {"samples": 0}
        successes = [s for s in samples if s.success]
        latencies = [s.latency_ms for s in successes] if successes else []
        return {
            "samples": len(samples),
            "success_rate": len(successes) / len(samples) if samples else 0.0,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "p90_latency_ms": sorted(latencies)[int(len(latencies) * 0.9)] if latencies else 0,
        }

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _resolve_tier(self, purpose: str) -> str:
        if purpose in self.purpose_tier_overrides:
            return self.purpose_tier_overrides[purpose]
        return _PURPOSE_TIERS.get(purpose, "balanced")

    def _score_model(
        self, model: GgufModel, tier: str, purpose: str
    ) -> ModelRanking:
        score = 0.0
        rationale_parts: list[str] = []

        score += self._score_size(model, tier)
        score += self._score_quant(model, tier)
        score += self._score_instruct(model)
        score += self._score_architecture(model)
        score += self._score_ram_fit(model)
        score += self._score_historical_perf(model, purpose)

        rationale = "; ".join(rationale_parts) if rationale_parts else tier
        return ModelRanking(
            model=model, score=round(score, 3), tier=tier, rationale=rationale
        )

    def _score_size(self, model: GgufModel, tier: str) -> float:
        b = model.param_billions
        if b <= 0:
            b = model.size_bytes / (600_000_000)  # rough estimate from file size

        if tier == "fast":
            if b <= 1.5:
                return 10.0
            if b <= 3.0:
                return 5.0
            if b <= 7.0:
                return 1.0
            return -5.0
        elif tier == "quality":
            if b >= 7.0:
                return 10.0
            if b >= 3.0:
                return 6.0
            if b >= 1.5:
                return 2.0
            return 0.0
        else:  # balanced
            if 1.5 <= b <= 3.0:
                return 10.0
            if 3.0 < b <= 7.0:
                return 7.0
            if b < 1.5:
                return 4.0
            return 2.0

    def _score_quant(self, model: GgufModel, tier: str) -> float:
        q = model.quant_tag.lower()
        if tier == "fast":
            if "q4_0" in q:
                return 3.0
            if "q4_k" in q:
                return 2.5
            if "q2" in q or "q3" in q:
                return 3.5
            if "q8" in q or "fp16" in q or "f16" in q:
                return -1.0
            return 1.0
        elif tier == "quality":
            if "q4_k_m" in q:
                return 3.0
            if "q5" in q or "q6" in q:
                return 4.0
            if "q8" in q:
                return 5.0
            if "q4_0" in q:
                return 1.5
            if "q2" in q or "q3" in q:
                return -1.0
            return 2.0
        else:  # balanced
            if "q4_k_m" in q or "q4_k_s" in q:
                return 3.0
            if "q4_0" in q:
                return 2.0
            if "q5" in q:
                return 2.5
            if "q2" in q:
                return -0.5
            return 1.5

    @staticmethod
    def _score_instruct(model: GgufModel) -> float:
        return 3.0 if model.is_instruct else -1.0

    @staticmethod
    def _score_architecture(model: GgufModel) -> float:
        bonuses = {
            "qwen": 1.5,
            "llama": 1.5,
            "phi": 1.0,
            "gemma": 1.0,
            "deepseek": 0.5,
        }
        return bonuses.get(model.architecture, 0.0)

    def _score_ram_fit(self, model: GgufModel) -> float:
        if self.ram_budget_bytes <= 0:
            return 0.0
        overhead = 500_000_000  # ~500MB for llama-server runtime
        available = self.ram_budget_bytes - overhead
        if model.size_bytes > available:
            return -20.0
        headroom = (available - model.size_bytes) / available
        if headroom > 0.3:
            return 2.0
        return 0.5

    def _score_historical_perf(self, model: GgufModel, purpose: str) -> float:
        stats = self.get_model_stats(model.name)
        if stats.get("samples", 0) < 3:
            return 0.0
        success_rate = stats.get("success_rate", 0.0)
        bonus = (success_rate - 0.5) * 4.0
        avg_latency = stats.get("avg_latency_ms", 5000)
        if avg_latency < 3000:
            bonus += 1.5
        elif avg_latency > 10000:
            bonus -= 1.5
        return round(bonus, 2)
