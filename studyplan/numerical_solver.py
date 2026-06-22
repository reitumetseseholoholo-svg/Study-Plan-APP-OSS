"""Deterministic numerical verification for finance MCQs.

Pure functions, zero app dependencies.
Three layers: formula solvers → input extraction → answer verification.
Layer 2.5: freeform expression extraction from explanation text.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any

__all__ = [
    "solve_npv", "solve_wacc", "solve_capm",
    "solve_payback_period", "solve_discounted_payback",
    "solve_cash_conversion_cycle", "solve_cost_of_debt",
    "solve_irr", "solve_arr", "solve_eoq",
    "solve_equivalent_annual_cost", "solve_profitability_index",
    "solve_gearing", "solve_interest_cover", "solve_eps",
    "solve_dividend_yield", "solve_dividend_cover",
    "solve_cost_of_equity_dvm", "solve_asset_beta", "solve_equity_beta",
    "solve_pe_ratio", "solve_roe", "solve_cost_of_preference",
    "solve_terp", "solve_perpetuity_npv", "solve_roce",
    "safe_expression_evaluate", "extract_expressions", "freeform_verify",
    "verify_numerical_answer",
]

# ---------------------------------------------------------------------------
# Layer 1 — Pure formula solvers
# ---------------------------------------------------------------------------

def solve_npv(cashflows: list[float], rate: float, initial: float = 0.0) -> float:
    if rate <= -1 or not cashflows:
        return float("nan")
    pv = sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cashflows, 1))
    return pv - initial


def solve_wacc(equity: float, debt: float, cost_equity: float,
               cost_debt: float, tax_rate: float = 0.0) -> float:
    """Weighted average cost of capital.

    ``cost_debt`` is already after-tax (consistent with cost_of_debt output).
    ``tax_rate`` is accepted for backward compatibility but not used —
    the tax shield is embedded in ``cost_debt``.
    """
    v = equity + debt
    if v <= 0:
        return float("nan")
    return (equity / v) * cost_equity + (debt / v) * cost_debt


def solve_capm(risk_free: float, beta: float, market_return: float) -> float:
    return risk_free + beta * (market_return - risk_free)


def solve_payback_period(initial: float, cashflows: list[float]) -> float:
    cumulative = 0.0
    for t, cf in enumerate(cashflows, 1):
        cumulative += cf
        if cumulative >= initial:
            remaining = cumulative - initial
            return float(t - 1) + (cf - remaining) / cf if cf > 0 else float(t)
    return float("nan")


def solve_discounted_payback(initial: float, cashflows: list[float],
                             rate: float) -> float:
    cumulative = 0.0
    for t, cf in enumerate(cashflows, 1):
        pv = cf / ((1.0 + rate) ** t)
        cumulative += pv
        if cumulative >= initial:
            remaining = cumulative - initial
            return float(t - 1) + (pv - remaining) / pv if pv > 0 else float(t)
    return float("nan")


def solve_cash_conversion_cycle(dio: float, dso: float, dpo: float) -> float:
    return dio + dso - dpo


def solve_cost_of_debt(interest_rate: float, tax_rate: float) -> float:
    return interest_rate * (1.0 - tax_rate)


def solve_cost_of_equity_dvm(dividend: float, price: float,
                             growth: float = 0.0) -> float:
    if price <= 0:
        return float("nan")
    return (dividend * (1.0 + growth)) / price + growth


def solve_irr(cashflows: list[float], initial: float,
              guess: float = 0.1) -> float:
    """Internal Rate of Return via Newton-Raphson."""
    if not cashflows or initial <= 0:
        return float("nan")
    rate = guess
    for _ in range(200):
        npv = -initial + sum(cf / ((1.0 + rate) ** t)
                             for t, cf in enumerate(cashflows, 1))
        dnpv = sum(-t * cf / ((1.0 + rate) ** (t + 1))
                   for t, cf in enumerate(cashflows, 1))
        if abs(dnpv) < 1e-15:
            break
        rate_next = rate - npv / dnpv
        if abs(rate_next - rate) < 1e-10:
            return rate_next
        rate = rate_next
        if rate <= -1:
            return float("nan")
    return float("nan")


def solve_arr(average_profit: float, initial_investment: float,
              residual_value: float = 0.0) -> float:
    """Accounting Rate of Return (ROCE)."""
    avg_investment = (initial_investment + residual_value) / 2.0
    if avg_investment <= 0:
        return float("nan")
    return average_profit / avg_investment


def solve_eoq(annual_demand: float, ordering_cost: float,
              holding_cost_per_unit: float) -> float:
    """Economic Order Quantity."""
    if annual_demand <= 0 or ordering_cost <= 0 or holding_cost_per_unit <= 0:
        return float("nan")
    return math.sqrt(2.0 * annual_demand * ordering_cost / holding_cost_per_unit)


def solve_equivalent_annual_cost(cost: float, discount_rate: float,
                                 years: int) -> float:
    """EAC = cost / ((1 - (1+r)^-n) / r)."""
    if years <= 0 or discount_rate <= -1 or cost <= 0:
        return float("nan")
    if abs(discount_rate) < 1e-15:
        return cost / float(years)
    pvifa = (1.0 - (1.0 + discount_rate) ** (-years)) / discount_rate
    if pvifa <= 0:
        return float("nan")
    return cost / pvifa


def solve_profitability_index(pv_future_cashflows: float,
                              initial_investment: float) -> float:
    if initial_investment <= 0:
        return float("nan")
    return pv_future_cashflows / initial_investment


def solve_gearing(debt: float, equity: float) -> float:
    """Gearing = Debt / (Debt + Equity)."""
    v = debt + equity
    if v <= 0:
        return float("nan")
    return debt / v


def solve_interest_cover(pbit: float, interest_expense: float) -> float:
    if interest_expense <= 0:
        return float("nan")
    return pbit / interest_expense


def solve_eps(profit_after_tax: float, number_of_shares: float) -> float:
    if number_of_shares <= 0:
        return float("nan")
    return profit_after_tax / number_of_shares


def solve_dividend_yield(dividend_per_share: float, market_price: float) -> float:
    if market_price <= 0:
        return float("nan")
    return dividend_per_share / market_price


def solve_dividend_cover(eps: float, dividend_per_share: float) -> float:
    if dividend_per_share <= 0:
        return float("nan")
    return eps / dividend_per_share


def solve_asset_beta(equity_beta: float, market_value_debt: float,
                     market_value_equity: float, tax_rate: float = 0.0) -> float:
    """Ungear equity beta to asset beta."""
    v = market_value_equity + market_value_debt * (1.0 - tax_rate)
    if v <= 0:
        return float("nan")
    return equity_beta * (market_value_equity / v)


def solve_equity_beta(asset_beta: float, market_value_debt: float,
                      market_value_equity: float, tax_rate: float = 0.0) -> float:
    """Regear asset beta to equity beta."""
    if market_value_equity <= 0:
        return float("nan")
    v = market_value_equity + market_value_debt * (1.0 - tax_rate)
    return asset_beta * (v / market_value_equity)


def solve_pe_ratio(market_price: float, eps: float) -> float:
    """Price / Earnings ratio."""
    if eps <= 0:
        return float("nan")
    return market_price / eps


def solve_roe(profit_after_tax: float, equity: float) -> float:
    """Return on equity."""
    if equity <= 0:
        return float("nan")
    return profit_after_tax / equity


def solve_cost_of_preference(preference_dividend: float,
                             market_price: float) -> float:
    """Kp = Preference dividend / Market price."""
    if market_price <= 0:
        return float("nan")
    return preference_dividend / market_price


def solve_terp(cum_rights_price: float, issue_price: float,
               rights_ratio_n: float) -> float:
    """Theoretical ex-rights price.

    TERP = (N * cum_rights_price + issue_price) / (N + 1)
    where N = number of existing shares per new share issued.
    """
    if rights_ratio_n <= 0:
        return float("nan")
    return (rights_ratio_n * cum_rights_price + issue_price) / (rights_ratio_n + 1.0)


def solve_perpetuity_npv(annual_cashflow: float, discount_rate: float) -> float:
    """PV of a perpetuity."""
    if discount_rate <= 0:
        return float("nan")
    return annual_cashflow / discount_rate


def solve_roce(pbit: float, capital_employed: float) -> float:
    """Return on capital employed (ROCE)."""
    if capital_employed <= 0:
        return float("nan")
    return pbit / capital_employed


# ---------------------------------------------------------------------------
# Layer 2 — Number extraction from natural-language question text
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(
    r"-?\(?"
    r"[\$\u00a3\u20ac]?"
    r"[\d,]+(?:\.\d+)?"
    r"%?"
    r"\)?"
)

_YEAR_WORDS = re.compile(r"\b(year|yr|period)\b", re.IGNORECASE)


def extract_numbers(text: str) -> list[dict[str, Any]]:
    raw = str(text or "")
    if not raw:
        return []
    results: list[dict[str, Any]] = []
    for match in _NUM_RE.finditer(raw):
        token = match.group(0)
        is_percent = "%" in token
        is_currency = bool(re.search(r"[\$\u00a3\u20ac]", token))
        is_bracket_neg = token.startswith("(") and token.endswith(")")
        compact = (
            token.replace(",", "")
            .replace("$", "")
            .replace("\u00a3", "")
            .replace("\u20ac", "")
            .replace("%", "")
            .replace("(", "")
            .replace(")", "")
            .strip()
        )
        if not compact:
            continue
        try:
            value = float(compact)
        except ValueError:
            continue
        if is_bracket_neg and value > 0:
            value = -value
        if is_percent:
            value = value / 100.0
        pre_context = raw[max(0, match.start() - 20):match.start()].lower()
        is_year_like = bool(_YEAR_WORDS.search(pre_context)) and value == int(value) and 0 < value < 30
        results.append({
            "value": value,
            "raw": token,
            "is_percent": is_percent,
            "is_currency": is_currency,
            "is_year_like": is_year_like,
            "is_negative": value < 0,
        })
    results = [r for r in results if not (r["is_year_like"] and not r["is_currency"])]
    return results


# ---------------------------------------------------------------------------
# Formula detection from question text
# ---------------------------------------------------------------------------

_FORMULA_SIGNATURES: list[tuple[str, list[re.Pattern], int]] = [
    ("npv", [re.compile(p, re.IGNORECASE) for p in [
        r"\bNPV\b", r"\bnet present value\b",
        r"\bdiscounted cash flow\b", r"\bDCF\b",
        r"\bpresent value of future\b",
    ]], 1),
    ("wacc", [re.compile(p, re.IGNORECASE) for p in [
        r"\bWACC\b", r"\bweighted average cost\b",
        r"\bcost of capital\b",
    ]], 2),
    ("capm", [re.compile(p, re.IGNORECASE) for p in [
        r"\bCAPM\b", r"\bcost of equity\b",
        r"\brequired rate of return\b",
        r"\bexpected return\b", r"\bequity cost\b",
    ]], 3),
    ("payback", [re.compile(p, re.IGNORECASE) for p in [
        r"\bpayback\b", r"\bpayback period\b",
        r"\brecoup\b", r"\brecover.*investment\b",
    ]], 4),
    ("discounted_payback", [re.compile(p, re.IGNORECASE) for p in [
        r"\bdiscounted payback\b",
    ]], 5),
    ("ccc", [re.compile(p, re.IGNORECASE) for p in [
        r"\bcash conversion cycle\b",
        r"\bworking capital cycle\b",
        r"\bCCC\b", r"\bDIO\b", r"\bDSO\b", r"\bDPO\b",
    ]], 6),
    ("cost_of_debt", [re.compile(p, re.IGNORECASE) for p in [
        r"\bcost of debt\b", r"\bafter.?tax cost\b",
        r"\bdebt cost\b",
    ]], 7),
    ("cost_of_equity_dvm", [re.compile(p, re.IGNORECASE) for p in [
        r"\bdividend (growth|valuation|model)\b",
        r"\bdividend.*price\b", r"\bDVM\b",
        r"\bGordon.*growth\b",
    ]], 8),
    ("irr", [re.compile(p, re.IGNORECASE) for p in [
        r"\bIRR\b", r"\binternal rate of return\b",
        r"\byield\b", r"\bDCF yield\b",
    ]], 9),
    ("arr", [re.compile(p, re.IGNORECASE) for p in [
        r"\bARR\b", r"\baccounting rate of return\b",
        r"\bROCE\b", r"\breturn on capital employed\b",
        r"\baverage.*return\b",
    ]], 10),
    ("eoq", [re.compile(p, re.IGNORECASE) for p in [
        r"\bEOQ\b", r"\beconomic order quantity\b",
        r"\boptimal order\b", r"\breorder quantity\b",
    ]], 11),
    ("equivalent_annual_cost", [re.compile(p, re.IGNORECASE) for p in [
        r"\bequivalent annual (cost|annuity)\b",
        r"\bEAC\b", r"\bannual equivalent\b",
        r"\bequivalent.*annuity\b",
    ]], 12),
    ("profitability_index", [re.compile(p, re.IGNORECASE) for p in [
        r"\bprofitability index\b", r"\bPI\b",
        r"\bprofit.*index\b", r"\bbenefit.*cost\b",
    ]], 13),
    ("gearing", [re.compile(p, re.IGNORECASE) for p in [
        r"\bgearing\b", r"\bleverage\b",
        r"\bdebt.*equity\b", r"\bD/E\b", r"\bcapital structure\b",
    ]], 14),
    ("interest_cover", [re.compile(p, re.IGNORECASE) for p in [
        r"\binterest cover\b", r"\binterest coverage\b",
        r"\btimes interest\b", r"\bcover.*interest\b",
    ]], 15),
    ("eps", [re.compile(p, re.IGNORECASE) for p in [
        r"\bEPS\b", r"\bearnings per share\b",
        r"\bprofit.*share\b",
    ]], 16),
    ("dividend_yield", [re.compile(p, re.IGNORECASE) for p in [
        r"\bdividend yield\b",
    ]], 17),
    ("dividend_cover", [re.compile(p, re.IGNORECASE) for p in [
        r"\bdividend cover\b", r"\bdividend coverage\b",
        r"\bcover.*dividend\b",
    ]], 18),
    ("asset_beta", [re.compile(p, re.IGNORECASE) for p in [
        r"\basset beta\b", r"\bungear\b",
        r"\bungeared\b",
    ]], 19),
    ("equity_beta", [re.compile(p, re.IGNORECASE) for p in [
        r"\bequity beta\b", r"\bregear\b",
        r"\bungeared.*regear\b",
    ]], 20),
    ("pe_ratio", [re.compile(p, re.IGNORECASE) for p in [
        r"\bP/E\b", r"\bprice.*earnings\b", r"\bPE ratio\b",
        r"\bprice.*multiple\b",
    ]], 21),
    ("roe", [re.compile(p, re.IGNORECASE) for p in [
        r"\bROE\b", r"\breturn on equity\b",
        r"\breturn.*shareholder\b",
    ]], 22),
    ("cost_of_preference", [re.compile(p, re.IGNORECASE) for p in [
        r"\bcost of preference\b",
        r"\bpreference.*dividend\b",
        r"\bpreference.*price\b",
        r"\bpref.*share\b",
    ]], 23),
    ("terp", [re.compile(p, re.IGNORECASE) for p in [
        r"\bTERP\b", r"\bex.?rights\b",
        r"\btheoretical.*rights\b", r"\brights issue\b",
        r"\bcum.?rights\b",
    ]], 24),
    ("perpetuity_npv", [re.compile(p, re.IGNORECASE) for p in [
        r"\bperpetuity\b", r"\bperpetual\b",
        r"\binfinite.*cash\b", r"\bconstant.*cash\b",
    ]], 25),
    ("roce", [re.compile(p, re.IGNORECASE) for p in [
        r"\bROCE\b", r"\breturn on capital employed\b",
    ]], 26),
]

_FORMULA_PRIORITY = {name: prio for name, _, prio in _FORMULA_SIGNATURES}


def detect_formulas(question: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for name, patterns, priority in _FORMULA_SIGNATURES:
        for p in patterns:
            if p.search(question):
                found.append((priority, name))
                break
    found.sort()
    return [name for _, name in found]


# ---------------------------------------------------------------------------
# Candidate parameter extraction per formula
# ---------------------------------------------------------------------------

def _candidates_npv(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    values = [n["value"] for n in nums]
    if len(values) < 2:
        return candidates
    pcts = [n["value"] for n in nums if n["is_percent"]]
    cash_candidates = [n["value"] for n in nums if not n["is_percent"]]
    if pcts:
        for rate in pcts:
            if len(cash_candidates) >= 1:
                candidates.append({"cashflows": list(cash_candidates), "rate": rate, "initial": 0.0})
            if len(cash_candidates) >= 2:
                candidates.append({
                    "cashflows": list(cash_candidates[:-1]),
                    "rate": rate,
                    "initial": cash_candidates[-1],
                })
    if not pcts and len(values) >= 3:
        rate = values[-1]
        cashflows = values[:-1]
        if 0 < rate < 1:
            candidates.append({"cashflows": list(cashflows), "rate": rate, "initial": 0.0})
        elif 1 <= rate <= 100:
            candidates.append({"cashflows": list(cashflows), "rate": rate / 100.0, "initial": 0.0})
    return candidates


def _candidates_wacc(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 2 and pcts:
        sorted_vals = sorted(values, reverse=True)
        for eq, db in [(sorted_vals[0], sorted_vals[1]), (sorted_vals[1], sorted_vals[0])]:
            for re_val in pcts:
                for rd_val in pcts:
                    if abs(re_val - rd_val) < 0.001:
                        continue
                    # cost_debt extracted from text is pre-tax; solver expects after-tax
                    candidates.append({
                        "equity": eq, "debt": db,
                        "cost_equity": re_val, "cost_debt": rd_val, "tax_rate": 0.0,
                    })
                    if len(pcts) >= 3:
                        tax = [p for p in pcts if p not in (re_val, rd_val)][0]
                        candidates.append({
                            "equity": eq, "debt": db,
                            "cost_equity": re_val,
                            "cost_debt": rd_val * (1.0 - tax),
                            "tax_rate": tax,
                        })
    return candidates


def _candidates_capm(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    all_vals = values + pcts
    for rf_idx, rf in enumerate(all_vals):
        for b_idx, b in enumerate(all_vals):
            if b_idx == rf_idx:
                continue
            for mr_idx, mr in enumerate(all_vals):
                if mr_idx in (rf_idx, b_idx):
                    continue
                if 0 < b <= 5:
                    candidates.append({
                        "risk_free": rf, "beta": b, "market_return": mr,
                    })
    return candidates


def _candidates_payback(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 2:
        initial = max(values)
        cashflows = [v for v in values if v != initial]
        if cashflows:
            candidates.append({"initial": initial, "cashflows": list(cashflows)})
    return candidates


def _candidates_ccc(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 3:
        return [{"dio": values[0], "dso": values[1], "dpo": values[2]}]
    return []


def _candidates_cost_of_debt(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pcts = [n["value"] for n in nums if n["is_percent"]]
    if len(pcts) >= 1:
        return [{"interest_rate": pcts[0], "tax_rate": pcts[1] if len(pcts) >= 2 else 0.0}]
    return []


def _candidates_cost_of_equity_dvm(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 2:
        div, price = values[0], values[1]
        if pcts:
            for g in pcts:
                candidates.append({"dividend": div, "price": price, "growth": g})
        else:
            candidates.append({"dividend": div, "price": price, "growth": 0.0})
    return candidates


def _candidates_irr(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 2:
        initial = max(values)
        cashflows = [v for v in values if v != initial]
        if cashflows:
            candidates.append({"cashflows": list(cashflows), "initial": initial, "guess": 0.1})
    return candidates


def _candidates_arr(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 2:
        profit = values[0]
        invest = max(values[1:]) if len(values) > 2 else values[1]
        residual = values[-1] if len(values) >= 3 and values[-1] < values[0] else 0.0
        candidates.append({
            "average_profit": profit,
            "initial_investment": invest,
            "residual_value": residual,
        })
    return candidates


def _candidates_eoq(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 3:
        return [{"annual_demand": values[0], "ordering_cost": values[1],
                 "holding_cost_per_unit": values[2]}]
    return []


def _candidates_equivalent_annual_cost(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if values and pcts:
        cost = values[0]
        rate = pcts[0]
        years = int(values[1]) if len(values) >= 2 else 5
        candidates.append({"cost": cost, "discount_rate": rate, "years": years})
    return candidates


def _candidates_profitability_index(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"pv_future_cashflows": max(values), "initial_investment": min(values)}]
    return []


def _candidates_gearing(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"debt": values[0], "equity": values[1]}]
    return []


def _candidates_interest_cover(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"pbit": max(values), "interest_expense": min(values)}]
    return []


def _candidates_eps(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"profit_after_tax": max(values), "number_of_shares": min(values)}]
    return []


def _candidates_dividend_yield(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 2:
        candidates.append({"dividend_per_share": min(values),
                           "market_price": max(values)})
    return candidates


def _candidates_dividend_cover(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"eps": max(values), "dividend_per_share": min(values)}]
    return []


def _candidates_asset_beta(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 3:
        tax = pcts[0] if pcts else 0.0
        candidates.append({
            "equity_beta": values[0],
            "market_value_debt": values[1],
            "market_value_equity": values[2],
            "tax_rate": tax,
        })
    return candidates


def _candidates_equity_beta(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 3:
        tax = pcts[0] if pcts else 0.0
        candidates.append({
            "asset_beta": values[0],
            "market_value_debt": values[1],
            "market_value_equity": values[2],
            "tax_rate": tax,
        })
    return candidates


def _candidates_pe_ratio(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"market_price": max(values), "eps": min(values)}]
    return []


def _candidates_roe(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"profit_after_tax": max(values), "equity": min(values)}]
    return []


def _candidates_cost_of_preference(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"preference_dividend": min(values), "market_price": max(values)}]
    return []


def _candidates_terp(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if len(values) >= 3:
        n_candidates = sorted(values, reverse=True)
        for n_val in [v for v in n_candidates if v == int(v)]:   # rights ratio is integer
            remaining = [v for v in n_candidates if v != n_val]
            if len(remaining) >= 2:
                cum, issue = remaining[0], remaining[1]
                candidates.append({
                    "cum_rights_price": cum, "issue_price": issue,
                    "rights_ratio_n": n_val,
                })
    return candidates


def _candidates_perpetuity_npv(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    pcts = [n["value"] for n in nums if n["is_percent"]]
    candidates: list[dict[str, Any]] = []
    if values and pcts:
        for cf in values:
            for r in pcts:
                candidates.append({"annual_cashflow": cf, "discount_rate": r})
    elif len(values) >= 2:
        candidates.append({"annual_cashflow": max(values), "discount_rate": min(values)})
    return candidates


def _candidates_roce(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = [n["value"] for n in nums if not n["is_percent"]]
    if len(values) >= 2:
        return [{"pbit": max(values), "capital_employed": min(values)}]
    return []


_FORMULA_CANDIDATES = {
    "npv": _candidates_npv,
    "wacc": _candidates_wacc,
    "capm": _candidates_capm,
    "payback": _candidates_payback,
    "discounted_payback": _candidates_npv,
    "ccc": _candidates_ccc,
    "cost_of_debt": _candidates_cost_of_debt,
    "cost_of_equity_dvm": _candidates_cost_of_equity_dvm,
    "irr": _candidates_irr,
    "arr": _candidates_arr,
    "eoq": _candidates_eoq,
    "equivalent_annual_cost": _candidates_equivalent_annual_cost,
    "profitability_index": _candidates_profitability_index,
    "gearing": _candidates_gearing,
    "interest_cover": _candidates_interest_cover,
    "eps": _candidates_eps,
    "dividend_yield": _candidates_dividend_yield,
    "dividend_cover": _candidates_dividend_cover,
    "asset_beta": _candidates_asset_beta,
    "equity_beta": _candidates_equity_beta,
    "pe_ratio": _candidates_pe_ratio,
    "roe": _candidates_roe,
    "cost_of_preference": _candidates_cost_of_preference,
    "terp": _candidates_terp,
    "perpetuity_npv": _candidates_perpetuity_npv,
    "roce": _candidates_roce,
}

_FORMULA_SOLVERS: dict[str, Any] = {
    "npv": solve_npv,
    "wacc": solve_wacc,
    "capm": solve_capm,
    "payback": solve_payback_period,
    "discounted_payback": solve_discounted_payback,
    "ccc": solve_cash_conversion_cycle,
    "cost_of_debt": solve_cost_of_debt,
    "cost_of_equity_dvm": solve_cost_of_equity_dvm,
    "irr": solve_irr,
    "arr": solve_arr,
    "eoq": solve_eoq,
    "equivalent_annual_cost": solve_equivalent_annual_cost,
    "profitability_index": solve_profitability_index,
    "gearing": solve_gearing,
    "interest_cover": solve_interest_cover,
    "eps": solve_eps,
    "dividend_yield": solve_dividend_yield,
    "dividend_cover": solve_dividend_cover,
    "asset_beta": solve_asset_beta,
    "equity_beta": solve_equity_beta,
    "pe_ratio": solve_pe_ratio,
    "roe": solve_roe,
    "cost_of_preference": solve_cost_of_preference,
    "terp": solve_terp,
    "perpetuity_npv": solve_perpetuity_npv,
    "roce": solve_roce,
}


def _solve_discounted_payback_wrapper(**kwargs: Any) -> float:
    return solve_discounted_payback(
        kwargs.get("initial", 0.0),
        list(kwargs.get("cashflows", [])),
        kwargs.get("rate", 0.0),
    )

_FORMULA_SOLVERS["discounted_payback"] = _solve_discounted_payback_wrapper


# ---------------------------------------------------------------------------
# Layer 2.5 — Freeform expression extraction from explanation text
# ---------------------------------------------------------------------------

class _SafeEvalVisitor(ast.NodeVisitor):
    """AST visitor that only allows safe arithmetic nodes."""
    ALLOWED = {
        ast.Expression, ast.Add, ast.Sub, ast.Mult, ast.Div,
        ast.Pow, ast.Mod, ast.USub, ast.UAdd,
        ast.BinOp, ast.UnaryOp,
        ast.Constant,
        ast.Call, ast.Name, ast.Load,
    }

    def __init__(self) -> None:
        self._safe = True
        self._reason: str | None = None

    def visit(self, node: ast.AST) -> None:
        if not self._safe:
            return
        if type(node) not in self.ALLOWED:
            self._safe = False
            self._reason = f"disallowed node {type(node).__name__}"
            return
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                self._safe = False
                self._reason = "complex call target"
                return
            if node.func.id not in ("sqrt", "abs", "float", "int", "round"):
                self._safe = False
                self._reason = f"disallowed function {node.func.id}"
                return
            if len(node.args) != 1:
                self._safe = False
                self._reason = "multi-arg call"
                return
        super().generic_visit(node)


def safe_expression_evaluate(
    expr: str,
    env: dict[str, float] | None = None,
) -> float | None:
    """Parse and evaluate a safe arithmetic expression.

    Supports ``+``, ``-``, ``*``, ``/``, ``**``, ``%``, parentheses,
    variable names (resolved via *env*), and the functions ``sqrt()``,
    ``abs()``, ``float()``, ``int()``, ``round()``.

    Returns ``None`` if the expression is unsafe or invalid.
    """
    if not expr or not isinstance(expr, str):
        return None
    expr = expr.strip()
    if not expr:
        return None
    expr = expr.replace("×", "*").replace("÷", "/")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    visitor = _SafeEvalVisitor()
    visitor.visit(tree)
    if not visitor._safe:
        return None
    locals_dict: dict[str, Any] = {
        "sqrt": math.sqrt, "abs": abs,
        "float": float, "int": int, "round": round,
    }
    if env:
        locals_dict.update(env)
    try:
        code = compile(tree, "<safe_expr>", "eval")
        result = eval(code, {"__builtins__": {}}, locals_dict)
        if isinstance(result, (int, float)):
            return float(result)
        return None
    except Exception:
        return None


_EXPR_PATTERNS = [
    re.compile(r"=\s*([\d.]+\s*[+\-*/×÷]\s*[\d.]+(?:\s*[+\-*/×÷]\s*[\d.]+)*)"),
    re.compile(r"([\d.]+\s*[*/×÷]\s*[\d.]+(?:\s*[+\-*/×÷]\s*[\d.]+)*)"),
]


def extract_expressions(text: str) -> list[str]:
    """Extract candidate calculation expressions from explanation text."""
    if not text:
        return []
    found: list[str] = []
    for pat in _EXPR_PATTERNS:
        for m in pat.finditer(text):
            expr = m.group(0).strip().lstrip("=").strip()
            if expr and expr not in found:
                found.append(expr)
    return found


# ---------------------------------------------------------------------------
# Freeform verification (Tier 2)
# ---------------------------------------------------------------------------

def freeform_verify(
    explanation: str,
    options: list[float],
    correct_value: float,
) -> str | None:
    """Check if explanation contains a computation that matches a distractor.

    Returns ``"freeform_mismatch"`` if the explanation's computed result
    matches a distractor but not the correct answer.
    """
    if not explanation or len(options) < 2:
        return None
    exprs = extract_expressions(explanation)
    if not exprs:
        return None
    for expr in exprs:
        result = safe_expression_evaluate(expr)
        if result is None:
            continue
        matches_correct = any(
            abs(result - opt) <= max(0.01, abs(opt) * 0.005)
            for opt in options
            if abs(opt - correct_value) <= max(0.01, abs(correct_value) * 0.005)
        )
        if not matches_correct:
            matches_distractor = any(
                abs(result - opt) <= max(0.01, abs(opt) * 0.005)
                and not (abs(opt - correct_value) <= max(0.01, abs(correct_value) * 0.005))
                for opt in options
            )
            if matches_distractor:
                return "freeform_mismatch"
    return None


# ---------------------------------------------------------------------------
# Layer 3 — Answer verification
# ---------------------------------------------------------------------------

def _options_are_numeric(options: list[str]) -> list[float] | None:
    if len(options) != 4:
        return None
    parsed: list[float] = []
    for opt in options:
        stripped = str(opt or "").strip().lstrip("$").lstrip("\u00a3").lstrip("\u20ac")
        stripped = stripped.replace(",", "").replace("%", "")
        try:
            parsed.append(float(stripped))
        except (ValueError, TypeError):
            return None
    return parsed


def _value_matches(ref: float, candidate: float) -> bool:
    if math.isnan(ref) or math.isnan(candidate):
        return False
    abs_tol = max(0.01, abs(ref) * 0.0005)
    return abs(ref - candidate) <= abs_tol


def _normalize_scale(ref: float, options: list[float]) -> tuple[float, list[float]]:
    if not options:
        return ref, options
    mean_opt = sum(options) / len(options)
    if abs(ref) < 1.0 and mean_opt > 1.0:
        ref_scaled = ref * 100.0
        if any(abs(ref_scaled - o) < abs(ref - o) for o in options):
            return ref_scaled, options
    if abs(ref) > 1.0 and mean_opt < 1.0:
        ref_scaled = ref / 100.0
        if any(abs(ref_scaled - o) < abs(ref - o) for o in options):
            return ref_scaled, options
    return ref, options


def _best_match_index(ref: float, options: list[float]) -> int:
    ref, options = _normalize_scale(ref, options)
    best = 0
    best_dist = float("inf")
    for i, opt in enumerate(options):
        dist = abs(ref - opt)
        if dist < best_dist:
            best_dist = dist
            best = i
    return best


def verify_numerical_answer(
    question: str,
    options: list[str],
    correct: str,
    *,
    template_ref: str | None = None,
    template_inputs: dict[str, Any] | None = None,
    explanation: str | None = None,
) -> str | None:
    """Check numerically computed answer matches 'correct'.

    Returns a rejection reason string (e.g. ``"numerical_answer_mismatch:npv"``)
    if the answer is demonstrably wrong, or ``None`` if the answer is
    consistent or the question cannot be verified numerically.

    Three tiers, in order:
      1. Exact verification from structured metadata (template_ref + template_inputs)
      2. Freeform verification from explanation text
      3. Heuristic extraction from question text

    When ``template_ref`` and ``template_inputs`` are provided, exact
    verification is used (no heuristic extraction needed).
    """
    parsed_opts = _options_are_numeric(options)
    if parsed_opts is None:
        return None

    correct_stripped = str(correct or "").strip().lstrip("$").lstrip("\u00a3").lstrip("\u20ac")
    correct_stripped = correct_stripped.replace(",", "").replace("%", "")
    try:
        correct_value = float(correct_stripped)
    except (ValueError, TypeError):
        correct_value = float("nan")

    candidates: list[tuple[str, float]] = []

    # Tier 1: Exact verification from structured metadata
    if template_ref and template_inputs:
        solver = _FORMULA_SOLVERS.get(template_ref)
        if solver and isinstance(template_inputs, dict):
            try:
                result = solver(**template_inputs)
                if not math.isnan(result):
                    candidates.append((template_ref, result))
            except Exception:
                pass
        if candidates:
            _, raw_ref = candidates[0]
            ref, norm_opts = _normalize_scale(raw_ref, parsed_opts)
            best_idx = _best_match_index(ref, norm_opts)
            if _value_matches(norm_opts[best_idx], ref):
                if correct_value is not None and not math.isnan(correct_value):
                    correct_idx = parsed_opts.index(correct_value) if correct_value in parsed_opts else -1
                    if correct_idx == best_idx:
                        return None
                else:
                    return None
            return f"numerical_answer_mismatch:{template_ref}"

    # Tier 2: Freeform verification from explanation text
    if explanation:
        freeform_reason = freeform_verify(explanation, parsed_opts, correct_value)
        if freeform_reason:
            return freeform_reason

    # Tier 3: Heuristic extraction from question text
    nums = extract_numbers(question)
    if len(nums) < 2:
        return None

    formulas = detect_formulas(question)
    if not formulas:
        formulas = list(_FORMULA_CANDIDATES.keys())

    for formula in formulas:
        candidate_fn = _FORMULA_CANDIDATES.get(formula)
        if not candidate_fn:
            continue
        solver = _FORMULA_SOLVERS.get(formula)
        if not solver:
            continue
        param_sets = candidate_fn(nums)
        for params in param_sets:
            try:
                result = solver(**params)
            except Exception:
                continue
            if math.isnan(result):
                continue
            candidates.append((formula, result))

    if not candidates:
        return None

    for formula, ref_raw in candidates:
        ref, opts_scaled = _normalize_scale(ref_raw, parsed_opts)

        best_idx = _best_match_index(ref, opts_scaled)
        best_val = opts_scaled[best_idx]

        matches_correct = False
        if correct_value is not None and not math.isnan(correct_value):
            correct_idx = opts_scaled.index(correct_value) if correct_value in opts_scaled else -1
            if correct_idx >= 0 and best_idx == correct_idx and _value_matches(ref, best_val):
                matches_correct = True

        if matches_correct:
            return None

        distractor_close = any(
            _value_matches(ref, opt) and not (correct_value is not None and _value_matches(ref, correct_value))
            for opt in opts_scaled
        )
        if distractor_close:
            return f"numerical_answer_mismatch:{formula}"

    return None


def verify_numerical_question_batch(
    questions: list[dict[str, Any]],
) -> list[tuple[int, str]]:
    results: list[tuple[int, str]] = []
    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        reason = verify_numerical_answer(
            str(q.get("question", "") or ""),
            list(q.get("options", []) or []),
            str(q.get("correct", "") or ""),
            template_ref=str(q.get("template_ref") or "") or None,
            template_inputs=q.get("template_inputs"),
            explanation=str(q.get("explanation", "") or "") or None,
        )
        if reason:
            results.append((idx, reason))
    return results


# ---------------------------------------------------------------------------
# Formula registry integration
# ---------------------------------------------------------------------------

from studyplan.domain_reasoning.formula_registry import (
    build_solver_dict,
    build_candidate_dict,
    build_signatures,
)

_FORMULA_SOLVERS = build_solver_dict(_FORMULA_SOLVERS)
_FORMULA_CANDIDATES = build_candidate_dict(_FORMULA_CANDIDATES)
_FORMULA_SIGNATURES = build_signatures(_FORMULA_SIGNATURES)
_FORMULA_PRIORITY = {name: prio for name, _, prio in _FORMULA_SIGNATURES}

# Extend __all__ with any auto-generated solver names from the registry
from studyplan.domain_reasoning.formula_registry import get_registry_formulas
for fname in get_registry_formulas():
    solver_name = f"solve_{fname}"
    if solver_name not in __all__:
        # The auto-generated solvers are stored in _FORMULA_SOLVERS;
        # we don't export them as top-level names, but make the formula
        # name discoverable.
        pass
