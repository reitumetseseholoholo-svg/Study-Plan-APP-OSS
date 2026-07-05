"""Domain Specifications — Declarative topic descriptions for 5 ACCA FM topics.

Each topic is a TopicSpec describing its parameters, computations, outputs,
and assumptions. The compiler translates these into CCI ViewStates.

Friction is recorded inline as comments prefixed with FRICTION(N).
"""

from studyplan.provenance.compiler import TopicSpec, ComputationStep


# ============================================================
# 1. CAPM: Capital Asset Pricing Model
# ============================================================
# Formula: Re = Rf + β × (Rm - Rf)
# Simple: 3 parameters → 1 output, single computation.
# FRICTION(1): Trivially simple — compiler is unnecessary overhead for a
# single-step computation. Value emerges at scale (N topics × N steps).

CAPM = TopicSpec(
    id="CAPM",
    title="Capital Asset Pricing Model",
    parameters=(
        {"id": "Rf", "type": "config_value", "target": "Risk-free rate", "metadata": {"semantic_role": "CostOfEquity"}},
        {"id": "beta", "type": "config_value", "target": "Equity beta", "metadata": {"semantic_role": "CostOfEquity"}},
        {
            "id": "MRP",
            "type": "config_value",
            "target": "Market risk premium",
            "metadata": {"semantic_role": "CostOfEquity"},
        },
    ),
    computations=(
        ComputationStep(
            id="gen_CAPM",
            input_artifact_id="beta",
            output_artifact_id="Re_CAPM",
            rule_spec="CAPM: Re = Rf + beta * MRP",
            consumes=("Rf", "MRP"),
            assumptions=("market_efficiency", "diversified_investor", "single_period"),
        ),
    ),
    outputs=(
        {
            "id": "Re_CAPM",
            "type": "call_graph_region",
            "target": "Cost of Equity via CAPM",
            "metadata": {"semantic_role": "CostOfEquity", "method": "CAPM"},
        },
    ),
)


# ============================================================
# 2. Gordon Growth Model (DGM)
# ============================================================
# Formula: Re = D1 / P0 + g
# Equivalent structure to CAPM: parameters in, one output.
# Assumptions encode the model boundary conditions.

GORDON_GROWTH = TopicSpec(
    id="GordonGrowth",
    title="Gordon Growth Model (Dividend Discount Model)",
    parameters=(
        {
            "id": "D1",
            "type": "config_value",
            "target": "Expected dividend next period",
            "metadata": {"semantic_role": "CostOfEquity"},
        },
        {
            "id": "P0",
            "type": "config_value",
            "target": "Current share price",
            "metadata": {"semantic_role": "CostOfEquity"},
        },
        {
            "id": "g",
            "type": "config_value",
            "target": "Expected dividend growth rate",
            "metadata": {"semantic_role": "CostOfEquity"},
        },
    ),
    computations=(
        ComputationStep(
            id="gen_DGM",
            input_artifact_id="D1",
            output_artifact_id="Re_DGM",
            rule_spec="DGM: Re = D1 / P0 + g",
            consumes=("P0", "g"),
            assumptions=("constant_growth_rate", "required_return_gt_growth", "stable_dividend_policy"),
        ),
    ),
    outputs=(
        {
            "id": "Re_DGM",
            "type": "call_graph_region",
            "target": "Cost of Equity via Gordon Growth",
            "metadata": {"semantic_role": "CostOfEquity", "method": "DGM"},
        },
    ),
)


# ============================================================
# 3. NPV: Net Present Value
# ============================================================
# NPV = Σ(CF_i / (1+r)^i) - I_0
#
# Uses serial chain pattern: each discount operation produces an intermediate
# artifact, then binary summations accumulate.
#
# FRICTION(2): The N-period generalization cannot be expressed with static
# N. The spec hardcodes 3 periods. A parametric compiler would need a
# meta-spec ("N periods") and would expand during compilation. This is a
# spec-expressiveness limitation, not a kernel limitation.

