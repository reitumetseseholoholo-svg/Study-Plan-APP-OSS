"""Cost of equity (DVM) concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_cost_of_equity_dvm
from studyplan.domain_reasoning.templates import FormulaTemplate


class CostOfEquityDvmTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.cost_of_equity_dvm", solve_cost_of_equity_dvm, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        d = float(inputs.get("dividend", 0))
        p = float(inputs.get("price", 1))
        g = float(inputs.get("growth", 0))
        result = self._solver(d, p, g)

        d1 = d * (1.0 + g)
        steps: list[dict[str, Any]] = [
            {
                "step_id": "dividend_next_year",
                "description": "Expected dividend next year",
                "value": d1,
                "formula": f"{d}*(1+{g})",
            },
            {
                "step_id": "cost_of_equity_dvm",
                "description": "Cost of equity (DVM)",
                "value": result,
                "formula": f"({d1}/{p})+{g}",
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
            if sid == "dividend_next_year":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.001:
                        tags.append("dividend_error")
            if sid == "cost_of_equity_dvm":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and abs(float(sv) - float(truth_val)) > 0.01:
                        tags.append("wrong_growth")
        return tags
