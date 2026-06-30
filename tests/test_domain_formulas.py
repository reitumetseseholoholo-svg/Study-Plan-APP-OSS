"""Parametrized unit tests for all 21 ACCA FM domain formula templates.

Each template wraps a deterministic solver with step-aware solve(),
evaluate_steps(), and classify_errors().  Tests cover:

  - Correct solve() output for canonical inputs
  - Return dict structure (concept_id, result, steps, inputs, is_nan)
  - Edge cases: division by zero, zero inputs, NaN guards
  - classify_errors() for known mistake patterns
"""

from __future__ import annotations

from typing import Any

import pytest

from studyplan.domain_reasoning.templates import FormulaTemplate


# ---------------------------------------------------------------------------
# Template imports
# ---------------------------------------------------------------------------

from studyplan.domain_reasoning.domains.acca_fm.wacc import WaccTemplate
from studyplan.domain_reasoning.domains.acca_fm.npv import NpvTemplate
from studyplan.domain_reasoning.domains.acca_fm.capm import CapmTemplate
from studyplan.domain_reasoning.domains.acca_fm.payback import (
    PaybackTemplate,
    DiscountedPaybackTemplate,
)
from studyplan.domain_reasoning.domains.acca_fm.ccc import CccTemplate
from studyplan.domain_reasoning.domains.acca_fm.cost_of_debt import CostOfDebtTemplate
from studyplan.domain_reasoning.domains.acca_fm.cost_of_equity_dvm import (
    CostOfEquityDvmTemplate,
)
from studyplan.domain_reasoning.domains.acca_fm.irr import IrrTemplate
from studyplan.domain_reasoning.domains.acca_fm.arr import ArrTemplate
from studyplan.domain_reasoning.domains.acca_fm.eoq import EoqTemplate
from studyplan.domain_reasoning.domains.acca_fm.equivalent_annual_cost import (
    EquivalentAnnualCostTemplate,
)
from studyplan.domain_reasoning.domains.acca_fm.profitability_index import (
    ProfitabilityIndexTemplate,
)
from studyplan.domain_reasoning.domains.acca_fm.gearing import (
    GearingTemplate,
    InterestCoverTemplate,
    EpsTemplate,
    DividendYieldTemplate,
    DividendCoverTemplate,
)
from studyplan.domain_reasoning.domains.acca_fm.asset_beta import AssetBetaTemplate
from studyplan.domain_reasoning.domains.acca_fm.equity_beta import EquityBetaTemplate
from studyplan.domain_reasoning.domains.acca_fm.pe_ratio import PeRatioTemplate
from studyplan.domain_reasoning.domains.acca_fm.roe import RoeTemplate
from studyplan.domain_reasoning.domains.acca_fm.cost_of_preference import (
    CostOfPreferenceTemplate,
)
from studyplan.domain_reasoning.domains.acca_fm.terp import TerpTemplate
from studyplan.domain_reasoning.domains.acca_fm.perpetuity_npv import (
    PerpetuityNpvTemplate,
)
from studyplan.domain_reasoning.domains.acca_fm.roce import RoceTemplate


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _check_solve_result(
    result: dict[str, Any],
    *,
    concept_id: str,
    expected: float,
) -> None:
    """Assert the structure and value of a solve() return dict."""
    assert result is not None
    assert result.get("concept_id") == concept_id, (
        f"Expected concept_id={concept_id!r}, got {result.get('concept_id')!r}"
    )
    assert not result.get("is_nan", False), f"Unexpected NaN for {concept_id}"
    res = result.get("result")
    assert res is not None, f"result is None for {concept_id}"
    assert isinstance(res, float), f"result not float for {concept_id}"
    assert abs(res - expected) < 1e-9, f"{concept_id}: expected {expected}, got {res}"
    # Check steps exist and are well-formed
    steps = result.get("steps", [])
    assert isinstance(steps, list), f"steps not a list for {concept_id}"
    assert len(steps) >= 1, f"no steps for {concept_id}"
    for s in steps:
        assert "step_id" in s, f"step missing step_id in {concept_id}"
        assert "value" in s, f"step {s.get('step_id')} missing value in {concept_id}"
    # Check inputs captured
    assert "inputs" in result, f"inputs missing for {concept_id}"


