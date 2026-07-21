"""Tests for Cognitive IR (CIR) — type system, validation, and passes."""

from __future__ import annotations

import pytest

from studyplan.provenance.cir import (
    RELATION_TYPES,
    CIR_CURRENT_VERSION,
    Identity,
    Artifact,
    Relation,
    CognitiveIR,
    validate_ir,
    assert_valid_ir,
    resolve_identity_equivalence,
    collapse_duplicate_identities,
    normalize_artifact_links,
    detect_contradictions,
    run_passes,
)


# ====================================================================
# Type tests
# ====================================================================


class TestIdentity:
    def test_minimal(self):
        i = Identity(id="npv", type="formula")
        assert i.id == "npv"
        assert i.type == "formula"
        assert i.label == ""

    def test_with_label(self):
        i = Identity(id="npv", type="concept", label="Net Present Value")
        assert i.label == "Net Present Value"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid identity type"):
            Identity(id="x", type="widget")

    def test_frozen(self):
        i = Identity(id="npv", type="formula")
        with pytest.raises(AttributeError):
            i.id = "other"


class TestArtifact:
    def test_minimal(self):
        a = Artifact(id="def1", type="definition", target_identity="npv")
        assert a.id == "def1"
        assert a.target_identity == "npv"

    def test_with_optional_fields(self):
        a = Artifact(id="ex1", type="example", target_identity="irr", source_id="textbook")
        assert a.source_id == "textbook"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid artifact type"):
            Artifact(id="x", type="notebook", target_identity="npv")


class TestRelation:
    def test_valid_types(self):
        for rt in RELATION_TYPES:
            r = Relation(type=rt, source="a", target="b")
            assert r.type == rt

    def test_self_reference_raises(self):
        with pytest.raises(ValueError, match="Self-referencing"):
            Relation(type="assumes", source="x", target="x")

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid relation type"):
            Relation(type="depends_on", source="a", target="b")


# ====================================================================
# Container tests
# ====================================================================


class TestCognitiveIR:
    def test_empty(self):
        ir = CognitiveIR()
        assert ir.version == CIR_CURRENT_VERSION
        assert len(ir.identities) == 0

    def test_with_data(self):
        ir = CognitiveIR(
            identities=(Identity(id="a", type="concept"),),
            artifacts=(Artifact(id="a1", type="definition", target_identity="a"),),
            relations=(Relation(type="defines", source="a1", target="a"),),
        )
        assert ir.get_identity("a") is not None
        assert ir.get_artifact("a1") is not None
        assert len(ir.relations_for("a")) == 1

    def test_identity_ids(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="x", type="concept"),
                Identity(id="y", type="formula"),
            ),
        )
        assert ir.identity_ids == frozenset({"x", "y"})

    def test_all_ids(self):
        ir = CognitiveIR(
            identities=(Identity(id="x", type="concept"),),
            artifacts=(Artifact(id="x1", type="definition", target_identity="x"),),
        )
        assert ir.all_ids == frozenset({"x", "x1"})

    def test_get_identity_missing(self):
        ir = CognitiveIR()
        assert ir.get_identity("nonexistent") is None

    def test_artifacts_targeting(self):
        ir = CognitiveIR(
            identities=(Identity(id="npv", type="formula"),),
            artifacts=(
                Artifact(id="a1", type="definition", target_identity="npv"),
                Artifact(id="a2", type="example", target_identity="npv"),
                Artifact(id="a3", type="definition", target_identity="irr"),
            ),
        )
        targets = ir.artifacts_targeting("npv")
        assert len(targets) == 2
        assert {a.id for a in targets} == {"a1", "a2"}

    def test_relations_by_type(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="concept"),
            ),
            relations=(
                Relation(type="produces", source="a", target="b"),
                Relation(type="assumes", source="b", target="a"),
                Relation(type="produces", source="b", target="a"),
            ),
        )
        assert len(ir.relations_by_type("produces")) == 2
        assert len(ir.relations_by_type("assumes")) == 1

    def test_identities_by_type(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="formula"),
                Identity(id="c", type="concept"),
            ),
        )
        assert len(ir.identities_by_type("concept")) == 2
        assert len(ir.identities_by_type("formula")) == 1

    def test_frozen_container(self):
        ir = CognitiveIR()
        with pytest.raises(AttributeError):
            ir.identities = (Identity(id="x", type="concept"),)


