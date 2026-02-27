from __future__ import annotations

import json

import pytest

from studyplan.infrastructure import ConfigManager, PerformanceMonitor, SecureImporter


def test_config_manager_defaults_and_overrides():
    defaults = ConfigManager(environ={}).load()
    assert defaults.cache_size == 500
    assert defaults.write_interval_seconds == 30
    assert defaults.enable_secure_imports is True

    cfg = ConfigManager(
        environ={
            "STUDYPLAN_CACHE_SIZE": "1200",
            "STUDYPLAN_WRITE_INTERVAL": "45",
            "STUDYPLAN_MAX_FILE_SIZE": "2097152",
            "STUDYPLAN_ALLOWED_EXTENSIONS": ".json,.csv,.txt",
            "STUDYPLAN_ENABLE_PERFORMANCE_MONITORING": "1",
            "STUDYPLAN_ENABLE_SECURE_IMPORTS": "0",
        }
    ).load()
    assert cfg.cache_size == 1200
    assert cfg.write_interval_seconds == 45
    assert cfg.max_file_size_bytes == 2 * 1024 * 1024
    assert ".txt" in cfg.allowed_extensions
    assert cfg.enable_performance_monitoring is True
    assert cfg.enable_secure_imports is False


def test_performance_monitor_track_and_snapshot():
    monitor = PerformanceMonitor(enabled=True, max_operations=32)
    with monitor.track("srs_update"):
        pass
    monitor.record("srs_update", 12.5, ok=False)
    snap = monitor.snapshot(limit=8)
    assert bool(snap.get("enabled", False)) is True
    ops = snap.get("operations", {})
    assert isinstance(ops, dict) and "srs_update" in ops
    row = ops["srs_update"]
    assert int(row.get("count", 0) or 0) >= 2
    assert int(row.get("error_count", 0) or 0) >= 1


def test_secure_importer_path_and_size_guards(tmp_path):
    importer = SecureImporter(max_file_size_bytes=1024, allowed_extensions=(".json", ".csv"))
    good = tmp_path / "payload.json"
    good.write_text(json.dumps({"ok": True}), encoding="utf-8")
    normalized = importer.validate_file_path(str(good), allowed_extensions=(".json",))
    assert normalized.endswith("payload.json")
    payload = importer.load_json(str(good))
    assert payload == {"ok": True}

    bad_ext = tmp_path / "notes.txt"
    bad_ext.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        importer.validate_file_path(str(bad_ext), allowed_extensions=(".json",))

    large = tmp_path / "large.json"
    large.write_text("x" * 2048, encoding="utf-8")
    with pytest.raises(ValueError):
        importer.enforce_file_size(str(large))

