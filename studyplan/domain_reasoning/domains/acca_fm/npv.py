"""NPV concept template — first end-to-end deterministic domain slice."""

from __future__ import annotations

import math
import re
from typing import Any

from studyplan.numerical_solver import solve_npv
from studyplan.domain_reasoning.templates import FormulaTemplate


class NpvTemplate(FormulaTemplate):
    """NPV template with step-aware error classification."""

    def __init__(self) -> None:
        super().__init__("fm.npv", solve_npv, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        cashflows = list(inputs.get("cashflows", []))
        rate = float(inputs.get("rate", 0.0))
        initial = float(inputs.get("initial", 0.0))
        result = self._solver(cashflows, rate, initial)
        steps: list[dict[str, Any]] = []
        for t, cf in enumerate(cashflows, 1):
            pv = cf / ((1.0 + rate) ** t)
            steps.append({
                "step_id": f"pv_year_{t}",
                "description": f"PV of year {t} cashflow",
                "value": pv,
                "formula": f"{cf} / (1 + {rate})^{t}",
            })
        total_pv = sum(s["value"] for s in steps)
        steps.append({
            "step_id": "total_pv",
            "description": "Sum of discounted cashflows",
            "value": total_pv,
            "formula": f"sum of {len(cashflows)} PVs",
        })
        steps.append({
            "step_id": "npv",
            "description": "NPV = total PV - initial investment",
            "value": result,
            "formula": f"{total_pv} - {initial}",
        })
        return {
            "concept_id": self.concept_id,
            "result": result,
            "steps": steps,
            "inputs": dict(inputs),
            "is_nan": isinstance(result, float) and math.isnan(result),
        }

    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        truth_val = truth.get("result")
        if truth_val is None or (isinstance(truth_val, float) and math.isnan(truth_val)):
            return tags
        truth_float = float(truth_val)
        for step in learner_steps or []:
            step_val = step.get("value")
            step_id = step.get("step_id", "")
            if re.match(r"pv_year_\d+", step_id):
                s_val = step.get("sign", 1)
                truth_sign = 1 if truth_float >= 0 else -1
                if s_val != truth_sign:
                    tags.append("sign_error")
            if "rate" in step_id or "discount" in step_id:
                if step_val is not None:
                    try:
                        sv = float(step_val)
                        tv = truth_float
                        if abs(sv - tv) > max(0.01, abs(tv) * 0.05):
                            tags.append("wrong_discount_rate")
                    except (ValueError, TypeError):
                        pass
        return tags
