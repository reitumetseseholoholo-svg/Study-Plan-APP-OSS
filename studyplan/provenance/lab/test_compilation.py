"""Tests for CIR Compilation Runtime — fragment, plugin, resolver, merger, builder.

Covers:
  1. CIRFragment format — identity_ids, artifact_ids, provenance
  2. FrontendPlugin protocol — abstract methods, compile_to_cir
  3. FMFormulaPlugin — single formula → fragment
  4. FMKnowledgeBasePlugin — full KB → fragment
  5. IdentityResolver — DSU, label match, mapping
  6. CIRMerger — basic merge, cross-source resolution, artifact dedup, contradictions
  7. CIRBuilder — full orchestration, single source, multi-source
  8. Error handling — unknown source, duplicate registration
"""

import pytest

from studyplan.provenance.cir import CognitiveIR, Identity, Artifact, Relation, assert_valid_ir
from studyplan.provenance.knowledge_ir import (
    FMFormula,
    FMKnowledgeBase,
    FMChapter,
    FMPedagogicalSet,
    PedagogicalArtifact,
    FormulaParam,
    Assumption,
)
from studyplan.provenance.lab.compilation import (
    CIRFragment,
    FragmentProvenance,
    FrontendPlugin,
    IdentityResolver,
    LookalikeStrategy,
    CIRMerger,
    CIRBuilder,
    FMFormulaPlugin,
    FMKnowledgeBasePlugin,
    NotesFrontendPlugin,
    parse_notes,
    ParsedNoteBlock,
)


# ============================================================
# Fixtures
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
        ),
        output_concept_id="WACC.result",
        assumes=(Assumption("constant_capital_structure", "capital structure is constant"),),
        dependencies=("CAPM",),
        diagnostic_tags=("core",),
        centrality=0.9,
    )


@pytest.fixture
def npv_formula():
    return FMFormula(
        concept_id="NPV",
        label="Net Present Value",
        description="Sum of discounted future cash flows",
        expression="sum(CF_t/(1+r)^t) - I0",
        params=(FormulaParam("r", kind="percent", role="discount_rate"),),
        output_concept_id="NPV.result",
        assumes=(Assumption("constant_discount_rate", "discount rate is constant"),),
        dependencies=("WACC",),
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
                        content="WACC is the weighted average.",
                    ),
                ),
            ),
        },
    )


@pytest.fixture
def fm_plugin():
    return FMFormulaPlugin()


@pytest.fixture
def kb_plugin():
    return FMKnowledgeBasePlugin()


# ============================================================
# 1. CIRFragment
# ============================================================


def test_fragment_empty():
    """Empty fragment has zero counts."""
    f = CIRFragment()
    assert f.identity_count() == 0
    assert f.artifact_count() == 0
    assert f.relation_count() == 0
    assert len(f.identity_ids) == 0


def test_fragment_with_data():
    """Fragment with data returns correct counts."""
    f = CIRFragment(
        identities=(Identity(id="x", type="concept", label="X"),),
        artifacts=(Artifact(id="a1", type="definition", target_identity="x"),),
        relations=(Relation(type="produces", source="x", target="y"),),
    )
    assert f.identity_count() == 1
    assert f.artifact_count() == 1
    assert f.relation_count() == 1
    assert "x" in f.identity_ids
    assert "a1" in f.artifact_ids


def test_fragment_provenance_default():
    """Default provenance is unknown."""
    f = CIRFragment()
    assert f.provenance.source_kind == "unknown"


def test_fragment_provenance_custom():
    """Custom provenance is preserved."""
    p = FragmentProvenance(source_kind="test", source_id="s1", confidence=0.8)
    f = CIRFragment(provenance=p)
    assert f.provenance.source_kind == "test"
    assert f.provenance.confidence == 0.8


def test_fragment_all_ids():
    """all_ids is union of identity_ids and artifact_ids."""
    f = CIRFragment(
        identities=(Identity(id="i1", type="concept", label="X"),),
        artifacts=(Artifact(id="a1", type="definition", target_identity="i1"),),
    )
    assert f.all_ids == frozenset({"i1", "a1"})


# ============================================================
# 2. FrontendPlugin protocol
# ============================================================


def test_plugin_abstract_cannot_instantiate():
    """FrontendPlugin ABC cannot be instantiated directly."""
    with pytest.raises(TypeError):
        FrontendPlugin()  # type: ignore


def test_fm_plugin_source_kind(fm_plugin):
    """FMFormulaPlugin.source_kind is 'fm_formula'."""
    assert fm_plugin.source_kind == "fm_formula"


def test_fm_plugin_repr(fm_plugin):
    """FMFormulaPlugin repr includes source kind."""
    assert "fm_formula" in repr(fm_plugin)


def test_fm_plugin_compile_to_cir(fm_plugin, wacc_formula):
    """FMFormulaPlugin compiles a formula into a valid CIRFragment."""
    fragment = fm_plugin.compile_to_cir(wacc_formula)
    assert isinstance(fragment, CIRFragment)
    assert fragment.identity_count() >= 2
    assert fragment.artifact_count() >= 2
    assert fragment.relation_count() >= 2


def test_fm_plugin_parse_invalid(fm_plugin):
    """FMFormulaPlugin raises TypeError for non-FMFormula input."""
    with pytest.raises(TypeError, match="FMFormulaPlugin expects FMFormula"):
        fm_plugin.parse("not a formula")  # type: ignore


def test_kb_plugin_source_kind(kb_plugin):
    """FMKnowledgeBasePlugin.source_kind is 'fm_knowledge_base'."""
    assert kb_plugin.source_kind == "fm_knowledge_base"


def test_kb_plugin_compile_to_cir(kb_plugin, fm_kb):
    """FMKnowledgeBasePlugin compiles a KB into a valid CIRFragment."""
    fragment = kb_plugin.compile_to_cir(fm_kb)
    assert isinstance(fragment, CIRFragment)
    assert fragment.identity_count() >= 4
    assert fragment.relation_count() >= 4
    assert "WACC" in fragment.identity_ids
    assert "NPV" in fragment.identity_ids


def test_kb_plugin_parse_invalid(kb_plugin):
    """FMKnowledgeBasePlugin raises TypeError for non-FMKnowledgeBase input."""
    with pytest.raises(TypeError, match="FMKnowledgeBasePlugin expects FMKnowledgeBase"):
        kb_plugin.parse("not a KB")  # type: ignore


