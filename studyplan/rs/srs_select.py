from __future__ import annotations

import math

_HAS_RUST: bool = False
_rs_select_srs = None
_rs_batch_score = None

try:
    from studyplan_rs import select_srs_from_scored as _rs_select_srs  # type: ignore
    from studyplan_rs import batch_score_srs as _rs_batch_score  # type: ignore

    _HAS_RUST = True
except ImportError:
    pass


def select_srs_from_scored(
    scored: list[tuple[int, int, int, int, int, int, float, float, float]],
    count: int,
    n_questions: int,
    recent_set: list[int],
) -> list[int]:
    """Select SRS question indices from scored items.

    Uses Rust acceleration if available, pure-Python fallback otherwise.
    """
    if _HAS_RUST and _rs_select_srs is not None:
        idxs: list[int] = []
        due: list[int] = []
        overdue: list[int] = []
        in_cooldown: list[int] = []
        recent: list[int] = []
        is_new: list[int] = []
        retention: list[float] = []
        risk: list[float] = []
        gap_bonus: list[float] = []
        for item in scored:
            idxs.append(item[0])
            due.append(item[1])
            overdue.append(item[2])
            in_cooldown.append(item[3])
            recent.append(item[4])
            is_new.append(item[5])
            retention.append(item[6])
            risk.append(item[7])
            gap_bonus.append(item[8])
        return _rs_select_srs(
            idxs,
            due,
            overdue,
            in_cooldown,
            recent,
            is_new,
            retention,
            risk,
            gap_bonus,
            count,
            n_questions,
            recent_set,
        )
    return _select_srs_from_scored_py(scored, count, n_questions, recent_set)


def _select_srs_from_scored_py(
    scored: list[tuple[int, int, int, int, int, int, float, float, float]],
    count: int,
    n_questions: int,
    recent_set: list[int],
) -> list[int]:
    """Pure-Python fallback for SRS question selection."""
    target = min(count, n_questions)
    if target <= 0:
        return []

    recent_lookup = set(recent_set)

    # Phase 1: due items first
    due_items = [item for item in scored if item[1] == 1]
    due_items.sort(key=lambda x: (x[3], -x[2], -x[8], -x[7], x[6]))
    max_due = min(target, max(3, int(count * 0.5)))
    selected = [idx for idx, *_rest in due_items[:max_due]]
    due_count = len(due_items)

    # Phase 2: fill from non-cooldown pool
    if len(selected) < target:
        remaining = target - len(selected)
        non_due = [item for item in scored if item[1] == 0 and item[0] not in selected]
        non_cooldown = [item for item in non_due if item[3] == 0]
        non_cooldown.sort(key=lambda x: (-x[2], -x[8], -x[7], -x[5], x[4], x[6]))
        selected.extend([idx for idx, *_rest in non_cooldown[:remaining]])

    # Phase 3: fallback to cooldown items
    if len(selected) < target:
        remaining = target - len(selected)
        fallback = [item for item in scored if item[0] not in selected]
        fallback.sort(key=lambda x: (-x[1], -x[2], -x[8], -x[7], x[4], x[6]))
        selected.extend([idx for idx, *_rest in fallback[:remaining]])

    # Phase 4: diversity enforcement
    _enforce_diversity(selected, scored, due_count, target, recent_lookup)

    return selected


def batch_score_srs(
    has_fsrs_due: list[int],
    fsrs_due_days_since: list[int],
    has_last_review: list[int],
    days_since_review: list[int],
    sm2_interval: list[float],
    has_fsrs_stability: list[int],
    fsrs_stability: list[float],
) -> tuple[list[int], list[float]]:
    """Batch-compute is_overdue and retention_probability for SRS items.

    Uses Rust acceleration if available, pure-Python fallback otherwise.
    """
    if _HAS_RUST and _rs_batch_score is not None:
        return _rs_batch_score(
            has_fsrs_due,
            fsrs_due_days_since,
            has_last_review,
            days_since_review,
            sm2_interval,
            has_fsrs_stability,
            fsrs_stability,
        )
    return _batch_score_srs_py(
        has_fsrs_due,
        fsrs_due_days_since,
        has_last_review,
        days_since_review,
        sm2_interval,
        has_fsrs_stability,
        fsrs_stability,
    )


def _batch_score_srs_py(
    has_fsrs_due: list[int],
    fsrs_due_days_since: list[int],
    has_last_review: list[int],
    days_since_review: list[int],
    sm2_interval: list[float],
    has_fsrs_stability: list[int],
    fsrs_stability: list[float],
) -> tuple[list[int], list[float]]:
    """Pure-Python fallback for batch SRS scoring."""
    n = len(has_fsrs_due)
    overdue = [0] * n
    retention = [0.0] * n
    for i in range(n):
        # is_overdue
        if has_fsrs_due[i] and fsrs_due_days_since[i] >= 0:
            overdue[i] = 1
        elif has_last_review[i]:
            interval = max(1.0, sm2_interval[i])
            overdue[i] = 1 if days_since_review[i] >= interval else 0
        # retention_probability
        if has_last_review[i] and days_since_review[i] >= 0:
            ds = float(days_since_review[i])
            if has_fsrs_stability[i] and fsrs_stability[i] > 0.0:
                s = max(0.1, fsrs_stability[i])
                retention[i] = math.pow(0.9, ds / s)
            else:
                interval = max(1.0, sm2_interval[i])
                retention[i] = math.pow(0.9, ds / interval)
    return overdue, retention


def _enforce_diversity(
    selected: list[int],
    scored: list[tuple[int, int, int, int, int, int, float, float, float]],
    due_count: int,
    target: int,
    recent_lookup: set[int],
) -> None:
    """Ensure minimum non-recent ratio unless due pressure is high."""
    if not recent_lookup or target <= 0:
        return
    min_non_recent = int(math.ceil(target * 0.70))
    due_pressure = due_count >= max(1, int(math.ceil(target * 0.60)))
    if due_pressure:
        return
    non_recent_selected = [idx for idx in selected if idx not in recent_lookup]
    if len(non_recent_selected) >= min_non_recent:
        return
    needed = min_non_recent - len(non_recent_selected)
    candidates = [item for item in scored if item[0] not in selected and item[4] == 0]
    candidates.sort(key=lambda x: (-x[1], -x[2], -x[8], -x[7], x[6]))
    additions = [idx for idx, *_rest in candidates[:needed]]
    if not additions:
        return
    due_by_idx = {idx: due for idx, due, *_rest in scored}
    replaceable = [idx for idx in selected if idx in recent_lookup and due_by_idx.get(idx, 0) == 0]
    for add_idx in additions:
        if not replaceable:
            break
        old_idx = replaceable.pop(0)
        try:
            pos = selected.index(old_idx)
        except ValueError:
            continue
        selected[pos] = add_idx
