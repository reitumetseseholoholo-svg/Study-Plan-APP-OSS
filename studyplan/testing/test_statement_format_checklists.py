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
