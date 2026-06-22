"""Tests for the deterministic numerical solver."""

import math
import pytest

from studyplan.numerical_solver import (
    solve_npv, solve_wacc, solve_capm,
    solve_payback_period, solve_discounted_payback,
    solve_cash_conversion_cycle, solve_cost_of_debt,
    solve_cost_of_equity_dvm,
    solve_irr, solve_arr, solve_eoq,
    solve_equivalent_annual_cost, solve_profitability_index,
    solve_gearing, solve_interest_cover, solve_eps,
    solve_dividend_yield, solve_dividend_cover,
    solve_asset_beta, solve_equity_beta,
    solve_pe_ratio, solve_roe, solve_cost_of_preference,
    solve_terp, solve_perpetuity_npv, solve_roce,
    extract_numbers, detect_formulas,
    verify_numerical_answer,
    safe_expression_evaluate, extract_expressions, freeform_verify,
)

# ---------------------------------------------------------------------------
# Existing formula solvers
# ---------------------------------------------------------------------------

class TestSolveNPV:
    def test_basic(self):
        result = solve_npv([100, 200, 300], 0.10)
        assert abs(result - (100/1.1 + 200/1.1**2 + 300/1.1**3)) < 0.01

    def test_with_initial(self):
        result = solve_npv([100, 200, 300], 0.10, initial=50)
        expected = (100/1.1 + 200/1.1**2 + 300/1.1**3) - 50
        assert abs(result - expected) < 0.01

    def test_nan_on_bad_rate(self):
        assert math.isnan(solve_npv([100], -2.0))

    def test_nan_on_empty(self):
        assert math.isnan(solve_npv([], 0.1))


class TestSolveWACC:
    def test_no_tax(self):
        result = solve_wacc(60, 40, 0.12, 0.06)
        expected = (60/100)*0.12 + (40/100)*0.06
        assert abs(result - expected) < 0.001

    def test_with_tax(self):
        result = solve_wacc(60, 40, 0.12, 0.042, 0.30)
        expected = (60/100)*0.12 + (40/100)*0.042
        assert abs(result - expected) < 0.001

    def test_nan_on_zero_value(self):
        assert math.isnan(solve_wacc(0, 0, 0.1, 0.05))


class TestSolveCAPM:
    def test_basic(self):
        result = solve_capm(0.03, 1.2, 0.10)
        expected = 0.03 + 1.2 * (0.10 - 0.03)
        assert abs(result - expected) < 0.001


class TestSolvePayback:
    def test_exact(self):
        result = solve_payback_period(100, [50, 50])
        assert abs(result - 2.0) < 0.01

    def test_partial(self):
        result = solve_payback_period(100, [30, 40, 50])
        assert abs(result - 2.6) < 0.01

    def test_nan_when_never_recouped(self):
        assert math.isnan(solve_payback_period(100, [10, 10]))


class TestSolveDiscountedPayback:
    def test_basic(self):
        result = solve_discounted_payback(100, [50, 50, 50], 0.10)
        assert not math.isnan(result)
        assert result > 0


class TestSolveCCC:
    def test_basic(self):
        result = solve_cash_conversion_cycle(40, 30, 20)
        assert abs(result - 50.0) < 0.01


class TestSolveCostOfDebt:
    def test_basic(self):
        result = solve_cost_of_debt(0.08, 0.30)
        assert abs(result - 0.056) < 0.001

    def test_no_tax(self):
        result = solve_cost_of_debt(0.08, 0.0)
        assert abs(result - 0.08) < 0.001


class TestSolveCostOfEquityDVM:
    def test_no_growth(self):
        result = solve_cost_of_equity_dvm(2.0, 20.0)
        assert abs(result - 0.10) < 0.001

    def test_with_growth(self):
        result = solve_cost_of_equity_dvm(2.0, 20.0, 0.04)
        expected = (2.0 * 1.04) / 20.0 + 0.04
        assert abs(result - expected) < 0.001

    def test_nan_on_zero_price(self):
        assert math.isnan(solve_cost_of_equity_dvm(1.0, 0.0))


# ---------------------------------------------------------------------------
# New formula solvers
# ---------------------------------------------------------------------------

