"""Tests for studyplan.hint_system module."""
import pytest

from studyplan.hint_system import HintBank, HintLevel


# ---------------------------------------------------------------------------
# HintBank.generate_hints
# ---------------------------------------------------------------------------


def test_generate_hints_returns_five_levels():
    bank = HintBank(topic="NPV", concept="net present value")
    hints = bank.generate_hints()
    assert len(hints) == 5


def test_generate_hints_levels_are_0_through_4():
    bank = HintBank(topic="WACC", concept="weighted average cost of capital")
    hints = bank.generate_hints()
    for i, hint in enumerate(hints):
        assert hint.level == i


def test_generate_hints_all_have_non_empty_text():
    bank = HintBank(topic="NPV", concept="discounting")
    hints = bank.generate_hints()
    for hint in hints:
        assert hint.text.strip()


def test_generate_hints_labels_assigned():
    bank = HintBank(topic="NPV", concept="discounting")
    hints = bank.generate_hints()
    assert hints[0].label == "Nudge"
    assert hints[1].label == "Hint"
    assert hints[4].label == "Solution"


# ---------------------------------------------------------------------------
# HintBank.get_hint
# ---------------------------------------------------------------------------


def test_get_hint_returns_correct_level():
    bank = HintBank(topic="NPV", concept="discounting")
    for level in range(5):
        hint = bank.get_hint(level)
        assert hint.level == level


def test_get_hint_clamps_below_zero():
    bank = HintBank(topic="NPV", concept="discounting")
    hint = bank.get_hint(-3)
    assert hint.level == 0


def test_get_hint_clamps_above_four():
    bank = HintBank(topic="NPV", concept="discounting")
    hint = bank.get_hint(99)
    assert hint.level == 4


# ---------------------------------------------------------------------------
# Hint content for different item_types
# ---------------------------------------------------------------------------


def test_numeric_with_formula_error_tag_includes_formula_context():
    bank = HintBank(
        topic="NPV", concept="net present value",
        item_type="numeric", error_tags=("formula_error",)
    )
    light = bank.get_hint(1)
    assert "formula" in light.text.lower()


def test_numeric_with_sign_error_tag_mentions_sign():
    bank = HintBank(
        topic="NPV", concept="cash flows",
        item_type="numeric", error_tags=("sign_error",)
    )
    light = bank.get_hint(1)
    assert "sign" in light.text.lower()


def test_short_answer_with_expected_answer_includes_keywords():
    bank = HintBank(
        topic="WACC", concept="cost of capital",
        item_type="short_answer", expected_answer="market value weighted average discount rate"
    )
    light = bank.get_hint(1)
    # Should mention some of the first words of expected_answer
    assert "market" in light.text.lower() or "value" in light.text.lower()


def test_solution_level_uses_expected_answer_when_provided():
    bank = HintBank(
        topic="NPV", concept="discounting",
        item_type="numeric", expected_answer="42.5"
    )
    solution = bank.get_hint(4)
    assert "42.5" in solution.text


def test_solution_level_fallback_text_when_no_expected_answer():
    bank = HintBank(topic="NPV", concept="discounting")
    solution = bank.get_hint(4)
    assert "discounting" in solution.text.lower() or "npv" in solution.text.lower()


def test_medium_hint_numeric_has_step_structure():
    bank = HintBank(topic="NPV", concept="discounting", item_type="numeric")
    medium = bank.get_hint(2)
    assert "step" in medium.text.lower()


def test_medium_hint_short_answer_has_structure():
    bank = HintBank(topic="NPV", concept="discounting", item_type="short_answer")
    medium = bank.get_hint(2)
    assert "structure" in medium.text.lower() or "state" in medium.text.lower() or "1." in medium.text


def test_misread_tag_adjusts_nudge():
    bank = HintBank(topic="NPV", concept="discounting", error_tags=("misread",))
    nudge = bank.get_hint(0)
    assert "read" in nudge.text.lower() or "question" in nudge.text.lower()


# ---------------------------------------------------------------------------
# HintBank.recommend_next_level
# ---------------------------------------------------------------------------


def test_recommend_next_level_same_if_not_attempted():
    assert HintBank.recommend_next_level(2, has_attempted=False, is_struggling=False) == 2


def test_recommend_next_level_increments_normally():
    assert HintBank.recommend_next_level(1, has_attempted=True, is_struggling=False) == 2


def test_recommend_next_level_escalates_in_struggle_mode():
    result = HintBank.recommend_next_level(1, has_attempted=True, is_struggling=True, time_since_hint_seconds=30.0)
    assert result == 3  # 1 + 2


def test_recommend_next_level_does_not_exceed_4():
    assert HintBank.recommend_next_level(4, has_attempted=True, is_struggling=True, time_since_hint_seconds=60.0) == 4


def test_recommend_next_level_does_not_escalate_in_struggle_too_soon():
    # Under 15 seconds, no fast escalation
    result = HintBank.recommend_next_level(1, has_attempted=True, is_struggling=True, time_since_hint_seconds=5.0)
    assert result == 2
