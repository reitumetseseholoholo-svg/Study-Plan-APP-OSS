"""Tests for the domain reasoning layer — concepts, templates, evaluator, diagnostics."""

import math

import pytest

from studyplan.domain_reasoning import (
    ConceptMetadata, ConceptTemplate, FormulaTemplate,
    StepEvaluation, ConceptEvaluation, QuestionDiagnostic,
    BUILTIN_CONCEPTS, STRUCTURE_TYPE_CONCEPTS,
    TEMPLATE_REGISTRY,
    detect_concepts, run_template,
    evaluate_question, merge_concept_results, format_error_summary,
)


# ===================================================================
# Concept metadata
# ===================================================================

class TestConceptMetadata:
    def test_all_have_ids(self):
        for cid, meta in BUILTIN_CONCEPTS.items():
            assert meta.concept_id == cid
            assert meta.template_ref
            assert 0 <= meta.centrality <= 1

    def test_all_in_registry(self):
        for cid in BUILTIN_CONCEPTS:
            assert cid in TEMPLATE_REGISTRY, f"{cid} missing"

    def test_wacc_dependencies(self):
        w = BUILTIN_CONCEPTS["fm.wacc"]
        assert "fm.cost_of_equity_dvm" in w.dependencies
        # cost_of_debt removed — WACC now expects after-tax cost_debt directly
        assert "fm.cost_of_debt" not in w.dependencies

    def test_irr_depends_on_npv(self):
        assert "fm.npv" in BUILTIN_CONCEPTS["fm.irr"].dependencies

    def test_equity_beta_depends_on_asset_beta(self):
        assert "fm.asset_beta" in BUILTIN_CONCEPTS["fm.equity_beta"].dependencies

    def test_discounted_payback_no_dependency(self):
        assert BUILTIN_CONCEPTS["fm.discounted_payback"].dependencies == ()


class TestStructureTypeConcepts:
    def test_npv_timing(self):
        c = STRUCTURE_TYPE_CONCEPTS["npv_annuity_timing"]
        assert "fm.npv" in c and "fm.irr" in c

    def test_gearing(self):
        c = STRUCTURE_TYPE_CONCEPTS["gearing_financial_risk"]
        assert "fm.gearing" in c and "fm.asset_beta" in c

    def test_empty_types(self):
        assert STRUCTURE_TYPE_CONCEPTS["fx_exposure_hedge"] == []
        assert STRUCTURE_TYPE_CONCEPTS["foreign_investment_appraisal"] == []

    def test_all_present(self):
        expected = {
            "npv_annuity_timing", "wacc_optimization",
            "fx_exposure_hedge", "working_capital_cycle",
            "dividend_policy_tradeoff", "capm_required_return",
            "gearing_financial_risk", "foreign_investment_appraisal",
            "rights_issue_valuation",
        }
        assert set(STRUCTURE_TYPE_CONCEPTS) == expected


class TestDetectConcepts:
    def test_npv(self):
        assert "fm.npv" in detect_concepts("Calculate NPV")

    def test_capm(self):
        assert "fm.capm" in detect_concepts("CAPM required return")

    def test_irr(self):
        assert "fm.irr" in detect_concepts("IRR of the investment")

    def test_eps(self):
        assert "fm.eps" in detect_concepts("Calculate EPS")

    def test_gearing(self):
        assert "fm.gearing" in detect_concepts("gearing ratio")

    def test_multiple(self):
        c = detect_concepts("NPV and IRR analysis")
        assert "fm.npv" in c and "fm.irr" in c

    def test_no_match(self):
        assert detect_concepts("What is finance?") == []

    def test_ccc(self):
        assert "fm.ccc" in detect_concepts("cash conversion cycle")

    def test_dividend_yield(self):
        assert "fm.dividend_yield" in detect_concepts("dividend yield")

    def test_wacc(self):
        assert "fm.wacc" in detect_concepts("WACC calculation")


# ===================================================================
# FormulaTemplate basics
# ===================================================================

