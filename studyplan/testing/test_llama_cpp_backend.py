"""Tests for llama.cpp secondary backend and Ollama model sync."""

from __future__ import annotations

import json
import os
import types

from studyplan.inference import llama_cpp_backend as backend


def test_discover_ollama_gguf_models_from_modelfile_digest(monkeypatch):
    digest = "a" * 64
    expected_path = os.path.expanduser(f"~/.ollama/models/blobs/sha256-{digest}")

    monkeypatch.setattr(backend, "shutil_which", lambda _cmd: "/usr/bin/ollama")

    def _fake_run_capture(cmd, timeout_s=20):
        joined = " ".join(cmd)
        if joined.endswith("list"):
            return ("NAME ID SIZE MODIFIED\nmodel-a:latest 123 2GB now\n", "", 0)
        if "show model-a:latest --modelfile" in joined:
            return (f"FROM sha256:{digest}\n", "", 0)
        return ("", "bad call", 1)

    monkeypatch.setattr(backend, "_run_capture", _fake_run_capture)
    monkeypatch.setattr(backend.os.path, "isfile", lambda p: str(p) == expected_path)

    models = backend.discover_ollama_gguf_models(max_models=4)
    assert models == {"model-a:latest": expected_path}


def test_sync_registry_merges_discovered_models(tmp_path, monkeypatch):
    reg = tmp_path / "llama_cpp_models.json"
    reg.write_text(
        json.dumps(
            {
                "updated_at": "old",
                "models": {
                    "existing:model": "/tmp/existing.gguf",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        backend,
        "discover_ollama_gguf_models",
        lambda **_kwargs: {"new:model": "/tmp/new.gguf"},
    )
    summary = backend.sync_ollama_models_to_llamacpp_registry(registry_path=str(reg), max_models=2)
    assert int(summary["existing"]) == 1
    assert int(summary["discovered"]) == 1
    assert int(summary["total"]) == 2
    payload = json.loads(reg.read_text(encoding="utf-8"))
    assert payload["models"]["existing:model"] == "/tmp/existing.gguf"
    assert payload["models"]["new:model"] == "/tmp/new.gguf"


def test_llamacpp_qgen_service_fallbacks_when_chat_fails():
    svc = backend.LlamaCppHTTPQGenService()
    svc._chat_completion = types.MethodType(lambda _self, _prompt: ("", "network_down"), svc)
    rows = svc.generate_questions(topic="NPV", source_text="discounting", count=2)
    assert len(rows) == 2
    assert all("NPV" in row for row in rows)


def test_llamacpp_qgen_extracts_json_list():
    text = json.dumps(["Q1", "Q2", "Q3"])
    rows = backend.LlamaCppHTTPQGenService._extract_questions(text, 2)
    assert rows == ["Q1", "Q2"]

