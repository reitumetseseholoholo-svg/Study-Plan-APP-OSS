from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from studyplan.domain_reasoning.formula_registry import _substitute_and_eval
from studyplan.numerical_solver import (
    solve_npv,
    solve_payback_period,
    solve_discounted_payback,
    solve_irr,
    solve_arr,
    solve_profitability_index,
    solve_perpetuity_npv,
    solve_equivalent_annual_cost,
    solve_wacc,
    solve_capm,
    solve_cash_conversion_cycle,
    solve_cost_of_debt,
    solve_cost_of_equity_dvm,
    solve_eoq,
    solve_gearing,
    solve_interest_cover,
    solve_eps,
    solve_dividend_yield,
    solve_dividend_cover,
    solve_asset_beta,
    solve_equity_beta,
    solve_pe_ratio,
    solve_roe,
    solve_cost_of_preference,
    solve_terp,
    solve_roce,
)
from studyplan.provenance.knowledge_ir import FMFormula
from studyplan.provenance.learning.events import execution_result
from studyplan.provenance.learning.event_bus import EventBus


_CANONICAL_SOLVERS: dict[str, Any] = {
    "fm.npv": solve_npv,
    "fm.payback": solve_payback_period,
    "fm.discounted_payback": solve_discounted_payback,
    "fm.irr": solve_irr,
    "fm.arr": solve_arr,
    "fm.profitability_index": solve_profitability_index,
    "fm.perpetuity_npv": solve_perpetuity_npv,
    "fm.equivalent_annual_cost": solve_equivalent_annual_cost,
    "fm.wacc": solve_wacc,
    "fm.capm": solve_capm,
    "fm.cash_conversion_cycle": solve_cash_conversion_cycle,
    "fm.cost_of_debt": solve_cost_of_debt,
    "fm.cost_of_equity_dvm": solve_cost_of_equity_dvm,
    "fm.eoq": solve_eoq,
    "fm.gearing": solve_gearing,
    "fm.interest_cover": solve_interest_cover,
    "fm.eps": solve_eps,
    "fm.dividend_yield": solve_dividend_yield,
    "fm.dividend_cover": solve_dividend_cover,
    "fm.asset_beta": solve_asset_beta,
    "fm.equity_beta": solve_equity_beta,
    "fm.pe_ratio": solve_pe_ratio,
    "fm.roe": solve_roe,
    "fm.cost_of_preference": solve_cost_of_preference,
    "fm.terp": solve_terp,
    "fm.roce": solve_roce,
}

_FORMULA_PARAM_MAP: dict[str, dict[str, str]] = {
    "fm.npv": {"r": "rate"},
    "fm.discounted_payback": {"r": "rate"},
    "fm.irr": {"low_rate": "low_rate", "high_rate": "high_rate"},
    "fm.arr": {"avg_profit": "average_profit", "avg_investment": "average_investment"},
    "fm.perpetuity_npv": {"annual_cf": "annual_cashflow", "r": "discount_rate"},
    "fm.equivalent_annual_cost": {"n": "years"},
}


@dataclass(frozen=True)
class FMExecutionContext:
    formula_id: str
    params: dict[str, float]


class FMExecutionEngine:
    """Deterministic formula evaluation engine.

    Given a formula and concrete parameter values, computes the correct
    answer. Pure function territory — zero state, zero pedagogy, zero
    randomness.
    """

    def __init__(self, formula_registry: dict[str, FMFormula] | None = None, bus: EventBus | None = None):
        self._formulas = formula_registry or {}
        self._bus = bus

    def evaluate(self, formula: FMFormula, ctx: FMExecutionContext) -> float:
        solver = _CANONICAL_SOLVERS.get(formula.concept_id)
        evaluation_trace: list[str] = []
        if solver is not None:
            output = self._call_solver(formula.concept_id, solver, ctx.params)
            evaluation_trace = ["solver_lookup", formula.concept_id]
        else:
            output = self._evaluate_expression(formula, ctx.params)
            evaluation_trace = ["expression_eval", formula.concept_id]
        self._emit_execution(formula.concept_id, dict(ctx.params), output, evaluation_trace)
        return output

    def evaluate_by_id(self, formula_id: str, ctx: FMExecutionContext) -> float:
        formula = self._formulas.get(formula_id)
        if formula is None:
            raise KeyError(f"Unknown formula: {formula_id}")
        return self.evaluate(formula, ctx)

    def _emit_execution(self, formula_id: str, inputs: dict[str, float], output: float, trace: list[str]) -> None:
        if self._bus is not None:
            self._bus.emit(
                execution_result(
                    formula_id=formula_id,
                    inputs=inputs,
                    output=output,
                    evaluation_trace=trace,
                    session_id=self._bus.session_id,
                )
            )

    def _call_solver(self, formula_id: str, solver: Any, params: dict[str, float]) -> float:
        mapped: dict[str, Any] = {}
        aliases = _FORMULA_PARAM_MAP.get(formula_id, {})
        sig = solver.__code__
        vnames = sig.co_varnames[: sig.co_argcount]
        for name in vnames:
            if name in params:
                mapped[name] = params[name]
            else:
                aliased = _find_alias(name, params, aliases)
                if aliased is not None:
                    mapped[name] = aliased
                elif name == "cashflows":
                    mapped[name] = _extract_list(params, "cashflows")
                else:
                    mapped[name] = 0.0
        try:
            result = solver(**mapped)
            if math.isnan(result):
                return 0.0
            return result
        except Exception:
            return 0.0

    def _evaluate_expression(self, formula: FMFormula, params: dict[str, float]) -> float:
        env: dict[str, float] = {}
        for p in formula.params:
            val = params.get(p.name)
            if val is not None:
                env[p.name] = float(val)
        try:
            result = _substitute_and_eval(formula.expression, env)
            if math.isnan(result):
                return 0.0
            return result
        except Exception:
            return 0.0


def _extract_list(params: dict[str, float], key: str) -> list[float]:
    raw = params.get(key)
    if isinstance(raw, (list, tuple)):
        return [float(v) for v in raw]
    return []


def _find_alias(solver_param: str, params: dict[str, float], aliases: dict[str, str]) -> Any:
    for formula_name, alias_name in aliases.items():
        if alias_name == solver_param and formula_name in params:
            return params[formula_name]
    return None