# ---------------------------------------------------------------------------
# Parametrized: each template with canonical inputs
# ---------------------------------------------------------------------------

DOMAIN_FORMULA_CASES: list[tuple[str, type[FormulaTemplate], dict[str, Any], float]] = [
    (
        "fm.wacc",
        WaccTemplate,
        {"equity": 100, "debt": 50, "cost_equity": 0.12, "cost_debt": 0.06, "tax_rate": 0.25},
        0.10,
    ),
    ("fm.npv", NpvTemplate, {"cashflows": [100, 200, 300], "rate": 0.10, "initial": 500}, -18.407212622088764),
    ("fm.capm", CapmTemplate, {"risk_free": 0.03, "beta": 1.2, "market_return": 0.10}, 0.114),
    ("fm.payback", PaybackTemplate, {"initial": 1000, "cashflows": [300, 400, 500]}, 2.6),
    (
        "fm.discounted_payback",
        DiscountedPaybackTemplate,
        {"initial": 1000, "cashflows": [300, 400, 500], "rate": 0.05},
        2.81375,
    ),
    ("fm.ccc", CccTemplate, {"dio": 30, "dso": 45, "dpo": 20}, 55.0),
    ("fm.cost_of_debt", CostOfDebtTemplate, {"interest_rate": 0.08, "tax_rate": 0.25}, 0.06),
    ("fm.cost_of_equity_dvm", CostOfEquityDvmTemplate, {"dividend": 0.50, "price": 5.00, "growth": 0.03}, 0.133),
    ("fm.irr", IrrTemplate, {"cashflows": [100, 200, 300], "initial": 400}, 0.19437709962747876),
    (
        "fm.arr",
        ArrTemplate,
        {"average_profit": 50, "initial_investment": 500, "residual_value": 50},
        0.18181818181818182,
    ),
    (
        "fm.eoq",
        EoqTemplate,
        {"annual_demand": 10000, "ordering_cost": 50, "holding_cost_per_unit": 2},
        707.1067811865476,
    ),
    (
        "fm.equivalent_annual_cost",
        EquivalentAnnualCostTemplate,
        {"cost": 10000, "discount_rate": 0.10, "years": 5},
        2637.974807947452,
    ),
    (
        "fm.profitability_index",
        ProfitabilityIndexTemplate,
        {"pv_future_cashflows": 1200, "initial_investment": 1000},
        1.2,
    ),
    ("fm.gearing", GearingTemplate, {"debt": 50, "equity": 100}, 0.3333333333333333),
    ("fm.interest_cover", InterestCoverTemplate, {"pbit": 200, "interest_expense": 50}, 4.0),
    ("fm.eps", EpsTemplate, {"profit_after_tax": 100000, "number_of_shares": 50000}, 2.0),
    ("fm.dividend_yield", DividendYieldTemplate, {"dividend_per_share": 0.25, "market_price": 5.00}, 0.05),
    ("fm.dividend_cover", DividendCoverTemplate, {"eps": 0.40, "dividend_per_share": 0.25}, 1.6),
    (
        "fm.asset_beta",
        AssetBetaTemplate,
        {"equity_beta": 1.2, "market_value_debt": 50, "market_value_equity": 100, "tax_rate": 0.25},
        0.8727272727272727,
    ),
    (
        "fm.equity_beta",
        EquityBetaTemplate,
        {"asset_beta": 0.8, "market_value_debt": 100, "market_value_equity": 50, "tax_rate": 0.25},
        2.0,
    ),
    ("fm.pe_ratio", PeRatioTemplate, {"market_price": 10.00, "eps": 0.50}, 20.0),
    ("fm.roe", RoeTemplate, {"profit_after_tax": 200000, "equity": 1000000}, 0.2),
    (
        "fm.cost_of_preference",
        CostOfPreferenceTemplate,
        {"preference_dividend": 0.10, "market_price": 1.50},
        0.06666666666666667,
    ),
    ("fm.terp", TerpTemplate, {"cum_rights_price": 4.00, "issue_price": 3.00, "rights_ratio_n": 4}, 3.8),
    ("fm.perpetuity_npv", PerpetuityNpvTemplate, {"annual_cashflow": 100, "discount_rate": 0.08}, 1250.0),
    ("fm.roce", RoceTemplate, {"pbit": 200, "capital_employed": 1000}, 0.2),
]


