"""llama.cpp-first runtime orchestrator.

Ties together the GGUF registry, model selector, and managed llama-server
to provide a single entry point that:

1. Scans local GGUF models (GPT4All + Ollama blobs + extras)
2. Picks the best model for the requested purpose
3. Ensures llama-server is running with that model
4. Returns the endpoint URL for LlamaCppTutorService
5. Falls back to Ollama API if direct serving fails

Memory note: when both managed ``llama-server`` and ``ollama`` are resident, RAM use is
approximately the sum of loaded weights (plus KV). Prefer one primary backend, lower
``num_ctx``, ``OLLAMA_MAX_LOADED_MODELS=1``, and app-side Ollama concurrency limits on
small machines; see ``host_inference_profile`` and Preferences.
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
from .model_infer_tuning import resolve_model_runtime_tuning
from .model_selector import ModelSelector, Purpose

log = logging.getLogger(__name__)


def _resolve_preferred_gguf(
    registry: GgufRegistry,
    selector: ModelSelector,
    catalog: list[GgufModel],
    preferred_name: str,
) -> GgufModel | None:
    """Return a catalog model matching ``preferred_name``, or None.

    Honors the selector RAM budget the same way as automatic ranking.
    """
    pref = (preferred_name or "").strip()
    if not pref:
        return None
    m = registry.find_by_name(pref)
    if m is None:
        pl = pref.lower()
        bn = os.path.basename(pref).lower()
        for cand in catalog:
            if cand.name.lower() == pl or cand.name.lower() == bn:
                m = cand
                break
            if os.path.basename(cand.path).lower() == bn:
                m = cand
                break
    if m is None:
        return None
    if selector.ram_budget_bytes > 0:
        overhead = 500_000_000
        avail = max(0, int(selector.ram_budget_bytes) - overhead)
        if m.size_bytes > avail:
            log.warning(
                "Preferred GGUF %r (~%d MiB) exceeds RAM budget (~%d MiB); ignoring preference",
                m.name,
                int(m.size_bytes // (1024 * 1024)),
                int(avail // (1024 * 1024)),
            )
            return None
    return m


def _launch_kw_for_gguf(model: GgufModel, purpose: str, cfg: type) -> dict[str, int]:
    """Per-model llama-server flags derived from ``model_infer_tuning`` + Config."""
    tun = resolve_model_runtime_tuning(model.name, purpose=purpose, gguf=model)
    base_th = int(getattr(cfg, "LLAMA_CPP_SERVER_THREADS", 4) or 4)
    base_ctx = int(getattr(cfg, "LLAMA_CPP_SERVER_CTX_SIZE", 4096) or 4096)
    ngl_cfg = int(getattr(cfg, "LLAMA_CPP_SERVER_N_GPU_LAYERS", 0) or 0)
    bs_cfg = int(getattr(cfg, "LLAMA_CPP_SERVER_BATCH_SIZE", 512) or 512)
    opt_threads = tun.llama_server_threads
    if opt_threads is None:
        opt_threads = max(1, min(32, int(round(base_th * float(tun.thread_multiplier)))))
    opt_ctx = tun.llama_server_ctx_size
    if opt_ctx is None:
        opt_ctx = min(base_ctx, int(tun.num_ctx))
    opt_ctx = max(512, min(32768, int(opt_ctx)))
    opt_ngl = tun.llama_server_n_gpu_layers
    if opt_ngl is None:
        opt_ngl = ngl_cfg
    opt_batch = tun.llama_server_batch_size
    if opt_batch is None:
        opt_batch = bs_cfg
    return {
        "threads": int(opt_threads),
        "ctx_size": int(opt_ctx),
        "n_gpu_layers": int(opt_ngl),
        "batch_size": int(opt_batch),
    }


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
    def from_config(
        cls,
        config: type[Config] | None = None,
        *,
        ollama_host_override: str | None = None,
    ) -> LlamaRuntime:
        """Build a LlamaRuntime from the centralized Config.

        Pass ollama_host_override (e.g. from app Preferences) to unify the Ollama
        fallback host with the rest of the app; otherwise LLAMA_CPP_OLLAMA_HOST is used.
        """
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

        idle_shutdown = float(getattr(cfg, "LLAMA_CPP_SERVER_IDLE_SHUTDOWN_SECONDS", 0.0) or 0.0)
        idle_poll = float(getattr(cfg, "LLAMA_CPP_SERVER_IDLE_POLL_SECONDS", 10.0) or 10.0)
        extra = getattr(cfg, "LLAMA_CPP_SERVER_EXTRA_ARGS", None)
        extra_list = list(extra) if isinstance(extra, (list, tuple)) else []
        server_cfg = LlamaServerConfig(
            binary=server_bin,
            port=int(getattr(cfg, "LLAMA_CPP_SERVER_PORT", 8090) or 8090),
            threads=int(getattr(cfg, "LLAMA_CPP_SERVER_THREADS", 4) or 4),
            ctx_size=int(getattr(cfg, "LLAMA_CPP_SERVER_CTX_SIZE", 4096) or 4096),
            n_gpu_layers=int(getattr(cfg, "LLAMA_CPP_SERVER_N_GPU_LAYERS", 0) or 0),
            batch_size=int(getattr(cfg, "LLAMA_CPP_SERVER_BATCH_SIZE", 512) or 512),
            startup_timeout_seconds=float(
                getattr(cfg, "LLAMA_CPP_SERVER_STARTUP_TIMEOUT", 60.0) or 60.0
            ),
            idle_shutdown_seconds=max(0.0, idle_shutdown),
            idle_poll_interval_seconds=max(1.0, min(300.0, idle_poll)),
            extra_args=extra_list,
        )

        ram_mb = int(getattr(cfg, "LLAMA_CPP_RAM_BUDGET_MB", 0) or 0)
        ram_bytes = ram_mb * 1024 * 1024 if ram_mb > 0 else _detect_available_ram()

        default_host = str(
            getattr(cfg, "LLAMA_CPP_OLLAMA_HOST", "http://127.0.0.1:11434") or ""
        ).rstrip("/") or "http://127.0.0.1:11434"
        host = (
            str(ollama_host_override or "").strip().rstrip("/")
            or default_host
        )

        return cls(
            registry=GgufRegistry(config=registry_cfg),
            selector=ModelSelector(ram_budget_bytes=ram_bytes),
            server=LlamaServerManager(config=server_cfg),
            ollama_fallback_enabled=bool(
                getattr(cfg, "LLAMA_CPP_OLLAMA_FALLBACK", True)
            ),
            ollama_host=host,
        )

    def ensure_ready(
        self,
        purpose: str = Purpose.GENERAL,
        *,
        preferred_gguf_name: str = "",
    ) -> RuntimeStatus:
        """Make sure an inference backend is ready for the given purpose.

        Tries llama-server first, falls back to Ollama if configured.

        When ``preferred_gguf_name`` is set (registry model name), that GGUF is
        tried before automatic ranking. Unknown names or models over the RAM
        budget are ignored with a log line.
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

        pref_raw = (preferred_gguf_name or "").strip()
        preferred = None
        if pref_raw:
            preferred = _resolve_preferred_gguf(
                self.registry, self.selector, catalog, pref_raw
            )
            if preferred is None:
                log.warning(
                    "Preferred managed GGUF %r not found or not usable; using auto selection",
                    pref_raw,
                )

        ranked_models = [r.model for r in self.selector.rank(catalog, purpose)]
        if not ranked_models:
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

        seen_names: set[str] = set()
        attempts: list[GgufModel] = []
        for m in ([preferred] if preferred is not None else []) + ranked_models:
            if m.name in seen_names:
                continue
            seen_names.add(m.name)
            attempts.append(m)
            if len(attempts) >= 6:
                break

        first = attempts[0]
        if self.server.is_running and self.server.current_model == first.name:
            return RuntimeStatus(
                backend="llama_server",
                model_name=first.name,
                model_path=first.path,
                endpoint=self.server.endpoint,
                healthy=True,
                startup_latency_ms=self.server.startup_latency_ms,
                catalog_size=len(catalog),
            )

        last_tried = first
        for model in attempts:
            last_tried = model
            ok = self.server.ensure_running(
                model.path,
                model.name,
                **_launch_kw_for_gguf(model, purpose, Config),
            )
            if ok:
                self._last_purpose = purpose
                return RuntimeStatus(
                    backend="llama_server",
                    model_name=model.name,
                    model_path=model.path,
                    endpoint=self.server.endpoint,
                    healthy=True,
                    startup_latency_ms=self.server.startup_latency_ms,
                    catalog_size=len(catalog),
                )
            log.warning(
                "llama-server failed to start with %s, trying next candidates",
                model.name,
            )

        if self.ollama_fallback_enabled:
            return self._try_ollama_fallback(purpose)

        return RuntimeStatus(
            backend="none",
            model_name=last_tried.name,
            model_path=last_tried.path,
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

    def mark_server_used(self) -> None:
        """Refresh idle timer after HTTP traffic to the managed llama-server."""
        self.server.mark_used()

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
        host = (self.ollama_host or "").strip().rstrip("/") or "http://127.0.0.1:11434"

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

        model_name = _pick_ollama_model_safe_for_ram(models, purpose)
        log.info(
            "Using Ollama backend at %s (model=%s, RAM-safe selection)",
            host,
            model_name or "(auto)",
        )
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

def _get_ollama_ram_budget_bytes() -> int:
    """RAM budget for Ollama model choice (bytes). 0 = no filter."""
    try:
        env_mb = os.environ.get("STUDYPLAN_OLLAMA_RAM_BUDGET_MB", "").strip()
        if env_mb:
            mb = int(env_mb)
            if mb > 0:
                return mb * 1024 * 1024
    except (ValueError, TypeError):
        pass
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    available_kb = int(parts[1])
                    return int(available_kb * 1024 * 0.75)
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _estimate_ollama_model_ram_bytes(model_name: str) -> int:
    """Estimate RAM (bytes) to load this Ollama model. 0 = unknown."""
    import re
    raw = str(model_name or "").strip().lower()
    if not raw:
        return 0
    m = re.search(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(?:b|bn)(?![a-z0-9])", raw)
    if not m:
        return 0
    try:
        size_b = float(m.group(1))
    except (ValueError, TypeError):
        return 0
    if size_b <= 0:
        return 0
    if "q2" in raw or "q2_k" in raw:
        bpp = 0.35
    elif "q3" in raw or "q3_k" in raw:
        bpp = 0.45
    elif "q4" in raw or "q4_0" in raw or "q4_k" in raw:
        bpp = 0.58
    elif "q5" in raw or "q5_k" in raw:
        bpp = 0.75
    elif "q6" in raw or "q8" in raw or "f16" in raw or "fp16" in raw:
        bpp = 1.0
    else:
        bpp = 0.58
    model_bytes = int(size_b * 1e9 * bpp)
    return model_bytes + 550_000_000


def _pick_ollama_model_safe_for_ram(models: list[str], purpose: str) -> str:
    """Pick an Ollama model that fits in RAM and aligns with purpose when possible."""
    if not models:
        return ""
    purpose_tier = _purpose_tier_from_name(purpose)
    budget = _get_ollama_ram_budget_bytes()
    if budget <= 0:
        return _pick_ollama_model_by_purpose(models, purpose_tier)
    fitting = []
    for name in models:
        need = _estimate_ollama_model_ram_bytes(name)
        if need <= 0 or need <= budget:
            fitting.append(name)
    if fitting:
        return _pick_ollama_model_by_purpose(fitting, purpose_tier)
    # None fit: pick smallest estimated to reduce OOM risk (treat unknown as large)
    def _ram_key(name: str) -> tuple[int, int]:
        est = _estimate_ollama_model_ram_bytes(name)
        return (1 if est == 0 else 0, est or 0)
    all_sorted = sorted(models, key=_ram_key)
    return all_sorted[0]


def _purpose_tier_from_name(purpose: str) -> str:
    normalized = str(purpose or "").strip().lower()
    if normalized in {str(Purpose.HINT), "fast"}:
        return "fast"
    if normalized in {str(Purpose.DEEP_REASON), "quality"}:
        return "quality"
    return "balanced"


def _pick_ollama_model_by_purpose(models: list[str], purpose_tier: str) -> str:
    if not models:
        return ""
    rows: list[tuple[str, int]] = []
    for name in models:
        rows.append((name, _estimate_ollama_model_ram_bytes(name)))
    known = [(name, est) for name, est in rows if est > 0]
    if purpose_tier == "fast":
        if known:
            known.sort(key=lambda row: row[1])
            return known[0][0]
        return models[0]
    if purpose_tier == "quality":
        if known:
            known.sort(key=lambda row: row[1], reverse=True)
            return known[0][0]
        return models[0]

    # balanced: aim near median known size to avoid extremes (too tiny/too heavy)
    if known:
        sizes = sorted(est for _, est in known)
        median = sizes[len(sizes) // 2]
        best_name = min(
            known,
            key=lambda row: (abs(row[1] - median), row[0]),
        )[0]
        return best_name
    return models[0]


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
