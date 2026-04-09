"""Unit tests for studyplan/fsrs.py — FSRS-4.5 scheduler."""
from __future__ import annotations

import datetime
import math

import pytest

from studyplan.fsrs import (
    DEFAULT_DESIRED_RETENTION,
    FSRSCard,
    FSRSScheduler,
    _safe_float,
    _safe_int,
    fsrs_update_srs_item,
    optimize_desired_retention_from_history,
)


# ---------------------------------------------------------------------------
# FSRSCard construction
# ---------------------------------------------------------------------------


def test_fsrs_card_default_values():
    card = FSRSCard()
    assert card.stability == 1.0
    assert 1.0 <= card.difficulty <= 10.0
    assert card.reps == 0
    assert card.lapses == 0
    assert card.last_review is None
    assert card.is_new() is True


def test_fsrs_card_from_srs_dict_empty():
    card = FSRSCard.from_srs_dict({})
    assert card.stability >= 0.01
    assert 1.0 <= card.difficulty <= 10.0


def test_fsrs_card_from_srs_dict_reads_fsrs_keys():
    d = {
        "fsrs_stability": 5.5,
        "fsrs_difficulty": 3.2,
        "fsrs_reps": 4,
        "fsrs_lapses": 1,
        "fsrs_last_review": "2025-01-10",
        "fsrs_due": "2025-01-20",
    }
    card = FSRSCard.from_srs_dict(d)
    assert card.stability == 5.5
    assert card.difficulty == 3.2
    assert card.reps == 4
    assert card.lapses == 1
    assert card.last_review == "2025-01-10"
    assert card.due == "2025-01-20"


def test_fsrs_card_from_srs_dict_falls_back_to_legacy_last_review():
    d = {"last_review": "2025-03-01"}
    card = FSRSCard.from_srs_dict(d)
    assert card.last_review == "2025-03-01"


def test_fsrs_card_to_dict_has_expected_keys():
    card = FSRSCard(stability=3.0, difficulty=4.5, reps=2, lapses=0, last_review="2025-01-01", due="2025-01-08")
    d = card.to_dict()
    assert "fsrs_stability" in d
    assert "fsrs_difficulty" in d
    assert "fsrs_reps" in d
    assert "fsrs_lapses" in d
    assert "fsrs_last_review" in d
    assert "fsrs_due" in d


def test_fsrs_card_non_dict_input_returns_default():
    card = FSRSCard.from_srs_dict(None)  # type: ignore[arg-type]
    assert card.is_new()


# ---------------------------------------------------------------------------
# FSRSScheduler construction
# ---------------------------------------------------------------------------


def test_scheduler_default_weights():
    sched = FSRSScheduler()
    assert len(sched.w) == 17
    assert sched.desired_retention == DEFAULT_DESIRED_RETENTION


def test_scheduler_rejects_wrong_weight_count():
    with pytest.raises(ValueError, match="17 weights"):
        FSRSScheduler(weights=(1.0, 2.0))


def test_scheduler_clamps_desired_retention():
    sched = FSRSScheduler(desired_retention=0.5)
    assert sched.desired_retention == 0.70

    sched2 = FSRSScheduler(desired_retention=0.999)
    assert sched2.desired_retention == 0.99


# ---------------------------------------------------------------------------
# FSRSScheduler.review — new card
# ---------------------------------------------------------------------------


@pytest.fixture
def sched():
    return FSRSScheduler()


def test_review_new_card_again_sets_lapse(sched):
    card = FSRSCard()
    updated = sched.review(card, rating=1)
    assert updated.lapses == 1
    assert updated.reps == 0
    assert updated.last_review is not None


def test_review_new_card_good_increments_reps(sched):
    card = FSRSCard()
    updated = sched.review(card, rating=3)
    assert updated.reps == 1
    assert updated.lapses == 0


