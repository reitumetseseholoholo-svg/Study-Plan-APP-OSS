"""TF-IDF builder and query with Cython acceleration.

Tries to import the compiled ``tfidf_fast`` Cython module.
Falls back to pure-Python implementations if unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Try to import compiled Cython module
# ---------------------------------------------------------------------------

_HAS_CYTHON: bool = False
try:
    from studyplan.cython.tfidf_fast import (  # type: ignore[import-untyped]
        build_chapter_assets as _cy_build,
        query_assets as _cy_query,
    )

    _HAS_CYTHON = True
except ImportError:
    _cy_build = None  # type: ignore[assignment]
    _cy_query = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_chapter_assets(
    outcome_texts: list[str],
    ordered_ids: list[str],
) -> tuple[Any, Any, list[str]] | None:
    """Build TfidfVectorizer + outcome matrix from outcome texts.

    Returns ``(vectorizer, outcome_matrix, ordered_ids)`` or ``None``.
    """
    if _HAS_CYTHON and _cy_build is not None:
        return _cy_build(outcome_texts, ordered_ids)
    return _build_chapter_assets_py(outcome_texts, ordered_ids)


def query_assets(
    vectorizer: Any,
    outcome_matrix: Any,
    ordered_ids: list[str],
    normalized_text: str,
) -> tuple[str | None, float]:
    """Find the best-matching outcome for ``normalized_text``.

    Returns ``(best_outcome_id, score)`` or ``(None, 0.0)``.
    """
    if _HAS_CYTHON and _cy_query is not None:
        return _cy_query(vectorizer, outcome_matrix, ordered_ids, normalized_text)
    return _query_assets_py(vectorizer, outcome_matrix, ordered_ids, normalized_text)


# ---------------------------------------------------------------------------
# Pure-Python fallbacks
# ---------------------------------------------------------------------------


def _build_chapter_assets_py(
    outcome_texts: list[str],
    ordered_ids: list[str],
) -> tuple[Any, Any, list[str]] | None:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except Exception:
        return None
    try:
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), lowercase=True)
        outcome_matrix = vectorizer.fit_transform(outcome_texts)
    except Exception:
        return None
    return (vectorizer, outcome_matrix, list(ordered_ids))


def _query_assets_py(
    vectorizer: Any,
    outcome_matrix: Any,
    ordered_ids: list[str],
    normalized_text: str,
) -> tuple[str | None, float]:
    try:
        from sklearn.metrics.pairwise import cosine_similarity
    except Exception:
        return None, 0.0
    try:
        query_vec = vectorizer.transform([normalized_text])
        sims = cosine_similarity(query_vec, outcome_matrix).flatten().tolist()
        if not sims:
            return None, 0.0
        best_idx = max(range(len(sims)), key=lambda i: float(sims[i]))
        if best_idx < 0 or best_idx >= len(ordered_ids):
            return None, 0.0
        return ordered_ids[best_idx], float(sims[best_idx])
    except Exception:
        return None, 0.0
