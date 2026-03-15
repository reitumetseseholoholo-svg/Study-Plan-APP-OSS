"""Tests for syllabus outcome completion (truncated detection and AI completion)."""
from __future__ import annotations

import pytest

from studyplan.syllabus_outcomes import (
    complete_truncated_syllabus_outcomes,
    is_truncated_outcome_text,
)


def test_is_truncated_outcome_text_ellipsis() -> None:
    assert is_truncated_outcome_text("Explain the purpose of financial manag...") is True
    assert is_truncated_outcome_text("Apply DCF methods to evaluate…") is True
    assert is_truncated_outcome_text("Discuss the role of working capital.") is False


def test_is_truncated_outcome_text_short_no_punctuation() -> None:
    # 12–24 chars with no final punctuation -> truncated
    assert is_truncated_outcome_text("Explain NPV and IRR") is True
    assert is_truncated_outcome_text("Explain NPV.") is False


def test_is_truncated_outcome_text_ends_mid_sentence() -> None:
    assert is_truncated_outcome_text("The candidate must be able to explain the role and purpose of,") is True
    assert is_truncated_outcome_text("The candidate must be able to explain the role and purpose of.") is False


def test_is_truncated_outcome_text_long_no_period() -> None:
    assert is_truncated_outcome_text("Explain the purpose of financial management and the role of the financial manager in the") is True
    assert is_truncated_outcome_text("Explain the purpose of financial management.") is False


def test_complete_truncated_syllabus_outcomes_empty_config() -> None:
    config: dict = {}
    out, n = complete_truncated_syllabus_outcomes(config, lambda p, m: "")
    assert n == 0
    assert out == {}


def test_complete_truncated_syllabus_outcomes_no_truncated() -> None:
    config = {
        "syllabus_structure": {
            "Ch1": {
                "learning_outcomes": [
                    {"id": "a1", "text": "Explain the purpose of financial management.", "level": 1},
                ],
            },
        },
    }
    out, n = complete_truncated_syllabus_outcomes(config, lambda p, m: "")
    assert n == 0
    assert out["syllabus_structure"]["Ch1"]["learning_outcomes"][0]["text"] == "Explain the purpose of financial management."


def test_complete_truncated_syllabus_outcomes_completes_one() -> None:
    config = {
        "syllabus_structure": {
            "Ch1": {
                "learning_outcomes": [
                    {"id": "a1", "text": "Explain the purpose of financial manag...", "level": 1},
                ],
            },
        },
    }
    def mock_llm(prompt: str, max_tokens: int) -> str:
        return "Explain the purpose of financial management and the role of the financial manager."
    out, n = complete_truncated_syllabus_outcomes(config, mock_llm)
    assert n == 1
    assert "financial management" in out["syllabus_structure"]["Ch1"]["learning_outcomes"][0]["text"]
    assert out["syllabus_structure"]["Ch1"]["learning_outcomes"][0]["text"].endswith(".")
