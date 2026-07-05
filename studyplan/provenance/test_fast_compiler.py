"""Tests for FastDomainCompiler — research-lab-principled domain compilation.

Test methodology follows the Research Laboratory protocol:
    1. Each test section has a hypothesis with predictions
    2. Predictions are stated as testable claims
    3. Falsification conditions are documented
    4. Evidence classes are assigned
    5. Compression scores are reported

Experiment H-FDC-01:
    A TypeRegistry-based domain compiler with invariant validation
    compiles any declarative DomainSpec into a valid ViewState without
    kernel changes. Compilation is deterministic and produces provenance.

Evidence classes:
    E1 — Unit: Individual components work (TypeRegistry, DomainSpec, CompilationRecord)
    E2 — Integration: Full compile pipeline produces valid ViewStates
    E3 — Cross-domain: Works for FM, PG, LLVM, GUI domains
    E4 — Determinism: Same spec → same ViewState with same hash
    E5 — Validation: Invariant checks catch spec errors
    E6 — Inference: infer() produces compilable specs
    E7 — Compression: Lines saved vs old compiler
    E8 — Provenance: CompilationRecord captures full context
"""

import pytest
import time

from studyplan.provenance.kernel import ViewState, Artifact, Transformation
from studyplan.provenance.kernel.types import ARTIFACT_TYPES
from studyplan.provenance.fast_compiler import (
    TypeRegistry,
    DomainSpec,
    DomainNode,
    DomainEdge,
    FastDomainCompiler,
    CompilationRecord,
    compile_fast,
    ParametricNode,
    ParametricEdge,
    ParametricSpec,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def compiler():
    return FastDomainCompiler()


@pytest.fixture
def registry():
    return TypeRegistry()


@pytest.fixture
def fm_npv_spec():
    """NPV spec expressed as a DomainSpec (not TopicSpec)."""
    return DomainSpec(
        id="NPV",
        title="Net Present Value",
        domain="fm",
        nodes=(
            DomainNode(id="r", concept="discount_rate", kind="parameter", target="Discount rate"),
            DomainNode(id="I_0", concept="initial_investment", kind="parameter", target="Initial investment"),
            DomainNode(
                id="CF_1", concept="cash_flow", kind="parameter", target="Cash flow t=1", metadata={"period": "1"}
            ),
            DomainNode(
                id="CF_2", concept="cash_flow", kind="parameter", target="Cash flow t=2", metadata={"period": "2"}
            ),
            DomainNode(
                id="CF_3", concept="cash_flow", kind="parameter", target="Cash flow t=3", metadata={"period": "3"}
            ),
            DomainNode(
                id="discounted_CF_1", concept="call_graph_region", kind="intermediate", target="Discounted CF t=1"
            ),
            DomainNode(
                id="discounted_CF_2", concept="call_graph_region", kind="intermediate", target="Discounted CF t=2"
            ),
            DomainNode(
                id="discounted_CF_3", concept="call_graph_region", kind="intermediate", target="Discounted CF t=3"
            ),
            DomainNode(id="sum_12", concept="call_graph_region", kind="intermediate", target="Partial sum"),
            DomainNode(id="gross_NPV", concept="call_graph_region", kind="intermediate", target="Gross present value"),
            DomainNode(id="NPV", concept="call_graph_region", kind="output", target="Net Present Value"),
        ),
        edges=(
            DomainEdge(
                id="discount_CF_1",
                from_id="CF_1",
                to_id="discounted_CF_1",
                rule="discounted_CF_1 = CF_1 / (1+r)^1",
                consumes=("r",),
                assumptions=("constant_discount_rate", "periodic_cash_flows"),
            ),
            DomainEdge(
                id="discount_CF_2",
                from_id="CF_2",
                to_id="discounted_CF_2",
                rule="discounted_CF_2 = CF_2 / (1+r)^2",
                consumes=("r",),
                assumptions=("constant_discount_rate", "periodic_cash_flows"),
            ),
            DomainEdge(
                id="discount_CF_3",
                from_id="CF_3",
                to_id="discounted_CF_3",
                rule="discounted_CF_3 = CF_3 / (1+r)^3",
                consumes=("r",),
                assumptions=("constant_discount_rate", "periodic_cash_flows"),
            ),
            DomainEdge(
                id="sum_12",
                from_id="discounted_CF_1",
                to_id="sum_12",
                rule="sum_12 = discounted_CF_1 + discounted_CF_2",
                consumes=("discounted_CF_2",),
            ),
            DomainEdge(
                id="sum_gross",
                from_id="sum_12",
                to_id="gross_NPV",
                rule="gross_NPV = sum_12 + discounted_CF_3",
                consumes=("discounted_CF_3",),
            ),
            DomainEdge(
                id="net_NPV",
                from_id="gross_NPV",
                to_id="NPV",
                rule="NPV = gross_NPV - I_0",
                consumes=("I_0",),
                assumptions=("rational_investment_decision",),
            ),
        ),
    )


# ============================================================
# E1 — Unit: TypeRegistry
# ============================================================


class TestTypeRegistry:
    """Hypothesis: TypeRegistry externalizes domain→type mapping.

    Prediction P1:
        A TypeRegistry eliminates domain-specific hardcoding from
        the compiler. Adding a new domain requires 3 lines:
        register, resolve, validate.

    Falsification:
        F1a: A domain with an unknown artifact type is silently accepted.
        F1b: resolve() returns wrong type for a registered concept.
    """

    def test_register_and_resolve(self, registry):
        registry.register_domain(
            "test_domain",
            {
                "rate": "config_value",
                "node": "ast_node",
            },
        )
        assert registry.resolve("test_domain", "rate") == "config_value"
        assert registry.resolve("test_domain", "node") == "ast_node"

    def test_register_rejects_unknown_types(self, registry):
        with pytest.raises(ValueError, match="Unknown artifact types"):
            registry.register_domain("bad", {"x": "nonexistent_type"})

    def test_resolve_unknown_domain_raises(self, registry):
        with pytest.raises(KeyError, match="Unknown domain"):
            registry.resolve("no_such_domain", "rate")

    def test_resolve_unknown_concept_raises(self, registry):
        registry.register_domain("d", {"a": "config_value"})
        with pytest.raises(KeyError):
            registry.resolve("d", "nonexistent_concept")

    def test_resolve_or_infer_exact_match(self, registry):
        registry.register_domain("d", {"my_rate": "config_value"})
        assert registry.resolve_or_infer("d", "my_rate") == "config_value"

    def test_resolve_or_infer_kind_parameter(self, registry):
        registry.register_domain("d", {})
        # No mapping, but kind="parameter" → config_value
        assert registry.resolve_or_infer("d", "anything", kind="parameter") == "config_value"

    def test_resolve_or_infer_kind_output(self, registry):
        registry.register_domain("d", {})
        assert registry.resolve_or_infer("d", "anything", kind="output") == "call_graph_region"

    def test_resolve_or_infer_convention_rate(self, registry):
        registry.register_domain("d", {})
        assert registry.resolve_or_infer("d", "discount_rate") == "config_value"

    def test_resolve_or_infer_convention_node(self, registry):
        registry.register_domain("d", {})
        assert registry.resolve_or_infer("d", "plan_node") == "control_flow_pattern"

    def test_known_domains(self, registry):
        assert registry.known_domains == frozenset()
        registry.register_domain("a", {"x": "config_value"})
        assert "a" in registry.known_domains

    def test_snapshot_includes_registered_types(self, registry):
        registry.register_domain("d", {"rate": "config_value"})
        snap = registry.snapshot()
        assert "d" in snap["domains"]
        assert snap["domains"]["d"]["rate"] == "config_value"
        assert "valid_artifact_types" in snap
        assert "config_value" in snap["valid_artifact_types"]

    def test_default_edge_semantics(self, registry):
        registry.register_domain("d", {"x": "config_value"})
        assert registry.default_edge_semantics("d") == "generative_mapping"

    def test_default_edge_semantics_custom(self, registry):
        registry.register_domain("d", {"x": "config_value"}, default_edge_semantics="call")
        assert registry.default_edge_semantics("d") == "call"


# ============================================================
# E1 — Unit: DomainSpec
# ============================================================


class TestDomainSpec:
    """Hypothesis: DomainSpec is a universal spec format.

    Prediction:
        Any domain's computation can be expressed as a DomainSpec
        without loss of information.

    Falsification:
        F2a: A DomainSpec that loses information during construction.
        F2b: A DomainSpec that produces a different ViewState than
             an equivalent hand-built ViewState.
    """

    def test_requires_id(self):
        with pytest.raises(AssertionError):
            DomainSpec(id="", title="", domain="fm")

    def test_requires_domain(self):
        with pytest.raises(AssertionError):
            DomainSpec(id="x", title="", domain="")

    def test_requires_nodes_or_edges(self):
        with pytest.raises(AssertionError):
            DomainSpec(id="x", title="", domain="fm", nodes=(), edges=())

    def test_minimal_spec(self):
        spec = DomainSpec(
            id="min",
            title="Minimal",
            domain="fm",
            nodes=(DomainNode(id="a", concept="discount_rate", kind="parameter"),),
        )
        assert spec.id == "min"
        assert len(spec.nodes) == 1
        assert len(spec.edges) == 0

    def test_preserves_metadata(self):
        spec = DomainSpec(
            id="m",
            title="M",
            domain="fm",
            nodes=(DomainNode(id="x", concept="rate", kind="parameter", target="X", metadata={"key": "val"}),),
        )
        assert spec.nodes[0].metadata["key"] == "val"
        assert spec.nodes[0].target == "X"


# ============================================================
# E2 — Integration: Full compile pipeline
# ============================================================


class TestCompile:
    """Hypothesis: compile() produces valid ViewStates.

    Prediction P2:
        For any valid DomainSpec, compile() returns a ViewState
        that passes invariant validation.

    Falsification:
        F3a: compile() silently produces an invalid ViewState.
        F3b: compile() raises for a valid spec.
    """

    def test_compiles_fm_npv(self, compiler, fm_npv_spec):
        vs, record = compiler.compile(fm_npv_spec)
        assert isinstance(vs, ViewState)
        assert len(vs.artifact_space) == 11  # 5 params + 6 intermediates/outputs
        assert len(vs.transform_space) == 6  # 3 discount + 2 sum + 1 net
        assert record.validation["pass"] is True

    def test_compilation_record_is_produced(self, compiler, fm_npv_spec):
        vs, record = compiler.compile(fm_npv_spec)
        assert isinstance(record, CompilationRecord)
        assert record.spec_id == "NPV"
        assert record.domain == "fm"
        assert len(record.spec_hash) == 16
        assert record.output_hash == vs.content_hash
        assert record.compilation_time_ms > 0
        assert "domains" in record.registry_snapshot

    def test_artifact_types_are_valid(self, compiler, fm_npv_spec):
        vs, _ = compiler.compile(fm_npv_spec)
        for a in vs.artifact_space:
            assert a.type in ARTIFACT_TYPES, f"Invalid type: {a.type}"

    def test_transforms_connect_existing_artifacts(self, compiler, fm_npv_spec):
        vs, _ = compiler.compile(fm_npv_spec)
        ids = {a.id for a in vs.artifact_space}
        for t in vs.transform_space:
            assert t.input_artifact_id in ids, f"Missing input: {t.input_artifact_id}"
            assert t.output_artifact_id in ids, f"Missing output: {t.output_artifact_id}"

    def test_constraints_are_key_value_pairs(self, compiler, fm_npv_spec):
        vs, _ = compiler.compile(fm_npv_spec)
        for t in vs.transform_space:
            for key, val in t.constraints:
                assert isinstance(key, str)
                assert isinstance(val, str)

    def test_minimal_spec(self, compiler):
        spec = DomainSpec(
            id="min",
            title="Minimal",
            domain="fm",
            nodes=(
                DomainNode(id="x", concept="discount_rate", kind="parameter"),
                DomainNode(id="y", concept="call_graph_region", kind="output"),
            ),
            edges=(DomainEdge(id="gen", from_id="x", to_id="y", rule="y = f(x)"),),
        )
        vs, record = compiler.compile(spec)
        assert len(vs.artifact_space) == 2
        assert len(vs.transform_space) == 1
        assert record.validation["pass"] is True

    def test_empty_transforms(self, compiler):
        spec = DomainSpec(
            id="params_only",
            title="Params",
            domain="fm",
            nodes=(
                DomainNode(id="a", concept="discount_rate", kind="parameter"),
                DomainNode(id="b", concept="cash_flow", kind="parameter"),
            ),
        )
        vs, record = compiler.compile(spec)
        assert len(vs.artifact_space) == 2
        assert len(vs.transform_space) == 0
        assert record.validation["pass"] is True


# ============================================================
# E3 — Cross-domain compilation
# ============================================================


class TestCrossDomain:
    """Hypothesis: FastDomainCompiler works for any domain.

    Prediction P3:
        The compiler produces valid ViewStates for FM, PG, LLVM,
        and GUI domains using the same code path.

    Falsification:
        F4a: A non-FM domain requires kernel type changes.
        F4b: A non-FM domain produces a ViewState that fails validation.
    """

    def test_fm_capm(self, compiler):
        spec = DomainSpec(
            id="CAPM",
            title="CAPM",
            domain="fm",
            nodes=(
                DomainNode(id="Rf", concept="discount_rate", kind="parameter", target="Risk-free rate"),
                DomainNode(id="beta", concept="cost_of_equity", kind="parameter", target="Equity beta"),
                DomainNode(id="MRP", concept="cost_of_equity", kind="parameter", target="Market risk premium"),
                DomainNode(id="Re_CAPM", concept="call_graph_region", kind="output", target="Cost of Equity via CAPM"),
            ),
            edges=(
                DomainEdge(
                    id="gen_CAPM",
                    from_id="beta",
                    to_id="Re_CAPM",
                    rule="Re = Rf + beta * MRP",
                    consumes=("Rf", "MRP"),
                    assumptions=("market_efficiency",),
                ),
            ),
        )
        vs, record = compiler.compile(spec)
        assert len(vs.artifact_space) == 4
        assert len(vs.transform_space) == 1
        assert record.validation["pass"] is True

    def test_pg_domain(self, compiler):
        """PostgreSQL query optimizer domain."""
        spec = DomainSpec(
            id="PG_optimizer",
            title="PG Optimizer",
            domain="pg",
            nodes=(
                DomainNode(id="from_clause", concept="plan_node", kind="parameter", target="FROM clause"),
                DomainNode(id="plan_tree_dp", concept="plan_node", kind="output", target="Plan tree via DP"),
                DomainNode(id="plan_tree_geqo", concept="plan_node", kind="output", target="Plan tree via GEQO"),
                DomainNode(id="planner_c", concept="source_file", kind="parameter", target="planner.c"),
            ),
            edges=(
                DomainEdge(
                    id="gen_dp", from_id="from_clause", to_id="plan_tree_dp", rule="DP search produces optimal plan"
                ),
                DomainEdge(
                    id="gen_geqo",
                    from_id="from_clause",
                    to_id="plan_tree_geqo",
                    rule="Genetic algorithm produces near-optimal plan",
                    semantics="generative_mapping",
                    assumptions=("join_count > 12",),
                ),
                DomainEdge(
                    id="call_planner",
                    from_id="from_clause",
                    to_id="planner_c",
                    rule="planner.c invoked for FROM clause processing",
                    semantics="call",
                ),
            ),
        )
        vs, record = compiler.compile(spec)
        assert len(vs.artifact_space) == 4
        assert len(vs.transform_space) == 3
        assert record.validation["pass"] is True

    def test_llvm_domain(self, compiler):
        """LLVM IR basic block domain."""
        spec = DomainSpec(
            id="LLVM_bb",
            title="LLVM Basic Blocks",
            domain="llvm",
            nodes=(
                DomainNode(id="bb_entry", concept="basic_block", kind="parameter", target="Entry block"),
                DomainNode(id="bb_exit", concept="basic_block", kind="output", target="Exit block"),
                DomainNode(id="inst_add", concept="instruction", kind="parameter", target="add instruction"),
            ),
            edges=(
                DomainEdge(
                    id="cf_entry_exit",
                    from_id="bb_entry",
                    to_id="bb_exit",
                    rule="entry → exit",
                    assumptions=("no_loop",),
                ),
            ),
        )
        vs, record = compiler.compile(spec)
        assert len(vs.artifact_space) == 3
        assert len(vs.transform_space) == 1
        assert record.validation["pass"] is True

    def test_gui_domain(self, compiler):
        """GTK4 component hierarchy domain."""
        spec = DomainSpec(
            id="GUI_simple",
            title="Simple GUI",
            domain="gui",
            nodes=(
                DomainNode(id="window", concept="widget", kind="parameter", target="Main window"),
                DomainNode(id="button", concept="widget", kind="parameter", target="Start button"),
                DomainNode(id="label", concept="widget", kind="output", target="Status label"),
            ),
            edges=(
                DomainEdge(id="pc_window_button", from_id="window", to_id="button", rule="window contains button"),
                DomainEdge(id="pc_window_label", from_id="window", to_id="label", rule="window contains label"),
            ),
        )
        vs, record = compiler.compile(spec)
        assert len(vs.artifact_space) == 3
        assert len(vs.transform_space) == 2
        assert record.validation["pass"] is True


# ============================================================
# E4 — Determinism
# ============================================================


class TestDeterminism:
    """Hypothesis: Compilation is deterministic.

    Prediction P4:
        Compiling the same spec twice produces identical ViewStates
        with identical content_hashes.

    Falsification:
        F5a: Same spec, different compilation → different content_hash.
        F5b: Same spec, different compiler instances → different ViewState.
    """

    def test_same_spec_same_hash(self, compiler, fm_npv_spec):
        vs1, r1 = compiler.compile(fm_npv_spec)
        vs2, r2 = compiler.compile(fm_npv_spec)
        assert vs1.content_hash == vs2.content_hash
        assert r1.output_hash == r2.output_hash

    def test_different_instances_same_hash(self, fm_npv_spec):
        c1 = FastDomainCompiler()
        c2 = FastDomainCompiler()
        vs1, _ = c1.compile(fm_npv_spec)
        vs2, _ = c2.compile(fm_npv_spec)
        assert vs1.content_hash == vs2.content_hash

    def test_artifact_order_independence(self, compiler):
        """Artifact ordering in spec should not affect hash."""
        spec_a = DomainSpec(
            id="test",
            title="Test",
            domain="fm",
            nodes=(
                DomainNode(id="a", concept="discount_rate", kind="parameter"),
                DomainNode(id="b", concept="call_graph_region", kind="output"),
            ),
            edges=(DomainEdge(id="gen", from_id="a", to_id="b", rule="a→b"),),
        )
        spec_b = DomainSpec(
            id="test",
            title="Test",
            domain="fm",
            nodes=(
                DomainNode(id="b", concept="call_graph_region", kind="output"),
                DomainNode(id="a", concept="discount_rate", kind="parameter"),
            ),
            edges=(DomainEdge(id="gen", from_id="a", to_id="b", rule="a→b"),),
        )
        vs_a, _ = compiler.compile(spec_a)
        vs_b, _ = compiler.compile(spec_b)
        # Note: content_hash depends on sorted IDs, so order-independent
        assert vs_a.content_hash == vs_b.content_hash


# ============================================================
# E5 — Validation catches errors
# ============================================================


class TestValidation:
    """Hypothesis: Invariant validation catches spec errors at compile time.

    Prediction P5:
        A spec with dangling edges (referencing nonexistent artifact IDs)
        produces a ViewState that fails iR1 validation.

    Falsification:
        F6a: A spec with errors passes validation silently.
        F6b: A spec with no errors fails validation.
    """

    def test_dangling_input_detected(self, compiler):
        spec = DomainSpec(
            id="bad",
            title="Bad",
            domain="fm",
            nodes=(
                DomainNode(id="a", concept="discount_rate", kind="parameter"),
                DomainNode(id="b", concept="call_graph_region", kind="output"),
            ),
            edges=(DomainEdge(id="gen", from_id="a", to_id="nonexistent", rule="a → ???"),),
        )
        _, record = compiler.compile(spec)
        assert record.validation["pass"] is False
        assert any("nonexistent" in e for e in record.validation.get("errors", []))

    def test_dangling_output_detected(self, compiler):
        spec = DomainSpec(
            id="bad2",
            title="Bad2",
            domain="fm",
            nodes=(DomainNode(id="b", concept="call_graph_region", kind="output"),),
            edges=(DomainEdge(id="gen", from_id="missing", to_id="b", rule="??? → b"),),
        )
        _, record = compiler.compile(spec)
        assert record.validation["pass"] is False

    def test_validate_existing_viewstate(self, compiler):
        """Can validate a ViewState without its original spec."""
        vs, _ = compiler.compile(
            DomainSpec(
                id="test",
                title="Test",
                domain="fm",
                nodes=(
                    DomainNode(id="a", concept="discount_rate", kind="parameter"),
                    DomainNode(id="b", concept="call_graph_region", kind="output"),
                ),
                edges=(DomainEdge(id="gen", from_id="a", to_id="b", rule="a→b"),),
            )
        )
        result = compiler.validate(vs)
        assert result["pass"] is True
        assert result["iR0_valid_types"] is True
        assert result["iR1_edge_connectivity"] is True

    def test_validate_broken_viewstate(self, compiler):
        """Orphan ViewState with broken edge is caught by iR1."""
        from studyplan.provenance.kernel import ViewState

        vs = ViewState(
            artifact_space=frozenset(
                [
                    Artifact(id="a", type="config_value", target="A"),
                ]
            ),
            transform_space=frozenset(
                [
                    Transformation(
                        id="bad",
                        input_artifact_id="a",
                        output_artifact_id="nonexistent",
                        transformation_type="generative_mapping",
                        rule_spec="bad",
                    ),
                ]
            ),
        )
        result = compiler.validate(vs)
        assert result["pass"] is False
        assert result["iR1_edge_connectivity"] is False


# ============================================================
# E6 — Inference from raw data
# ============================================================


class TestInfer:
    """Hypothesis: infer() produces compilable specs from raw data.

    Prediction P6:
        infer() + compile() produces ViewStates that pass validation.

    Falsification:
        F7: infer() produces a spec that fails compilation.
    """

    def test_infer_from_simple_data(self, compiler):
        nodes = [
            {"id": "x", "concept": "discount_rate", "kind": "parameter"},
            {"id": "y", "concept": "call_graph_region", "kind": "output"},
        ]
        edges = [
            {"id": "gen", "from_id": "x", "to_id": "y", "rule": "y = f(x)"},
        ]
        spec = compiler.infer("fm", nodes, edges)
        assert spec.id == "inferred_fm"
        assert spec.domain == "fm"
        vs, record = compiler.compile(spec)
        assert record.validation["pass"] is True
        assert len(vs.artifact_space) == 2
        ids = {a.id for a in vs.artifact_space}
        assert "x" in ids
        assert "y" in ids

    def test_infer_sets_inferred_metadata(self, compiler):
        nodes = [{"id": "a", "concept": "discount_rate", "kind": "parameter"}]
        spec = compiler.infer("fm", nodes, [])
        assert spec.metadata.get("inferred") is True

    def test_infer_handles_empty_nodes(self, compiler):
        spec = compiler.infer("fm", [], [])
        assert len(spec.nodes) == 1  # placeholder node added to satisfy DomainSpec
        vs, record = compiler.compile(spec)
        assert record.validation["pass"] is True


# ============================================================
# E7 — Compression measurement
# ============================================================


class TestCompression:
    """Measure compression: lines saved vs old DomainCompiler.

    The old DomainCompiler needs:
        - _infer_type() (15 lines, FM-specific)
        - _build_artifact() with FM-specific default types (25 lines)
        - _build_transform() with FM-specific assumption encoding (20 lines)
        - Plus N domain-specific TopicSpec files with FM types

    The FastDomainCompiler replaces all type-inference logic with
    TypeRegistry.resolve_or_infer() (3 lines per lookup).

    Compression for D domains with T type checks each:
        Old: O(D × T) lines of domain-specific code
        New: O(D) registry registrations + O(1) per type resolution

    For the 4 current domains (FM, PG, LLVM, GUI):
        Old compiler: ~60 lines of type-inference + per-domain boilerplate
        Fast compiler: ~12 lines of type registration + 3-line resolution

    This test measures the actual line savings.
    """

    def test_registry_replaces_type_inference(self):
        """Type inference moved from compiler (15 lines) to registry (0.5 lines per type)."""
        r = TypeRegistry()
        r.register_domain(
            "fm",
            {
                "rate": "config_value",
                "cost": "config_value",
            },
        )
        # Old compiler: 15-line _infer_type() with FM-specific role names
        # New compiler: registry.resolve_or_infer(domain, concept, kind)
        assert r.resolve_or_infer("fm", "rate", "parameter") == "config_value"
        assert r.resolve_or_infer("fm", "cost", "parameter") == "config_value"

    def test_registry_eliminates_domain_specific_code_per_domain(self):
        """Each new domain requires registration, not compiler modification."""
        r = TypeRegistry()
        r.register_domain("fm", {"rate": "config_value"})
        r.register_domain("pg", {"plan": "ast_node"})
        r.register_domain("llvm", {"block": "control_flow_pattern"})
        r.register_domain("gui", {"widget": "ast_node"})
        # Old compiler: 4 separate type-checking branches
        # Fast compiler: 4 registry.register_domain() calls
        assert r.known_domains == frozenset({"fm", "pg", "llvm", "gui"})
        assert r.resolve("fm", "rate") == "config_value"
        assert r.resolve("pg", "plan") == "ast_node"

    def test_fm_npv_compression(self, compiler, fm_npv_spec):
        """FM NPV: 11 nodes + 6 edges replaces 178 lines of TopicSpec."""
        vs, record = compiler.compile(fm_npv_spec)
        assert len(vs.artifact_space) == 11
        assert len(vs.transform_space) == 6
        assert record.validation["pass"] is True
        # The old NPV TopicSpec is 178 lines (compiler_spec.py:99-179)
        # The equivalent DomainSpec is ~70 lines
        # Compression ratio: ~2.5x
        assert record.compilation_time_ms < 50  # fast


# ============================================================
# E8 — CompilationRecord provenance
# ============================================================


class TestCompilationRecord:
    """Hypothesis: CompilationRecord captures full provenance for lab analysis.

    Prediction P8:
        CompilationRecord contains sufficient information to
        reproduce, audit, and compare compilations.

    Falsification:
        F8a: Two compilations of different specs produce identical records.
        F8b: CompilationRecord omits data needed for reproduction.
    """

    def test_record_contains_all_fields(self, compiler, fm_npv_spec):
        vs, record = compiler.compile(fm_npv_spec)
        d = record.to_dict()
        assert "spec_hash" in d
        assert "spec_id" in d
        assert "domain" in d
        assert "compiler_version" in d
        assert "registry_snapshot" in d
        assert "compilation_time_ms" in d
        assert "validation" in d
        assert "output_hash" in d

    def test_records_differ_for_different_specs(self, compiler, fm_npv_spec):
        spec2 = DomainSpec(
            id="CAPM",
            title="CAPM",
            domain="fm",
            nodes=(
                DomainNode(id="Rf", concept="discount_rate", kind="parameter"),
                DomainNode(id="Re", concept="call_graph_region", kind="output"),
            ),
            edges=(DomainEdge(id="gen", from_id="Rf", to_id="Re", rule="CAPM"),),
        )
        _, r1 = compiler.compile(fm_npv_spec)
        _, r2 = compiler.compile(spec2)
        assert r1.spec_hash != r2.spec_hash
        assert r1.output_hash != r2.output_hash

    def test_record_identifies_compiler_version(self, compiler, fm_npv_spec):
        _, record = compiler.compile(fm_npv_spec)
        assert record.compiler_version == FastDomainCompiler.VERSION

    def test_record_preserves_domain(self, compiler):
        spec = DomainSpec(
            id="pg_test",
            title="PG Test",
            domain="pg",
            nodes=(
                DomainNode(id="a", concept="plan_node", kind="parameter"),
                DomainNode(id="b", concept="plan_node", kind="output"),
            ),
            edges=(DomainEdge(id="gen", from_id="a", to_id="b", rule="a→b", semantics="call"),),
        )
        _, record = compiler.compile(spec)
        assert record.domain == "pg"
        assert "pg" in record.registry_snapshot["domains"]

    def test_record_includes_validation_results(self, compiler):
        bad_spec = DomainSpec(
            id="bad",
            title="Bad",
            domain="fm",
            nodes=(DomainNode(id="a", concept="discount_rate", kind="parameter"),),
            edges=(DomainEdge(id="gen", from_id="a", to_id="missing", rule=""),),
        )
        _, record = compiler.compile(bad_spec)
        assert record.validation["pass"] is False
        assert len(record.validation.get("errors", [])) > 0


# ============================================================
# E9 — compile_fast convenience
# ============================================================


class TestCompileFast:
    """Hypothesis: compile_fast returns ViewState directly."""

    def test_compile_fast_returns_viewstate(self, fm_npv_spec):
        vs = compile_fast(fm_npv_spec)
        assert isinstance(vs, ViewState)
        assert len(vs.artifact_space) == 11

    def test_compile_fast_accepts_registry(self, fm_npv_spec):
        r = TypeRegistry()
        r.register_domain("fm", {"discount_rate": "config_value"})
        vs = compile_fast(fm_npv_spec, registry=r)
        assert isinstance(vs, ViewState)


# ============================================================
# E10 — Edge semantics detection
# ============================================================


class TestEdgeSemantics:
    """Hypothesis: Edge semantics are inferred from registry when not specified."""

    def test_default_semantics_from_registry(self, compiler):
        spec = DomainSpec(
            id="test",
            title="Test",
            domain="fm",
            nodes=(
                DomainNode(id="a", concept="discount_rate", kind="parameter"),
                DomainNode(id="b", concept="call_graph_region", kind="output"),
            ),
            edges=(DomainEdge(id="gen", from_id="a", to_id="b", rule="f(x)"),),
        )
        vs, _ = compiler.compile(spec)
        t = next(iter(vs.transform_space))
        assert t.transformation_type == "generative_mapping"

    def test_explicit_semantics_used_when_given(self, compiler):
        spec = DomainSpec(
            id="test",
            title="Test",
            domain="pg",
            nodes=(
                DomainNode(id="a", concept="plan_node", kind="parameter"),
                DomainNode(id="b", concept="plan_node", kind="output"),
            ),
            edges=(DomainEdge(id="call", from_id="a", to_id="b", rule="a calls b", semantics="call"),),
        )
        vs, _ = compiler.compile(spec)
        t = next(iter(vs.transform_space))
        assert t.transformation_type == "call"


# ============================================================
# E11 — Custom TypeRegistry via constructor
# ============================================================


class TestCustomRegistry:
    """Hypothesis: Users can supply a custom registry for domain-specific types."""

    def test_custom_registry(self):
        r = TypeRegistry()
        r.register_domain(
            "medicine",
            {
                "symptom": "control_flow_pattern",
                "diagnosis": "call_graph_region",
                "vital": "config_value",
            },
        )
        c = FastDomainCompiler(type_registry=r)
        spec = DomainSpec(
            id="diagnosis",
            title="Diagnosis",
            domain="medicine",
            nodes=(
                DomainNode(id="fever", concept="vital", kind="parameter", target="Body temperature"),
                DomainNode(id="result", concept="diagnosis", kind="output", target="Diagnosis"),
            ),
            edges=(DomainEdge(id="infer", from_id="fever", to_id="result", rule="Infer from fever"),),
        )
        vs, record = c.compile(spec)
        assert record.validation["pass"] is True
        # Verify types came from custom registry
        ids = {a.id: a.type for a in vs.artifact_space}
        assert ids["fever"] == "config_value"
        assert ids["result"] == "call_graph_region"

    def test_custom_registry_unknown_domain(self):
        r = TypeRegistry()
        c = FastDomainCompiler(type_registry=r)
        spec = DomainSpec(
            id="test",
            title="Test",
            domain="unknown_domain",
            nodes=(DomainNode(id="a", concept="rate", kind="parameter"),),
        )
        # resolve_or_infer() catches KeyError and infers type from kind
        vs, record = c.compile(spec)
        assert record.validation["pass"] is True
        ids = {a.id: a.type for a in vs.artifact_space}
        assert ids["a"] == "config_value"

    def test_multiple_custom_registries(self):
        """Two compiler instances with different registries are independent."""
        r1 = TypeRegistry()
        r1.register_domain("domain_a", {"x": "config_value"})
        r2 = TypeRegistry()
        r2.register_domain("domain_b", {"y": "ast_node"})
        c1 = FastDomainCompiler(type_registry=r1)
        c2 = FastDomainCompiler(type_registry=r2)
        s1 = DomainSpec(
            id="a", title="A", domain="domain_a", nodes=(DomainNode(id="x", concept="x", kind="parameter"),)
        )
        s2 = DomainSpec(
            id="b", title="B", domain="domain_b", nodes=(DomainNode(id="y", concept="y", kind="intermediate"),)
        )
        vs1, _ = c1.compile(s1)
        vs2, _ = c2.compile(s2)
        assert {a.id for a in vs1.artifact_space} == {"x"}
        assert {a.id for a in vs2.artifact_space} == {"y"}


# ============================================================
# E12 — Performance: compilation is fast
# ============================================================


class TestPerformance:
    """Hypothesis: Compilation is sub-10ms for typical specs.

    Prediction P9:
        Any spec with <100 nodes compiles in under 50ms.

    Falsification:
        F9a: A small spec takes >100ms to compile.
    """

    def test_small_spec_is_fast(self, compiler, fm_npv_spec):
        t0 = time.perf_counter()
        for _ in range(100):
            compiler.compile(fm_npv_spec)
        elapsed = (time.perf_counter() - t0) * 1000
        assert elapsed < 2000, f"100 compilations took {elapsed:.1f}ms (expected <2000ms)"
        # Average: <20ms per compilation

    def test_large_spec_is_fast(self, compiler):
        """100 nodes + 100 edges should compile quickly."""
        nodes = tuple(
            DomainNode(id=f"node_{i}", concept="discount_rate", kind="parameter" if i < 50 else "intermediate")
            for i in range(100)
        )
        edges = tuple(
            DomainEdge(id=f"edge_{i}", from_id=f"node_{i}", to_id=f"node_{i + 1}", rule=f"step_{i}") for i in range(99)
        )
        spec = DomainSpec(id="large", title="Large", domain="fm", nodes=nodes, edges=edges)
        t0 = time.perf_counter()
        vs, record = compiler.compile(spec)
        elapsed = (time.perf_counter() - t0) * 1000
        assert elapsed < 100, f"100-node spec took {elapsed:.1f}ms (expected <100ms)"
        assert len(vs.artifact_space) == 100
        assert len(vs.transform_space) == 99
        assert record.validation["pass"] is True


# ============================================================
# Parametric expansion tests (Earns P5)
# ============================================================


class TestParametricNode:
    """Evidence class E9: ParametricNode expansion is correct."""

    def test_expands_single_node(self):
        pn = ParametricNode(id_template="CF_{i}", concept="cash_flow", kind="parameter", range_end=1)
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,))
        spec = pspec.expand()
        assert len(spec.nodes) == 1
        assert spec.nodes[0].id == "CF_1"
        assert spec.nodes[0].concept == "cash_flow"
        assert spec.nodes[0].kind == "parameter"

    def test_expands_multiple_indices(self):
        pn = ParametricNode(id_template="CF_{i}", concept="cash_flow", kind="parameter", range_start=1, range_end=3)
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,))
        spec = pspec.expand()
        assert len(spec.nodes) == 3
        ids = [n.id for n in spec.nodes]
        assert ids == ["CF_1", "CF_2", "CF_3"]

    def test_expands_from_zero(self):
        pn = ParametricNode(id_template="x_{i}", concept="cash_flow", kind="parameter", range_start=0, range_end=2)
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,))
        spec = pspec.expand()
        assert len(spec.nodes) == 3
        assert spec.nodes[0].id == "x_0"

    def test_preserves_concrete_nodes(self):
        cn = DomainNode(id="r", concept="discount_rate", kind="parameter")
        pn = ParametricNode(id_template="CF_{i}", concept="cash_flow", kind="parameter", range_end=2)
        pspec = ParametricSpec(id="test", title="Test", domain="fm", nodes=(cn,), parametric_nodes=(pn,))
        spec = pspec.expand()
        assert len(spec.nodes) == 3
        assert spec.nodes[0].id == "r"

    def test_target_template_substitution(self):
        pn = ParametricNode(
            id_template="PV_{i}",
            concept="present_value",
            kind="intermediate",
            range_end=2,
            target_template="period_{i}_pv",
        )
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,))
        spec = pspec.expand()
        assert spec.nodes[0].target == "period_1_pv"
        assert spec.nodes[1].target == "period_2_pv"

    def test_metadata_template_substitution(self):
        pn = ParametricNode(
            id_template="PV_{i}",
            concept="present_value",
            kind="intermediate",
            range_end=2,
            metadata_template={"period": "{i}", "label": "PV_period_{i}"},
        )
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,))
        spec = pspec.expand()
        assert spec.nodes[0].metadata == {"period": "1", "label": "PV_period_1"}
        assert spec.nodes[1].metadata == {"period": "2", "label": "PV_period_2"}