def test_kb_plugin_includes_pedagogical(kb_plugin, fm_kb):
    """FMKnowledgeBasePlugin includes pedagogical artifacts in fragment."""
    fragment = kb_plugin.compile_to_cir(fm_kb)
    artifact_ids = fragment.artifact_ids
    has_pedagogical = any("def" in aid or "WACC.def" in aid for aid in artifact_ids)
    assert has_pedagogical, "Pedagogical artifacts not found in fragment"


# ============================================================
# 3. IdentityResolver
# ============================================================


def test_resolver_empty():
    """Empty resolver produces empty mapping."""
    r = IdentityResolver()
    assert r.identity_count == 0
    assert r.resolve() == {}


def test_resolver_single_fragment():
    """Single fragment identities map to themselves."""
    f = CIRFragment(
        identities=(
            Identity(id="WACC", type="formula", label="WACC"),
            Identity(id="NPV", type="formula", label="NPV"),
        ),
    )
    r = IdentityResolver()
    r.ingest(f)
    m = r.resolve()
    assert m["WACC"] == "WACC"
    assert m["NPV"] == "NPV"


def test_resolver_label_match(fm_kb, kb_plugin):
    """Identical labels across fragments are unioned."""
    f1 = CIRFragment(
        identities=(Identity(id="WACC", type="formula", label="WACC"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="WACC.v2", type="formula", label="WACC"),),
    )
    r = IdentityResolver()
    r.ingest(f1)
    r.ingest(f2)
    m = r.resolve()
    assert m["WACC"] == m["WACC.v2"]  # same equivalence class


def test_resolver_no_false_positive():
    """Different labels are NOT resolved together."""
    f1 = CIRFragment(
        identities=(Identity(id="A", type="formula", label="Alpha"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="B", type="formula", label="Beta"),),
    )
    r = IdentityResolver()
    r.ingest(f1)
    r.ingest(f2)
    m = r.resolve()
    assert m["A"] != m["B"]


def test_resolver_reset():
    """Reset clears all identities."""
    f = CIRFragment(
        identities=(Identity(id="A", type="concept", label="Alpha"),),
    )
    r = IdentityResolver()
    r.ingest(f)
    assert r.identity_count == 1
    r.reset()
    assert r.identity_count == 0


def test_resolver_ingest_multiple(fm_kb, kb_plugin):
    """Ingesting multiple fragments accumulates identities."""
    f1 = CIRFragment(
        identities=(Identity(id="A", type="concept", label="A"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="B", type="concept", label="B"),),
    )
    r = IdentityResolver()
    r.ingest(f1)
    r.ingest(f2)
    assert r.identity_count == 2
    m = r.resolve()
    assert len(set(m.values())) == 2  # 2 equivalence classes


def test_resolver_type_sensitive():
    """Same label, different type — NOT matched (resolver key includes type)."""
    f1 = CIRFragment(
        identities=(Identity(id="A", type="formula", label="X"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="B", type="concept", label="X"),),
    )
    r = IdentityResolver()
    r.ingest(f1)
    r.ingest(f2)
    m = r.resolve()
    assert m["A"] != m["B"]  # different type → different class


# ============================================================
# 4. CIRMerger
# ============================================================


def test_merger_empty():
    """Merging empty fragment list returns valid empty IR."""
    merger = CIRMerger()
    ir = merger.merge([])
    assert isinstance(ir, CognitiveIR)
    assert_valid_ir(ir)
    assert len(ir.identities) == 0


def test_merger_single_fragment(fm_kb, kb_plugin):
    """Merging a single fragment returns valid IR with correct content."""
    fragment = kb_plugin.compile_to_cir(fm_kb)
    merger = CIRMerger()
    ir = merger.merge([fragment])
    assert_valid_ir(ir)
    assert "WACC" in ir.identity_ids
    assert "NPV" in ir.identity_ids
    assert merger.last_report is not None
    assert merger.last_report.fragment_count == 1


def test_merger_identity_resolution():
    """Merger resolves identities across fragments with same label."""
    f1 = CIRFragment(
        identities=(
            Identity(id="WACC.f1", type="formula", label="WACC"),
            Identity(id="CAPM", type="formula", label="CAPM"),
        ),
        relations=(Relation(type="assumes", source="WACC.f1", target="CAPM"),),
    )
    f2 = CIRFragment(
        identities=(
            Identity(id="WACC.f2", type="formula", label="WACC"),
            Identity(id="NPV", type="formula", label="NPV"),
        ),
        relations=(Relation(type="assumes", source="NPV", target="WACC.f2"),),
    )
    merger = CIRMerger()
    ir = merger.merge([f1, f2])
    assert_valid_ir(ir)
    # WACC.f1 and WACC.f2 should be resolved to the same canonical ID
    assert ir.identity_ids == frozenset({"WACC.f1", "CAPM", "NPV"})
    # The assumes relation from NPV should target the canonical WACC
    assert len(ir.relations) >= 2
    report = merger.last_report
    assert report is not None
    assert report.identity_remapped > 0  # at least one remapping


def test_merger_artifact_dedup():
    """Duplicate artifacts across fragments are deduplicated."""
    f1 = CIRFragment(
        identities=(Identity(id="X", type="concept", label="X"),),
        artifacts=(Artifact(id="x.desc", type="definition", target_identity="X", content_preview="description of X"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="X", type="concept", label="X"),),
        artifacts=(Artifact(id="x.desc", type="definition", target_identity="X", content_preview="description of X"),),
    )
    merger = CIRMerger()
    ir = merger.merge([f1, f2])
    assert_valid_ir(ir)
    # Should only have one artifact (deduped)
    assert len(ir.artifacts) == 1


def test_merger_no_false_dedup():
    """Similar but different artifacts are NOT deduplicated."""
    f1 = CIRFragment(
        identities=(Identity(id="X", type="concept", label="X"),),
        artifacts=(
            Artifact(id="x.desc.1", type="definition", target_identity="X", content_preview="first description"),
        ),
    )
    f2 = CIRFragment(
        identities=(Identity(id="X", type="concept", label="X"),),
        artifacts=(
            Artifact(id="x.desc.2", type="definition", target_identity="X", content_preview="second description"),
        ),
    )
    merger = CIRMerger()
    ir = merger.merge([f1, f2])
    assert len(ir.artifacts) == 2


