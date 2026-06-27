"""Tests for the llama.cpp-first runtime orchestrator."""

import os
import tempfile
from unittest.mock import MagicMock, patch

from studyplan.ai.gguf_registry import GgufRegistry, GgufRegistryConfig
from studyplan.ai.llama_runtime import (
    LlamaRuntime,
    RuntimeStatus,
    _detect_available_ram,
    _pick_ollama_model_safe_for_ram,
)
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
                server=LlamaServerManager(config=LlamaServerConfig(binary="/nonexistent/llama-server")),
                ollama_fallback_enabled=False,
            )
            status = rt.ensure_ready()
            assert not status.healthy
            assert status.catalog_size >= 1
            assert "binary" in str(status.error or "").lower()

    def test_binary_missing_uses_ollama_fallback_without_server_attempts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "test-1.5b-instruct-q4_k_m.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            fake_server = MagicMock(spec=LlamaServerManager)
            fake_server.binary_available = False
            rt = LlamaRuntime(
                registry=GgufRegistry(config=cfg),
                selector=ModelSelector(),
                server=fake_server,
                ollama_fallback_enabled=True,
                ollama_host="http://127.0.0.1:11434",
            )
            rt._try_ollama_fallback = MagicMock(
                return_value=RuntimeStatus(
                    backend="ollama",
                    model_name="fallback-model",
                    model_path="",
                    endpoint="http://127.0.0.1:11434/api/generate",
                    healthy=True,
                    startup_latency_ms=0,
                    catalog_size=1,
                    error="",
                )
            )

            status = rt.ensure_ready()

            assert status.healthy
            assert status.backend == "ollama"
            assert fake_server.ensure_running.call_count == 0
            assert rt._try_ollama_fallback.call_count == 1

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
                server=LlamaServerManager(config=LlamaServerConfig(binary="/nonexistent")),
                ollama_fallback_enabled=False,
            )
            report = rt.status()
            assert report["catalog_size"] == 2
            assert len(report["top_models"]) == 2
            assert report["ollama_fallback"] is False


class TestLlamaCppPrecedence:
    """Verify Ollama is preferred over managed llama-server."""

    def test_ensure_ready_returns_ollama_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "tiny-1b-q4.gguf"))
            cfg = GgufRegistryConfig(
                gpt4all_dir=tmpdir,
                ollama_manifests_dir="/nonexistent",
                ollama_blobs_dir="/nonexistent",
            )
            fake_server = MagicMock(spec=LlamaServerManager)

            rt = LlamaRuntime(
                registry=GgufRegistry(config=cfg),
                selector=ModelSelector(),
                server=fake_server,
                ollama_fallback_enabled=True,
                ollama_host="http://127.0.0.1:11434",
            )
            status = rt.ensure_ready(Purpose.GENERAL)
            assert status.healthy
            # Ollama is preferred — should be used before managed server
            assert status.backend == "ollama", f"Expected ollama, got {status.backend}"
            # Managed server was never touched
            fake_server.ensure_running.assert_not_called()

    def test_ensure_ready_uses_llama_server_when_ollama_disabled(self):
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
                ollama_fallback_enabled=False,
                ollama_host="",
            )
            status = rt.ensure_ready(Purpose.GENERAL)
            assert status.healthy
            assert status.backend == "llama_server"
            assert status.endpoint == "http://127.0.0.1:8090"
            assert fake_server.ensure_running.call_count <= 1

    def test_ensure_ready_managed_server_only_when_ollama_unavailable(self):
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

    def test_preferred_gguf_attempted_before_auto_rank(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_fake_gguf(os.path.join(tmpdir, "aaa-1b-q4.gguf"))
            _write_fake_gguf(os.path.join(tmpdir, "zzz-7b-q4.gguf"))
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
            fake_server.ensure_running.return_value = True
            fake_server.stop.return_value = None
            fake_server.status.return_value = {"running": False}

            rt = LlamaRuntime(
                registry=GgufRegistry(config=cfg),
                selector=ModelSelector(),
                server=fake_server,
                ollama_fallback_enabled=False,
                ollama_host="",
            )
            status = rt.ensure_ready(Purpose.GENERAL, preferred_gguf_name="zzz-7b-q4.gguf")
            assert status.healthy
            assert status.model_name == "zzz-7b-q4"
            first = fake_server.ensure_running.call_args_list[0]
            assert first[0][1] == "zzz-7b-q4"


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


class TestOllamaPurposeSelection:
    def test_no_budget_picks_by_purpose_tier(self):
        models = [
            "qwen2-1-5b-instruct-q4-0:latest",
            "llama-3-2-3b-instruct-q4-0:latest",
            "qwen2-5-7b-instruct-q4-0:latest",
        ]
        with patch(
            "studyplan.ai.llama_runtime._get_ollama_ram_budget_bytes",
            return_value=0,
        ):
            picked_hint = _pick_ollama_model_safe_for_ram(models, Purpose.HINT)
            picked_deep = _pick_ollama_model_safe_for_ram(models, Purpose.DEEP_REASON)
            picked_tutor = _pick_ollama_model_safe_for_ram(models, Purpose.TUTOR)
            # HINT should pick the smallest model (1.5B)
            assert "1-5b" in picked_hint or "1.5b" in picked_hint
            # DEEP_REASON should pick the largest model (7B)
            assert "7b" in picked_deep
            # TUTOR (balanced) should avoid extremes
            assert "3b" in picked_tutor

    def test_budget_filtered_picks_by_purpose_tier(self):
        models = [
            "qwen2-1-5b-instruct-q4-0:latest",
            "llama-3-2-3b-instruct-q4-0:latest",
            "qwen2-5-7b-instruct-q4-0:latest",
        ]
        with patch(
            "studyplan.ai.llama_runtime._get_ollama_ram_budget_bytes",
            return_value=3_500_000_000,  # ~3.5 GiB: fits 1.5B and 3B but not 7B
        ):
            picked_hint = _pick_ollama_model_safe_for_ram(models, Purpose.HINT)
            picked_deep = _pick_ollama_model_safe_for_ram(models, Purpose.DEEP_REASON)
            picked_tutor = _pick_ollama_model_safe_for_ram(models, Purpose.TUTOR)
            # All picks should exclude the 7B model (over budget)
            for picked in (picked_hint, picked_deep, picked_tutor):
                assert picked, "a model should be picked"
                assert "7b" not in picked, f"{picked} should have been filtered by RAM budget"
            # HINT picks smallest fitting (1.5B)
            assert "1-5b" in picked_hint or "1.5b" in picked_hint
            # DEEP_REASON without 7B picks the next best fitting (3B)
            assert "3b" in picked_deep