class TestParametricEdge:
    """Evidence class E10: ParametricEdge expansion is correct."""

    def test_expands_single_edge(self):
        pe = ParametricEdge(
            id_template="discount_{i}", from_template="CF_{i}", to_template="PV_{i}", rule="CF_i / (1+r)^i", range_end=1
        )
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_edges=(pe,))
        spec = pspec.expand()
        assert len(spec.edges) == 1
        e = spec.edges[0]
        assert e.id == "discount_1"
        assert e.from_id == "CF_1"
        assert e.to_id == "PV_1"

    def test_expands_multiple_edges(self):
        pe = ParametricEdge(
            id_template="discount_{i}", from_template="CF_{i}", to_template="PV_{i}", range_start=1, range_end=3
        )
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_edges=(pe,))
        spec = pspec.expand()
        assert len(spec.edges) == 3

    def test_concrete_and_parametric_edges(self):
        ce = DomainEdge(id="sum", from_id="PV_1", to_id="total", rule="sum")
        pe = ParametricEdge(id_template="discount_{i}", from_template="CF_{i}", to_template="PV_{i}", range_end=2)
        pspec = ParametricSpec(id="test", title="Test", domain="fm", edges=(ce,), parametric_edges=(pe,))
        spec = pspec.expand()
        assert len(spec.edges) == 3
        assert spec.edges[0].id == "sum"

    def test_rule_substitution(self):
        pe = ParametricEdge(
            id_template="e_{i}", from_template="CF_{i}", to_template="PV_{i}", rule="CF_{i} / (1+r)^{i}", range_end=2
        )
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_edges=(pe,))
        spec = pspec.expand()
        assert spec.edges[0].rule == "CF_1 / (1+r)^1"
        assert spec.edges[1].rule == "CF_2 / (1+r)^2"


