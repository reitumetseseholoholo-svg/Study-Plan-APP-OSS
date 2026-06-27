"""Explicit concept metadata and detection.

Each concept represents a procedural finance/accounting skill that can
be evaluated deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptMetadata:
    """Metadata for a deterministic procedural concept.

    Fields mirror the authored module schema (see DOMAIN_REASONING_ARCHITECTURE.md).
    """

    concept_id: str
    label: str
    template_ref: str
    dependencies: tuple[str, ...] = ()
    output_slots: tuple[str, ...] = ()
    diagnostic_tags: tuple[str, ...] = ()
    centrality: float = 0.5
    chapter_refs: tuple[str, ...] = ()
    outcome_ids: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Built-in concept registry — one entry per supported solver formula.
# These are the concepts we can evaluate deterministically via
# the numerical solver's formula library.
# ---------------------------------------------------------------------------

BUILTIN_CONCEPTS: dict[str, ConceptMetadata] = {
    "fm.npv": ConceptMetadata(
        concept_id="fm.npv",
        label="Net present value",
        template_ref="fm.npv",
        dependencies=(),
        output_slots=("npv",),
        diagnostic_tags=("sign_error", "wrong_discount_rate", "omit_initial"),
        centrality=0.9,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.wacc": ConceptMetadata(
        concept_id="fm.wacc",
        label="Weighted average cost of capital",
        template_ref="fm.wacc",
        dependencies=("fm.cost_of_equity_dvm",),
        output_slots=("wacc",),
        diagnostic_tags=("wrong_weighting", "debt_component_error", "wrong_cost_component"),
        centrality=0.85,
        chapter_refs=("cost_of_capital",),
    ),
    "fm.capm": ConceptMetadata(
        concept_id="fm.capm",
        label="Capital asset pricing model",
        template_ref="fm.capm",
        dependencies=(),
        output_slots=("cost_equity",),
        diagnostic_tags=("wrong_premium", "risk_free_rate_error", "beta_error"),
        centrality=0.8,
        chapter_refs=("cost_of_capital",),
    ),
    "fm.payback": ConceptMetadata(
        concept_id="fm.payback",
        label="Payback period",
        template_ref="fm.payback",
        dependencies=(),
        output_slots=("payback",),
        diagnostic_tags=("cumulative_error", "fractional_year_error"),
        centrality=0.6,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.discounted_payback": ConceptMetadata(
        concept_id="fm.discounted_payback",
        label="Discounted payback period",
        template_ref="fm.discounted_payback",
        dependencies=(),
        output_slots=("discounted_payback",),
        diagnostic_tags=("pv_error", "cumulative_error"),
        centrality=0.6,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.ccc": ConceptMetadata(
        concept_id="fm.ccc",
        label="Cash conversion cycle",
        template_ref="fm.ccc",
        dependencies=(),
        output_slots=("ccc",),
        diagnostic_tags=("wrong_term", "sign_error"),
        centrality=0.65,
        chapter_refs=("working_capital",),
    ),
    "fm.cost_of_debt": ConceptMetadata(
        concept_id="fm.cost_of_debt",
        label="Cost of debt (after tax)",
        template_ref="fm.cost_of_debt",
        dependencies=(),
        output_slots=("cost_debt",),
        diagnostic_tags=("omit_tax", "wrong_rate"),
        centrality=0.7,
        chapter_refs=("cost_of_capital",),
    ),
    "fm.cost_of_equity_dvm": ConceptMetadata(
        concept_id="fm.cost_of_equity_dvm",
        label="Cost of equity (dividend valuation model)",
        template_ref="fm.cost_of_equity_dvm",
        dependencies=(),
        output_slots=("cost_equity",),
        diagnostic_tags=("wrong_growth", "dividend_error"),
        centrality=0.7,
        chapter_refs=("cost_of_capital",),
    ),
    "fm.irr": ConceptMetadata(
        concept_id="fm.irr",
        label="Internal rate of return",
        template_ref="fm.irr",
        dependencies=("fm.npv",),
        output_slots=("irr",),
        diagnostic_tags=("interpolation_error", "sign_error"),
        centrality=0.75,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.arr": ConceptMetadata(
        concept_id="fm.arr",
        label="Accounting rate of return",
        template_ref="fm.arr",
        dependencies=(),
        output_slots=("arr",),
        diagnostic_tags=("avg_investment_error", "profit_error"),
        centrality=0.55,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.eoq": ConceptMetadata(
        concept_id="fm.eoq",
        label="Economic order quantity",
        template_ref="fm.eoq",
        dependencies=(),
        output_slots=("eoq",),
        diagnostic_tags=("sqrt_error", "cost_component_error"),
        centrality=0.6,
        chapter_refs=("working_capital",),
    ),
    "fm.equivalent_annual_cost": ConceptMetadata(
        concept_id="fm.equivalent_annual_cost",
        label="Equivalent annual cost",
        template_ref="fm.equivalent_annual_cost",
        dependencies=(),
        output_slots=("equivalent_annual_cost",),
        diagnostic_tags=("pvifa_error", "annuity_error"),
        centrality=0.65,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.profitability_index": ConceptMetadata(
        concept_id="fm.profitability_index",
        label="Profitability index",
        template_ref="fm.profitability_index",
        dependencies=(),
        output_slots=("profitability_index",),
        diagnostic_tags=("pv_error", "investment_error"),
        centrality=0.6,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.gearing": ConceptMetadata(
        concept_id="fm.gearing",
        label="Gearing ratio",
        template_ref="fm.gearing",
        dependencies=(),
        output_slots=("gearing_ratio",),
        diagnostic_tags=("wrong_denominator", "component_error"),
        centrality=0.7,
        chapter_refs=("business_finance",),
    ),
    "fm.interest_cover": ConceptMetadata(
        concept_id="fm.interest_cover",
        label="Interest cover",
        template_ref="fm.interest_cover",
        dependencies=(),
        output_slots=("interest_cover",),
        diagnostic_tags=("wrong_pbit", "wrong_interest"),
        centrality=0.6,
        chapter_refs=("business_finance",),
    ),
    "fm.eps": ConceptMetadata(
        concept_id="fm.eps",
        label="Earnings per share",
        template_ref="fm.eps",
        dependencies=(),
        output_slots=("eps",),
        diagnostic_tags=("shares_error", "profit_error"),
        centrality=0.7,
        chapter_refs=("business_finance",),
    ),
    "fm.dividend_yield": ConceptMetadata(
        concept_id="fm.dividend_yield",
        label="Dividend yield",
        template_ref="fm.dividend_yield",
        dependencies=(),
        output_slots=("dividend_yield",),
        diagnostic_tags=("price_error", "dividend_error"),
        centrality=0.55,
        chapter_refs=("business_finance",),
    ),
    "fm.dividend_cover": ConceptMetadata(
        concept_id="fm.dividend_cover",
        label="Dividend cover",
        template_ref="fm.dividend_cover",
        dependencies=("fm.eps",),
        output_slots=("dividend_cover",),
        diagnostic_tags=("dividend_error", "eps_error"),
        centrality=0.55,
        chapter_refs=("business_finance",),
    ),
    "fm.asset_beta": ConceptMetadata(
        concept_id="fm.asset_beta",
        label="Asset beta (ungearing)",
        template_ref="fm.asset_beta",
        dependencies=(),
        output_slots=("asset_beta",),
        diagnostic_tags=("tax_error", "weight_error"),
        centrality=0.7,
        chapter_refs=("business_finance",),
    ),
    "fm.equity_beta": ConceptMetadata(
        concept_id="fm.equity_beta",
        label="Equity beta (regearing)",
        template_ref="fm.equity_beta",
        dependencies=("fm.asset_beta",),
        output_slots=("equity_beta",),
        diagnostic_tags=("tax_error", "weight_error"),
        centrality=0.7,
        chapter_refs=("business_finance",),
    ),
    "fm.pe_ratio": ConceptMetadata(
        concept_id="fm.pe_ratio",
        label="Price / Earnings ratio",
        template_ref="fm.pe_ratio",
        dependencies=(),
        output_slots=("pe_ratio",),
        diagnostic_tags=("eps_error", "price_error"),
        centrality=0.65,
        chapter_refs=("business_finance",),
    ),
    "fm.roe": ConceptMetadata(
        concept_id="fm.roe",
        label="Return on equity",
        template_ref="fm.roe",
        dependencies=(),
        output_slots=("roe",),
        diagnostic_tags=("equity_error", "profit_error"),
        centrality=0.65,
        chapter_refs=("business_finance",),
    ),
    "fm.cost_of_preference": ConceptMetadata(
        concept_id="fm.cost_of_preference",
        label="Cost of preference shares",
        template_ref="fm.cost_of_preference",
        dependencies=(),
        output_slots=("cost_of_preference",),
        diagnostic_tags=("price_error", "dividend_error"),
        centrality=0.6,
        chapter_refs=("cost_of_capital",),
    ),
    "fm.terp": ConceptMetadata(
        concept_id="fm.terp",
        label="Theoretical ex-rights price",
        template_ref="fm.terp",
        dependencies=(),
        output_slots=("terp",),
        diagnostic_tags=("value_error", "ratio_error"),
        centrality=0.65,
        chapter_refs=("business_finance",),
    ),
    "fm.perpetuity_npv": ConceptMetadata(
        concept_id="fm.perpetuity_npv",
        label="Present value of a perpetuity",
        template_ref="fm.perpetuity_npv",
        dependencies=(),
        output_slots=("perpetuity_npv",),
        diagnostic_tags=("rate_error", "cashflow_error"),
        centrality=0.55,
        chapter_refs=("investment_appraisal",),
    ),
    "fm.roce": ConceptMetadata(
        concept_id="fm.roce",
        label="Return on capital employed",
        template_ref="fm.roce",
        dependencies=(),
        output_slots=("roce",),
        diagnostic_tags=("capital_error", "profit_error"),
        centrality=0.6,
        chapter_refs=("investment_appraisal",),
    ),
}


# ---------------------------------------------------------------------------
# Mapping: StructureType → concept IDs
# ---------------------------------------------------------------------------


# Lazy import to avoid circular dependency at module level.
def _get_structure_type_concepts() -> dict[str, list[str]]:
    """Return mapping of StructureType enum values → concept ID lists."""
    return {
        "npv_annuity_timing": [
            "fm.npv",
            "fm.payback",
            "fm.discounted_payback",
            "fm.irr",
            "fm.equivalent_annual_cost",
            "fm.profitability_index",
            "fm.perpetuity_npv",
        ],
        "wacc_optimization": [
            "fm.wacc",
            "fm.cost_of_debt",
            "fm.cost_of_equity_dvm",
            "fm.cost_of_preference",
        ],
        "fx_exposure_hedge": [],
        "working_capital_cycle": [
            "fm.ccc",
            "fm.eoq",
        ],
        "dividend_policy_tradeoff": [
            "fm.eps",
            "fm.dividend_yield",
            "fm.dividend_cover",
            "fm.pe_ratio",
            "fm.roe",
        ],
        "capm_required_return": [
            "fm.capm",
            "fm.cost_of_equity_dvm",
        ],
        "gearing_financial_risk": [
            "fm.gearing",
            "fm.interest_cover",
            "fm.asset_beta",
            "fm.equity_beta",
            "fm.roce",
        ],
        "foreign_investment_appraisal": [],
        "rights_issue_valuation": [
            "fm.terp",
        ],
    }


STRUCTURE_TYPE_CONCEPTS: dict[str, list[str]] = _get_structure_type_concepts()


# ---------------------------------------------------------------------------
# Detection: question text → concept IDs
# ---------------------------------------------------------------------------

# Map formula names (from numerical_solver.detect_formulas) → concept IDs
_FORMULA_TO_CONCEPT: dict[str, str] = {
    "npv": "fm.npv",
    "wacc": "fm.wacc",
    "capm": "fm.capm",
    "payback": "fm.payback",
    "discounted_payback": "fm.discounted_payback",
    "ccc": "fm.ccc",
    "cost_of_debt": "fm.cost_of_debt",
    "cost_of_equity_dvm": "fm.cost_of_equity_dvm",
    "irr": "fm.irr",
    "arr": "fm.arr",
    "eoq": "fm.eoq",
    "equivalent_annual_cost": "fm.equivalent_annual_cost",
    "profitability_index": "fm.profitability_index",
    "gearing": "fm.gearing",
    "interest_cover": "fm.interest_cover",
    "eps": "fm.eps",
    "dividend_yield": "fm.dividend_yield",
    "dividend_cover": "fm.dividend_cover",
    "asset_beta": "fm.asset_beta",
    "equity_beta": "fm.equity_beta",
    "pe_ratio": "fm.pe_ratio",
    "roe": "fm.roe",
    "cost_of_preference": "fm.cost_of_preference",
    "terp": "fm.terp",
    "perpetuity_npv": "fm.perpetuity_npv",
    "roce": "fm.roce",
}


# Merge in formula registry entries
from studyplan.domain_reasoning.formula_registry import (
    build_concept_dict,
    build_formula_to_concept,
    build_structure_type_concepts,
)

BUILTIN_CONCEPTS = build_concept_dict(BUILTIN_CONCEPTS)
_FORMULA_TO_CONCEPT = build_formula_to_concept(_FORMULA_TO_CONCEPT)
STRUCTURE_TYPE_CONCEPTS = build_structure_type_concepts(STRUCTURE_TYPE_CONCEPTS)


def detect_concepts(
    question: str,
    detected_formulas: list[str] | None = None,
) -> list[str]:
    """Map a question to deterministic concept IDs.

    Accepts optional pre-computed formula names from
    ``numerical_solver.detect_formulas``.
    """
    if detected_formulas is None:
        from studyplan.numerical_solver import detect_formulas as _df

        detected_formulas = _df(question)

    seen: set[str] = set()
    result: list[str] = []
    for formula in detected_formulas:
        cid = _FORMULA_TO_CONCEPT.get(formula)
        if cid and cid not in seen:
            seen.add(cid)
            result.append(cid)
    return result
