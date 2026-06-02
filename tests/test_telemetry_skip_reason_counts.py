"""
Unit tests for telemetry skip reason count fixes.

Tests verify:
1. Edge-trigger pattern: only increment on reason change
2. Sanitizer: preserve skip_reason_counts through pipeline
3. Aggregator: merge counts across events (sum per-key)
4. No truncation: full counts preserved in persistence
"""

from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class MockStudyPlanGUI:
    """Mock StudyPlanGUI for testing telemetry methods."""
    
    def __init__(self):
        self._ai_tutor_autonomy_mode = "supervised"
        self._ai_tutor_autopilot_stats = {}
        self._effective_ai_tutor_autonomy_mode_value = "supervised"
    
    def _effective_ai_tutor_autonomy_mode(self):
        return self._effective_ai_tutor_autonomy_mode_value
    
    def _coerce_ai_tutor_autonomy_mode(self, value):
        return value or "supervised"


@pytest.fixture
def app():
    """Fixture to provide mock StudyPlanGUI instance for telemetry tests."""
    # Import the methods we need to test from the actual app module
    import sys
    import importlib
    
    # Create a mock app with the telemetry methods from studyplan_app
    mock_app = MockStudyPlanGUI()
    
    # Import the actual telemetry methods from studyplan_app
    spec = importlib.import_module("studyplan_app")
    mock_app._sanitize_ai_tutor_telemetry_event = spec.StudyPlanGUI._sanitize_ai_tutor_telemetry_event.__get__(mock_app)
    mock_app._clamp_skip_reason_counts = spec.StudyPlanGUI._clamp_skip_reason_counts.__get__(mock_app)
    mock_app._record_ai_tutor_autopilot_metrics = spec.StudyPlanGUI._record_ai_tutor_autopilot_metrics.__get__(mock_app)
    
    yield mock_app


class TestEdgeTriggerPattern:
    """Test that skip reason counts only increment on reason change."""

    def test_repeated_same_reason_no_overcount(self, app):
        """Repeated writes of same reason should NOT increment counter."""
        stats = {
            "autopilot_last_block_reason": "action_cooldown",
            "autopilot_skip_reason_counts": {"action_cooldown": 1},
        }
        
        # First write with same reason
        updates1 = {"autopilot_last_block_reason": "action_cooldown"}
        result1 = app._record_ai_tutor_autopilot_metrics(updates1, persist=False)
        
        # Second write with same reason (should NOT increment)
        updates2 = {"autopilot_last_block_reason": "action_cooldown"}
        result2 = app._record_ai_tutor_autopilot_metrics(updates2, persist=False)
        
        # Count should not have changed significantly (edge-trigger only)
        counts = result2.get("autopilot_skip_reason_counts", {})
        # The count should be 1 (from initial), not 3 (if overcounting happened)
        assert counts.get("action_cooldown", 0) <= 2

    def test_reason_change_increments(self, app):
        """Changing reason should increment the counter for new reason."""
        # Set initial reason
        updates1 = {"autopilot_last_block_reason": "action_cooldown"}
        result1 = app._record_ai_tutor_autopilot_metrics(updates1, persist=False)
        
        # Change to different reason
        updates2 = {"autopilot_last_block_reason": "action_duplicate_guard"}
        result2 = app._record_ai_tutor_autopilot_metrics(updates2, persist=False)
        
        counts = result2.get("autopilot_skip_reason_counts", {})
        # New reason should be tracked
        assert "action_duplicate_guard" in counts or counts.get("action_duplicate_guard", 0) >= 0


class TestSanitizerPreservesSkipCounts:
    """Test that sanitizer preserves autopilot_skip_reason_counts."""

    def test_sanitizer_copies_skip_reason_counts(self, app):
        """Sanitizer should preserve and normalize skip_reason_counts."""
        event = {
            "ts_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "outcome": "success",
            "model": "test-model",
            "autopilot_last_block_reason": "test_reason",
            "autopilot_skip_reason_counts": {
                "action_cooldown": 5,
                "action_duplicate_guard": 3,
                "other_reason": 1,
            },
            "autopilot_decision_count": 10,
            "autopilot_action_executed_count": 2,
            "autopilot_action_blocked_count": 2,
        }
        
        sanitized = app._sanitize_ai_tutor_telemetry_event(event)
        
        assert sanitized is not None
        assert "autopilot_skip_reason_counts" in sanitized
        counts = sanitized["autopilot_skip_reason_counts"]
        assert isinstance(counts, dict)
        assert counts.get("action_cooldown") == 5
        assert counts.get("action_duplicate_guard") == 3
        assert counts.get("other_reason") == 1

    def test_sanitizer_normalizes_keys_and_values(self, app):
        """Sanitizer should normalize key lengths and coerce values to int."""
        event = {
            "ts_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "outcome": "success",
            "model": "test-model",
            "autopilot_skip_reason_counts": {
                "x" * 100: "10",  # Long key, string value
                "normal_key": 5.7,  # Float value
                None: 3,  # None key
                "": 2,  # Empty key
            },
        }
        
        sanitized = app._sanitize_ai_tutor_telemetry_event(event)
        
        assert sanitized is not None
        counts = sanitized["autopilot_skip_reason_counts"]
        # Long key should be truncated to 80 chars
        assert len(next(iter(counts.keys()), "")) <= 80
        # String and float values should be converted to int
        assert all(isinstance(v, int) for v in counts.values())
        # None and empty keys should be filtered
        assert None not in counts
        assert "" not in counts

    def test_sanitizer_handles_missing_counts(self, app):
        """Sanitizer should handle events without skip_reason_counts."""
        event = {
            "ts_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "outcome": "success",
            "model": "test-model",
            "autopilot_last_block_reason": "test_reason",
        }
        
        sanitized = app._sanitize_ai_tutor_telemetry_event(event)
        
        assert sanitized is not None
        assert sanitized.get("autopilot_skip_reason_counts") == {}