class TestSolveIRR:
    def test_basic(self):
        # Investment of 100, returns 60 and 60 -> IRR ~ 13.07%
        result = solve_irr([60, 60], 100)
        assert not math.isnan(result)
        # NPV = -100 + 60/(1+r) + 60/(1+r)^2 = 0 => r ~ 0.1307
        assert abs(result - 0.1307) < 0.01

    def test_nan_no_cashflows(self):
        assert math.isnan(solve_irr([], 100))


class TestSolveARR:
    def test_basic(self):
        result = solve_arr(15000, 100000, 0)
        # Avg investment = 50000, ARR = 15000/50000 = 0.30
        assert abs(result - 0.30) < 0.001

    def test_with_residual(self):
        result = solve_arr(12000, 80000, 20000)
        # Avg investment = (80000+20000)/2 = 50000, ARR = 12000/50000 = 0.24
        assert abs(result - 0.24) < 0.001

    def test_nan_on_zero_investment(self):
        assert math.isnan(solve_arr(100, 0))


class TestSolveEOQ:
    def test_basic(self):
        result = solve_eoq(10000, 50, 2)
        # sqrt(2 * 10000 * 50 / 2) = sqrt(500000) = 707.1
        assert abs(result - 707.1) < 1.0

    def test_nan_on_zero_demand(self):
        assert math.isnan(solve_eoq(0, 50, 2))


class TestSolveEquivalentAnnualCost:
    def test_basic(self):
        result = solve_equivalent_annual_cost(50000, 0.10, 5)
        # PVIFA(10%, 5) = (1-1.1^-5)/0.1 = 3.791, EAC = 50000/3.791 = 13189
        assert not math.isnan(result)
        assert abs(result - 13189) < 100

    def test_nan_bad_years(self):
        assert math.isnan(solve_equivalent_annual_cost(100, 0.1, 0))


class TestSolveProfitabilityIndex:
    def test_basic(self):
        result = solve_profitability_index(120000, 100000)
        assert abs(result - 1.20) < 0.001

    def test_nan_zero_investment(self):
        assert math.isnan(solve_profitability_index(100, 0))


class TestSolveGearing:
    def test_debt_ratio(self):
        result = solve_gearing(40, 60)
        assert abs(result - 0.40) < 0.001

    def test_nan_zero_value(self):
        assert math.isnan(solve_gearing(0, 0))


class TestSolveInterestCover:
    def test_basic(self):
        result = solve_interest_cover(500000, 100000)
        assert abs(result - 5.0) < 0.001

    def test_nan_zero_interest(self):
        assert math.isnan(solve_interest_cover(100, 0))


class TestSolveEPS:
    def test_basic(self):
        result = solve_eps(2000000, 500000)
        assert abs(result - 4.0) < 0.001


class TestSolveDividendYield:
    def test_basic(self):
        result = solve_dividend_yield(0.50, 10.00)
        assert abs(result - 0.05) < 0.001


class TestSolveDividendCover:
    def test_basic(self):
        result = solve_dividend_cover(0.40, 0.20)
        assert abs(result - 2.0) < 0.001


class TestSolveAssetBeta:
    def test_basic(self):
        # Ba = Be * (E / (E + D(1-T)))
        result = solve_asset_beta(1.2, 40, 60, 0.30)
        denom = 60 + 40 * (1 - 0.30)
        expected = 1.2 * (60 / denom)
        assert abs(result - expected) < 0.001


class TestSolveEquityBeta:
    def test_basic(self):
        # Be = Ba * (E + D(1-T)) / E
        result = solve_equity_beta(0.8, 40, 60, 0.30)
        numer = 60 + 40 * (1 - 0.30)
        expected = 0.8 * (numer / 60)
        assert abs(result - expected) < 0.001


# ---------------------------------------------------------------------------
# Number extraction
# ---------------------------------------------------------------------------

class TestExtractNumbers:
    def test_basic_numbers(self):
        nums = extract_numbers("The cost is $50,000 and rate is 12%")
        values = [n["value"] for n in nums]
        assert abs(values[0] - 50000) < 1
        assert abs(values[1] - 0.12) < 0.001

    def test_empty(self):
        assert extract_numbers("") == []

    def test_bracket_negative(self):
        nums = extract_numbers("loss of (500)")
        assert any(n["value"] == -500 for n in nums)

    def test_year_like_filtered(self):
        nums = extract_numbers("over 5 years the cost")
        years = [n for n in nums if n["is_year_like"]]
        assert len(years) == 0


