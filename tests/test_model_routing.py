"""Purpose-based LLM routing config (Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studyplan.ai import model_routing


@pytest.fixture(autouse=True)
def _clear_routing_cache():
    model_routing.clear_llm_model_routing_cache()
    yield
    model_routing.clear_llm_model_routing_cache()


# ---------------------------------------------------------------------------
# _purpose_keys
# ---------------------------------------------------------------------------


def test_purpose_keys_general() -> None:
    assert model_routing._purpose_keys("") == ["general"]
    assert model_routing._purpose_keys(None) == ["general"]


def test_purpose_keys_direct_match() -> None:
    keys = model_routing._purpose_keys("tutor")
    assert "tutor" in keys


def test_purpose_keys_alias_includes_canonical() -> None:
    keys = model_routing._purpose_keys("gap_gen")
    assert "gap_generation" in keys
    assert "gap_gen" in keys


def test_purpose_keys_section_c_aliases() -> None:
    keys = model_routing._purpose_keys("section_c_eval")
    assert "section_c_evaluation" in keys
    assert "section_c_eval" in keys


# ---------------------------------------------------------------------------
# _config_path_candidates
# ---------------------------------------------------------------------------


def test_config_path_candidates_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = tmp_path / "custom_route.json"
    dummy.touch()
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(dummy))
    candidates = model_routing._config_path_candidates()
    paths = [str(p) for p in candidates]
    assert str(dummy) in paths


def test_config_path_candidates_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When no env var set, falls back to CONFIG_HOME/llm_model_routing.json."""
    monkeypatch.delenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", raising=False)
    candidates = model_routing._config_path_candidates()
    assert any("llm_model_routing.json" in str(p) for p in candidates)


# ---------------------------------------------------------------------------
# load_llm_model_routing_table
# ---------------------------------------------------------------------------


def test_load_llm_empty_on_missing_file() -> None:
    assert model_routing.load_llm_model_routing_table() == {}


def test_load_llm_from_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "purposes": {
            "tutor": {"primary": "big-teach:latest", "failover": ["small-fast:latest"]},
        },
    }
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    table = model_routing.load_llm_model_routing_table()
    assert "tutor" in table
    assert table["tutor"]["primary"] == "big-teach:latest"
    assert table["tutor"]["failover"] == ["small-fast:latest"]


def test_load_llm_failover_string_single(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"tutor": {"primary": "a:latest", "failover": "b:latest"}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    table = model_routing.load_llm_model_routing_table()
    assert table["tutor"]["failover"] == ["b:latest"]


def test_load_llm_failover_string_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"tutor": {"primary": "a:latest", "failover": "b:latest,c:latest"}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    table = model_routing.load_llm_model_routing_table()
    assert table["tutor"]["failover"] == ["b:latest", "c:latest"]


def test_load_llm_deduplicates_failover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"tutor": {"primary": "a:latest", "failover": ["b:latest", "b:latest"]}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    table = model_routing.load_llm_model_routing_table()
    assert table["tutor"]["failover"] == ["b:latest"]


def test_load_llm_ignores_empty_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"": {"primary": "x:latest"}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    table = model_routing.load_llm_model_routing_table()
    assert len(table) == 0


def test_load_llm_failover_chain_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Alias key (gap_gen) is normalized to canonical (gap_generation)."""
    cfg = {"purposes": {"gap_gen": {"primary": "fast-gen:latest", "failover": []}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    table = model_routing.load_llm_model_routing_table()
    assert "gap_gen" in table
    assert table["gap_gen"]["primary"] == "fast-gen:latest"


# ---------------------------------------------------------------------------
# routed_primary_for_purpose
# ---------------------------------------------------------------------------


def test_routed_primary_and_failover_from_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "version": 1,
        "purposes": {
            "tutor": {"primary": "big-teach:latest", "failover": ["small-fast:latest", "ghost:missing"]},
        },
    }
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    cands = ["small-fast:latest", "big-teach:latest", "other:latest"]
    assert model_routing.routed_primary_for_purpose("tutor", cands) == "big-teach:latest"
    assert model_routing.routed_failover_chain_for_purpose("tutor", cands) == ["small-fast:latest"]


def test_routed_primary_missing_from_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"tutor": {"primary": "missing:latest", "failover": []}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    assert model_routing.routed_primary_for_purpose("tutor", ["other:latest"]) == ""


def test_routed_primary_empty_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"tutor": {"primary": "a:latest", "failover": []}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    assert model_routing.routed_primary_for_purpose("tutor", []) == ""


def test_routed_primary_uses_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"gap_generation": {"primary": "gen:latest", "failover": []}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    result = model_routing.routed_primary_for_purpose("gap_gen", ["gen:latest"])
    assert result == "gen:latest"


# ---------------------------------------------------------------------------
# routed_failover_chain_for_purpose
# ---------------------------------------------------------------------------


def test_failover_chain_empty_table() -> None:
    assert model_routing.routed_failover_chain_for_purpose("tutor", ["a"]) == []


def test_failover_chain_empty_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"tutor": {"primary": "a:latest", "failover": ["b:latest"]}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    assert model_routing.routed_failover_chain_for_purpose("tutor", []) == []


def test_failover_chain_skips_non_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"purposes": {"tutor": {"primary": "a:latest", "failover": ["x:latest", "y:latest"]}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    chain = model_routing.routed_failover_chain_for_purpose("tutor", ["x:latest"])
    assert chain == ["x:latest"]


# ---------------------------------------------------------------------------
# clear_llm_model_routing_cache
# ---------------------------------------------------------------------------


def test_clear_cache() -> None:
    model_routing.clear_llm_model_routing_cache()
    assert model_routing._cache_path is None
    assert model_routing._cache_mtime is None
    assert model_routing._cache_payload is None


def test_resolve_local_llm_default_prefers_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from studyplan_app_runtime_helpers import resolve_local_llm_default_for_purpose

    cfg = {"purposes": {"tutor": {"primary": "routed-a:latest", "failover": []}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    picked = resolve_local_llm_default_for_purpose(
        "tutor",
        ["other:latest", "routed-a:latest"],
    )
    assert picked == "routed-a:latest"