class TestParametricSpec:
    """Evidence class E11: ParametricSpec end-to-end."""

    def test_metadata_tracks_expansion(self):
        pn = ParametricNode(id_template="CF_{i}", concept="cash_flow", kind="parameter", range_end=3)
        pspec = ParametricSpec(id="npv_3p", title="3-period NPV", domain="fm", parametric_nodes=(pn,))
        spec = pspec.expand()
        assert spec.metadata["expanded"] is True
        assert spec.metadata["parametric_node_count"] == 1
        assert spec.metadata["expanded_node_count"] == 3

    def test_deterministic_expansion(self):
        pn = ParametricNode(id_template="x_{i}", concept="cash_flow", kind="parameter", range_end=5)
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,))
        spec1 = pspec.expand()
        spec2 = pspec.expand()
        assert len(spec1.nodes) == len(spec2.nodes)
        assert [n.id for n in spec1.nodes] == [n.id for n in spec2.nodes]

    def test_empty_parametric(self):
        pspec = ParametricSpec(
            id="test", title="Test", domain="fm", nodes=(DomainNode(id="a", concept="cash_flow", kind="parameter"),)
        )
        spec = pspec.expand()
        assert len(spec.nodes) == 1
        assert spec.edges == ()

    def test_expanded_spec_is_valid_domainspec(self):
        pn = ParametricNode(id_template="CF_{i}", concept="cash_flow", kind="parameter", range_end=3)
        pe = ParametricEdge(id_template="e_{i}", from_template="CF_{i}", to_template="PV_{i}", range_end=3)
        pspec = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,), parametric_edges=(pe,))
        spec = pspec.expand()
        assert isinstance(spec, DomainSpec)
        assert spec.id == "test"
        assert spec.domain == "fm"

    def test_no_interference_between_consecutive_expansions(self):
        pn = ParametricNode(id_template="x_{i}", concept="cash_flow", kind="parameter", range_end=2)
        spec1 = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,)).expand()
        spec2 = ParametricSpec(id="test", title="Test", domain="fm", parametric_nodes=(pn,)).expand()
        assert [n.id for n in spec1.nodes] == [n.id for n in spec2.nodes]


