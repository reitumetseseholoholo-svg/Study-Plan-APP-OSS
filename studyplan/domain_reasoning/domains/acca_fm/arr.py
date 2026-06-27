"""ARR/ROCE concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_arr
from studyplan.domain_reasoning.templates import FormulaTemplate


class ArrTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.arr", solve_arr, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        profit = float(inputs.get("average_profit", 0))
        invest = float(inputs.get("initial_investment", 1))
        residual = float(inputs.get("residual_value", 0))
        result = self._solver(profit, invest, residual)

        avg_investment = (invest + residual) / 2.0
        steps: list[dict[str, Any]] = [
            {
                "step_id": "avg_investment",
                "description": "Average investment",
                "value": avg_investment,
                "formula": f"({invest}+{residual})/2",
            },
            {
                "step_id": "arr",
                "description": "ARR = Avg profit / Avg investment",
                "value": result,
                "formula": f"{profit}/{avg_investment}",
            },
        ]
        return {
            "concept_id": self.concept_id,
            "result": result,
            "steps": steps,
            "inputs": dict(inputs),
            "is_nan": isinstance(result, float) and math.isnan(result),
        }

    def classify_errors(self, learner_steps: list[dict[str, Any]], truth: dict[str, Any]) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        for step in learner_steps or []:
            sid = str(step.get("step_id", ""))
            if sid == "avg_investment":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == "avg_investment"), None)
                    if ts and float(sv) != float(ts["value"]):
                        expected = float(ts["value"])
                        if float(sv) == expected * 2:
                            tags.append("avg_investment_error")
        return tags
