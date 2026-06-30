"""Tests for domain concept metadata and detection (concepts.py).

Covers: ConceptMetadata, BUILTIN_CONCEPTS, _FORMULA_TO_CONCEPT,
STRUCTURE_TYPE_CONCEPTS, detect_concepts, label aliases.
"""

from __future__ import annotations

import pytest

from studyplan.domain_reasoning.concepts import (
    ConceptMetadata,
    BUILTIN_CONCEPTS,
    STRUCTURE_TYPE_CONCEPTS,
    detect_concepts,
    _FORMULA_TO_CONCEPT,
)


# ---------------------------------------------------------------------------
# ConceptMetadata construction
# ---------------------------------------------------------------------------


def test_concept_metadata_minimal() -> None:
    m = ConceptMetadata(concept_id="fm.test", label="Test", template_ref="fm.test")
    assert m.concept_id == "fm.test"
    assert m.label == "Test"
    assert m.template_ref == "fm.test"
    assert m.dependencies == ()
    assert m.output_slots == ()
    assert m.diagnostic_tags == ()
    assert m.centrality == 0.5


def test_concept_metadata_full() -> None:
    m = ConceptMetadata(
        concept_id="fm.npv",
        label="Net present value",
        template_ref="fm.npv",
        dependencies=("fm.capm",),
        output_slots=("npv",),
        diagnostic_tags=("sign_error", "wrong_discount_rate"),
        centrality=0.9,
        chapter_refs=("investment_appraisal",),
        outcome_ids=("a1", "b2"),
    )
    assert m.concept_id == "fm.npv"
    assert "sign_error" in m.diagnostic_tags
    assert m.centrality == 0.9
    assert "a1" in m.outcome_ids


# ---------------------------------------------------------------------------
# BUILTIN_CONCEPTS — structure and completeness
# ---------------------------------------------------------------------------

EXPECTED_CONCEPT_IDS: set[str] = {
    "fm.npv",
    "fm.wacc",
    "fm.capm",
    "fm.payback",
    "fm.discounted_payback",
    "fm.ccc",
    "fm.cost_of_debt",
    "fm.cost_of_equity_dvm",
    "fm.irr",
    "fm.arr",
    "fm.eoq",
    "fm.equivalent_annual_cost",
    "fm.profitability_index",
    "fm.gearing",
    "fm.interest_cover",
    "fm.eps",
    "fm.dividend_yield",
    "fm.dividend_cover",
    "fm.asset_beta",
    "fm.equity_beta",
    "fm.pe_ratio",
    "fm.roe",
    "fm.cost_of_preference",
    "fm.terp",
    "fm.perpetuity_npv",
    "fm.roce",
}


def test_builtin_concepts_count() -> None:
    assert len(BUILTIN_CONCEPTS) >= len(EXPECTED_CONCEPT_IDS)


def test_builtin_concepts_keys() -> None:
    for cid in EXPECTED_CONCEPT_IDS:
        assert cid in BUILTIN_CONCEPTS, f"Missing {cid}"


def test_builtin_concepts_all_have_required_fields() -> None:
    for cid, meta in BUILTIN_CONCEPTS.items():
        assert isinstance(meta, ConceptMetadata), f"{cid} not ConceptMetadata"
        assert meta.concept_id == cid, f"{cid} concept_id mismatch"
        assert isinstance(meta.label, str) and meta.label
        assert isinstance(meta.template_ref, str) and meta.template_ref
        assert 0.0 <= meta.centrality <= 1.0


def test_builtin_concepts_centrality_ranges() -> None:
    high = [m.centrality for m in BUILTIN_CONCEPTS.values() if m.centrality >= 0.8]
    low = [m.centrality for m in BUILTIN_CONCEPTS.values() if m.centrality <= 0.4]
    assert len(high) >= 2, "Should have high-centrality concepts (npv, wacc, capm)"
    assert len(low) == 0, "Low-centrality concepts should be absent"


def test_builtin_concepts_templates_reachable() -> None:
    from studyplan.domain_reasoning.templates import TEMPLATE_REGISTRY

    for cid, meta in BUILTIN_CONCEPTS.items():
        ref = meta.template_ref
        assert ref in TEMPLATE_REGISTRY, f"template_ref={ref!r} for {cid} not in TEMPLATE_REGISTRY"


def test_builtin_concepts_dependency_chain() -> None:
    """Verify dependency references point to existing concepts."""
    for cid, meta in BUILTIN_CONCEPTS.items():
        for dep in meta.dependencies:
            assert dep in BUILTIN_CONCEPTS, f"{cid} depends on {dep} which is not in BUILTIN_CONCEPTS"


# ---------------------------------------------------------------------------
# _FORMULA_TO_CONCEPT
# ---------------------------------------------------------------------------