# ====================================================================
# Validation tests
# ====================================================================


class TestValidateIR:
    def test_empty_is_valid(self):
        ir = CognitiveIR()
        result = validate_ir(ir)
        assert result.valid is True

    def test_valid_ir(self):
        ir = CognitiveIR(
            identities=(Identity(id="npv", type="formula"),),
            artifacts=(Artifact(id="d1", type="definition", target_identity="npv"),),
            relations=(Relation(type="defines", source="d1", target="npv"),),
        )
        result = validate_ir(ir)
        assert result.valid is True

    def test_duplicate_identity_id(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="x", type="concept"),
                Identity(id="x", type="formula"),
            ),
        )
        result = validate_ir(ir)
        assert result.valid is False
        assert any(e.rule == "V1" for e in result.errors)

    def test_duplicate_artifact_id(self):
        ir = CognitiveIR(
            identities=(Identity(id="x", type="concept"),),
            artifacts=(
                Artifact(id="a1", type="definition", target_identity="x"),
                Artifact(id="a1", type="example", target_identity="x"),
            ),
        )
        result = validate_ir(ir)
        assert result.valid is False
        assert any(e.rule == "V2" for e in result.errors)

    def test_artifact_targets_unknown_identity(self):
        ir = CognitiveIR(
            identities=(Identity(id="npv", type="formula"),),
            artifacts=(Artifact(id="a1", type="definition", target_identity="unknown"),),
        )
        result = validate_ir(ir)
        assert result.valid is False
        assert any(e.rule == "V3" for e in result.errors)

    def test_relation_source_not_found(self):
        ir = CognitiveIR(
            identities=(Identity(id="a", type="concept"),),
            relations=(Relation(type="produces", source="ghost", target="a"),),
        )
        result = validate_ir(ir)
        assert result.valid is False
        assert any(e.rule == "V4" for e in result.errors)

    def test_relation_target_not_found(self):
        ir = CognitiveIR(
            identities=(Identity(id="a", type="concept"),),
            relations=(Relation(type="assumes", source="a", target="ghost"),),
        )
        result = validate_ir(ir)
        assert result.valid is False
        assert any(e.rule == "V5" for e in result.errors)

    def test_invalid_version(self):
        ir = CognitiveIR(version=(1, 0))  # missing patch
        result = validate_ir(ir)
        assert result.valid is False
        assert any(e.rule == "V10" for e in result.errors)

    def test_invalid_version_negative(self):
        ir = CognitiveIR(version=(1, -1, 0))
        result = validate_ir(ir)
        assert result.valid is False

    def test_redundant_equivalent_to_warning(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="concept"),
            ),
            relations=(
                Relation(type="equivalent_to", source="a", target="b"),
                Relation(type="equivalent_to", source="b", target="a"),
            ),
        )
        result = validate_ir(ir)
        assert result.valid is True
        assert len(result.warnings) > 0
        assert any(w.rule == "V11" for w in result.warnings)

    def test_assert_valid_ir_passes(self):
        ir = CognitiveIR(identities=(Identity(id="x", type="concept"),))
        assert_valid_ir(ir)

    def test_assert_valid_ir_raises(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="x", type="concept"),
                Identity(id="x", type="formula"),
            ),
        )
        with pytest.raises(ValueError, match="CIR validation failed"):
            assert_valid_ir(ir)


# ====================================================================
# IR Pass tests
# ====================================================================


