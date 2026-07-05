"""Tests for CIRLab — CIR query lab and layer architecture.

Tests cover:
  1. CIRLab query templates work on FM CIR
  2. All 5 CIR layers have valid definitions
  3. Layer invariants hold
  4. Upward transitions navigate correctly
  5. CIR frontend compiler produces valid CIR
  6. Downward projections
  7. FMKB compilation yields expected structure
"""

import pytest

from studyplan.provenance.cir import assert_valid_ir
from studyplan.provenance.knowledge_ir import (
    FMFormula,
    FMPedagogicalSet,
    PedagogicalArtifact,
    FMKnowledgeBase,
    FMChapter,
    FormulaParam,
    Assumption,
)
from studyplan.provenance.lab.cir_frontend import (
    compile_formula,
    compile_knowledge_base,
    compile_pedagogical_set,
)
from studyplan.provenance.lab.cir_lab import CIRLab
from studyplan.provenance.lab.cir_layers import (
    CIR_LAYERS,
    CIR_ORDER,
    resolve_cir_layer,
    extract_cir_layer,
    layer_sequence,
)


# ============================================================
# FM formula fixtures
# ============================================================


@pytest.fixture
def wacc_formula():
    return FMFormula(
        concept_id="WACC",
        label="Weighted Average Cost of Capital",
        description="Enterprise cost of capital weighting debt and equity",
        expression="E/(E+D)*Re + D/(E+D)*Rd*(1-T)",
        params=(
            FormulaParam("E", kind="value", role="equity_value"),
            FormulaParam("D", kind="value", role="debt_value"),
            FormulaParam("Re", kind="percent", role="cost_of_equity"),
            FormulaParam("Rd", kind="percent", role="cost_of_debt"),
            FormulaParam("T", kind="percent", role="tax_rate"),
        ),
        output_concept_id="WACC.result",
        assumes=(
            Assumption("constant_capital_structure", "capital structure is constant"),
            Assumption("market_efficiency", "markets are efficient"),
        ),
        dependencies=("CAPM", "CostOfDebt"),
        diagnostic_tags=("core", "exam_favorite"),
        centrality=0.9,
    )


@pytest.fixture
def npv_formula():
    return FMFormula(
        concept_id="NPV",
        label="Net Present Value",
        description="Sum of discounted future cash flows minus initial investment",
        expression="sum(CF_t/(1+r)^t) - I0",
        params=(
            FormulaParam("CF_t", kind="value", role="cash_flow"),
            FormulaParam("r", kind="percent", role="discount_rate"),
            FormulaParam("I0", kind="value", role="initial_investment"),
        ),
        output_concept_id="NPV.result",
        assumes=(Assumption("constant_discount_rate", "discount rate is constant across periods"),),
        dependencies=("WACC", "TimeValueOfMoney"),
        centrality=0.95,
    )


@pytest.fixture
def fm_kb(wacc_formula, npv_formula):
    return FMKnowledgeBase(
        chapter=FMChapter(id="FM.Ch4", title="Investment Appraisal"),
        formulas={"WACC": wacc_formula, "NPV": npv_formula},
        pedagogical={
            "WACC": FMPedagogicalSet(
                concept_id="WACC",
                definitions=(
                    PedagogicalArtifact(
                        id="WACC.def.1",
                        kind="definition",
                        content="WACC is the weighted average of cost of equity and debt.",
                    ),
                ),
                worked_examples=(
                    PedagogicalArtifact(
                        id="WACC.we.1",
                        kind="worked_example",
                        content="Example: E=100, D=50, Re=10%, Rd=5%, T=30% → WACC=7.67%",
                    ),
                ),
                misconceptions=(
                    PedagogicalArtifact(
                        id="WACC.mis.1",
                        kind="misconception",
                        content="Common mistake: forgetting tax shield on debt.",
                    ),
                ),
            ),
        },
    )


@pytest.fixture
def wacc_ir(wacc_formula):
    return compile_formula(wacc_formula)


@pytest.fixture
def npv_ir(npv_formula):
    return compile_formula(npv_formula)


@pytest.fixture
def full_ir(fm_kb):
    return compile_knowledge_base(fm_kb)


@pytest.fixture
def lab(full_ir):
    return CIRLab(full_ir)


# ============================================================
# 1. CIR frontend compiler produces valid CIR
# ============================================================


def test_compile_formula_produces_valid_ir(wacc_ir):
    """compile_formula produces a valid CognitiveIR."""
    assert_valid_ir(wacc_ir)


