# cython: boundscheck=False, wraparound=False, cdivision=True
"""Cython-accelerated cosine similarity for dense embedding vectors.

Compile with: cythonize -i studyplan/cython/cosine_fast.pyx
"""

from __future__ import annotations


cpdef double cosine_similarity(list a, list b):
    """Compute cosine similarity between two dense vectors.

    Returns a float in [-1, 1] or 0.0 on edge cases.
    """
    cdef int n, i
    cdef double dot = 0.0, norm_a = 0.0, norm_b = 0.0
    cdef double va, vb

    if not a or not b:
        return 0.0

    n = len(a)
    if len(b) < n:
        n = len(b)
    if n <= 0:
        return 0.0

    for i in range(n):
        va = <double>a[i]
        vb = <double>b[i]
        dot += va * vb
        norm_a += va * va
        norm_b += vb * vb

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0

    return dot / (norm_a ** 0.5 * norm_b ** 0.5)
