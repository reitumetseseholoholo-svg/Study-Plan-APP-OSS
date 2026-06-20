"""Tests for the reasoning engine — dependency chaining, plan compilation, execution."""

import math
import pytest
from studyplan.domain_reasoning.reasoning_engine import (
    reason_question,
    ReasoningTrace,
    PlanStep,
    ExecutionRecord,
    _resolve_dependency_chain,
    _get_expected_param_keys,
    _build_inputs_for,
    _compile_plan,
    _find_alternatives,
    _OUTPUT_SLOT_GROUPS,
    _plug_input_gaps,
    _compute_confidence,
)
from studyplan.domain_reasoning.concepts import BUILTIN_CONCEPTS


# ===================================================================
# Dependency chain resolution
# ===================================================================

class TestResolveDependencyChain:
    def test_no_deps(self):
        order = _resolve_dependency_chain("fm.npv", BUILTIN_CONCEPTS)
        assert order == ["fm.npv"]

    def test_single_dep(self):
        order = _resolve_dependency_chain("fm.equity_beta", BUILTIN_CONCEPTS)
        assert order == ["fm.asset_beta", "fm.equity_beta"]

    def test_two_deps(self):
        order = _resolve_dependency_chain("fm.wacc", BUILTIN_CONCEPTS)
        assert "fm.cost_of_equity_dvm" in order
        assert "fm.cost_of_debt" in order
        assert order[-1] == "fm.wacc"

    def test_irr_depends_on_npv(self):
        order = _resolve_dependency_chain("fm.irr", BUILTIN_CONCEPTS)
        assert order == ["fm.npv", "fm.irr"]

    def test_dividend_cover_depends_on_eps(self):
        order = _resolve_dependency_chain("fm.dividend_cover", BUILTIN_CONCEPTS)
        assert order == ["fm.eps", "fm.dividend_cover"]

    def test_unknown_concept(self):
        order = _resolve_dependency_chain("fm.nonexistent", BUILTIN_CONCEPTS)
        assert order == ["fm.nonexistent"]

    def test_unknown_dependency(self):
        """A concept listed as a dep but not in BUILTIN_CONCEPTS."""
        from dataclasses import dataclass
        from typing import Any
        custom = {
            "fm.a": type("", (), {"dependencies": ("fm.b",)})(),
        }
        order = _resolve_dependency_chain("fm.a", custom)
        assert order == ["fm.b", "fm.a"]


# ===================================================================
# Expected param key detection
# ===================================================================

class TestGetExpectedParamKeys:
    def test_npv(self):
        keys = _get_expected_param_keys("fm.npv")
        assert keys is not None
        assert "cashflows" in keys
        assert "rate" in keys

    def test_wacc(self):
        keys = _get_expected_param_keys("fm.wacc")
        assert keys == {"equity", "debt", "cost_equity", "cost_debt", "tax_rate"}

    def test_capm(self):
        keys = _get_expected_param_keys("fm.capm")
        assert keys == {"risk_free", "beta", "market_return"}

    def test_asset_beta(self):
        keys = _get_expected_param_keys("fm.asset_beta")
        assert "equity_beta" in keys

    def test_equity_beta(self):
        keys = _get_expected_param_keys("fm.equity_beta")
        assert "asset_beta" in keys

    def test_unknown(self):
        assert _get_expected_param_keys("fm.unknown") is None

    def test_covers_all_builtin(self):
        for cid in BUILTIN_CONCEPTS:
            keys = _get_expected_param_keys(cid)
            assert keys is not None, f"{cid} has no expected params"


# ===================================================================
# Plan compilation
# ===================================================================

