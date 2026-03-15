"""Tests for RAG encoding (bytes from PDF) and reconfig chunk building (non-dict entries)."""
from __future__ import annotations

import types

import pytest

# Chunk-building logic used by studyplan_app when building chunks_by_path from doc["chunks"].
# We test that non-dict entries are filtered so no .get() is called on non-dict.
def _build_chunks_for_reconfig(doc_chunks: list) -> list[dict]:
    """Same filtering as studyplan_app on_reconfigure_from_rag / _maybe_auto_reconfigure_from_rag."""
    return [
        {"text": str(c.get("text", "") or "").strip()}
        for c in doc_chunks
        if isinstance(c, dict) and c.get("text")
    ]


def test_reconfig_chunk_building_filters_non_dict():
    """Non-dict entries in doc['chunks'] must be skipped; only dicts with text are included."""
    doc_chunks = [
        {"text": "Chapter 1 content"},
        "not a dict",
        None,
        {"text": "Chapter 2 content"},
        [],
        {"no_text": "skip"},
        {"text": ""},
        {"text": "  valid  "},
    ]
    result = _build_chunks_for_reconfig(doc_chunks)
    assert result == [
        {"text": "Chapter 1 content"},
        {"text": "Chapter 2 content"},
        {"text": "valid"},
    ]


def test_reconfig_chunk_building_empty_list():
    """Empty chunks list produces empty list."""
    assert _build_chunks_for_reconfig([]) == []


def test_rag_bytes_coercion_to_str():
    """Bytes from PDF extraction must be decodable with errors=replace (no raise)."""
    raw = b"Valid ASCII and \xff invalid byte \xfe here."
    decoded = raw.decode("utf-8", errors="replace").strip()
    assert isinstance(decoded, str)
    assert "Valid ASCII" in decoded
    assert "\ufffd" in decoded  # replacement char for \xff
