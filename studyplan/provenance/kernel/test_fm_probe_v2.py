"""FM Domain Probe v2 — WACC ontology worksheet.

Method: For every FM construct, ask whether existing ontology can express
it. Classify each failure as vocabulary (rename), encoding (composition),
or ontology (new primitive). Only the third counts against the ontology.

Three-level failure taxonomy:
  1. VOCABULARY — name is misleading; rename without changing structure
  2. ENCODING — composition is awkward; improve pattern but no new types
  3. ONTOLOGY — no composition exists; genuinely new primitive needed

Key insight from discussion: interpretation (semantic role) is metadata
on artifacts, not an edge type. Assumptions and preconditions are
artifact attributes, not graph nodes.
"""

from studyplan.provenance.kernel import (
    ViewState,
    PREDEFINED_CONTEXTS,
    projection,
    Artifact,
    Transformation,
)

EC = PREDEFINED_CONTEXTS["default_optimizer"]

# ============================================================
# WORKSHEET: FM construct → ontology mapping
# ============================================================
# Each section defines one FM construct and classifies the fit.

# ---
# WORKSHEET ROW 1: Formula (e.g., CAPM)
# Construct: Re = Rf + β × (Rm - Rf)
# Ontology candidate: generative_mapping over computational artifacts
# ---

# Semantic role assigned as artifact metadata, not a separate edge
META_COE = (("semantic_role", "CostOfEquity"),)
META_COD = (("semantic_role", "CostOfDebt"),)
META_CSTR = (("semantic_role", "CapitalStructure"),)
META_CCAP = (("semantic_role", "CostOfCapital"),)
META_CW = (("semantic_role", "CapitalStructureWeight"),)
META_TAX = (("semantic_role", "TaxRate"),)

CAPM_ARTIFACTS = [
    Artifact(id="Rf", type="config_value", target="Risk-free rate", metadata=META_COE),
    Artifact(id="beta", type="config_value", target="Equity beta", metadata=META_COE),
    Artifact(id="MRP", type="config_value", target="Market risk premium", metadata=META_COE),
    Artifact(
        id="Re_CAPM",
        type="call_graph_region",
        target="CAPM output: Rf + β × MRP",
        metadata=META_COE + (("method", "CAPM"),),
    ),
]

T_GEN_CAPM = Transformation(
    id="gen_CAPM",
    input_artifact_id="beta",
    output_artifact_id="Re_CAPM",
    transformation_type="generative_mapping",
    rule_spec="CAPM: Re = Rf + β × MRP",
    constraints=(("consumes", "Rf"), ("consumes", "MRP")),
)

CLASSIFICATION_ROW_1 = (
    "Formula (CAPM)",
    "VOCABULARY: ast_node is too compiler-specific → rename to computational_artifact",
    "generative_mapping fits cleanly: inputs → computation → output",
    "No ontology failure",
)

# ---
# WORKSHEET ROW 2: Assumption (e.g., market efficiency)
# Construct: CAPM requires market efficiency, diversified investors
# Ontology candidate: constraint on the generative_mapping
# ---

# Assumption is a constraint tuple on the transformation, not a new type

T_GEN_CAPM_WITH_ASSUMPTIONS = Transformation(
    id="gen_CAPM_assumptions",
    input_artifact_id="beta",
    output_artifact_id="Re_CAPM",
    transformation_type="generative_mapping",
    rule_spec="CAPM: Re = Rf + β × MRP",
    constraints=(
        ("consumes", "Rf"),
        ("consumes", "MRP"),
        ("assumption", "market_efficiency — all available info in price"),
        ("assumption", "diversified_investor — only systematic risk priced"),
        ("assumption", "single_period — no multi-period dynamics"),
    ),
)

CLASSIFICATION_ROW_2 = (
    "Assumption (market efficiency)",
    "VOCABULARY: 'constraint' sounds limiting; 'precondition' is more neutral",
    "Tuples on transformation naturally express 'this transformation valid only under...'",
    "No ontology failure. But constraint INHERITANCE (do WACC artifacts inherit CAPM assumptions?) is a kernel gap.",
)

# ---
# WORKSHEET ROW 3: Model (e.g., CAPM, DGM as distinct computations)
# Construct: CAPM computes Re; DGM computes Re (same semantic role, different method)
# Ontology candidate: separate artifacts sharing a semantic_role metadata property
# ---

