"""Tests for per-model inference tuning (model_infer_tuning.py).

Covers: ModelRuntimeTuning, bucket size, arch hints, purpose task kind,
base tuning table, purpose modifiers, model-specific defaults, coerce
helpers, patch tuning, JSON profile merging, and the full resolve pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studyplan.ai.model_infer_tuning import (
    ModelRuntimeTuning,
    _apply_model_specific_defaults,
    _apply_purpose,
    _arch_hint,
    _base_tuning_for_bucket,
    _coerce_float,
    _coerce_int,
    _config_path_candidates,
    _load_json_profile,
    _merge_json_profile,
    _patch_tuning,
    _purpose_task_kind,
    _size_bucket,
    clear_model_runtime_tuning_cache,
    resolve_model_runtime_tuning,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_tuning_cache():
    clear_model_runtime_tuning_cache()
    yield
    clear_model_runtime_tuning_cache()


# ---------------------------------------------------------------------------
# ModelRuntimeTuning
# ---------------------------------------------------------------------------


def test_model_runtime_tuning_defaults() -> None:
    t = ModelRuntimeTuning()
    assert t.temperature == 0.28
    assert t.top_p == 0.92
    assert t.num_ctx == 4096
    assert t.thread_multiplier == 1.0
    assert t.thread_cap is None
    assert t.max_output_tokens == 1408
    assert t.llama_server_threads is None


def test_model_runtime_tuning_custom() -> None:
    t = ModelRuntimeTuning(temperature=0.5, num_ctx=8192, thread_cap=4)
    assert t.temperature == 0.5
    assert t.num_ctx == 8192
    assert t.thread_cap == 4


# ---------------------------------------------------------------------------
# _size_bucket
# ---------------------------------------------------------------------------


def test_size_bucket_none() -> None:
    assert _size_bucket(None) == "unknown"


def test_size_bucket_negative() -> None:
    assert _size_bucket(-1.0) == "unknown"


def test_size_bucket_zero() -> None:
    assert _size_bucket(0.0) == "unknown"


def test_size_bucket_tiny() -> None:
    assert _size_bucket(0.5) == "tiny"
    assert _size_bucket(1.5) == "tiny"


def test_size_bucket_small() -> None:
    assert _size_bucket(2.0) == "small"
    assert _size_bucket(3.0) == "small"


def test_size_bucket_medium() -> None:
    assert _size_bucket(4.0) == "medium"
    assert _size_bucket(8.0) == "medium"


def test_size_bucket_large() -> None:
    assert _size_bucket(10.0) == "large"
    assert _size_bucket(14.0) == "large"


def test_size_bucket_xlarge() -> None:
    assert _size_bucket(20.0) == "xlarge"


# ---------------------------------------------------------------------------
# _arch_hint
# ---------------------------------------------------------------------------


def test_arch_hint_phi() -> None:
    assert _arch_hint("phi-3-mini") == "phi"


def test_arch_hint_gemma() -> None:
    assert _arch_hint("gemma-2-2b") == "gemma"


def test_arch_hint_qwen() -> None:
    assert _arch_hint("qwen-2.5-7b") == "qwen"


def test_arch_hint_mistral() -> None:
    assert _arch_hint("mistral-7b") == "mistral"


def test_arch_hint_llama() -> None:
    assert _arch_hint("llama-3.1-8b") == "llama"


def test_arch_hint_deepseek() -> None:
    assert _arch_hint("deepseek-coder-6.7b") == "deepseek"


def test_arch_hint_unknown() -> None:
    assert _arch_hint("some-random-model") == ""


def test_arch_hint_empty() -> None:
    assert _arch_hint("") == ""
    assert _arch_hint(None) == ""


# ---------------------------------------------------------------------------
# _purpose_task_kind
# ---------------------------------------------------------------------------


def test_purpose_task_kind_coach() -> None:
    assert _purpose_task_kind("coach") == "json_task"
    assert _purpose_task_kind("autopilot") == "json_task"
    assert _purpose_task_kind("gap_generation") == "json_task"
    assert _purpose_task_kind("assess") == "json_task"
    assert _purpose_task_kind("judge") == "json_task"
    assert _purpose_task_kind("section_c_evaluation") == "json_task"
    assert _purpose_task_kind("section_c_loop_diff") == "json_task"


def test_purpose_task_kind_judgment() -> None:
    assert _purpose_task_kind("section_c_judgment") == "judgment_task"


def test_purpose_task_kind_deep_reason() -> None:
    assert _purpose_task_kind("deep_reason") == "deep_tutor"


def test_purpose_task_kind_tutor() -> None:
    assert _purpose_task_kind("tutor") == "tutor"
    assert _purpose_task_kind("") == "tutor"
    assert _purpose_task_kind("unknown") == "tutor"


# ---------------------------------------------------------------------------
# _base_tuning_for_bucket
# ---------------------------------------------------------------------------


def test_base_tuning_unknown() -> None:
    t = _base_tuning_for_bucket("unknown", "")
    assert t == ModelRuntimeTuning()


def test_base_tuning_tiny() -> None:
    t = _base_tuning_for_bucket("tiny", "")
    assert t.temperature == 0.40
    assert t.max_output_tokens == 1280


def test_base_tuning_small() -> None:
    t = _base_tuning_for_bucket("small", "")
    assert t.temperature == 0.34
    assert t.max_output_tokens == 1344


def test_base_tuning_medium() -> None:
    t = _base_tuning_for_bucket("medium", "")
    assert t.temperature == 0.28
    assert t.thread_multiplier == 0.95


def test_base_tuning_large() -> None:
    t = _base_tuning_for_bucket("large", "")
    assert t.temperature == 0.24
    assert t.thread_multiplier == 0.88
    assert t.llama_server_batch_size == 384


def test_base_tuning_xlarge() -> None:
    t = _base_tuning_for_bucket("xlarge", "")
    assert t.temperature == 0.20
    assert t.thread_cap == 8
    assert t.llama_server_batch_size == 256


def test_base_tuning_arch_phi_gemma() -> None:
    t = _base_tuning_for_bucket("medium", "phi")
    assert t.temperature == 0.32  # 0.28 + 0.04, capped at 0.42
    t2 = _base_tuning_for_bucket("medium", "gemma")
    assert t2.temperature == 0.32


def test_base_tuning_arch_qwen_deepseek() -> None:
    t = _base_tuning_for_bucket("medium", "qwen")
    assert t.temperature == 0.25  # 0.28 - 0.03, floored at 0.12
    t2 = _base_tuning_for_bucket("medium", "deepseek")
    assert t2.temperature == 0.25


def test_base_tuning_arch_mistral() -> None:
    t = _base_tuning_for_bucket("medium", "mistral")
    assert t.top_p == 0.92  # 0.92 + 0.01, capped at 0.92


# ---------------------------------------------------------------------------
# _apply_purpose
# ---------------------------------------------------------------------------


def test_apply_purpose_tutor() -> None:
    base = ModelRuntimeTuning(temperature=0.30, top_p=0.92)
    t = _apply_purpose(base, "tutor")
    assert t == base


def test_apply_purpose_json_task() -> None:
    base = ModelRuntimeTuning(temperature=0.30, top_p=0.92, thread_multiplier=0.8)
    t = _apply_purpose(base, "json_task")
    assert t.temperature == 0.195  # 0.30 * 0.65 = 0.195
    assert t.top_p == 0.90  # min(0.90, 0.92)
    assert t.thread_multiplier == pytest.approx(0.85, rel=1e-9)  # min(1.0, 0.8 + 0.05)


def test_apply_purpose_judgment_task() -> None:
    base = ModelRuntimeTuning(temperature=0.30, top_p=0.92, max_output_tokens=1408, num_ctx=4096)
    t = _apply_purpose(base, "judgment_task")
    assert t.temperature == 0.216  # 0.30 * 0.72
    assert t.max_output_tokens == min(4096, int(1408 * 1.4))
    assert t.num_ctx == max(4096, min(8192, int(4096 * 1.05)))


def test_apply_purpose_deep_tutor() -> None:
    base = ModelRuntimeTuning(temperature=0.30, top_p=0.92, max_output_tokens=1408, num_ctx=4096)
    t = _apply_purpose(base, "deep_tutor")
    assert t.temperature == 0.25  # 0.30 - 0.05, floored at 0.12
    assert t.max_output_tokens == min(2048, int(1408 * 1.1))
    assert t.num_ctx == max(4096, min(8192, int(4096 * 1.15)))


# ---------------------------------------------------------------------------
# _apply_model_specific_defaults
# ---------------------------------------------------------------------------


def test_model_specific_qwen35_4b_coach() -> None:
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92, num_ctx=4096)
    t = _apply_model_specific_defaults("qwen3.5-4b", "coach", base)
    assert t.temperature == 0.14
    assert t.top_p == 0.88
    assert t.num_ctx == 3072
    assert t.max_output_tokens == 960
    assert t.llama_server_batch_size == 512


def test_model_specific_qwen35_4b_tutor() -> None:
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92, num_ctx=4096)
    t = _apply_model_specific_defaults("qwen3.5-4b", "tutor", base)
    assert t.temperature == 0.22
    assert t.top_p == 0.90
    assert t.num_ctx == 4096
    assert t.max_output_tokens == 1280


def test_model_specific_phi4_mini() -> None:
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92, num_ctx=8192)
    t = _apply_model_specific_defaults("phi-4-mini", "tutor", base)
    assert t.num_ctx == 4096


def test_model_specific_unmatched() -> None:
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92)
    t = _apply_model_specific_defaults("llama-3.2-3b", "tutor", base)
    assert t == base


# ---------------------------------------------------------------------------
# _coerce_float / _coerce_int
# ---------------------------------------------------------------------------


def test_coerce_float() -> None:
    assert _coerce_float(3.14, 0.0) == 3.14
    assert _coerce_float("2.5", 0.0) == 2.5
    assert _coerce_float("not_a_number", 1.0) == 1.0
    assert _coerce_float(None, 0.5) == 0.5


def test_coerce_int() -> None:
    assert _coerce_int(42, 0) == 42
    assert _coerce_int("7", 0) == 7
    assert _coerce_int("bad", 10) == 10
    assert _coerce_int(None, 5) == 5


# ---------------------------------------------------------------------------
# _patch_tuning
# ---------------------------------------------------------------------------


def test_patch_tuning_empty() -> None:
    base = ModelRuntimeTuning(temperature=0.28)
    assert _patch_tuning(base, {}) == base


def test_patch_tuning_temperature() -> None:
    base = ModelRuntimeTuning(temperature=0.28)
    t = _patch_tuning(base, {"temperature": 0.7})
    assert t.temperature == 0.7


def test_patch_tuning_clamps() -> None:
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92)
    t = _patch_tuning(base, {"temperature": 5.0, "top_p": -1.0})
    assert t.temperature == 2.0
    assert t.top_p == 0.0


def test_patch_tuning_thread_cap_none() -> None:
    base = ModelRuntimeTuning(thread_cap=8)
    t = _patch_tuning(base, {"thread_cap": None})
    assert t.thread_cap is None


def test_patch_tuning_thread_cap_value() -> None:
    base = ModelRuntimeTuning(thread_cap=None)
    t = _patch_tuning(base, {"thread_cap": 4})
    assert t.thread_cap == 4


def test_patch_tuning_llama_server_threads() -> None:
    base = ModelRuntimeTuning(llama_server_threads=None)
    t = _patch_tuning(base, {"llama_server_threads": 6})
    assert t.llama_server_threads == 6


def test_patch_tuning_llama_server_threads_none() -> None:
    base = ModelRuntimeTuning(llama_server_threads=4)
    t = _patch_tuning(base, {"llama_server_threads": None})
    assert t.llama_server_threads is None


def test_patch_tuning_llama_server_ctx_size() -> None:
    base = ModelRuntimeTuning(num_ctx=4096)
    t = _patch_tuning(base, {"llama_server_ctx_size": 8192})
    assert t.llama_server_ctx_size == 8192


def test_patch_tuning_llama_server_n_gpu_layers() -> None:
    base = ModelRuntimeTuning()
    t = _patch_tuning(base, {"llama_server_n_gpu_layers": -1})
    assert t.llama_server_n_gpu_layers == -1


def test_patch_tuning_llama_server_batch_size() -> None:
    base = ModelRuntimeTuning()
    t = _patch_tuning(base, {"llama_server_batch_size": 1024})
    assert t.llama_server_batch_size == 1024


# ---------------------------------------------------------------------------
# _config_path_candidates
# ---------------------------------------------------------------------------


def test_config_path_candidates_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = tmp_path / "runtime.json"
    dummy.touch()
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(dummy))
    candidates = _config_path_candidates()
    assert str(dummy) in [str(p) for p in candidates]


def test_config_path_candidates_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", raising=False)
    candidates = _config_path_candidates()
    assert any("llm_model_runtime.json" in str(p) for p in candidates)


# ---------------------------------------------------------------------------
# _load_json_profile
# ---------------------------------------------------------------------------


def test_load_json_profile_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_DISABLE", "1")
    assert _load_json_profile() == {}


def test_load_json_profile_disabled_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_DISABLE", "true")
    assert _load_json_profile() == {}


def test_load_json_profile_empty_when_no_file() -> None:
    assert _load_json_profile() == {}


def test_load_json_profile_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"exact": {"test-model": {"temperature": 0.5}}}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    data = _load_json_profile()
    assert data == cfg


def test_load_json_profile_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"exact": {"m": {"temperature": 0.5}}}
    path = tmp_path / "cached.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    assert _load_json_profile() == cfg
    # Second call returns same (no re-read)
    assert _load_json_profile() == cfg


# ---------------------------------------------------------------------------
# _merge_json_profile
# ---------------------------------------------------------------------------


def test_merge_json_profile_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"exact": {"my-model:latest": {"temperature": 0.99}}}
    path = tmp_path / "merge.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    base = ModelRuntimeTuning(temperature=0.28)
    merged = _merge_json_profile("my-model:latest", base)
    assert merged.temperature == 0.99


def test_merge_json_profile_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"prefixes": [{"prefix": "my-", "tuning": {"temperature": 0.1}}]}
    path = tmp_path / "prefix.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    base = ModelRuntimeTuning(temperature=0.28)
    merged = _merge_json_profile("my-model", base)
    assert merged.temperature == 0.1


def test_merge_json_profile_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"exact": {"other:latest": {"temperature": 0.99}}}
    path = tmp_path / "nomerge.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    base = ModelRuntimeTuning(temperature=0.28)
    merged = _merge_json_profile("my-model:latest", base)
    assert merged.temperature == 0.28


def test_merge_json_profile_prefix_longest_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "prefixes": [
            {"prefix": "my-", "tuning": {"temperature": 0.1}},
            {"prefix": "my-model-", "tuning": {"temperature": 0.05}},
        ]
    }
    path = tmp_path / "longest.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    base = ModelRuntimeTuning(temperature=0.28)
    merged = _merge_json_profile("my-model-v2", base)
    assert merged.temperature == 0.05


# ---------------------------------------------------------------------------
# resolve_model_runtime_tuning (full pipeline)
# ---------------------------------------------------------------------------


def test_resolve_unknown_model() -> None:
    result = resolve_model_runtime_tuning("unknown-model:latest", purpose="tutor")
    assert isinstance(result, ModelRuntimeTuning)
    assert result.temperature == 0.28  # unknown -> default


def test_resolve_tiny_model() -> None:
    class TinyGGUF:
        param_billions = 1.0

    result = resolve_model_runtime_tuning("custom-tiny", purpose="tutor", gguf=TinyGGUF())
    assert result.temperature == 0.40
    assert result.max_output_tokens == 1280


def test_resolve_with_gguf() -> None:
    class FakeGGUF:
        param_billions = 7.0
        architecture = "llama"

    result = resolve_model_runtime_tuning("custom", purpose="tutor", gguf=FakeGGUF())
    assert result.llama_server_batch_size == 512  # medium bucket
    assert result.temperature == 0.28


def test_resolve_with_gguf_missing_attr() -> None:
    class FakeGGUF:
        pass

    result = resolve_model_runtime_tuning("phi-3-mini", purpose="tutor", gguf=FakeGGUF())
    assert isinstance(result, ModelRuntimeTuning)


def test_resolve_purpose_json() -> None:
    result = resolve_model_runtime_tuning("medium-model", purpose="assess")
    assert result.temperature < 0.28  # json_task reduces temperature


def test_resolve_model_specific_qwen() -> None:
    result = resolve_model_runtime_tuning("qwen3.5-4b", purpose="coach")
    assert result.temperature == 0.14
    assert result.max_output_tokens == 960


def test_resolve_model_specific_phi() -> None:
    result = resolve_model_runtime_tuning("phi-4-mini", purpose="tutor")
    assert result.num_ctx <= 4096


# ---------------------------------------------------------------------------
# Edge cases — model_infer_tuning
# ---------------------------------------------------------------------------


def test_model_runtime_tuning_frozen() -> None:
    t = ModelRuntimeTuning(temperature=0.5)
    with pytest.raises(AttributeError):
        t.temperature = 0.9  # type: ignore[misc]


def test_size_bucket_edge_boundaries() -> None:
    assert _size_bucket(0.001) == "tiny"
    assert _size_bucket(1.5) == "tiny"
    assert _size_bucket(1.51) == "small"
    assert _size_bucket(3.01) == "medium"
    assert _size_bucket(8.01) == "large"
    assert _size_bucket(14.01) == "xlarge"


def test_arch_hint_substring_protection() -> None:
    """Should not match tokens embedded in larger words."""
    assert _arch_hint("myphi-3") == ""  # 'phi' embedded, no boundary
    assert _arch_hint("phi-3") == "phi"
    assert _arch_hint("notphi") == ""  # no boundary
    assert _arch_hint("llama") == "llama"


def test_arch_hint_matches_known_tokens() -> None:
    assert _arch_hint("tinyllama-1.1b") == "tinyllama"
    assert _arch_hint("orca-2-7b") == "orca"


def test_purpose_task_kind_case_insensitive() -> None:
    assert _purpose_task_kind("COACH") == "json_task"
    assert _purpose_task_kind("Deep_Reason") == "deep_tutor"


def test_base_tuning_tiny_phi_arch() -> None:
    t = _base_tuning_for_bucket("tiny", "phi")
    assert t.temperature == 0.42  # 0.40 + 0.04 capped at 0.42


def test_base_tuning_large_deepseek_arch() -> None:
    t = _base_tuning_for_bucket("large", "deepseek")
    assert t.temperature == 0.21  # 0.24 - 0.03


def test_apply_purpose_json_task_min_temp() -> None:
    base = ModelRuntimeTuning(temperature=0.05, top_p=0.92)
    t = _apply_purpose(base, "json_task")
    assert t.temperature == 0.08  # max(0.08, 0.05*0.65)


def test_apply_purpose_deep_tutor_min_temp() -> None:
    base = ModelRuntimeTuning(temperature=0.08, top_p=0.92)
    t = _apply_purpose(base, "deep_tutor")
    assert t.temperature == 0.12  # max(0.12, 0.08-0.05)


def test_apply_model_specific_qwen35_4b_other_purpose() -> None:
    """Should return base unchanged for an unmatched purpose."""
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92, num_ctx=4096)
    t = _apply_model_specific_defaults("qwen3.5-4b", "unknown_purpose", base)
    assert t == base


def test_apply_model_specific_phi4_mini_case() -> None:
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92, num_ctx=8192)
    t = _apply_model_specific_defaults("Phi-4-Mini", "tutor", base)
    assert t.num_ctx == 4096


def test_apply_model_specific_phi4_mini_lower_bound() -> None:
    base = ModelRuntimeTuning(temperature=0.28, top_p=0.92, num_ctx=1024)
    t = _apply_model_specific_defaults("phi-4-mini", "tutor", base)
    assert t.num_ctx == 2048  # max(2048, min(4096, 1024))


def test_coerce_float_none() -> None:
    assert _coerce_float(None, 0.5) == 0.5


def test_coerce_float_string() -> None:
    assert _coerce_float("3.14", 0.0) == 3.14


def test_coerce_int_none() -> None:
    assert _coerce_int(None, 10) == 10


def test_coerce_int_bool() -> None:
    assert _coerce_int(True, 0) == 1


def test_patch_tuning_empty_patch() -> None:
    base = ModelRuntimeTuning(temperature=0.28)
    assert _patch_tuning(base, None) == base


def test_patch_tuning_all_fields() -> None:
    base = ModelRuntimeTuning()
    patch = {
        "temperature": 0.5,
        "top_p": 0.8,
        "num_ctx": 8192,
        "thread_multiplier": 1.2,
        "thread_cap": 4,
        "max_output_tokens": 2048,
        "llama_server_threads": 8,
        "llama_server_ctx_size": 8192,
        "llama_server_n_gpu_layers": 0,
        "llama_server_batch_size": 1024,
    }
    t = _patch_tuning(base, patch)
    assert t.temperature == 0.5
    assert t.top_p == 0.8
    assert t.num_ctx == 8192
    assert t.thread_multiplier == 1.2
    assert t.thread_cap == 4
    assert t.max_output_tokens == 2048
    assert t.llama_server_threads == 8
    assert t.llama_server_ctx_size == 8192
    assert t.llama_server_n_gpu_layers == 0
    assert t.llama_server_batch_size == 1024


def test_patch_tuning_clamp_range() -> None:
    base = ModelRuntimeTuning()
    patch = {
        "temperature": 5.0,
        "top_p": -1.0,
        "num_ctx": 100000,
        "thread_multiplier": 10.0,
        "thread_cap": 100,
        "max_output_tokens": 100000,
        "llama_server_threads": 100,
        "llama_server_ctx_size": 100000,
        "llama_server_n_gpu_layers": 100000,
        "llama_server_batch_size": 100000,
    }
    t = _patch_tuning(base, patch)
    assert t.temperature == 2.0
    assert t.top_p == 0.0
    assert t.num_ctx == 32768
    assert t.thread_multiplier == 1.5
    assert t.thread_cap == 32
    assert t.max_output_tokens == 8192
    assert t.llama_server_threads == 32
    assert t.llama_server_ctx_size == 32768
    assert t.llama_server_n_gpu_layers == 100000
    assert t.llama_server_batch_size == 4096


def test_patch_tuning_null_strings() -> None:
    base = ModelRuntimeTuning(thread_cap=8, llama_server_threads=4)
    patch = {
        "thread_cap": "none",
        "llama_server_threads": "null",
        "llama_server_ctx_size": "",
    }
    t = _patch_tuning(base, patch)
    assert t.thread_cap is None
    assert t.llama_server_threads is None
    assert t.llama_server_ctx_size is None


def test_patch_tuning_llama_server_gpu_negative() -> None:
    base = ModelRuntimeTuning()
    t = _patch_tuning(base, {"llama_server_n_gpu_layers": -2})
    assert t.llama_server_n_gpu_layers == -1


def test_merge_json_profile_empty_exact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"exact": {}}
    path = tmp_path / "empty_exact.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    base = ModelRuntimeTuning()
    merged = _merge_json_profile("test", base)
    assert merged == base


def test_merge_json_profile_empty_prefixes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"prefixes": []}
    path = tmp_path / "empty_prefix.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(path))
    clear_model_runtime_tuning_cache()
    base = ModelRuntimeTuning()
    merged = _merge_json_profile("test", base)
    assert merged == base


def test_resolve_with_unknown_purpose() -> None:
    result = resolve_model_runtime_tuning("test-model", purpose="nonexistent")
    assert isinstance(result, ModelRuntimeTuning)
    assert result.temperature == 0.28


def test_resolve_model_empty_name() -> None:
    result = resolve_model_runtime_tuning("", purpose="tutor")
    assert isinstance(result, ModelRuntimeTuning)


# ---------------------------------------------------------------------------
# clear_model_runtime_tuning_cache
# ---------------------------------------------------------------------------


def test_clear_cache() -> None:
    clear_model_runtime_tuning_cache()
    from studyplan.ai.model_infer_tuning import _cache_path, _cache_mtime, _cache_payload

    assert _cache_path is None
    assert _cache_mtime is None
    assert _cache_payload is None