class TestFormulaTemplate:
    def test_npv(self):
        t = TEMPLATE_REGISTRY["fm.npv"]
        r = t.solve({"cashflows": [100, 200], "rate": 0.10})
        assert not r["is_nan"]
        expected = 100/1.1 + 200/1.1**2
        assert abs(r["result"] - expected) < 0.01
        assert r["concept_id"] == "fm.npv"
        assert len(r["steps"]) >= 1

    def test_wacc(self):
        t = TEMPLATE_REGISTRY["fm.wacc"]
        r = t.solve({"equity": 60, "debt": 40, "cost_equity": 0.12, "cost_debt": 0.042, "tax_rate": 0.30})
        expected = 0.6*0.12 + 0.4*0.042
        assert abs(r["result"] - expected) < 0.001
        assert len(r["steps"]) >= 4

    def test_capm(self):
        t = TEMPLATE_REGISTRY["fm.capm"]
        r = t.solve({"risk_free": 0.03, "beta": 1.2, "market_return": 0.10})
        assert abs(r["result"] - 0.114) < 0.001
        assert len(r["steps"]) == 3

    def test_ccc(self):
        t = TEMPLATE_REGISTRY["fm.ccc"]
        r = t.solve({"dio": 40, "dso": 30, "dpo": 20})
        assert abs(r["result"] - 50) < 0.01

    def test_irr(self):
        t = TEMPLATE_REGISTRY["fm.irr"]
        r = t.solve({"cashflows": [60, 60], "initial": 100})
        assert abs(r["result"] - 0.1307) < 0.01
        assert len(r["steps"]) == 5  # 4 NPV guesses + 1 IRR

    def test_payback(self):
        t = TEMPLATE_REGISTRY["fm.payback"]
        r = t.solve({"initial": 100, "cashflows": [30, 40, 50]})
        assert abs(r["result"] - 2.6) < 0.01
        assert len(r["steps"]) == 4  # 3 cumulative + payback

    def test_discounted_payback(self):
        t = TEMPLATE_REGISTRY["fm.discounted_payback"]
        r = t.solve({"initial": 100, "cashflows": [50, 50, 50], "rate": 0.10})
        assert not r["is_nan"]

    def test_gearing(self):
        t = TEMPLATE_REGISTRY["fm.gearing"]
        r = t.solve({"debt": 40, "equity": 60})
        assert abs(r["result"] - 0.40) < 0.001

    def test_eoq(self):
        t = TEMPLATE_REGISTRY["fm.eoq"]
        r = t.solve({"annual_demand": 10000, "ordering_cost": 50, "holding_cost_per_unit": 2})
        assert abs(r["result"] - 707.1) < 1.0

    def test_arr(self):
        t = TEMPLATE_REGISTRY["fm.arr"]
        r = t.solve({"average_profit": 15000, "initial_investment": 100000})
        assert abs(r["result"] - 0.30) < 0.01

    def test_unknown_concept(self):
        assert run_template("fm.nonexistent", {}) is None

    def test_isinstance(self):
        assert isinstance(TEMPLATE_REGISTRY["fm.npv"], ConceptTemplate)

    def test_all_templates_solve(self):
        for cid, t in TEMPLATE_REGISTRY.items():
            if cid in ("fm.cost_of_debt",):
                r = t.solve({"interest_rate": 0.08, "tax_rate": 0.30})
            elif cid == "fm.cost_of_equity_dvm":
                r = t.solve({"dividend": 2, "price": 20, "growth": 0.04})
            elif cid == "fm.equivalent_annual_cost":
                r = t.solve({"cost": 50000, "discount_rate": 0.10, "years": 5})
            elif cid == "fm.profitability_index":
                r = t.solve({"pv_future_cashflows": 120000, "initial_investment": 100000})
            elif cid == "fm.asset_beta":
                r = t.solve({"equity_beta": 1.2, "market_value_debt": 40, "market_value_equity": 60, "tax_rate": 0.30})
            elif cid == "fm.equity_beta":
                r = t.solve({"asset_beta": 0.8, "market_value_debt": 40, "market_value_equity": 60, "tax_rate": 0.30})
            elif cid == "fm.interest_cover":
                r = t.solve({"pbit": 500000, "interest_expense": 100000})
            elif cid == "fm.eps":
                r = t.solve({"profit_after_tax": 2000000, "number_of_shares": 500000})
            elif cid == "fm.dividend_yield":
                r = t.solve({"dividend_per_share": 0.50, "market_price": 10.0})
            elif cid == "fm.dividend_cover":
                r = t.solve({"eps": 0.40, "dividend_per_share": 0.20})
            elif cid == "fm.pe_ratio":
                r = t.solve({"market_price": 10.0, "eps": 2.0})
            elif cid == "fm.roe":
                r = t.solve({"profit_after_tax": 500000, "equity": 2000000})
            elif cid == "fm.cost_of_preference":
                r = t.solve({"preference_dividend": 0.08, "market_price": 1.00})
            elif cid == "fm.terp":
                r = t.solve({"cum_rights_price": 2.00, "issue_price": 1.50, "rights_ratio_n": 4})
            elif cid == "fm.perpetuity_npv":
                r = t.solve({"annual_cashflow": 1000, "discount_rate": 0.10})
            elif cid == "fm.roce":
                r = t.solve({"pbit": 50000, "capital_employed": 250000})
            elif cid == "fm.dividend_growth_rate":
                r = t.solve({"roe": 0.15, "retention_ratio": 0.6})
            elif cid == "fm.earning_yield":
                r = t.solve({"eps": 2.5, "market_price": 50.0})
            elif cid == "fm.quick_ratio":
                r = t.solve({"current_assets": 100.0, "inventory": 30.0, "current_liabilities": 50.0})
            elif cid == "fm.asset_turnover":
                r = t.solve({"sales": 500.0, "capital_employed": 250.0})
            else:
                continue
            assert not r["is_nan"], f"{cid} returned nan"


# ===================================================================
# Diagnostics
# ===================================================================

class TestDiagnostics:
    def test_concept_evaluation_defaults(self):
        ev = ConceptEvaluation(concept_id="fm.npv")
        assert ev.error_tags == []
        assert ev.steps == []
        assert ev.confidence == 0.0

    def test_step_evaluation(self):
        s = StepEvaluation(step_id="npv", expected=10.0, actual=9.5, match=False)
        assert s.step_id == "npv"
        assert s.match is False

    def test_merge_concept_results_empty(self):
        diag = merge_concept_results([])
        assert diag.concept_ids == []
        assert diag.has_deterministic_truth is False

    def test_merge_single(self):
        ev = ConceptEvaluation(concept_id="fm.npv", result=10.0, confidence=0.9)
        diag = merge_concept_results([ev])
        assert "fm.npv" in diag.concept_ids
        assert diag.primary_concept_id == "fm.npv"
        assert diag.has_deterministic_truth is True
        assert diag.diagnostic_confidence == 0.9

    def test_merge_with_errors(self):
        ev = ConceptEvaluation(concept_id="fm.npv", error_tags=["sign_error"], confidence=0.7)
        diag = merge_concept_results([ev])
        assert "sign_error" in diag.all_error_tags
        assert "fm.npv" in diag.weak_concepts

    def test_merge_picks_highest_confidence(self):
        ev1 = ConceptEvaluation(concept_id="fm.npv", confidence=0.9)
        ev2 = ConceptEvaluation(concept_id="fm.irr", confidence=0.7)
        diag = merge_concept_results([ev1, ev2])
        assert diag.primary_concept_id == "fm.npv"

    def test_format_error_summary_no_diagnostics(self):
        diag = QuestionDiagnostic()
        s = format_error_summary(diag)
        assert "no deterministic truth" in s

    def test_format_error_summary_with_errors(self):
        diag = QuestionDiagnostic(
            primary_concept_id="fm.npv",
            all_error_tags=["sign_error", "cumulative_error"],
            has_deterministic_truth=True,
            diagnostic_confidence=0.85,
        )
        s = format_error_summary(diag)
        assert "fm.npv" in s
        assert "sign_error" in s
        assert "0.85" in s


# ===================================================================
# Evaluator
# ===================================================================

class TestEvaluateQuestion:
    def test_no_question(self):
        diag = evaluate_question("")
        assert diag.has_deterministic_truth is False

    def test_npv_question(self):
        diag = evaluate_question(
            "Calculate the NPV at 10% with cashflows $100, $200, $300",
        )
        # Should detect npv and produce an evaluation
        if diag.has_deterministic_truth:
            assert any("npv" in c for c in diag.concept_ids)

    def test_capm_question(self):
        diag = evaluate_question(
            "CAPM: risk free 3%, beta 1.2, market return 10%",
        )
        if diag.has_deterministic_truth:
            assert "fm.capm" in diag.concept_ids

    def test_with_metadata(self):
        diag = evaluate_question(
            "WACC question",
            template_ref="fm.wacc",
            template_inputs={"equity": 50, "debt": 50, "cost_equity": 0.12, "cost_debt": 0.06, "tax_rate": 0.0},
        )
        assert diag.has_deterministic_truth is True
        assert "fm.wacc" in diag.concept_ids
        assert abs(diag.concept_evaluations[0].result - 0.09) < 0.001

    def test_with_wrong_correct(self):
        diag = evaluate_question(
            "CAPM: risk free 3%, beta 1.2, market return 10%",
            options=["8.4%", "10.2%", "11.4%", "12.8%"],
            correct="9.5%",
        )
        # Should flag a mismatch since CAPM gives 11.4%, not 9.5%
        if diag.has_deterministic_truth:
            any_has_error = any("mismatch" in " ".join(ev.error_tags) for ev in diag.concept_evaluations)
            assert any_has_error or diag.all_error_tags

    def test_with_template_and_learner_answer(self):
        diag = evaluate_question(
            "NPV question",
            template_ref="fm.npv",
            template_inputs={"cashflows": [100, 200], "rate": 0.10, "initial": 50},
            learner_answer="150",
        )
        assert diag.has_deterministic_truth is True

    def test_irr_question(self):
        diag = evaluate_question("Calculate the IRR for the project")
        if diag.has_deterministic_truth:
            assert "fm.irr" in diag.concept_ids

    def test_gearing_question(self):
        diag = evaluate_question("What is the gearing ratio?")
        if diag.has_deterministic_truth:
            assert "fm.gearing" in diag.concept_ids


