"""Host hardware hints for local LLM defaults (llama-server, Ollama client, paths).

Reads /proc/meminfo and /proc/cpuinfo on Linux so laptops/APUs get conservative
threads, context, and batch sizes without manual env tuning. Explicit env vars
always override (handled in ``studyplan.config``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemSnapshot:
    mem_total_kb: int = 0
    mem_available_kb: int = 0
    swap_total_kb: int = 0
    swap_free_kb: int = 0

    @property
    def mem_total_mb(self) -> float:
        return max(0.0, float(self.mem_total_kb) / 1024.0)

    @property
    def mem_available_mb(self) -> float:
        return max(0.0, float(self.mem_available_kb) / 1024.0)

    @property
    def swap_used_kb(self) -> int:
        return max(0, int(self.swap_total_kb) - int(self.swap_free_kb))


def mem_snapshot() -> MemSnapshot:
    data: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, rest = line.split(":", 1)
                parts = rest.split()
                if not parts:
                    continue
                try:
                    data[key.strip()] = int(parts[0])
                except ValueError:
                    continue
    except OSError:
        return MemSnapshot()
    return MemSnapshot(
        mem_total_kb=int(data.get("MemTotal", 0) or 0),
        mem_available_kb=int(data.get("MemAvailable", 0) or 0),
        swap_total_kb=int(data.get("SwapTotal", 0) or 0),
        swap_free_kb=int(data.get("SwapFree", 0) or 0),
    )


def _read_linux_cpu_model_name() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                if str(key).strip().lower() == "model name":
                    model = str(value or "").strip()
                    if model:
                        return model
    except OSError:
        pass
    return ""


def _estimate_physical_cores(logical: int, model_name: str) -> int:
    logical = max(1, int(logical or 1))
    name = str(model_name or "").strip().lower()
    if logical <= 2:
        return logical
    if "ryzen" in name and logical % 2 == 0:
        return max(1, logical // 2)
    if logical >= 8 and logical % 2 == 0:
        return max(1, logical // 2)
    return logical


def _memory_pressure(mem: MemSnapshot) -> str:
    """Rough tier for tuning defaults."""
    total = mem.mem_total_mb
    avail = mem.mem_available_mb
    swap_used_mb = mem.swap_used_kb / 1024.0
    if total <= 0:
        return "unknown"
    # iGPU carve-out + small SODIMMs: total may read as ~5.5–6 GiB on an "8 GB" laptop.
    if total < 7500 or avail < 1200 or swap_used_mb > 400:
        return "high"
    if total < 14000 or avail < 2400 or swap_used_mb > 128:
        return "moderate"
    return "low"


def default_llama_server_thread_count() -> int:
    logical = max(1, int(os.cpu_count() or 1))
    model_name = _read_linux_cpu_model_name()
    physical = _estimate_physical_cores(logical, model_name)
    lower = str(model_name or "").lower()
    # Match studyplan_app heuristics (3700U, etc.).
    is_ryzen_mobile = "ryzen" in lower and ("u" in lower or "mobile" in lower)
    mem = mem_snapshot()
    pressure = _memory_pressure(mem)
    if is_ryzen_mobile:
        target = max(4, min(logical, physical + 2))
    elif logical >= 8:
        target = max(4, min(logical, physical + 1))
    else:
        target = max(2, min(logical, physical))
    if pressure == "high":
        target = min(target, max(3, physical))
    elif pressure == "moderate":
        target = min(target, max(4, physical + 1))
    return max(1, min(16, int(target)))


def default_llama_server_ctx_size() -> int:
    mem = mem_snapshot()
    pressure = _memory_pressure(mem)
    if pressure == "high":
        return 2048
    if pressure == "moderate":
        return 3072
    return 4096


def default_llama_server_batch_size() -> int:
    pressure = _memory_pressure(mem_snapshot())
    if pressure == "high":
        return 256
    if pressure == "moderate":
        return 384
    return 512


def default_ollama_client_num_ctx() -> int:
    """Default ``num_ctx`` for Ollama HTTP requests from the app (not the daemon)."""
    return int(default_llama_server_ctx_size())


def default_ollama_app_max_concurrent_requests() -> int:
    """Parallel in-app Ollama HTTP calls (semaphore). Conservative under RAM pressure."""
    p = _memory_pressure(mem_snapshot())
    if p in {"unknown", "high"}:
        return 1
    if p == "moderate":
        return 2
    return 3


def default_llama_server_idle_shutdown_seconds() -> float:
    """Stop managed ``llama-server`` sooner when RAM is tight (frees weights + KV)."""
    p = _memory_pressure(mem_snapshot())
    if p == "high":
        return 90.0
    if p == "moderate":
        return 180.0
    if p == "unknown":
        return 240.0
    return 300.0


def default_performance_cache_max_size() -> int:
    """Fewer in-process perf cache entries under memory pressure."""
    p = _memory_pressure(mem_snapshot())
    if p == "high":
        return 400
    if p == "moderate":
        return 700
    if p == "unknown":
        return 500
    return 1000


def default_performance_cache_rag_doc_store_mode() -> str:
    """How to store `rag_doc:*` entries in the in-memory performance cache.

    - payload: store full chunk payloads (fastest, uses most RAM)
    - meta: store only lightweight references and stats (RAM-friendly)
    - none: do not cache rag docs in memory (lowest RAM, more sqlite reads)
    """
    p = _memory_pressure(mem_snapshot())
    if p in {"high", "moderate", "unknown"}:
        return "meta"
    return "payload"


def default_ai_tutor_rag_max_sources() -> int:
    """Default RAG snippet count before user prefs load."""
    p = _memory_pressure(mem_snapshot())
    if p in {"unknown", "high"}:
        return 4
    if p == "moderate":
        return 5
    return 6


def default_ai_tutor_rag_max_pdf_bytes() -> int:
    """Cap per-PDF ingest size for tutor RAG when RAM is tight."""
    p = _memory_pressure(mem_snapshot())
    if p in {"unknown", "high"}:
        return 96 * 1024 * 1024
    if p == "moderate":
        return 160 * 1024 * 1024
    return 256 * 1024 * 1024


def default_ai_tutor_max_response_chars() -> int:
    """Cap streamed tutor reply buffer under memory pressure."""
    p = _memory_pressure(mem_snapshot())
    if p in {"unknown", "high"}:
        return 7000
    if p == "moderate":
        return 9500
    return 12000


def default_ai_tutor_rag_ingest_max_chunks() -> int:
    """Cap chunk materialization per PDF during tutor RAG ingest.

    This limits peak RAM from building the per-chunk text list (even if the perf
    cache later evicts old documents).
    """
    p = _memory_pressure(mem_snapshot())
    if p in {"unknown", "high"}:
        return 600
    if p == "moderate":
        return 900
    return 1200


def default_ollama_app_queue_wait_seconds() -> float:
    """Max wait to acquire an Ollama slot; longer when memory is tight."""
    p = _memory_pressure(mem_snapshot())
    if p == "high":
        return 4.0
    if p == "moderate":
        return 2.5
    if p == "unknown":
        return 2.0
    return 1.5


def default_ollama_keep_alive_seconds() -> int:
    """How long Ollama should keep weights loaded after a request.

    Lower values reduce peak RAM when Ollama and managed llama.cpp can both be active.
    """
    p = _memory_pressure(mem_snapshot())
    if p in {"unknown", "high"}:
        return 0
    if p == "moderate":
        return 30
    return 120


def suggested_auto_llama_extra_args(mem: MemSnapshot | None = None) -> list[str]:
    """Extra llama-server CLI flags when memory is tight (user can disable via env).

    Keeps flags minimal for compatibility across llama.cpp builds.
    """
    m = mem if mem is not None else mem_snapshot()
    if _memory_pressure(m) != "high":
        return []
    # Avoid mmap page-in churn when swap is already warm; skip --mlock here (can fail or pin too much on small RAM).
    return ["--no-mmap"]


def ollama_models_base_dir() -> str:
    """Directory where Ollama stores manifests/blobs (for GGUF discovery).

    Order: ``STUDYPLAN_OLLAMA_MODELS_DIR`` (handled in config caller), then
    standard ``OLLAMA_MODELS``, then ``~/.ollama/models``.
    """
    raw = str(os.environ.get("OLLAMA_MODELS", "") or "").strip()
    if raw:
        return os.path.expanduser(raw)
    return os.path.expanduser("~/.ollama/models")


def summarize_for_logging() -> dict[str, Any]:
    m = mem_snapshot()
    return {
        "mem_total_mb": round(m.mem_total_mb, 1),
        "mem_available_mb": round(m.mem_available_mb, 1),
        "swap_used_mb": round(m.swap_used_kb / 1024.0, 1),
        "memory_pressure": _memory_pressure(m),
        "cpu_model": _read_linux_cpu_model_name()[:120],
        "llama_threads_hint": default_llama_server_thread_count(),
        "llama_ctx_hint": default_llama_server_ctx_size(),
        "llama_idle_shutdown_s_hint": default_llama_server_idle_shutdown_seconds(),
        "perf_cache_max_hint": default_performance_cache_max_size(),
        "perf_cache_rag_doc_mode_hint": str(default_performance_cache_rag_doc_store_mode()),
        "tutor_rag_sources_hint": default_ai_tutor_rag_max_sources(),
        "tutor_rag_ingest_max_chunks_hint": default_ai_tutor_rag_ingest_max_chunks(),
        "tutor_max_response_chars_hint": default_ai_tutor_max_response_chars(),
        "ollama_keep_alive_s_hint": int(default_ollama_keep_alive_seconds()),
    }
