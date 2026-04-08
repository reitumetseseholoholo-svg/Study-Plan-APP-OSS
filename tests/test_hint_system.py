"""Unit tests for studyplan/hint_system.py."""
from __future__ import annotations

import pytest

from studyplan.hint_system import HintBank, HintLevel


# ---------------------------------------------------------------------------
# HintLevel dataclass
# ---------------------------------------------------------------------------


def test_hint_level_dataclass_stores_fields():
    h = HintLevel(level=2, text="Think about the formula.", label="Scaffold", context="formula")
    assert h.level == 2
    assert h.text == "Think about the formula."
    assert h.label == "Scaffold"
    assert h.context == "formula"


def test_hint_level_default_context_is_empty():
    h = HintLevel(level=0, text="Nudge", label="Nudge")
    assert h.context == ""


# ---------------------------------------------------------------------------
# HintBank.generate_hints — returns exactly 5 levels
# ---------------------------------------------------------------------------


@pytest.fixture
def bank_short_answer():
    return HintBank(
        topic="NPV calculation",
        concept="Net Present Value",
        item_type="short_answer",
        expected_answer="discount future cash flows at cost of capital",
        error_tags=(),
    )


@pytest.fixture
def bank_numeric():
    return HintBank(
        topic="WACC",
        concept="Weighted Average Cost of Capital",
        item_type="numeric",
        expected_answer="0.10",
        error_tags=("formula_error",),
    )


def test_generate_hints_returns_five_levels(bank_short_answer):
    hints = bank_short_answer.generate_hints()
    assert len(hints) == 5


def test_hint_levels_are_sequential(bank_short_answer):
    hints = bank_short_answer.generate_hints()
    for i, h in enumerate(hints):
        assert h.level == i


def test_hint_labels_are_non_empty(bank_short_answer):
    hints = bank_short_answer.generate_hints()
    for h in hints:
        assert h.label.strip()


def test_hint_texts_are_non_empty(bank_short_answer):
    hints = bank_short_answer.generate_hints()
    for h in hints:
        assert h.text.strip()


def test_solution_hint_contains_expected_answer(bank_short_answer):
    hints = bank_short_answer.generate_hints()
    solution = hints[4]
    assert solution.level == 4
    assert "discount" in solution.text.lower() or "cost of capital" in solution.text.lower()


# ---------------------------------------------------------------------------
# HintBank.get_hint — clamping
# ---------------------------------------------------------------------------


def test_get_hint_clamps_below_zero(bank_short_answer):
    h = bank_short_answer.get_hint(-5)
    assert h.level == 0


def test_get_hint_clamps_above_four(bank_short_answer):
    h = bank_short_answer.get_hint(99)
    assert h.level == 4


def test_get_hint_returns_correct_level(bank_short_answer):
    for level in range(5):
        h = bank_short_answer.get_hint(level)
        assert h.level == level


# ---------------------------------------------------------------------------
# Numeric item type generates formula-oriented hints
# ---------------------------------------------------------------------------


def test_numeric_light_hint_mentions_formula_when_formula_error(bank_numeric):
    hint = bank_numeric.get_hint(1)
    assert "formula" in hint.text.lower()


def test_numeric_medium_hint_provides_steps(bank_numeric):
    hint = bank_numeric.get_hint(2)
    assert "step" in hint.text.lower() or "formula" in hint.text.lower()


# ---------------------------------------------------------------------------
# recommend_next_level
# ---------------------------------------------------------------------------


def test_recommend_next_level_advances_normally():
    next_lvl = HintBank.recommend_next_level(
        current_level=1,
        has_attempted=True,
        is_struggling=False,
        time_since_hint_seconds=30.0,
    )
    assert next_lvl == 2


def test_recommend_next_level_stays_if_no_attempt():
    next_lvl = HintBank.recommend_next_level(
        current_level=2,
        has_attempted=False,
        is_struggling=False,
    )
    assert next_lvl == 2


def test_recommend_next_level_escalates_faster_in_struggle():
    next_lvl = HintBank.recommend_next_level(
        current_level=0,
        has_attempted=True,
        is_struggling=True,
        time_since_hint_seconds=20.0,
    )
    assert next_lvl >= 2


def test_recommend_next_level_caps_at_four():
    next_lvl = HintBank.recommend_next_level(
        current_level=4,
        has_attempted=True,
        is_struggling=True,
    )
    assert next_lvl == 4


# ---------------------------------------------------------------------------
# HintBank with sign_error error_tag
# ---------------------------------------------------------------------------


def test_nudge_for_misread_error_tag():
    bank = HintBank(
        topic="Ratios",
        concept="Current ratio",
        item_type="short_answer",
        error_tags=("misread",),
    )
    nudge = bank.get_hint(0)
    assert "read" in nudge.text.lower() or "question" in nudge.text.lower()


def test_light_hint_for_sign_error_numeric():
    bank = HintBank(
        topic="NPV",
        concept="NPV",
        item_type="numeric",
        error_tags=("sign_error",),
    )
    hint = bank.get_hint(1)
    assert "sign" in hint.text.lower() or "+" in hint.text or "−" in hint.text
