"""Tests for the llama.cpp-first runtime orchestrator."""

import os
import tempfile

from studyplan.ai.gguf_registry import GgufRegistry, GgufRegistryConfig
from studyplan.ai.llama_runtime import LlamaRuntime, _detect_available_ram
from studyplan.ai.llama_server import LlamaServerConfig, LlamaServerManager
from studyplan.ai.model_selector import ModelSelector, Purpose


_COUNTER = 0


def _write_fake_gguf(path: str, size: int = 4096) -> None:
    global _COUNTER
    _COUNTER += 1
    with open(path, "wb") as f:
        f.write(b"GGUF")
        tag = f"rt_model_{_COUNTER}_{os.path.basename(path)}".encode()
        f.write(tag)
        remaining = size - 4 - len(tag)
        if remaining > 0:
            f.write(b"\x00" * remaining)


class TestDetectRam:
    def test_returns_positive(self):
        ram = _detect_available_ram()
        if os.path.exists("/proc/meminfo"):
            assert ram > 0
        else:
            assert ram >= 0


class TestRuntimeStatus:
    def test_no_models_no_ollama(self):
        cfg = GgufRegistryConfig(
            gpt4all_dir="/nonexistent",
            ollama_manifests_dir="/nonexistent",
            ollama_blobs_dir="/nonexistent",
        )
        rt = LlamaRuntime(
            registry=GgufRegistry(config=cfg),
            selector=ModelSelector(),
            server=LlamaServerManager(config=LlamaServerConfig(binary="/nonexistent")),
            ollama_fallback_enabled=False,
        )
        status = rt.ensure_ready()
        assert not status.healthy
        assert status.backend == "none"
        assert "No GGUF models" in status.error

    def test_models_found_but_server_binary_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "test-1.5b-instruct-q4_k_m.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            rt = LlamaRuntime(
                registry=GgufRegistry(config=cfg),
                selector=ModelSelector(),
                server=LlamaServerManager(
                    config=LlamaServerConfig(binary="/nonexistent/llama-server")
                ),
                ollama_fallback_enabled=False,
            )
            status = rt.ensure_ready()
            assert not status.healthy
            assert status.catalog_size >= 1

    def test_status_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"))
            _write_fake_gguf(os.path.join(tmpdir, "Llama-3.2-3B-Instruct-Q4_0.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            rt = LlamaRuntime(
                registry=GgufRegistry(config=cfg),
                selector=ModelSelector(),
                server=LlamaServerManager(
                    config=LlamaServerConfig(binary="/nonexistent")
                ),
                ollama_fallback_enabled=False,
            )
            report = rt.status()
            assert report["catalog_size"] == 2
            assert len(report["top_models"]) == 2
            assert report["ollama_fallback"] is False


class TestRuntimeFromConfig:
    def test_builds_from_defaults(self):
        rt = LlamaRuntime.from_config()
        assert rt.registry is not None
        assert rt.selector is not None
        assert rt.server is not None

    def test_shutdown_idempotent(self):
        rt = LlamaRuntime.from_config()
        rt.shutdown()
        rt.shutdown()