Artifact(
    id="Re_DGM", type="call_graph_region", target="DGM output: D1/P0 + g", metadata=META_COE + (("method", "DGM"),)
)

CLASSIFICATION_ROW_3 = (
    "Model (CAPM vs DGM as parallel computations)",
    "No vocabulary issue",
    "Each model is a separate computation artifact. Semantic role is metadata on both. No edge needed between them — they share a role, not an identity.",
    "No ontology failure",
)

# ---
# WORKSHEET ROW 4: Interpretation (symbol → meaning)
# Construct: Re denotes "Cost of Equity" (semantic assignment)
# Ontology candidate: metadata on the output artifact, NOT a transformation
# ---

CLASSIFICATION_ROW_4 = (
    "Interpretation (Re → 'Cost of Equity')",
    "VOCABULARY: edge semantics like 'interpretation_mapping' would imply a graph relationship; this is an attribute",
    "semantic_role as metadata cleanly assigns meaning without creating spurious edges. Multiple models can share the same role.",
    "No ontology failure",
)

# ---
# WORKSHEET ROW 5: Approximation (e.g., DGM with constant growth)
# Construct: DGM approximates perpetuity value under constant growth assumption
# Ontology candidate: additional assumption constraint on the transformation
# ---

T_GEN_DGM = Transformation(
    id="gen_DGM",
    input_artifact_id="Re_DGM",
    output_artifact_id="Re_DGM",  # self-loop: computation generates itself
    transformation_type="generative_mapping",
    rule_spec="DGM: Re = D1/P0 + g (Gordon Growth Model)",
    constraints=(
        ("assumption", "constant_growth_rate"),
        ("assumption", "required_return_gt_growth"),
        ("assumption", "stable_dividend_policy"),
    ),
)

CLASSIFICATION_ROW_5 = (
    "Approximation (DGM constant growth perpetuity)",
    "No vocabulary issue",
    "Approximation is expressed via assumptions on the generative_mapping. The constraint set is richer than 'exact' models.",
    "No ontology failure",
)

# ---
# WORKSHEET ROW 6: Constraint (e.g., capital structure weights sum to 1)
# Construct: E/V + D/V = 1 (identity constraint on capital structure)
# Ontology candidate: equivalence_mapping (E/V and D/V are complementary)
# ---

# This doesn't fit equivalence_mapping cleanly because E/V and D/V are
# not equivalent — they're complementary. They sum to 1.
# Could be expressed as: observable constraint on the artifact pair,
# or as a structural property of the computation.

CLASSIFICATION_ROW_6 = (
    "Constraint (E/V + D/V = 1)",
    "VOCABULARY: no existing name captures 'complementary pair'",
    "Cannot express as a single edge. Could be two equivalence_mappings: (E/V → 1 - D/V) and (D/V → 1 - E/V). This works but is redundant.",
    "NEEDS BETTER COMPOSITION: a pairwise constraint is expressible but awkward. Not an ontology failure — the information is present, just distributed.",
)

# ---
# WORKSHEET ROW 7: Diagnostic misconception
# Construct: Student confuses pre-tax and post-tax WACC
# Ontology candidate: projection over two artifacts sharing a semantic role
# ---

CLASSIFICATION_ROW_7 = (
    "Diagnostic misconception (pre-tax vs post-tax WACC)",
    "No vocabulary issue",
    "Two artifacts (WACC_pre_tax, WACC_post_tax) differ only by cost-of-debt component. A projection query can identify the divergence point. Misconception = wrong path selection in the computation graph.",
    "No ontology failure",
)

# ---
# WORKSHEET ROW 8: Alternative valuation method
# Construct: APV (Adjusted Present Value) vs WACC for firm valuation
# Ontology candidate: two distinct computational artifacts sharing output role
# ---

CLASSIFICATION_ROW_8 = (
    "Alternative valuation method (APV vs WACC)",
    "No vocabulary issue",
    "Same pattern as CAPM vs DGM: separate artifacts, shared semantic_role. Decision point modeled as... hmm, there's no explicit 'alternative path' edge type.",
    "ENCODING: cannot express 'these two computations are alternatives for the same purpose' without using decision_mapping or just having both present.",
)

