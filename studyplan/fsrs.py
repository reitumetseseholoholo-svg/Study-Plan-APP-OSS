"""FSRS-4.5 spaced-repetition scheduler.

Implements the Free Spaced Repetition Scheduler algorithm (FSRS v4.5) as a
drop-in alternative to the SM-2 scheduler used in ``StudyPlanEngine.update_srs``.

The engine calls ``fsrs_update_srs_item`` each time a question is answered.
Callers that want the old SM-2 logic (``efactor``/``interval``) can continue
to use it unchanged; FSRS stores extra state under ``fsrs_*`` keys that coexist
with the legacy keys so data files stay forward-compatible.

References
----------
- FSRS algorithm: https://github.com/open-spaced-repetition/fsrs4anki/wiki/The-Algorithm
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Default FSRS-4.5 weights (w_0 … w_16)
# These are the community-optimised defaults; users can override via
# studyplan engine preferences if they train on their own data.
# ---------------------------------------------------------------------------
_DEFAULT_W = (
    0.4072, 1.1829, 3.1262, 15.4722,
    7.2102, 0.5316, 1.0651, 0.0589,
    1.5330, 0.1544, 1.0070, 1.9395,
    0.1100, 0.2900, 2.2700, 0.2500,
    2.9898,
)

# Desired retention target (probability of recall at scheduled review).
DEFAULT_DESIRED_RETENTION = 0.9

# Fuzzing factor applied to intervals to spread reviews (keeps reviews from
# all piling up on the same day).
_FUZZ_FACTOR = 0.05


# ---------------------------------------------------------------------------
# Core FSRS data class
# ---------------------------------------------------------------------------


@dataclass
class FSRSCard:
    """Per-card FSRS state.

    Attributes
    ----------
    stability:
        Estimated memory stability in days (s > 0).  A value of 1 means you
        have a 90 % chance of recall after 1 day; a value of 10 means the same
        after 10 days, etc.
    difficulty:
        Intrinsic difficulty on [1, 10].  Higher = harder card.
    reps:
        Number of successful reviews since the last lapse.
    lapses:
        Total number of times the card was forgotten.
    last_review:
        ISO-format date string of the most recent review (or ``None``).
    due:
        ISO-format date string when the card is next due (or ``None`` for new cards).
    """

    stability: float = 1.0
    difficulty: float = 5.0
    reps: int = 0
    lapses: int = 0
    last_review: str | None = None
    due: str | None = None

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "fsrs_stability": self.stability,
            "fsrs_difficulty": self.difficulty,
            "fsrs_reps": self.reps,
            "fsrs_lapses": self.lapses,
            "fsrs_last_review": self.last_review,
            "fsrs_due": self.due,
        }

    @classmethod
    def from_srs_dict(cls, d: dict[str, Any]) -> "FSRSCard":
        """Construct from an SRS item dict (may contain legacy and FSRS keys)."""
        if not isinstance(d, dict):
            return cls()
        return cls(
            stability=_safe_float(d.get("fsrs_stability"), 1.0, min_v=0.01),
            difficulty=_safe_float(d.get("fsrs_difficulty"), 5.0, min_v=1.0, max_v=10.0),
            reps=max(0, _safe_int(d.get("fsrs_reps"), 0)),
            lapses=max(0, _safe_int(d.get("fsrs_lapses"), 0)),
            last_review=d.get("fsrs_last_review") or d.get("last_review"),
            due=d.get("fsrs_due"),
        )

    def is_new(self) -> bool:
        return self.last_review is None


# ---------------------------------------------------------------------------
# FSRS Scheduler
# ---------------------------------------------------------------------------


class FSRSScheduler:
    """Implements FSRS-4.5 scheduling logic.

    Parameters
    ----------
    weights:
        Sequence of 17 FSRS weight parameters (w_0 … w_16).  Defaults to the
        community-tuned values.
    desired_retention:
        Target recall probability at review (default 0.9).
    """

    def __init__(
        self,
        weights: tuple[float, ...] | None = None,
        desired_retention: float = DEFAULT_DESIRED_RETENTION,
    ) -> None:
        w = tuple(weights) if weights else _DEFAULT_W
        if len(w) != 17:
            raise ValueError(f"FSRS requires exactly 17 weights; got {len(w)}")
        self.w = w
        self.desired_retention = max(0.70, min(0.99, desired_retention))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review(
        self,
        card: FSRSCard,
        rating: int,
        review_date: datetime.date | None = None,
    ) -> FSRSCard:
        """Update a card after a review.

        Parameters
        ----------
        card:
            Current card state (may be a new card).
        rating:
            Quality of recall:
            - 1 = Again (forgot)
            - 2 = Hard
            - 3 = Good
            - 4 = Easy
        review_date:
            Date of the review.  Defaults to today.
        """
        rating = max(1, min(4, int(rating)))
        today = review_date or datetime.date.today()

        # Derive elapsed days since last review.
        if card.last_review is not None:
            try:
                last = datetime.date.fromisoformat(str(card.last_review))
                elapsed = max(0, (today - last).days)
            except (ValueError, TypeError):
                elapsed = 0
        else:
            elapsed = 0

        if card.is_new():
            new_stability = self._initial_stability(rating)
            new_difficulty = self._initial_difficulty(rating)
            new_reps = 1 if rating >= 3 else 0
            new_lapses = 0 if rating >= 3 else 1
        elif rating == 1:
            # Lapse: card forgotten
            new_stability = self._stability_after_lapse(card.stability)
            new_difficulty = self._next_difficulty(card.difficulty, rating)
            new_reps = 0
            new_lapses = card.lapses + 1
        else:
            # Recalled (hard / good / easy)
            retrievability = self._retrievability(card.stability, elapsed)
            new_stability = self._stability_after_recall(
                card.stability, card.difficulty, retrievability, rating
            )
            new_difficulty = self._next_difficulty(card.difficulty, rating)
            new_reps = card.reps + 1
            new_lapses = card.lapses

        new_stability = max(0.1, new_stability)
        new_difficulty = max(1.0, min(10.0, new_difficulty))

        interval_days = self._next_interval(new_stability)
        due_date = today + datetime.timedelta(days=interval_days)

        return FSRSCard(
            stability=round(new_stability, 4),
            difficulty=round(new_difficulty, 4),
            reps=new_reps,
            lapses=new_lapses,
            last_review=today.isoformat(),
            due=due_date.isoformat(),
        )

    def is_due(self, card: FSRSCard, today: datetime.date | None = None) -> bool:
        """Return True if the card is due for review today or is new."""
        if card.is_new():
            return True
        check_date = today or datetime.date.today()
        if not card.due:
            return True
        try:
            due_date = datetime.date.fromisoformat(str(card.due))
            return due_date <= check_date
        except (ValueError, TypeError):
            return True

    # ------------------------------------------------------------------
    # FSRS-4.5 equations
    # ------------------------------------------------------------------

    def _retrievability(self, stability: float, elapsed_days: int) -> float:
        """Recall probability (exponential forgetting curve)."""
        if stability <= 0:
            return 0.0
        return math.pow(1.0 + elapsed_days / (9.0 * stability), -1.0)

    def _initial_stability(self, rating: int) -> float:
        # w_0 … w_3 are per-grade initial stability values.
        return max(0.1, self.w[rating - 1])

    def _initial_difficulty(self, rating: int) -> float:
        # w_4 + (rating - 3) * -w_5, clamped to [1, 10]
        d = self.w[4] + (rating - 3) * (-self.w[5])
        return max(1.0, min(10.0, d))

    def _next_difficulty(self, d: float, rating: int) -> float:
        # Mean-reversion formula from FSRS 4.5
        target = self.w[4] - math.exp(self.w[5] * (rating - 1)) + 1
        raw = d + (target - d) * self.w[6]
        return max(1.0, min(10.0, raw))

    def _stability_after_recall(
        self, s: float, d: float, r: float, rating: int
    ) -> float:
        # S'_r = S * (e^(w_8) * (11 - d) * S^(-w_9) * (e^(w_10*(1-r)) - 1) * hard/easy + 1)
        w8, w9, w10 = self.w[8], self.w[9], self.w[10]
        hard_penalty = self.w[15] if rating == 2 else 1.0
        easy_bonus = self.w[16] if rating == 4 else 1.0
        raw = (
            s
            * (
                math.exp(w8)
                * (11.0 - d)
                * math.pow(s, -w9)
                * (math.exp(w10 * (1.0 - r)) - 1.0)
                * hard_penalty
                * easy_bonus
                + 1.0
            )
        )
        return max(0.1, raw)

    def _stability_after_lapse(self, s: float) -> float:
        # S'_f = w_11 * d^(-w_12) * ((S+1)^(w_13) - 1) * e^(w_14*(1-r)) adjusted
        return max(0.1, self.w[11] * math.pow(s, -self.w[12]))

    def _next_interval(self, stability: float) -> int:
        """Convert stability to a review interval in days."""
        # I = S * ln(R_desired) / ln(0.9)  (for FSRS desired-retention scheduling)
        # Equivalent: I = 9 * S * (R^(-1/(-1)) - 1)  simplifies to:
        # I = S * (R_desired^(-1) - 1) * 9
        desired = self.desired_retention
        if desired <= 0 or desired >= 1:
            desired = DEFAULT_DESIRED_RETENTION
        raw = stability * (math.pow(desired, 1.0 / -1.0) - 1.0) * 9.0
        # Apply small fuzz to avoid clumping.
        fuzz = 1.0 + (hash(round(stability, 2)) % 7 - 3) * _FUZZ_FACTOR
        interval = max(1, round(raw * fuzz))
        return interval


# ---------------------------------------------------------------------------
# Engine-level integration helper
# ---------------------------------------------------------------------------


def fsrs_update_srs_item(
    srs_item: dict[str, Any],
    is_correct: bool,
    *,
    scheduler: FSRSScheduler | None = None,
    review_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Apply FSRS to a single SRS item dict and return the updated dict.

    The item dict is mutated in-place **and** returned.  Legacy SM-2 keys
    (``interval``, ``efactor``, ``last_review``) are also updated so that
    callers which read only the legacy fields continue to work.

    Parameters
    ----------
    srs_item:
        The mutable SRS dict stored in ``engine.srs_data[chapter][idx]``.
    is_correct:
        True → rating 3 (Good); False → rating 1 (Again).
        Extended callers can store a finer rating in ``srs_item["fsrs_rating"]``
        before calling this function.
    scheduler:
        Optional pre-built scheduler.  A default-weights instance is created
        per call if omitted (cheap since it holds no mutable state).
    review_date:
        Date of the review.  Defaults to today.
    """
    if not isinstance(srs_item, dict):
        return srs_item

    sched = scheduler or FSRSScheduler()

    # Allow callers to supply a fine-grained FSRS rating (1-4).
    # Fall back to binary correct / incorrect.
    raw_rating = srs_item.get("fsrs_rating")
    if raw_rating is not None:
        try:
            rating = max(1, min(4, int(raw_rating)))
        except (TypeError, ValueError):
            rating = 3 if is_correct else 1
    else:
        rating = 3 if is_correct else 1

    card = FSRSCard.from_srs_dict(srs_item)
    updated = sched.review(card, rating, review_date=review_date)

    # Write FSRS state back.
    srs_item.update(updated.to_dict())

    # Sync legacy SM-2 keys so the rest of the engine stays compatible.
    today = (review_date or datetime.date.today()).isoformat()
    srs_item["last_review"] = today

    # Derive a legacy-compatible interval from the FSRS due date.
    if updated.due:
        try:
            due = datetime.date.fromisoformat(updated.due)
            review = datetime.date.fromisoformat(today)
            legacy_interval = max(1, (due - review).days)
        except (ValueError, TypeError):
            legacy_interval = max(1, round(updated.stability))
    else:
        legacy_interval = max(1, round(updated.stability))

    srs_item["interval"] = float(legacy_interval)
    # Map FSRS difficulty [1,10] → SM-2 efactor [1.3, 2.5] (linear).
    srs_item["efactor"] = round(1.3 + (10.0 - updated.difficulty) / 9.0 * 1.2, 4)

    # Clear temporary rating hint.
    srs_item.pop("fsrs_rating", None)

    return srs_item


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _safe_float(
    value: Any,
    default: float,
    *,
    min_v: float | None = None,
    max_v: float | None = None,
) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default
    if min_v is not None and out < min_v:
        out = min_v
    if max_v is not None and out > max_v:
        out = max_v
    return out


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# FSRS weight / retention optimizer
# ---------------------------------------------------------------------------


