"""Tests for studyplan.json_safety module."""
import json
import os

import pytest

from studyplan.json_safety import load_json_file_with_limit, quarantine_corrupt_file


# ---------------------------------------------------------------------------
# quarantine_corrupt_file
# ---------------------------------------------------------------------------


def test_quarantine_returns_none_for_empty_path():
    assert quarantine_corrupt_file("") is None


def test_quarantine_returns_none_for_nonexistent_file(tmp_path):
    assert quarantine_corrupt_file(str(tmp_path / "ghost.json")) is None


def test_quarantine_renames_existing_file(tmp_path):
    target = tmp_path / "data.json"
    target.write_text("{}")
    new_path = quarantine_corrupt_file(str(target))
    assert new_path is not None
    assert not target.exists()
    assert os.path.exists(new_path)


def test_quarantine_suffix_included_in_new_name(tmp_path):
    target = tmp_path / "data.json"
    target.write_text("{}")
    new_path = quarantine_corrupt_file(str(target), suffix="json")
    assert new_path is not None
    assert new_path.endswith(".json")


def test_quarantine_no_suffix_still_works(tmp_path):
    target = tmp_path / "data.json"
    target.write_text("{}")
    new_path = quarantine_corrupt_file(str(target), suffix=None)
    assert new_path is not None
    assert os.path.exists(new_path)


def test_quarantine_returns_none_for_non_string_path():
    assert quarantine_corrupt_file(None) is None  # type: ignore[arg-type]


def test_quarantine_returns_none_for_whitespace_path():
    assert quarantine_corrupt_file("   ") is None


# ---------------------------------------------------------------------------
# load_json_file_with_limit
# ---------------------------------------------------------------------------


def test_load_json_file_valid(tmp_path):
    f = tmp_path / "good.json"
    payload = {"key": "value", "number": 42}
    f.write_text(json.dumps(payload), encoding="utf-8")
    result = load_json_file_with_limit(str(f), max_bytes=1024, label="test")
    assert result == payload


def test_load_json_file_list(tmp_path):
    f = tmp_path / "list.json"
    f.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = load_json_file_with_limit(str(f), max_bytes=1024, label="list_test")
    assert result == [1, 2, 3]


def test_load_json_file_raises_value_error_on_corrupt_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{ not valid json }", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        load_json_file_with_limit(str(f), max_bytes=1024, label="bad_test")


def test_load_json_file_quarantines_corrupt_by_default(tmp_path):
    f = tmp_path / "corrupt.json"
    f.write_text("{ bad", encoding="utf-8")
    with pytest.raises(ValueError, match="Quarantined"):
        load_json_file_with_limit(str(f), max_bytes=1024, label="qtest")
    # Original file should no longer exist after quarantine
    assert not f.exists()


def test_load_json_file_no_quarantine_on_corrupt(tmp_path):
    f = tmp_path / "corrupt_no_q.json"
    f.write_text("{ bad", encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_json_file_with_limit(str(f), max_bytes=1024, label="nqtest", quarantine_corrupt=False)
    # Without quarantine, message should NOT mention quarantine path
    assert "Quarantined" not in str(exc_info.value)
    # Original file still present since we didn't quarantine
    assert f.exists()


def test_load_json_file_raises_on_size_exceeded(tmp_path):
    f = tmp_path / "big.json"
    # enforce_file_size_limit clamps the limit to at least 1024 bytes, so
    # produce a file larger than 1024 bytes to trigger the size error.
    f.write_text(json.dumps({"a": "b" * 2000}), encoding="utf-8")
    assert f.stat().st_size > 1024
    with pytest.raises(ValueError, match="too large"):
        load_json_file_with_limit(str(f), max_bytes=1025, label="size_test")
