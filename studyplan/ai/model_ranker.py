"""Unified model ranker across all backends.

Provides a single quality-scoring and selection pipeline used by both
GGUF (``ModelSelector``) and Ollama (``_pick_ollama_model_safe_for_ram``)
paths, eliminating duplicate formulas and inconsistent rankings.

Usage::

    from studyplan.ai.model_ranker import pick_best, score_quality
    best = pick_best(["llama3.2:3b", "qwen2:7b"], "tutor", ram_budget=8_000_000_000)
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quantisation bytes-per-parameter lookup
# ---------------------------------------------------------------------------
_QUANT_BPP: dict[str, float] = {
    "q2_k": 0.35, "q2": 0.35,
    "q3_k": 0.45, "q3": 0.45,
    "q4_k": 0.58, "q4_0": 0.58, "q4": 0.58,
    "q5_k": 0.75, "q5": 0.75,
    "q6": 1.0, "q8": 1.0, "f16": 1.0, "fp16": 1.0, "bf16": 1.0,
}


def quant_bpp(model_name: str) -> float:
    raw = str(model_name or "").strip().lower()
    for key in sorted(_QUANT_BPP, key=len, reverse=True):
        if key in raw:
            return _QUANT_BPP[key]
    return 0.58


# ---------------------------------------------------------------------------
# Parameter-size extraction
# ---------------------------------------------------------------------------
_PARAM_DOT = re.compile(r"(?<![a-z0-9])(\d+[._]\d+)\s*(?:b|bn)(?![a-z0-9])")
_PARAM_INT = re.compile(r"(?<![a-z0-9])(\d+)\s*(?:b|bn)(?![a-z0-9])")


def estimate_param_b(model_name: str) -> float:
    """Extract billions of parameters from a model name.

    Handles ``7b``, ``1.5b``, ``1_5b``, ``1-5b``, ``8bn``.

    Strategy:
    1. Dot/underscore decimal → unambiguous.
    2. Rightmost ``\\d+b`` — check for preceding ``\\d+-`` that forms
       a plausible size (fractional digit 0 or 5).
    3. Fallback to just the integer.
    """
    raw = str(model_name or "").strip().lower()
    if not raw:
        return 0.0

    m = _PARAM_DOT.search(raw)
    if m:
        try:
            return float(m.group(1).replace("_", "."))
        except (ValueError, TypeError):
            pass

    matches = list(_PARAM_INT.finditer(raw))
    if not matches:
        return 0.0

    m = matches[-1]
    frac_str: str = m.group(1)
    start: int = m.start()

    if start >= 2 and raw[start - 1] == "-":
        int_end = start - 1
        int_start = int_end - 1
        while int_start >= 0 and raw[int_start].isdigit():
            int_start -= 1
        int_str = raw[int_start + 1: int_end]
        if int_str.isdigit():
            try:
                combined = float(f"{int_str}.{frac_str}")
                if 0 < combined <= 200 and frac_str[-1] in ("0", "5"):
                    return combined
            except (ValueError, TypeError):
                pass

    try:
        v = float(frac_str)
        return v if v > 0 else 0.0
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Architecture inference
# ---------------------------------------------------------------------------
def infer_architecture(model_name: str) -> str:
    lower = str(model_name or "").strip().lower()
    for token in ("deepseek", "llama", "qwen", "phi", "gemma",
                  "orca", "mistral", "mamba", "falcon", "starcoder",
                  "tinyllama", "gpt4all"):
        if token in lower:
            return token
    return ""


def _is_instruct_model(model_name: str) -> bool:
    lower = str(model_name or "").strip().lower()
    return any(tok in lower for tok in ("instruct", "chat", "it-", "-it", ".it"))


# ---------------------------------------------------------------------------
# Purpose-tier mapping
# ---------------------------------------------------------------------------
_PURPOSE_TIER: dict[str, str] = {
    "hint": "fast",
    "fast": "fast",
    "deep_reason": "quality",
    "deepreason": "quality",
    "quality": "quality",
    "judgment": "quality",
    "section_c_judgment": "quality",
    "assess": "balanced",
    "assessment": "balanced",
    "tutor": "balanced",
    "coach": "balanced",
    "autopilot": "balanced",
    "general": "balanced",
    "gap_generation": "balanced",
    "section_c_generation": "balanced",
    "section_c_evaluation": "balanced",
    "section_c_loop_diff": "balanced",
}


def resolve_tier(purpose: str) -> str:
    return _PURPOSE_TIER.get(str(purpose or "").strip().lower(), "balanced")


# ---------------------------------------------------------------------------
# Architecture bonuses
# ---------------------------------------------------------------------------
_ARCH_BONUS: dict[str, float] = {
    "qwen": 1.5,
    "llama": 1.5,
    "phi": 1.0,
    "gemma": 1.0,
    "deepseek": 0.5,
    "mistral": 0.5,
    "gpt4all": 0.3,
}


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------
def score_quality(model_name: str, purpose_tier: str, *,
                  param_b: float = 0.0,
                  quant: str = "",
                  is_instruct: bool | None = None,
                  arch: str = "") -> float:
    """Return a higher-is-better quality score for *model_name*.

    All keyword parameters are optional — if omitted they are inferred
    from *model_name*.
    """
    name = str(model_name or "").strip().lower()
    if not name:
        return 0.0

    if param_b <= 0:
        param_b = estimate_param_b(name)
    if not arch:
        arch = infer_architecture(name)
    if not quant:
        quant = _infer_quant_from_name(name)
    if is_instruct is None:
        is_instruct = _is_instruct_model(name)

    bpp: float = _QUANT_BPP[quant] if quant in _QUANT_BPP else quant_bpp(name)

    score = 0.0

    # --- Parameter-size preference (per purpose tier) ---
    score += _param_size_score(param_b, purpose_tier)

    # --- Quantisation quality ---
    # Base bonus from bits-per-parameter
    if bpp >= 1.0:
        score += 2.0
    elif bpp >= 0.75:
        score += 1.5
    elif bpp >= 0.58:
        score += 1.0
    elif bpp >= 0.45:
        score += 0.5
    # Additional nuance from quant tag beyond raw BPP.
    # This preserves the differentiation the old ModelSelector had
    # (q4_k_m > q4_0, q5 > q4, etc.).
    qt = quant or _infer_quant_from_name(name)
    if "q5" in qt or "q6" in qt:
        score += 1.5
    elif "q4_k_m" in qt or "q4_k_s" in qt:
        score += 1.0
    elif "q4_k" in qt:
        score += 0.8
    elif "q8" in qt:
        score += 0.5
    elif qt.startswith("q4_0"):
        score += 0.0
    elif "q2" in qt or "q3" in qt:
        score -= 1.0
    else:
        score += 0.3

    # --- Instruct bonus ---
    if is_instruct:
        score += 3.0
    else:
        score -= 0.5

    # --- Architecture bonus ---
    for token, bonus in _ARCH_BONUS.items():
        if token in name:
            score += bonus
            break

    return score


def _param_size_score(size_b: float, tier: str) -> float:
    if size_b <= 0:
        return 3.0
    if tier == "fast":
        if size_b <= 1.5:
            return 10.0
        if size_b <= 3.0:
            return 7.0
        if size_b <= 7.0:
            return 2.0
        return -3.0
    if tier == "quality":
        if size_b >= 30.0:
            return 10.0
        if size_b >= 12.0:
            return 8.0
        if size_b >= 7.0:
            return 6.0
        if size_b >= 3.0:
            return 3.0
        return 0.5
    # balanced — sweet spot 1.5-3B (fast enough for interactive, capable enough for tutor)
    if size_b < 1.5:
        return 4.0
    if 1.5 <= size_b < 3.0:
        return 10.0
    if 3.0 <= size_b <= 7.0:
        return 10.5  # slight edge over 1.5B for balanced tutor
    return 2.0


def _infer_quant_from_name(name: str) -> str:
    m = re.search(
        r"(q[2345678](?:_[0kms]+(?:_[sml])?)?|fp16|f16|bf16|f32)", name, re.IGNORECASE
    )
    return m.group(1).lower().replace("-", "_") if m else ""


# ---------------------------------------------------------------------------
# RAM estimation
# ---------------------------------------------------------------------------
_RUNTIME_OVERHEAD = 300_000_000


def estimate_ram(model_name: str, *,
                 actual_size_bytes: int | None = None,
                 num_ctx: int = 4096) -> int:
    """Estimate RAM (bytes) needed to load *model_name*."""
    if actual_size_bytes is not None and actual_size_bytes > 0:
        weight_bytes = int(actual_size_bytes)
    else:
        size_b = estimate_param_b(model_name)
        if size_b <= 0:
            return 0
        bpp = _QUANT_BPP.get(_infer_quant_from_name(model_name)) or quant_bpp(model_name)
        weight_bytes = int(size_b * 1_000_000_000 * bpp)

    ctx = max(512, min(65536, int(num_ctx)))
    size_b = estimate_param_b(model_name)
    if size_b > 0:
        kv_overhead = int(size_b * 300_000_000 * ctx / 4096)
    else:
        kv_overhead = int(weight_bytes * ctx * 0.5 / 4096)

    return int(weight_bytes) + int(kv_overhead) + _RUNTIME_OVERHEAD


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------
def pick_best(models: list[str], purpose: str, *,
              ram_budget: int = 0,
              exclude: set[str] | None = None,
              actual_sizes: dict[str, int] | None = None) -> str | None:
    """Pick the best model from *models* for *purpose*.

    Parameters
    ----------
    models:
        Model name strings (e.g. ``["llama3.2:3b", "qwen2:7b"]``).
    purpose:
        High-level purpose (``"tutor"``, ``"coach"``, etc.).
    ram_budget:
        Maximum RAM in bytes. 0 = no limit.
    exclude:
        Model names to skip (e.g. cooldown set).
    actual_sizes:
        Optional mapping of model name → GGUF file size (bytes) for
        more accurate RAM estimation.
    """
    if not models:
        return None

    tier = resolve_tier(purpose)
    ex = frozenset(exclude) if exclude else frozenset()

    scored: list[tuple[float, int, str]] = []
    for name in models:
        if name in ex:
            continue
        q = score_quality(name, tier)
        actual = (actual_sizes or {}).get(name)
        need = estimate_ram(name, actual_size_bytes=actual)
        fits = (need <= 0) or (ram_budget <= 0) or (need <= ram_budget)
        if not fits:
            continue
        headroom = 0.0
        if ram_budget > 0 and need > 0:
            hr = max(0.0, 1.0 - (need / ram_budget))
            if hr > 0.3:
                headroom = 0.5
        scored.append((q + headroom, need or 0, name))

    if not scored:
        return None

    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    return scored[0][2]