def test_compile_formula_has_identities(wacc_ir):
    """Compiled WACC formula creates identity nodes."""
    ids = wacc_ir.identity_ids
    assert "WACC" in ids
    assert "WACC.concept" in ids


def test_compile_formula_has_artifacts(wacc_ir):
    """Compiled WACC formula creates artifact nodes for params and assumptions."""
    assert len(wacc_ir.artifacts) >= 2  # description + params + assumptions
    names = [a.id for a in wacc_ir.artifacts]
    assert "WACC.desc" in names
    assert any("param.E" in n for n in names)


def test_compile_formula_has_assumes_relations(wacc_ir):
    """Compiled WACC formula has assumes relations for dependencies."""
    rels = [(r.type, r.source, r.target) for r in wacc_ir.relations]
    assert ("assumes", "WACC", "CAPM") in rels
    assert ("assumes", "WACC", "CostOfDebt") in rels


def test_compile_formula_has_produces_relation(wacc_ir):
    """Compiled WACC formula has a produces relation."""
    rels = [(r.type, r.source, r.target) for r in wacc_ir.relations]
    assert ("produces", "WACC", "WACC.result") in rels


def test_compile_knowledge_base_merges(full_ir):
    """compile_knowledge_base merges multiple formulas."""
    assert_valid_ir(full_ir)
    assert "WACC" in full_ir.identity_ids
    assert "NPV" in full_ir.identity_ids
    assert "CAPM" in full_ir.identity_ids  # created as dep identity
    assert "TimeValueOfMoney" in full_ir.identity_ids


def test_compile_pedagogical_set_produces_valid_ir(fm_kb):
    """compile_pedagogical_set produces valid CIR."""
    pset = fm_kb.pedagogical["WACC"]
    ir = compile_pedagogical_set(pset, "WACC")
    assert_valid_ir(ir)


def test_compile_pedagogical_set_has_artifacts(fm_kb):
    """Pedagogical set creates artifact nodes with illustrates relations."""
    pset = fm_kb.pedagogical["WACC"]
    ir = compile_pedagogical_set(pset, "WACC")
    assert len(ir.artifacts) == 3  # def, we, mis
    assert len(ir.relations) == 3  # illustrates × 3


def test_compile_pedagogical_set_illustrates_relations(fm_kb):
    """Each pedagogical artifact has an illustrates relation to its concept."""
    pset = fm_kb.pedagogical["WACC"]
    ir = compile_pedagogical_set(pset, "WACC")
    for r in ir.relations:
        assert r.type == "illustrates"
        assert r.target == "WACC"


# ============================================================
# 2. CIRLab query templates
# ============================================================


def test_concept_inventory(lab):
    """Concept inventory lists all identity nodes."""
    result = lab.query("concept_inventory")
    ids = [i.id for i in result.data]
    assert "WACC" in ids
    assert "NPV" in ids
    assert result.summary["identity_count"] >= 4


def test_relation_inventory(lab):
    """Relation inventory lists all relations."""
    result = lab.query("relation_inventory")
    assert result.summary["relation_count"] >= 4
    types = result.summary["relation_types"]
    assert "assumes" in types
    assert "produces" in types


def test_artifact_inventory(lab):
    """Artifact inventory lists all artifact nodes."""
    result = lab.query("artifact_inventory")
    assert result.summary["artifact_count"] >= 2
    assert "definition" in result.summary["artifact_types"]


def test_concept_dependencies(lab):
    """Concept dependencies returns direct depends-on relations."""
    result = lab.query("concept_dependencies", concept_id="WACC")
    assert "CAPM" in result.data
    assert "CostOfDebt" in result.data
    assert result.summary["dependency_count"] == 2


def test_concept_dependencies_npv(lab):
    """NPV depends on WACC and TimeValueOfMoney."""
    result = lab.query("concept_dependencies", concept_id="NPV")
    assert "WACC" in result.data
    assert "TimeValueOfMoney" in result.data


def test_dependent_concepts(lab):
    """WACC has NPV as a dependent."""
    result = lab.query("dependent_concepts", concept_id="WACC")
    assert "NPV" in result.data


def test_artifact_coverage(lab):
    """Artifact coverage returns artifacts for a concept."""
    result = lab.query("artifact_coverage", concept_id="WACC")
    names = [a.id for a in result.data]
    assert "WACC.desc" in names
    assert any("param.E" in n for n in names)


def test_dependency_closure(lab):
    """Dependency closure for NPV includes transitive deps."""
    result = lab.query("dependency_closure", concept_id="NPV")
    closure = result.data
    assert "WACC" in closure
    assert "CAPM" in closure
    assert "CostOfDebt" in closure
    assert "TimeValueOfMoney" in closure
    assert "NPV" not in closure  # closure excludes the seed