class TestResolveIdentityEquivalence:
    def test_no_equivalence_unchanged(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="formula"),
            ),
            relations=(Relation(type="produces", source="a", target="b"),),
        )
        result = resolve_identity_equivalence(ir)
        assert len(result.identities) == 2
        assert result.metadata.get("pass_resolve_identity_equivalence") is True

    def test_merge_two_equivalent(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="npv", type="formula", label="Net Present Value"),
                Identity(id="net_present_value", type="formula", label="NPV"),
            ),
            relations=(Relation(type="equivalent_to", source="npv", target="net_present_value"),),
        )
        result = resolve_identity_equivalence(ir)
        assert len(result.identities) == 1
        assert result.identities[0].id == "net_present_value"  # alphabetically first

    def test_relation_remapping(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="concept"),
                Identity(id="c", type="concept"),
            ),
            relations=(
                Relation(type="equivalent_to", source="a", target="b"),
                Relation(type="produces", source="c", target="a"),
            ),
        )
        result = resolve_identity_equivalence(ir)
        assert len(result.identities) == 2
        assert len(result.relations) == 1
        assert result.relations[0].target == "a"  # canonical = alphabetically first

    def test_artifact_remapping(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="concept"),
            ),
            artifacts=(Artifact(id="d1", type="definition", target_identity="a"),),
            relations=(Relation(type="equivalent_to", source="a", target="b"),),
        )
        result = resolve_identity_equivalence(ir)
        assert len(result.artifacts) == 1
        assert result.artifacts[0].target_identity == "a"  # canonical = alphabetically first

    def test_chain_of_equivalence(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="x", type="concept"),
                Identity(id="y", type="concept"),
                Identity(id="z", type="concept"),
            ),
            relations=(
                Relation(type="equivalent_to", source="x", target="y"),
                Relation(type="equivalent_to", source="y", target="z"),
            ),
        )
        result = resolve_identity_equivalence(ir)
        assert len(result.identities) == 1
        assert result.identities[0].id == "x"


class TestCollapseDuplicateIdentities:
    def test_no_duplicates_unchanged(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="npv", type="formula", label="NPV"),
                Identity(id="irr", type="formula", label="IRR"),
            ),
        )
        result = collapse_duplicate_identities(ir)
        assert len(result.identities) == 2

    def test_collapse_duplicate_label(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="npv", type="formula", label="Net Present Value"),
                Identity(id="npv_dup", type="formula", label="Net Present Value"),
            ),
        )
        result = collapse_duplicate_identities(ir)
        assert len(result.identities) == 1
        assert result.identities[0].id == "npv"

    def test_collapse_updates_artifact_target(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="keep", type="concept", label="TVM"),
                Identity(id="dup", type="concept", label="TVM"),
            ),
            artifacts=(Artifact(id="a1", type="definition", target_identity="dup"),),
        )
        result = collapse_duplicate_identities(ir)
        assert result.artifacts[0].target_identity == "keep"

    def test_empty_labels_not_collapsed(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept", label=""),
                Identity(id="b", type="concept", label=""),
            ),
        )
        result = collapse_duplicate_identities(ir)
        assert len(result.identities) == 2

    def test_case_insensitive_matching(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="npv", type="formula", label="Net Present Value"),
                Identity(id="npv2", type="formula", label="net present value"),
            ),
        )
        result = collapse_duplicate_identities(ir)
        assert len(result.identities) == 1


class TestNormalizeArtifactLinks:
    def test_valid_artifacts_unchanged(self):
        ir = CognitiveIR(
            identities=(Identity(id="npv", type="formula"),),
            artifacts=(Artifact(id="d1", type="definition", target_identity="npv"),),
        )
        result = normalize_artifact_links(ir)
        assert len(result.artifacts) == 1

    def test_removes_dangling_artifact(self):
        ir = CognitiveIR(
            identities=(Identity(id="npv", type="formula"),),
            artifacts=(
                Artifact(id="d1", type="definition", target_identity="npv"),
                Artifact(id="d2", type="example", target_identity="unknown"),
            ),
        )
        result = normalize_artifact_links(ir)
        assert len(result.artifacts) == 1
        assert result.metadata.get("normalize_artifact_links_removed") == 1

    def test_metadata_tracks_removal(self):
        ir = CognitiveIR(
            artifacts=(Artifact(id="d1", type="definition", target_identity="ghost"),),
        )
        result = normalize_artifact_links(ir)
        assert result.metadata.get("normalize_artifact_links_removed") == 1


