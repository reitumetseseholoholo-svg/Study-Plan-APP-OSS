"""
Per-model inference tuning for Ollama and llama-server (llama.cpp).

Balances subjective quality vs latency using estimated model size, architecture hints,
and optional JSON overrides (``STUDYPLAN_LLM_MODEL_RUNTIME_PATH`` or
``<CONFIG_HOME>/llm_model_runtime.json``).

Disable custom profiles with ``STUDYPLAN_LLM_MODEL_RUNTIME_DISABLE=1`` (defaults only).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

_cache_path: str | None = None
_cache_mtime: float | None = None
_cache_payload: dict[str, Any] | None = None


def clear_model_runtime_tuning_cache() -> None:
    global _cache_path, _cache_mtime, _cache_payload
    _cache_path = None
    _cache_mtime = None
    _cache_payload = None


@dataclass(frozen=True)
class ModelRuntimeTuning:
    """Unified knobs for Ollama /api/generate options and llama-server launch."""

    temperature: float = 0.28
    top_p: float = 0.92
    num_ctx: int = 4096
    # Multiply host-aware thread count (after _effective_ollama_num_threads base logic).
    thread_multiplier: float = 1.0
    thread_cap: int | None = None  # optional upper bound on Ollama num_thread
    max_output_tokens: int = 1408
    # llama-server; None = derive from Config base * thread_multiplier
    llama_server_threads: int | None = None
    llama_server_ctx_size: int | None = None
    llama_server_n_gpu_layers: int | None = None  # None = use Config.LLAMA_CPP_SERVER_N_GPU_LAYERS
    llama_server_batch_size: int | None = None  # None = use Config.LLAMA_CPP_SERVER_BATCH_SIZE


def _config_path_candidates() -> list[Path]:
    out: list[Path] = []
    env = str(os.environ.get("STUDYPLAN_LLM_MODEL_RUNTIME_PATH", "") or "").strip()
    if env:
        out.append(Path(os.path.expanduser(env)))
    try:
        from studyplan.config import CONFIG_HOME

        out.append(Path(CONFIG_HOME) / "llm_model_runtime.json")
    except Exception:
        pass
    return out


def _load_json_profile() -> dict[str, Any]:
    global _cache_path, _cache_mtime, _cache_payload
    if str(os.environ.get("STUDYPLAN_LLM_MODEL_RUNTIME_DISABLE", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {}
    for path in _config_path_candidates():
        try:
            if not path.is_file():
                continue
            mtime = float(path.stat().st_mtime)
        except OSError:
            continue
        key = str(path.resolve())
        if _cache_payload is not None and _cache_path == key and _cache_mtime == mtime:
            return _cache_payload
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        _cache_path = key
        _cache_mtime = mtime
        _cache_payload = data
        return _cache_payload
    _cache_path = None
    _cache_mtime = None
    _cache_payload = None
    return {}


def _purpose_task_kind(purpose: str) -> str:
    p = str(purpose or "").strip().lower()
    if p in {"coach", "autopilot", "gap_generation", "section_c_generation", "assess", "judge"}:
        return "json_task"
    if p in {"section_c_evaluation", "section_c_loop_diff"}:
        return "json_task"
    if p in {"section_c_judgment"}:
        return "judgment_task"
    if p in {"deep_reason"}:
        return "deep_tutor"
    return "tutor"


def _size_bucket(param_b: float | None) -> str:
    if param_b is None or param_b <= 0:
        return "unknown"
    if param_b <= 1.5:
        return "tiny"
    if param_b <= 3.0:
        return "small"
    if param_b <= 8.0:
        return "medium"
    if param_b <= 14.0:
        return "large"
    return "xlarge"


def _estimate_param_b_from_name(model_name: str) -> float | None:
    raw = str(model_name or "").strip().lower()
    if not raw:
        return None
    m = re.search(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(?:b|bn)(?![a-z0-9])", raw)
    if m:
        try:
            v = float(m.group(1))
            return v if v > 0 else None
        except ValueError:
            pass
    # Common Ollama tags without explicit "b"
    if "0.5b" in raw or re.search(r"[-:]0\.5b", raw):
        return 0.5
    if "1.5b" in raw or "1b" in raw:
        if "3.2-1b" in raw or "1.1b" in raw:
            return 1.0
        return 1.5
    if "3b" in raw and "13b" not in raw and "33b" not in raw:
        return 3.0
    if "7b" in raw or "8b" in raw:
        return 7.5
    if "12b" in raw or "13b" in raw:
        return 13.0
    if "34b" in raw or "32b" in raw:
        return 34.0
    if "70b" in raw or "72b" in raw:
        return 70.0
    return None


def _arch_hint(name: str) -> str:
    n = str(name or "").lower()
    for token in ("phi", "gemma", "qwen", "mistral", "llama", "deepseek", "tinyllama", "orca"):
        if token in n:
            return token
    return ""


def _base_tuning_for_bucket(bucket: str, arch: str) -> ModelRuntimeTuning:
    """Default sweet-spot table (tutor / balanced chat)."""
    if bucket == "tiny":
        t = ModelRuntimeTuning(
            temperature=0.40,
            top_p=0.94,
            num_ctx=4096,
            thread_multiplier=1.0,
            max_output_tokens=1280,
            llama_server_batch_size=512,
        )
    elif bucket == "small":
        t = ModelRuntimeTuning(
            temperature=0.34,
            top_p=0.93,
            num_ctx=4096,
            thread_multiplier=1.0,
            max_output_tokens=1344,
            llama_server_batch_size=512,
        )
    elif bucket == "medium":
        t = ModelRuntimeTuning(
            temperature=0.28,
            top_p=0.92,
            num_ctx=4096,
            thread_multiplier=0.95,
            max_output_tokens=1408,
            llama_server_batch_size=512,
        )
    elif bucket == "large":
        t = ModelRuntimeTuning(
            temperature=0.24,
            top_p=0.90,
            num_ctx=4096,
            thread_multiplier=0.88,
            max_output_tokens=1536,
            llama_server_batch_size=384,
        )
    elif bucket == "xlarge":
        t = ModelRuntimeTuning(
            temperature=0.20,
            top_p=0.88,
            num_ctx=3584,
            thread_multiplier=0.72,
            thread_cap=8,
            max_output_tokens=1536,
            llama_server_batch_size=256,
        )
    else:
        t = ModelRuntimeTuning()

    if arch in {"phi", "gemma"}:
        t = replace(t, temperature=min(0.42, t.temperature + 0.04))
    elif arch in {"qwen", "deepseek"}:
        t = replace(t, temperature=max(0.12, t.temperature - 0.03))
    elif arch == "mistral":
        t = replace(t, top_p=min(0.92, t.top_p + 0.01))
    return t


def _apply_purpose(t: ModelRuntimeTuning, task: str) -> ModelRuntimeTuning:
    if task == "json_task":
        return replace(
            t,
            temperature=max(0.08, min(0.22, t.temperature * 0.65)),
            top_p=min(0.90, t.top_p),
            thread_multiplier=min(1.0, t.thread_multiplier + 0.05),
        )
    if task == "judgment_task":
        # Second-pass Section C marking: slightly more headroom for structured JSON + brief rationale.
        return replace(
            t,
            temperature=max(0.10, min(0.26, t.temperature * 0.72)),
            top_p=min(0.92, t.top_p),
            max_output_tokens=min(4096, int(t.max_output_tokens * 1.4)),
            num_ctx=max(t.num_ctx, min(8192, int(t.num_ctx * 1.05))),
        )
    if task == "deep_tutor":
        return replace(
            t,
            temperature=max(0.12, t.temperature - 0.05),
            top_p=min(0.90, t.top_p),
            num_ctx=max(t.num_ctx, min(8192, int(t.num_ctx * 1.15))),
            max_output_tokens=min(2048, int(t.max_output_tokens * 1.1)),
        )
    return t


def _apply_model_specific_defaults(model_name: str, purpose: str, t: ModelRuntimeTuning) -> ModelRuntimeTuning:
    """Model-family overrides tuned for common local deployments."""
    name = str(model_name or "").strip().lower()
    purpose_key = str(purpose or "").strip().lower()
    compact = name.replace("_", "").replace("-", "").replace(" ", "")
    # Qwen 3.5 4B: balanced tutor quality with practical local latency.
    if ("qwen3.5" in compact or "qwen35" in compact) and "4b" in compact:
        if purpose_key in {"coach", "autopilot"}:
            return replace(
                t,
                temperature=max(0.08, min(1.0, 0.14)),
                top_p=max(0.0, min(1.0, 0.88)),
                num_ctx=max(2048, min(8192, 3072)),
                thread_multiplier=max(0.25, min(1.5, 1.0)),
                max_output_tokens=max(256, min(8192, 960)),
                llama_server_batch_size=512,
            )
        if purpose_key == "tutor":
            return replace(
                t,
                temperature=max(0.08, min(1.0, 0.22)),
                top_p=max(0.0, min(1.0, 0.90)),
                num_ctx=max(2048, min(8192, 4096)),
                thread_multiplier=max(0.25, min(1.5, 0.95)),
                max_output_tokens=max(256, min(8192, 1280)),
                llama_server_batch_size=512,
            )
    return t


def _coerce_float(val: Any, default: float) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _coerce_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _patch_tuning(base: ModelRuntimeTuning, patch: dict[str, Any]) -> ModelRuntimeTuning:
    if not patch:
        return base
    kwargs: dict[str, Any] = {}
    if "temperature" in patch:
        kwargs["temperature"] = max(0.0, min(2.0, _coerce_float(patch.get("temperature"), base.temperature)))
    if "top_p" in patch:
        kwargs["top_p"] = max(0.0, min(1.0, _coerce_float(patch.get("top_p"), base.top_p)))
    if "num_ctx" in patch:
        kwargs["num_ctx"] = max(512, min(32768, _coerce_int(patch.get("num_ctx"), base.num_ctx)))
    if "thread_multiplier" in patch:
        kwargs["thread_multiplier"] = max(0.25, min(1.5, _coerce_float(patch.get("thread_multiplier"), base.thread_multiplier)))
    if "thread_cap" in patch:
        cap_raw = patch.get("thread_cap")
        if cap_raw is None or str(cap_raw).strip().lower() in {"", "none", "null"}:
            kwargs["thread_cap"] = None
        else:
            kwargs["thread_cap"] = max(1, min(32, _coerce_int(cap_raw, 8)))
    if "max_output_tokens" in patch:
        kwargs["max_output_tokens"] = max(256, min(8192, _coerce_int(patch.get("max_output_tokens"), base.max_output_tokens)))
    if "llama_server_threads" in patch:
        lt = patch.get("llama_server_threads")
        if lt is None or str(lt).strip().lower() in {"", "none", "null"}:
            kwargs["llama_server_threads"] = None
        else:
            kwargs["llama_server_threads"] = max(1, min(32, _coerce_int(lt, 4)))
    if "llama_server_ctx_size" in patch:
        lc = patch.get("llama_server_ctx_size")
        if lc is None or str(lc).strip().lower() in {"", "none", "null"}:
            kwargs["llama_server_ctx_size"] = None
        else:
            kwargs["llama_server_ctx_size"] = max(512, min(32768, _coerce_int(lc, base.num_ctx)))
    if "llama_server_n_gpu_layers" in patch:
        ng = patch.get("llama_server_n_gpu_layers")
        if ng is None or str(ng).strip().lower() in {"", "none", "null"}:
            kwargs["llama_server_n_gpu_layers"] = None
        else:
            kwargs["llama_server_n_gpu_layers"] = max(-1, min(999999, _coerce_int(ng, 0)))
    if "llama_server_batch_size" in patch:
        bs = patch.get("llama_server_batch_size")
        if bs is None or str(bs).strip().lower() in {"", "none", "null"}:
            kwargs["llama_server_batch_size"] = None
        else:
            kwargs["llama_server_batch_size"] = max(32, min(4096, _coerce_int(bs, 512)))
    return replace(base, **kwargs) if kwargs else base


def _merge_json_profile(model_name: str, base: ModelRuntimeTuning) -> ModelRuntimeTuning:
    raw = _load_json_profile()
    if not raw:
        return base
    name = str(model_name or "").strip()
    lower = name.lower()
    out = base
    exact = raw.get("exact")
    if isinstance(exact, dict) and name:
        row = exact.get(name) or exact.get(lower)
        if isinstance(row, dict):
            out = _patch_tuning(out, row)
    prefixes = raw.get("prefixes")
    if isinstance(prefixes, list) and lower:
        best: tuple[int, dict[str, Any]] = (0, {})
        for item in prefixes:
            if not isinstance(item, dict):
                continue
            pref = str(item.get("prefix", "") or "").strip().lower()
            if not pref or not lower.startswith(pref):
                continue
            if len(pref) > best[0]:
                patch = item.get("tuning")
                if isinstance(patch, dict):
                    best = (len(pref), patch)
        if best[0] > 0 and best[1]:
            out = _patch_tuning(out, best[1])
    return out


def resolve_model_runtime_tuning(
    model_name: str,
    *,
    purpose: str = "tutor",
    gguf: Any | None = None,
) -> ModelRuntimeTuning:
    """Return merged tuning for an Ollama model tag or GGUF catalog name."""
    param_b: float | None = None
    if gguf is not None:
        try:
            pb = float(getattr(gguf, "param_billions", 0.0) or 0.0)
            if pb > 0:
                param_b = pb
        except (TypeError, ValueError):
            param_b = None
    if param_b is None:
        param_b = _estimate_param_b_from_name(model_name)
    bucket = _size_bucket(param_b)
    arch = _arch_hint(str(model_name or ""))
    if gguf is not None:
        try:
            ga = str(getattr(gguf, "architecture", "") or "").strip().lower()
            if ga:
                arch = ga
        except Exception:
            pass
    base = _base_tuning_for_bucket(bucket, arch)
    base = _apply_purpose(base, _purpose_task_kind(purpose))
    base = _apply_model_specific_defaults(model_name, purpose, base)
    return _merge_json_profile(model_name, base)