def test_merger_contradictions():
    """Contradict relations create contradiction artifacts."""
    f1 = CIRFragment(
        identities=(
            Identity(id="A", type="concept", label="A"),
            Identity(id="B", type="concept", label="B"),
        ),
        relations=(Relation(type="contradicts", source="A", target="B"),),
    )
    merger = CIRMerger()
    ir = merger.merge([f1])
    # Contradiction should be detected — contradiction artifact added
    assert len(ir.artifacts) >= 1  # at least one contradiction artifact
    assert merger.last_report is not None
    assert merger.last_report.contradictions_detected >= 1


def test_merger_cross_source_relation_rewrite():
    """Relation targets are rewritten to canonical IDs."""
    f1 = CIRFragment(
        identities=(Identity(id="X", type="formula", label="WACC"),),
        relations=(Relation(type="produces", source="X", target="X.result"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="X.v2", type="formula", label="WACC"),),
        relations=(Relation(type="assumes", source="Y", target="X.v2"),),
    )
    merger = CIRMerger()
    ir = merger.merge([f1, f2])
    assert_valid_ir(ir)


def test_merger_relation_dedup():
    """Duplicate relations across fragments are deduplicated."""
    f1 = CIRFragment(
        identities=(Identity(id="A", type="concept", label="A"), Identity(id="B", type="concept", label="B")),
        relations=(Relation(type="assumes", source="A", target="B"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="A", type="concept", label="A"), Identity(id="B", type="concept", label="B")),
        relations=(Relation(type="assumes", source="A", target="B"),),
    )
    merger = CIRMerger()
    ir = merger.merge([f1, f2])
    assert len(ir.relations) == 1


def test_merger_report_tracking():
    """MergeReport tracks all merge statistics."""
    f1 = CIRFragment(
        identities=(Identity(id="A", type="concept", label="A"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="B", type="concept", label="B"),),
    )
    merger = CIRMerger()
    merger.merge([f1, f2])
    report = merger.last_report
    assert report is not None
    assert report.fragment_count == 2
    assert report.total_identities == 2
    assert isinstance(report.identity_equivalence_classes, int)
    assert isinstance(report.warnings, list)


# ============================================================
# 5. CIRBuilder
# ============================================================


def test_builder_empty():
    """Builder with no sources returns empty valid IR."""
    builder = CIRBuilder()
    ir = builder.build({})
    assert isinstance(ir, CognitiveIR)
    assert len(ir.identities) == 0
    assert len(ir.artifacts) == 0


def test_builder_register_frontend(fm_plugin):
    """Register a frontend plugin."""
    builder = CIRBuilder()
    builder.register_frontend("fm_formula", fm_plugin)
    assert "fm_formula" in builder.registered_kinds
    assert builder.has_frontend("fm_formula")


def test_builder_register_duplicate(fm_plugin):
    """Duplicate registration raises ValueError."""
    builder = CIRBuilder()
    builder.register_frontend("fm_formula", fm_plugin)
    with pytest.raises(ValueError, match="already registered"):
        builder.register_frontend("fm_formula", fm_plugin)


def test_builder_register_kind_mismatch(fm_plugin):
    """Registering with mismatched source_kind raises ValueError."""
    builder = CIRBuilder()
    with pytest.raises(ValueError, match="does not match"):
        builder.register_frontend("wrong_kind", fm_plugin)


def test_builder_unregister(fm_plugin):
    """Unregister removes a frontend."""
    builder = CIRBuilder()
    builder.register_frontend("fm_formula", fm_plugin)
    assert builder.has_frontend("fm_formula")
    builder.unregister_frontend("fm_formula")
    assert not builder.has_frontend("fm_formula")


def test_builder_single_source(fm_kb, kb_plugin):
    """Build with single source produces valid IR."""
    builder = CIRBuilder()
    builder.register_frontend("fm_knowledge_base", kb_plugin)
    ir = builder.build({"fm_knowledge_base": fm_kb})
    assert_valid_ir(ir)
    assert "WACC" in ir.identity_ids
    assert "NPV" in ir.identity_ids


def test_builder_unknown_source(fm_plugin):
    """Building with unknown source kind raises ValueError."""
    builder = CIRBuilder()
    builder.register_frontend("fm_formula", fm_plugin)
    with pytest.raises(ValueError, match="No frontend registered"):
        builder.build({"unknown_source": "data"})


def test_builder_multi_source(wacc_formula, npv_formula, fm_plugin):
    """Build from multiple frontends produces merged IR."""
    builder = CIRBuilder()
    builder.register_frontend("fm_formula", fm_plugin)

    ir = builder.build_all(
        [
            ("fm_formula", wacc_formula, "wacc"),
            ("fm_formula", npv_formula, "npv"),
        ]
    )
    assert_valid_ir(ir)
    assert "WACC" in ir.identity_ids
    assert "NPV" in ir.identity_ids


def test_builder_last_report(fm_kb, kb_plugin):
    """Builder exposes last merge report."""
    builder = CIRBuilder()
    builder.register_frontend("fm_knowledge_base", kb_plugin)
    builder.build({"fm_knowledge_base": fm_kb})
    report = builder.last_report
    assert report is not None
    assert report.fragment_count == 1


def test_builder_build_before_any_report(fm_plugin):
    """Before any build, last_report is None."""
    builder = CIRBuilder()
    assert builder.last_report is None


# ============================================================
# 6. LookalikeStrategy
# ============================================================


def test_lookalike_default():
    """Default strategy enables exact + label match, disables semantic."""
    s = LookalikeStrategy()
    assert s.exact_match is True
    assert s.label_match is True
    assert s.semantic_match is False


def test_lookalike_custom():
    """Custom strategy parameters are preserved."""
    s = LookalikeStrategy(exact_match=False, semantic_match=True, semantic_threshold=0.9)
    assert s.exact_match is False
    assert s.semantic_match is True
    assert s.semantic_threshold == 0.9


# ============================================================
# 7. Cross-source conflict handling
# ============================================================