# ---
# WORKSHEET ROW 9: Sensitivity analysis
# Construct: How does WACC change when Tc varies?
# Ontology candidate: query over parameter space
# ---

CLASSIFICATION_ROW_9 = (
    "Sensitivity analysis (WACC vs Tc)",
    "VOCABULARY: not a single construct but a query pattern",
    "Expressible as: project(WACC), then evaluate under different Tc values via different EvaluationContexts. Not a static relationship — it's a query over parameterized space.",
    "No ontology failure. But the kernel doesn't support parameterized evaluation (vary a constraint and re-evaluate). This is a runtime capability, not an ontology gap.",
)


# ============================================================
# Build ViewStates
# ============================================================


def build_row1_vs() -> ViewState:
    """CAPM formula as ontology."""
    return ViewState(
        artifact_space=frozenset(
            CAPM_ARTIFACTS
            + [
                Artifact(
                    id="Re",
                    type="call_graph_region",
                    target="Cost of Equity (generic semantic role)",
                    metadata=META_COE,
                ),
            ]
        ),
        transform_space=frozenset([T_GEN_CAPM]),
    )


def build_row2_vs() -> ViewState:
    """CAPM with explicit assumptions."""
    return ViewState(
        artifact_space=frozenset(
            CAPM_ARTIFACTS
            + [
                Artifact(
                    id="market_efficiency_flag",
                    type="config_value",
                    target="Market efficiency precondition",
                    metadata=(("role", "precondition"),),
                ),
            ]
        ),
        transform_space=frozenset([T_GEN_CAPM_WITH_ASSUMPTIONS]),
    )


def build_full_wacc_vs() -> ViewState:
    """Complete WACC domain."""
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
                    id="Re_DGM",
                    type="call_graph_region",
                    target="DGM: D1/P0 + g",
                    metadata=META_COE + (("method", "DGM"),),
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
                    id="WACC",
                    type="call_graph_region",
                    target="WACC = (E/V)*Re + (D/V)*Rd*(1-Tc)",
                    metadata=(("semantic_role", "CostOfCapital"),),
                ),
                Artifact(
                    id="WACC_pretax",
                    type="call_graph_region",
                    target="Pre-tax WACC: (E/V)*Re + (D/V)*Rd",
                    metadata=(("semantic_role", "CostOfCapital"), ("tax_treatment", "pre_tax")),
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
                # CAPM computation
                Transformation(
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
                ),
                # DGM computation
                Transformation(
                    id="gen_DGM",
                    input_artifact_id="Re_DGM",
                    output_artifact_id="Re_DGM",
                    transformation_type="generative_mapping",
                    rule_spec="DGM: Re = D1/P0 + g",
                    constraints=(("assumption", "constant_growth"), ("assumption", "required_return_gt_growth")),
                ),
                # After-tax cost of debt
                Transformation(
                    id="gen_Rd_after_tax",
                    input_artifact_id="Rd",
                    output_artifact_id="Rd_after_tax",
                    transformation_type="generative_mapping",
                    rule_spec="After-tax Rd = Rd * (1 - Tc)",
                    constraints=(("consumes", "Tc"), ("assumption", "tax_deductible_interest")),
                ),
                # Capital structure weights
                Transformation(
                    id="gen_EV",
                    input_artifact_id="E",
                    output_artifact_id="E_over_V",
                    transformation_type="generative_mapping",
                    rule_spec="Equity weight = E / (E + D)",
                    constraints=(("consumes", "D"),),
                ),
                Transformation(
                    id="gen_DV",
                    input_artifact_id="D",
                    output_artifact_id="D_over_V",
                    transformation_type="generative_mapping",
                    rule_spec="Debt weight = D / (E + D)",
                    constraints=(("consumes", "E"),),
                ),
                # WACC computations
                Transformation(
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
                ),
                # Pre-tax WACC (no tax shield)
                Transformation(
                    id="gen_WACC_pretax",
                    input_artifact_id="Re_CAPM",
                    output_artifact_id="WACC_pretax",
                    transformation_type="generative_mapping",
                    rule_spec="Pre-tax WACC = (E/V)*Re + (D/V)*Rd",
                    constraints=(
                        ("consumes", "E_over_V"),
                        ("consumes", "D_over_V"),
                        ("consumes", "Rd"),
                        ("assumption", "no_tax") or ("assumption", "irrelevant_tax"),
                    ),
                ),
                # Data flow for dependency structure
                Transformation(
                    id="flow_Rd_to_WACC",
                    input_artifact_id="Rd_after_tax",
                    output_artifact_id="WACC_posttax",
                    transformation_type="data_flow",
                    rule_spec="After-tax cost of debt flows into post-tax WACC",
                ),
                Transformation(
                    id="flow_EV_to_WACC",
                    input_artifact_id="E_over_V",
                    output_artifact_id="WACC_posttax",
                    transformation_type="data_flow",
                    rule_spec="Equity weight flows into WACC",
                ),
                Transformation(
                    id="flow_DV_to_WACC",
                    input_artifact_id="D_over_V",
                    output_artifact_id="WACC_posttax",
                    transformation_type="data_flow",
                    rule_spec="Debt weight flows into WACC",
                ),
            ]
        ),
    )