@pytest.mark.parametrize("concept_id,cls,inputs,expected", DOMAIN_FORMULA_CASES)
def test_solve_canonical(
    concept_id: str,
    cls: type[FormulaTemplate],
    inputs: dict[str, Any],
    expected: float,
) -> None:
    """Verify solve() returns the correct result for canonical inputs."""
    template = cls()
    result = template.solve(inputs)
    _check_solve_result(result, concept_id=concept_id, expected=expected)


# ---------------------------------------------------------------------------
# Edge cases: NaN / division-by-zero
# ---------------------------------------------------------------------------

NAN_CASES: list[tuple[str, type[FormulaTemplate], dict[str, Any]]] = [
    ("fm.wacc — zero total value", WaccTemplate, {"equity": 0, "debt": 0, "cost_equity": 0.12, "cost_debt": 0.06}),
    ("fm.npv — no cashflows", NpvTemplate, {"cashflows": [], "rate": 0.10, "initial": 100}),
    (
        "fm.eoq — zero holding cost",
        EoqTemplate,
        {"annual_demand": 1000, "ordering_cost": 50, "holding_cost_per_unit": 0},
    ),
    ("fm.gearing — zero total value", GearingTemplate, {"debt": 0, "equity": 0}),
    ("fm.roce — zero capital", RoceTemplate, {"pbit": 100, "capital_employed": 0}),
]


@pytest.mark.parametrize("label,cls,inputs", NAN_CASES)
def test_solve_nan(label: str, cls: type[FormulaTemplate], inputs: dict[str, Any]) -> None:
    """Verify solve() returns is_nan for edge cases like division by zero."""
    template = cls()
    result = template.solve(inputs)
    assert result is not None
    assert result.get("is_nan", False) is True, f"Expected is_nan=True for {label}, got result={result.get('result')}"


# ---------------------------------------------------------------------------
# Return-structure integrity
# ---------------------------------------------------------------------------

STRUCTURE_CASES = [
    (WaccTemplate, {"equity": 200, "debt": 100, "cost_equity": 0.10, "cost_debt": 0.05}),
    (NpvTemplate, {"cashflows": [50, 60], "rate": 0.08, "initial": 80}),
    (CapmTemplate, {"risk_free": 0.02, "beta": 0.8, "market_return": 0.08}),
    (CccTemplate, {"dio": 40, "dso": 60, "dpo": 30}),
    (EoqTemplate, {"annual_demand": 5000, "ordering_cost": 30, "holding_cost_per_unit": 1.5}),
]


@pytest.mark.parametrize("cls,inputs", STRUCTURE_CASES)
def test_solve_structure(cls: type[FormulaTemplate], inputs: dict[str, Any]) -> None:
    """Verify solve() return dict contains all required keys."""
    template = cls()
    result = template.solve(inputs)
    assert isinstance(result, dict)
    assert "concept_id" in result
    assert "result" in result
    assert "steps" in result
    assert "inputs" in result
    assert "is_nan" in result
    steps = result["steps"]
    assert isinstance(steps, list)
    for s in steps:
        assert isinstance(s, dict)
        assert "step_id" in s
        assert "description" in s
        assert "value" in s
        assert isinstance(s["value"], (int, float))
    assert isinstance(result["inputs"], dict)
    assert isinstance(result["is_nan"], bool)


# ---------------------------------------------------------------------------
# classify_errors coverage
# ---------------------------------------------------------------------------