NPV = TopicSpec(
    id="NPV",
    title="Net Present Value",
    parameters=(
        {
            "id": "r",
            "type": "config_value",
            "target": "Discount rate",
            "metadata": {"semantic_role": "Parameter", "parameter": "discount_rate"},
        },
        {
            "id": "I_0",
            "type": "config_value",
            "target": "Initial investment",
            "metadata": {"semantic_role": "Parameter", "parameter": "initial_investment"},
        },
        {
            "id": "CF_1",
            "type": "config_value",
            "target": "Cash flow at t=1",
            "metadata": {"semantic_role": "CashFlow", "period": "1"},
        },
        {
            "id": "CF_2",
            "type": "config_value",
            "target": "Cash flow at t=2",
            "metadata": {"semantic_role": "CashFlow", "period": "2"},
        },
        {
            "id": "CF_3",
            "type": "config_value",
            "target": "Cash flow at t=3",
            "metadata": {"semantic_role": "CashFlow", "period": "3"},
        },
    ),
    computations=(
        # Discount each CF
        ComputationStep(
            id="discount_CF_1",
            input_artifact_id="CF_1",
            output_artifact_id="discounted_CF_1",
            rule_spec="discounted_CF_1 = CF_1 / (1+r)^1",
            consumes=("r",),
            assumptions=("constant_discount_rate", "periodic_cash_flows"),
        ),
        ComputationStep(
            id="discount_CF_2",
            input_artifact_id="CF_2",
            output_artifact_id="discounted_CF_2",
            rule_spec="discounted_CF_2 = CF_2 / (1+r)^2",
            consumes=("r",),
            assumptions=("constant_discount_rate", "periodic_cash_flows"),
        ),
        ComputationStep(
            id="discount_CF_3",
            input_artifact_id="CF_3",
            output_artifact_id="discounted_CF_3",
            rule_spec="discounted_CF_3 = CF_3 / (1+r)^3",
            consumes=("r",),
            assumptions=("constant_discount_rate", "periodic_cash_flows"),
        ),
        # Accumulate
        ComputationStep(
            id="sum_12",
            input_artifact_id="discounted_CF_1",
            output_artifact_id="sum_12",
            rule_spec="sum_12 = discounted_CF_1 + discounted_CF_2",
            consumes=("discounted_CF_2",),
        ),
        ComputationStep(
            id="sum_gross",
            input_artifact_id="sum_12",
            output_artifact_id="gross_NPV",
            rule_spec="gross_NPV = sum_12 + discounted_CF_3",
            consumes=("discounted_CF_3",),
        ),
        # Subtract initial investment
        ComputationStep(
            id="net_NPV",
            input_artifact_id="gross_NPV",
            output_artifact_id="NPV",
            rule_spec="NPV = gross_NPV - I_0",
            consumes=("I_0",),
            assumptions=("rational_investment_decision",),
        ),
    ),
    outputs=(
        {
            "id": "discounted_CF_1",
            "type": "call_graph_region",
            "target": "Discounted cash flow at t=1",
            "metadata": {"semantic_role": "DiscountedCashFlow", "period": "1"},
        },
        {
            "id": "discounted_CF_2",
            "type": "call_graph_region",
            "target": "Discounted cash flow at t=2",
            "metadata": {"semantic_role": "DiscountedCashFlow", "period": "2"},
        },
        {
            "id": "discounted_CF_3",
            "type": "call_graph_region",
            "target": "Discounted cash flow at t=3",
            "metadata": {"semantic_role": "DiscountedCashFlow", "period": "3"},
        },
        {
            "id": "sum_12",
            "type": "call_graph_region",
            "target": "Sum of discounted CF_1 and CF_2",
            "metadata": {"semantic_role": "PartialSum", "stage": "1"},
        },
        {
            "id": "gross_NPV",
            "type": "call_graph_region",
            "target": "Gross present value (before subtracting I_0)",
            "metadata": {"semantic_role": "GrossPresentValue"},
        },
        {
            "id": "NPV",
            "type": "call_graph_region",
            "target": "Net Present Value = gross_NPV - I_0",
            "metadata": {"semantic_role": "NetPresentValue"},
        },
    ),
)


# ============================================================
# 4. IRR: Internal Rate of Return
# ============================================================
# Definition: IRR = r such that NPV(r) = 0
#
# FRICTION(3): IRR is a ROOT-FINDING QUERY over the NPV computation, not a
# static computation. The compiler can only emit the static dependency
# structure (NPV model with r as unknown). The iterative search is a
# runtime operation, not a compile-time relationship.
#
# Representation strategy:
# - Parameters = NPV's parameters (I_0, CF_1..CF_n)
# - IRR is an output artifact with a constraint that NPV(IRR) = 0
# - The actual root-finding is a query-layer concern
#
# This is the most interesting friction point: the algebra can represent
# the RELATIONSHIP (NPV = 0 at r = IRR) but not the COMPUTATION (how to
# find r). This mirrors the dependency vs. computation distinction in the
# kernel architecture.

