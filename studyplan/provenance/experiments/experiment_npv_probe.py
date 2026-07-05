"""FM-01: NPV Domain Probe (Phase II Construction Experiment)

Hypothesis
----------
Net Present Value (NPV) — a multi-cash-flow discounted valuation — can be
represented as a composition of existing CCI primitives without increasing
ontology cardinality. This is the second FM topic tested (after WACC).

This is the key test for the multi-input composition question:

    WACC required 4 inputs → data_flow edges + generative_mapping root.
    NPV requires N cash flows + discount rate + initial investment.
    If NPV also needs the same workaround pattern, then multi-input
    computation is a DOMAIN-WIDE property, not a WACC anomaly.

Predictions
-----------
1. All NPV concepts expressible with existing Artifact types.
2. Multi-input composition uses the same data_flow + generative_mapping
   workaround as WACC — no new primitive needed.
3. Kernel queries (projection, traversal, collect_inherited_constraints)
   work on NPV ViewState without modification.
4. Zero new ontology elements (artifact types, edge semantics, types).

Three-level failure taxonomy
----------------------------
- Vocabulary: name doesn't exist but concept maps to existing type (→ rename)
- Encoding: composition API is awkward but possible (→ better composition)
- Ontology: concept fundamentally unrepresentable (→ new primitive, counts
  against the architecture)

Experiment
----------
Phase 1 — Representational: Build NPV ViewState, classify each construct.
Phase 2 — Query: Run kernel operations, verify correctness.
Phase 3 — Comparison: Compare multi-input pattern with WACC.
"""

from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    Transformation,
    PREDEFINED_CONTEXTS,
    projection,
    collect_inherited_constraints,
)

EC = PREDEFINED_CONTEXTS["default_optimizer"]

META_DCF = (("semantic_role", "DiscountedCashFlow"),)
META_CF = (("semantic_role", "CashFlow"),)
META_PARAM = (("semantic_role", "Parameter"),)


# ============================================================
# Phase 1: Representational — Build NPV ViewState
# ============================================================
# NPV structure:
#   CF_1, CF_2, ..., CF_n  (cash flows)
#   r                        (discount rate)
#   I_0                      (initial investment)
#   Each CF_i → discounted_CF_i = CF_i / (1+r)^i
#   discounted_CF_1..n → NPV = Σ discounted_CF_i - I_0


def build_npv_vs() -> ViewState:
    """Build NPV domain as CCI artifacts + transformations."""
    base_artifacts = [
        Artifact(
            id="r",
            type="config_value",
            target="Discount rate (cost of capital)",
            metadata=META_PARAM + (("parameter", "discount_rate"),),
        ),
        Artifact(
            id="I_0",
            type="config_value",
            target="Initial investment (t=0)",
            metadata=META_PARAM + (("parameter", "initial_investment"),),
        ),
        Artifact(id="CF_1", type="config_value", target="Cash flow at t=1", metadata=META_CF + (("period", "1"),)),
        Artifact(id="CF_2", type="config_value", target="Cash flow at t=2", metadata=META_CF + (("period", "2"),)),
        Artifact(id="CF_3", type="config_value", target="Cash flow at t=3", metadata=META_CF + (("period", "3"),)),
    ]

    # Each CF discounted: discounted_CF_i = CF_i / (1+r)^i
    discount_transforms = [
        Transformation(
            id=f"discount_CF_{i}",
            input_artifact_id=f"CF_{i}",
            output_artifact_id=f"discounted_CF_{i}",
            transformation_type="generative_mapping",
            rule_spec=f"discounted_CF_{i} = CF_{i} / (1+r)^{i}",
            constraints=(
                ("consumes", "r"),
                ("assumption", "constant_discount_rate"),
                ("assumption", "periodic_cash_flows"),
            ),
        )
        for i in range(1, 4)
    ]

    # Discounted CF artifacts + intermediate sum + final NPV
    intermediate_artifacts = [
        Artifact(
            id=f"discounted_CF_{i}",
            type="call_graph_region",
            target=f"Discounted cash flow at t={i}",
            metadata=META_DCF + (("period", str(i)),),
        )
        for i in range(1, 4)
    ]

    # Summation chain: discounted_CF_1 + discounted_CF_2 = sum_12
    # sum_12 + discounted_CF_3 = gross_NPV
    # gross_NPV - I_0 = NPV
    sum_chain_artifacts = [
        Artifact(
            id="sum_12",
            type="call_graph_region",
            target="Sum of discounted CF_1 and CF_2",
            metadata=(("semantic_role", "PartialSum"), ("stage", "1")),
        ),
        Artifact(
            id="gross_NPV",
            type="call_graph_region",
            target="Gross present value (before subtracting I_0)",
            metadata=(("semantic_role", "GrossPresentValue"),),
        ),
        Artifact(
            id="NPV",
            type="call_graph_region",
            target="Net Present Value = gross_NPV - I_0",
            metadata=(("semantic_role", "NetPresentValue"),),
        ),
    ]

    sum_transforms = [
        Transformation(
            id="sum_12",
            input_artifact_id="discounted_CF_1",
            output_artifact_id="sum_12",
            transformation_type="generative_mapping",
            rule_spec="sum_12 = discounted_CF_1 + discounted_CF_2",
            constraints=(("consumes", "discounted_CF_2"),),
        ),
        Transformation(
            id="sum_gross",
            input_artifact_id="sum_12",
            output_artifact_id="gross_NPV",
            transformation_type="generative_mapping",
            rule_spec="gross_NPV = sum_12 + discounted_CF_3",
            constraints=(("consumes", "discounted_CF_3"),),
        ),
        Transformation(
            id="net_NPV",
            input_artifact_id="gross_NPV",
            output_artifact_id="NPV",
            transformation_type="generative_mapping",
            rule_spec="NPV = gross_NPV - I_0",
            constraints=(("consumes", "I_0"), ("assumption", "rational_investment_decision")),
        ),
    ]

    return ViewState(
        artifact_space=frozenset(base_artifacts + intermediate_artifacts + sum_chain_artifacts),
        transform_space=frozenset(discount_transforms + sum_transforms),
    )


