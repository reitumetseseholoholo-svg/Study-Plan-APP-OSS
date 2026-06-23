"""Tests for the domain reasoning layer — concepts, templates, evaluator, diagnostics."""

import math

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
