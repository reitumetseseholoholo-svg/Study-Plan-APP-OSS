"""Profitability index concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_profitability_index
from studyplan.domain_reasoning.templates import FormulaTemplate


class ProfitabilityIndexTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.profitability_index", solve_profitability_index, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        pv = float(inputs.get("pv_future_cashflows", 0))
        inv = float(inputs.get("initial_investment", 1))
        result = self._solver(pv, inv)

        steps: list[dict[str, Any]] = [
            {"step_id": "profitability_index", "description": "PI = PV of future CFs / Initial investment", "value": result, "formula": f"{pv}/{inv}"},
        ]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}

    def classify_errors(self, learner_steps: list[dict[str, Any]], truth: dict[str, Any]) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        for step in learner_steps or []:
            sid = str(step.get("step_id", ""))
            if sid == "profitability_index":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and float(sv) != float(truth_val):
                        if abs(float(sv) - float(truth_val)) > 1.0:
                            tags.append("investment_error")
                        else:
                            tags.append("pv_error")
        return tags
