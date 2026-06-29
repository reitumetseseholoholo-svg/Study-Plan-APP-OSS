"""
Tests for coach pipeline caching and throttle improvements.

Covers:
- _get_pace_info perf_cache integration
- _get_must_review_due_count perf_cache integration
- _queue_coach_sync_if_mismatch time-based throttle
"""

from __future__ import annotations

import datetime
import time
import types

import pytest

try:
    from studyplan_app import StudyPlanGUI
except Exception as exc:  # pragma: no cover
    pytest.skip(f"studyplan_app import unavailable: {exc}", allow_module_level=True)


class _FakePerfCache:
    """Minimal perf_cache double — stores values with TTL but ignores expiry for test control."""

    def __init__(self):
        self._store: dict[str, object] = {}
        self._ttl: dict[str, float] = {}
        self.gets: list[str] = []
        self.sets: list[str] = []

    def get(self, key: str):
        self.gets.append(key)
        return self._store.get(key)

    def set(self, key: str, value: object, ttl_seconds: float = 300):
        self.sets.append(key)
        self._store[key] = value
        self._ttl[key] = ttl_seconds


# ── _get_pace_info caching ────────────────────────────────────────────


def _make_engine_with_pace(
    status: str = "on_track", required_avg: float = 30.0, current_avg: float = 35.0, delta: float = -5.0
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        get_pace_status=lambda: {
            "status": status,
            "days_remaining": 40,
            "required_avg": required_avg,
            "current_avg": current_avg,
            "delta": delta,
        },
        study_hub_stats={},
    )


def _make_pace_dummy(engine) -> types.SimpleNamespace:
    dummy = types.SimpleNamespace(
        engine=engine,
        _perf_cache=_FakePerfCache(),
        _get_retrieval_ratio_today=lambda: 0.45,
        _get_retrieval_min_pct=lambda: 0.30,
    )
    dummy._get_pace_info = types.MethodType(StudyPlanGUI._get_pace_info, dummy)
    return dummy


class TestGetPaceInfoCaching:
    def test_first_call_produces_valid_dict(self):
        eng = _make_engine_with_pace("behind")
        dummy = _make_pace_dummy(eng)
        result = dummy._get_pace_info()
        assert isinstance(result, dict)
        assert result.get("status") == "behind"
        assert "days_remaining" in result

    def test_second_call_uses_cache(self):
        eng = _make_engine_with_pace("ahead")
        dummy = _make_pace_dummy(eng)
        # Track how many times engine.get_pace_status is called
        call_count = 0

        def tracked_pace():
            nonlocal call_count
            call_count += 1
            return {"status": "ahead", "days_remaining": 40}

        eng.get_pace_status = tracked_pace
        _ = dummy._get_pace_info()
        assert call_count == 1
        _ = dummy._get_pace_info()
        # Second call should hit cache, not re-invoke engine
        assert call_count == 1

    def test_cache_returns_copy_not_reference(self):
        eng = _make_engine_with_pace("on_track")
        dummy = _make_pace_dummy(eng)
        first = dummy._get_pace_info()
        second = dummy._get_pace_info()
        # Mutating first should NOT affect second
        first["status"] = "mutated"
        assert second.get("status") == "on_track"
        assert first is not second

    def test_cache_served_after_miss(self):
        """First call = miss, second = hit."""
        eng = _make_engine_with_pace()
        dummy = _make_pace_dummy(eng)
        # Clear the fake cache to ensure a fresh miss
        cache = dummy._perf_cache
        cache._store.clear()
        cache.gets.clear()
        cache.sets.clear()

        _ = dummy._get_pace_info()
        assert "coach:pace_info" in cache.sets

        _ = dummy._get_pace_info()
        assert "coach:pace_info" in cache.gets
        # The second call should read from cache, not set again
        assert cache.sets.count("coach:pace_info") == 1

    def test_cache_miss_when_perf_cache_none(self):
        """Graceful fallback when _perf_cache is None."""
        dummy = types.SimpleNamespace(
            engine=_make_engine_with_pace("behind"),
            _perf_cache=None,
            _get_retrieval_ratio_today=lambda: 0.45,
            _get_retrieval_min_pct=lambda: 0.30,
        )
        dummy._get_pace_info = types.MethodType(StudyPlanGUI._get_pace_info, dummy)
        first = dummy._get_pace_info()
        assert first.get("status") == "behind"
        # No cache to hit, but should still work
        second = dummy._get_pace_info()
        assert second.get("status") == "behind"

    def test_cache_includes_retrieval_override(self):
        """Low retrieval ratio should produce 'behind' status even if pace says 'ahead'."""
        eng = _make_engine_with_pace("ahead")
        dummy = _make_pace_dummy(eng)
        dummy._get_retrieval_ratio_today = lambda: 0.15  # below min
        dummy._get_retrieval_min_pct = lambda: 0.30
        result = dummy._get_pace_info()
        assert result.get("status") == "behind"
        assert result.get("status_note") == "low_retrieval"


# ── _get_must_review_due_count caching ────────────────────────────────


