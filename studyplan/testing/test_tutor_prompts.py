"""Tests for studyplan.ai.tutor_prompts (Slice 2: matrix-aligned tutor prompts)."""
from __future__ import annotations

from pathlib import Path

import pytest

from studyplan.ai.tutor_prompts import (
    get_prompt_for_tutor_action,
    get_tutor_matrix_path,
    load_tutor_matrix,
)


def test_get_tutor_matrix_path_from_repo() -> None:
    """When running from repo, matrix path resolves to tests/tutor_quality/matrix_v1.json."""
    path = get_tutor_matrix_path()
    # May be None if not in repo (e.g. installed); if present, must be matrix file
    if path is not None:
        assert path.name == "matrix_v1.json"
        assert path.is_file()


def test_load_tutor_matrix_returns_empty_when_path_none() -> None:
    assert load_tutor_matrix(None) == {}


def test_get_prompt_for_tutor_action_exact_match() -> None:
    """Exact (module_id, chapter, action_type) returns matrix prompt."""
    path = get_tutor_matrix_path()
    if path is None:
        pytest.skip("matrix not found (not in repo?)")
    prompt = get_prompt_for_tutor_action("acca_f9", "WACC", "explain", matrix_path=path)
    assert prompt is not None
    assert "WACC" in prompt
    assert "after-tax" in prompt or "cost of equity" in prompt


def test_get_prompt_for_tutor_action_fallback_same_module() -> None:
    """When chapter does not match, first case for (module_id, action_type) is used."""
    path = get_tutor_matrix_path()
    if path is None:
        pytest.skip("matrix not found (not in repo?)")
    # "Unknown Chapter" is not in matrix; should still get some F9 explain prompt
    prompt = get_prompt_for_tutor_action("acca_f9", "Unknown Chapter", "explain", matrix_path=path)
    assert prompt is not None
    assert "explain" in prompt.lower() or "WACC" in prompt


def test_get_prompt_for_tutor_action_returns_none_for_unknown_module() -> None:
    path = get_tutor_matrix_path()
    if path is None:
        pytest.skip("matrix not found (not in repo?)")
    prompt = get_prompt_for_tutor_action("unknown_module", "WACC", "explain", matrix_path=path)
    assert prompt is None


def test_get_prompt_for_tutor_action_returns_none_for_unknown_action_type() -> None:
    path = get_tutor_matrix_path()
    if path is None:
        pytest.skip("matrix not found (not in repo?)")
    prompt = get_prompt_for_tutor_action("acca_f9", "WACC", "invalid_action", matrix_path=path)
    assert prompt is None


def test_chapter_match_substring() -> None:
    """Matrix chapter 'Chapter 5: IFRS 15...' matches app chapter containing IFRS 15."""
    path = get_tutor_matrix_path()
    if path is None:
        pytest.skip("matrix not found (not in repo?)")
    prompt = get_prompt_for_tutor_action(
        "acca_f7",
        "Chapter 5: IFRS 15 Revenue from Contracts with Customers",
        "explain",
        matrix_path=path,
    )
    assert prompt is not None
    assert "IFRS 15" in prompt or "revenue" in prompt.lower()
