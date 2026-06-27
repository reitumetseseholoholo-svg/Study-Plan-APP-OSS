"""Perpetuity NPV concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_perpetuity_npv
from studyplan.domain_reasoning.templates import FormulaTemplate


class PerpetuityNpvTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.perpetuity_npv", solve_perpetuity_npv, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        cf = float(inputs.get("annual_cashflow", 0))
        r = float(inputs.get("discount_rate", 1))
        result = self._solver(cf, r)

        steps: list[dict[str, Any]] = [
            {
                "step_id": "perpetuity_npv",
                "description": "PV = Annual CF / Discount rate",
                "value": result,
                "formula": f"{cf}/{r}",
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
            if sid == "perpetuity_npv":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and float(sv) != float(truth_val):
                        tags.append("rate_error" if float(sv) > float(truth_val) else "cashflow_error")
        return tags