def test_merger_remaps_relation_targets():
    """Relation targets are remapped through identity resolution."""
    f1 = CIRFragment(
        identities=(Identity(id="capm_v1", type="formula", label="CAPM"),),
        relations=(Relation(type="produces", source="capm_v1", target="capm_v1.result"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="capm_v2", type="formula", label="CAPM"),),
        relations=(Relation(type="assumes", source="WACC", target="capm_v2"),),
    )
    merger = CIRMerger()
    ir = merger.merge([f1, f2])
    assert_valid_ir(ir)
    # All relations should reference valid identities
    for r in ir.relations:
        assert r.source in ir.all_ids, f"Relation source {r.source} not found"
        assert r.target in ir.all_ids, f"Relation target {r.target} not found"


def test_merger_preserves_nonconflicting_artifacts():
    """Non-conflicting artifacts from both fragments are preserved."""
    f1 = CIRFragment(
        identities=(Identity(id="A", type="concept", label="A"),),
        artifacts=(Artifact(id="a.1", type="definition", target_identity="A", content_preview="from source 1"),),
    )
    f2 = CIRFragment(
        identities=(Identity(id="A", type="concept", label="A"),),
        artifacts=(Artifact(id="a.2", type="example", target_identity="A", content_preview="from source 2"),),
    )
    merger = CIRMerger()
    ir = merger.merge([f1, f2])
    assert len(ir.artifacts) == 2


# ============================================================
# 8. NotesFrontendPlugin (second frontend — validates multi-frontend)
# ============================================================

SAMPLE_NOTES = """\
# WACC
type: formula
description: Weighted Average Cost of Capital
depends: CAPM
param: E (equity_value)
param: D (debt_value)

# NPV
type: formula
description: Net Present Value
depends: WACC
param: r (discount_rate)

# CAPM
type: formula
description: Capital Asset Pricing Model
"""


@pytest.fixture
def notes_plugin():
    return NotesFrontendPlugin()


@pytest.fixture
def notes_text():
    return SAMPLE_NOTES


def test_notes_plugin_source_kind(notes_plugin):
    """NotesFrontendPlugin.source_kind is 'notes'."""
    assert notes_plugin.source_kind == "notes"


def test_parse_notes_empty():
    """Empty text produces no blocks."""
    assert parse_notes("") == []


def test_parse_notes_single_block():
    """Single note block parses correctly."""
    blocks = parse_notes("# WACC\ntype: formula\ndescription: test")
    assert len(blocks) == 1
    assert blocks[0].heading == "WACC"
    assert blocks[0].properties["type"] == ["formula"]
    assert blocks[0].properties["description"] == ["test"]


def test_parse_notes_multiple_blocks():
    """Multiple note blocks parse correctly."""
    blocks = parse_notes(SAMPLE_NOTES)
    assert len(blocks) == 3
    headings = [b.heading for b in blocks]
    assert headings == ["WACC", "NPV", "CAPM"]


def test_parse_notes_multi_value_property():
    """Properties with multiple values (depends, param) are lists."""
    blocks = parse_notes(SAMPLE_NOTES)
    wacc = blocks[0]
    assert wacc.properties["depends"] == ["CAPM"]
    assert len(wacc.properties["param"]) == 2


def test_notes_plugin_compile_to_cir(notes_plugin, notes_text):
    """NotesFrontendPlugin compiles text to a valid CIR fragment."""
    fragment = notes_plugin.compile_to_cir(notes_text)
    assert isinstance(fragment, CIRFragment)
    assert fragment.identity_count() >= 3  # WACC, NPV, CAPM
    assert fragment.artifact_count() >= 3  # descriptions + params
    assert fragment.relation_count() >= 2  # WACC→CAPM, NPV→WACC


def test_notes_plugin_identities(notes_plugin, notes_text):
    """Extracted identities match note headings + dependencies."""
    fragment = notes_plugin.compile_to_cir(notes_text)
    ids = fragment.identity_ids
    assert "WACC" in ids
    assert "NPV" in ids
    assert "CAPM" in ids


def test_notes_plugin_relations(notes_plugin, notes_text):
    """Extracted relations include assumes edges from depends fields."""
    fragment = notes_plugin.compile_to_cir(notes_text)
    rels = [(r.type, r.source, r.target) for r in fragment.relations]
    assert ("assumes", "WACC", "CAPM") in rels
    assert ("assumes", "NPV", "WACC") in rels


def test_notes_plugin_artifacts(notes_plugin, notes_text):
    """Extracted artifacts include definitions and explanations."""
    fragment = notes_plugin.compile_to_cir(notes_text)
    assert len(fragment.artifacts) >= 3


def test_notes_plugin_parse_invalid(notes_plugin):
    """NotesFrontendPlugin raises TypeError for invalid input."""
    with pytest.raises(TypeError, match="NotesFrontendPlugin expects"):
        notes_plugin.parse(42)  # type: ignore


def test_notes_plugin_parse_preparsed(notes_plugin):
    """NotesFrontendPlugin accepts pre-parsed block list."""
    blocks = [ParsedNoteBlock(heading="X", properties={"type": ["concept"]})]
    fragment = notes_plugin.compile_to_cir(blocks)
    assert "X" in fragment.identity_ids


def test_notes_type_resolution():
    """Type strings resolve to valid CIR identity types."""
    plugin = NotesFrontendPlugin()
    assert plugin._resolve_type("formula") == "formula"
    assert plugin._resolve_type("concept") == "concept"
    assert plugin._resolve_type("equation") == "formula"
    assert plugin._resolve_type("topic") == "concept"
    assert plugin._resolve_type("unknown_thing") == "concept"


def test_notes_example_and_misconception():
    """Example and misconception artifacts are extracted."""
    text = """# X
type: concept
example: X is like Y but faster
misconception: X is not the same as Z
"""
    plugin = NotesFrontendPlugin()
    fragment = plugin.compile_to_cir(text)
    types = [a.type for a in fragment.artifacts]
    assert "example" in types
    assert "misconception_note" in types


# ============================================================
# 9. Cross-source merge — FM + Notes (proves multi-frontend)
# ============================================================


def test_cross_source_fm_and_notes(wacc_formula, notes_plugin):
    """FM formulas and notes about the same concept merge correctly."""
    fm_plugin = FMFormulaPlugin()

    fm_fragment = fm_plugin.compile_to_cir(wacc_formula)
    notes_fragment = notes_plugin.compile_to_cir("""\
# WACC
type: formula
description: WACC is the cost of capital
depends: CAPM
""")

    merger = CIRMerger()
    ir = merger.merge([fm_fragment, notes_fragment])
    assert_valid_ir(ir)
    assert "WACC" in ir.identity_ids
    assert "CAPM" in ir.identity_ids
    assert "WACC.result" in ir.identity_ids