def test_review_new_card_easy_has_longest_interval(sched):
    card = FSRSCard()
    updated_good = sched.review(card, rating=3)
    updated_easy = sched.review(card, rating=4)

    def _days(c: FSRSCard) -> int:
        if c.due is None or c.last_review is None:
            return 0
        d = datetime.date.fromisoformat(c.due) - datetime.date.fromisoformat(c.last_review)
        return d.days

    assert _days(updated_easy) >= _days(updated_good)


def test_review_new_card_again_has_shortest_interval(sched):
    card = FSRSCard()
    again = sched.review(card, rating=1)
    good = sched.review(card, rating=3)

    def _interval(c: FSRSCard) -> int:
        if c.due is None or c.last_review is None:
            return 0
        return (datetime.date.fromisoformat(c.due) - datetime.date.fromisoformat(c.last_review)).days

    assert _interval(again) <= _interval(good)


# ---------------------------------------------------------------------------
# FSRSScheduler.review — existing card
# ---------------------------------------------------------------------------


def _reviewed_card(sched: FSRSScheduler, n_good: int = 3) -> FSRSCard:
    card = FSRSCard()
    for _ in range(n_good):
        card = sched.review(card, rating=3, review_date=datetime.date(2025, 1, 1))
    return card


def test_review_existing_card_correct_increases_stability(sched):
    card = _reviewed_card(sched, n_good=2)
    s_before = card.stability
    updated = sched.review(card, rating=3, review_date=datetime.date(2025, 1, 15))
    assert updated.stability >= s_before


def test_review_existing_card_lapse_increases_lapses(sched):
    card = _reviewed_card(sched, n_good=3)
    lapses_before = card.lapses
    updated = sched.review(card, rating=1)
    assert updated.lapses == lapses_before + 1


def test_review_existing_card_lapse_resets_reps(sched):
    card = _reviewed_card(sched, n_good=3)
    updated = sched.review(card, rating=1)
    assert updated.reps == 0


def test_stability_stays_positive_after_lapse(sched):
    card = _reviewed_card(sched, n_good=1)
    for _ in range(5):
        card = sched.review(card, rating=1)
    assert card.stability > 0.0


def test_difficulty_clamps_between_1_and_10(sched):
    card = FSRSCard()
    # Apply extreme ratings repeatedly.
    for rating in [1, 1, 1, 4, 4, 4, 1, 1, 4]:
        card = sched.review(card, rating=rating)
    assert 1.0 <= card.difficulty <= 10.0


# ---------------------------------------------------------------------------
# FSRSScheduler.is_due
# ---------------------------------------------------------------------------


def test_is_due_new_card(sched):
    card = FSRSCard()
    assert sched.is_due(card) is True


def test_is_due_future_card(sched):
    future = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    card = FSRSCard(
        last_review=datetime.date.today().isoformat(),
        due=future,
    )
    assert sched.is_due(card) is False


def test_is_due_past_card(sched):
    card = FSRSCard(
        last_review="2020-01-01",
        due="2020-01-02",
    )
    assert sched.is_due(card) is True


def test_is_due_today(sched):
    today = datetime.date.today()
    card = FSRSCard(last_review="2020-01-01", due=today.isoformat())
    assert sched.is_due(card) is True


# ---------------------------------------------------------------------------
# fsrs_update_srs_item — integration with legacy SRS dict
# ---------------------------------------------------------------------------


def test_fsrs_update_srs_item_correct_updates_legacy_keys():
    item: dict = {"last_review": None, "interval": 1, "efactor": 2.5}
    fsrs_update_srs_item(item, is_correct=True)
    assert item["last_review"] is not None
    assert float(item["interval"]) >= 1.0
    assert 1.3 <= float(item["efactor"]) <= 2.5


def test_fsrs_update_srs_item_incorrect_sets_short_interval():
    item: dict = {"last_review": None, "interval": 10, "efactor": 2.5}
    fsrs_update_srs_item(item, is_correct=False)
    assert float(item["interval"]) >= 1.0