def test_dependent_closure(lab):
    """Dependent closure includes all concepts relying on a given concept."""
    result = lab.query("dependent_closure", concept_id="CAPM")
    assert "WACC" in result.data
    assert "NPV" in result.data


def test_contradictions_empty(lab):
    """No contradictions in a freshly compiled IR."""
    result = lab.query("contradictions")
    assert result.summary["contradiction_count"] == 0


def test_unknown_query_raises(lab):
    """Unknown query method raises ValueError."""
    with pytest.raises(ValueError, match="Unknown CIR query"):
        lab.query("nonexistent_query")


# ============================================================
# 3. CIRLayer definitions are valid
# ============================================================


def test_all_layers_registered():
    """All 5 CIR layers are registered."""
    assert len(CIR_LAYERS) == 5
    assert CIR_ORDER == ["CIRL0", "CIRL1", "CIRL2", "CIRL3", "CIRL4"]


def test_each_layer_has_required_fields():
    """Each layer has name, invariant, canonical_query, check_invariant."""
    for name in CIR_ORDER:
        layer = resolve_cir_layer(name)
        assert layer.name == name
        assert isinstance(layer.invariant, str) and len(layer.invariant) > 0
        assert isinstance(layer.canonical_query, tuple) and len(layer.canonical_query) == 2
        assert callable(layer.check_invariant)
        assert callable(layer.upward_query)
        assert callable(layer.downward_projection)


def test_unknown_layer_raises():
    """resolve_cir_layer raises KeyError for unknown layers."""
    with pytest.raises(KeyError):
        resolve_cir_layer("CIRL5")
    with pytest.raises(KeyError):
        resolve_cir_layer("nonexistent")


def test_default_params_argument(lab):
    """CIRL3 default params are populated."""
    layer = resolve_cir_layer("CIRL3")
    _, params = layer.canonical_query
    assert isinstance(params, dict)


# ============================================================
# 4. Layer extraction
# ============================================================


@pytest.mark.parametrize("layer_name", ["CIRL0", "CIRL1", "CIRL2", "CIRL3", "CIRL4"])
def test_each_layer_extracts_successfully(lab, layer_name):
    """Each layer extracts successfully."""
    result = extract_cir_layer(lab, layer_name)
    assert result.summary["layer"] == layer_name
    assert result.summary["invariant_holds"] is True


def test_CIRL0_identities(lab):
    """CIRL0 returns all identity nodes."""
    result = extract_cir_layer(lab, "CIRL0")
    ids = [i.id for i in result.data]
    assert "WACC" in ids
    assert "NPV" in ids


def test_CIRL0_no_artifacts(lab):
    """CIRL0 (concept_inventory) returns no artifact information."""
    result = extract_cir_layer(lab, "CIRL0")
    for i in result.data:
        assert not hasattr(i, "content_preview")  # identities don't have content


def test_CIRL1_relations(lab):
    """CIRL1 returns all relations."""
    result = extract_cir_layer(lab, "CIRL1")
    assert len(result.data) >= 4


def test_CIRL2_artifacts(lab):
    """CIRL2 returns artifacts."""
    result = extract_cir_layer(lab, "CIRL2")
    assert len(result.data) >= 2


def test_CIRL3_closure_includes_transitive(lab):
    """CIRL3 transitive closure includes indirect dependencies."""
    result = extract_cir_layer(lab, "CIRL3")
    # Without a concept_id param, closure defaults to empty concept_id
    # Let's test with explicit param
    result2 = extract_cir_layer(lab, "CIRL3", concept_id="NPV")
    closure = result2.data
    assert "WACC" in closure
    assert "CAPM" in closure


def test_CIRL4_no_contradictions(lab):
    """CIRL4 finds no contradictions in clean IR."""
    result = extract_cir_layer(lab, "CIRL4")
    assert result.summary["contradiction_count"] == 0


# ============================================================
# 5. Upward transitions
# ============================================================


def test_upward_transition_CIRL0_to_CIRL1(lab):
    """CIRL0 → CIRL1: add relations."""
    results = layer_sequence(lab, "CIRL0", "CIRL1")
    assert len(results) == 2
    assert "transition_CIRL0_to_CIRL1" in results[1].annotations[0]


def test_upward_transition_CIRL1_to_CIRL2(lab):
    """CIRL1 → CIRL2: add artifacts."""
    results = layer_sequence(lab, "CIRL1", "CIRL2")
    assert len(results) == 2
    assert results[1].summary["from_layer"] == "CIRL1"
    assert results[1].summary["to_layer"] == "CIRL2"


