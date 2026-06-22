"""Executable template protocol and registry.

Each template wraps a deterministic solver function with concept
metadata, input schema, and diagnostic classification.
"""

from __future__ import annotations

import math
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ConceptTemplate(Protocol):
    """Interface for a deterministic concept template.

    Implementations wrap a solver function with input/output schemas
    and error classification.
    """
    concept_id: str
    template_version: str

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Compute the authoritative reference solution."""
        ...

    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Compare learner intermediate steps against truth."""
        ...

    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]:
        """Return diagnostic error tags based on step comparison."""
        ...


# ---------------------------------------------------------------------------
# Concrete: FormulaTemplate — wraps a bare solver function
# ---------------------------------------------------------------------------

class FormulaTemplate:
    """Adapter that wraps a numerical solver function as a ConceptTemplate.

    Provides minimal ``solve()``, default ``evaluate_steps()`` (by comparing
    final answer), and heuristics for ``classify_errors()``.
    """

    def __init__(
        self,
        concept_id: str,
        solver_fn: Any,
        version: str = "1.0.0",
        input_schema: dict[str, tuple[type, str]] | None = None,
    ) -> None:
        self.concept_id = concept_id
        self.template_version = version
        self._solver = solver_fn
        self._input_schema = input_schema or {}

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        result = self._solver(**inputs)
        return {
            "concept_id": self.concept_id,
            "result": result,
            "inputs": dict(inputs),
            "is_nan": isinstance(result, float) and math.isnan(result),
        }

    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not learner_steps or not truth:
            return []
        truth_result = truth.get("result")
        results: list[dict[str, Any]] = []
        for step in learner_steps:
            step_val = step.get("value")
            if step_val is not None and truth_result is not None:
                match = abs(float(step_val) - float(truth_result)) < max(0.01, abs(float(truth_result)) * 0.005)
            else:
                match = False
            results.append({
                "step_id": step.get("step_id", ""),
                "expected": truth_result,
                "actual": step_val,
                "match": match,
            })
        return results

    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]:
        tags: list[str] = []
        if not learner_steps or not truth:
            return tags
        truth_result = truth.get("result")
        if truth_result is None or (isinstance(truth_result, float) and math.isnan(truth_result)):
            return tags
        for step in learner_steps:
            step_val = step.get("value")
            step_id = step.get("step_id", "")
            if step_id and step_val is not None:
                try:
                    diff = abs(float(step_val) - float(truth_result))
                    if diff > max(0.01, abs(float(truth_result)) * 0.005):
                        tags.append(f"{step_id}_mismatch")
                except (ValueError, TypeError):
                    tags.append(f"{step_id}_parse_error")
        return tags


# ---------------------------------------------------------------------------
# Registry: concept_id → template instance
# ---------------------------------------------------------------------------

def _build_registry() -> dict[str, ConceptTemplate]:
    """Build the template registry.

    Uses domain-specific step-aware templates where available,
    falling back to generic FormulaTemplate wrappers.
    """
    from studyplan.domain_reasoning.domains.acca_fm.npv import NpvTemplate
    from studyplan.domain_reasoning.domains.acca_fm.wacc import WaccTemplate
    from studyplan.domain_reasoning.domains.acca_fm.capm import CapmTemplate
    from studyplan.domain_reasoning.domains.acca_fm.ccc import CccTemplate
    from studyplan.domain_reasoning.domains.acca_fm.irr import IrrTemplate
    from studyplan.domain_reasoning.domains.acca_fm.payback import PaybackTemplate, DiscountedPaybackTemplate
    from studyplan.domain_reasoning.domains.acca_fm.gearing import GearingTemplate, InterestCoverTemplate, EpsTemplate, DividendYieldTemplate, DividendCoverTemplate
    from studyplan.domain_reasoning.domains.acca_fm.eoq import EoqTemplate
    from studyplan.domain_reasoning.domains.acca_fm.arr import ArrTemplate
    from studyplan.domain_reasoning.domains.acca_fm.cost_of_debt import CostOfDebtTemplate
    from studyplan.domain_reasoning.domains.acca_fm.cost_of_equity_dvm import CostOfEquityDvmTemplate
    from studyplan.domain_reasoning.domains.acca_fm.equivalent_annual_cost import EquivalentAnnualCostTemplate
    from studyplan.domain_reasoning.domains.acca_fm.profitability_index import ProfitabilityIndexTemplate
    from studyplan.domain_reasoning.domains.acca_fm.asset_beta import AssetBetaTemplate
    from studyplan.domain_reasoning.domains.acca_fm.equity_beta import EquityBetaTemplate
    from studyplan.domain_reasoning.domains.acca_fm.pe_ratio import PeRatioTemplate
    from studyplan.domain_reasoning.domains.acca_fm.roe import RoeTemplate
    from studyplan.domain_reasoning.domains.acca_fm.cost_of_preference import CostOfPreferenceTemplate
    from studyplan.domain_reasoning.domains.acca_fm.terp import TerpTemplate
    from studyplan.domain_reasoning.domains.acca_fm.perpetuity_npv import PerpetuityNpvTemplate
    from studyplan.domain_reasoning.domains.acca_fm.roce import RoceTemplate

    return {
        "fm.npv": NpvTemplate(),
        "fm.wacc": WaccTemplate(),
        "fm.capm": CapmTemplate(),
        "fm.payback": PaybackTemplate(),
        "fm.discounted_payback": DiscountedPaybackTemplate(),
        "fm.ccc": CccTemplate(),
        "fm.cost_of_debt": CostOfDebtTemplate(),
        "fm.cost_of_equity_dvm": CostOfEquityDvmTemplate(),
        "fm.irr": IrrTemplate(),
        "fm.arr": ArrTemplate(),
        "fm.eoq": EoqTemplate(),
        "fm.equivalent_annual_cost": EquivalentAnnualCostTemplate(),
        "fm.profitability_index": ProfitabilityIndexTemplate(),
        "fm.gearing": GearingTemplate(),
        "fm.interest_cover": InterestCoverTemplate(),
        "fm.eps": EpsTemplate(),
        "fm.dividend_yield": DividendYieldTemplate(),
        "fm.dividend_cover": DividendCoverTemplate(),
        "fm.asset_beta": AssetBetaTemplate(),
        "fm.equity_beta": EquityBetaTemplate(),
        "fm.pe_ratio": PeRatioTemplate(),
        "fm.roe": RoeTemplate(),
        "fm.cost_of_preference": CostOfPreferenceTemplate(),
        "fm.terp": TerpTemplate(),
        "fm.perpetuity_npv": PerpetuityNpvTemplate(),
        "fm.roce": RoceTemplate(),
    }


TEMPLATE_REGISTRY: dict[str, ConceptTemplate] = _build_registry()

# Merge in auto-generated templates from formula registry
from studyplan.domain_reasoning.formula_registry import build_template_registry
TEMPLATE_REGISTRY = build_template_registry(TEMPLATE_REGISTRY)


def run_template(
    concept_id: str,
    inputs: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute a template by concept ID.

    Returns the solve result dict, or ``None`` if the concept is unknown.
    """
    template = TEMPLATE_REGISTRY.get(concept_id)
    if template is None:
        return None
    return template.solve(inputs)
