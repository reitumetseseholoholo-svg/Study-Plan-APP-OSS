"""Cost of debt concept template (after-tax)."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_cost_of_debt
from studyplan.domain_reasoning.templates import FormulaTemplate


class CostOfDebtTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.cost_of_debt", solve_cost_of_debt, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        r = float(inputs.get("interest_rate", 0))
        t = float(inputs.get("tax_rate", 0))
        result = self._solver(r, t)

        taxable = r * t
        steps: list[dict[str, Any]] = [
            {"step_id": "tax_shield", "description": "Tax shield on debt", "value": taxable, "formula": f"{r}*{t}"},
            {
                "step_id": "cost_of_debt",
                "description": "Cost of debt (after tax)",
                "value": result,
                "formula": f"{r}* (1-{t})",
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
            if sid == "tax_shield":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.001:
                        tags.append("omit_tax")
            if sid == "cost_of_debt":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and abs(float(sv) - float(truth_val)) > 0.01:
                        tags.append("wrong_rate")
        return tags
