"""Lookup concept — table-based value retrieval.

A lookup concept maps category names or conditions to values from a
predefined table.  Examples: VAT rates by goods type, tax allowances
by year, standard deduction tables.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LookupRule:
    """A rule that maps a condition to a table key.

    When *condition* evaluates to True (against the input context),
    the *output_key* is used to look up a value from the table.
    """
    condition: str
    output_key: str


@dataclass
class LookupConfig:
    """Configuration for a ``lookup`` type concept.

    ``table`` maps category/classification keys to their values.
    ``rules`` are evaluated in order; the first matching rule determines
    the key used for the lookup.  If no rule matches, *default key* or
    ``None`` is returned.
    """
    table: dict[str, Any]
    rules: list[LookupRule]
    default_key: str | None = None
    output_slot: str = "lookup_result"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

class LookupTemplate:
    """ConceptTemplate implementation for table-based lookups.

    Given an input context, evaluates ``rules`` in order.  The first
    matching rule's ``output_key`` is used to index into ``table``.
    """

    concept_id: str
    template_version: str

    def __init__(
        self,
        concept_id: str,
        config: LookupConfig,
        version: str = "1.0.0",
    ) -> None:
        self.concept_id = concept_id
        self.template_version = version
        self._table = config.table
        self._rules = config.rules
        self._default_key = config.default_key
        self._output_slot = config.output_slot

    # ------------------------------------------------------------------
    # Public API (ConceptTemplate protocol)
    # ------------------------------------------------------------------

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ctx: dict[str, float] = {}
        for k, v in inputs.items():
            if isinstance(v, (int, float)):
                ctx[str(k)] = float(v)

        matched_key: str | None = None
        matched_condition: str = "none"

        for rule in self._rules:
            from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression
            try:
                cond_val = _eval_rule_expression(rule.condition, ctx)
                if bool(cond_val):
                    matched_key = rule.output_key
                    matched_condition = rule.condition
                    break
            except (ValueError, NameError):
                continue

        if matched_key is None:
            matched_key = self._default_key

        value: Any = None
        if matched_key and matched_key in self._table:
            value = self._table[matched_key]

        is_nan = value is None
        return {
            "concept_id": self.concept_id,
            "result": value,
            "inputs": dict(inputs),
            "is_nan": is_nan,
            "steps": [{
                "step_id": self._output_slot,
                "description": f"Lookup: {matched_key or 'none'}",
                "value": value,
                "matched_condition": matched_condition,
            }],
            "lookup_key": matched_key,
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
                match = step_val == truth_result
            else:
                match = (step_val is None and truth_result is None)
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
        truth_key = truth.get("lookup_key")
        for step in learner_steps:
            step_val = step.get("value")
            if step_val != truth_result:
                if truth_key:
                    tags.append(f"wrong_category_{truth_key}")
                else:
                    tags.append("lookup_mismatch")
        return tags


# ---------------------------------------------------------------------------
# Candidate extractor
# ---------------------------------------------------------------------------

def _make_lookup_candidate_fn(
    config: LookupConfig,
) -> Callable[..., list[dict[str, Any]]]:
    """Build a candidate function for lookup concepts.

    Lookup candidates just enumerate the table keys as possible
    classification targets, since the inputs are typically category
    descriptors, not numbers.
    """
    def candidate_fn(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for key, val in config.table.items():
            candidates.append({"lookup_key": key, "value": val})
        return candidates[:5]

    return candidate_fn


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_lookup_template(
    concept_id: str,
    config: LookupConfig,
) -> LookupTemplate:
    """Factory: build a ``LookupTemplate`` from configuration."""
    return LookupTemplate(
        concept_id=concept_id,
        config=config,
    )