def _make_must_review_dummy() -> types.SimpleNamespace:
    """Creates a dummy with stubbed engine and minimal must-review data."""
    engine = types.SimpleNamespace(
        CHAPTERS=["Ch A", "Ch B"],
        must_review={
            "Ch A": {"0": (datetime.date.today() - datetime.timedelta(days=1)).isoformat()},
            "Ch B": {},
        },
        _parse_date=lambda raw: datetime.date.fromisoformat(raw) if raw else None,
    )
    _topic_must_count_calls = [0]

    def _get_topic_must_review_due_count(topic: str, today=None):
        _topic_must_count_calls[0] += 1
        if today is None:
            today = datetime.date.today()
        try:
            items = engine.must_review.get(topic, {})
            count = 0
            for _idx_raw, due_raw in items.items():
                due_date = engine._parse_date(due_raw)
                if due_date and due_date <= today:
                    count += 1
            return count
        except Exception:
            return 0

    dummy = types.SimpleNamespace(
        engine=engine,
        _perf_cache=_FakePerfCache(),
        _get_topic_must_review_due_count=_get_topic_must_review_due_count,
    )
    dummy._get_must_review_due_count = types.MethodType(StudyPlanGUI._get_must_review_due_count, dummy)
    dummy._topic_must_count_calls = _topic_must_count_calls
    return dummy


class TestGetMustReviewDueCountCaching:
    def test_first_call_returns_correct_count(self):
        dummy = _make_must_review_dummy()
        result = dummy._get_must_review_due_count()
        assert result >= 1  # Ch A has a past-due item

    def test_second_call_uses_cache(self):
        dummy = _make_must_review_dummy()
        _ = dummy._get_must_review_due_count()
        calls_after_first = dummy._topic_must_count_calls[0]
        _ = dummy._get_must_review_due_count()
        # The internal helper should NOT be called again on second call
        assert dummy._topic_must_count_calls[0] == calls_after_first

    def test_cache_key_includes_date(self):
        """Verify cache key is date-anchored."""
        dummy = _make_must_review_dummy()
        cache = dummy._perf_cache
        _ = dummy._get_must_review_due_count()
        expected_prefix = f"coach:must_due:{datetime.date.today().isoformat()}"
        assert any(k.startswith("coach:must_due:") for k in cache.sets)
        assert any(k == expected_prefix for k in cache.sets)

    def test_exception_path_caches_zero(self):
        """When the engine access fails, cache stores 0."""
        dummy = _make_must_review_dummy()
        dummy.engine.CHAPTERS = None  # will cause iteration to fail
        cache = dummy._perf_cache
        result = dummy._get_must_review_due_count()
        assert result == 0
        expected_prefix = f"coach:must_due:{datetime.date.today().isoformat()}"
        assert any(k == expected_prefix for k in cache.sets)

    def test_graceful_when_perf_cache_none(self):
        """No crash when _perf_cache is None."""
        dummy = _make_must_review_dummy()
        dummy._perf_cache = None
        result = dummy._get_must_review_due_count()
        assert isinstance(result, int)


# ── _queue_coach_sync_if_mismatch throttle ────────────────────────────


class TestCoachSyncThrottle:
    @staticmethod
    def _make_sync_dummy() -> types.SimpleNamespace:
        dummy = types.SimpleNamespace(
            _coach_sync_in_progress=False,
            _last_coach_sync_request_time=0.0,
            _coach_pick_topic="Topic A",
            _last_study_room_coach_topic="Topic B",
            _last_dashboard_coach_topic="Topic B",
            _last_coach_sync_key="",
            _coach_sync_retry_count=0,
            _last_coach_sync_origin="",
            _run_coach_sync_after_mismatch=lambda origin="": None,
        )
        dummy._queue_coach_sync_if_mismatch = types.MethodType(StudyPlanGUI._queue_coach_sync_if_mismatch, dummy)
        return dummy

    def test_first_call_proceeds(self):
        dummy = self._make_sync_dummy()
        result = dummy._queue_coach_sync_if_mismatch("test")
        assert result is None  # no return value, but should not error
        assert dummy._last_coach_sync_request_time > 0

    def test_rapid_second_call_is_throttled(self):
        dummy = self._make_sync_dummy()
        # Set the guard timestamp to almost-now
        dummy._last_coach_sync_request_time = time.monotonic()
        # The _coach_sync_in_progress guard was already set by _make_sync_dummy being
        # freshly created, but we reset it to test the *time* throttle specifically.
        dummy._coach_sync_in_progress = False
        first_key_before = dummy._last_coach_sync_key
        dummy._queue_coach_sync_if_mismatch("test")
        # The sync key should still be empty — time guard prevented the mismatch
        # from being processed
        assert dummy._last_coach_sync_key == first_key_before
        # Timestamp should remain the manually-set value (not updated)
        assert dummy._last_coach_sync_request_time <= time.monotonic()

    def test_throttle_respects_time_window(self):
        """Call after 1+ seconds should proceed."""
        dummy = self._make_sync_dummy()
        # Simulate a call 2 seconds ago
        dummy._last_coach_sync_request_time = time.monotonic() - 2.0
        dummy._coach_sync_in_progress = False
        dummy._queue_coach_sync_if_mismatch("test")
        # Should have proceeded (not throttled)
        assert dummy._last_coach_sync_request_time > time.monotonic() - 1.0
        # Verify the sync was actually queued by checking retry count
        assert dummy._coach_sync_retry_count >= 1

    def test_no_throttle_when_topics_match(self):
        """When all three topics match, no sync is queued (no throttle needed)."""
        dummy = self._make_sync_dummy()
        # Make all topics match
        dummy._coach_pick_topic = "Topic A"
        dummy._last_study_room_coach_topic = "Topic A"
        dummy._last_dashboard_coach_topic = "Topic A"
        dummy._coach_sync_in_progress = False
        dummy._queue_coach_sync_if_mismatch("test")
        # Sync key should be empty (no mismatch detected)
        assert dummy._last_coach_sync_key == ""
        # Retry count should not have been incremented
        assert dummy._coach_sync_retry_count == 0