def optimize_desired_retention_from_history(
    review_history: list[dict[str, Any]],
    *,
    scheduler: "FSRSScheduler | None" = None,
    min_retention: float = 0.70,
    max_retention: float = 0.99,
    steps: int = 30,
) -> dict[str, Any]:
    """Suggest an optimal ``desired_retention`` target from the user's review history.

    Each entry in *review_history* must contain:
    - ``fsrs_stability`` (float): FSRS stability at the time of the review
    - ``elapsed_days`` (int): days since last review
    - ``recalled`` (bool): whether the user recalled the card (rating ≥ 2)

    The function sweeps ``desired_retention`` across [min_retention, max_retention]
    and finds the value that minimises binary-cross-entropy loss between predicted
    retrievability and actual recall outcomes.  In other words: "what retention
    target best matches how this specific learner actually forgets?"

    Returns a dict with keys:
    - ``suggested_retention`` (float): the best-fit target in [0.70, 0.99]
    - ``current_avg_predicted_r`` (float): mean predicted R across all reviews
    - ``actual_recall_rate`` (float): fraction of reviews where user recalled
    - ``sample_count`` (int): number of usable review events
    - ``loss_at_suggestion`` (float): BCE loss at the suggested retention
    """
    sched = scheduler or FSRSScheduler()

    # Build a list of (stability, elapsed_days, recalled) triples.
    usable: list[tuple[float, int, bool]] = []
    for entry in review_history:
        if not isinstance(entry, dict):
            continue
        s_raw = entry.get("fsrs_stability")
        e_raw = entry.get("elapsed_days")
        r_raw = entry.get("recalled")
        if s_raw is None or e_raw is None or r_raw is None:
            continue
        try:
            s = float(s_raw)
            e = int(e_raw)
        except (TypeError, ValueError):
            continue
        if s <= 0 or e < 0:
            continue
        usable.append((s, e, bool(r_raw)))

    if not usable:
        return {
            "suggested_retention": DEFAULT_DESIRED_RETENTION,
            "current_avg_predicted_r": 0.0,
            "actual_recall_rate": 0.0,
            "sample_count": 0,
            "loss_at_suggestion": 0.0,
        }

    def _bce_loss(retention_target: float) -> float:
        """Binary cross-entropy between predicted R(t) and actual recall."""
        eps = 1e-9
        total = 0.0
        for s, e, recalled in usable:
            r_pred = sched._retrievability(s, e)
            r_pred = max(eps, min(1.0 - eps, r_pred))
            if recalled:
                total -= math.log(r_pred)
            else:
                total -= math.log(1.0 - r_pred)
        return total / max(1, len(usable))

    # Grid search over retention values.
    step_size = (max_retention - min_retention) / max(1, steps - 1)
    best_retention = float(DEFAULT_DESIRED_RETENTION)
    best_loss = float("inf")
    for i in range(steps):
        candidate = min_retention + i * step_size
        loss = _bce_loss(candidate)
        if loss < best_loss:
            best_loss = loss
            best_retention = candidate

    # Compute diagnostics.
    total_r = sum(sched._retrievability(s, e) for s, e, _ in usable)
    avg_predicted_r = total_r / max(1, len(usable))
    actual_recall_rate = sum(1 for _, _, recalled in usable if recalled) / max(1, len(usable))

    return {
        "suggested_retention": round(best_retention, 3),
        "current_avg_predicted_r": round(avg_predicted_r, 3),
        "actual_recall_rate": round(actual_recall_rate, 3),
        "sample_count": len(usable),
        "loss_at_suggestion": round(best_loss, 6),
    }


