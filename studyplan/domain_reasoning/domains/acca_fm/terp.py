"""Theoretical ex-rights price concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_terp
from studyplan.domain_reasoning.templates import FormulaTemplate


class TerpTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.terp", solve_terp, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        cum = float(inputs.get("cum_rights_price", 0))
        issue = float(inputs.get("issue_price", 0))
        n = float(inputs.get("rights_ratio_n", 1))
        result = self._solver(cum, issue, n)

        total_value = n * cum + issue
        steps: list[dict[str, Any]] = [
            {
                "step_id": "total_value",
                "description": "N × cum-rights + issue price",
                "value": total_value,
                "formula": f"{n}*{cum}+{issue}",
            },
            {
                "step_id": "terp",
                "description": "TERP = Total / (N + 1)",
                "value": result,
                "formula": f"{total_value}/({n}+1)",
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
            if sid == "total_value":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.01:
                        tags.append("value_error")
            if sid == "terp":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and float(sv) != float(truth_val):
                        tags.append("ratio_error")
        return tags