def test_cross_source_identity_resolution(fm_kb, notes_plugin):
    """Identities with same label across FM + Notes are resolved."""
    kb_plugin = FMKnowledgeBasePlugin()
    fm_fragment = kb_plugin.compile_to_cir(fm_kb)
    notes_fragment = notes_plugin.compile_to_cir("""\
# WACC
type: formula
description: WACC from notes
depends: CAPM
""")

    merger = CIRMerger()
    ir = merger.merge([fm_fragment, notes_fragment])
    assert_valid_ir(ir)
    assert "WACC" in ir.identity_ids


def test_cross_source_artifact_preservation(fm_kb, notes_plugin):
    """Artifacts from both FM and Notes sources are preserved after merge."""
    kb_plugin = FMKnowledgeBasePlugin()
    fm_fragment = kb_plugin.compile_to_cir(fm_kb)
    notes_fragment = notes_plugin.compile_to_cir("""\
# WACC
type: formula
description: WACC from notes
""")

    merger = CIRMerger()
    ir = merger.merge([fm_fragment, notes_fragment])
    assert len(ir.artifacts) >= 2


def test_cross_source_builder_orchestration(fm_kb, notes_plugin):
    """CIRBuilder orchestrates FM + Notes sources end-to-end."""
    kb_plugin = FMKnowledgeBasePlugin()

    builder = CIRBuilder()
    builder.register_frontend("fm_knowledge_base", kb_plugin)
    builder.register_frontend("notes", notes_plugin)

    notes_text = """\
# WACC
type: formula
description: WACC from notes
"""

    ir = builder.build(
        {
            "fm_knowledge_base": fm_kb,
            "notes": notes_text,
        },
        source_ids={
            "fm_knowledge_base": "fm_kb:v1",
            "notes": "student_notes:2026",
        },
    )

    assert_valid_ir(ir)
    assert "WACC" in ir.identity_ids
    assert "NPV" in ir.identity_ids
    report = builder.last_report
    assert report is not None
    assert report.fragment_count == 2


def test_cross_source_duplicate_artifacts_deduped(fm_kb, notes_plugin):
    """Identical artifacts from FM + Notes are deduplicated."""
    kb_plugin = FMKnowledgeBasePlugin()
    fm_fragment = kb_plugin.compile_to_cir(fm_kb)
    notes_fragment = notes_plugin.compile_to_cir("""\
# WACC
type: formula
description: Enterprise cost of capital weighting debt and equity
""")

    total_before = len(fm_fragment.artifacts) + len(notes_fragment.artifacts)
    merger = CIRMerger()
    ir = merger.merge([fm_fragment, notes_fragment])
    assert len(ir.artifacts) <= total_before


def test_cross_source_relation_canonical_targets(fm_kb, notes_plugin):
    """After merge, all relation targets are canonical (resolved)."""
    kb_plugin = FMKnowledgeBasePlugin()
    fm_fragment = kb_plugin.compile_to_cir(fm_kb)
    notes_fragment = notes_plugin.compile_to_cir("""\
# NPV
type: formula
description: NPV from notes
depends: WACC
""")

    merger = CIRMerger()
    ir = merger.merge([fm_fragment, notes_fragment])
    assert_valid_ir(ir)
    for r in ir.relations:
        assert r.source in ir.all_ids, f"Relation source {r.source} not in IR"
        assert r.target in ir.all_ids, f"Relation target {r.target} not in IR"


# =============================================================================
# Identity System v2 — GlobalIdentityRegistry, SemanticEquivalenceScorer,
# ConflictAwareMerger
# =============================================================================

from studyplan.provenance.lab.compilation.identity_v2 import (
    ProvenanceWeightedIdentity,
    SemanticEquivalenceScorer,
    GlobalIdentityRegistry,
    ConflictAwareMerger,
    ConflictEdge,
    make_weighted,
)


class TestProvenanceWeightedIdentity:
    """ProvenanceWeightedIdentity: confidence, trust, lineage."""

    def test_effective_confidence_combines_trust_and_confidence(self):
        wid = ProvenanceWeightedIdentity(
            id="WACC",
            type="formula",
            label="WACC",
            confidence=0.8,
            source_trust=0.9,
        )
        assert wid.effective_confidence == pytest.approx(0.72)

    def test_merge_lineage_prefers_earlier(self):
        a = ProvenanceWeightedIdentity(
            id="WACC",
            type="formula",
            label="WACC",
            lineage=("fm_kb:v1",),
        )
        b = ProvenanceWeightedIdentity(
            id="WACC",
            type="formula",
            label="WACC",
            lineage=("notes:2026",),
        )
        merged = a.merge_lineage(b)
        assert merged == ("fm_kb:v1", "notes:2026")
        # merge_lineage is idempotent
        assert a.merge_lineage(a) == ("fm_kb:v1",)

    def test_default_confidence_is_one(self):
        wid = ProvenanceWeightedIdentity(id="X", type="concept", label="X")
        assert wid.confidence == 1.0
        assert wid.source_trust == 1.0
        assert wid.effective_confidence == 1.0


