"""Tests for module_chapters: load_chapter_spec_from_path, validation."""
from __future__ import annotations

import pytest

from studyplan.module_chapters import load_chapter_spec_from_path


def test_load_chapter_spec_from_path_valid_json(tmp_path):
    """Valid JSON list returns the list."""
    path = tmp_path / "chapters.json"
    path.write_text('["Ch1", "Ch2"]', encoding="utf-8")
    out = load_chapter_spec_from_path(str(path))
    assert out == ["Ch1", "Ch2"]


def test_load_chapter_spec_from_path_invalid_json_raises_value_error(tmp_path):
    """Invalid JSON raises ValueError with path in message."""
    path = tmp_path / "bad.json"
    path.write_text("{ not valid json ]", encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_chapter_spec_from_path(str(path))
    assert "Invalid JSON" in str(exc_info.value)
    assert path.name in str(exc_info.value) or str(path) in str(exc_info.value)


def test_load_chapter_spec_from_path_missing_file_raises_value_error(tmp_path):
    """Missing file raises ValueError (OSError wrapped)."""
    path = tmp_path / "nonexistent.json"
    assert not path.exists()
    with pytest.raises(ValueError) as exc_info:
        load_chapter_spec_from_path(str(path))
    assert "Cannot read" in str(exc_info.value) or "No such file" in str(exc_info.value)


def test_load_chapter_spec_from_path_not_list_raises_value_error(tmp_path):
    """Non-list JSON content raises ValueError."""
    path = tmp_path / "object.json"
    path.write_text('{"chapters": ["A"]}', encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        load_chapter_spec_from_path(str(path))
    assert "must contain a list" in str(exc_info.value)