ERROR_CLASSIFICATION_CASES: list[tuple[str, type[FormulaTemplate], dict[str, Any], list[dict[str, Any]], list[str]]] = [
    (
        "NpvTemplate — missing sign",
        NpvTemplate,
        {"cashflows": [100, 200, 300], "rate": 0.10, "initial": 500},
        [{"step_id": "pv_year_1", "value": 90.909}, {"step_id": "npv", "value": -18.407}],
        [],
    ),
    (
        "WaccTemplate — wrong weighting > 1",
        WaccTemplate,
        {"equity": 100, "debt": 50, "cost_equity": 0.12, "cost_debt": 0.06, "tax_rate": 0.25},
        [{"step_id": "weight_equity", "value": 1.5}, {"step_id": "wacc", "value": 0.10}],
        ["wrong_weighting"],
    ),
    (
        "WaccTemplate — debt component error",
        WaccTemplate,
        {"equity": 100, "debt": 50, "cost_equity": 0.12, "cost_debt": 0.06, "tax_rate": 0.25},
        [
            {"step_id": "weight_equity", "value": 0.667},
            {"step_id": "cost_debt_component", "value": 0.50},
            {"step_id": "wacc", "value": 0.10},
        ],
        ["cost_debt_component_mismatch", "debt_component_error", "weight_equity_mismatch"],
    ),
    (
        "CccTemplate — wrong term (added DPO instead of subtracting)",
        CccTemplate,
        {"dio": 30, "dso": 45, "dpo": 20},
        [{"step_id": "ccc", "value": 95.0}],
        ["ccc_mismatch", "wrong_term"],
    ),
    (
        "GearingTemplate — wrong denominator (Debt/Equity instead of Debt/(D+E))",
        GearingTemplate,
        {"debt": 50, "equity": 100},
        [{"step_id": "gearing", "value": 0.5}],
        ["wrong_denominator", "gearing_mismatch"],
    ),
    (
        "EoqTemplate — sqrt error (missing sqrt)",
        EoqTemplate,
        {"annual_demand": 10000, "ordering_cost": 50, "holding_cost_per_unit": 2},
        [
            {"step_id": "two_d_o", "value": 1_000_000},
            {"step_id": "dividend", "value": 500_000},
            {"step_id": "eoq", "value": 500_000.0},
        ],
        ["sqrt_error", "dividend_mismatch", "eoq_mismatch"],
    ),
    (
        "CapmTemplate — wrong premium",
        CapmTemplate,
        {"risk_free": 0.03, "beta": 1.2, "market_return": 0.10},
        [{"step_id": "equity_risk_premium", "value": 0.05}, {"step_id": "capm", "value": 0.09}],
        ["equity_risk_premium_mismatch", "capm_mismatch", "wrong_premium"],
    ),
]


@pytest.mark.parametrize("label,cls,inputs,learner_steps,expected_tags", ERROR_CLASSIFICATION_CASES)
def test_classify_errors(
    label: str,
    cls: type[FormulaTemplate],
    inputs: dict[str, Any],
    learner_steps: list[dict[str, Any]],
    expected_tags: list[str],
) -> None:
    """Verify classify_errors() detects known mistake patterns."""
    template = cls()
    truth = template.solve(inputs)
    tags = template.classify_errors(learner_steps, truth)
    for et in expected_tags:
        assert et in tags, f"{label}: expected tag {et!r} not found in {tags}"


# ---------------------------------------------------------------------------
# evaluate_steps coverage
# ---------------------------------------------------------------------------


def test_formula_template_evaluate_steps_match() -> None:
    """Default evaluate_steps: matching answer returns match=True."""
    template = WaccTemplate()
    truth = template.solve({"equity": 100, "debt": 50, "cost_equity": 0.12, "cost_debt": 0.06})
    steps = template.evaluate_steps(
        [{"step_id": "learner_final", "value": 0.10}],
        truth,
    )
    assert len(steps) >= 1
    assert steps[0]["match"] is True, f"Expected match=True, got {steps}"


def test_formula_template_evaluate_steps_mismatch() -> None:
    """Default evaluate_steps: wrong answer returns match=False."""
    template = WaccTemplate()
    truth = template.solve({"equity": 100, "debt": 50, "cost_equity": 0.12, "cost_debt": 0.06})
    steps = template.evaluate_steps(
        [{"step_id": "learner_final", "value": 0.20}],
        truth,
    )
    assert len(steps) >= 1
    assert steps[0]["match"] is False


def test_evaluate_steps_empty_inputs() -> None:
    """Empty learner steps or truth returns empty list."""
    template = WaccTemplate()
    assert template.evaluate_steps([], {}) == []
    assert template.evaluate_steps(None, None) == []