# ---------------------------------------------------------------------------
# Formula detection
# ---------------------------------------------------------------------------

class TestDetectFormulas:
    def test_detect_npv(self):
        result = detect_formulas("Calculate the NPV of the project")
        assert "npv" in result

    def test_detect_capm(self):
        result = detect_formulas("Using CAPM, what is the cost of equity?")
        assert "capm" in result

    def test_detect_irr(self):
        result = detect_formulas("What is the IRR of this investment?")
        assert "irr" in result

    def test_detect_eoq(self):
        result = detect_formulas("Calculate the EOQ for the inventory")
        assert "eoq" in result

    def test_no_match(self):
        result = detect_formulas("What is the meaning of finance?")
        assert result == []


# ---------------------------------------------------------------------------
# Safe expression evaluation
# ---------------------------------------------------------------------------

class TestSafeExpressionEvaluate:
    def test_simple_addition(self):
        assert safe_expression_evaluate("2 + 3") == 5.0

    def test_multiplication(self):
        assert safe_expression_evaluate("4 * 5") == 20.0

    def test_power(self):
        assert safe_expression_evaluate("2 ** 3") == 8.0

    def test_modulo(self):
        assert safe_expression_evaluate("10 % 3") == 1.0

    def test_sqrt(self):
        assert safe_expression_evaluate("sqrt(16)") == 4.0

    def test_abs(self):
        assert safe_expression_evaluate("abs(-5)") == 5.0

    def test_complex(self):
        result = safe_expression_evaluate("(2 + 3) * 4")
        assert result == 20.0

    def test_unsafe_call_rejected(self):
        assert safe_expression_evaluate("__import__('os')") is None

    def test_unsafe_attribute_rejected(self):
        assert safe_expression_evaluate("().__class__") is None

    def test_unary_plus(self):
        assert safe_expression_evaluate("2 ++ 3") == 5.0

    def test_empty(self):
        assert safe_expression_evaluate("") is None

    def test_times_symbol(self):
        assert safe_expression_evaluate("4 × 5") == 20.0

    def test_divide_symbol(self):
        assert safe_expression_evaluate("10 ÷ 2") == 5.0

    def test_float_with_percent(self):
        result = safe_expression_evaluate("5000 * 0.12")
        assert abs(result - 600.0) < 0.01


# ---------------------------------------------------------------------------
# Expression extraction
# ---------------------------------------------------------------------------

class TestExtractExpressions:
    def test_equal_sign(self):
        exprs = extract_expressions("NPV = 5000 * 0.12 = 600")
        assert len(exprs) >= 1

    def test_empty(self):
        assert extract_expressions("") == []

    def test_arithmetic_chain(self):
        exprs = extract_expressions("The answer is 100 * 0.05")
        assert any("100" in e for e in exprs)


# ---------------------------------------------------------------------------
# Freeform verification
# ---------------------------------------------------------------------------

class TestFreeformVerify:
    def test_matches_correct_ok(self):
        # Explanation computes to ~600 which matches correct value
        reason = freeform_verify(
            "NPV = 5000 * 0.12 = 600",
            [400, 500, 600, 700],
            600.0,
        )
        assert reason is None

    def test_matches_distractor_rejected(self):
        # Explanation computes to ~600 but correct is 500
        reason = freeform_verify(
            "NPV = 5000 * 0.12 = 600",
            [400, 500, 600, 700],
            500.0,
        )
        assert reason == "freeform_mismatch"

    def test_no_expressions(self):
        reason = freeform_verify("The NPV is positive.", [100, 200, 300, 400], 200.0)
        assert reason is None

    def test_matches_nothing_ok(self):
        reason = freeform_verify(
            "The result is 12345 * 67890",
            [100, 200, 300, 400],
            200.0,
        )
        assert reason is None

    def test_matches_correct_but_different_option_value(self):
        reason = freeform_verify(
            "The cost is 1000 * 2 = 2000",
            [1000, 1500, 2000, 2500],
            2000.0,
        )
        assert reason is None


# ---------------------------------------------------------------------------
# verify_numerical_answer — integration
# ---------------------------------------------------------------------------

