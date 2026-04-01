from __future__ import annotations

import json

import pytest

from studyplan.ai import model_infer_tuning as mit


def test_resolve_tuning_smaller_model_higher_temperature() -> None:
    small = mit.resolve_model_runtime_tuning("phi3:mini", purpose="tutor")
    huge = mit.resolve_model_runtime_tuning("llama3.3:70b-q4_k_m", purpose="tutor")
    assert small.temperature > huge.temperature
    assert small.thread_multiplier >= huge.thread_multiplier


def test_deep_reason_lowers_temperature() -> None:
    base = mit.resolve_model_runtime_tuning("llama3.1:8b", purpose="tutor")
    deep = mit.resolve_model_runtime_tuning("llama3.1:8b", purpose="deep_reason")
    assert deep.temperature <= base.temperature
    assert deep.num_ctx >= base.num_ctx


def test_json_task_lowers_temperature() -> None:
    tutor = mit.resolve_model_runtime_tuning("mistral:7b", purpose="tutor")
    coach = mit.resolve_model_runtime_tuning("mistral:7b", purpose="coach")
    assert coach.temperature < tutor.temperature


def test_json_exact_overlay(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mit.clear_model_runtime_tuning_cache()
    cfg = {
        "exact": {"custom:tag": {"temperature": 0.11, "num_ctx": 2048, "thread_multiplier": 0.5}},
    }
    p = tmp_path / "runtime.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", str(p))
    mit.clear_model_runtime_tuning_cache()
    t = mit.resolve_model_runtime_tuning("custom:tag", purpose="tutor")
    assert t.temperature == pytest.approx(0.11)
    assert t.num_ctx == 2048
    assert t.thread_multiplier == pytest.approx(0.5)
    mit.clear_model_runtime_tuning_cache()


def test_qwen35_4b_tutor_profile_applies_model_specific_defaults() -> None:
    t = mit.resolve_model_runtime_tuning("qwen3.5:4b-instruct-q4_k_m", purpose="tutor")
    assert t.temperature == pytest.approx(0.22)
    assert t.top_p == pytest.approx(0.90)
    assert t.num_ctx == 4096
    assert t.thread_multiplier == pytest.approx(0.95)
    assert t.max_output_tokens == 1280


def test_qwen35_4b_coach_profile_prefers_compact_json_outputs() -> None:
    t = mit.resolve_model_runtime_tuning("Qwen-3.5 4B", purpose="coach")
    assert t.temperature == pytest.approx(0.14)
    assert t.top_p == pytest.approx(0.88)
    assert t.num_ctx == 3072
    assert t.max_output_tokens == 960
