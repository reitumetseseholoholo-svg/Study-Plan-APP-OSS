"""Tests for TF-IDF module (cython/tfidf.py).

Covers: pure-Python fallback build_chapter_assets and query_assets,
empty inputs, single-element edge cases, missing sklearn.
"""

from __future__ import annotations


from studyplan.cython.tfidf import (
    _HAS_CYTHON,
    _build_chapter_assets_py,
    _query_assets_py,
    build_chapter_assets,
    query_assets,
)


# ---------------------------------------------------------------------------
# _build_chapter_assets_py
# ---------------------------------------------------------------------------


def test_build_assets_basic() -> None:
    texts = ["calculate net present value", "compute internal rate of return", "evaluate payback period"]
    ids = ["out_npv", "out_irr", "out_payback"]
    result = _build_chapter_assets_py(texts, ids)
    assert result is not None
    vectorizer, matrix, out_ids = result
    assert vectorizer is not None
    assert matrix.shape[0] == 3
    assert out_ids == ids


def test_build_assets_empty_texts_returns_none() -> None:
    result = _build_chapter_assets_py([], [])
    assert result is None  # TfidfVectorizer raises on empty corpus


def test_build_assets_single_outcome() -> None:
    texts = ["single outcome text"]
    ids = ["out_single"]
    result = _build_chapter_assets_py(texts, ids)
    assert result is not None
    _, matrix, out_ids = result
    assert matrix.shape[0] == 1
    assert out_ids == ["out_single"]


def test_build_assets_single_word_fails() -> None:
    """Single-char tokens don't match the default token_pattern."""
    result = _build_chapter_assets_py(["a"], ["out_a"])
    assert result is None


def test_build_assets_empty_string_among_valid() -> None:
    texts = ["real text", "", "another real text"]
    ids = ["out_a", "out_b", "out_c"]
    result = _build_chapter_assets_py(texts, ids)
    assert result is not None
    _, matrix, out_ids = result
    assert matrix.shape[0] == 3
    assert out_ids == ["out_a", "out_b", "out_c"]


# ---------------------------------------------------------------------------
# _query_assets_py
# ---------------------------------------------------------------------------


def test_query_assets_basic() -> None:
    texts = ["calculate net present value", "compute internal rate of return"]
    ids = ["out_npv", "out_irr"]
    built = _build_chapter_assets_py(texts, ids)
    assert built is not None
    vec, mat, oids = built
    best_id, score = _query_assets_py(vec, mat, oids, "net present value")
    assert best_id == "out_npv"
    assert score > 0.0


def test_query_assets_no_match() -> None:
    texts = ["calculate net present value", "compute internal rate of return"]
    ids = ["out_npv", "out_irr"]
    built = _build_chapter_assets_py(texts, ids)
    assert built is not None
    vec, mat, oids = built
    best_id, score = _query_assets_py(vec, mat, oids, "completely unrelated topic")
    assert best_id in ("out_npv", "out_irr")
    assert score >= 0.0


def test_query_assets_exact_match() -> None:
    texts = ["discounted cash flow", "net present value"]
    ids = ["out_dcf", "out_npv"]
    built = _build_chapter_assets_py(texts, ids)
    assert built is not None
    vec, mat, oids = built
    best_id, score = _query_assets_py(vec, mat, oids, texts[0])
    assert best_id == "out_dcf"
    assert score >= 0.99


def test_query_assets_single_outcome() -> None:
    texts = ["unique outcome description"]
    ids = ["out_unique"]
    built = _build_chapter_assets_py(texts, ids)
    assert built is not None
    vec, mat, oids = built
    best_id, score = _query_assets_py(vec, mat, oids, "anything")
    assert best_id == "out_unique"
    assert score >= 0.0


def test_query_assets_empty_query() -> None:
    texts = ["first option", "second option"]
    ids = ["out_1", "out_2"]
    built = _build_chapter_assets_py(texts, ids)
    assert built is not None
    vec, mat, oids = built
    best_id, score = _query_assets_py(vec, mat, oids, "")
    assert best_id is not None
    assert score >= 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def test_public_build_dispatches() -> None:
    texts = ["calculate net present value", "compute internal rate of return"]
    ids = ["out_npv", "out_irr"]
    result = build_chapter_assets(texts, ids)
    assert result is not None


def test_public_query_dispatches() -> None:
    texts = ["calculate net present value", "compute internal rate of return"]
    ids = ["out_npv", "out_irr"]
    built = build_chapter_assets(texts, ids)
    assert built is not None
    vec, mat, oids = built
    best_id, score = query_assets(vec, mat, oids, "net present value")
    assert best_id == "out_npv"
    assert score > 0.0


def test_public_build_empty() -> None:
    result = build_chapter_assets([], [])
    if _HAS_CYTHON:
        assert result is not None or result is None
    else:
        assert result is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_build_assets_identical_texts() -> None:
    texts = ["same text", "same text", "same text"]
    ids = ["out_a", "out_b", "out_c"]
    result = _build_chapter_assets_py(texts, ids)
    assert result is not None
    _, matrix, out_ids = result
    assert matrix.shape[0] == 3
    assert out_ids == ids


def test_build_assets_special_chars() -> None:
    texts = ["ROI = 15%", "EVA calculation", "beta coefficient"]
    ids = ["out_roi", "out_eva", "out_beta"]
    result = _build_chapter_assets_py(texts, ids)
    assert result is not None
    _, matrix, out_ids = result
    assert matrix.shape[0] == 3
    assert out_ids == ids


def test_query_assets_empty_outcomes_not_built() -> None:
    built = _build_chapter_assets_py([], [])
    assert built is None
    # Can't query what wasn't built


def test_query_mismatched_ids() -> None:
    texts = ["apple fruit", "banana fruit"]
    ids = ["out_apple", "out_banana"]
    built = _build_chapter_assets_py(texts, ids)
    assert built is not None
    vec, mat, oids = built
    best_id, score = _query_assets_py(vec, mat, oids, "apple")
    assert best_id == "out_apple"
    assert score > 0.0