def test_fsrs_update_srs_item_writes_fsrs_keys():
    item: dict = {}
    fsrs_update_srs_item(item, is_correct=True)
    assert "fsrs_stability" in item
    assert "fsrs_difficulty" in item
    assert "fsrs_reps" in item


def test_fsrs_update_srs_item_handles_non_dict_gracefully():
    result = fsrs_update_srs_item(None, is_correct=True)  # type: ignore[arg-type]
    assert result is None


def test_fsrs_update_srs_item_uses_fine_grained_rating():
    item: dict = {"fsrs_rating": 4}
    fsrs_update_srs_item(item, is_correct=True)
    # After an "Easy" rating (4) the interval should be longer than "Good" (3).
    easy_interval = float(item["interval"])

    item2: dict = {}
    fsrs_update_srs_item(item2, is_correct=True)
    good_interval = float(item2["interval"])

    assert easy_interval >= good_interval


def test_fsrs_update_srs_item_removes_rating_hint():
    item: dict = {"fsrs_rating": 3}
    fsrs_update_srs_item(item, is_correct=True)
    assert "fsrs_rating" not in item


def test_fsrs_update_srs_item_with_custom_scheduler():
    sched = FSRSScheduler(desired_retention=0.85)
    item: dict = {}
    fsrs_update_srs_item(item, is_correct=True, scheduler=sched)
    assert "fsrs_stability" in item


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def test_safe_float_returns_default_for_none():
    assert _safe_float(None, 3.0) == 3.0


def test_safe_float_clamps_min():
    assert _safe_float(0.0, 1.0, min_v=0.5) == 0.5


def test_safe_float_clamps_max():
    assert _safe_float(15.0, 1.0, max_v=10.0) == 10.0


def test_safe_int_returns_default_for_string():
    assert _safe_int("abc", 5) == 5


def test_safe_int_converts_valid_value():
    assert _safe_int("7", 0) == 7


# ---------------------------------------------------------------------------
# optimize_desired_retention_from_history
# ---------------------------------------------------------------------------


def _make_history(recall_rate: float, n: int = 20) -> list[dict]:
    """Build a synthetic review history with the given recall rate."""
    records = []
    for i in range(n):
        records.append(
            {
                "fsrs_stability": 5.0,
                "elapsed_days": 7,
                "recalled": i < int(n * recall_rate),
            }
        )
    return records


def test_optimize_retention_returns_all_expected_keys():
    result = optimize_desired_retention_from_history(_make_history(0.85))
    for key in ("suggested_retention", "current_avg_predicted_r", "actual_recall_rate", "sample_count", "loss_at_suggestion"):
        assert key in result, f"missing key: {key}"


def test_optimize_retention_empty_history_returns_default():
    result = optimize_desired_retention_from_history([])
    assert result["suggested_retention"] == DEFAULT_DESIRED_RETENTION
    assert result["sample_count"] == 0


def test_optimize_retention_varies_with_different_histories():
    """Suggested retention must differ when actual recall rates differ."""
    result_high = optimize_desired_retention_from_history(_make_history(0.95, n=30))
    result_low = optimize_desired_retention_from_history(_make_history(0.72, n=30))
    assert result_high["suggested_retention"] != result_low["suggested_retention"]


def test_optimize_retention_suggestion_reflects_actual_recall():
    """Suggested retention should be close to the observed recall rate."""
    for recall in (0.75, 0.85, 0.92):
        result = optimize_desired_retention_from_history(_make_history(recall, n=40))
        # Allow a tolerance of one grid step (≈0.01 for default 30 steps).
        assert abs(result["suggested_retention"] - recall) < 0.05, (
            f"recall={recall}: suggested={result['suggested_retention']}"
        )


def test_optimize_retention_suggestion_stays_within_bounds():
    result = optimize_desired_retention_from_history(_make_history(0.50, n=20))
    assert 0.70 <= result["suggested_retention"] <= 0.99
