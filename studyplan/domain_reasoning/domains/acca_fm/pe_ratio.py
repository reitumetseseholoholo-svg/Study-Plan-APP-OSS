"""P/E ratio concept template."""

from __future__ import annotations

import math
from typing import Any

from studyplan.numerical_solver import solve_pe_ratio
from studyplan.domain_reasoning.templates import FormulaTemplate


class PeRatioTemplate(FormulaTemplate):
    def __init__(self) -> None:
        super().__init__("fm.pe_ratio", solve_pe_ratio, version="1.0.0")

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        p = float(inputs.get("market_price", 0))
        e = float(inputs.get("eps", 1))
        result = self._solver(p, e)

        steps: list[dict[str, Any]] = [
            {"step_id": "pe_ratio", "description": "P/E = Market price / EPS", "value": result, "formula": f"{p}/{e}"},
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
            if sid == "pe_ratio":
                sv = step.get("value")
                if sv is not None:
                    truth_val = truth.get("result")
                    if truth_val is not None and float(sv) != float(truth_val):
                        tags.append("eps_error" if float(sv) < float(truth_val) else "price_error")
        return tags