def test_upward_transition_CIRL2_to_CIRL3(lab):
    """CIRL2 → CIRL3: add closure."""
    results = layer_sequence(lab, "CIRL2", "CIRL3")
    assert len(results) == 2


def test_upward_transition_CIRL3_to_CIRL4(lab):
    """CIRL3 → CIRL4: add contradictions."""
    results = layer_sequence(lab, "CIRL3", "CIRL4")
    assert len(results) == 2


def test_full_sequence_CIRL0_to_CIRL4(lab):
    """Navigate from most concrete (CIRL0) to most abstract (CIRL4)."""
    results = layer_sequence(lab, "CIRL0", "CIRL4")
    assert len(results) == 5  # 1 extract + 4 transitions
    assert "CIRL0" in results[0].summary.get("layer", "")
    assert results[-1].summary.get("to_layer") == "CIRL4"


def test_downward_navigation_raises(lab):
    """Navigating downward raises ValueError."""
    with pytest.raises(ValueError, match="Cannot navigate downward"):
        layer_sequence(lab, "CIRL4", "CIRL0")
    with pytest.raises(ValueError, match="Cannot navigate downward"):
        layer_sequence(lab, "CIRL3", "CIRL1")


# ============================================================
# 6. Downward projections
# ============================================================


def test_downward_CIRL0_projection(full_ir):
    """Downward to CIRL0 removes artifacts and relations."""
    layer = resolve_cir_layer("CIRL0")
    proj = layer.downward_projection(full_ir)
    assert len(proj.identities) == len(full_ir.identities)  # all identities preserved
    assert len(proj.artifacts) == 0
    assert len(proj.relations) == 0


def test_downward_CIRL1_projection(full_ir):
    """Downward to CIRL1 removes artifacts."""
    layer = resolve_cir_layer("CIRL1")
    proj = layer.downward_projection(full_ir)
    assert len(proj.identities) == len(full_ir.identities)
    assert len(proj.artifacts) == 0
    assert len(proj.relations) > 0  # relations kept


def test_downward_CIRL0_is_valid(full_ir):
    """Downward projection to CIRL0 is still valid CIR."""
    layer = resolve_cir_layer("CIRL0")
    proj = layer.downward_projection(full_ir)
    assert_valid_ir(proj)


def test_downward_CIRL1_is_valid(full_ir):
    """Downward projection to CIRL1 is still valid CIR."""
    layer = resolve_cir_layer("CIRL1")
    proj = layer.downward_projection(full_ir)
    assert_valid_ir(proj)


# ============================================================
# 7. CIRLab execute (custom fn)
# ============================================================


def test_execute_custom_fn(lab):
    """CIRLab.execute runs an arbitrary callable."""
    result = lab.execute(lambda ir: len(ir.identities))
    assert isinstance(result.data, int)
    assert result.data >= 4


def test_execute_custom_fn_with_params(lab):
    """CIRLab.execute passes params to the callable."""
    result = lab.execute(
        lambda ir, name: [i for i in ir.identities if i.id == name],
        name="WACC",
    )
    assert len(result.data) == 1
    assert result.data[0].label == "Weighted Average Cost of Capital"


# ============================================================
# 8. Ask alias
# ============================================================


def test_ask_alias(lab):
    """lab.ask is an alias for lab.query."""
    r1 = lab.ask("concept_inventory")
    r2 = lab.query("concept_inventory")
    assert len(r1.data) == len(r2.data)


# ============================================================
# 9. singleton formula compilation invariants
# ============================================================


def test_single_formula_has_identity_count(wacc_ir):
    """A single formula produces identity nodes (formula, concept, result, deps)."""
    assert len(wacc_ir.identities) == 5  # formula, concept, result, 2 deps


def test_single_formula_has_param_artifacts(wacc_ir):
    """Each parameter becomes an artifact."""
    param_count = 5  # E, D, Re, Rd, T
    found = sum(1 for a in wacc_ir.artifacts if "param" in a.id)
    assert found == param_count, f"Expected {param_count} param artifacts, got {found}"


def test_single_formula_has_assumption_artifacts(wacc_ir):
    """Each assumption becomes an artifact."""
    assumption_count = 2  # constant_capital_structure, market_efficiency
    found = sum(1 for a in wacc_ir.artifacts if "assumption" in a.id)
    assert found == assumption_count, f"Expected {assumption_count} assumption artifacts, got {found}"
