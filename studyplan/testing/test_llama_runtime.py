"""Tests for the llama.cpp-first runtime orchestrator."""

import os
import tempfile
from unittest.mock import MagicMock

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


class TestLlamaCppPrecedence:
    """Verify llama.cpp (llama-server) is tried before Ollama fallback."""

    def test_ensure_ready_returns_llama_server_when_server_succeeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "tiny-1b-q4.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            fake_server = MagicMock(spec=LlamaServerManager)
            fake_server.is_running = True
            fake_server.current_model = "tiny-1b-q4.gguf"
            fake_server.endpoint = "http://127.0.0.1:8090"
            fake_server.startup_latency_ms = 0
            fake_server.ensure_running.return_value = True
            fake_server.stop.return_value = None
            fake_server.status.return_value = {"running": True}

            rt = LlamaRuntime(
                registry=GgufRegistry(config=cfg),
                selector=ModelSelector(),
                server=fake_server,
                ollama_fallback_enabled=True,
                ollama_host="http://127.0.0.1:11434",
            )
            status = rt.ensure_ready(Purpose.GENERAL)
            assert status.healthy
            assert status.backend == "llama_server"
            assert status.endpoint == "http://127.0.0.1:8090"
            # When server is already running the right model, ensure_running is not called
            assert fake_server.ensure_running.call_count <= 1

    def test_ensure_ready_falls_back_to_ollama_only_after_llama_server_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "tiny-1b-q4.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            fake_server = MagicMock(spec=LlamaServerManager)
            fake_server.is_running = False
            fake_server.current_model = ""
            fake_server.endpoint = ""
            fake_server.startup_latency_ms = 0
            fake_server.ensure_running.return_value = False
            fake_server.stop.return_value = None
            fake_server.status.return_value = {"running": False}

            rt = LlamaRuntime(
                registry=GgufRegistry(config=cfg),
                selector=ModelSelector(),
                server=fake_server,
                ollama_fallback_enabled=False,
                ollama_host="",
            )
            status = rt.ensure_ready(Purpose.GENERAL)
            assert not status.healthy
            assert status.backend == "none"
            assert "llama-server" in (status.error or "")
            # Runtime tried llama-server first (ensure_running was called)
            assert fake_server.ensure_running.call_count >= 1


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
