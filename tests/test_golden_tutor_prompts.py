"""Golden tutor prompt fixture validation (Phase 0 roadmap)."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "golden_tutor_prompts.json"


def test_golden_tutor_prompts_fixture_schema():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) >= 20
    ids: set[str] = set()
    for row in data:
        assert isinstance(row, dict)
        rid = str(row.get("id", "") or "").strip()
        assert rid
        assert rid not in ids
        ids.add(rid)
        prompt = str(row.get("user_prompt", "") or "").strip()
        assert len(prompt) >= 8
        tags = row.get("tags", [])
        assert isinstance(tags, list) and tags


def test_golden_prompts_documented_in_telemetry_doc():
    text = (Path(__file__).resolve().parent.parent / "docs" / "LLM_TELEMETRY_SCHEMA.md").read_text(encoding="utf-8")
    assert "golden_tutor_prompts.json" in text
