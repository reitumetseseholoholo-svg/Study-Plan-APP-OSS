"""Tests for the intelligent model selector."""

from studyplan.ai.gguf_registry import GgufModel
from studyplan.ai.model_selector import ModelSelector, Purpose


def _model(
    name: str = "test-model",
    size_bytes: int = 1_000_000_000,
    architecture: str = "qwen",
    param_billions: float = 1.5,
    quant_tag: str = "q4_k_m",
    is_instruct: bool = True,
    source: str = "gpt4all",
) -> GgufModel:
    return GgufModel(
        name=name,
        path=f"/fake/{name}.gguf",
        size_bytes=size_bytes,
        source=source,
        architecture=architecture,
        param_billions=param_billions,
        quant_tag=quant_tag,
        is_instruct=is_instruct,
        content_hash="abc123",
    )


SMALL_QWEN = _model("qwen2.5-1.5b-instruct-q4_k_m", param_billions=1.5, size_bytes=986_000_000)
MEDIUM_LLAMA = _model("llama-3.2-3b-instruct-q4_0", param_billions=3.0, size_bytes=1_920_000_000, architecture="llama", quant_tag="q4_0")
LARGE_PHI = _model("phi-3-mini-4k-instruct-q4_0", param_billions=3.8, size_bytes=2_176_000_000, architecture="phi", quant_tag="q4_0")
BASE_MODEL = _model("llama-3.2-1b-q4_0", param_billions=1.0, is_instruct=False, architecture="llama", quant_tag="q4_0", size_bytes=738_000_000)
ALL_MODELS = [SMALL_QWEN, MEDIUM_LLAMA, LARGE_PHI, BASE_MODEL]


class TestPurposeTiers:
    def test_fast_prefers_small(self):
        sel = ModelSelector()
        ranked = sel.rank(ALL_MODELS, Purpose.HINT)
        assert ranked[0].model.name == SMALL_QWEN.name

    def test_balanced_prefers_medium(self):
        sel = ModelSelector()
        ranked = sel.rank(ALL_MODELS, Purpose.TUTOR)
        top = ranked[0].model
        assert top.param_billions >= 1.5

    def test_quality_prefers_large(self):
        sel = ModelSelector()
        ranked = sel.rank(ALL_MODELS, Purpose.DEEP_REASON)
        top = ranked[0].model
        assert top.param_billions >= 3.0

    def test_instruct_preferred_over_base(self):
        sel = ModelSelector()
        ranked = sel.rank(ALL_MODELS, Purpose.GENERAL)
        instruct_scores = {r.model.name: r.score for r in ranked if r.model.is_instruct}
        base_scores = {r.model.name: r.score for r in ranked if not r.model.is_instruct}
        best_instruct = max(instruct_scores.values())
        best_base = max(base_scores.values()) if base_scores else -999
        assert best_instruct > best_base


class TestPickBest:
    def test_returns_model(self):
        sel = ModelSelector()
        best = sel.pick_best(ALL_MODELS, Purpose.HINT)
        assert best is not None
        assert isinstance(best, GgufModel)

    def test_empty_list(self):
        sel = ModelSelector()
        assert sel.pick_best([], Purpose.HINT) is None


class TestRamBudget:
    def test_excludes_too_large(self):
        sel = ModelSelector(ram_budget_bytes=1_200_000_000)
        ranked = sel.rank(ALL_MODELS, Purpose.GENERAL)
        top = ranked[0].model
        assert top.size_bytes < 1_200_000_000

    def test_no_budget_includes_all(self):
        sel = ModelSelector(ram_budget_bytes=0)
        ranked = sel.rank(ALL_MODELS, Purpose.GENERAL)
        assert len(ranked) == len(ALL_MODELS)


class TestHistoricalPerf:
    def test_perf_recording(self):
        sel = ModelSelector()
        sel.record_outcome("test-model", latency_ms=500, success=True)
        sel.record_outcome("test-model", latency_ms=600, success=True)
        sel.record_outcome("test-model", latency_ms=700, success=True)
        stats = sel.get_model_stats("test-model")
        assert stats["samples"] == 3
        assert stats["success_rate"] == 1.0
        assert stats["avg_latency_ms"] == 600

    def test_no_history(self):
        sel = ModelSelector()
        stats = sel.get_model_stats("nonexistent")
        assert stats["samples"] == 0


class TestCustomTierOverrides:
    def test_override_hint_to_quality(self):
        sel = ModelSelector(purpose_tier_overrides={Purpose.HINT: "quality"})
        ranked = sel.rank(ALL_MODELS, Purpose.HINT)
        top = ranked[0].model
        assert top.param_billions >= 3.0