class TestVerifyNumericalAnswer:
    def test_heuristic_correct_passes(self):
        reason = verify_numerical_answer(
            "NPV at 10% rate with cashflows $100, $200, $300",
            ["$445", "$500", "$555", "$600"],
            "$555",
        )
        assert reason is None

    def test_heuristic_wrong_rejects(self):
        reason = verify_numerical_answer(
            "CAPM: risk free 3%, beta 1.2, market return 10%",
            ["8.4%", "10.2%", "11.4%", "12.8%"],
            "9.5%",  # Wrong — should be 11.4%
        )
        assert reason is not None
        assert "capm" in reason

    def test_non_numeric_options_skipped(self):
        reason = verify_numerical_answer(
            "What is finance?",
            ["Theory", "Practice", "Both", "Neither"],
            "Both",
        )
        assert reason is None

    def test_exact_template_verification(self):
        reason = verify_numerical_answer(
            "WACC question",
            ["7.5%", "8.2%", "9.0%", "9.6%"],
            "9.0%",
            template_ref="wacc",
            template_inputs={
                "equity": 50, "debt": 50,
                "cost_equity": 0.12, "cost_debt": 0.06, "tax_rate": 0.0,
            },
        )
        # WACC = 0.5*0.12 + 0.5*0.06 = 0.09 = 9.0%
        assert reason is None

    def test_exact_template_wrong_rejects(self):
        reason = verify_numerical_answer(
            "WACC question",
            ["7.5%", "8.2%", "9.0%", "9.6%"],
            "7.5%",  # Wrong — should be 9.0%
            template_ref="wacc",
            template_inputs={
                "equity": 50, "debt": 50,
                "cost_equity": 0.12, "cost_debt": 0.06, "tax_rate": 0.0,
            },
        )
        assert reason is not None
        assert "wacc" in reason

    def test_freeform_rejects_distractor_match(self):
        reason = verify_numerical_answer(
            "What is the cost?",
            ["$400", "$500", "$600", "$700"],
            "$500",
            explanation="The answer is 5000 * 0.12 = 600",
        )
        # 600 matches distractor but correct is 500
        assert reason == "freeform_mismatch"

    def test_freeform_passes_correct_match(self):
        reason = verify_numerical_answer(
            "What is the cost?",
            ["$400", "$500", "$600", "$700"],
            "$600",
            explanation="The answer is 5000 * 0.12 = 600",
        )
        assert reason is None

    def test_irr_detection(self):
        reason = verify_numerical_answer(
            "IRR: initial investment $100, returns $60 and $60",
            ["10%", "11%", "12%", "13%"],
            "13%",
        )
        # IRR should be ~13.07%
        assert reason is None

    def test_gearing_detection(self):
        reason = verify_numerical_answer(
            "Gearing ratio: debt $40m, equity $60m",
            ["30%", "35%", "40%", "45%"],
            "40%",
        )
        # Gearing = 40/(40+60) = 40%
        assert reason is None

    def test_arr_detection(self):
        reason = verify_numerical_answer(
            "ARR: average profit $15,000, initial investment $100,000, no residual",
            ["10%", "15%", "20%", "30%"],
            "30%",
        )
        # ARR = 15000 / ((100000+0)/2) = 15000/50000 = 30%
        assert reason is None

    def test_small_numbers_preserved(self):
        reason = verify_numerical_answer(
            "EPS: profit $2m, 500k shares",
            ["$2.50", "$3.00", "$4.00", "$5.00"],
            "$4.00",
        )
        # EPS = 2000000/500000 = 4
        assert reason is None

    def test_eps_wrong_rejects(self):
        reason = verify_numerical_answer(
            "EPS: profit $2,000,000, shares 500,000",
            ["$2.50", "$3.00", "$4.00", "$5.00"],
            "$3.00",
        )
        # EPS = 2,000,000/500,000 = 4.00, not 3.00
        assert reason is not None


# ===================================================================
# New concept solver tests
# ===================================================================

class TestSolvePeRatio:
    def test_basic(self):
        result = solve_pe_ratio(10.0, 2.0)
        assert abs(result - 5.0) < 0.001

    def test_inverse(self):
        result = solve_pe_ratio(20.0, 0.50)
        assert abs(result - 40.0) < 0.001

    def test_nan_on_zero_eps(self):
        assert math.isnan(solve_pe_ratio(10.0, 0.0))


