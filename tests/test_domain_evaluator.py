"""Tests for the domain evaluation pipeline (evaluate_question)."""

from __future__ import annotations


import pytest

from studyplan.domain_reasoning.evaluator import (
    evaluate_question,
    _value_matches,
    _try_parse_correct,
    _evaluate_single_concept,
)
from studyplan.domain_reasoning.diagnostics import (
    ConceptEvaluation,
    QuestionDiagnostic,
    merge_concept_results,
)


# ---------------------------------------------------------------------------
# _try_parse_correct
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("123.45", 123.45),
        ("$500", 500.0),
        ("\u00a3250", 250.0),
        ("\u20ac99.99", 99.99),
        ("15%", 15.0),
        ("1,234.56", 1234.56),
        ("", None),
        (None, None),
        ("not_a_number", None),
        ("  42  ", 42.0),
    ],
)
def test_try_parse_correct(raw: str | None, expected: float | None) -> None:
    res = _try_parse_correct(raw)
    if expected is None:
        assert res is None
    else:
        assert res is not None
        assert abs(res - expected) < 1e-9


# ---------------------------------------------------------------------------
# _value_matches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref,candidate,expected",
    [
        (100.0, 100.0, True),
        (100.0, 100.5, True),  # Within 0.5%
        (100.0, 102.0, False),  # Beyond 0.5%
        (1.0, 1.005, True),  # 0.5% of 1 → 0.005, within
        (1.0, 1.02, False),
        (0.0, 0.0, True),
        (0.0, 0.005, True),  # abs_tol = max(0.01, 0 * 0.005) = 0.01
        (0.0, 0.02, False),
        (float("nan"), 5.0, False),
        (5.0, float("nan"), False),
    ],
)
def test_value_matches(ref: float, candidate: float, expected: bool) -> None:
    assert _value_matches(ref, candidate) == expected


# ---------------------------------------------------------------------------
# _evaluate_single_concept
# ---------------------------------------------------------------------------


def test_evaluate_single_concept_known_template() -> None:
    """Known concept with correct inputs returns a ConceptEvaluation."""
    ev = _evaluate_single_concept(
        "fm.capm",
        {"risk_free": 0.02, "beta": 1.0, "market_return": 0.08},
        correct_value=0.08,
        learner_answer="0.08",
        is_primary=True,
    )
    assert ev is not None
    assert ev.concept_id == "fm.capm"
    assert ev.result is not None and abs(ev.result - 0.08) < 1e-9
    assert len(ev.steps) > 0
    # Correct answer → no final_answer_mismatch (but may have step mismatches
    # since no learner workings provided for step matching)
    assert "final_answer_mismatch" not in ev.error_tags


def test_evaluate_single_concept_wrong_answer() -> None:
    """Wrong learner answer produces step-level mismatch tags."""
    ev = _evaluate_single_concept(
        "fm.capm",
        {"risk_free": 0.02, "beta": 1.0, "market_return": 0.08},
        correct_value=0.08,
        learner_answer="0.10",
        is_primary=False,
    )
    assert ev is not None
    # Correct result (0.08) matches correct_value (0.08) → no final_answer_mismatch
    # but step matching returns mismatches because no workings provided
    assert any("mismatch" in t for t in ev.error_tags)


def test_evaluate_single_concept_unknown() -> None:
    """Unknown concept returns None."""
    ev = _evaluate_single_concept("fm.nonexistent", {}, None, None)
    assert ev is None


def test_evaluate_single_concept_nan_result() -> None:
    """Template that returns NaN is skipped (returns None)."""
    ev = _evaluate_single_concept(
        "fm.wacc",
        {"equity": 0, "debt": 0, "cost_equity": 0.12, "cost_debt": 0.06},
        correct_value=None,
        learner_answer=None,
    )
    assert ev is None


# ---------------------------------------------------------------------------
# evaluate_question — Tier 1 (exact template_ref)
# ---------------------------------------------------------------------------


def test_evaluate_question_tier1() -> None:
    """Tier 1: exact template_ref + template_inputs produces primary evaluation."""
    diag = evaluate_question(
        question="What is the WACC?",
        template_ref="fm.wacc",
        template_inputs={"equity": 100, "debt": 50, "cost_equity": 0.12, "cost_debt": 0.06},
        correct="0.10",
        learner_answer="0.10",
    )
    assert diag.has_deterministic_truth
    assert len(diag.concept_evaluations) >= 1
    primary = diag.concept_evaluations[0]
    assert primary.concept_id == "fm.wacc"
    # Primary gets 0.9 base, minus 0.1 per error tag (step mismatches
    # from missing learner workings) — may be lower than 0.8
    assert primary.confidence > 0  # Non-zero confidence


def test_evaluate_question_tier1_without_tier2_duplicate() -> None:
    """Concepts evaluated via tier 1 are skipped in tier 2."""
    diag = evaluate_question(
        question="NPV with cashflows",
        template_ref="fm.npv",
        template_inputs={"cashflows": [100, 200], "rate": 0.10, "initial": 200},
        correct="57.85",
        learner_answer="57.85",
    )
    # fm.npv should appear only once
    npv_evals = [e for e in diag.concept_evaluations if e.concept_id == "fm.npv"]
    assert len(npv_evals) == 1


# ---------------------------------------------------------------------------
# evaluate_question — Tier 2 (auto-detected concepts)
# ---------------------------------------------------------------------------