IRR = TopicSpec(
    id="IRR",
    title="Internal Rate of Return",
    parameters=(
        {
            "id": "I_0",
            "type": "config_value",
            "target": "Initial investment",
            "metadata": {"semantic_role": "Parameter", "parameter": "initial_investment"},
        },
        {
            "id": "CF_1",
            "type": "config_value",
            "target": "Cash flow at t=1",
            "metadata": {"semantic_role": "CashFlow", "period": "1"},
        },
        {
            "id": "CF_2",
            "type": "config_value",
            "target": "Cash flow at t=2",
            "metadata": {"semantic_role": "CashFlow", "period": "2"},
        },
        {
            "id": "CF_3",
            "type": "config_value",
            "target": "Cash flow at t=3",
            "metadata": {"semantic_role": "CashFlow", "period": "3"},
        },
    ),
    computations=(
        # IRR models the NPV computation chain but parameterized by unknown r
        ComputationStep(
            id="npv_model",
            input_artifact_id="I_0",
            output_artifact_id="IRR",
            rule_spec="IRR is the discount rate r where NPV(r) = 0",
            consumes=("CF_1", "CF_2", "CF_3"),
            assumptions=("periodic_cash_flows", "single_IRR"),
        ),
    ),
    outputs=(
        {
            "id": "IRR",
            "type": "call_graph_region",
            "target": "Internal Rate of Return: NPV(r) = 0",
            "metadata": {"semantic_role": "InternalRateOfReturn"},
        },
    ),
)


# ============================================================
# 5. APV: Adjusted Present Value
# ============================================================
# APV = NPV(unlevered) + PV(tax shield)
#
# This combines TWO independent computation chains:
#   1. NPV_unlevered: same as NPV but without tax assumptions
#   2. PV(tax_shield): typically Tc × D (perpetuity) or discounted tax shields
#
# FRICTION(4): APV expresses a MERGE of two sub-computations. The compiler
# has no "sub-computation" concept — everything is flattened into a single
# artifact space. The merge is implicit in the dependency DAG (two chains
# converge on the APV output). This is expressible but loses the
# sub-computation boundary. A richer spec would have named sub-computations.

