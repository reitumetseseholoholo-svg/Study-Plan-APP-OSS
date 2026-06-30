"""Tests for domain template infrastructure: registry, protocol, run_template."""

from __future__ import annotations

import math
from typing import Any


from studyplan.domain_reasoning.templates import (
    FormulaTemplate,
    TEMPLATE_REGISTRY,
    run_template,
)


# ---------------------------------------------------------------------------
# FormulaTemplate construction
# ---------------------------------------------------------------------------


def _dummy_solver(a: float, b: float) -> float:
    return a + b


def test_formula_template_init() -> None:
    """FormulaTemplate wraps a solver with metadata."""
    t = FormulaTemplate("fm.test", _dummy_solver, version="2.0.0")
    assert t.concept_id == "fm.test"
    assert t.template_version == "2.0.0"
    assert t._solver is _dummy_solver


def test_formula_template_default_solve() -> None:
    """Default solve() calls the solver with **inputs."""
    t = FormulaTemplate("fm.test", _dummy_solver)
    result = t.solve({"a": 3, "b": 4})
    assert result["concept_id"] == "fm.test"
    assert result["result"] == 7.0
    assert result["is_nan"] is False
    assert result["inputs"] == {"a": 3, "b": 4}


def test_formula_template_default_solve_nan() -> None:
    """NaN from solver is reflected in is_nan."""

    def _nan_solver(**kwargs: Any) -> float:
        return float("nan")

    t = FormulaTemplate("fm.nan_test", _nan_solver)
    result = t.solve({})
    assert result["is_nan"] is True
    assert math.isnan(result["result"])


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_all_registry_entries_conform_to_protocol() -> None:
    """Every entry in TEMPLATE_REGISTRY satisfies the ConceptTemplate protocol."""
    for cid, template in TEMPLATE_REGISTRY.items():
        assert isinstance(cid, str), f"Non-string key: {cid!r}"
        # Duck-type check: must have concept_id, template_version, solve()
        assert hasattr(template, "concept_id"), f"{cid} missing concept_id"
        assert hasattr(template, "template_version"), f"{cid} missing template_version"
        assert hasattr(template, "solve"), f"{cid} missing solve()"
        assert hasattr(template, "evaluate_steps"), f"{cid} missing evaluate_steps()"
        assert hasattr(template, "classify_errors"), f"{cid} missing classify_errors()"


# ---------------------------------------------------------------------------
# run_template()
# ---------------------------------------------------------------------------


def test_run_template_known_concept() -> None:
    """run_template returns the solve result for a known concept."""
    result = run_template("fm.capm", {"risk_free": 0.02, "beta": 1.0, "market_return": 0.08})
    assert result is not None
    assert result["concept_id"] == "fm.capm"
    assert abs(result["result"] - 0.08) < 1e-9


def test_run_template_unknown_concept() -> None:
    """run_template returns None for an unknown concept."""
    result = run_template("fm.does_not_exist", {})
    assert result is None


def test_run_template_nan_concept() -> None:
    """run_template reflects NaN from solver."""
    result = run_template("fm.wacc", {"equity": 0, "debt": 0, "cost_equity": 0.12, "cost_debt": 0.06})
    assert result is not None
    assert result["is_nan"] is True


# ---------------------------------------------------------------------------
# Registry keys (smoke-test that all expected concepts are present)
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


def test_registry_contains_all_expected_concepts() -> None:
    """All 21 ACCA FM domain templates are registered."""
    for cid in EXPECTED_CONCEPT_IDS:
        assert cid in TEMPLATE_REGISTRY, f"Expected {cid} in TEMPLATE_REGISTRY"


def test_registry_min_size() -> None:
    """Registry has at least the 21 hand-written templates (plus auto-generated)."""
    assert len(TEMPLATE_REGISTRY) >= len(EXPECTED_CONCEPT_IDS)


# ---------------------------------------------------------------------------
# classify_errors defaults
# ---------------------------------------------------------------------------


def _simple_solver(x: float) -> float:
    return x * 2


def test_classify_errors_default_mismatch() -> None:
    """Default classify_errors tags step_id_mismatch when diff > 0.5%."""
    t = FormulaTemplate("fm.double", _simple_solver)
    truth = t.solve({"x": 10})
    tags = t.classify_errors([{"step_id": "final", "value": 19.0}], truth)
    assert "final_mismatch" in tags


def test_classify_errors_default_match() -> None:
    """Default classify_errors returns no tags when answer matches."""
    t = FormulaTemplate("fm.double", _simple_solver)
    truth = t.solve({"x": 10})
    tags = t.classify_errors([{"step_id": "final", "value": 20.0}], truth)
    assert tags == []


def test_classify_errors_default_nan_truth() -> None:
    """NaN truth returns empty tags."""

    def _nan_solver(**kwargs: Any) -> float:
        return float("nan")

    t = FormulaTemplate("fm.nan", _nan_solver)
    truth = t.solve({})
    tags = t.classify_errors([{"step_id": "s1", "value": 1.0}], truth)
    assert tags == []


def test_classify_errors_parse_error() -> None:
    """Non-numeric learner step values produce parse error tags."""
    t = FormulaTemplate("fm.test", _simple_solver)
    truth = t.solve({"x": 5})
    tags = t.classify_errors([{"step_id": "s1", "value": "not_a_number"}], truth)
    assert "s1_parse_error" in tags