class TestDetectContradictions:
    def test_no_contradictions(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="concept"),
            ),
        )
        result = detect_contradictions(ir)
        assert result.metadata.get("contradiction_count") == 0

    def test_detects_contradiction(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept", label="Theory A"),
                Identity(id="b", type="concept", label="Theory B"),
            ),
            relations=(Relation(type="contradicts", source="a", target="b"),),
        )
        result = detect_contradictions(ir)
        assert result.metadata.get("contradiction_count") == 1
        assert len(result.metadata.get("contradictions", [])) == 1

    def test_multiple_contradictions(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="concept"),
                Identity(id="c", type="concept"),
            ),
            relations=(
                Relation(type="contradicts", source="a", target="b"),
                Relation(type="contradicts", source="b", target="c"),
            ),
        )
        result = detect_contradictions(ir)
        assert result.metadata.get("contradiction_count") == 2

    def test_contradiction_metadata_has_labels(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept", label="Efficient Market"),
                Identity(id="b", type="concept", label="Behavioral Finance"),
            ),
            relations=(Relation(type="contradicts", source="a", target="b"),),
        )
        result = detect_contradictions(ir)
        c = result.metadata["contradictions"][0]
        assert c["source_label"] == "Efficient Market"
        assert c["target_label"] == "Behavioral Finance"


# ====================================================================
# Pipeline tests
# ====================================================================


class TestRunPasses:
    def test_default_pipeline(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="a", type="concept"),
                Identity(id="b", type="concept", label="Duplicate"),
                Identity(id="c", type="concept", label="Duplicate"),
            ),
            relations=(Relation(type="equivalent_to", source="a", target="b"),),
        )
        result = run_passes(ir)
        assert result.metadata.get("pass_resolve_identity_equivalence") is True
        assert result.metadata.get("pass_collapse_duplicate_identities") is True
        assert result.metadata.get("pass_normalize_artifact_links") is True
        assert result.metadata.get("pass_detect_contradictions") is True

    def test_custom_pass_order(self):
        ir = CognitiveIR(identities=(Identity(id="a", type="concept"),))
        result = run_passes(ir, passes=["detect_contradictions"])
        assert result.metadata.get("pass_detect_contradictions") is True

    def test_pipeline_output_is_valid(self):
        ir = CognitiveIR(
            identities=(
                Identity(id="npv", type="formula"),
                Identity(id="net_present_value", type="formula"),
            ),
            relations=(Relation(type="equivalent_to", source="npv", target="net_present_value"),),
        )
        result = run_passes(ir)
        validation = validate_ir(result)
        assert validation.valid is True

    def test_full_contradiction_contradicts_unchanged(self):
        """Test that contradicts relations survive the pipeline."""
        ir = CognitiveIR(
            identities=(
                Identity(id="theory_a", type="concept"),
                Identity(id="theory_b", type="concept"),
            ),
            relations=(Relation(type="contradicts", source="theory_a", target="theory_b"),),
        )
        result = run_passes(ir)
        assert result.metadata.get("contradiction_count") == 1


# ====================================================================
# End-to-end: FM IR → CIR compilation
# ====================================================================


