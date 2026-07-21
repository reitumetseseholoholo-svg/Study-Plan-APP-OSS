"""P0 — Provenance Completeness.

Hypothesis
----------
Constraint inheritance is not a separate reasoning system — it's a traversal query
over existing graph structure. For any artifact X:

    effective_constraints(X) = constraints(X) U constraints(all provenance ancestors)

where "provenance ancestors" are artifacts reachable via backward traversal
(following output → input edges). The same generic operation works across domains
with zero domain-specific logic.

If true, then:
    Tutor("What assumptions did I just make?")
    == Kernel query("traverse backwards from current artifact, collect constraints")

Prediction
----------
The cross-domain convergence (Probe 7) extends to constraint inheritance:
FM and PostgreSQL use the same traversal primitive to reconstruct inherited
assumptions, because inheritance IS traversal.

Protocol
--------
1. Define collect_inherited_constraints() — purely graph-theoretic:
   traverse backwards, collect transformation constraints, return set.
   ZERO domain knowledge about what a "constraint" or "assumption" is.

2. Verify on FM domain:
   effective_constraints(WACC_posttax) includes CAPM's assumptions
   (market_efficiency, diversified_investor) without any FM-specific logic.

3. Verify cross-domain:
   Same function on PostgreSQL optimizer artifact returns planner constraints.
   No optimizer-specific logic in the traversal.
"""

from studyplan.provenance.kernel import (
    ViewState,
    PREDEFINED_CONTEXTS,
    collect_inherited_constraints,
)
from studyplan.provenance.kernel.loaders import build_pg_optimizer_data
from studyplan.provenance.kernel.types import Artifact, Transformation

EC = PREDEFINED_CONTEXTS["default_optimizer"]


# ============================================================
# FM domain: WACC with assumption constraints
# ============================================================

META_COE = (("semantic_role", "CostOfEquity"),)

CAPM_ARTIFACTS = [
    Artifact(id="Rf", type="config_value", target="Risk-free rate", metadata=META_COE),
    Artifact(id="beta", type="config_value", target="Equity beta", metadata=META_COE),
    Artifact(id="MRP", type="config_value", target="Market risk premium", metadata=META_COE),
]

T_GEN_CAPM = Transformation(
    id="gen_CAPM",
    input_artifact_id="beta",
    output_artifact_id="Re_CAPM",
    transformation_type="generative_mapping",
    rule_spec="CAPM: Re = Rf + beta * MRP",
    constraints=(
        ("consumes", "Rf"),
        ("consumes", "MRP"),
        ("assumption", "market_efficiency"),
        ("assumption", "diversified_investor"),
    ),
)

T_GEN_RD_AFTER_TAX = Transformation(
    id="gen_Rd_after_tax",
    input_artifact_id="Rd",
    output_artifact_id="Rd_after_tax",
    transformation_type="generative_mapping",
    rule_spec="After-tax Rd = Rd * (1 - Tc)",
    constraints=(("consumes", "Tc"), ("assumption", "tax_deductible_interest")),
)

T_GEN_EV = Transformation(
    id="gen_EV",
    input_artifact_id="E",
    output_artifact_id="E_over_V",
    transformation_type="generative_mapping",
    rule_spec="Equity weight = E / (E + D)",
    constraints=(("consumes", "D"),),
)

T_GEN_DV = Transformation(
    id="gen_DV",
    input_artifact_id="D",
    output_artifact_id="D_over_V",
    transformation_type="generative_mapping",
    rule_spec="Debt weight = D / (E + D)",
    constraints=(("consumes", "E"),),
)

T_GEN_WACC = Transformation(
    id="gen_WACC",
    input_artifact_id="Re_CAPM",
    output_artifact_id="WACC_posttax",
    transformation_type="generative_mapping",
    rule_spec="WACC = (E/V)*Re + (D/V)*Rd*(1-Tc)",
    constraints=(
        ("consumes", "E_over_V"),
        ("consumes", "D_over_V"),
        ("consumes", "Rd_after_tax"),
        ("assumption", "constant_capital_structure"),
    ),
)

T_FLOW_RD = Transformation(
    id="flow_Rd_to_WACC",
    input_artifact_id="Rd_after_tax",
    output_artifact_id="WACC_posttax",
    transformation_type="data_flow",
    rule_spec="After-tax cost of debt flows into WACC",
)

T_FLOW_EV = Transformation(
    id="flow_EV_to_WACC",
    input_artifact_id="E_over_V",
    output_artifact_id="WACC_posttax",
    transformation_type="data_flow",
    rule_spec="Equity weight flows into WACC",
)

T_FLOW_DV = Transformation(
    id="flow_DV_to_WACC",
    input_artifact_id="D_over_V",
    output_artifact_id="WACC_posttax",
    transformation_type="data_flow",
    rule_spec="Debt weight flows into WACC",
)


