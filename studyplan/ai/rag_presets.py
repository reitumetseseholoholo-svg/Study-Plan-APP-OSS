"""
Named RAG retrieval presets for tutor turns (roadmap Phase 2).

Presets tune char budget, neighbor expansion, score floor, top-k ceiling, per-source
chunk caps, and hard char caps without duplicating env parsing in the app.
"""
from __future__ import annotations

from typing import Any

RAG_PRESET_NAMES = frozenset({"tutor_explain", "tutor_drill", "coach", "gap_gen"})
RAG_PRESET_DEFAULT = "tutor_explain"

# Keys: optional char_budget (upper bound on snippet chars), neighbor_window, rag_min_score_add,
# top_k_max (ceiling on env top_k_max), max_chunks_per_source, hard_char_cap (ceiling with env hard cap).
_PRESET_SPECS: dict[str, dict[str, Any]] = {
    "tutor_explain": {
        "char_budget": None,
        "neighbor_window": None,
        "rag_min_score_add": 0.0,
        "top_k_max": None,
        "max_chunks_per_source": 2,
        "hard_char_cap": None,
    },
    "tutor_drill": {
        "char_budget": 1300,
        "neighbor_window": 0,
        "rag_min_score_add": 0.02,
        "top_k_max": 9,
        "max_chunks_per_source": 1,
        "hard_char_cap": 2400,
    },
    "coach": {
        "char_budget": 1450,
        "neighbor_window": 0,
        "rag_min_score_add": 0.0,
        "top_k_max": 9,
        "max_chunks_per_source": 2,
        "hard_char_cap": 2600,
    },
    "gap_gen": {
        "char_budget": 1600,
        "neighbor_window": 0,
        "rag_min_score_add": 0.03,
        "top_k_max": 10,
        "max_chunks_per_source": 2,
        "hard_char_cap": 2800,
    },
}


def normalize_rag_preset_name(name: str | None) -> str:
    n = str(name or "").strip().lower()
    return n if n in RAG_PRESET_NAMES else RAG_PRESET_DEFAULT


def apply_rag_preset_to_runtime(
    preset: str | None,
    *,
    char_budget: int,
    neighbor_window: int,
    top_k_max: int,
    rag_min_score: float,
    hard_cap_env: int,
) -> dict[str, Any]:
    """Apply preset on top of env-derived values. Returns fields to merge into RAG builder."""
    pname = normalize_rag_preset_name(preset)
    spec = _PRESET_SPECS[pname]
    out_budget = int(char_budget)
    cap = spec.get("char_budget")
    if cap is not None:
        out_budget = min(out_budget, int(cap))
    nw = int(neighbor_window)
    if spec.get("neighbor_window") is not None:
        nw = int(spec["neighbor_window"])
    nw = max(0, min(2, nw))
    tkm = int(top_k_max)
    if spec.get("top_k_max") is not None:
        tkm = min(tkm, int(spec["top_k_max"]))
    tkm = max(4, min(16, tkm))
    rms = float(rag_min_score) + float(spec.get("rag_min_score_add", 0.0) or 0.0)
    rms = max(0.0, min(0.8, rms))
    max_per = int(spec.get("max_chunks_per_source", 2) or 2)
    max_per = max(1, min(4, max_per))
    hard = int(hard_cap_env)
    ph = spec.get("hard_char_cap")
    if ph is not None:
        hard = min(hard, int(ph))
    hard = max(800, min(8000, hard))
    out_budget = min(int(out_budget), int(hard))
    return {
        "rag_preset": pname,
        "char_budget": int(out_budget),
        "neighbor_window": int(nw),
        "top_k_max": int(tkm),
        "rag_min_score": float(rms),
        "max_chunks_per_source": int(max_per),
        "hard_char_cap": int(hard),
    }
