"""Tests for RAG preset configuration (rag_presets.py)."""

from __future__ import annotations

import pytest

from studyplan.ai.rag_presets import (
    RAG_PRESET_NAMES,
    RAG_PRESET_DEFAULT,
    normalize_rag_preset_name,
    apply_rag_preset_to_runtime,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_preset_names_are_known() -> None:
    assert RAG_PRESET_NAMES == {"tutor_explain", "tutor_drill", "coach", "gap_gen"}


def test_preset_default() -> None:
    assert RAG_PRESET_DEFAULT == "tutor_explain"


# ---------------------------------------------------------------------------
# normalize_rag_preset_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("tutor_explain", "tutor_explain"),
        ("TUTOR_DRILL", "tutor_drill"),
        ("  Coach  ", "coach"),
        ("gap_gen", "gap_gen"),
        ("unknown_preset", "tutor_explain"),  # fallback to default
        ("", "tutor_explain"),
        (None, "tutor_explain"),
    ],
)
def test_normalize_rag_preset_name(name: str | None, expected: str) -> None:
    assert normalize_rag_preset_name(name) == expected


# ---------------------------------------------------------------------------
# apply_rag_preset_to_runtime — each preset
# ---------------------------------------------------------------------------


def test_apply_tutor_explain_relaxes_budget() -> None:
    """tutor_explain has no upper cap, passes env values through."""
    result = apply_rag_preset_to_runtime(
        "tutor_explain",
        char_budget=2000,
        neighbor_window=1,
        top_k_max=12,
        rag_min_score=0.1,
        hard_cap_env=5000,
    )
    assert result["rag_preset"] == "tutor_explain"
    assert result["char_budget"] == 2000
    assert result["neighbor_window"] == 1
    assert result["top_k_max"] == 12
    assert result["rag_min_score"] == 0.1
    assert result["hard_char_cap"] == 5000


def test_apply_tutor_drill_caps() -> None:
    """tutor_drill has strict caps."""
    result = apply_rag_preset_to_runtime(
        "tutor_drill",
        char_budget=5000,
        neighbor_window=5,
        top_k_max=20,
        rag_min_score=0.0,
        hard_cap_env=9999,
    )
    assert result["rag_preset"] == "tutor_drill"
    assert result["char_budget"] == 1300  # capped by spec
    assert result["neighbor_window"] == 0  # overridden by spec then clamped [0,2]
    assert result["top_k_max"] == 9  # capped by spec
    assert result["hard_char_cap"] == 2400  # capped by spec


def test_apply_coach_preset() -> None:
    """Coach preset: char_budget 1450, top_k_max 9, hard_char_cap 2600."""
    result = apply_rag_preset_to_runtime(
        "coach",
        char_budget=3000,
        neighbor_window=2,
        top_k_max=15,
        rag_min_score=0.05,
        hard_cap_env=5000,
    )
    assert result["rag_preset"] == "coach"
    assert result["char_budget"] == 1450
    assert result["top_k_max"] == 9
    assert result["hard_char_cap"] == 2600


def test_apply_gap_gen_preset() -> None:
    """gap_gen: char_budget 1600, top_k_max 10, hard_char_cap 2800, rag_min_score 0.03 add."""
    result = apply_rag_preset_to_runtime(
        "gap_gen",
        char_budget=5000,
        neighbor_window=0,
        top_k_max=20,
        rag_min_score=0.0,
        hard_cap_env=9999,
    )
    assert result["rag_preset"] == "gap_gen"
    assert result["char_budget"] == 1600
    assert result["top_k_max"] == 10
    assert result["hard_char_cap"] == 2800
    assert abs(result["rag_min_score"] - 0.03) < 1e-9  # base 0.0 + add 0.03


# ---------------------------------------------------------------------------
# apply_rag_preset_to_runtime — clamping ranges
# ---------------------------------------------------------------------------


def test_clamp_neighbor_window() -> None:
    result = apply_rag_preset_to_runtime(
        "tutor_explain",
        char_budget=1000,
        neighbor_window=99,
        top_k_max=10,
        rag_min_score=0.0,
        hard_cap_env=5000,
    )
    assert 0 <= result["neighbor_window"] <= 2


def test_clamp_top_k_max() -> None:
    result = apply_rag_preset_to_runtime(
        "tutor_explain",
        char_budget=1000,
        neighbor_window=0,
        top_k_max=999,
        rag_min_score=0.0,
        hard_cap_env=5000,
    )
    assert 4 <= result["top_k_max"] <= 16


def test_clamp_rag_min_score() -> None:
    result = apply_rag_preset_to_runtime(
        "tutor_explain",
        char_budget=1000,
        neighbor_window=0,
        top_k_max=10,
        rag_min_score=-0.5,
        hard_cap_env=5000,
    )
    assert 0.0 <= result["rag_min_score"] <= 0.8


def test_clamp_max_chunks_per_source() -> None:
    result = apply_rag_preset_to_runtime(
        "tutor_explain",
        char_budget=1000,
        neighbor_window=0,
        top_k_max=10,
        rag_min_score=0.0,
        hard_cap_env=5000,
    )
    assert 1 <= result["max_chunks_per_source"] <= 4


def test_clamp_hard_char_cap() -> None:
    result = apply_rag_preset_to_runtime(
        "tutor_explain",
        char_budget=1000,
        neighbor_window=0,
        top_k_max=10,
        rag_min_score=0.0,
        hard_cap_env=50,  # below minimum
    )
    assert result["hard_char_cap"] >= 800


def test_clamp_hard_char_cap_upper() -> None:
    result = apply_rag_preset_to_runtime(
        "tutor_explain",
        char_budget=1000,
        neighbor_window=0,
        top_k_max=10,
        rag_min_score=0.0,
        hard_cap_env=99999,  # above maximum
    )
    assert result["hard_char_cap"] <= 8000


# ---------------------------------------------------------------------------
# Default fallback
# ---------------------------------------------------------------------------


def test_unknown_preset_falls_back_to_default() -> None:
    result = apply_rag_preset_to_runtime(
        "completely_unknown",
        char_budget=1000,
        neighbor_window=0,
        top_k_max=10,
        rag_min_score=0.0,
        hard_cap_env=5000,
    )
    assert result["rag_preset"] == "tutor_explain"


def test_none_preset_falls_back_to_default() -> None:
    result = apply_rag_preset_to_runtime(
        None,
        char_budget=1000,
        neighbor_window=0,
        top_k_max=10,
        rag_min_score=0.0,
        hard_cap_env=5000,
    )
    assert result["rag_preset"] == "tutor_explain"


# ---------------------------------------------------------------------------
# Return dict structure
# ---------------------------------------------------------------------------


def test_return_dict_keys() -> None:
    result = apply_rag_preset_to_runtime(
        "coach",
        char_budget=2000,
        neighbor_window=1,
        top_k_max=10,
        rag_min_score=0.05,
        hard_cap_env=3000,
    )
    expected_keys = {
        "rag_preset",
        "char_budget",
        "neighbor_window",
        "top_k_max",
        "rag_min_score",
        "max_chunks_per_source",
        "hard_char_cap",
    }
    assert set(result.keys()) == expected_keys