# ============================================================
# Phase 1 cell classification
# ============================================================

CLASSIFICATION = {
    "discount_rate": (
        "Discount rate (r)",
        "VOCABULARY: config_value with semantic_role=Parameter",
        "Maps to config_value (existing type). Semantic metadata disambiguates role.",
        "No ontology failure",
    ),
    "cash_flow_period": (
        "Periodic cash flows (CF_i)",
        "VOCABULARY: config_value with semantic_role=CashFlow + period metadata",
        "Same as discount rate. Multiple instances distinguished by metadata.",
        "No ontology failure",
    ),
    "discount_operation": (
        "Discount a single cash flow: CF_i / (1+r)^i",
        "VOCABULARY: generative_mapping with consumes constraint for r",
        "Single-input generative_mapping works. r is a consumed parameter.",
        "No ontology failure",
    ),
    "multi_cf_discount": (
        "Discount multiple cash flows against the same r",
        "Vocabulary: multiple parallel generative_mappings, all consuming r.",
        "Same pattern repeats N times. Multi-input expressible as N separate transforms.",
        "No ontology failure",
    ),
    "summation_chain": (
        "Accumulate discounted CFs: Σ discounted_CF_i",
        "ENCODING: no native sum-in-1 primitive. Must chain binary summations.",
        "Summation requires N-1 intermediate artifacts (sum_12, gross_NPV). Ugly but works.",
        "ENCODING: same pressure as WACC's multi-input. Composition layer is awkward for N>2 operations.",
    ),
    "subtract_investment": (
        "NPV = gross_NPV - I_0",
        "No vocabulary issue",
        "Binary operation expressible as simple generative_mapping.",
        "No ontology failure",
    ),
    "constant_discount_rate": (
        "Assumption: r is constant across all periods",
        "No vocabulary issue",
        "Expressible as constraint on each discount transform.",
        "No ontology failure",
    ),
    "sensitivity_analysis": (
        "What if r changes? Or a CF changes?",
        "VOCABULARY: not a construct but a query pattern",
        "Same as WACC row 9: parameterized over EvaluationContext. Not a static artifact.",
        "No ontology failure. Same deferral as WACC sensitivity.",
    ),
}


# ============================================================
# Phase 2: Queries — Verify kernel operations on NPV
# ============================================================


def test_npv_viewstate_built():
    """ViewState builds without error."""
    vs = build_npv_vs()
    assert len(vs.artifact_space) > 0
    assert len(vs.transform_space) > 0


def test_npv_artifacts_count():
    """Count all artifacts: 5 base + 3 discounted + 3 sum chain = 11."""
    vs = build_npv_vs()
    assert len(vs.artifact_space) == 11


def test_npv_transforms_count():
    """Count all transforms: 3 discount + 3 sum = 6."""
    vs = build_npv_vs()
    assert len(vs.transform_space) == 6


def test_npv_discount_traversal():
    """Traverse from NPV back through discount chain, verify all CFs reachable."""
    vs = build_npv_vs()
    inherited = collect_inherited_constraints(vs, "NPV")
    # Should include constraints from the full chain
    assert ("assumption", "constant_discount_rate") in inherited
    assert ("assumption", "periodic_cash_flows") in inherited
    assert ("assumption", "rational_investment_decision") in inherited
    assert ("consumes", "I_0") in inherited


def test_npv_discount_consumes_r():
    """Each discount transform consumes the discount rate r."""
    vs = build_npv_vs()
    for i in range(1, 4):
        inherited = collect_inherited_constraints(vs, f"discounted_CF_{i}")
        assert ("consumes", "r") in inherited
        assert ("assumption", "constant_discount_rate") in inherited