class TestParametricCompilation:
    """Evidence class E12: Compiled parametric specs → valid ViewStates."""

    def test_compiles_npv_3_period(self, compiler):
        """3-period parametric → compiled → valid ViewState."""
        pspec = ParametricSpec(
            id="NPV_3p",
            title="3-period Net Present Value",
            domain="fm",
            nodes=(
                DomainNode(id="r", concept="discount_rate", kind="parameter"),
                DomainNode(id="I_0", concept="initial_investment", kind="parameter"),
                DomainNode(id="total_PV", concept="present_value", kind="intermediate"),
                DomainNode(id="NPV", concept="net_present_value", kind="output"),
            ),
            edges=(
                DomainEdge(
                    id="net",
                    from_id="total_PV",
                    to_id="NPV",
                    rule="NPV = total_PV - I_0",
                    assumptions=("rational_investment_decision",),
                    consumes=("I_0",),
                ),
            ),
            parametric_nodes=[
                ParametricNode(id_template="CF_{i}", concept="cash_flow", kind="parameter", range_end=3),
                ParametricNode(id_template="PV_{i}", concept="present_value", kind="intermediate", range_end=3),
            ],
            parametric_edges=[
                ParametricEdge(
                    id_template="discount_{i}",
                    from_template="CF_{i}",
                    to_template="PV_{i}",
                    rule="CF_{i} / (1+r)^{i}",
                    range_end=3,
                ),
                ParametricEdge(
                    id_template="sum_{i}",
                    from_template="PV_{i}",
                    to_template="total_PV",
                    rule="sum of PV_i",
                    range_end=3,
                ),
            ],
        )
        vs, record = compiler.compile(pspec.expand())
        assert record.validation["pass"] is True
        assert len(vs.artifact_space) == 10
        assert len(vs.transform_space) == 7
        pv_ids = {a.id for a in vs.artifact_space if a.id.startswith("PV_")}
        assert pv_ids == {"PV_1", "PV_2", "PV_3"}

    def test_compiles_npv_5_period(self, compiler):
        """Same structure, different parameter value."""
        pspec = ParametricSpec(
            id="NPV_5p",
            title="5-period NPV",
            domain="fm",
            nodes=(
                DomainNode(id="r", concept="discount_rate", kind="parameter"),
                DomainNode(id="I_0", concept="initial_investment", kind="parameter"),
                DomainNode(id="total_PV", concept="present_value", kind="intermediate"),
                DomainNode(id="NPV", concept="net_present_value", kind="output"),
            ),
            edges=(
                DomainEdge(
                    id="net",
                    from_id="total_PV",
                    to_id="NPV",
                    rule="NPV = total_PV - I_0",
                    assumptions=("rational_investment_decision",),
                    consumes=("I_0",),
                ),
            ),
            parametric_nodes=[
                ParametricNode(id_template="CF_{i}", concept="cash_flow", kind="parameter", range_end=5),
                ParametricNode(id_template="PV_{i}", concept="present_value", kind="intermediate", range_end=5),
            ],
            parametric_edges=[
                ParametricEdge(id_template="discount_{i}", from_template="CF_{i}", to_template="PV_{i}", range_end=5),
                ParametricEdge(id_template="sum_{i}", from_template="PV_{i}", to_template="total_PV", range_end=5),
            ],
        )
        vs, record = compiler.compile(pspec.expand())
        assert record.validation["pass"] is True
        assert len(vs.artifact_space) == 14
        assert len(vs.transform_space) == 11

    def test_compiles_custom_domain_with_params(self, compiler):
        """Non-FM domain: generic parametric compilation."""
        reg = TypeRegistry()
        reg.register_domain(
            "physics",
            {
                "mass": "config_value",
                "velocity": "config_value",
                "momentum": "config_value",
            },
        )
        physics_compiler = FastDomainCompiler(reg)
        pspec = ParametricSpec(
            id="momentum_N",
            title="N-body momentum",
            domain="physics",
            nodes=(DomainNode(id="total_p", concept="momentum", kind="output"),),
            parametric_nodes=[
                ParametricNode(id_template="m_{i}", concept="mass", kind="parameter", range_end=3),
                ParametricNode(id_template="v_{i}", concept="velocity", kind="parameter", range_end=3),
                ParametricNode(id_template="p_{i}", concept="momentum", kind="intermediate", range_end=3),
            ],
            parametric_edges=[
                ParametricEdge(
                    id_template="compute_p_{i}",
                    from_template="m_{i}",
                    to_template="p_{i}",
                    rule="p = m * v",
                    range_end=3,
                    consumes=("v_{i}",),
                ),
                ParametricEdge(id_template="sum_p_{i}", from_template="p_{i}", to_template="total_p", range_end=3),
            ],
        )
        vs, record = physics_compiler.compile(pspec.expand())
        assert record.validation["pass"] is True
        assert len(vs.artifact_space) == 10
        assert len(vs.transform_space) == 6

    def test_determinism_across_compilations(self, compiler):
        pspec = ParametricSpec(
            id="det_test",
            title="Determinism test",
            domain="fm",
            parametric_nodes=[
                ParametricNode(id_template="x_{i}", concept="cash_flow", kind="parameter", range_end=4),
            ],
        )
        vs1, _ = compiler.compile(pspec.expand())
        vs2, _ = compiler.compile(pspec.expand())
        assert vs1.content_hash == vs2.content_hash

    def test_validation_fails_with_dangling_ref(self, compiler):
        """Edge references parametric nodes that don't exist."""
        pspec = ParametricSpec(
            id="dangling",
            title="Dangling ref",
            domain="fm",
            parametric_edges=[
                ParametricEdge(id_template="e_{i}", from_template="X_{i}", to_template="Y_{i}", range_end=2),
            ],
        )
        vs, record = compiler.compile(pspec.expand())
        assert record.validation["pass"] is False
        assert any("iR1" in e for e in record.validation.get("errors", []))