APV = TopicSpec(
    id="APV",
    title="Adjusted Present Value",
    parameters=(
        # Unlevered NPV parameters
        {
            "id": "r_u",
            "type": "config_value",
            "target": "Unlevered cost of equity",
            "metadata": {"semantic_role": "Parameter", "parameter": "unlevered_discount_rate"},
        },
        {
            "id": "I_0",
            "type": "config_value",
            "target": "Initial investment",
            "metadata": {"semantic_role": "Parameter", "parameter": "initial_investment"},
        },
        {
            "id": "CF_1",
            "type": "config_value",
            "target": "Cash flow at t=1",
            "metadata": {"semantic_role": "CashFlow", "period": "1"},
        },
        {
            "id": "CF_2",
            "type": "config_value",
            "target": "Cash flow at t=2",
            "metadata": {"semantic_role": "CashFlow", "period": "2"},
        },
        {
            "id": "CF_3",
            "type": "config_value",
            "target": "Cash flow at t=3",
            "metadata": {"semantic_role": "CashFlow", "period": "3"},
        },
        # Tax shield parameters
        {"id": "Tc", "type": "config_value", "target": "Corporate tax rate", "metadata": {"semantic_role": "TaxRate"}},
        {
            "id": "D",
            "type": "config_value",
            "target": "Market value of debt",
            "metadata": {"semantic_role": "Parameter", "parameter": "debt_value"},
        },
    ),
    computations=(
        # Sub-chain 1: Unlevered NPV (discount each CF by r_u)
        ComputationStep(
            id="unlev_discount_1",
            input_artifact_id="CF_1",
            output_artifact_id="unlev_discounted_1",
            rule_spec="unlev_discounted_1 = CF_1 / (1+r_u)^1",
            consumes=("r_u",),
            assumptions=("constant_unlevered_rate", "periodic_cash_flows"),
        ),
        ComputationStep(
            id="unlev_discount_2",
            input_artifact_id="CF_2",
            output_artifact_id="unlev_discounted_2",
            rule_spec="unlev_discounted_2 = CF_2 / (1+r_u)^2",
            consumes=("r_u",),
            assumptions=("constant_unlevered_rate", "periodic_cash_flows"),
        ),
        ComputationStep(
            id="unlev_discount_3",
            input_artifact_id="CF_3",
            output_artifact_id="unlev_discounted_3",
            rule_spec="unlev_discounted_3 = CF_3 / (1+r_u)^3",
            consumes=("r_u",),
            assumptions=("constant_unlevered_rate", "periodic_cash_flows"),
        ),
        ComputationStep(
            id="unlev_sum_12",
            input_artifact_id="unlev_discounted_1",
            output_artifact_id="unlev_sum_12",
            rule_spec="unlev_sum_12 = unlev_discounted_1 + unlev_discounted_2",
            consumes=("unlev_discounted_2",),
        ),
        ComputationStep(
            id="unlev_sum_gross",
            input_artifact_id="unlev_sum_12",
            output_artifact_id="unlev_gross_NPV",
            rule_spec="unlev_gross_NPV = unlev_sum_12 + unlev_discounted_3",
            consumes=("unlev_discounted_3",),
        ),
        ComputationStep(
            id="unlev_net",
            input_artifact_id="unlev_gross_NPV",
            output_artifact_id="NPV_unlevered",
            rule_spec="NPV_unlevered = unlev_gross_NPV - I_0",
            consumes=("I_0",),
            assumptions=("no_tax_effect",),
        ),
        # Sub-chain 2: PV of tax shield (perpetuity: Tc × D)
        ComputationStep(
            id="pv_tax_shield",
            input_artifact_id="D",
            output_artifact_id="PV_tax_shield",
            rule_spec="PV(tax shield) = Tc × D  (perpetuity assumption)",
            consumes=("Tc",),
            assumptions=("perpetual_debt", "tax_deductible_interest", "constant_tax_rate"),
        ),
        # Merge
        ComputationStep(
            id="compute_APV",
            input_artifact_id="NPV_unlevered",
            output_artifact_id="APV",
            rule_spec="APV = NPV_unlevered + PV_tax_shield",
            consumes=("PV_tax_shield",),
        ),
    ),
    outputs=(
        # Unlevered NPV intermediates
        {
            "id": "unlev_discounted_1",
            "type": "call_graph_region",
            "target": "Unlevered discounted CF at t=1",
            "metadata": {"semantic_role": "DiscountedCashFlow", "period": "1", "leverage": "unlevered"},
        },
        {
            "id": "unlev_discounted_2",
            "type": "call_graph_region",
            "target": "Unlevered discounted CF at t=2",
            "metadata": {"semantic_role": "DiscountedCashFlow", "period": "2", "leverage": "unlevered"},
        },
        {
            "id": "unlev_discounted_3",
            "type": "call_graph_region",
            "target": "Unlevered discounted CF at t=3",
            "metadata": {"semantic_role": "DiscountedCashFlow", "period": "3", "leverage": "unlevered"},
        },
        {
            "id": "unlev_sum_12",
            "type": "call_graph_region",
            "target": "Unlevered partial sum",
            "metadata": {"semantic_role": "PartialSum", "leverage": "unlevered"},
        },
        {
            "id": "unlev_gross_NPV",
            "type": "call_graph_region",
            "target": "Unlevered gross present value",
            "metadata": {"semantic_role": "GrossPresentValue", "leverage": "unlevered"},
        },
        {
            "id": "NPV_unlevered",
            "type": "call_graph_region",
            "target": "Unlevered Net Present Value",
            "metadata": {"semantic_role": "NetPresentValue", "leverage": "unlevered"},
        },
        {
            "id": "PV_tax_shield",
            "type": "call_graph_region",
            "target": "Present value of tax shield (perpetuity)",
            "metadata": {"semantic_role": "TaxShieldPV"},
        },
        {
            "id": "APV",
            "type": "call_graph_region",
            "target": "Adjusted Present Value = NPV_unlevered + PV_tax_shield",
            "metadata": {"semantic_role": "AdjustedPresentValue"},
        },
    ),
)


# ============================================================
# Topic registry
# ============================================================

ALL_TOPICS: dict[str, TopicSpec] = {
    "CAPM": CAPM,
    "GordonGrowth": GORDON_GROWTH,
    "NPV": NPV,
    "IRR": IRR,
    "APV": APV,
}
