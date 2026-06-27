"""Cosine similarity with Cython acceleration.

Tries to import the compiled ``cosine_fast`` Cython module.
Falls back to pure-Python implementation if unavailable.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Try to import compiled Cython module
# ---------------------------------------------------------------------------

_HAS_CYTHON: bool = False
try:
    from studyplan.cython.cosine_fast import cosine_similarity as _cy_cosine  # type: ignore[import-untyped]

    _HAS_CYTHON = True
except ImportError:
    _cy_cosine = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two dense embedding vectors.

    Parameters
    ----------
    a : list[float]
        First vector.
    b : list[float]
        Second vector.

    Returns
    -------
    float
        Cosine similarity in ``[-1, 1]`` or ``0.0`` on edge cases.
    """
    if _HAS_CYTHON and _cy_cosine is not None:
        return _cy_cosine(a, b)
    return _cosine_similarity_py(a, b)


# ---------------------------------------------------------------------------
# Pure-Python fallback
# ---------------------------------------------------------------------------


def _cosine_similarity_py(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(n):
        va = float(a[i])
        vb = float(b[i])
        dot += va * vb
        norm_a += va * va
        norm_b += vb * vb
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / ((norm_a**0.5) * (norm_b**0.5))