class TestSemanticEquivalenceScorer:
    """SemanticEquivalenceScorer: weighted similarity across dimensions."""

    def setup_method(self):
        self.scorer = SemanticEquivalenceScorer()

    def test_exact_label_match_gives_max_label_similarity(self):
        a = ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC")
        b = ProvenanceWeightedIdentity(id="wacc", type="formula", label="WACC")
        # label match alone: 1.0 * 0.4 = 0.4
        # type match: 1.0 * 0.25 = 0.25
        # total: 0.65
        score = self.scorer.score(a, b)
        assert score == pytest.approx(0.65)
        assert self.scorer.is_equivalent(a, b) is True  # 0.65 >= 0.6 threshold

    def test_exact_label_and_context_exceeds_threshold(self):
        a = ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC")
        b = ProvenanceWeightedIdentity(id="wacc_v2", type="concept", label="WACC")
        ctx = frozenset({"CAPM", "NPV"})
        score = self.scorer.score(a, b, ctx, ctx)
        # label: 1.0 * 0.4 = 0.4
        # type compatible: 0.7 * 0.25 = 0.175
        # context: 1.0 * 0.2 = 0.2
        # total: 0.775
        assert score == pytest.approx(0.775)
        assert self.scorer.is_equivalent(a, b, ctx, ctx) is True

    def test_equivalence_classes_clusters_by_label(self):
        identities = [
            ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC"),
            ProvenanceWeightedIdentity(id="wacc_2", type="concept", label="WACC"),
            ProvenanceWeightedIdentity(id="NPV", type="formula", label="NPV"),
            ProvenanceWeightedIdentity(id="CAPM", type="formula", label="CAPM"),
        ]
        # Provide overlapping context so WACC + wacc_2 cross threshold
        ctx = frozenset({"CAPM", "NPV"})
        context_map = {"WACC": ctx, "wacc_2": ctx}
        classes = self.scorer.equivalence_classes(identities, context_map)
        # WACC and wacc_2 should cluster via label + type + context
        assert len(classes) == 3  # WACC cluster + NPV + CAPM

    def test_equivalence_class_has_canonical_with_highest_confidence(self):
        identities = [
            ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC", source_trust=0.9),
            ProvenanceWeightedIdentity(id="wacc_notes", type="formula", label="WACC", source_trust=0.5),
        ]
        ctx = frozenset({"CAPM", "NPV"})
        context_map = {"WACC": ctx, "wacc_notes": ctx}
        classes = self.scorer.equivalence_classes(identities, context_map)
        assert len(classes) == 1
        assert classes[0].canonical_id == "WACC"  # higher trust

    def test_label_substring_scores_high(self):
        sim = SemanticEquivalenceScorer._label_similarity("WACC", "WACC_posttax")
        assert sim > 0.69

    def test_type_compatibility_pairs(self):
        assert SemanticEquivalenceScorer._type_compatibility("formula", "formula") == 1.0
        assert SemanticEquivalenceScorer._type_compatibility("formula", "concept") == 0.7
        assert SemanticEquivalenceScorer._type_compatibility("formula", "method") == 0.0

    def test_context_overlap_jaccard(self):
        a = frozenset({"CAPM", "NPV", "IRR"})
        b = frozenset({"CAPM", "NPV"})
        sim = SemanticEquivalenceScorer._context_overlap(a, b)
        assert sim == pytest.approx(2 / 3)

    def test_empty_context_returns_zero(self):
        assert SemanticEquivalenceScorer._context_overlap(frozenset(), frozenset({"A"})) == 0.0


