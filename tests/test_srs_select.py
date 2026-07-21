"""Tests for the SRS selection module (srs_select.py).

Covers the pure-Python fallback path for SRS question selection,
batch scoring, and diversity enforcement.
"""

from __future__ import annotations

import math


from studyplan.rs.srs_select import (
    _select_srs_from_scored_py,
    _batch_score_srs_py,
    _enforce_diversity,
)

# Scored tuple format (9 fields):
# (idx, due, overdue, in_cooldown, recent, is_new, retention, risk, gap_bonus)


def _make_item(
    idx: int,
    due: int = 0,
    overdue: int = 0,
    cooldown: int = 0,
    recent: int = 0,
    is_new: int = 0,
    retention: float = 0.5,
    risk: float = 0.0,
    gap_bonus: float = 0.0,
) -> tuple[int, int, int, int, int, int, float, float, float]:
    return (idx, due, overdue, cooldown, recent, is_new, retention, risk, gap_bonus)


# ---------------------------------------------------------------------------
# _select_srs_from_scored_py — basic
# ---------------------------------------------------------------------------


def test_empty_scored() -> None:
    assert _select_srs_from_scored_py([], 10, 10, []) == []


def test_target_zero() -> None:
    scored = [_make_item(1, due=1)]
    assert _select_srs_from_scored_py(scored, 0, 10, []) == []


def test_selects_due_items_first() -> None:
    scored = [
        _make_item(1, due=1),
        _make_item(2, due=0),
        _make_item(3, due=1),
    ]
    selected = _select_srs_from_scored_py(scored, 2, 10, [])
    # Due items (1, 3) should be selected
    assert 1 in selected
    assert 3 in selected


def test_fills_remaining_from_non_cooldown() -> None:
    scored = [
        _make_item(1, due=0, cooldown=0, retention=0.9),
        _make_item(2, due=0, cooldown=1, retention=0.5),
        _make_item(3, due=0, cooldown=0, retention=0.7),
    ]
    selected = _select_srs_from_scored_py(scored, 2, 10, [])
    assert 1 in selected
    assert 3 in selected
    assert 2 not in selected  # cooldown


def test_falls_back_to_cooldown() -> None:
    scored = [
        _make_item(1, due=0, cooldown=1),
        _make_item(2, due=0, cooldown=1),
        _make_item(3, due=0, cooldown=1),
    ]
    selected = _select_srs_from_scored_py(scored, 2, 10, [])
    assert len(selected) == 2


def test_selects_min_3_due_items() -> None:
    """Phase 1 picks at least 3 due items even if target is small."""
    scored = [_make_item(i, due=1) for i in range(5)]
    selected = _select_srs_from_scored_py(scored, 4, 10, [])
    assert len(selected) >= 3


# ---------------------------------------------------------------------------
# _batch_score_srs_py
# ---------------------------------------------------------------------------


def test_batch_score_empty() -> None:
    overdue, retention = _batch_score_srs_py([], [], [], [], [], [], [])
    assert overdue == []
    assert retention == []


def test_batch_score_fsrs_due() -> None:
    overdue, retention = _batch_score_srs_py(
        has_fsrs_due=[1],  # FSRS says due
        fsrs_due_days_since=[3],
        has_last_review=[1],
        days_since_review=[5],
        sm2_interval=[10.0],
        has_fsrs_stability=[1],
        fsrs_stability=[30.0],
    )
    assert overdue[0] == 1
    assert retention[0] > 0


def test_batch_score_sm2_fallback() -> None:
    """When FSRS stability is absent, use SM2 interval for retention."""
    overdue, retention = _batch_score_srs_py(
        has_fsrs_due=[0],
        fsrs_due_days_since=[-1],
        has_last_review=[1],
        days_since_review=[5],
        sm2_interval=[10.0],
        has_fsrs_stability=[0],
        fsrs_stability=[0.0],
    )
    assert overdue[0] == 0  # days_since < interval
    expected_ret = math.pow(0.9, 5.0 / 10.0)
    assert abs(retention[0] - expected_ret) < 1e-9


def test_batch_score_overdue_sm2() -> None:
    """Days since review >= interval → overdue."""
    overdue, retention = _batch_score_srs_py(
        has_fsrs_due=[0],
        fsrs_due_days_since=[-1],
        has_last_review=[1],
        days_since_review=[15],
        sm2_interval=[10.0],
        has_fsrs_stability=[0],
        fsrs_stability=[0.0],
    )
    assert overdue[0] == 1


def test_batch_score_no_review() -> None:
    """Items without review history default to 0 overdue, 0.0 retention."""
    overdue, retention = _batch_score_srs_py(
        has_fsrs_due=[0],
        fsrs_due_days_since=[-1],
        has_last_review=[0],
        days_since_review=[-1],
        sm2_interval=[0.0],
        has_fsrs_stability=[0],
        fsrs_stability=[0.0],
    )
    assert overdue[0] == 0
    assert retention[0] == 0.0


# ---------------------------------------------------------------------------
# _enforce_diversity
# ---------------------------------------------------------------------------


def test_enforce_diversity_no_recent_set() -> None:
    selected = [1, 2, 3]
    _enforce_diversity(selected, [], 0, 3, set())
    assert selected == [1, 2, 3]


def test_enforce_diversity_skips_under_due_pressure() -> None:
    """When due_pressure >= 60%, skip diversity swap."""
    scored = [_make_item(i) for i in range(10)]
    selected = [1, 2, 3]
    due_count = 4
    target = 5
    recent_lookup = {1, 2, 3}
    _enforce_diversity(selected, scored, due_count, target, recent_lookup)
    # With due_pressure (4 >= ceil(5*0.6)=3), selected unchanged
    assert selected == [1, 2, 3]


def test_enforce_diversity_swaps_recent() -> None:
    """When not under due pressure, swap recent items for non-recent."""
    scored = [
        _make_item(0, recent=0),
        _make_item(1, recent=1),
        _make_item(2, recent=1),
        _make_item(3, recent=0),
    ]
    selected = [1, 2]
    due_count = 0
    recent_lookup = {1, 2}
    _enforce_diversity(selected, scored, due_count, 2, recent_lookup)
    # Should swap at least one recent for non-recent
    non_recent = [i for i in selected if i not in recent_lookup]
    assert len(non_recent) >= 1, f"Expected >=1 non-recent, got {selected}"