class TestCIRCompilation:
    def test_compile_fm_formula_to_cir(self):
        from studyplan.provenance.knowledge_ir import FMFormula, FormulaParam

        formula = FMFormula(
            concept_id="fm.npv",
            label="NPV",
            description="Net Present Value",
            expression="sum(...)",
            params=(FormulaParam("initial", "value", "init"),),
            output_concept_id="fm.npv",
            dependencies=("fm.capm",),
            diagnostic_tags=("sign_error",),
        )

        ir = _compile_formula(formula)
        val = validate_ir(ir)
        assert val.valid is True, val.errors

        ids = {i.id for i in ir.identities}
        assert "fm.npv" in ids
        assert "fm.npv.formula" in ids
        assert "fm.capm" in ids

    def test_compile_multiple_formulas(self):
        from studyplan.provenance.knowledge_ir import FMFormula

        npv = FMFormula(
            concept_id="fm.npv",
            label="NPV",
            description="",
            expression="sum(...)",
            params=(),
            output_concept_id="fm.npv",
            dependencies=("fm.capm",),
        )
        capm = FMFormula(
            concept_id="fm.capm",
            label="CAPM",
            description="",
            expression="rf + b*(rm - rf)",
            params=(),
            output_concept_id="fm.capm",
        )

        merged = CognitiveIR()
        for f in (npv, capm):
            merged = _merge_ir(merged, _compile_formula(f))

        val = validate_ir(merged)
        assert val.valid is True
        assert "fm.npv" in merged.identity_ids
        assert "fm.capm" in merged.identity_ids

    def test_assumptions_become_artifacts(self):
        from studyplan.provenance.knowledge_ir import FMFormula, Assumption

        formula = FMFormula(
            concept_id="fm.wacc",
            label="WACC",
            description="",
            expression="E/V*Re + D/V*Rd*(1-T)",
            params=(),
            output_concept_id="fm.wacc",
            assumes=(
                Assumption("constant_capital_structure", "Capital structure is constant"),
                Assumption("market_efficiency", "Markets are efficient"),
            ),
        )
        ir = _compile_formula(formula)
        assumption_artifacts = [a for a in ir.artifacts if a.type == "definition"]
        assert len(assumption_artifacts) == 2

    def test_pipeline_on_compiled_ir(self):
        from studyplan.provenance.knowledge_ir import FMFormula

        npv = FMFormula(
            concept_id="fm.npv",
            label="NPV",
            description="",
            expression="",
            params=(),
            output_concept_id="fm.npv",
            dependencies=("fm.capm",),
        )

        ir = _compile_formula(npv)
        result = run_passes(ir)
        val = validate_ir(result)
        assert val.valid is True


# ====================================================================
# Helpers for CIR compilation tests
# ====================================================================


def _compile_formula(f: FMFormula) -> CognitiveIR:
    """Compile an FMFormula into CIR."""
    from studyplan.provenance.cir import Identity as CIRIdentity
    from studyplan.provenance.cir import Artifact as CIRArtifact
    from studyplan.provenance.cir import Relation as CIRRelation

    identities: list[CIRIdentity] = [
        CIRIdentity(id=f.concept_id, type="formula", label=f.label),
        CIRIdentity(id=f"{f.concept_id}.formula", type="concept", label=f"{f.label} concept"),
    ]

    seen_ids = {i.id for i in identities}

    def _ensure_identity(dep_id: str) -> None:
        if dep_id not in seen_ids:
            identities.append(CIRIdentity(id=dep_id, type="formula", label=dep_id))
            seen_ids.add(dep_id)

    artifacts: list[CIRArtifact] = []
    if f.description:
        artifacts.append(
            CIRArtifact(
                id=f"{f.concept_id}.desc",
                type="definition",
                target_identity=f.concept_id,
                content_preview=f.description[:200],
            )
        )

    for param in f.params:
        artifacts.append(
            CIRArtifact(
                id=f"{f.concept_id}.param.{param.name}",
                type="definition",
                target_identity=f.concept_id,
                content_preview=f"{param.name}: {param.role}",
            )
        )

    for assump in f.assumes:
        artifacts.append(
            CIRArtifact(
                id=f"{f.concept_id}.assumption.{assump.condition}",
                type="definition",
                target_identity=f.concept_id,
                content_preview=assump.condition,
            )
        )

    relations: list[CIRRelation] = []
    if f.concept_id != f.output_concept_id:
        relations.append(CIRRelation(type="produces", source=f.concept_id, target=f.output_concept_id))
    for dep in f.dependencies:
        _ensure_identity(dep)
        relations.append(CIRRelation(type="assumes", source=f.concept_id, target=dep))

    return CognitiveIR(
        identities=tuple(identities),
        artifacts=tuple(artifacts),
        relations=tuple(relations),
    )


def _merge_ir(a: CognitiveIR, b: CognitiveIR) -> CognitiveIR:
    """Merge two CIR containers, deduplicating identities by ID."""
    seen_ids = a.identity_ids
    identities = list(a.identities)
    for i in b.identities:
        if i.id not in seen_ids:
            identities.append(i)
            seen_ids |= {i.id}
    return CognitiveIR(
        identities=tuple(identities),
        artifacts=a.artifacts + b.artifacts,
        relations=a.relations + b.relations,
        metadata={**a.metadata, **b.metadata},
    )
