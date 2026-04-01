"""Tests for static statement format checklists (FR Phase 2.1)."""
from __future__ import annotations

from studyplan.statement_format_checklists import format_checklists_as_text, load_statement_format_checklists


def test_load_statement_format_checklists_has_core_sections() -> None:
    data = load_statement_format_checklists()
    assert "SoFP" in data and "SoPL" in data and "SoCF" in data
    assert all(isinstance(data[k], list) and data[k] for k in ("SoFP", "SoCF"))


def test_format_checklists_as_text_non_empty() -> None:
    text = format_checklists_as_text()
    assert "SoFP" in text and "IAS" in text


def test_load_statement_format_checklists_returns_empty_on_corrupt_json(monkeypatch, tmp_path):
    from studyplan import statement_format_checklists as mod

    bad_path = tmp_path / "checklists.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(mod, "_CHECKLIST_PATH", bad_path)

    data = mod.load_statement_format_checklists()
    assert data == {}


def test_load_statement_format_checklists_returns_empty_on_missing_file(monkeypatch, tmp_path):
    from studyplan import statement_format_checklists as mod

    missing_path = tmp_path / "missing.json"
    monkeypatch.setattr(mod, "_CHECKLIST_PATH", missing_path)

    data = mod.load_statement_format_checklists()
    assert data == {}