class TestSolveRoe:
    def test_basic(self):
        result = solve_roe(500000, 2000000)
        assert abs(result - 0.25) < 0.001

    def test_nan_on_zero_equity(self):
        assert math.isnan(solve_roe(100, 0))


class TestSolveCostOfPreference:
    def test_basic(self):
        result = solve_cost_of_preference(0.08, 1.00)
        assert abs(result - 0.08) < 0.001

    def test_above_par(self):
        result = solve_cost_of_preference(0.08, 1.20)
        assert abs(result - 0.0667) < 0.001

    def test_nan_on_zero_price(self):
        assert math.isnan(solve_cost_of_preference(0.05, 0))


class TestSolveTerp:
    def test_one_for_four(self):
        result = solve_terp(2.00, 1.50, 4)
        expected = (4 * 2.00 + 1.50) / 5.0
        assert abs(result - expected) < 0.001

    def test_one_for_two(self):
        result = solve_terp(3.00, 2.00, 2)
        expected = (2 * 3.00 + 2.00) / 3.0
        assert abs(result - expected) < 0.001

    def test_nan_on_zero_ratio(self):
        assert math.isnan(solve_terp(10, 5, 0))


class TestSolvePerpetuityNpv:
    def test_basic(self):
        result = solve_perpetuity_npv(1000, 0.10)
        assert abs(result - 10000) < 0.01

    def test_nan_on_zero_rate(self):
        assert math.isnan(solve_perpetuity_npv(100, 0))


class TestSolveRoce:
    def test_basic(self):
        result = solve_roce(50000, 250000)
        assert abs(result - 0.20) < 0.001

    def test_nan_on_zero_capital(self):
        assert math.isnan(solve_roce(100, 0))


# ---------------------------------------------------------------------------
# DSL-registered formula solvers (accessed via _FORMULA_SOLVERS)
# ---------------------------------------------------------------------------

class TestSolveDividendGrowthRate:
    def test_basic(self):
        from studyplan.numerical_solver import _FORMULA_SOLVERS
        s = _FORMULA_SOLVERS["dividend_growth_rate"]
        result = s(roe=0.15, retention_ratio=0.6)
        assert abs(result - 0.09) < 0.001

    def test_nan_on_missing_param(self):
        from studyplan.numerical_solver import _FORMULA_SOLVERS
        s = _FORMULA_SOLVERS["dividend_growth_rate"]
        assert math.isnan(s(roe=0.15))

    def test_detection(self):
        result = detect_formulas("What is the dividend growth rate?")
        assert "dividend_growth_rate" in result


class TestSolveEarningYield:
    def test_basic(self):
        from studyplan.numerical_solver import _FORMULA_SOLVERS
        s = _FORMULA_SOLVERS["earning_yield"]
        result = s(eps=2.5, market_price=50.0)
        assert abs(result - 0.05) < 0.001

    def test_detection(self):
        result = detect_formulas("Calculate the earnings yield.")
        assert "earning_yield" in result


class TestSolveQuickRatio:
    def test_basic(self):
        from studyplan.numerical_solver import _FORMULA_SOLVERS
        s = _FORMULA_SOLVERS["quick_ratio"]
        result = s(current_assets=100.0, inventory=30.0, current_liabilities=50.0)
        assert abs(result - 1.4) < 0.001

    def test_nan_on_zero_liabilities(self):
        from studyplan.numerical_solver import _FORMULA_SOLVERS
        s = _FORMULA_SOLVERS["quick_ratio"]
        result = s(current_assets=100.0, inventory=30.0, current_liabilities=0.0)
        assert math.isnan(result) or abs(result) > 1e6

    def test_detection(self):
        result = detect_formulas("What is the acid test ratio?")
        assert "quick_ratio" in result


class TestSolveAssetTurnover:
    def test_basic(self):
        from studyplan.numerical_solver import _FORMULA_SOLVERS
        s = _FORMULA_SOLVERS["asset_turnover"]
        result = s(sales=500.0, capital_employed=250.0)
        assert abs(result - 2.0) < 0.001

    def test_detection(self):
        result = detect_formulas("Calculate the asset turnover.")
        assert "asset_turnover" in result
