from __future__ import annotations

import pytest

from studyplan.ai import tutor_llm_purpose as tlp


def test_infer_tutor_llm_purpose_short_default() -> None:
    assert tlp.infer_tutor_llm_purpose("What is NPV?") == "tutor"


def test_infer_tutor_llm_purpose_long_message() -> None:
    body = "explain this " * 200
    assert len(body) >= 1100
    assert tlp.infer_tutor_llm_purpose(body) == "deep_reason"


def test_infer_tutor_llm_purpose_keywords() -> None:
    assert tlp.infer_tutor_llm_purpose("Help me prove this by induction.") == "deep_reason"
    assert tlp.infer_tutor_llm_purpose("Debug this recursion in my amortization code.") == "deep_reason"


def test_infer_tutor_llm_purpose_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDYPLAN_TUTOR_DYNAMIC_MODEL_PURPOSE", "0")
    long_body = "word " * 300
    assert tlp.infer_tutor_llm_purpose(long_body) == "tutor"
