"""WACC concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_wacc
from studyplan.domain_reasoning.templates import FormulaTemplate


class WaccTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.wacc", solve_wacc, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        eq = float(inputs.get("equity", 0))
        db = float(inputs.get("debt", 0))
        re = float(inputs.get("cost_equity", 0))
        rd = float(inputs.get("cost_debt", 0))
        tax = float(inputs.get("tax_rate", 0))
        v = eq + db
        result = self._solver(eq, db, re, rd, tax)

        steps: list[dict[str, Any]] = []
        if v > 0:
            w_e = eq / v
            w_d = db / v
            steps.append({"step_id": "weight_equity", "description": "Equity weight", "value": w_e, "formula": f"{eq}/{v}"})
            steps.append({"step_id": "weight_debt", "description": "Debt weight", "value": w_d, "formula": f"{db}/{v}"})
            steps.append({"step_id": "cost_equity_component", "description": "Equity component", "value": w_e * re, "formula": f"{w_e}*{re}"})
            rd_after_tax = rd * (1 - tax)
            steps.append({"step_id": "cost_debt_after_tax", "description": "Debt cost after tax", "value": rd_after_tax, "formula": f"{rd}*(1-{tax})"})
            steps.append({"step_id": "cost_debt_component", "description": "Debt component", "value": w_d * rd_after_tax, "formula": f"{w_d}*{rd_after_tax}"})
        steps.append({"step_id": "wacc", "description": "WACC", "value": result, "formula": f"{w_e if v>0 else 0}*{re}+{w_d if v>0 else 0}*{rd}*(1-{tax})"})

        return {"concept_id": self.concept_id, "result": result, "steps": steps, "inputs": dict(inputs), "is_nan": isinstance(result, float) and math.isnan(result)}

    def classify_errors(self, learner_steps: list[dict[str, Any]], truth: dict[str, Any]) -> list[str]:
        tags: list[str] = super().classify_errors(learner_steps, truth)
        if not truth:
            return tags
        for step in learner_steps or []:
            sid = str(step.get("step_id", ""))
            if "weight" in sid and "equity" in sid:
                sv = step.get("value")
                if sv is not None and not (0 <= float(sv) <= 1):
                    tags.append("wrong_weighting")
            if "tax" in sid or "debt_after" in sid:
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.01:
                        tags.append("omit_tax_shield")
        return tags
