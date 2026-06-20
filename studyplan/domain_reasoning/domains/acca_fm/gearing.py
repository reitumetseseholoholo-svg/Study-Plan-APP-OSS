"""Gearing and related ratio concept templates."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_gearing, solve_interest_cover, solve_eps, solve_dividend_yield, solve_dividend_cover
from studyplan.domain_reasoning.templates import FormulaTemplate


class GearingTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.gearing", solve_gearing, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        db = float(inputs.get("debt", 0))
        eq = float(inputs.get("equity", 0))
        result = self._solver(db, eq)

        v = db + eq
        steps: list[dict[str, Any]] = [
            {"step_id": "total_capital", "description": "Debt + Equity", "value": v, "formula": f"{db}+{eq}"},
            {"step_id": "gearing", "description": "Debt / (Debt + Equity)", "value": result, "formula": f"{db}/{v}"},
        ]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}

    def classify_errors(self, learner_steps: list[dict[str, Any]], truth: dict[str, Any]) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        inputs = truth.get("inputs", {})
        debt = float(inputs.get("debt", 0))
        equity = float(inputs.get("equity", 1))
        for step in learner_steps or []:
            sid = str(step.get("step_id", ""))
            if sid == "gearing":
                sv = step.get("value")
                if sv is not None and equity > 0:
                    learner_val = float(sv)
                    truth_result = truth.get("result")
                    # Check if learner used Debt/Equity instead of Debt/(Debt+Equity)
                    wrong_debt_equity = debt / equity
                    if abs(learner_val - wrong_debt_equity) < 0.01:
                        tags.append("wrong_denominator")
                    # Check if learner used Equity/(Debt+Equity) instead
                    elif truth_result is not None:
                        wrong_equity_ratio = equity / (debt + equity)
                        if abs(learner_val - wrong_equity_ratio) < 0.01:
                            tags.append("wrong_denominator")
        return tags


class InterestCoverTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.interest_cover", solve_interest_cover, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        pbit = float(inputs.get("pbit", 0))
        interest = float(inputs.get("interest_expense", 0))
        result = self._solver(pbit, interest)
        steps = [{"step_id": "interest_cover", "description": "PBIT / Interest", "value": result, "formula": f"{pbit}/{interest}"}]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}


class EpsTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.eps", solve_eps, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        profit = float(inputs.get("profit_after_tax", 0))
        shares = float(inputs.get("number_of_shares", 1))
        result = self._solver(profit, shares)
        steps = [{"step_id": "eps", "description": "Profit / Shares", "value": result, "formula": f"{profit}/{shares}"}]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}


class DividendYieldTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.dividend_yield", solve_dividend_yield, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        d = float(inputs.get("dividend_per_share", 0))
        p = float(inputs.get("market_price", 1))
        result = self._solver(d, p)
        steps = [{"step_id": "dividend_yield", "description": "Dividend / Price", "value": result, "formula": f"{d}/{p}"}]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}


class DividendCoverTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.dividend_cover", solve_dividend_cover, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        eps_val = float(inputs.get("eps", 0))
        d = float(inputs.get("dividend_per_share", 1))
        result = self._solver(eps_val, d)
        steps = [{"step_id": "dividend_cover", "description": "EPS / Dividend", "value": result, "formula": f"{eps_val}/{d}"}]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}