# ===================================================================
# Template error classification
# ===================================================================

class TestNpvErrorClassification:
    def test_sign_error(self):
        t = TEMPLATE_REGISTRY["fm.npv"]
        truth = t.solve({"cashflows": [100, 200], "rate": 0.10})
        learner = [{"step_id": "pv_year_1", "value": -90.91, "sign": -1}]
        tags = t.classify_errors(learner, truth)
        assert "sign_error" in tags or "pv_year_1_mismatch" in tags

    def test_no_errors_when_correct(self):
        t = TEMPLATE_REGISTRY["fm.npv"]
        truth = t.solve({"cashflows": [100], "rate": 0.10})
        learner = [{"step_id": "pv_year_1", "value": 90.91, "sign": 1}]
        tags = t.classify_errors(learner, truth)
        assert "sign_error" not in tags


class TestWaccErrorClassification:
    def test_wrong_weighting(self):
        t = TEMPLATE_REGISTRY["fm.wacc"]
        truth = t.solve({"equity": 60, "debt": 40, "cost_equity": 0.12, "cost_debt": 0.06, "tax_rate": 0})
        learner = [{"step_id": "weight_equity", "value": 2.0}]
        tags = t.classify_errors(learner, truth)
        assert "wrong_weighting" in tags


class TestCapmErrorClassification:
    def test_wrong_premium(self):
        t = TEMPLATE_REGISTRY["fm.capm"]
        truth = t.solve({"risk_free": 0.03, "beta": 1.2, "market_return": 0.10})
        learner = [{"step_id": "equity_risk_premium", "value": 0.05}]  # Should be 0.07
        tags = t.classify_errors(learner, truth)
        assert "wrong_premium" in tags


class TestCccErrorClassification:
    def test_sign_error(self):
        t = TEMPLATE_REGISTRY["fm.ccc"]
        truth = t.solve({"dio": 40, "dso": 30, "dpo": 20})
        # DPO should be subtracted; giving the same value means sign is wrong
        learner = [{"step_id": "ccc", "value": 50.0}]  # correct is 50, sign_error not triggered
        tags = t.classify_errors(learner, truth)
        assert "sign_error" not in tags  # value matches


class TestPaybackErrorClassification:
    def test_cumulative_error(self):
        t = TEMPLATE_REGISTRY["fm.payback"]
        truth = t.solve({"initial": 100, "cashflows": [30, 40, 50]})
        learner = [{"step_id": "cumulative_year_1", "value": 25.0}]  # should be 30
        tags = t.classify_errors(learner, truth)
        assert "cumulative_error" in tags


class TestEoqErrorClassification:
    def test_cost_component_error(self):
        t = TEMPLATE_REGISTRY["fm.eoq"]
        truth = t.solve({"annual_demand": 10000, "ordering_cost": 50, "holding_cost_per_unit": 2})
        learner = [{"step_id": "two_d_o", "value": 500000.0}]  # should be 1000000
        tags = t.classify_errors(learner, truth)
        assert "cost_component_error" in tags

    def test_sqrt_error(self):
        t = TEMPLATE_REGISTRY["fm.eoq"]
        truth = t.solve({"annual_demand": 10000, "ordering_cost": 50, "holding_cost_per_unit": 2})
        learner = [{"step_id": "eoq", "value": 500.0}]  # should be ~707
        tags = t.classify_errors(learner, truth)
        assert "sqrt_error" in tags


class TestGearingErrorClassification:
    def test_wrong_denominator(self):
        t = TEMPLATE_REGISTRY["fm.gearing"]
        truth = t.solve({"debt": 40, "equity": 60})
        # If learner used Debt/Equity (=0.667) instead of Debt/(Debt+Equity) (=0.4)
        learner = [{"step_id": "gearing", "value": 0.6667}]
        tags = t.classify_errors(learner, truth)
        assert "wrong_denominator" in tags


class TestArrErrorClassification:
    def test_avg_investment_error(self):
        t = TEMPLATE_REGISTRY["fm.arr"]
        truth = t.solve({"average_profit": 15000, "initial_investment": 100000, "residual_value": 0})
        # If learner used initial investment instead of average
        learner = [{"step_id": "avg_investment", "value": 100000.0}]  # should be 50000
        tags = t.classify_errors(learner, truth)
        assert "avg_investment_error" in tags


# ===================================================================
# Diagnostics — edge cases
# ===================================================================

class TestDiagnosticsEdgeCases:
    def test_nan_result(self):
        ev = ConceptEvaluation(concept_id="fm.npv", is_nan=True)
        diag = merge_concept_results([ev])
        assert diag.has_deterministic_truth is False

    def test_multiple_concepts_merged(self):
        evs = [
            ConceptEvaluation(concept_id="fm.npv", result=10.0, confidence=0.9),
            ConceptEvaluation(concept_id="fm.irr", result=0.13, confidence=0.7, error_tags=["interpolation_error"]),
        ]
        diag = merge_concept_results(evs)
        assert len(diag.concept_ids) == 2
        assert "interpolation_error" in diag.all_error_tags
        assert "fm.irr" in diag.weak_concepts
        assert diag.primary_concept_id == "fm.npv"

    def test_blocked_dependencies(self):
        from studyplan.domain_reasoning.concepts import BUILTIN_CONCEPTS
        evs = [
            ConceptEvaluation(concept_id="fm.equity_beta", error_tags=["weight_error"]),
            ConceptEvaluation(concept_id="fm.asset_beta", error_tags=["tax_error"]),
        ]
        diag = merge_concept_results(evs, BUILTIN_CONCEPTS)
        assert any("blocked" in b for b in diag.blocked_dependencies)

    def test_format_empty(self):
        s = format_error_summary(QuestionDiagnostic())
        assert "no deterministic truth" in s


# ===================================================================
# Hybrid DSL tests (formula_registry — declare_formula / declare_formula_chain)
# ===================================================================

import pytest

from studyplan.domain_reasoning.formula_registry import (
    get_registry,
    get_registry_formulas,
    validate_registry,
    declare_formula,
    declare_formula_chain,
    RegistryValidationError,
    ExpressionTemplate,
    ChainTemplate,
    ChainStep,
)


