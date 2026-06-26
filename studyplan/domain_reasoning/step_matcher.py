"""Step-by-step learner working comparison.

Parses learner free-text workings to extract labeled intermediate values,
then matches them against truth steps from the deterministic solver.

Typical usage::

    from studyplan.domain_reasoning.step_matcher import (
        parse_learner_workings,
        match_learner_steps,
    )

    learner_steps = parse_learner_workings(
        "WACC = 5% + 1.2*(10%-5%) = 11%\\nPV yr 1 = 1000/1.1 = 909.09"
    )
    truth = template.solve(inputs)
    matches = match_learner_steps(truth.get("steps", []), learner_steps)
    # matches[i] = {"step_id": ..., "expected": ..., "actual": ..., "match": bool, "confidence": float}
"""

from __future__ import annotations

import math
import re
from typing import Any

_STEP_TOLERANCE = 0.02  # 2% relative tolerance for step value comparison
_LABEL_SIMILARITY_MIN = 0.15  # minimum similarity score to consider a match


def parse_learner_workings(text: str) -> list[dict[str, Any]]:
    """Extract labeled numeric values from learner free-text workings.

    Handles common Section C answer formats::

        "WACC = 5% + 1.2 x 5% = 11%"
        "PV of Year 1 = 1,000 / 1.1 = 909.09"
        "Cost of equity: 11.2%"
        "g = 5%  (a) WACC = 11%"

    Returns a list of dicts, each with keys:
        ``step_id`` (normalized label),
        ``value`` (float),
        ``raw_label`` (original label text).

    The list preserves the order in which values appear in the text.
    """
    if not text or not text.strip():
        return []

    results: list[dict[str, Any]] = []
    seen_values: set[float] = set()

    # Split into lines and also try to split on (a), (b), (c) markers
    lines = re.split(r"\n+|(?=\s*\([a-zA-Z]\)\s*)", text)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        _extract_from_line(line, results, seen_values)

    return results


def _extract_from_line(
    line: str,
    results: list[dict[str, Any]],
    seen_values: set[float],
) -> None:
    """Try multiple extraction strategies on a single line."""

    # Strategy 1: "label = expression = value"
    m = re.search(
        r"([A-Za-z][A-Za-z0-9_\s\-/\u00b2\u00b3\u2070-\u2079\u2080-\u2089()]+?)\s*=\s*.+?=\s*(?:[$£\u00a3\u20ac])?\s*([+-]?\d[\d,.]*(?:\.\d+)?)",
        line,
        re.IGNORECASE,
    )
    if m:
        label = m.group(1).strip()
        value = _parse_number(m.group(2))
        if value is not None and _is_novel_value(value, seen_values):
            seen_values.add(value)
            results.append(
                {
                    "step_id": _normalize_label(label),
                    "value": round(value, 6),
                    "raw_label": label,
                }
            )
            return

    # Strategy 2: "label = value"  or  "label: value"
    m = re.search(
        r"([A-Za-z][A-Za-z0-9_\s\-/\u00b2\u00b3\u2070-\u2079\u2080-\u2089()]{1,60}?)\s*[:=]\s*(?:[$£\u00a3\u20ac])?\s*([+-]?\d[\d,.]*(?:\.\d+)?)",
        line,
        re.IGNORECASE,
    )
    if m:
        label = m.group(1).strip()
        value = _parse_number(m.group(2))
        if value is not None and _is_novel_value(value, seen_values):
            if _is_calc_result(value, label):
                seen_values.add(value)
                results.append(
                    {
                        "step_id": _normalize_label(label),
                        "value": round(value, 6),
                        "raw_label": label,
                    }
                )
                return

    # Strategy 3: inline "(a) value" or "(a) label value"
    m = re.search(
        r"\(([a-zA-Z])\)\s*([A-Za-z].+?)?\s*(?:[$£\u00a3\u20ac])?\s*([+-]?\d[\d,.]*(?:\.\d+)?)",
        line,
        re.IGNORECASE,
    )
    if m:
        part = m.group(1).lower()
        extra_label = m.group(2)
        value = _parse_number(m.group(3))
        if value is not None and _is_novel_value(value, seen_values):
            if _is_calc_result(value, line):
                label = f"part_{part}"
                if extra_label:
                    label = _normalize_label(extra_label)
                seen_values.add(value)
                results.append(
                    {
                        "step_id": label,
                        "value": round(value, 6),
                        "raw_label": f"({part}) {extra_label or ''}".strip(),
                    }
                )


def _parse_number(s: str) -> float | None:
    """Parse a number from a string, handling common notation."""
    s = s.strip()
    # Remove currency symbols and percentage signs
    s = s.replace(",", "").replace("%", "").replace("$", "").replace("\u00a3", "").replace("\u20ac", "")
    # Handle "1,000.50" → "1000.50"
    s = s.replace(",", ".")
    # If there are multiple dots, keep only the last one
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _is_novel_value(value: float, seen: set[float]) -> bool:
    """Check if a value is meaningfully different from already-seen values."""
    for existing in seen:
        if abs(value - existing) < 0.001:
            return False
    return True


def _is_calc_result(value: float, context: str) -> bool:
    """Heuristic: exclude small integers that look like ordinals or years."""
    if 0 <= value <= 10 and value == int(value):
        # Check if it's just a year number or small label
        if re.search(rf"\b{int(value)}\b", context, re.IGNORECASE):
            return False
    return True