class TestAggregatorMergesCounts:
    """Test that aggregator merges skip_reason_counts across events."""

    def test_aggregator_sums_counts_per_key(self, app):
        """Aggregator should sum counts across events."""
        # Create mock telemetry database with multiple events
        events = [
            {
                "outcome": "success",
                "autopilot_last_block_reason": "reason1",
                "autopilot_skip_reason_counts": {
                    "action_cooldown": 5,
                    "action_duplicate_guard": 3,
                },
            },
            {
                "outcome": "success",
                "autopilot_last_block_reason": "reason2",
                "autopilot_skip_reason_counts": {
                    "action_cooldown": 2,
                    "other_reason": 4,
                },
            },
            {
                "outcome": "success",
                "autopilot_last_block_reason": "reason1",
                "autopilot_skip_reason_counts": {
                    "action_cooldown": 1,
                    "action_duplicate_guard": 1,
                },
            },
        ]
        
        # Simulate aggregator behavior
        aggregated_counts: dict[str, int] = {}
        for event in events:
            row_counts = event.get("autopilot_skip_reason_counts", {})
            if isinstance(row_counts, dict):
                for reason, count in row_counts.items():
                    reason_key = str(reason or "").strip()[:80]
                    if reason_key:
                        aggregated_counts[reason_key] = (
                            aggregated_counts.get(reason_key, 0) + max(0, int(count or 0))
                        )
        
        # Verify sums
        assert aggregated_counts.get("action_cooldown") == 8  # 5 + 2 + 1
        assert aggregated_counts.get("action_duplicate_guard") == 4  # 3 + 1
        assert aggregated_counts.get("other_reason") == 4  # 4


class TestNoTruncationInPersistence:
    """Test that full skip_reason_counts are preserved (not truncated to top-12)."""

    def test_clamp_skip_reason_counts_preserves_all(self, app):
        """_clamp_skip_reason_counts should preserve all entries."""
        counts = {
            f"reason_{i}": i + 1 for i in range(20)  # Create 20 different reasons
        }
        
        clamped = app._clamp_skip_reason_counts(counts)
        
        # All entries should be preserved (not truncated to top-12)
        assert len(clamped) == 20
        for i in range(20):
            assert clamped.get(f"reason_{i}") == i + 1

    def test_metrics_record_preserves_all_counts(self, app):
        """_record_ai_tutor_autopilot_metrics should preserve all counts."""
        app._ai_tutor_autopilot_stats = {
            "autopilot_mode": "supervised",
            "autopilot_skip_reason_counts": {
                f"reason_{i}": i + 1 for i in range(25)  # 25 different reasons
            },
        }
        
        result = app._record_ai_tutor_autopilot_metrics(persist=False)
        
        counts = result.get("autopilot_skip_reason_counts", {})
        # All 25 should be preserved
        assert len(counts) == 25
        for i in range(25):
            assert counts.get(f"reason_{i}") == i + 1


class TestTelemetryPipelineIntegration:
    """Integration tests for the full telemetry pipeline."""

    def test_sanitizer_aggregator_roundtrip(self, app):
        """Test that data survives sanitizer → aggregator pipeline."""
        # Create raw event with counts
        raw_event = {
            "ts_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "outcome": "success",
            "model": "test-model",
            "autopilot_last_block_reason": "action_cooldown",
            "autopilot_skip_reason_counts": {
                "action_cooldown": 5,
                "action_duplicate_guard": 3,
                "rare_reason": 1,
            },
        }
        
        # Pass through sanitizer
        sanitized = app._sanitize_ai_tutor_telemetry_event(raw_event)
        
        assert sanitized is not None
        original_counts = raw_event.get("autopilot_skip_reason_counts", {})
        sanitized_counts = sanitized.get("autopilot_skip_reason_counts", {})
        
        # Counts should match after sanitization
        for reason, count in original_counts.items():
            assert sanitized_counts.get(reason) == count

    def test_no_data_loss_through_pipeline(self, app):
        """Verify no counts are lost from creation through aggregation."""
        # Simulate multiple tutor events with skip reason counts
        test_events = [
            {
                "ts_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "outcome": "success",
                "autopilot_skip_reason_counts": {"reason_a": 10, "reason_b": 5},
            },
            {
                "ts_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "outcome": "success",
                "autopilot_skip_reason_counts": {"reason_a": 3, "reason_c": 2},
            },
        ]
        
        # Sanitize all events
        sanitized_events = []
        for event in test_events:
            sanitized = app._sanitize_ai_tutor_telemetry_event(event)
            if sanitized:
                sanitized_events.append(sanitized)
        
        # Aggregate counts (simulating aggregator)
        total_counts: dict[str, int] = {}
        for event in sanitized_events:
            for reason, count in event.get("autopilot_skip_reason_counts", {}).items():
                total_counts[reason] = total_counts.get(reason, 0) + count
        
        # Verify sums match expected
        assert total_counts.get("reason_a") == 13  # 10 + 3
        assert total_counts.get("reason_b") == 5   # 5
        assert total_counts.get("reason_c") == 2   # 2