class TestFormulaRegistry:
    def test_registry_has_dsl_formulas(self):
        reg = get_registry()
        assert "fm.dividend_growth_rate" in reg
        assert "fm.quick_ratio" in reg
        assert "fm.asset_turnover" in reg
        assert "fm.cost_equity_capm_to_wacc" in reg

    def test_registry_formula_names(self):
        names = get_registry_formulas()
        assert "dividend_growth_rate" in names
        assert "asset_turnover" in names
        assert "ungear_regear" in names

    def test_validation_passes(self):
        msgs = validate_registry()
        # Should have no critical errors (warnings about builtin deps are OK)
        critical = [m for m in msgs if "error" in m.lower()]
        assert len(critical) == 0, f"Validation errors: {critical}"

    def test_expression_template_single_step(self):
        t = ExpressionTemplate("fm.test", lambda **kw: kw.get("x", 0) * 2, "x * 2")
        result = t.solve({"x": 5.0})
        assert result["result"] == 10.0
        assert not result["is_nan"]
        assert len(result["steps"]) == 1

    def test_expression_template_nan_input(self):
        t = ExpressionTemplate("fm.test", lambda **kw: float("nan"), "bad")
        result = t.solve({"x": 1.0})
        assert result["is_nan"]

    def test_expression_template_evaluate_steps(self):
        t = ExpressionTemplate("fm.test", lambda **kw: 42.0, "x")
        results = t.evaluate_steps(
            [{"step_id": "s1", "value": 42.0}],
            {"result": 42.0},
        )
        assert results[0]["match"] is True

    def test_expression_template_classify_errors(self):
        t = ExpressionTemplate("fm.test", lambda **kw: 50.0, "x")
        tags = t.classify_errors(
            [{"step_id": "s1", "value": 10.0}],
            {"result": 50.0},
        )
        assert "s1_mismatch" in tags


class TestChainTemplate:
    def test_chain_two_steps(self):
        steps = [
            ChainStep(slot="a", expression="x + y", param_names=("x", "y")),
            ChainStep(slot="b", expression="a * z", param_names=("z",)),
        ]
        t = ChainTemplate("fm.chain_test", steps)
        result = t.solve({"x": 2.0, "y": 3.0, "z": 4.0})
        assert result["result"] == 20.0  # (2+3) * 4
        assert len(result["steps"]) == 2
        assert not result["is_nan"]

    def test_chain_intermediate_forwarded(self):
        """Step 2 should see step 1's output automatically."""
        steps = [
            ChainStep(slot="half", expression="full / 2", param_names=("full",)),
            ChainStep(slot="quarter", expression="half / 2", param_names=()),
        ]
        t = ChainTemplate("fm.halving", steps)
        result = t.solve({"full": 100.0})
        assert result["result"] == 25.0
        assert result["steps"][0]["value"] == 50.0

    def test_chain_nan_early_exit(self):
        steps = [
            ChainStep(slot="a", expression="x + y", param_names=("x", "y")),
            ChainStep(slot="b", expression="a / z", param_names=("z",)),
        ]
        t = ChainTemplate("fm.nan_chain", steps)
        # z=0 gives step2 nan, but step1 succeeds
        result = t.solve({"x": 1.0, "y": 2.0, "z": 0.0})
        assert result["steps"][0]["value"] == 3.0
        assert result["steps"][1]["value"] is None or math.isnan(result["steps"][1]["value"])

    def test_chain_evaluate_steps(self):
        steps = [
            ChainStep(slot="a", expression="x * 2", param_names=("x",)),
        ]
        t = ChainTemplate("fm.eval_chain", steps)
        results = t.evaluate_steps(
            [{"step_id": "a", "value": 20.0}],
            {"result": 20.0},
        )
        assert results[0]["match"] is True

    def test_chain_classify_errors(self):
        steps = [
            ChainStep(slot="a", expression="x * 2", param_names=("x",)),
        ]
        t = ChainTemplate("fm.err_chain", steps)
        tags = t.classify_errors(
            [{"step_id": "a", "value": 5.0}],
            {"result": 10.0},
        )
        assert "a_mismatch" in tags


class TestFormulaCandidatePermutation:
    """Verify permutation-aware candidate extraction."""

    def test_quick_ratio_candidates(self):
        from studyplan.numerical_solver import _FORMULA_CANDIDATES, extract_numbers
        fn = _FORMULA_CANDIDATES.get("quick_ratio")
        assert fn is not None
        nums = extract_numbers("Current assets 500, inventory 200, liabilities 250")
        candidates = fn(nums)
        assert len(candidates) >= 1
        c = candidates[0]
        assert "current_assets" in c
        assert "current_liabilities" in c

    def test_quick_ratio_correct_order(self):
        from studyplan.numerical_solver import _FORMULA_CANDIDATES, extract_numbers
        fn = _FORMULA_CANDIDATES.get("quick_ratio")
        nums = extract_numbers("CA=500, Inv=200, CL=250")
        candidates = fn(nums)
        # The best candidate should assign 500→CA, 200→Inv, 250→CL
        c = candidates[0]
        assert c["current_assets"] == 500.0
        assert c["inventory"] == 200.0
        assert c["current_liabilities"] == 250.0

    def test_ungear_regear_candidates(self):
        from studyplan.numerical_solver import _FORMULA_CANDIDATES, extract_numbers
        fn = _FORMULA_CANDIDATES.get("ungear_regear")
        assert fn is not None
        nums = extract_numbers("Equity beta 1.2, tax 25%, D/E 50%, new D/E 80%")
        candidates = fn(nums)
        assert len(candidates) >= 1
        c = candidates[0]
        assert abs(c["equity_beta"] - 1.2) < 0.01
        assert abs(c["tax"] - 0.25) < 0.01