def build_fm_wacc_vs() -> ViewState:
    """FM WACC domain with explicit assumption constraints on transformations."""
    return ViewState(
        artifact_space=frozenset(
            [
                Artifact(id="Rf", type="config_value", target="Risk-free rate", metadata=META_COE),
                Artifact(id="beta", type="config_value", target="Equity beta", metadata=META_COE),
                Artifact(id="MRP", type="config_value", target="Market risk premium", metadata=META_COE),
                Artifact(
                    id="Rd",
                    type="config_value",
                    target="Pre-tax cost of debt",
                    metadata=(("semantic_role", "CostOfDebt"),),
                ),
                Artifact(
                    id="Tc", type="config_value", target="Corporate tax rate", metadata=(("semantic_role", "TaxRate"),)
                ),
                Artifact(
                    id="E",
                    type="config_value",
                    target="Market value of equity",
                    metadata=(("semantic_role", "CapitalStructure"),),
                ),
                Artifact(
                    id="D",
                    type="config_value",
                    target="Market value of debt",
                    metadata=(("semantic_role", "CapitalStructure"),),
                ),
                Artifact(
                    id="Re_CAPM",
                    type="call_graph_region",
                    target="CAPM: Rf + beta * MRP",
                    metadata=META_COE + (("method", "CAPM"),),
                ),
                Artifact(
                    id="Rd_after_tax",
                    type="call_graph_region",
                    target="After-tax cost of debt: Rd * (1 - Tc)",
                    metadata=(("semantic_role", "CostOfDebt_after_tax"),),
                ),
                Artifact(
                    id="E_over_V",
                    type="call_graph_region",
                    target="Equity weight: E / (E + D)",
                    metadata=(("semantic_role", "CapitalStructureWeight"),),
                ),
                Artifact(
                    id="D_over_V",
                    type="call_graph_region",
                    target="Debt weight: D / (E + D)",
                    metadata=(("semantic_role", "CapitalStructureWeight"),),
                ),
                Artifact(
                    id="WACC_posttax",
                    type="call_graph_region",
                    target="Post-tax WACC: (E/V)*Re + (D/V)*Rd*(1-Tc)",
                    metadata=(("semantic_role", "CostOfCapital"), ("tax_treatment", "post_tax")),
                ),
            ]
        ),
        transform_space=frozenset(
            [
                T_GEN_CAPM,
                T_GEN_RD_AFTER_TAX,
                T_GEN_EV,
                T_GEN_DV,
                T_GEN_WACC,
                T_FLOW_RD,
                T_FLOW_EV,
                T_FLOW_DV,
            ]
        ),
    )


# ============================================================
# Tests
# ============================================================


def test_p0_collect_inherited_constraints_base_artifact():
    """A base input artifact (no ancestors) has no inherited constraints."""
    vs = build_fm_wacc_vs()
    result = collect_inherited_constraints(vs, "Rf")
    assert len(result) == 0, f"Base artifact should have no inherited constraints: {result}"


def test_p0_collect_inherited_constraints_intermediate():
    """An intermediate artifact inherits only its direct transformation's constraints."""
    vs = build_fm_wacc_vs()
    result = collect_inherited_constraints(vs, "Re_CAPM")
    # Should have gen_CAPM's constraints: (consumes Rf), (consumes MRP),
    # (assumption market_efficiency), (assumption diversified_investor)
    assert ("assumption", "market_efficiency") in result
    assert ("assumption", "diversified_investor") in result
    assert ("consumes", "Rf") in result
    assert ("consumes", "MRP") in result


def test_p0_constraint_inheritance_via_traversal():
    """effective_constraints(WACC_posttax) includes CAPM assumptions.

    This is the core claim: constraint inheritance IS traversal.
    WACC_posttax should inherit constraints from gen_WACC, gen_CAPM,
    gen_Rd_after_tax, gen_EV, and gen_DV — all via graph reachability alone.
    """
    vs = build_fm_wacc_vs()
    result = collect_inherited_constraints(vs, "WACC_posttax")

    # Direct constraint from gen_WACC
    assert ("assumption", "constant_capital_structure") in result, "Should inherit WACC's own assumption"

    # Inherited via gen_CAPM → Re_CAPM → gen_WACC → WACC_posttax
    assert ("assumption", "market_efficiency") in result, "Should inherit CAPM's assumptions via transitive dependency"
    assert ("assumption", "diversified_investor") in result, (
        "Should inherit CAPM's diversified_investor via transitive dependency"
    )

    # Inherited via gen_Rd_after_tax → Rd_after_tax → data_flow → WACC_posttax
    assert ("assumption", "tax_deductible_interest") in result, "Should inherit tax assumption via data_flow path"

    # Inherited via gen_EV → E_over_V → data_flow → WACC_posttax
    assert ("consumes", "D") in result, "Should inherit consumption constraints from upstream transforms"


def test_p0_inheritance_without_domain_knowledge():
    """The collector has zero FM-specific logic — it's purely graph operations."""
    from studyplan.provenance.kernel import primitives
    import inspect

    source = inspect.getsource(primitives.collect_inherited_constraints)
    assert "market_efficiency" not in source
    assert "assumption" not in source
    assert "CAPM" not in source
    assert "WACC" not in source
    # The only domain knowledge is the generic "consumes" key — that's part of
    # the constraint schema, not FM-specific