# ============================================================
# PROBES
# ============================================================


def test_row1_formula():
    """Row 1: Formula as generative_mapping."""
    vs = build_row1_vs()
    result, _ = projection(vs, EC, filter_type="transformation", predicate=lambda t: t.id == "gen_CAPM")
    assert len(result.transforms) == 1


def test_row2_assumptions():
    """Row 2: Assumptions as constraints on transformation."""
    vs = build_row2_vs()
    result, _ = projection(vs, EC, filter_type="transformation", predicate=lambda t: t.id == "gen_CAPM_assumptions")
    assert len(result.transforms) == 1
    t = list(result.transforms)[0]
    assumptions = [c for c in t.constraints if c[0] == "assumption"]
    assert len(assumptions) >= 2


def test_row3_model():
    """Row 3: Multiple models share a semantic_role."""
    vs = build_full_wacc_vs()
    # Find all artifacts with CostOfEquity role
    result, _ = projection(
        vs,
        EC,
        filter_type="artifact",
        predicate=lambda a: any(k == "semantic_role" and v == "CostOfEquity" for k, v in a.metadata),
    )
    count = len(result.artifacts)
    assert count >= 2, f"Should have multiple CostOfEquity models (found {count})"


def test_row4_interpretation():
    """Row 4: Interpretation is metadata, not an edge.

    The core claim: semantic_role on artifact metadata replaces any
    hypothetical 'interpretation_mapping' edge type.
    """
    vs = build_full_wacc_vs()
    # Every artifact with a semantic_role should have it internally
    # No edge traversal needed to discover "what is this artifact's meaning"
    result, _ = projection(
        vs, EC, filter_type="artifact", predicate=lambda a: any(k == "semantic_role" for k, v in a.metadata)
    )
    assert len(result.artifacts) >= 10, "Most WACC artifacts should carry semantic role metadata"


def test_row5_approximation():
    """Row 5: Approximation as enriched assumption set."""
    vs = build_full_wacc_vs()
    result, _ = projection(
        vs, EC, filter_type="transformation", predicate=lambda t: "constant_growth" in str(t.constraints)
    )
    assert len(result.transforms) >= 1
    t = list(result.transforms)[0]
    approx_assumptions = [c for c in t.constraints if c[0] == "assumption" and "constant" in c[1].lower()]
    assert len(approx_assumptions) >= 1


def test_row6_complementary_constraint():
    """Row 6: E/V + D/V = 1 requires better composition.

    This is an ENCODING failure. The information exists (both use same inputs),
    but there's no single primitive for 'these two values are complementary.'
    """
    vs = build_full_wacc_vs()
    # Workaround: both artifacts share the same inputs E and D
    result, _ = projection(vs, EC, filter_type="transformation", predicate=lambda t: t.id in ("gen_EV", "gen_DV"))
    assert len(result.transforms) == 2
    ev = next(t for t in result.transforms if t.id == "gen_EV")
    dv = next(t for t in result.transforms if t.id == "gen_DV")
    # Both consume {E, D}. The complementarity is implicit in shared inputs.
    assert any("D" in str(c) for c in ev.constraints)
    assert any("E" in str(c) for c in dv.constraints)
    # This works but doesn't EXPLICITLY represent the sum-to-1 constraint.
    # User query would need to detect complementary patterns.
    # Not an ontology failure — information is present, just distributed.


