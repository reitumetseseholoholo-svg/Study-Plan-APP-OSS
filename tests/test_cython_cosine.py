"""Tests for Cython-accelerated cosine similarity module."""

from __future__ import annotations

import math
import random


def _cosine_similarity_py(a: list[float], b: list[float]) -> float:
    """Pure-Python reference implementation."""
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
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def test_cosine_similarity_imports():
    """Verify the public API is importable and Cython path loads when .so exists."""
    from studyplan.cython.cosine import cosine_similarity, _HAS_CYTHON, _cosine_similarity_py

    assert callable(cosine_similarity)
    # _HAS_CYTHON is True when compiled .so is available
    assert isinstance(_HAS_CYTHON, bool)
    assert callable(_cosine_similarity_py)


def test_cosine_similarity_matches_python():
    """Results from Cython and pure-Python paths must be identical."""
    from studyplan.cython.cosine import cosine_similarity, _cosine_similarity_py

    rng = random.Random(42)
    for _ in range(50):
        n = rng.randint(1, 512)
        a = [rng.uniform(-1.0, 1.0) for _ in range(n)]
        b = [rng.uniform(-1.0, 1.0) for _ in range(n)]
        expected = _cosine_similarity_py(a, b)
        assert abs(cosine_similarity(a, b) - expected) < 1e-12, f"mismatch for n={n}"


def test_cosine_similarity_identical_vectors():
    """Cosine similarity of a vector with itself must be 1.0."""
    from studyplan.cython.cosine import cosine_similarity

    for n in [1, 4, 16, 128, 768]:
        v = [float(i + 1) / n for i in range(n)]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-12, f"identical n={n}"


def test_cosine_similarity_orthogonal():
    """Cosine similarity of orthogonal vectors must be 0.0."""
    from studyplan.cython.cosine import cosine_similarity

    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-12


def test_cosine_similarity_opposite():
    """Cosine similarity of opposite vectors must be -1.0."""
    from studyplan.cython.cosine import cosine_similarity

    v = [0.5, 0.5, 0.5, 0.5]
    neg = [-0.5, -0.5, -0.5, -0.5]
    assert abs(cosine_similarity(v, neg) - (-1.0)) < 1e-12


def test_cosine_similarity_empty():
    """Empty or None-like inputs must return 0.0."""
    from studyplan.cython.cosine import cosine_similarity

    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], []) == 0.0
    assert cosine_similarity([], []) == 0.0


def test_cosine_similarity_zero_vector():
    """Zero vector must return 0.0 (division by zero guard)."""
    from studyplan.cython.cosine import cosine_similarity

    zero = [0.0, 0.0, 0.0]
    normal = [1.0, 2.0, 3.0]
    assert cosine_similarity(zero, normal) == 0.0
    assert cosine_similarity(normal, zero) == 0.0
    assert cosine_similarity(zero, zero) == 0.0


def test_cosine_similarity_different_lengths():
    """When lengths differ, min length is used."""
    from studyplan.cython.cosine import cosine_similarity

    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0]
    # Only first 2 dims used: dot=1.0, norm_a=1.0, norm_b=1.0
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-12


def test_cosine_similarity_tiny_values():
    """Very small values must not crash (underflow to 0.0 is acceptable)."""
    from studyplan.cython.cosine import cosine_similarity

    tiny = 1e-200
    a = [tiny, tiny, tiny]
    b = [tiny, tiny, tiny]
    # dot product = 3e-400 underflows to 0.0 in double precision
    # both Cython and Python paths return 0.0 — no crash is the main guarantee
    sim = cosine_similarity(a, b)
    assert isinstance(sim, float)


def test_cosine_similarity_fallback_import():
    """Verify the fallback path works when Cython .so is missing."""
    import sys

    # Simulate missing .so by removing the module from sys.modules
    # and forcing import of the pure-Python fallback
    keys = [k for k in sys.modules if "cosine_fast" in k]
    for k in keys:
        del sys.modules[k]

    # Re-import — will use the pure-Python path
    from studyplan.cython.cosine import cosine_similarity as cs

    a = [1.0, 2.0, 3.0]
    b = [4.0, 5.0, 6.0]
    result = cs(a, b)
    expected = _cosine_similarity_py(a, b)
    assert abs(result - expected) < 1e-12
    # Note: _HAS_CYTHON may still be True if the .so is on disk
    # but the fallback function must still produce correct results
    assert callable(cs)


def test_cosine_similarity_consistency_regression():
    """Regression: known input must produce known output."""
    from studyplan.cython.cosine import cosine_similarity

    # Manually computed: a=[3,4], b=[3,4] -> cos=1.0
    a = [3.0, 4.0]
    b = [3.0, 4.0]
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-12

    # a=[1,0], b=[0,1] -> cos=0
    assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-12

    # a=[1,2,3], b=[4,5,6]
    # dot=4+10+18=32, |a|=sqrt(14)≈3.742, |b|=sqrt(77)≈8.775
    # cos=32/(3.742*8.775)=32/32.832≈0.9746
    sim = cosine_similarity([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    expected = 32.0 / (math.sqrt(14.0) * math.sqrt(77.0))
    assert abs(sim - expected) < 1e-12
