"""Return on capital employed concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_roce
from studyplan.domain_reasoning.templates import FormulaTemplate


class RoceTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.roce", solve_roce, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        p = float(inputs.get("pbit", 0))
        ce = float(inputs.get("capital_employed", 1))
        result = self._solver(p, ce)

        steps: list[dict[str, Any]] = [
            {"step_id": "roce", "description": "ROCE = PBIT / Capital employed", "value": result, "formula": f"{p}/{ce}"},
        ]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}

    def classify_errors(self, learner_steps: list[dict[str, Any]], truth: dict[str, Any]) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        for step in learner_steps or []:
            sid = str(step.get("step_id", ""))
            if sid == "roce":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and float(sv) != float(truth_val):
                        tags.append("capital_error" if float(sv) > float(truth_val) else "profit_error")
        return tags