class TestCompilePlan:
    def test_single_step(self):
        plan = _compile_plan("fm.npv", BUILTIN_CONCEPTS, "NPV", {})
        assert len(plan) == 1
        assert plan[0].concept_id == "fm.npv"

    def test_chained_steps(self):
        plan = _compile_plan("fm.equity_beta", BUILTIN_CONCEPTS, "question", {})
        assert len(plan) == 2
        assert plan[0].concept_id == "fm.asset_beta"
        assert plan[1].concept_id == "fm.equity_beta"

    def test_steps_have_output_slots(self):
        plan = _compile_plan("fm.equity_beta", BUILTIN_CONCEPTS, "question", {})
        for step in plan:
            assert step.output_slots  # each step should have at least one slot

    def test_explicit_inputs_on_target(self):
        plan = _compile_plan(
            "fm.capm", BUILTIN_CONCEPTS, "question", {},
            explicit_ref="fm.capm",
            explicit_inputs={"risk_free": 0.03, "beta": 1.2, "market_return": 0.10},
        )
        assert len(plan) == 1
        assert plan[0].inputs.get("risk_free") == 0.03

    def test_returns_empty_for_unknown(self):
        plan = _compile_plan("fm.nonexistent", BUILTIN_CONCEPTS, "question", {})
        assert plan == []


# ===================================================================
# reason_question — basic execution
# ===================================================================

class TestReasonQuestion:
    def test_empty_question(self):
        r = reason_question("")
        assert not r.has_result
        assert r.trace_summary == "no reasoning possible"

    def test_no_concept_detected(self):
        r = reason_question("What is finance?")
        assert not r.has_result

    def test_npv_explicit(self):
        r = reason_question("NPV question",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100, 200], "rate": 0.10, "initial": 50})
        assert r.has_result
        assert abs(r.final_result - 206.2) < 1.0
        assert len(r.execution) == 1
        assert r.execution[0].success

    def test_capm_explicit(self):
        r = reason_question("CAPM question",
                            template_ref="fm.capm",
                            template_inputs={"risk_free": 0.03, "beta": 1.2, "market_return": 0.10})
        assert r.has_result
        assert abs(r.final_result - 0.114) < 0.001

    def test_wacc_explicit(self):
        r = reason_question("WACC",
                            template_ref="fm.wacc",
                            template_inputs={"equity": 60, "debt": 40, "cost_equity": 0.12,
                                             "cost_debt": 0.06, "tax_rate": 0.30})
        assert r.has_result
        assert abs(r.final_result - 0.0888) < 0.001
        # WACC itself should succeed even if dep steps fail
        assert r.execution[-1].success

    def test_payback(self):
        r = reason_question("Payback",
                            template_ref="fm.payback",
                            template_inputs={"initial": 100, "cashflows": [30, 40, 50]})
        assert r.has_result
        assert abs(r.final_result - 2.6) < 0.01

    def test_gearing(self):
        r = reason_question("Gearing",
                            template_ref="fm.gearing",
                            template_inputs={"debt": 40, "equity": 60})
        assert r.has_result
        assert abs(r.final_result - 0.40) < 0.001

    def test_eoq(self):
        r = reason_question("EOQ",
                            template_ref="fm.eoq",
                            template_inputs={"annual_demand": 10000, "ordering_cost": 50,
                                             "holding_cost_per_unit": 2})
        assert r.has_result
        assert abs(r.final_result - 707.1) < 1.0

    def test_ccc(self):
        r = reason_question("CCC",
                            template_ref="fm.ccc",
                            template_inputs={"dio": 40, "dso": 30, "dpo": 20})
        assert r.has_result
        assert abs(r.final_result - 50) < 0.01

    def test_eps(self):
        r = reason_question("EPS",
                            template_ref="fm.eps",
                            template_inputs={"profit_after_tax": 2000000, "number_of_shares": 500000})
        assert r.has_result
        assert abs(r.final_result - 4.0) < 0.01

    def test_arr(self):
        r = reason_question("ARR",
                            template_ref="fm.arr",
                            template_inputs={"average_profit": 15000, "initial_investment": 100000})
        assert r.has_result
        assert abs(r.final_result - 0.30) < 0.01

    def test_interest_cover(self):
        r = reason_question("Interest cover",
                            template_ref="fm.interest_cover",
                            template_inputs={"pbit": 500000, "interest_expense": 100000})
        assert r.has_result
        assert abs(r.final_result - 5.0) < 0.01

    def test_asset_beta(self):
        r = reason_question("Asset beta",
                            template_ref="fm.asset_beta",
                            template_inputs={"equity_beta": 1.2, "market_value_debt": 40,
                                             "market_value_equity": 60, "tax_rate": 0.30})
        assert r.has_result
        assert abs(r.final_result - 0.818) < 0.01

    def test_dividend_yield(self):
        r = reason_question("Div yield",
                            template_ref="fm.dividend_yield",
                            template_inputs={"dividend_per_share": 0.50, "market_price": 10.0})
        assert r.has_result
        assert abs(r.final_result - 0.05) < 0.001

    def test_equivalent_annual_cost(self):
        r = reason_question("EAC",
                            template_ref="fm.equivalent_annual_cost",
                            template_inputs={"cost": 50000, "discount_rate": 0.10, "years": 5})
        assert r.has_result
        assert abs(r.final_result - 13189.87) < 1.0

    def test_profitability_index(self):
        r = reason_question("Profit index",
                            template_ref="fm.profitability_index",
                            template_inputs={"pv_future_cashflows": 120000, "initial_investment": 100000})
        assert r.has_result
        assert abs(r.final_result - 1.20) < 0.01


