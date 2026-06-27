"""Cash conversion cycle concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_cash_conversion_cycle
from studyplan.domain_reasoning.templates import FormulaTemplate


class CccTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.ccc", solve_cash_conversion_cycle, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        dio = float(inputs.get("dio", 0))
        dso = float(inputs.get("dso", 0))
        dpo = float(inputs.get("dpo", 0))
        result = self._solver(dio, dso, dpo)

        steps: list[dict[str, Any]] = [
            {"step_id": "dio_plus_dso", "description": "DIO + DSO", "value": dio + dso, "formula": f"{dio}+{dso}"},
            {
                "step_id": "ccc",
                "description": "CCC = DIO + DSO - DPO",
                "value": result,
                "formula": f"{dio}+{dso}-{dpo}",
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
            if sid == "ccc":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == "ccc"), None)
                    if ts and float(sv) != float(ts["value"]):
                        diff = float(sv) - float(ts["value"])
                        if abs(abs(diff) - 2 * float(ts["value"])) < 1.0:
                            tags.append("sign_error")
                        else:
                            tags.append("wrong_term")
        return tags