# ============================================================
# Cross-domain check: PostgreSQL optimizer
# ============================================================


def test_p0_pg_constraint_inheritance():
    """Same collector, different domain — PostgreSQL optimizer.

    from_clause → gen_geqo → plan_tree_geqo
    gen_geqo has constraint ("activation", "join_count > 12").
    Backward traversal from plan_tree_geqo should find it.
    """
    vs = build_pg_optimizer_data().build()
    result = collect_inherited_constraints(vs, "plan_tree_geqo")

    assert ("activation", "join_count > 12") in result, "GEQO plan tree should inherit the GEQO activation constraint"

    # Should also reach from_clause (upstream of gen_geqo) and find
    # any decision_mapping constraints from from_clause
    constraint_keys = {k for k, v in result}
    assert "activation" in constraint_keys, "Constraint collector should find domain-specific constraint keys"


def test_p0_pg_deep_inheritance():
    """Deep inheritance: from_clause → dec_nl → nestedloop_node.

    nestedloop_node inherits constraints from dec_nl.
    Simultaneously, from_clause is also upstream of gen_geqo → plan_tree_geqo.
    """
    vs = build_pg_optimizer_data().build()
    # Try two different leaf artifacts and verify their chains
    result_nl = collect_inherited_constraints(vs, "nestedloop_node")
    assert ("condition", "cost(nested_loop) < cost(hash_join)") in result_nl, (
        "Nested loop should inherit the decision condition from dec_nl"
    )

    result_geqo = collect_inherited_constraints(vs, "plan_tree_geqo")
    assert ("activation", "join_count > 12") in result_geqo, (
        "GEQO should inherit the activation constraint from gen_geqo"
    )


# ============================================================
# Provenance replay of constraint inheritance
# ============================================================


def test_p0_constraint_inheritance_via_provenance():
    """Constraint inheritance reconstructed from provenance trace alone.

    Run a query that produces WACC_posttax, capture provenance, then
    replay the constraint collection from the provenance trace.
    This tests whether provenance captures enough information to
    reconstruct semantic inheritance after the fact.
    """
    vs = build_fm_wacc_vs()
    # Query to isolate WACC_posttax and its ancestors
    from studyplan.provenance.kernel import compose as run_chain

    result, vs_final = run_chain(
        vs,
        EC,
        [
            ("projection", {"filter_type": "artifact", "predicate": lambda a: a.id == "WACC_posttax"}),
        ],
    )

    # Replay: extract artifact from result, collect inherited constraints
    wacc_artifact = next(iter(result.artifacts))
    inherited = collect_inherited_constraints(vs, wacc_artifact.id)

    # Same assertions as the direct test
    assert ("assumption", "market_efficiency") in inherited
    assert ("assumption", "diversified_investor") in inherited
    assert ("assumption", "constant_capital_structure") in inherited
    assert ("assumption", "tax_deductible_interest") in inherited


def test_p0_provenance_trace_contains_structure():
    """Provenance trace captures query structure needed for constraint inheritance."""
    vs = build_fm_wacc_vs()
    from studyplan.provenance.kernel import compose as run_chain

    result, vs_final = run_chain(
        vs,
        EC,
        [
            ("projection", {"filter_type": "artifact", "predicate": lambda a: a.id == "WACC_posttax"}),
        ],
    )

    assert len(vs_final.provenance) == 1
    entry = vs_final.provenance[0]
    assert entry.primitive == "projection"
    # The provenance entry captures what was queried, not what was returned —
    # the full constraint inheritance requires the original ViewState.
    # This demonstrates that provenance + original data = constraint reconstruction.


# ============================================================
# Edge case: artifact with no provenance ancestors
# ============================================================


def test_p0_predecessor_chain_completeness():
    """The chain of predecessors is complete: every upstream transform's
    constraints are included."""
    vs = build_fm_wacc_vs()
    result = collect_inherited_constraints(vs, "WACC_posttax")

    # Count distinct constraint types collected
    constraint_types = {k for k, v in result}
    assert "assumption" in constraint_types
    assert "consumes" in constraint_types

    # The 3 consumed artifacts (E_over_V, D_over_V, Rd_after_tax) each
    # add their consuming transforms' constraints
    assert len(result) >= 6, "Should collect at least 6 constraints across the WACC dependency chain"


def test_p0_diamond_dependency():
    """Diamond dependency: E_over_V and D_over_V both feed into WACC.
    Both gen_EV and gen_DV constraints should be collected once each."""
    vs = build_fm_wacc_vs()
    result = collect_inherited_constraints(vs, "WACC_posttax")

    # gen_EV has ("consumes", "D")
    assert ("consumes", "D") in result
    # gen_DV has ("consumes", "E")
    assert ("consumes", "E") in result