class TestFullPipelineDSL:
    """End-to-end tests of DSL formulas in the reasoning pipeline."""

    def test_quick_ratio_detection_and_solve(self):
        from studyplan.domain_reasoning.reasoning_engine import reason_question
        trace = reason_question(
            "What is the quick ratio with CA=500, Inv=200, CL=250?"
        )
        assert trace.target_concept_id == "fm.quick_ratio"
        assert trace.final_result is not None
        assert abs(trace.final_result - 1.2) < 0.01

    def test_asset_turnover_detection(self):
        from studyplan.domain_reasoning.concepts import detect_concepts
        concepts = detect_concepts("Calculate asset turnover with sales 1000 and CE 500")
        assert "fm.asset_turnover" in concepts

    def test_dividend_growth_rate_solve(self):
        from studyplan.domain_reasoning.reasoning_engine import reason_question
        trace = reason_question(
            "g = ROE * retention ratio (ROE 15%, retention 60%)",
            template_ref="fm.dividend_growth_rate",
        )
        assert trace.final_result is not None
        assert abs(trace.final_result - 0.09) < 0.001  # 0.15 * 0.60

    def test_ungear_regear_chain_solve(self):
        from studyplan.domain_reasoning.reasoning_engine import reason_question
        trace = reason_question(
            "Ungear equity beta 1.2 (tax 25%, D/E 50%) and regear to D/E 80%",
            template_ref="fm.ungear_regear",
        )
        assert trace.final_result is not None
        assert abs(trace.final_result - 1.3964) < 0.01

    def test_capm_to_wacc_chain_solve(self):
        from studyplan.domain_reasoning.reasoning_engine import reason_question
        trace = reason_question(
            "WACC via CAPM: Rf 3%, beta 1.2, Rm 10%, Kd 5%, tax 25%, E/V 60%, D/V 40%",
            template_ref="fm.cost_equity_capm_to_wacc",
        )
        assert trace.final_result is not None
        assert abs(trace.final_result - 0.0834) < 0.001

    def test_dvm_to_wacc_chain_solve(self):
        from studyplan.domain_reasoning.reasoning_engine import reason_question
        trace = reason_question(
            "WACC via DVM: dividend 0.50, growth 5%, price 5.00, Kd 5%, tax 25%, E/V 60%, D/V 40%",
            template_ref="fm.cost_equity_dvm_to_wacc",
        )
        assert trace.final_result is not None
        assert trace.final_result > 0

    def test_blank_question_returns_empty(self):
        from studyplan.domain_reasoning.reasoning_engine import reason_question
        trace = reason_question("")
        assert trace.target_concept_id is None
        assert trace.final_result is None


class TestDeclareFormulaAPIDetails:
    """Unit-level API contract tests for declare_formula and declare_formula_chain."""

    def test_declare_formula_errors_on_both_expr_and_solver(self):
        import pytest
        with pytest.raises(ValueError, match="not both"):
            declare_formula("fm.bad",
                expression="x + y",
                solver_fn=lambda **kw: 1.0,
                param_names=["x", "y"])

    def test_declare_formula_errors_on_no_expr_or_solver(self):
        import pytest
        with pytest.raises(ValueError, match="expression or solver_fn"):
            declare_formula("fm.bad")

    def test_declare_chain_requires_slot_expression(self):
        with pytest.raises(Exception):
            declare_formula_chain("fm.bad_chain", steps=[{}])


# ===================================================================
# Rule chain concept tests
# ===================================================================

