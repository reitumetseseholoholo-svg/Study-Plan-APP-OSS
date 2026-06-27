"""Equivalent annual cost concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_equivalent_annual_cost
from studyplan.domain_reasoning.templates import FormulaTemplate


class EquivalentAnnualCostTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.equivalent_annual_cost", solve_equivalent_annual_cost, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        c = float(inputs.get("cost", 0))
        r = float(inputs.get("discount_rate", 0))
        n = int(inputs.get("years", 1))
        result = self._solver(c, r, n)

        pvifa = (1.0 - (1.0 + r) ** (-n)) / r if abs(r) > 1e-15 else float(n)
        steps: list[dict[str, Any]] = [
            {"step_id": "pvifa", "description": "PVIFA factor", "value": pvifa, "formula": f"(1-(1+{r})^-{n})/{r}"},
            {
                "step_id": "equivalent_annual_cost",
                "description": "EAC = Cost / PVIFA",
                "value": result,
                "formula": f"{c}/{pvifa}",
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
            if sid == "pvifa":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.01:
                        tags.append("pvifa_error")
            if sid == "equivalent_annual_cost":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and abs(float(sv) - float(truth_val)) > 0.01:
                        tags.append("annuity_error")
        return tags