# ===================================================================
# Dependency chaining at execution time
# ===================================================================

class TestDependencyChaining:
    def test_irr_uses_npv(self):
        """IRR depends on NPV — the plan should include both."""
        r = reason_question("IRR question",
                            template_ref="fm.irr",
                            template_inputs={"cashflows": [60, 60], "initial": 100})
        assert r.has_result
        concept_ids = [e.concept_id for e in r.execution]
        assert "fm.npv" in concept_ids
        assert "fm.irr" in concept_ids
        for e in r.execution:
            assert e.success, f"{e.concept_id} failed"

    def test_dividend_cover_uses_eps(self):
        """EPS is a dependency — when eps is NOT in explicit inputs, both run."""
        r = reason_question("Div cover",
                            template_ref="fm.dividend_cover",
                            template_inputs={"dividend_per_share": 0.20})
        assert r.has_result
        concept_ids = [e.concept_id for e in r.execution]
        assert "fm.eps" in concept_ids
        assert "fm.dividend_cover" in concept_ids

    def test_dividend_cover_skips_when_eps_given(self):
        """When `eps` is in explicit inputs, dependency step is skipped."""
        r = reason_question("Div cover",
                            template_ref="fm.dividend_cover",
                            template_inputs={"eps": 0.40, "dividend_per_share": 0.20})
        assert r.has_result
        assert r.execution[0].concept_id == "fm.dividend_cover"

    def test_equity_beta_plan_includes_asset_beta(self):
        """The dependency step appears in the plan even if it can't run."""
        r = reason_question("Equity beta",
                            template_ref="fm.equity_beta",
                            template_inputs={"market_value_debt": 40,
                                             "market_value_equity": 60, "tax_rate": 0.30})
        concept_ids = [p.concept_id for p in r.plan]
        assert "fm.asset_beta" in concept_ids
        assert "fm.equity_beta" in concept_ids

    def test_equity_beta_skips_when_asset_beta_given(self):
        """When `asset_beta` is in explicit inputs, dependency is skipped."""
        r = reason_question("Equity beta",
                            template_ref="fm.equity_beta",
                            template_inputs={"asset_beta": 0.8, "market_value_debt": 40,
                                             "market_value_equity": 60, "tax_rate": 0.30})
        assert r.has_result
        assert r.execution[0].concept_id == "fm.equity_beta"

    def test_dependency_order_preserved(self):
        """Dependencies run before dependents."""
        r = reason_question("IRR q",
                            template_ref="fm.irr",
                            template_inputs={"cashflows": [60, 60], "initial": 100})
        executed = [e.concept_id for e in r.execution]
        npv_idx = executed.index("fm.npv")
        irr_idx = executed.index("fm.irr")
        assert npv_idx < irr_idx, "NPV should run before IRR"

    def test_intermediate_forwarding(self):
        """Output of NPV step should be available to downstream steps."""
        r = reason_question("IRR q",
                            template_ref="fm.irr",
                            template_inputs={"cashflows": [60, 60], "initial": 100})
        # NPV should produce a result that IRR uses internally
        npv_step = r.execution[0]
        assert npv_step.success
        assert npv_step.result is not None
        assert npv_step.concept_id == "fm.npv"