def test_npv_projection_by_semantic_role():
    """Project all artifacts with a given semantic_role."""
    vs = build_npv_vs()
    result, _ = projection(
        vs,
        EC,
        filter_type="artifact",
        predicate=lambda a: a.metadata_dict().get("semantic_role") == "CashFlow",
    )
    assert len(result.artifacts) == 3  # CF_1, CF_2, CF_3


def test_npv_projection_by_parameter():
    """Project parameters only."""
    vs = build_npv_vs()
    result, _ = projection(
        vs,
        EC,
        filter_type="artifact",
        predicate=lambda a: a.metadata_dict().get("semantic_role") == "Parameter",
    )
    assert len(result.artifacts) == 2  # r, I_0


def test_npv_predecessor_chain():
    """Predecessor chain from NPV is complete and includes all upstream transforms."""
    vs = build_npv_vs()
    inherited = collect_inherited_constraints(vs, "NPV")
    # All 3 discount transforms add assumptions
    assert ("assumption", "periodic_cash_flows") in inherited
    # The summation chain adds constraints
    assert ("consumes", "I_0") in inherited
    assert len(inherited) >= 4, f"Should inherit from all upstream transforms: {inherited}"


# ============================================================
# Phase 3: Compare multi-input pattern with WACC
# ============================================================


def test_npv_parallel_discount_structure():
    """NPV parallel discount structure matches WACC's parallel consumption pattern.

    WACC: gen_EV consumes D, gen_DV consumes E (parallel).
    NPV: three discount transforms all consume r (parallel).
    """
    vs = build_npv_vs()
    # All three discount transforms consume r
    for i in range(1, 4):
        inherited = collect_inherited_constraints(vs, f"discounted_CF_{i}")
        assert ("consumes", "r") in inherited

    # All three are parallel — no transform depends on another discount's output
    # This creates a fan-out pattern (1 r → 3 discounts) similar to WACC's fan-in
    discount_transforms = [t for t in vs.transform_space if t.id.startswith("discount_CF")]
    assert len(discount_transforms) == 3
    # Verify they all consume r but produce different outputs
    r_consumers = [t.id for t in discount_transforms if any(c == ("consumes", "r") for c in t.constraints)]
    assert len(r_consumers) == 3


def test_npv_summation_chain_is_serial():
    """NPV summation chain is serial (not parallel), unlike WACC's fan-in.

    WACC: E_over_V + D_over_V + Rd_after_tax all feed into WACC_posttax (1 transform, 3 inputs).
    NPV: discounted_CF_1 + discounted_CF_2 = sum_12, then + discounted_CF_3 = gross_NPV.
    This is a LINEAR CHAIN, not a multi-input fan-in.

    Implication: NPV does NOT push the same multi-input pressure as WACC.
    The multi-input pressure in WACC was specific to the valuation formula
    (4 components merged in one equation). NPV's summation is inherently
    associative and sequential.
    """
    vs = build_npv_vs()
    # Check: sum_12 is input to sum_gross, which is input to net_NPV
    sum_12 = next(t for t in vs.transform_space if t.id == "sum_12")
    assert sum_12.input_artifact_id == "discounted_CF_1"
    assert ("consumes", "discounted_CF_2") in sum_12.constraints

    sum_gross = next(t for t in vs.transform_space if t.id == "sum_gross")
    assert sum_gross.input_artifact_id == "sum_12"
    assert ("consumes", "discounted_CF_3") in sum_gross.constraints

    # NPV itself: net_NPV has input=gross_NPV, consumes I_0
    # This is a binary operation (gross_NPV - I_0), not a multi-input fan-in
    net_npv = next(t for t in vs.transform_space if t.id == "net_NPV")
    assert net_npv.input_artifact_id == "gross_NPV"
    assert ("consumes", "I_0") in net_npv.constraints

    # Key conclusion: NPV's chain is SERIAL (depth 3), not FAN-IN (breadth 4).
    # WACC's formula was a single equation with 4 variables.
    # NPV's summation is incremental — each step has 2 inputs (unary + 1 consumed).
    # The unary transformation constraint holds for NPV without stretching.


def test_npv_requires_no_new_primitives():
    """NPV uses only: config_value, call_graph_region, generative_mapping, data_flow.

    No new Artifact types, no new edge semantics, no new primitive operations.
    """
    vs = build_npv_vs()
    artifact_types = {a.type for a in vs.artifact_space}
    assert artifact_types <= {"config_value", "call_graph_region"}, f"Unexpected artifact types: {artifact_types}"

    transform_types = {t.transformation_type for t in vs.transform_space}
    assert transform_types <= {"generative_mapping"}, f"Unexpected transform types: {transform_types}"


def test_npv_all_metadatas_set():
    """Every artifact has at least semantic_role metadata."""
    vs = build_npv_vs()
    for a in vs.artifact_space:
        md = a.metadata_dict()
        assert "semantic_role" in md, f"Artifact {a.id} missing semantic_role"