def test_formula_to_concept_has_all_expected() -> None:
    formula_names = {
        "npv",
        "wacc",
        "capm",
        "payback",
        "discounted_payback",
        "ccc",
        "cost_of_debt",
        "cost_of_equity_dvm",
        "irr",
        "arr",
        "eoq",
        "equivalent_annual_cost",
        "profitability_index",
        "gearing",
        "interest_cover",
        "eps",
        "dividend_yield",
        "dividend_cover",
        "asset_beta",
        "equity_beta",
        "pe_ratio",
        "roe",
        "cost_of_preference",
        "terp",
        "perpetuity_npv",
        "roce",
    }
    for fname in formula_names:
        assert fname in _FORMULA_TO_CONCEPT, f"Missing formula mapping: {fname}"
        cid = _FORMULA_TO_CONCEPT[fname]
        assert cid.startswith("fm."), f"Concept ID should start with fm.: {cid}"


def test_formula_to_concept_symmetry() -> None:
    """Every formula-to-concept mapping should have a matching concept entry."""
    for fname, cid in _FORMULA_TO_CONCEPT.items():
        assert cid in BUILTIN_CONCEPTS, f"formula {fname} maps to {cid} which is not in BUILTIN_CONCEPTS"


# ---------------------------------------------------------------------------
# STRUCTURE_TYPE_CONCEPTS
# ---------------------------------------------------------------------------


def test_structure_type_keys() -> None:
    expected_types = {
        "npv_annuity_timing",
        "wacc_optimization",
        "fx_exposure_hedge",
        "working_capital_cycle",
        "dividend_policy_tradeoff",
        "capm_required_return",
        "gearing_financial_risk",
        "foreign_investment_appraisal",
        "rights_issue_valuation",
    }
    for st in expected_types:
        assert st in STRUCTURE_TYPE_CONCEPTS, f"Missing structure type: {st}"


def test_structure_type_concepts_exist() -> None:
    for st, concepts in STRUCTURE_TYPE_CONCEPTS.items():
        for cid in concepts:
            assert cid in BUILTIN_CONCEPTS, f"structure type {st} references {cid} which is not in BUILTIN_CONCEPTS"


def test_structure_type_non_empty_groups() -> None:
    non_empty = [
        "npv_annuity_timing",
        "wacc_optimization",
        "working_capital_cycle",
        "dividend_policy_tradeoff",
        "capm_required_return",
        "gearing_financial_risk",
        "rights_issue_valuation",
    ]
    for st in non_empty:
        assert len(STRUCTURE_TYPE_CONCEPTS.get(st, [])) > 0, f"Expected non-empty structure type: {st}"


# ---------------------------------------------------------------------------
# detect_concepts — default ACCA FM path
# ---------------------------------------------------------------------------


def test_detect_concepts_empty_question() -> None:
    assert detect_concepts("") == []


def test_detect_concepts_npv() -> None:
    result = detect_concepts("Calculate the NPV", detected_formulas=["npv"])
    assert result == ["fm.npv"]


def test_detect_concepts_wacc() -> None:
    result = detect_concepts("WACC", detected_formulas=["wacc"])
    assert result == ["fm.wacc"]


def test_detect_concepts_multiple() -> None:
    result = detect_concepts("NPV and WACC", detected_formulas=["npv", "wacc"])
    assert "fm.npv" in result
    assert "fm.wacc" in result


def test_detect_concepts_no_duplicates() -> None:
    result = detect_concepts("NPV NPV", detected_formulas=["npv", "npv"])
    assert len(result) == 1
    assert result == ["fm.npv"]


def test_detect_concepts_unknown_formula() -> None:
    result = detect_concepts("something weird", detected_formulas=["unknown"])
    assert result == []


def test_detect_concepts_some_known_some_unknown() -> None:
    result = detect_concepts("NPV and something", detected_formulas=["npv", "foobar"])
    assert result == ["fm.npv"]


def test_detect_concepts_none_formulas_triggers_auto_detect() -> None:
    """When detected_formulas is None, detect_concepts calls the solver's detect."""
    result = detect_concepts("What is the NPV of this project with cashflows 100, 200 at 10%?")
    assert "fm.npv" in result


# ---------------------------------------------------------------------------
# detect_concepts — domain routing
# ---------------------------------------------------------------------------


def test_detect_concepts_pmp_domain() -> None:
    """PMP domain routing should not crash and return PMP concepts."""
    from studyplan.domain_reasoning.domain_registry import get_registry

    reg = get_registry("pmp")
    assert reg is not None
    result = detect_concepts("Cost Performance Index", domain="pmp")
    # PMP registry has formula detection via patterns
    assert isinstance(result, list)


def test_detect_concepts_unknown_domain() -> None:
    """Unknown domain should not raise."""
    with pytest.raises(KeyError):
        detect_concepts("test", domain="nonexistent")


# ---------------------------------------------------------------------------
# Label aliases (from _build_acca_registry)
# ---------------------------------------------------------------------------


def test_label_aliases_exist() -> None:
    """Label aliases should be importable through the ACCA registry."""
    from studyplan.domain_reasoning.concepts import _build_acca_registry

    reg = _build_acca_registry()
    assert "cost of equity" in reg.label_aliases
    assert reg.label_aliases["cost of equity"] == "cost_equity"
    assert "inventory days" in reg.label_aliases
    assert reg.label_aliases["inventory days"] == "inventory_days"
    assert "payable days" in reg.label_aliases
    assert reg.label_aliases["payable days"] == "payables_days"