def _normalize_label(label: str) -> str:
    """Normalize a human-written label to a step_id-like form.

    Handles common variations::

        "PV of Year 1"  → "pv_year_1"
        "PV yr 1"       → "pv_yr_1"
        "Total PV"      → "total_pv"
        "Cost of equity" → "cost_equity"
    """
    label = label.strip().lower()

    replacements = [
        ("net present value", "npv"),
        ("of year", "yr"),
        ("for year", "yr"),
        ("year", "yr"),
        ("present value", "pv"),
        ("cost of equity", "cost_equity"),
        ("cost of debt", "cost_debt"),
        ("weight of equity", "weight_equity"),
        ("weight of debt", "weight_debt"),
        ("equity weight", "eq_weight"),
        ("debt weight", "debt_weight"),
        ("total pv", "total_pv"),
        ("total present value", "total_pv"),
        ("capital employed", "capital_employed"),
        ("interest cover", "interest_cover"),
        ("dividend yield", "dividend_yield"),
        ("dividend cover", "dividend_cover"),
        ("price earnings", "pe_ratio"),
        ("profitability index", "profitability_index"),
        ("equivalent annual cost", "equivalent_annual_cost"),
        ("discounted payback", "discounted_payback"),
        ("asset beta", "asset_beta"),
        ("equity beta", "equity_beta"),
        ("perpetuity npv", "perpetuity_npv"),
        ("cost of preference", "cost_of_preference"),
        ("earning yield", "earning_yield"),
        ("asset turnover", "asset_turnover"),
        ("quick ratio", "quick_ratio"),
        ("dividend growth", "dividend_growth_rate"),
        ("inventory holding", "inventory_days"),
        ("inventory days", "inventory_days"),
        ("receivable collection", "receivables_days"),
        ("receivable days", "receivables_days"),
        ("payable payment", "payables_days"),
        ("payable days", "payables_days"),
    ]

    for orig, repl in replacements:
        if orig in label:
            label = label.replace(orig, repl)

    # Replace remaining non-alphanum (except underscore) with _
    label = re.sub(r"[^a-z0-9_]", "_", label).strip("_")
    # Collapse multiple underscores
    while "__" in label:
        label = label.replace("__", "_")
    return label or "unknown"


def _label_similarity(a: str, b: str) -> float:
    """Compute word-overlap similarity between two label strings (0-1)."""
    a_norm = a.lower().replace("_", " ").replace("-", " ")
    b_norm = b.lower().replace("_", " ").replace("-", " ")
    if a_norm == b_norm:
        return 1.0
    a_words = set(a_norm.split())
    b_words = set(b_norm.split())
    if not a_words or not b_words:
        return 0.0
    intersection = a_words & b_words
    union = a_words | b_words
    return len(intersection) / len(union)


def _values_match(expected: float, actual: float, tolerance: float | None = None) -> bool:
    """Check if two numeric values match within tolerance."""
    if math.isnan(expected) or math.isnan(actual):
        return False
    tol = _STEP_TOLERANCE if tolerance is None else tolerance
    abs_tol = max(0.01, abs(expected) * tol)
    return abs(expected - actual) <= abs_tol


def match_learner_steps(
    truth_steps: list[dict[str, Any]],
    learner_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match learner-extracted steps against truth steps.

    For each truth step, finds the best-matching learner step using
    label similarity and value proximity.

    Returns a list of match dicts (one per truth step) with keys:
        ``step_id``, ``description``, ``expected``, ``actual``,
        ``match`` (bool), ``confidence`` (float 0-1).
    """
    matches: list[dict[str, Any]] = []
    used_learner_indices: set[int] = set()

    for truth in truth_steps:
        t_id = str(truth.get("step_id", "") or "")
        t_desc = str(truth.get("description", "") or "")
        t_value = truth.get("value")
        if t_value is None:
            matches.append(
                {
                    "step_id": t_id,
                    "description": t_desc,
                    "expected": None,
                    "actual": None,
                    "match": False,
                    "confidence": 0.0,
                }
            )
            continue

        t_value = float(t_value)
        best_actual: float | None = None
        best_score = 0.0
        best_l_idx = -1

        for l_idx, learner in enumerate(learner_steps):
            if l_idx in used_learner_indices:
                continue
            l_value = learner.get("value")
            if l_value is None:
                continue
            l_value = float(l_value)
            l_id = str(learner.get("step_id", "") or "")

            sim = _label_similarity(t_id, l_id)
            exact_match = _values_match(t_value, l_value)

            # Boost score for numerical match
            score = sim
            if exact_match:
                score = max(score, 0.7)
            elif sim > 0 and _values_match(t_value, l_value, tolerance=0.05):
                score = max(score, sim + 0.2)

            if score > best_score:
                best_score = score
                best_actual = l_value
                best_l_idx = l_idx

        if best_score >= _LABEL_SIMILARITY_MIN and best_actual is not None:
            used_learner_indices.add(best_l_idx)
            matches.append(
                {
                    "step_id": t_id,
                    "description": t_desc,
                    "expected": t_value,
                    "actual": best_actual,
                    "match": _values_match(t_value, best_actual),
                    "confidence": min(1.0, best_score),
                }
            )
        else:
            matches.append(
                {
                    "step_id": t_id,
                    "description": t_desc,
                    "expected": t_value,
                    "actual": None,
                    "match": False,
                    "confidence": 0.0,
                }
            )

    return matches


def compute_step_error_tags(
    step_matches: list[dict[str, Any]],
) -> list[str]:
    """Generate error tags from step match results.

    Returns tags like ``step_pv_year_1_mismatch`` for each
    step where the learner value does not match.
    """
    tags: list[str] = []
    for m in step_matches:
        step_id = str(m.get("step_id", "") or "")
        if not step_id:
            continue
        if not m.get("match", False):
            tags.append(f"step_{step_id}_mismatch")
    return tags
