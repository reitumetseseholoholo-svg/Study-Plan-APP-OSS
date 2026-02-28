"""llama.cpp-first runtime orchestrator.

Ties together the GGUF registry, model selector, and managed llama-server
to provide a single entry point that:

1. Scans local GGUF models (GPT4All + Ollama blobs + extras)
2. Picks the best model for the requested purpose
3. Ensures llama-server is running with that model
4. Returns the endpoint URL for LlamaCppTutorService
5. Falls back to Ollama API if direct serving fails
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from .gguf_registry import GgufModel, GgufRegistry, GgufRegistryConfig
from .llama_server import LlamaServerConfig, LlamaServerManager
from .model_selector import ModelSelector, Purpose

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeStatus:
    backend: str  # "llama_server" | "ollama" | "none"
    model_name: str
    model_path: str
    endpoint: str
    healthy: bool
    startup_latency_ms: int
    catalog_size: int
    error: str = ""


@dataclass
class LlamaRuntime:
    """Top-level orchestrator for llama.cpp-first inference."""

    registry: GgufRegistry = field(default_factory=lambda: GgufRegistry())
    selector: ModelSelector = field(default_factory=lambda: ModelSelector())
    server: LlamaServerManager = field(default_factory=lambda: LlamaServerManager())
    ollama_fallback_enabled: bool = True
    ollama_host: str = "http://127.0.0.1:11434"
    _last_purpose: str = field(default="", init=False, repr=False)

    @classmethod
    def from_config(cls, config: type[Config] | None = None) -> LlamaRuntime:
        """Build a LlamaRuntime from the centralized Config."""
        cfg = config or Config

        extra_dirs: list[str] = []
        extra = getattr(cfg, "LLAMA_CPP_EXTRA_GGUF_DIR", "")
        if extra:
            extra_dirs.append(str(extra))

        registry_cfg = GgufRegistryConfig(
            gpt4all_dir=str(getattr(cfg, "LLAMA_CPP_GPT4ALL_MODELS_DIR", "") or ""),
            ollama_manifests_dir=str(getattr(cfg, "LLAMA_CPP_OLLAMA_MANIFESTS_DIR", "") or ""),
            ollama_blobs_dir=str(getattr(cfg, "LLAMA_CPP_OLLAMA_BLOBS_DIR", "") or ""),
            extra_dirs=extra_dirs,
            ttl_seconds=float(getattr(cfg, "LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS", 120.0) or 120.0),
        )

        server_bin = str(getattr(cfg, "LLAMA_CPP_SERVER_BIN", "") or "").strip()
        if not server_bin:
            server_bin = shutil.which("llama-server") or "llama-server"

        server_cfg = LlamaServerConfig(
            binary=server_bin,
            port=int(getattr(cfg, "LLAMA_CPP_SERVER_PORT", 8090) or 8090),
            threads=int(getattr(cfg, "LLAMA_CPP_SERVER_THREADS", 4) or 4),
            ctx_size=int(getattr(cfg, "LLAMA_CPP_SERVER_CTX_SIZE", 4096) or 4096),
            startup_timeout_seconds=float(
                getattr(cfg, "LLAMA_CPP_SERVER_STARTUP_TIMEOUT", 60.0) or 60.0
            ),
        )

        ram_mb = int(getattr(cfg, "LLAMA_CPP_RAM_BUDGET_MB", 0) or 0)
        ram_bytes = ram_mb * 1024 * 1024 if ram_mb > 0 else _detect_available_ram()

        return cls(
            registry=GgufRegistry(config=registry_cfg),
            selector=ModelSelector(ram_budget_bytes=ram_bytes),
            server=LlamaServerManager(config=server_cfg),
            ollama_fallback_enabled=bool(
                getattr(cfg, "LLAMA_CPP_OLLAMA_FALLBACK", True)
            ),
            ollama_host=str(
                getattr(cfg, "LLAMA_CPP_OLLAMA_HOST", "http://127.0.0.1:11434") or ""
            ).rstrip("/"),
        )

    def ensure_ready(self, purpose: str = Purpose.GENERAL) -> RuntimeStatus:
        """Make sure an inference backend is ready for the given purpose.

        Tries llama-server first, falls back to Ollama if configured.
        """
        catalog = self.registry.catalog()
        if not catalog:
            log.warning("No GGUF models found in any scanned directory")
            if self.ollama_fallback_enabled:
                return self._try_ollama_fallback(purpose)
            return RuntimeStatus(
                backend="none",
                model_name="",
                model_path="",
                endpoint="",
                healthy=False,
                startup_latency_ms=0,
                catalog_size=0,
                error="No GGUF models found",
            )

        best = self.selector.pick_best(catalog, purpose)
        if not best:
            log.warning("Model selector returned no candidate for purpose=%s", purpose)
            if self.ollama_fallback_enabled:
                return self._try_ollama_fallback(purpose)
            return RuntimeStatus(
                backend="none",
                model_name="",
                model_path="",
                endpoint="",
                healthy=False,
                startup_latency_ms=0,
                catalog_size=len(catalog),
                error="No suitable model for purpose",
            )

        if self.server.is_running and self.server.current_model == best.name:
            return RuntimeStatus(
                backend="llama_server",
                model_name=best.name,
                model_path=best.path,
                endpoint=self.server.endpoint,
                healthy=True,
                startup_latency_ms=self.server.startup_latency_ms,
                catalog_size=len(catalog),
            )

        ok = self.server.ensure_running(best.path, best.name)
        if ok:
            self._last_purpose = purpose
            return RuntimeStatus(
                backend="llama_server",
                model_name=best.name,
                model_path=best.path,
                endpoint=self.server.endpoint,
                healthy=True,
                startup_latency_ms=self.server.startup_latency_ms,
                catalog_size=len(catalog),
            )

        log.warning(
            "llama-server failed to start with %s, trying next candidates",
            best.name,
        )
        ranked = self.selector.rank(catalog, purpose)
        for ranking in ranked[1:4]:
            ok = self.server.ensure_running(ranking.model.path, ranking.model.name)
            if ok:
                self._last_purpose = purpose
                return RuntimeStatus(
                    backend="llama_server",
                    model_name=ranking.model.name,
                    model_path=ranking.model.path,
                    endpoint=self.server.endpoint,
                    healthy=True,
                    startup_latency_ms=self.server.startup_latency_ms,
                    catalog_size=len(catalog),
                )

        if self.ollama_fallback_enabled:
            return self._try_ollama_fallback(purpose)

        return RuntimeStatus(
            backend="none",
            model_name=best.name,
            model_path=best.path,
            endpoint="",
            healthy=False,
            startup_latency_ms=0,
            catalog_size=len(catalog),
            error="llama-server failed to start with any candidate model",
        )

    def get_endpoint(self, purpose: str = Purpose.GENERAL) -> str:
        """Return the active endpoint URL, starting server if needed."""
        status = self.ensure_ready(purpose)
        return status.endpoint if status.healthy else ""

    def get_active_model(self) -> str:
        if self.server.is_running:
            return self.server.current_model
        return ""

    def status(self) -> dict[str, Any]:
        catalog = self.registry.catalog()
        rankings = self.selector.rank(catalog) if catalog else []
        return {
            "server": self.server.status(),
            "catalog_size": len(catalog),
            "top_models": [
                {
                    "name": r.model.name,
                    "score": r.score,
                    "tier": r.tier,
                    "size_mb": round(r.model.size_bytes / (1024 * 1024)),
                    "source": r.model.source,
                    "arch": r.model.architecture,
                    "params_b": r.model.param_billions,
                    "quant": r.model.quant_tag,
                }
                for r in rankings[:8]
            ],
            "ollama_fallback": self.ollama_fallback_enabled,
        }

    def shutdown(self) -> None:
        self.server.stop()

    # ------------------------------------------------------------------
    # Ollama fallback
    # ------------------------------------------------------------------

    def _try_ollama_fallback(self, purpose: str) -> RuntimeStatus:
        host = self.ollama_host.rstrip("/") if self.ollama_host else ""
        if not host:
            return RuntimeStatus(
                backend="none",
                model_name="",
                model_path="",
                endpoint="",
                healthy=False,
                startup_latency_ms=0,
                catalog_size=0,
                error="Ollama fallback disabled (no host)",
            )

        if not _ollama_is_reachable(host):
            return RuntimeStatus(
                backend="none",
                model_name="",
                model_path="",
                endpoint="",
                healthy=False,
                startup_latency_ms=0,
                catalog_size=0,
                error=f"Ollama not reachable at {host}",
            )

        models = _ollama_list_models(host)
        if not models:
            return RuntimeStatus(
                backend="ollama",
                model_name="",
                model_path="",
                endpoint=f"{host}/api/generate",
                healthy=True,
                startup_latency_ms=0,
                catalog_size=0,
                error="Ollama reachable but no models found",
            )

        model_name = models[0]
        log.info("Falling back to Ollama with model=%s", model_name)
        return RuntimeStatus(
            backend="ollama",
            model_name=model_name,
            model_path="",
            endpoint=f"{host}/api/generate",
            healthy=True,
            startup_latency_ms=0,
            catalog_size=len(models),
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _detect_available_ram() -> int:
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _ollama_is_reachable(host: str) -> bool:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3.0):
            return True
    except Exception:
        return False


def _ollama_list_models(host: str) -> list[str]:
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    models_list = data.get("models")
    if not isinstance(models_list, list):
        return []
    out: list[str] = []
    for item in models_list:
        if isinstance(item, dict):
            name = str(item.get("name", "") or "").strip()
            if name:
                out.append(name)
    return out
