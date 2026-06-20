"""Payback and discounted payback concept templates."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_payback_period, solve_discounted_payback
from studyplan.domain_reasoning.templates import FormulaTemplate


class PaybackTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.payback", solve_payback_period, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        init = float(inputs.get("initial", 0))
        cfs = list(inputs.get("cashflows", []))
        result = self._solver(init, cfs)

        steps: list[dict[str, Any]] = []
        cumulative = 0.0
        for t, cf in enumerate(cfs, 1):
            cumulative += cf
            steps.append({
                "step_id": f"cumulative_year_{t}",
                "description": f"Cumulative after year {t}",
                "value": cumulative,
                "formula": f"cumulative + {cf}",
            })
        steps.append({
            "step_id": "payback",
            "description": "Payback period (years)",
            "value": result,
            "formula": f"Payback({init}, {cfs})",
        })
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}

    def classify_errors(self, learner_steps: list[dict[str, Any]], truth: dict[str, Any]) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        for step in learner_steps or []:
            sid = str(step.get("step_id", ""))
            if "cumulative" in sid:
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.01:
                        tags.append("cumulative_error")
            if sid == "payback":
                sv = step.get("value")
                if sv is not None:
                    truth_result = truth.get("result")
                    if truth_result is not None:
                        diff = abs(float(sv) - float(truth_result))
                        frac = diff - int(diff)
                        if frac > 0.01 and abs(frac - 0.5) > 0.01:
                            tags.append("fractional_year_error")
        return tags


class DiscountedPaybackTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.discounted_payback", solve_discounted_payback, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        init = float(inputs.get("initial", 0))
        cfs = list(inputs.get("cashflows", []))
        rate = float(inputs.get("rate", 0))
        result = self._solver(init, cfs, rate)

        steps: list[dict[str, Any]] = []
        cumulative = 0.0
        for t, cf in enumerate(cfs, 1):
            pv = cf / ((1.0 + rate) ** t)
            cumulative += pv
            steps.append({
                "step_id": f"pv_year_{t}",
                "description": f"PV of year {t}",
                "value": pv,
                "formula": f"{cf}/(1+{rate})^{t}",
            })
            steps.append({
                "step_id": f"cum_disc_year_{t}",
                "description": f"Cumulative discounted after year {t}",
                "value": cumulative,
                "formula": f"cumulative + {pv}",
            })
        steps.append({
            "step_id": "discounted_payback",
            "description": "Discounted payback period (years)",
            "value": result,
            "formula": f"DiscPayback({init}, {cfs}, {rate})",
        })
        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}
