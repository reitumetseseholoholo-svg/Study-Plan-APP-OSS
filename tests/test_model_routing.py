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


def test_resolve_local_llm_default_prefers_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    from studyplan_app import StudyPlanGUI

    cfg = {"purposes": {"tutor": {"primary": "routed-a:latest", "failover": []}}}
    path = tmp_path / "route.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(path))
    model_routing.clear_llm_model_routing_cache()
    dummy = types.SimpleNamespace()
    picked = StudyPlanGUI._resolve_local_llm_default_for_purpose(
        dummy,
        "tutor",
        ["other:latest", "routed-a:latest"],
    )
    assert picked == "routed-a:latest"
