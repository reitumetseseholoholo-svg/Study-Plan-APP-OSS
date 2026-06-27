"""Asset beta (ungearing) concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_asset_beta
from studyplan.domain_reasoning.templates import FormulaTemplate


class AssetBetaTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.asset_beta", solve_asset_beta, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        be = float(inputs.get("equity_beta", 1))
        vd = float(inputs.get("market_value_debt", 0))
        ve = float(inputs.get("market_value_equity", 1))
        t = float(inputs.get("tax_rate", 0))
        result = self._solver(be, vd, ve, t)

        v = ve + vd * (1.0 - t)
        w = ve / v
        steps: list[dict[str, Any]] = [
            {
                "step_id": "debt_after_tax",
                "description": "Vd × (1-T)",
                "value": vd * (1.0 - t),
                "formula": f"{vd}*(1-{t})",
            },
            {"step_id": "firm_value", "description": "Ve + Vd×(1-T)", "value": v, "formula": f"{ve}+{vd}*(1-{t})"},
            {"step_id": "equity_weight", "description": "Ve / (Ve + Vd×(1-T))", "value": w, "formula": f"{ve}/{v}"},
            {"step_id": "asset_beta", "description": "βa = βe × weight", "value": result, "formula": f"{be}*{w}"},
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
            if sid == "debt_after_tax":
                sv = step.get("value")
                if sv is not None:
                    truth_steps = truth.get("steps", [])
                    ts = next((s for s in truth_steps if s["step_id"] == sid), None)
                    if ts and abs(float(sv) - float(ts["value"])) > 0.01:
                        tags.append("tax_error")
            if sid == "equity_weight":
                sv = step.get("value")
                if sv is not None and not (0 <= float(sv) <= 1):
                    tags.append("weight_error")
        return tags
