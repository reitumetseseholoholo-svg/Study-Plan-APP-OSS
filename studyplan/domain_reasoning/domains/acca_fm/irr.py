"""IRR concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_irr, solve_npv
from studyplan.domain_reasoning.templates import FormulaTemplate


class IrrTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.irr", solve_irr, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        cfs = list(inputs.get("cashflows", []))
        init = float(inputs.get("initial", 0))
        result = self._solver(cfs, init)

        steps: list[dict[str, Any]] = []
        for rate_guess in [0.05, 0.10, 0.15, 0.20]:
            npv_at = solve_npv(cfs, rate_guess, init)
            steps.append(
                {
                    "step_id": f"npv_at_{int(rate_guess * 100)}pct",
                    "description": f"NPV at {int(rate_guess * 100)}%",
                    "value": npv_at,
                    "formula": f"NPV({cfs}, {rate_guess}, {init})",
                }
            )
        steps.append(
            {
                "step_id": "irr",
                "description": "IRR (interpolated)",
                "value": result,
                "formula": f"IRR({cfs}, {init})",
            }
        )
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
            if "npv_at" in sid:
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > max(0.01, abs(float(ts["value"])) * 0.05):
                        tags.append("interpolation_error")
            if sid == "irr":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == "irr"), None)
                    if ts and float(sv) * float(ts["value"]) < 0:
                        tags.append("sign_error")
        return tags
