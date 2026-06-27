"""Cost of preference shares concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_cost_of_preference
from studyplan.domain_reasoning.templates import FormulaTemplate


class CostOfPreferenceTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.cost_of_preference", solve_cost_of_preference, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        d = float(inputs.get("preference_dividend", 0))
        p = float(inputs.get("market_price", 1))
        result = self._solver(d, p)

        steps: list[dict[str, Any]] = [
            {
                "step_id": "cost_of_preference",
                "description": "Kp = Pref div / Market price",
                "value": result,
                "formula": f"{d}/{p}",
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
            if sid == "cost_of_preference":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and float(sv) != float(truth_val):
                        tags.append("price_error" if float(sv) > float(truth_val) else "dividend_error")
        return tags