def test_row7_misconception():
    """Row 7: Diagnostic misconception as projection query.

    Student who confuses pre-tax/post-tax WACC has selected the wrong
    artifact path. The kernel can find both and compare them.
    """
    vs = build_full_wacc_vs()
    # Find all CostOfCapital artifacts — shows WACC variants
    result, _ = projection(
        vs,
        EC,
        filter_type="artifact",
        predicate=lambda a: any(k == "semantic_role" and v == "CostOfCapital" for k, v in a.metadata),
    )
    assert len(result.artifacts) >= 2
    variants = {(a.id, dict(a.metadata).get("tax_treatment", "unknown")) for a in result.artifacts}
    assert ("WACC_pretax", "pre_tax") in variants
    assert ("WACC_posttax", "post_tax") in variants


def test_row8_alternative_methods():
    """Row 8: Alternative methods share semantic_role.

    Currently modeled as separate artifacts. No 'alternative_to' edge exists.
    """
    vs = build_full_wacc_vs()
    result, _ = projection(vs, EC, filter_type="artifact", predicate=lambda a: "CostOfEquity" in str(a.metadata))
    methods = {dict(a.metadata).get("method") for a in result.artifacts if "method" in dict(a.metadata)}
    assert "CAPM" in methods
    assert "DGM" in methods


def test_row9_sensitivity():
    """Row 9: Sensitivity analysis as parameterized query.

    The kernel doesn't support parameterized evaluation natively.
    This is a runtime capability gap, not an ontology gap.
    """
    vs = build_full_wacc_vs()
    # Can compute WACC under different Tc values by varying the EvaluationContext
    result, _ = projection(vs, EC, filter_type="artifact", predicate=lambda a: a.id.startswith("WACC"))
    assert len(result.artifacts) >= 1


# ============================================================
# WORKSHEET SUMMARY
# ============================================================


def test_worksheet_summary():
    """Print the ontology worksheet with failure classification."""
    rows = [
        CLASSIFICATION_ROW_1,
        CLASSIFICATION_ROW_2,
        CLASSIFICATION_ROW_3,
        CLASSIFICATION_ROW_4,
        CLASSIFICATION_ROW_5,
        CLASSIFICATION_ROW_6,
        CLASSIFICATION_ROW_7,
        CLASSIFICATION_ROW_8,
        CLASSIFICATION_ROW_9,
    ]

    print("=" * 72)
    print("FM ONTOLOGY WORKSHEET — Failure Classification")
    print("=" * 72)
    print(f"{'Construct':<38} {'Type':<16} {'Outcome':<16}")
    print("-" * 72)

    vocab = 0
    encoding = 0
    ontology = 0

    for name, v, e, o in rows:
        # Determine type
        if "VOCABULARY" in v:
            t = "1. Vocabulary"
            vocab += 1
        elif v:
            t = "—"
        else:
            t = "—"

        # Determine outcome
        if "No ontology failure" in o:
            outcome = "✓ Survives"
        elif "ENCODING" in o or "NEEDS BETTER" in e:
            outcome = "◐ Encoding"
            encoding += 1
        else:
            outcome = "✗ FAIL"
            ontology += 1

        print(f"{name:<38} {t:<16} {outcome:<16}")

    print("-" * 72)
    total = len(rows)
    print(f"Total constructs: {total}")
    print(f"  Vocabulary (rename):   {vocab}/{total}")
    print(f"  Encoding (compose):    {encoding}/{total}")
    print(f"  Ontology (new prim):   {ontology}/{total}")
    print()

    if ontology == 0 and encoding <= 2:
        print("VERDICT: Ontology survives intact.")
        print("  All FM constructs expressible with existing primitives.")
        print(f"  {vocab} constructs need renamed vocabulary.")
        print(f"  {encoding} constructs need better composition patterns.")
        print("  Zero new primitives required.")
    elif ontology <= 1:
        print("VERDICT: Ontology mostly survives (15% scenario).")
        print(f"  1 new primitive suggested by: {ontology} construct(s).")
    else:
        print("VERDICT: Ontology challenged (5% scenario).")
        print(f"  {ontology} constructs force new primitives.")

    print("=" * 72)
