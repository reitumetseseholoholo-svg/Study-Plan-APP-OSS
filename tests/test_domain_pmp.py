"""Tests for PMP domain formulas.

Covers: CPI, SPI, EAC solver functions, candidate extraction,
pattern matching, NaN edge cases, and registry construction.
"""

from __future__ import annotations

import copy
import math
import re

import pytest

from studyplan.domain_reasoning.domains.pmp import _pmp_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Save/restore PMP registry to prevent cross-test pollution."""
    saved = copy.deepcopy(dict(_pmp_registry))
    yield
    _pmp_registry.clear()
    _pmp_registry.update(saved)


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_pmp_registry_has_three_formulas() -> None:
    assert len(_pmp_registry) == 3


def test_pmp_registry_keys() -> None:
    assert "pmp.cpi" in _pmp_registry
    assert "pmp.spi" in _pmp_registry
    assert "pmp.eac" in _pmp_registry


def test_pmp_registry_all_expression() -> None:
    for _cid, decl in _pmp_registry.items():
        assert decl.concept_type == "expression"
        assert decl.solver_fn is not None
        assert decl.template is not None


# ---------------------------------------------------------------------------
# CPI: Cost Performance Index (CPI = EV / AC)
# ---------------------------------------------------------------------------


def test_cpi_nominal() -> None:
    solver = _pmp_registry["pmp.cpi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, ac=80.0)
    assert result == 1.25


def test_cpi_under_budget() -> None:
    solver = _pmp_registry["pmp.cpi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, ac=120.0)
    assert result == pytest.approx(0.8333, rel=1e-3)


def test_cpi_exact_on_budget() -> None:
    solver = _pmp_registry["pmp.cpi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, ac=100.0)
    assert result == 1.0


def test_cpi_zero_ac() -> None:
    solver = _pmp_registry["pmp.cpi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, ac=0.0)
    assert math.isnan(result) or math.isinf(result)


def test_cpi_missing_param() -> None:
    solver = _pmp_registry["pmp.cpi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0)
    assert math.isnan(result)


def test_cpi_zero_ev() -> None:
    solver = _pmp_registry["pmp.cpi"].solver_fn
    assert solver is not None
    result = solver(ev=0.0, ac=100.0)
    assert result == 0.0


def test_cpi_negative_ac() -> None:
    solver = _pmp_registry["pmp.cpi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, ac=-20.0)
    assert result == -5.0


def test_cpi_candidate_fn() -> None:
    cand = _pmp_registry["pmp.cpi"].candidate_fn
    assert cand is not None
    nums = [{"value": 100.0, "is_percent": False}, {"value": 50.0, "is_percent": False}]
    candidates = cand(nums)
    assert len(candidates) > 0


def test_cpi_patterns() -> None:
    patterns = _pmp_registry["pmp.cpi"].compiled_patterns
    assert patterns is not None
    for p in patterns:
        assert isinstance(p, re.Pattern)
    assert any(p.search("Cost Performance Index") for p in patterns)
    assert any(p.search("CPI") for p in patterns)
    assert any(p.search("EV / AC") for p in patterns)


# ---------------------------------------------------------------------------
# SPI: Schedule Performance Index (SPI = EV / PV)
# ---------------------------------------------------------------------------


def test_spi_nominal() -> None:
    solver = _pmp_registry["pmp.spi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, pv=80.0)
    assert result == 1.25


def test_spi_behind_schedule() -> None:
    solver = _pmp_registry["pmp.spi"].solver_fn
    assert solver is not None
    result = solver(ev=50.0, pv=100.0)
    assert result == 0.5


def test_spi_ahead() -> None:
    solver = _pmp_registry["pmp.spi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, pv=50.0)
    assert result == 2.0


def test_spi_zero_pv() -> None:
    solver = _pmp_registry["pmp.spi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0, pv=0.0)
    assert math.isnan(result) or math.isinf(result)


def test_spi_missing_param() -> None:
    solver = _pmp_registry["pmp.spi"].solver_fn
    assert solver is not None
    result = solver(ev=100.0)
    assert math.isnan(result)


def test_spi_large_values() -> None:
    solver = _pmp_registry["pmp.spi"].solver_fn
    assert solver is not None
    result = solver(ev=1e9, pv=2e9)
    assert result == 0.5


def test_spi_candidate_fn() -> None:
    cand = _pmp_registry["pmp.spi"].candidate_fn
    assert cand is not None
    nums = [{"value": 80.0, "is_percent": False}, {"value": 100.0, "is_percent": False}]
    candidates = cand(nums)
    assert len(candidates) > 0


def test_spi_patterns() -> None:
    patterns = _pmp_registry["pmp.spi"].compiled_patterns
    assert patterns is not None
    assert any(p.search("Schedule Performance Index") for p in patterns)


# ---------------------------------------------------------------------------
# EAC: Estimate at Completion (EAC = BAC / CPI)
# ---------------------------------------------------------------------------


def test_eac_nominal() -> None:
    solver = _pmp_registry["pmp.eac"].solver_fn
    assert solver is not None
    result = solver(bac=100000.0, cpi=0.8)
    assert result == 125000.0


def test_eac_on_track() -> None:
    solver = _pmp_registry["pmp.eac"].solver_fn
    assert solver is not None
    result = solver(bac=100000.0, cpi=1.0)
    assert result == 100000.0


def test_eac_over_budget() -> None:
    solver = _pmp_registry["pmp.eac"].solver_fn
    assert solver is not None
    result = solver(bac=100000.0, cpi=0.5)
    assert result == 200000.0


def test_eac_zero_cpi() -> None:
    solver = _pmp_registry["pmp.eac"].solver_fn
    assert solver is not None
    result = solver(bac=100000.0, cpi=0.0)
    assert math.isnan(result) or math.isinf(result)


def test_eac_missing_param() -> None:
    solver = _pmp_registry["pmp.eac"].solver_fn
    assert solver is not None
    result = solver(bac=100000.0)
    assert math.isnan(result)


def test_eac_zero_bac() -> None:
    solver = _pmp_registry["pmp.eac"].solver_fn
    assert solver is not None
    result = solver(bac=0.0, cpi=0.8)
    assert result == 0.0


def test_eac_negative_cpi() -> None:
    solver = _pmp_registry["pmp.eac"].solver_fn
    assert solver is not None
    result = solver(bac=100000.0, cpi=-0.5)
    assert result == -200000.0


def test_eac_candidate_fn() -> None:
    cand = _pmp_registry["pmp.eac"].candidate_fn
    assert cand is not None
    nums = [{"value": 100000.0, "is_percent": False}, {"value": 0.8, "is_percent": False}]
    candidates = cand(nums)
    assert len(candidates) > 0


def test_eac_patterns() -> None:
    patterns = _pmp_registry["pmp.eac"].compiled_patterns
    assert patterns is not None
    assert any(p.search("Estimate at Completion") for p in patterns)


# ---------------------------------------------------------------------------
# Cross-formula: EAC depends on CPI
# ---------------------------------------------------------------------------


def test_eac_dependency() -> None:
    decl = _pmp_registry["pmp.eac"]
    assert "pmp.cpi" in decl.dependencies


# ---------------------------------------------------------------------------
# Template solve
# ---------------------------------------------------------------------------


def test_cpi_template_solve() -> None:
    tmpl = _pmp_registry["pmp.cpi"].template
    assert tmpl is not None
    result = tmpl.solve({"ev": 100.0, "ac": 50.0})
    assert result["result"] == 2.0
    assert not result["is_nan"]
    assert len(result["steps"]) == 1


def test_eac_template_solve() -> None:
    tmpl = _pmp_registry["pmp.eac"].template
    assert tmpl is not None
    result = tmpl.solve({"bac": 100000.0, "cpi": 0.8})
    assert result["result"] == 125000.0


def test_cpi_template_solve_missing() -> None:
    tmpl = _pmp_registry["pmp.cpi"].template
    assert tmpl is not None
    result = tmpl.solve({"ev": 100.0})
    assert result["is_nan"]


def test_cpi_template_evaluate_steps() -> None:
    tmpl = _pmp_registry["pmp.cpi"].template
    assert tmpl is not None
    truth = tmpl.solve({"ev": 100.0, "ac": 80.0})
    learner = [{"step_id": "cpi", "value": 1.25}]
    evals = tmpl.evaluate_steps(learner, truth)
    assert evals[0]["match"] is True


def test_cpi_template_classify_errors() -> None:
    tmpl = _pmp_registry["pmp.cpi"].template
    assert tmpl is not None
    truth = tmpl.solve({"ev": 100.0, "ac": 80.0})
    learner = [{"step_id": "cpi", "value": 99.0}]
    tags = tmpl.classify_errors(learner, truth)
    assert "cpi_mismatch" in tags


# ---------------------------------------------------------------------------
# Template evaluate_steps edge cases
# ---------------------------------------------------------------------------


def test_template_evaluate_empty_learner() -> None:
    tmpl = _pmp_registry["pmp.cpi"].template
    assert tmpl is not None
    assert tmpl.evaluate_steps([], {"result": 1.0}) == []


def test_template_evaluate_nan_truth() -> None:
    tmpl = _pmp_registry["pmp.cpi"].template
    assert tmpl is not None
    truth = tmpl.solve({"ev": 0.0, "ac": 0.0})
    learner = [{"step_id": "cpi", "value": 1.0}]
    evals = tmpl.evaluate_steps(learner, truth)
    assert len(evals) == 0 or evals[0].get("match") is False


def test_template_classify_nan_truth() -> None:
    tmpl = _pmp_registry["pmp.cpi"].template
    assert tmpl is not None
    assert tmpl.classify_errors([{"step_id": "cpi", "value": 1.0}], {"result": float("nan")}) == []
