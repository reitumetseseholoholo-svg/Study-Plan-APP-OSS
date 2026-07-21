"""Tests for the unified model ranker (model_ranker.py).

Covers: quant BPP lookup, parameter-size extraction from names,
architecture inference, instruct detection, purpose-tier resolution,
quality scoring, RAM estimation, and pick_best selection.
"""

from __future__ import annotations

import pytest

from studyplan.ai.model_ranker import (
    quant_bpp,
    estimate_param_b,
    infer_architecture,
    _is_instruct_model,
    resolve_tier,
    score_quality,
    estimate_ram,
    pick_best,
)


# ---------------------------------------------------------------------------
# quant_bpp
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("qwen2.5:7b-q4_k_m", 0.58),
        ("llama3.2-q8_0", 1.0),
        ("phi3.5-q2_k.gguf", 0.35),
        ("gemma2-q6", 1.0),
        ("qwen2.5_coder_fp16", 1.0),
        ("mistral-bf16", 1.0),
        ("no_quant_suffix", 0.58),  # default
        ("", 0.58),
        (None, 0.58),
    ],
)
def test_quant_bpp(name: str | None, expected: float) -> None:
    assert quant_bpp(name) == expected


# ---------------------------------------------------------------------------
# estimate_param_b
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("llama3.2:3b", 3.0),
        ("qwen2.5:1.5b", 1.5),
        ("phi3:7b-q4_k_m", 7.0),
        ("deepseek-coder-6.7b", 6.7),
        ("qwen2.5_coder_0.5b", 0.5),
        ("qwen2.5_coder_0_5b", 0.5),
        ("gemma-2-27b-it", 27.0),
        ("no-digit-suffix", 0.0),
        ("", 0.0),
        (None, 0.0),
    ],
)
def test_estimate_param_b(name: str | None, expected: float) -> None:
    assert abs(estimate_param_b(name) - expected) < 0.01


# ---------------------------------------------------------------------------
# infer_architecture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("qwen2.5:7b", "qwen"),
        ("llama3.2:3b", "llama"),
        ("phi3:7b", "phi"),
        ("deepseek-coder:6.7b", "deepseek"),
        ("gemma2:9b", "gemma"),
        ("mistral:7b", "mistral"),
        ("unknown-model:7b", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_infer_architecture(name: str | None, expected: str) -> None:
    assert infer_architecture(name) == expected


# ---------------------------------------------------------------------------
# _is_instruct_model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("llama3.2:3b-instruct", True),
        ("qwen2.5:7b-chat", True),
        ("phi3-it", True),
        ("model.it", True),
        ("llama3.2:3b-base", False),
        ("deepseek-coder", False),
        ("", False),
    ],
)
def test_is_instruct(name: str, expected: bool) -> None:
    assert _is_instruct_model(name) == expected


# ---------------------------------------------------------------------------
# resolve_tier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "purpose,expected",
    [
        ("tutor", "balanced"),
        ("coach", "balanced"),
        ("hint", "fast"),
        ("deep_reason", "quality"),
        ("section_c_judgment", "quality"),
        ("unknown_purpose", "balanced"),
        ("", "balanced"),
        (None, "balanced"),
    ],
)
def test_resolve_tier(purpose: str | None, expected: str) -> None:
    assert resolve_tier(purpose) == expected


# ---------------------------------------------------------------------------
# score_quality — basic scoring components
# ---------------------------------------------------------------------------


def test_score_quality_empty_name() -> None:
    assert score_quality("", "fast") == 0.0


def test_score_quality_instruct_bonus() -> None:
    s_instruct = score_quality("qwen2.5:7b-instruct-q4_k_m", "balanced")
    s_base = score_quality("qwen2.5:7b-base-q4_k_m", "balanced")
    assert s_instruct > s_base, "Instruct models should score higher"


def test_score_quality_arch_bonus() -> None:
    s_qwen = score_quality("qwen2.5:7b-q4_k_m", "balanced")
    s_unknown = score_quality("unknown:7b-q4_k_m", "balanced")
    assert s_qwen > s_unknown, "Known architectures get bonus"


def test_score_quality_tier_preferences() -> None:
    """Fast tier prefers small models, quality tier prefers large ones."""
    s_fast_small = score_quality("phi3:1.5b-q4_k_m", "fast")
    s_fast_large = score_quality("llama3:70b-q4_k_m", "fast")
    s_qual_small = score_quality("phi3:1.5b-q4_k_m", "quality")
    s_qual_large = score_quality("llama3:70b-q4_k_m", "quality")
    assert s_fast_small > s_fast_large, "Fast tier prefers small models"
    assert s_qual_large > s_qual_small, "Quality tier prefers large models"


def test_score_quality_quant_bonus() -> None:
    s_high = score_quality("qwen2.5:7b-q8_0", "balanced")
    s_low = score_quality("qwen2.5:7b-q2_k", "balanced")
    assert s_high > s_low, "Higher quant should score higher"


# ---------------------------------------------------------------------------
# estimate_ram
# ---------------------------------------------------------------------------


def test_estimate_ram_known_model() -> None:
    ram = estimate_ram("qwen2.5:7b-q4_k_m")
    assert ram > 0, "RAM estimate should be positive"


def test_estimate_ram_with_actual_size() -> None:
    ram = estimate_ram("qwen2.5:7b-q4_k_m", actual_size_bytes=4_000_000_000)
    assert ram > 4_000_000_000, "RAM should include file size + overhead"


def test_estimate_ram_unknown_model() -> None:
    ram = estimate_ram("")
    assert ram == 0


def test_estimate_ram_ctx_range() -> None:
    ram_512 = estimate_ram("qwen2.5:7b-q4_k_m", num_ctx=512)
    ram_8192 = estimate_ram("qwen2.5:7b-q4_k_m", num_ctx=8192)
    assert ram_8192 > ram_512, "Higher context should need more RAM"


# ---------------------------------------------------------------------------
# pick_best
# ---------------------------------------------------------------------------


def test_pick_best_empty_list() -> None:
    assert pick_best([], "tutor") is None


def test_pick_best_single_model() -> None:
    best = pick_best(["qwen2.5:7b-q4_k_m"], "tutor")
    assert best == "qwen2.5:7b-q4_k_m"


def test_pick_best_prefers_better_model() -> None:
    best = pick_best(["llama3.2:3b-q4_k_m", "qwen2.5:7b-q4_k_m"], "tutor")
    assert best is not None
    assert "qwen" in best or "llama" in best, "Should pick the highest-scored model"


def test_pick_best_exclude() -> None:
    best = pick_best(["qwen2.5:7b-q4_k_m", "phi3:7b-q4_k_m"], "tutor", exclude={"qwen2.5:7b-q4_k_m"})
    assert best == "phi3:7b-q4_k_m"


def test_pick_best_ram_limit() -> None:
    """Very tight RAM budget excludes all models."""
    best = pick_best(["qwen2.5:7b-q4_k_m"], "tutor", ram_budget=1)
    assert best is None, "No model should fit in 1 byte RAM budget"