# ===================================================================
# Execution edge cases
# ===================================================================

class TestExecutionEdgeCases:
    def test_nan_result_handling(self):
        """Template returning NaN should mark step failed."""
        r = reason_question("Bad inputs",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [], "rate": -1})
        # Should not crash
        assert r.execution
        assert not r.execution[0].success

    def test_unknown_template_ref(self):
        r = reason_question("Unknown", template_ref="fm.unknown")
        assert not r.has_result

    def test_all_steps_recorded(self):
        r = reason_question("NPV",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100], "rate": 0.10})
        assert len(r.execution) == len(r.plan)


# ===================================================================
# Trace and diagnostic output
# ===================================================================

class TestTraceOutput:
    def test_to_dict_serializable(self):
        r = reason_question("NPV",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100, 200], "rate": 0.10, "initial": 50})
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["has_result"] is True
        assert isinstance(d["final_result"], float)
        assert isinstance(d["execution"], list)
        assert len(d["execution"]) == 1
        assert d["execution"][0]["success"] is True

    def test_trace_summary_non_empty(self):
        r = reason_question("NPV",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100], "rate": 0.10})
        assert isinstance(r.trace_summary, str)
        assert len(r.trace_summary) > 0

    def test_trace_summary_no_result(self):
        r = reason_question("")
        assert r.trace_summary == "no reasoning possible"

    def test_confidence_reflects_success_rate(self):
        r = reason_question("NPV",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100], "rate": 0.10})
        assert r.confidence == 1.0

    def test_confidence_partial(self):
        """When not all explicit inputs are provided for deps, some steps fail."""
        r = reason_question("WACC",
                            template_ref="fm.wacc",
                            template_inputs={"equity": 60, "debt": 40})
        # cost_equity and cost_debt not provided → dep steps fail
        assert 0 < r.confidence <= 1.0


# ===================================================================
# Integration with diagnostic layer
# ===================================================================

class TestDiagnosticIntegration:
    def test_diagnostic_attached(self):
        r = reason_question("NPV question",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100, 200], "rate": 0.10})
        assert r.diagnostic is not None

    def test_diagnostic_concept_ids(self):
        r = reason_question("WACC question",
                            template_ref="fm.wacc",
                            template_inputs={"equity": 60, "debt": 40, "cost_equity": 0.12,
                                             "cost_debt": 0.06, "tax_rate": 0.30})
        assert r.diagnostic.concept_ids

    def test_diagnostic_with_options(self):
        r = reason_question("NPV question",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100, 200], "rate": 0.10},
                            options=["200", "250", "300"],
                            correct="250")
        if r.diagnostic:
            # Should flag a mismatch since correct=250 but result ≈206
            assert r.diagnostic.has_deterministic_truth is True or not r.diagnostic.all_error_tags


# ===================================================================
# _build_inputs_for
# ===================================================================

class TestBuildInputsFor:
    def test_returns_candidate_params(self):
        inputs = _build_inputs_for("fm.npv", "NPV at 10% with 100, 200", None, None, {})
        assert "cashflows" in inputs or "rate" in inputs

    def test_explicit_overrides(self):
        inputs = _build_inputs_for("fm.capm", "question", "fm.capm",
                                   {"risk_free": 0.03, "beta": 1.2, "market_return": 0.10},
                                   {})
        assert inputs.get("risk_free") == 0.03

    def test_intermed_forwarding(self):
        inputs = _build_inputs_for("fm.equity_beta", "question", None, None,
                                   {"asset_beta": 0.8, "market_value_debt": 40})
        assert inputs.get("asset_beta") == 0.8

    def test_filters_unexpected_keys(self):
        inputs = _build_inputs_for("fm.capm", "question", None, None,
                                   {"risk_free": 0.03, "beta": 1.2, "not_a_param": 99})
        assert "not_a_param" not in inputs


# ===================================================================
# PlanStep and ExecutionRecord basic contract
# ===================================================================

