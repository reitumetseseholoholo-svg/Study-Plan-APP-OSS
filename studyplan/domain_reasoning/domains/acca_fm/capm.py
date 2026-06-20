"""CAPM concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_capm
from studyplan.domain_reasoning.templates import FormulaTemplate


class CapmTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.capm", solve_capm, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        rf = float(inputs.get("risk_free", 0))
        b = float(inputs.get("beta", 1))
        mr = float(inputs.get("market_return", 0))
        result = self._solver(rf, b, mr)

        equity_premium = mr - rf
        risk_premium = b * equity_premium
        steps: list[dict[str, Any]] = [
            {"step_id": "equity_risk_premium", "description": "Equity risk premium", "value": equity_premium, "formula": f"{mr}-{rf}"},
            {"step_id": "beta_times_premium", "description": "Beta × premium", "value": risk_premium, "formula": f"{b}*{equity_premium}"},
            {"step_id": "capm", "description": "CAPM = Rf + Beta × (Rm - Rf)", "value": result, "formula": f"{rf}+{b}*({mr}-{rf})"},
        ]
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}

    def classify_errors(self, learner_steps: list[dict[str, Any]], truth: dict[str, Any]) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        for step in learner_steps or []:
            sid = str(step.get("step_id", ""))
            if "premium" in sid:
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.001:
                        tags.append("wrong_premium" if "equity" in sid else "beta_error")
            if "risk_free" in sid or "rf" in sid:
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s.get("step_id") == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.001:
                        tags.append("risk_free_rate_error")
        return tags