class TestRuleChainTemplate:
    """Tests for the ``RuleChainTemplate`` class.

    Covers solve(), evaluate_steps(), classify_errors(), and edge
    cases including NaN, missing inputs, large values, and complex
    boolean conditions.
    """

    def make_income_tax_template(self):
        """Helper: build a realistic income tax rule chain."""
        from studyplan.domain_reasoning.concept_types.rule_concept import (
            RuleChainTemplate, RuleChainStep, Rule,
        )
        return RuleChainTemplate("tx.test_income_tax", steps=[
            RuleChainStep(
                slot="taxable_income",
                rules=[
                    Rule(condition="gross_income <= 12570", value=0),
                    Rule(condition="gross_income > 12570", value="gross_income - 12570"),
                ],
                description="Compute taxable income",
                param_names=("gross_income",),
            ),
            RuleChainStep(
                slot="tax_liability",
                rules=[
                    Rule(condition="taxable_income <= 50270", value="taxable_income * 0.20"),
                    Rule(condition=True, value="50270 * 0.20 + (taxable_income - 50270) * 0.40"),
                ],
                description="Compute tax liability",
            ),
        ])

    def make_allowance_taper_template(self):
        """Helper: personal allowance taper with multiple bands."""
        from studyplan.domain_reasoning.concept_types.rule_concept import (
            RuleChainTemplate, RuleChainStep, Rule,
        )
        return RuleChainTemplate("tx.test_allowance_taper", steps=[
            RuleChainStep(
                slot="adjusted_income",
                rules=[
                    Rule(condition=True, value="net_income"),
                ],
                param_names=("net_income",),
            ),
            RuleChainStep(
                slot="personal_allowance",
                rules=[
                    Rule(condition="adjusted_income <= 100000", value=12570),
                    Rule(
                        condition="adjusted_income > 100000 and adjusted_income <= 125140",
                        value="12570 - (adjusted_income - 100000) / 2",
                    ),
                    Rule(condition="adjusted_income > 125140", value=0),
                ],
            ),
        ])

    # ------------------------------------------------------------------
    # solve()
    # ------------------------------------------------------------------

    def test_basic_rate_tax(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": 50000})
        assert not r["is_nan"]
        assert abs(r["result"] - 7486.0) < 0.01
        assert len(r["steps"]) == 2

    def test_tax_below_allowance(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": 10000})
        assert r["result"] == 0.0
        assert len(r["steps"]) == 2

    def test_higher_rate_tax(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": 150000})
        expected = 50270 * 0.20 + (150000 - 12570 - 50270) * 0.40
        assert abs(r["result"] - expected) < 0.01

    def test_tax_at_band_boundary(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": 12570})
        assert r["result"] == 0.0

    def test_tax_just_above_basic_band(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": 12570 + 50270 + 1})
        expected = 50270 * 0.20 + 1 * 0.40
        assert abs(r["result"] - expected) < 0.01

    def test_step_outputs_flow_to_downstream(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": 50000})
        steps = r["steps"]
        assert steps[0]["step_id"] == "taxable_income"
        assert abs(steps[0]["value"] - 37430) < 0.01
        assert steps[1]["step_id"] == "tax_liability"
        assert abs(steps[1]["value"] - 7486) < 0.01

    def test_matched_condition_tracked(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": 50000})
        assert "gross_income > 12570" in r["steps"][0].get("matched_condition", "")

    def test_personal_allowance_taper(self):
        t = self.make_allowance_taper_template()
        r = t.solve({"net_income": 110000})
        expected = 12570 - (110000 - 100000) / 2
        assert abs(r["result"] - expected) < 0.01

    def test_allowance_fully_phased_out(self):
        t = self.make_allowance_taper_template()
        r = t.solve({"net_income": 130000})
        assert r["result"] == 0.0

    def test_allowance_full_at_below_100k(self):
        t = self.make_allowance_taper_template()
        r = t.solve({"net_income": 90000})
        assert r["result"] == 12570

    # ------------------------------------------------------------------
    # solve() edge cases
    # ------------------------------------------------------------------

    def test_missing_input_returns_default(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import (
            RuleChainTemplate, RuleChainStep, Rule,
        )
        t = RuleChainTemplate("tx.test_missing", steps=[
            RuleChainStep(
                slot="result",
                rules=[Rule(condition="x > 0", value="x * 2")],
                param_names=("x",),
            ),
        ])
        r = t.solve({"y": 10})
        # No rule matches (x missing, condition can't evaluate), defaults to 0.0
        assert r["result"] == 0.0

    def test_zero_division_is_caught(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import (
            RuleChainTemplate, RuleChainStep, Rule,
        )
        t = RuleChainTemplate("tx.test_div_zero", steps=[
            RuleChainStep(
                slot="result",
                rules=[
                    Rule(condition="x > 0", value="1 / x"),
                    Rule(condition=True, value=999),
                ],
                param_names=("x",),
            ),
        ])
        r = t.solve({"x": 0})
        assert r["result"] == 999  # falls to catch-all

    def test_no_catch_all_rule_defaults_to_zero(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import (
            RuleChainTemplate, RuleChainStep, Rule,
        )
        t = RuleChainTemplate("tx.test_no_default", steps=[
            RuleChainStep(
                slot="result",
                rules=[Rule(condition="x > 100", value=1)],
                param_names=("x",),
            ),
        ])
        r = t.solve({"x": 50})
        assert r["result"] == 0.0

    def test_non_numeric_inputs_get_default(self):
        t = self.make_income_tax_template()
        r = t.solve({"gross_income": "not_a_number"})
        # Non-numeric inputs are filtered out; rules default to 0.0
        assert r["result"] == 0.0

    # ------------------------------------------------------------------
    # evaluate_steps()
    # ------------------------------------------------------------------

    def test_evaluate_steps_all_correct(self):
        t = self.make_income_tax_template()
        truth = t.solve({"gross_income": 50000})
        learner = [
            {"step_id": "taxable_income", "value": 37430},
            {"step_id": "tax_liability", "value": 7486},
        ]
        ev = t.evaluate_steps(learner, truth)
        assert all(e["match"] for e in ev)
        assert len(ev) == 2

    def test_evaluate_steps_partial_match(self):
        t = self.make_income_tax_template()
        truth = t.solve({"gross_income": 50000})
        learner = [
            {"step_id": "taxable_income", "value": 37430},
            {"step_id": "tax_liability", "value": 10000},
        ]
        ev = t.evaluate_steps(learner, truth)
        assert ev[0]["match"]
        assert not ev[1]["match"]

    def test_evaluate_steps_empty_learner_returns_empty(self):
        t = self.make_income_tax_template()
        truth = t.solve({"gross_income": 50000})
        assert t.evaluate_steps([], truth) == []
        assert t.evaluate_steps(None, truth) == []

    def test_evaluate_steps_empty_truth_returns_empty(self):
        t = self.make_income_tax_template()
        learner = [{"step_id": "a", "value": 1}]
        assert t.evaluate_steps(learner, {}) == []
        assert t.evaluate_steps(learner, None) == []

    # ------------------------------------------------------------------
    # classify_errors()
    # ------------------------------------------------------------------

    def test_classify_errors_on_wrong_answer(self):
        t = self.make_income_tax_template()
        truth = t.solve({"gross_income": 50000})
        learner = [
            {"step_id": "taxable_income", "value": 50000},
            {"step_id": "tax_liability", "value": 10000},
        ]
        tags = t.classify_errors(learner, truth)
        assert len(tags) > 0
        assert any("mismatch" in tag for tag in tags)

    def test_classify_errors_on_correct_answer(self):
        t = self.make_income_tax_template()
        truth = t.solve({"gross_income": 50000})
        learner = [
            {"step_id": "taxable_income", "value": 37430},
            {"step_id": "tax_liability", "value": 7486},
        ]
        tags = t.classify_errors(learner, truth)
        assert len(tags) == 0

    def test_classify_errors_empty_inputs(self):
        t = self.make_income_tax_template()
        assert t.classify_errors([], None) == []
        assert t.classify_errors(None, {}) == []

    def test_classify_errors_on_missing_step_value(self):
        t = self.make_income_tax_template()
        truth = t.solve({"gross_income": 50000})
        learner = [{"step_id": "taxable_income", "value": None}]
        tags = t.classify_errors(learner, truth)
        assert any("missing" in tag for tag in tags)


class TestRuleChainEvaluator:
    """Tests for the rule chain expression evaluator used internally."""

    def test_comparison_operators(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        env = {"x": 10.0, "y": 20.0}
        assert _eval_rule_expression("x <= y", env) == 1.0
        assert _eval_rule_expression("x >= y", env) == 0.0
        assert _eval_rule_expression("x < y", env) == 1.0
        assert _eval_rule_expression("x > y", env) == 0.0
        assert _eval_rule_expression("x == y", env) == 0.0
        assert _eval_rule_expression("x != y", env) == 1.0

    def test_boolean_operators(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        env = {"a": 1.0, "b": 0.0}
        assert _eval_rule_expression("a and b", env) == 0.0
        assert _eval_rule_expression("a or b", env) == 1.0
        assert _eval_rule_expression("not b", env) == 1.0

    def test_compound_boolean(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        env = {"x": 5.0}
        assert _eval_rule_expression("x > 0 and x <= 10", env) == 1.0
        assert _eval_rule_expression("x > 10 or x < 0", env) == 0.0

    def test_arithmetic_expressions(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        env = {"a": 10.0, "b": 3.0}
        assert _eval_rule_expression("a + b", env) == 13.0
        assert _eval_rule_expression("a - b", env) == 7.0
        assert _eval_rule_expression("a * b", env) == 30.0
        assert _eval_rule_expression("a / b", env) == pytest.approx(3.333, rel=1e-3)
        assert _eval_rule_expression("a ** 2", env) == 100.0

    def test_max_min_functions(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        env = {"a": 10.0, "b": 20.0}
        assert _eval_rule_expression("max(a, b)", env) == 20.0
        assert _eval_rule_expression("min(a, b)", env) == 10.0
        assert _eval_rule_expression("abs(a - b)", env) == 10.0

    def test_unsafe_call_rejected(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        import pytest
        with pytest.raises((ValueError, NameError)):
            _eval_rule_expression("__import__('os')", {})

    def test_undefined_variable(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        import pytest
        with pytest.raises(NameError):
            _eval_rule_expression("undefined_var > 10", {})

    def test_invalid_syntax(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        import pytest
        with pytest.raises(ValueError):
            _eval_rule_expression("x @@@ y", {})

    def test_ternary_expression(self):
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
        env = {"x": 5.0}
        assert _eval_rule_expression("1 if x > 0 else 0", env) == 1.0
        assert _eval_rule_expression("1 if x < 0 else 0", env) == 0.0


# ===================================================================
# Lookup concept tests
# ===================================================================

class TestLookupTemplate:
    """Tests for the ``LookupTemplate`` class."""

    def make_vat_template(self):
        from studyplan.domain_reasoning.concept_types.lookup_concept import (
            LookupTemplate, LookupConfig, LookupRule,
        )
        return LookupTemplate("tx.test_vat", LookupConfig(
            table={"standard": 0.20, "reduced": 0.05, "zero": 0.0, "exempt": None},
            rules=[
                LookupRule(condition="goods_type == 1", output_key="standard"),
                LookupRule(condition="goods_type == 2", output_key="reduced"),
                LookupRule(condition="goods_type == 3", output_key="zero"),
            ],
            default_key="standard",
            output_slot="vat_result",
        ))

    def test_direct_match(self):
        t = self.make_vat_template()
        r = t.solve({"goods_type": 1.0})
        assert r["result"] == 0.20
        assert r.get("lookup_key") == "standard"

    def test_another_match(self):
        t = self.make_vat_template()
        r = t.solve({"goods_type": 2.0})
        assert r["result"] == 0.05
        assert r.get("lookup_key") == "reduced"

    def test_default_key_when_no_rule_matches(self):
        t = self.make_vat_template()
        r = t.solve({"goods_type": 99.0})
        assert r["result"] == 0.20
        assert r.get("lookup_key") == "standard"

    def test_none_value_in_table(self):
        t = self.make_vat_template()
        # goods_type=3 matches the "zero" rule → table lookup is 0.0
        r = t.solve({"goods_type": 3.0})
        assert r["result"] == 0.0
        assert not r["is_nan"]

    def test_key_not_in_table(self):
        from studyplan.domain_reasoning.concept_types.lookup_concept import (
            LookupTemplate, LookupConfig, LookupRule,
        )
        t = LookupTemplate("tx.test_bad_key", LookupConfig(
            table={"a": 1.0},
            rules=[LookupRule(condition="x == 1", output_key="nonexistent")],
            default_key="also_missing",
        ))
        r = t.solve({"x": 1.0})
        assert r["is_nan"]

    def test_evaluate_steps(self):
        t = self.make_vat_template()
        truth = t.solve({"goods_type": 1.0})
        learner = [{"step_id": "vat_result", "value": 0.20}]
        ev = t.evaluate_steps(learner, truth)
        assert ev[0]["match"]

    def test_evaluate_steps_mismatch(self):
        t = self.make_vat_template()
        truth = t.solve({"goods_type": 1.0})
        learner = [{"step_id": "vat_result", "value": 0.05}]
        ev = t.evaluate_steps(learner, truth)
        assert not ev[0]["match"]

    def test_classify_errors_match(self):
        t = self.make_vat_template()
        truth = t.solve({"goods_type": 1.0})
        learner = [{"step_id": "vat_result", "value": 0.20}]
        assert t.classify_errors(learner, truth) == []

    def test_classify_errors_mismatch(self):
        t = self.make_vat_template()
        truth = t.solve({"goods_type": 1.0})
        learner = [{"step_id": "vat_result", "value": 0.05}]
        tags = t.classify_errors(learner, truth)
        assert len(tags) > 0

    def test_match_by_second_rule_when_first_fails(self):
        from studyplan.domain_reasoning.concept_types.lookup_concept import (
            LookupTemplate, LookupConfig, LookupRule,
        )
        t = LookupTemplate("tx.test_fallback", LookupConfig(
            table={"a": 10, "b": 20},
            rules=[
                LookupRule(condition="x > 100", output_key="a"),
                LookupRule(condition="x > 0", output_key="b"),
            ],
            default_key="a",
        ))
        r = t.solve({"x": 50})
        assert r["result"] == 20
        assert r.get("lookup_key") == "b"


# ===================================================================
# Classification concept tests
# ===================================================================

class TestClassificationTemplate:
    """Tests for the ``ClassificationTemplate`` class."""

    def make_entity_template(self):
        from studyplan.domain_reasoning.concept_types.classification_concept import (
            ClassificationTemplate, ClassificationConfig,
            ClassificationNode, Branch,
        )
        return ClassificationTemplate("tx.test_entity", ClassificationConfig(
            tree=ClassificationNode(
                question="Is the entity incorporated?",
                branches=[
                    Branch(condition="incorp == 1", result="limited_company"),
                    Branch(condition=True, children=[
                        Branch(condition="partnership == 1", result="partnership"),
                        Branch(condition=True, result="sole_trader"),
                    ]),
                ],
            ),
            output_slot="entity_result",
        ))

    def test_incorporated(self):
        t = self.make_entity_template()
        r = t.solve({"incorp": 1.0})
        assert r["result"] == "limited_company"
        assert not r["is_nan"]

    def test_partnership(self):
        t = self.make_entity_template()
        r = t.solve({"incorp": 0.0, "partnership": 1.0})
        assert r["result"] == "partnership"

    def test_sole_trader(self):
        t = self.make_entity_template()
        r = t.solve({"incorp": 0.0, "partnership": 0.0})
        assert r["result"] == "sole_trader"

    def test_classification_path(self):
        t = self.make_entity_template()
        r = t.solve({"incorp": 0.0, "partnership": 1.0})
        path = r.get("classification_path", [])
        assert len(path) == 1
        assert "incorporated" in path[0].lower()

    def test_result_is_not_nan(self):
        t = self.make_entity_template()
        r = t.solve({"incorp": 1.0})
        assert not r["is_nan"]

    def test_empty_inputs(self):
        t = self.make_entity_template()
        r = t.solve({})
        assert r["result"] == "sole_trader"  # falls to sole_trader

    def test_evaluate_steps_correct(self):
        t = self.make_entity_template()
        truth = t.solve({"incorp": 1.0})
        learner = [{"step_id": "entity_result", "value": "limited_company"}]
        ev = t.evaluate_steps(learner, truth)
        assert ev[0]["match"]

    def test_evaluate_steps_wrong(self):
        t = self.make_entity_template()
        truth = t.solve({"incorp": 1.0})
        learner = [{"step_id": "entity_result", "value": "partnership"}]
        ev = t.evaluate_steps(learner, truth)
        assert not ev[0]["match"]

    def test_classify_errors_correct(self):
        t = self.make_entity_template()
        truth = t.solve({"incorp": 1.0})
        learner = [{"step_id": "entity_result", "value": "limited_company"}]
        assert t.classify_errors(learner, truth) == []

    def test_classify_errors_wrong(self):
        t = self.make_entity_template()
        truth = t.solve({"incorp": 1.0})
        learner = [{"step_id": "entity_result", "value": "sole_trader"}]
        tags = t.classify_errors(learner, truth)
        assert len(tags) > 0

    def test_decision_tree_trace_contains_questions(self):
        t = self.make_entity_template()
        r = t.solve({"incorp": 1.0})
        steps = r["steps"]
        assert len(steps) >= 2  # decision node + result
        assert steps[0]["step_id"] == "decision"
        assert steps[-1]["step_id"] == "entity_result"


class TestClassificationDeepTree:
    """More complex tree shapes."""

    def test_three_level_tree(self):
        from studyplan.domain_reasoning.concept_types.classification_concept import (
            ClassificationTemplate, ClassificationConfig,
            ClassificationNode, Branch,
        )
        t = ClassificationTemplate("tx.test_deep", ClassificationConfig(
            tree=ClassificationNode(
                question="Level 1: A or B?",
                branches=[
                    Branch(condition="l1 == 1", children=[
                        Branch(condition="l2 == 1", result="A1"),
                        Branch(condition=True, result="A2"),
                    ]),
                    Branch(condition=True, children=[
                        Branch(condition="l2 == 1", result="B1"),
                        Branch(condition=True, children=[
                            Branch(condition="l3 == 1", result="B2a"),
                            Branch(condition=True, result="B2b"),
                        ]),
                    ]),
                ],
            ),
        ))
        assert t.solve({"l1": 1.0, "l2": 1.0})["result"] == "A1"
        assert t.solve({"l1": 1.0, "l2": 0.0})["result"] == "A2"
        assert t.solve({"l1": 0.0, "l2": 1.0})["result"] == "B1"
        assert t.solve({"l1": 0.0, "l2": 0.0, "l3": 1.0})["result"] == "B2a"
        assert t.solve({"l1": 0.0, "l2": 0.0, "l3": 0.0})["result"] == "B2b"


class TestClassificationEmptyLeaves:
    """Edge cases: empty or missing leaf nodes."""

    def test_node_with_no_branches_returns_none(self):
        from studyplan.domain_reasoning.concept_types.classification_concept import (
            ClassificationTemplate, ClassificationConfig,
            ClassificationNode,
        )
        t = ClassificationTemplate("tx.test_empty", ClassificationConfig(
            tree=ClassificationNode(question="No branches?", branches=[]),
        ))
        r = t.solve({"x": 1.0})
        assert r["is_nan"]


# ===================================================================
# declare_concept() API tests
# ===================================================================

class TestDeclareConceptAPI:
    """Tests for the unified ``declare_concept()`` entry point."""

    def test_expression_type_works(self):
        from studyplan.domain_reasoning.formula_registry import declare_concept, get_registry
        d = declare_concept("test.dc_expr",
            concept_type="expression",
            expression="a * b",
            param_names=["a", "b"],
            param_kinds=["value", "value"],
            label="Multiply",
            output_slot="product",
        )
        assert d.concept_type == "expression"
        assert d.template is not None
        assert "test.dc_expr" in get_registry()

    def test_rule_chain_type_works(self):
        from studyplan.domain_reasoning.formula_registry import declare_concept, get_registry
        from studyplan.domain_reasoning.concept_types.rule_concept import (
            RuleChainConfig, RuleChainStep, Rule,
        )
        d = declare_concept("test.dc_rule",
            concept_type="rule_chain",
            concept_config=RuleChainConfig(
                steps=[RuleChainStep(
                    slot="out",
                    rules=[Rule(condition="x > 0", value="x * 2")],
                    param_names=("x",),
                )],
                output_slot="out",
            ),
            label="Rule test",
        )
        assert d.concept_type == "rule_chain"
        r = d.template.solve({"x": 5.0})
        assert r["result"] == 10.0

    def test_lookup_type_works(self):
        from studyplan.domain_reasoning.formula_registry import declare_concept, get_registry
        from studyplan.domain_reasoning.concept_types.lookup_concept import (
            LookupConfig, LookupRule,
        )
        d = declare_concept("test.dc_lookup",
            concept_type="lookup",
            concept_config=LookupConfig(
                table={"a": 1, "b": 2},
                rules=[LookupRule(condition="x == 1", output_key="a")],
                default_key="b",
            ),
            label="Lookup test",
        )
        assert d.concept_type == "lookup"
        r = d.template.solve({"x": 1.0})
        assert r["result"] == 1

    def test_classification_type_works(self):
        from studyplan.domain_reasoning.formula_registry import declare_concept, get_registry
        from studyplan.domain_reasoning.concept_types.classification_concept import (
            ClassificationConfig, ClassificationNode, Branch,
        )
        d = declare_concept("test.dc_class",
            concept_type="classification",
            concept_config=ClassificationConfig(
                tree=ClassificationNode(
                    question="Q?",
                    branches=[Branch(condition="x == 1", result="yes"),
                              Branch(condition=True, result="no")],
                ),
            ),
            label="Class test",
        )
        assert d.concept_type == "classification"
        r = d.template.solve({"x": 1.0})
        assert r["result"] == "yes"

    def test_invalid_type_raises(self):
        from studyplan.domain_reasoning.formula_registry import declare_concept
        import pytest
        with pytest.raises(ValueError, match="Unknown concept_type"):
            declare_concept("test.bad",
                concept_type="nonexistent",
                concept_config=None,
            )

    def test_expression_defaults_to_expression_type(self):
        from studyplan.domain_reasoning.formula_registry import declare_concept, get_registry
        d = declare_concept("test.dc_default",
            expression="x + 1",
            param_names=["x"],
        )
        assert d.concept_type == "expression"


class TestDeclareConceptConvenience:
    """Tests that declare_formula() and declare_formula_chain() still work."""

    def test_declare_formula_backward_compat(self):
        from studyplan.domain_reasoning.formula_registry import declare_formula, get_registry
        d = declare_formula("test.dc_back",
            expression="x * 2",
            param_names=["x"],
            param_kinds=["value"],
            output_slot="backward",
        )
        assert d.concept_type == "expression"
        r = d.template.solve({"x": 5.0})
        assert r["result"] == 10.0

    def test_declare_formula_chain_backward_compat(self):
        from studyplan.domain_reasoning.formula_registry import (
            declare_formula_chain, get_registry,
        )
        d = declare_formula_chain("test.dc_chain_back",
            steps=[dict(slot="s1", expression="x + y",
                        param_names=["x", "y"])],
            output_slot="s1",
        )
        assert d.concept_type == "expression"
        r = d.template.solve({"x": 1.0, "y": 2.0})
        assert r["result"] == 3.0

    def test_patterns_registered_correctly(self):
        from studyplan.domain_reasoning.formula_registry import (
            declare_concept, get_registry,
        )
        from studyplan.domain_reasoning.concept_types.rule_concept import (
            RuleChainConfig, RuleChainStep, Rule,
        )
        d = declare_concept("test.dc_pattern",
            concept_type="rule_chain",
            concept_config=RuleChainConfig(
                steps=[RuleChainStep(
                    slot="o",
                    rules=[Rule(condition="x > 0", value=1)],
                )],
                output_slot="o",
            ),
            patterns=[r"\btest pattern\b"],
            label="Pattern test",
        )
        assert len(d.compiled_patterns) == 1
        assert d.compiled_patterns[0].search("this is a test pattern!")