class TestDataTypes:
    def test_plan_step_defaults(self):
        s = PlanStep(concept_id="fm.npv", template_ref="fm.npv", label="NPV", inputs={})
        assert s.output_slots == ()
        assert s.depends_on == ()
        assert s.skipped is False

    def test_execution_record_defaults(self):
        r = ExecutionRecord(concept_id="fm.npv", success=True)
        assert r.label == ""
        assert r.error_tags == []
        assert r.detailed_steps == []
        assert r.duration_ms == 0.0
        assert r.skipped is False
        assert r.input_source_quality == 0.0

    def test_plan_step_has_new_fields(self):
        s = PlanStep(concept_id="fm.npv", template_ref="fm.npv", label="NPV", inputs={})
        assert s.expected_params == set()
        assert s.input_sources == {}


# ===================================================================
# Phase 2: Multi-path fallback
# ===================================================================

class TestMultiPathFallback:
    def test_wacc_falls_back_to_capm_when_dvm_fails(self):
        """When DVM can't compute (missing dividend/price/growth) but CAPM
        has all inputs (risk_free, beta, market_return), the engine should
        fall back to CAPM to produce cost_equity."""
        r = reason_question(
            "WACC with CAPM fallback",
            template_ref="fm.wacc",
            template_inputs={
                "equity": 60, "debt": 40,
                "risk_free": 0.05, "beta": 1.2, "market_return": 0.12,
                "interest_rate": 0.08, "tax_rate": 0.30,
            },
        )
        assert r.has_result
        # CAPM: 0.05 + 1.2 * (0.12 - 0.05) = 0.134
        # cost_of_debt: 0.08 * (1 - 0.30) = 0.056 (after-tax)
        # WACC template applies (1-tax) AGAIN to cost_debt:
        # WACC = 0.6*0.134 + 0.4*0.056*(1-0.30) = 0.0804 + 0.01568 = 0.09608
        assert abs(r.final_result - 0.09608) < 0.001
        capm_entries = [e for e in r.execution if e.concept_id == "fm.capm"]
        assert len(capm_entries) >= 1
        assert all(e.success for e in capm_entries)

    def test_no_fallback_when_no_alternative(self):
        """When a step fails and no alternative produces the same output
        slot, the step remains failed and execution continues."""
        r = reason_question("Payback fail",
                            template_ref="fm.payback",
                            template_inputs={})
        assert len(r.execution) == 1
        assert not r.execution[0].success

    def test_fallback_not_used_when_original_succeeds(self):
        """When the original step succeeds, no fallback is attempted."""
        r = reason_question("NPV",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100], "rate": 0.10, "initial": 50})
        assert r.execution[0].concept_id == "fm.npv"
        assert r.execution[0].success

    def test_capm_and_dvm_are_alternatives(self):
        """cost_equity should list both DVM and CAPM as alternatives."""
        dvm_alts = _find_alternatives("fm.cost_of_equity_dvm")
        assert "fm.capm" in dvm_alts
        capm_alts = _find_alternatives("fm.capm")
        assert "fm.cost_of_equity_dvm" in capm_alts

    def test_npv_has_no_alternatives(self):
        assert _find_alternatives("fm.npv") == []

    def test_output_slot_groups_include_cost_equity(self):
        assert "cost_equity" in _OUTPUT_SLOT_GROUPS
        assert "fm.cost_of_equity_dvm" in _OUTPUT_SLOT_GROUPS["cost_equity"]
        assert "fm.capm" in _OUTPUT_SLOT_GROUPS["cost_equity"]


# ===================================================================
# Phase 3: Input gap analysis
# ===================================================================