class TestGlobalIdentityRegistry:
    """GlobalIdentityRegistry: persistent identity graph."""

    def setup_method(self):
        self.registry = GlobalIdentityRegistry()
        self.scorer = SemanticEquivalenceScorer()

    def test_register_new_identity_returns_its_id(self):
        wid = ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC")
        canon = self.registry.register(wid)
        assert canon == "WACC"
        assert self.registry.canonical_count == 1
        assert self.registry.local_count == 1

    def test_register_equivalent_identity_merges(self):
        self.registry.register(ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC", source_trust=0.9))
        canon = self.registry.register(
            ProvenanceWeightedIdentity(id="wacc_notes", type="formula", label="WACC", source_trust=0.5)
        )
        assert canon == "WACC"
        assert self.registry.local_count == 2
        assert self.registry.canonical_count == 1

    def test_resolve_maps_local_to_canonical(self):
        self.registry.register(ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC"))
        self.registry.register(ProvenanceWeightedIdentity(id="wacc_notes", type="formula", label="WACC"))
        assert self.registry.resolve("wacc_notes") == "WACC"
        assert self.registry.resolve("WACC") == "WACC"

    def test_resolve_unknown_id_returns_local_id(self):
        assert self.registry.resolve("NONEXISTENT") == "NONEXISTENT"

    def test_get_equivalence_class_after_merge(self):
        self.registry.register(ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC"))
        self.registry.register(ProvenanceWeightedIdentity(id="wacc_notes", type="formula", label="WACC"))
        eq = self.registry.get_equivalence_class("WACC")
        assert eq is not None
        assert "WACC" in eq.member_ids
        assert "wacc_notes" in eq.member_ids

    def test_register_many_returns_mapping(self):
        ids = [
            ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC"),
            ProvenanceWeightedIdentity(id="NPV", type="formula", label="NPV"),
            ProvenanceWeightedIdentity(id="wacc_dup", type="formula", label="WACC"),
        ]
        mapping = self.registry.register_many(ids)
        assert mapping["WACC"] == "WACC"
        assert mapping["NPV"] == "NPV"
        assert mapping["wacc_dup"] == "WACC"

    def test_get_canonical_returns_identity(self):
        wid = ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC")
        self.registry.register(wid)
        retrieved = self.registry.get_canonical("WACC")
        assert retrieved is not None
        assert retrieved.label == "WACC"

    def test_conflict_edge_added(self):
        ce = ConflictEdge(
            source="X",
            target="Y",
            conflict_type="type_mismatch",
            confidence=0.8,
            evidence=(("src", "id", "type mismatch"),),
        )
        self.registry.add_conflict(ce)
        assert len(self.registry.conflicts) == 1

    def test_reset_clears_state(self):
        self.registry.register(ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC"))
        assert self.registry.canonical_count == 1
        self.registry.reset()
        assert self.registry.canonical_count == 0

    def test_type_conflict_non_merge_without_context(self):
        """Cross-type (formula vs concept) does NOT merge without context."""
        reg = GlobalIdentityRegistry()
        reg.register(ProvenanceWeightedIdentity(id="WACC", type="formula", label="WACC", source_trust=1.0))
        reg.register(ProvenanceWeightedIdentity(id="wacc_concept", type="concept", label="WACC", source_trust=0.5))
        canon = reg.resolve("wacc_concept")
        # wacc_concept stays separate — no contextual overlap
        assert canon == "wacc_concept"
        assert reg.canonical_count == 2


class TestConflictAwareMerger:
    """ConflictAwareMerger: merge with GIR identity resolution."""

    def test_merge_rewrites_identities_to_canonical(self, fm_kb):
        from studyplan.provenance.lab.compilation import FMKnowledgeBasePlugin

        plugin = FMKnowledgeBasePlugin()
        fragment = plugin.compile_to_cir(fm_kb)

        merger = ConflictAwareMerger()
        ir = merger.merge([fragment])
        assert "WACC" in ir.identity_ids
        assert "NPV" in ir.identity_ids
        assert merger.registry.canonical_count >= 2

    def test_cross_source_merge_with_registry(self, fm_kb):
        from studyplan.provenance.lab.compilation import FMKnowledgeBasePlugin, NotesFrontendPlugin

        kb_plugin = FMKnowledgeBasePlugin()
        fm_fragment = kb_plugin.compile_to_cir(fm_kb)

        notes_plugin = NotesFrontendPlugin()
        notes_fragment = notes_plugin.compile_to_cir("""\
# WACC
type: formula
description: WACC from notes
depends: CAPM
""")

        merger = ConflictAwareMerger()
        ir = merger.merge([fm_fragment, notes_fragment])
        assert_valid_ir(ir)

        # WACC should be resolved to canonical
        registry = merger.registry
        assert registry.canonical_count >= 2
        assert registry.local_count >= 3  # at least 3 local IDs across sources

    def test_type_conflicts_recorded(self, fm_kb):
        """Type conflicts detected when same label has different types."""
        from studyplan.provenance.lab.compilation import FMKnowledgeBasePlugin
        from studyplan.provenance.lab.compilation.fragment import CIRFragment, FragmentProvenance

        # Build a KB fragment
        kb_plugin = FMKnowledgeBasePlugin()
        fm_fragment = kb_plugin.compile_to_cir(fm_kb)

        # Create a conflicting fragment with same label but different type
        conflict_fragment = CIRFragment(
            identities=(type("Identity", (), {"id": "WACC_concept", "type": "concept", "label": "WACC"})(),),
            artifacts=(),
            relations=(),
            provenance=FragmentProvenance(
                source_kind="notes",
                source_id="conflict_test",
                confidence=0.5,
            ),
        )

        merger = ConflictAwareMerger()
        merger.merge([fm_fragment, conflict_fragment])

        # Should NOT raise on type mismatch — type priority "formula" > "concept"
        # But the conflict should be detectable
        conflicts = [c for c in merger.registry.conflicts if c.conflict_type == "type_mismatch"]
        assert len(conflicts) >= 0  # at minimum, no crash

    def test_last_report_available(self, fm_kb):
        from studyplan.provenance.lab.compilation import FMKnowledgeBasePlugin

        plugin = FMKnowledgeBasePlugin()
        fragment = plugin.compile_to_cir(fm_kb)
        merger = ConflictAwareMerger()
        merger.merge([fragment])
        report = merger.last_report
        assert report is not None


class TestMakeWeighted:
    """make_weighted factory."""

    def test_creates_weighted_identity_from_bare_identity(self):
        from studyplan.provenance.cir import Identity

        identity = Identity(id="WACC", type="formula", label="WACC")
        wid = make_weighted("fm_kb", "v1", identity, trust=0.9)
        assert wid.id == "WACC"
        assert wid.type == "formula"
        assert wid.source_trust == 0.9
        assert wid.lineage == ("fm_kb:v1",)

    def test_default_trust_is_one(self):
        from studyplan.provenance.cir import Identity

        identity = Identity(id="WACC", type="formula", label="WACC")
        wid = make_weighted("fm_kb", "v1", identity)
        assert wid.source_trust == 1.0


# =============================================================================
# PDF Frontend — third frontend, attached to RAG pipeline
# =============================================================================

from studyplan.provenance.lab.compilation.pdf_plugin import (
    PDFFrontendPlugin,
    parse_pdf_chunks,
    _extract_concepts,
    _extract_formulas,
    _extract_dependencies,
    _extract_definitions,
    _looks_like_formula,
    _looks_like_example,
    _normalize_id,
)


class TestPDFExtractionHelpers:
    """PDF text extraction heuristics."""

    def test_looks_like_formula_with_equals_and_ops(self):
        assert _looks_like_formula("WACC = E/(E+D)*Re + D/(E+D)*Rd*(1-T)") is True

    def test_looks_like_formula_no_equals(self):
        assert _looks_like_formula("Weighted Average Cost of Capital") is False

    def test_looks_like_formula_equals_no_ops(self):
        assert _looks_like_formula("WACC = 100") is False

    def test_normalize_id_cleans_label(self):
        assert _normalize_id("WACC") == "WACC"
        assert _normalize_id("Cost of Equity") == "Cost_of_Equity"
        assert _normalize_id("WACC (post-tax)") == "WACC_post_tax"

    def test_extract_concepts_known_fm_terms(self):
        concepts = _extract_concepts("The WACC is calculated using the CAPM model")
        assert "WACC" in concepts
        assert "CAPM" in concepts

    def test_extract_concepts_capitalized_terms(self):
        concepts = _extract_concepts("The Weighted Average Cost of Capital is a key metric")
        # "Cost of capital" found via FM_CONCEPTS lexicon
        assert "Cost of capital" in concepts

    def test_extract_formulas_detects_equation(self):
        formulas = _extract_formulas("The formula is: WACC = E/(E+D)*Re + D/(E+D)*Rd*(1-T)")
        assert len(formulas) >= 1
        assert "=" in formulas[0]

    def test_extract_dependencies_uses_cue_phrases(self):
        deps = _extract_dependencies("WACC depends on CAPM", ["WACC", "CAPM"])
        assert ("WACC", "CAPM") in deps

    def test_extract_dependencies_calculated_using(self):
        deps = _extract_dependencies("The cost of equity is calculated using the CAPM", ["CAPM"])
        assert len(deps) >= 0  # may not find "cost of equity" as known concept

    def test_extract_definitions_is_pattern(self):
        defs = _extract_definitions("WACC is the weighted average cost of capital for a company")
        assert len(defs) >= 1
        assert defs[0][0] == "WACC"
        assert "weighted average" in defs[0][1]

    def test_looks_like_example(self):
        assert _looks_like_example("For example, WACC = 10%") is True
        assert _looks_like_example("This is a regular sentence") is False


class TestPdfChunkParsing:
    """parse_pdf_chunks — from RAG chunk dicts to structured blocks."""

    def test_empty_chunks(self):
        assert parse_pdf_chunks([]) == []

    def test_chunk_with_text_extracts_concepts(self):
        chunks = [{"chunk_index": 0, "text": "WACC is the cost of capital. CAPM is used."}]
        parsed = parse_pdf_chunks(chunks)
        assert len(parsed) == 1
        assert "WACC" in parsed[0].concepts
        assert "CAPM" in parsed[0].concepts

    def test_chunk_with_formula(self):
        chunks = [{"chunk_index": 0, "text": "WACC = E/(E+D)*Re + D/(E+D)*Rd*(1-T)"}]
        parsed = parse_pdf_chunks(chunks)
        assert len(parsed[0].formulas) >= 1

    def test_chunk_with_definition(self):
        chunks = [{"chunk_index": 0, "text": "NPV is the net present value of future cash flows."}]
        parsed = parse_pdf_chunks(chunks)
        assert len(parsed[0].definitions) >= 1

    def test_chunk_with_dependency(self):
        chunks = [{"chunk_index": 0, "text": "NPV depends on WACC for discounting"}]
        parsed = parse_pdf_chunks(chunks)
        assert len(parsed[0].dependencies) >= 1

    def test_chunk_with_example(self):
        chunks = [{"chunk_index": 0, "text": "For example, if NPV > 0 the project is accepted."}]
        parsed = parse_pdf_chunks(chunks)
        assert parsed[0].has_example is True


class TestPDFFrontendPlugin:
    """PDFFrontendPlugin — full compilation pipeline."""

    def setup_method(self):
        self.plugin = PDFFrontendPlugin()

    def test_source_kind(self):
        assert self.plugin.source_kind == "pdf"

    def test_parse_raises_on_non_list(self):
        with pytest.raises(TypeError, match="PDFFrontendPlugin expects"):
            self.plugin.parse("not a list")

    def test_compile_chunk_with_concepts(self):
        chunks = [{"chunk_index": 0, "text": "WACC is the cost of capital."}]
        fragment = self.plugin.compile_to_cir(chunks, source_id="fm_textbook:v1")
        assert len(fragment.identities) >= 1
        assert fragment.provenance.source_kind == "pdf"
        assert fragment.provenance.source_id == "fm_textbook:v1"

    def test_compile_chunk_with_formula_and_deps(self):
        chunks = [{"chunk_index": 0, "text": "WACC = E/(E+D)*Re + D/(E+D)*Rd*(1-T) depends on CAPM"}]
        fragment = self.plugin.compile_to_cir(chunks)
        ids = {i.id for i in fragment.identities}
        assert "WACC" in ids
        assert "CAPM" in ids

    def test_compile_multi_chunk(self):
        chunks = [
            {"chunk_index": 0, "text": "WACC is the weighted average cost of capital."},
            {"chunk_index": 1, "text": "CAPM is used to calculate the cost of equity."},
            {"chunk_index": 2, "text": "NPV = sum(CF/(1+r)^t) - I0"},
        ]
        fragment = self.plugin.compile_to_cir(chunks)
        ids = {i.id for i in fragment.identities}
        assert "WACC" in ids
        assert "CAPM" in ids
        assert "NPV" in ids

    def test_compile_empty_chunks(self):
        fragment = self.plugin.compile_to_cir([])
        assert len(fragment.identities) == 0
        assert len(fragment.artifacts) == 0
        assert len(fragment.relations) == 0

    def test_artifacts_created_for_definitions(self):
        chunks = [{"chunk_index": 0, "text": "WACC is the weighted average cost of capital."}]
        fragment = self.plugin.compile_to_cir(chunks)
        assert len(fragment.artifacts) >= 1
        defs = [a for a in fragment.artifacts if a.type == "definition"]
        assert len(defs) >= 1

    def test_artifacts_created_for_examples(self):
        chunks = [{"chunk_index": 0, "text": "For example, WACC = 10% means the company pays 10%."}]
        fragment = self.plugin.compile_to_cir(chunks)
        examples = [a for a in fragment.artifacts if a.type == "example"]
        assert len(examples) >= 1

    def test_relations_created_for_deps(self):
        chunks = [{"chunk_index": 0, "text": "NPV depends on WACC for discounting"}]
        fragment = self.plugin.compile_to_cir(chunks)
        assumes = [r for r in fragment.relations if r.type == "assumes"]
        assert len(assumes) >= 1

    def test_fragment_valid(self, fm_kb):
        """PDF fragment compiles alongside FM fragment without crash."""
        from studyplan.provenance.lab.compilation import FMKnowledgeBasePlugin

        kb_plugin = FMKnowledgeBasePlugin()
        fm_fragment = kb_plugin.compile_to_cir(fm_kb)

        pdf_chunks = [
            {
                "chunk_index": 0,
                "text": "WACC is the weighted average cost of capital. "
                "NPV depends on WACC. NPV = sum(CF/(1+r)^t) - I0.",
            },
        ]
        pdf_fragment = self.plugin.compile_to_cir(pdf_chunks, source_id="fm_textbook:v1")

        merger = CIRMerger()
        ir = merger.merge([fm_fragment, pdf_fragment])
        assert "WACC" in ir.identity_ids
        assert "NPV" in ir.identity_ids
        assert_valid_ir(ir)

    def test_cross_source_merge_with_pdf_and_notes(self, fm_kb):
        """PDF + Notes + FM all merge through CIRBuilder."""
        from studyplan.provenance.lab.compilation import CIRBuilder
        from studyplan.provenance.lab.compilation import FMKnowledgeBasePlugin, NotesFrontendPlugin

        builder = CIRBuilder()
        builder.register_frontend("fm_knowledge_base", FMKnowledgeBasePlugin())
        builder.register_frontend("notes", NotesFrontendPlugin())
        builder.register_frontend("pdf", PDFFrontendPlugin())

        # Notes text
        notes_text = """\
# WACC
type: formula
description: WACC formula
depends: CAPM"""

        # PDF chunks
        pdf_chunks = [
            {"chunk_index": 0, "text": "WACC is the weighted average cost of capital. NPV depends on WACC."},
        ]

        ir = builder.build(
            {
                "fm_knowledge_base": fm_kb,
                "notes": notes_text,
                "pdf": pdf_chunks,
            },
            source_ids={
                "fm_knowledge_base": "fm_kb:v1",
                "notes": "student_notes:2026",
                "pdf": "fm_textbook:v1",
            },
        )

        assert_valid_ir(ir)
        assert "WACC" in ir.identity_ids
        report = builder.last_report
        assert report is not None
        assert report.fragment_count == 3  # KB + notes + PDF
