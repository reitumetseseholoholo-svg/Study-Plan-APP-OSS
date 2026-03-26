"""
Purpose-based local LLM model routing (roadmap Phase 4).

Optional JSON config lists a primary model and explicit failover order per purpose.
Paths: ``STUDYPLAN_LLM_MODEL_ROUTING_PATH`` or ``<CONFIG_HOME>/llm_model_routing.json``.

Only model names that exist in the current Ollama candidate list are used; missing
names are skipped so deployments stay safe.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_PURPOSE_ALIASES: dict[str, tuple[str, ...]] = {
    "tutor": ("tutor",),
    "deep_reason": ("deep_reason",),
    "coach": ("coach",),
    "autopilot": ("autopilot",),
    "gap_generation": ("gap_generation", "gap_gen"),
    "section_c_generation": ("section_c_generation", "section_c"),
    # Section C constructed-response: separate grading / judgment from generic coach chat.
    "section_c_evaluation": (
        "section_c_evaluation",
        "section_c_eval",
        "section_c_assess",
        "section_c_marking",
    ),
    "section_c_judgment": (
        "section_c_judgment",
        "section_c_judge",
        "section_c_thinking",
        "section_c_deep_judge",
    ),
    "section_c_loop_diff": (
        "section_c_loop_diff",
        "section_c_rewrite",
        "section_c_recheck",
    ),
    "general": ("general",),
}

_cache_path: str | None = None
_cache_mtime: float | None = None
_cache_payload: dict[str, Any] | None = None


def clear_llm_model_routing_cache() -> None:
    global _cache_path, _cache_mtime, _cache_payload
    _cache_path = None
    _cache_mtime = None
    _cache_payload = None


def _config_path_candidates() -> list[Path]:
    out: list[Path] = []
    env = str(os.environ.get("STUDYPLAN_LLM_MODEL_ROUTING_PATH", "") or "").strip()
    if env:
        out.append(Path(os.path.expanduser(env)))
    try:
        from studyplan.config import CONFIG_HOME

        out.append(Path(CONFIG_HOME) / "llm_model_routing.json")
    except Exception:
        pass
    return out


def _load_raw() -> dict[str, Any]:
    global _cache_path, _cache_mtime, _cache_payload
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


def load_llm_model_routing_table() -> dict[str, dict[str, Any]]:
    raw = _load_raw()
    purposes = raw.get("purposes")
    if not isinstance(purposes, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, val in purposes.items():
        pk = str(key or "").strip().lower()
        if not pk or not isinstance(val, dict):
            continue
        primary = val.get("primary")
        primary_s = str(primary).strip() if primary not in (None, "") else ""
        failover_raw = val.get("failover", val.get("failover_chain", []))
        chain: list[str] = []
        if isinstance(failover_raw, list):
            for item in failover_raw:
                s = str(item or "").strip()
                if s and s not in chain:
                    chain.append(s)
        elif isinstance(failover_raw, str) and failover_raw.strip():
            for token in failover_raw.replace(";", ",").split(","):
                s = str(token or "").strip()
                if s and s not in chain:
                    chain.append(s)
        out[pk] = {"primary": primary_s or None, "failover": chain}
    return out


def _purpose_keys(purpose: str) -> list[str]:
    p = str(purpose or "").strip().lower() or "general"
    keys = [p]
    for canon, aliases in _PURPOSE_ALIASES.items():
        if p == canon or p in aliases:
            if canon not in keys:
                keys.append(canon)
    return keys


def routed_primary_for_purpose(purpose: str, candidates: list[str]) -> str:
    """Return configured primary if it appears in ``candidates`` (exact match), else ''."""
    table = load_llm_model_routing_table()
    if not table or not candidates:
        return ""
    cand_set = {str(c or "").strip() for c in candidates if str(c or "").strip()}
    for pk in _purpose_keys(purpose):
        row = table.get(pk)
        if not isinstance(row, dict):
            continue
        primary = row.get("primary")
        if primary is None:
            continue
        name = str(primary).strip()
        if name and name in cand_set:
            return name
    return ""


def routed_failover_chain_for_purpose(purpose: str, candidates: list[str]) -> list[str]:
    """Ordered failover names from config that are in ``candidates``."""
    table = load_llm_model_routing_table()
    if not table or not candidates:
        return []
    cand_set = {str(c or "").strip() for c in candidates if str(c or "").strip()}
    seen: set[str] = set()
    out: list[str] = []
    for pk in _purpose_keys(purpose):
        row = table.get(pk)
        if not isinstance(row, dict):
            continue
        for item in list(row.get("failover") or []):
            name = str(item or "").strip()
            if not name or name in seen:
                continue
            if name not in cand_set:
                continue
            seen.add(name)
            out.append(name)
    return out