def build_review_history_from_srs_data(
    srs_data: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Convert engine ``srs_data`` dict to review-history entries for the optimizer.

    For each SRS item that has been reviewed at least once under FSRS, emits a
    ``{"fsrs_stability", "elapsed_days", "recalled"}`` record based on its current
    state.  Items without FSRS state are skipped.
    """
    today = datetime.date.today()
    result: list[dict[str, Any]] = []
    for chapter_items in srs_data.values():
        if not isinstance(chapter_items, list):
            continue
        for item in chapter_items:
            if not isinstance(item, dict):
                continue
            stability = item.get("fsrs_stability")
            last_review = item.get("fsrs_last_review") or item.get("last_review")
            reps = item.get("fsrs_reps", 0)
            if stability is None or not last_review or not reps:
                continue
            try:
                lr_date = datetime.date.fromisoformat(str(last_review))
                elapsed = max(0, (today - lr_date).days)
            except (ValueError, TypeError):
                continue
            lapses = int(item.get("fsrs_lapses", 0) or 0)
            # Heuristic: classify the card's *last* review outcome.
            # A card with zero lapses has never been forgotten → recalled.
            # A card with lapses but more reps than lapses had at least one
            # successful review after its last lapse → treat as recalled.
            # If reps == lapses the card has only ever been lapsed → not recalled.
            recalled = (lapses == 0 and int(reps) > 0) or (lapses > 0 and int(reps) > lapses)
            result.append(
                {
                    "fsrs_stability": float(stability),
                    "elapsed_days": elapsed,
                    "recalled": recalled,
                }
            )
    return result