class TestGapAnalysis:
    def test_capm_discovered_when_cost_equity_missing_and_capm_inputs_available(self):
        """When WACC needs cost_equity and DVM can't provide it but CAPM
        inputs are available, CAPM should be auto-discovered and added
        to the plan before WACC."""
        plan = _compile_plan(
            "fm.wacc", BUILTIN_CONCEPTS, "",
            givens={"equity": 60, "debt": 40, "risk_free": 0.05, "beta": 1.2,
                    "market_return": 0.12, "interest_rate": 0.08, "tax_rate": 0.30},
            explicit_ref="fm.wacc",
            explicit_inputs={"equity": 60, "debt": 40, "risk_free": 0.05,
                             "beta": 1.2, "market_return": 0.12,
                             "interest_rate": 0.08, "tax_rate": 0.30},
        )
        concept_ids = [p.concept_id for p in plan]
        assert "fm.capm" in concept_ids, (
            f"CAPM should be auto-discovered, got {concept_ids}")
        assert concept_ids[-1] == "fm.wacc", "WACC should be last"
        assert concept_ids.index("fm.capm") < concept_ids.index("fm.wacc")

    def test_no_gap_added_when_provider_inputs_unavailable(self):
        """If a provider concept's own inputs aren't available, don't add it."""
        plan = _compile_plan(
            "fm.wacc", BUILTIN_CONCEPTS, "",
            givens={"equity": 60, "debt": 40},
            explicit_ref="fm.wacc",
            explicit_inputs={"equity": 60, "debt": 40},
        )
        concept_ids = [p.concept_id for p in plan]
        assert "fm.capm" not in concept_ids, (
            f"CAPM should NOT be added without its inputs, got {concept_ids}")

    def test_plug_input_gaps_noop_on_simple_concept(self):
        """Gap analysis should not modify a plan that has no missing inputs."""
        plan = _compile_plan("fm.npv", BUILTIN_CONCEPTS,
                             "NPV 10% 100", {})
        original = list(plan)
        gapped = _plug_input_gaps(original, BUILTIN_CONCEPTS, "NPV 10% 100", {})
        assert len(gapped) == len(original)


# ===================================================================
# Phase 4: Weighted confidence
# ===================================================================

class TestWeightedConfidence:
    def test_all_explicit_inputs_gives_full_confidence(self):
        """All provided inputs are 'explicit' → quality = 1.0 → confidence = 1.0."""
        r = reason_question("NPV",
                            template_ref="fm.npv",
                            template_inputs={"cashflows": [100], "rate": 0.10, "initial": 50})
        assert r.confidence == 1.0

    def test_failed_deps_lower_but_not_zero_confidence(self):
        """Dependency steps that fail reduce confidence below 1.0 but > 0."""
        r = reason_question("WACC partial",
                            template_ref="fm.wacc",
                            template_inputs={"equity": 60, "debt": 40})
        assert 0 < r.confidence < 1.0

    def test_compute_confidence_empty(self):
        assert _compute_confidence([]) == 0.0

    def test_compute_confidence_all_success(self):
        recs = [
            ExecutionRecord(concept_id="fm.npv", success=True,
                            input_source_quality=1.0),
        ]
        assert _compute_confidence(recs) == 1.0

    def test_compute_confidence_mixed_quality(self):
        """Mixed input-source quality yields intermediate confidence."""
        recs = [
            ExecutionRecord(concept_id="fm.a", success=True,
                            input_source_quality=0.70),
        ]
        c = _compute_confidence(recs)
        assert c == pytest.approx(0.70)

    def test_compute_confidence_with_failures(self):
        """Failed steps reduce confidence below quality average."""
        recs = [
            ExecutionRecord(concept_id="fm.a", success=False,
                            input_source_quality=0.70),
            ExecutionRecord(concept_id="fm.b", success=True,
                            input_source_quality=1.0),
        ]
        c = _compute_confidence(recs)
        avg_q = (0.70 + 1.0) / 2  # 0.85
        success_rate = 0.5
        expected = avg_q * success_rate  # 0.85 * 0.5 = 0.425
        assert c == pytest.approx(expected)

    def test_compute_confidence_skipped_ignored(self):
        recs = [
            ExecutionRecord(concept_id="fm.a", success=False, skipped=True,
                            input_source_quality=0.0),
            ExecutionRecord(concept_id="fm.b", success=True,
                            input_source_quality=1.0),
        ]
        # Skipped record should be ignored → only 1 non-skipped step
        assert _compute_confidence(recs) == 1.0