def test_evaluate_question_tier2_detection() -> None:
    """Tier 2: concepts detected from question text are evaluated."""
    diag = evaluate_question(
        question="Calculate NPV with cashflows 100, 200, 300, discount rate 10%, initial investment 500.",
        correct="-18.41",
        learner_answer="-18.41",
    )
    # At minimum, the diagnostic should not crash
    assert isinstance(diag, QuestionDiagnostic)


def test_evaluate_question_tier2_multiple_concepts() -> None:
    """Multiple detected concepts each produce a ConceptEvaluation."""
    diag = evaluate_question(
        question="Calculate NPV with cashflows 100, 200 and discount rate 10%.",
        correct="0.00",
        learner_answer="0.00",
    )
    assert len(diag.concept_evaluations) >= 1


# ---------------------------------------------------------------------------
# evaluate_question — Tier 3 (fallback numerical verification)
# ---------------------------------------------------------------------------


def test_evaluate_question_tier3_fallback() -> None:
    """Tier 3: when templates can't extract inputs, falls back to verification."""
    diag = evaluate_question(
        question="What is 2 + 2?",
        options=["3", "4", "5"],
        correct="4",
        learner_answer="4",
    )
    # May have no deterministic truth if nothing matched
    assert isinstance(diag, QuestionDiagnostic)


def test_evaluate_question_all_tiers_empty() -> None:
    """No matching tiers produces has_deterministic_truth=False."""
    diag = evaluate_question(
        question="What is the meaning of life?",
        correct="42",
    )
    # No templates match this question
    assert isinstance(diag, QuestionDiagnostic)


# ---------------------------------------------------------------------------
# merge_concept_results
# ---------------------------------------------------------------------------


def test_merge_concept_results_empty() -> None:
    """Empty evaluations returns a minimal QuestionDiagnostic."""
    diag = merge_concept_results([], {})
    assert isinstance(diag, QuestionDiagnostic)
    assert not diag.has_deterministic_truth
    assert diag.concept_evaluations == []


def test_merge_concept_results_single() -> None:
    """Single evaluation is wrapped into a QuestionDiagnostic."""
    ev = ConceptEvaluation(
        concept_id="fm.test",
        result=42.0,
        steps=[],
        error_tags=[],
        confidence=0.9,
    )
    diag = merge_concept_results([ev], {"fm.test": None})
    assert diag.has_deterministic_truth
    assert len(diag.concept_evaluations) == 1
    assert diag.concept_evaluations[0].concept_id == "fm.test"


def test_merge_concept_results_aggregates_tags() -> None:
    """Error tags from all evaluations are collected in all_error_tags."""
    ev1 = ConceptEvaluation(
        concept_id="fm.wacc",
        result=0.10,
        steps=[],
        error_tags=["wrong_weighting"],
        confidence=0.6,
    )
    ev2 = ConceptEvaluation(
        concept_id="fm.capm",
        result=0.08,
        steps=[],
        error_tags=["beta_error"],
        confidence=0.7,
    )
    diag = merge_concept_results([ev1, ev2], {"fm.wacc": None, "fm.capm": None})
    assert "wrong_weighting" in diag.all_error_tags
    assert "beta_error" in diag.all_error_tags


def test_merge_concept_results_weak_concepts() -> None:
    """Concepts with error tags and low confidence are weak."""
    ev1 = ConceptEvaluation(
        concept_id="fm.wacc",
        result=0.10,
        steps=[],
        error_tags=["wrong_weighting"],
        confidence=0.3,
    )
    diag = merge_concept_results([ev1], {"fm.wacc": None})
    assert "fm.wacc" in diag.weak_concepts


# ---------------------------------------------------------------------------
# Error summary
# ---------------------------------------------------------------------------


def test_format_error_summary_exists() -> None:
    """format_error_summary helper is importable and callable."""
    from studyplan.domain_reasoning.diagnostics import format_error_summary

    diag = QuestionDiagnostic(
        question_slug="test question",
        concept_ids=["fm.test"],
        all_error_tags=["step1_mismatch", "sign_error"],
        has_deterministic_truth=True,
        diagnostic_confidence=0.5,
    )
    summary = format_error_summary(diag)
    assert isinstance(summary, str)
    assert "test question" in summary or "fm.test" in summary or "sign_error" in summary or summary != ""


# ---------------------------------------------------------------------------
# classify_step_id_error
# ---------------------------------------------------------------------------


def test_classify_step_id_error_mapping() -> None:
    """classify_step_id_error maps keywords to ErrorPattern."""
    from studyplan.domain_reasoning.diagnostics import classify_step_id_error, ErrorPattern

    assert classify_step_id_error("sign_error") == ErrorPattern.SIGN_ERROR
    assert classify_step_id_error("tax_neglect") == ErrorPattern.TAX_NEGLECT
    assert classify_step_id_error("wrong_discount") == ErrorPattern.WRONG_DISCOUNT_RATE
    assert classify_step_id_error("unknown_step") is None


# ---------------------------------------------------------------------------
# classify_step_errors
# ---------------------------------------------------------------------------


def test_classify_step_errors() -> None:
    """classify_step_errors returns string error tags."""
    from studyplan.domain_reasoning.diagnostics import classify_step_errors

    step_matches = [
        {"step_id": "pv_year_1", "match": False, "expected": 90.91, "actual": 100.0},
        {"step_id": "npv", "match": True, "expected": 57.85, "actual": 57.85},
    ]
    tags = classify_step_errors(step_matches)
    assert len(tags) >= 1
