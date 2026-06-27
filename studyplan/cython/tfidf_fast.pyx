# cython: boundscheck=False, wraparound=False, cdivision=True
"""Cython-accelerated TF-IDF builder and query for semantic chapter matching.

Compile with: cythonize -i studyplan/cython/tfidf_fast.pyx
"""

from __future__ import annotations

from typing import Any
import numpy as np
cimport numpy as cnp

# ---------------------------------------------------------------------------
# Build per-chapter TF-IDF assets
# ---------------------------------------------------------------------------

cpdef object build_chapter_assets(
    list outcome_texts,
    list ordered_ids,
):
    """Build TfidfVectorizer + outcome matrix from outcome texts.

    Returns
    -------
    (vectorizer, outcome_matrix, ordered_ids) or None on failure.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    cdef object vectorizer
    cdef object outcome_matrix

    try:
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), lowercase=True)
        outcome_matrix = vectorizer.fit_transform(outcome_texts)
    except Exception:
        return None

    return (vectorizer, outcome_matrix, list(ordered_ids))


# ---------------------------------------------------------------------------
# Query TF-IDF assets
# ---------------------------------------------------------------------------

cpdef tuple query_assets(
    object vectorizer,
    object outcome_matrix,
    list ordered_ids,
    str normalized_text,
):
    """Find the best-matching outcome for normalized_text.

    Returns
    -------
    (best_outcome_id, score) or (None, 0.0) on failure.
    """
    from sklearn.metrics.pairwise import cosine_similarity

    cdef int best_idx, i, n
    cdef double best_score, score
    cdef cnp.ndarray sims_arr
    cdef list sims_list

    try:
        query_vec = vectorizer.transform([normalized_text])
        sims_arr = cosine_similarity(query_vec, outcome_matrix).flatten()
        sims_list = sims_arr.tolist()
    except Exception:
        return (None, 0.0)

    if not sims_list or not ordered_ids:
        return (None, 0.0)

    n = len(sims_list)
    best_idx = 0
    best_score = <double>sims_list[0]
    for i in range(1, n):
        score = <double>sims_list[i]
        if score > best_score:
            best_score = score
            best_idx = i

    if best_idx < 0 or best_idx >= len(ordered_ids):
        return (None, 0.0)
    return (ordered_ids[best_idx], <double>best_score)
