"""EOQ concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_eoq
from studyplan.domain_reasoning.templates import FormulaTemplate


class EoqTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.eoq", solve_eoq, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        d = float(inputs.get("annual_demand", 0))
        o = float(inputs.get("ordering_cost", 0))
        h = float(inputs.get("holding_cost_per_unit", 1))
        result = self._solver(d, o, h)

        numerator = 2 * d * o
        dividend_val = numerator / h if abs(h) > 1e-15 else float("inf")
        steps: list[dict[str, Any]] = [
            {"step_id": "two_d_o", "description": "2 × D × O", "value": numerator, "formula": f"2*{d}*{o}"},
            {
                "step_id": "dividend",
                "description": "(2 × D × O) / H",
                "value": dividend_val,
                "formula": f"{numerator}/{h}",
            },
            {
                "step_id": "eoq",
                "description": "EOQ = sqrt((2 × D × O) / H)",
                "value": result,
                "formula": f"sqrt({numerator}/{h})",
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
            if sid == "two_d_o":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == "two_d_o"), None)
                    if ts and float(sv) != float(ts["value"]):
                        expected = float(ts["value"])
                        if float(sv) == expected / 2 or float(sv) == expected * 2:
                            tags.append("cost_component_error")
            if sid == "eoq":
                sv = step.get("value")
                if sv is not None:
                    truth_result = truth.get("result")
                    if truth_result is not None and float(sv) > 0 and float(truth_result) > 0:
                        ratio = float(sv) / float(truth_result)
                        if abs(ratio - 1.0) > 0.05:
                            tags.append("sqrt_error")
        return tags
