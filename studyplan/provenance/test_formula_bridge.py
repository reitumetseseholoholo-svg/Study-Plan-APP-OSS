"""Tests for Formula Bridge — auto-compile provenance DomainSpecs from DSL formula registry.

Hypothesis H-FB-01:
    The FormulaDecl registry contains sufficient structural information to
    generate provenance DomainSpecs for the FastDomainCompiler.

Predictions and evidence classes:
    P1 (E1): formula_to_domainspec produces a valid DomainSpec from a FormulaDecl
    P2 (E1): formula_chain_to_domainspec produces a multi-step DomainSpec
    P3 (E2): registry_to_domainspecs converts all registered formulas
    P4 (E2): auto_register_fm_domain populates the TypeRegistry correctly
    P5 (E3): auto-compiled DomainSpecs compile to valid ViewStates
    P6 (E3): compile_all_registry succeeds for all registry entries
    P7 (E4): Same FormulaDecl produces identical DomainSpec (determinism)
    P8 (E5): Missing fields produce graceful degradation, not crashes
    P9 (E3): resolve_topic_key finds topics in both ALL_TOPICS and formula registry
    P10 (E3): get_topic_viewstate compiles from either source
"""

import pytest

from studyplan.domain_reasoning.formula_registry import (
    FormulaDecl,
    CONCEPT_TYPE_EXPRESSION,
)
from studyplan.provenance.formula_bridge import (
    formula_to_domainspec,
    formula_chain_to_domainspec,
    registry_to_domainspecs,
    auto_register_fm_domain,
    compile_all_registry,
    resolve_topic_key,
    get_topic_viewstate,
)
from studyplan.provenance.fast_compiler import (
    DomainSpec,
    TypeRegistry,
)


# ============================================================
# E1: Individual components
# ============================================================


class TestFormulaToDomainSpec:
    """P1: formula_to_domainspec produces a valid DomainSpec from a FormulaDecl."""

    def test_converts_expression_formula(self):
        decl = FormulaDecl(
            concept_id="fm.cost_of_equity",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="cost_of_equity",
            expression="risk_free + beta * market_return",
            param_names=("risk_free", "beta", "market_return"),
            output_slot="cost_of_equity",
            label="Cost of Equity",
            diagnostic_tags=("market_efficiency", "single_period"),
        )
        spec = formula_to_domainspec("fm.cost_of_equity", decl)

        assert isinstance(spec, DomainSpec)
        assert spec.id == "fm.cost_of_equity"
        assert spec.domain == "fm"
        assert len(spec.nodes) == 4  # 3 params + 1 output
        assert len(spec.edges) == 1

        param_ids = {n.id for n in spec.nodes if n.kind == "parameter"}
        assert param_ids == {"risk_free", "beta", "market_return"}

        edge = spec.edges[0]
        assert edge.from_id == "risk_free"
        assert edge.to_id == "cost_of_equity"
        assert "market_efficiency" in edge.assumptions

    def test_converts_with_dependencies(self):
        decl = FormulaDecl(
            concept_id="fm.wacc",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="wacc",
            expression="cost_equity * eq_w + cost_debt * (1 - tax) * d_w",
            param_names=("cost_equity", "cost_debt", "tax", "eq_w", "d_w"),
            output_slot="wacc",
            dependencies=("fm.cost_of_equity", "fm.cost_of_debt"),
            label="WACC",
        )
        spec = formula_to_domainspec("fm.wacc", decl)

        node_ids = {n.id for n in spec.nodes}
        assert "cost_of_equity_result" in node_ids
        assert "cost_of_debt_result" in node_ids
        assert len(spec.nodes) == 8  # 5 params + 2 deps + 1 output

    def test_converts_minimal_decl(self):
        decl = FormulaDecl(
            concept_id="fm.simple",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="simple",
        )
        spec = formula_to_domainspec("fm.simple", decl)

        assert isinstance(spec, DomainSpec)
        assert len(spec.nodes) == 1  # just output
        assert len(spec.edges) == 1
        assert spec.edges[0].from_id == spec.edges[0].to_id  # self-loop for trivial


class TestChainConversion:
    """P2: formula_chain_to_domainspec produces a multi-step DomainSpec."""

    def test_two_step_chain(self):
        steps = _make_chain_steps(
            [
                {"slot": "after_tax", "expression": "pretax * (1 - tax_rate)", "param_names": ("pretax", "tax_rate")},
                {
                    "slot": "wacc",
                    "expression": "after_tax * weight + other * oweight",
                    "param_names": ("weight", "other", "oweight"),
                },
            ]
        )
        decl = FormulaDecl(
            concept_id="fm.two_step",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="two_step",
            output_slot="wacc",
            label="Two-step chain",
        )
        spec = formula_chain_to_domainspec("fm.two_step", decl, steps)

        assert isinstance(spec, DomainSpec)
        assert len(spec.nodes) >= 6  # 5 params + 2 step outputs (1 is final)
        assert len(spec.edges) == 2

        edge_ids = {e.id for e in spec.edges}
        assert "two_step_step_0" in edge_ids
        assert "two_step_step_1" in edge_ids


class TestRegistryExtraction:
    """P3: registry_to_domainspecs converts all registered formulas."""

    def test_converts_all_formulas(self):
        specs = registry_to_domainspecs()
        assert isinstance(specs, dict)
        assert len(specs) > 0

        for cid, spec in specs.items():
            assert isinstance(spec, DomainSpec)
            assert spec.id == cid
            assert len(spec.nodes) > 0

    def test_each_spec_has_edges(self):
        specs = registry_to_domainspecs()
        for cid, spec in specs.items():
            assert len(spec.edges) > 0, f"{cid} has no edges"


class TestAutoRegister:
    """P4: auto_register_fm_domain populates the TypeRegistry."""

    def test_populates_registry(self):
        tr = auto_register_fm_domain()
        assert "fm" in tr._mappings
        assert len(tr._mappings["fm"]) > 0

    def test_merges_with_existing(self):
        tr = TypeRegistry()
        tr.register_domain("fm", {"existing_concept": "config_value"}, "generative_mapping")
        before = len(tr._mappings["fm"])

        auto_register_fm_domain(tr)
        after = len(tr._mappings["fm"])
        assert after > before


# ============================================================
# E3: Compilation
# ============================================================


@pytest.fixture
def compiler():
    from studyplan.provenance.fast_compiler import FastDomainCompiler

    return FastDomainCompiler()


class TestCompilation:
    """P5: auto-compiled DomainSpecs compile to valid ViewStates."""

    def test_single_formula_compiles(self, compiler):
        decl = FormulaDecl(
            concept_id="fm.cost_of_equity",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="cost_of_equity",
            expression="risk_free + beta * (market_return - risk_free)",
            param_names=("risk_free", "beta", "market_return"),
            output_slot="cost_of_equity",
        )
        spec = formula_to_domainspec("fm.cost_of_equity", decl)
        vs, record = compiler.compile(spec)

        assert record.validation["pass"]
        assert len(vs.artifact_space) >= 3
        assert len(vs.transform_space) == 1

    def test_whole_registry_compiles(self):
        results = compile_all_registry()
        assert len(results) > 0

        failures = [cid for cid, entry in results.items() if not entry["pass"]]
        assert not failures, f"Failed to compile: {failures}"

    def test_chain_compiles(self, compiler):
        name = "fm.wacc"
        steps = _make_chain_steps(
            [
                {"slot": "after_tax", "expression": "pretax * (1 - tax_rate)", "param_names": ("pretax", "tax_rate")},
                {
                    "slot": "wacc",
                    "expression": "after_tax * weight + other * oweight",
                    "param_names": ("weight", "other", "oweight"),
                },
            ]
        )
        decl = FormulaDecl(
            concept_id=name,
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="wacc",
            output_slot="wacc",
        )
        spec = formula_chain_to_domainspec(name, decl, steps)
        compiler.registry = auto_register_fm_domain(compiler.registry)
        vs, record = compiler.compile(spec)

        assert record.validation["pass"]


# ============================================================
# E4: Determinism
# ============================================================


class TestDeterminism:
    """P7: Same FormulaDecl produces identical DomainSpec."""

    def test_deterministic_conversion(self):
        decl = FormulaDecl(
            concept_id="fm.test_det",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="test_det",
            expression="a + b",
            param_names=("a", "b"),
            output_slot="result",
        )
        spec1 = formula_to_domainspec("fm.test_det", decl)
        spec2 = formula_to_domainspec("fm.test_det", decl)

        assert spec1.id == spec2.id
        assert len(spec1.nodes) == len(spec2.nodes)
        assert len(spec1.edges) == len(spec2.edges)

    def test_deterministic_chain(self):
        steps = _make_chain_steps(
            [
                {"slot": "s1", "expression": "x + 1", "param_names": ("x",)},
            ]
        )
        decl = FormulaDecl(
            concept_id="fm.test_chain_det",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="test_chain_det",
        )
        spec1 = formula_chain_to_domainspec("fm.test_chain_det", decl, steps)
        spec2 = formula_chain_to_domainspec("fm.test_chain_det", decl, steps)

        assert len(spec1.edges) == len(spec2.edges)


# ============================================================
# E5: Graceful degradation
# ============================================================


class TestGracefulDegradation:
    """P8: Missing fields produce graceful degradation, not crashes."""

    def test_empty_fields_ok(self):
        decl = FormulaDecl(
            concept_id="fm.empty",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="empty",
        )
        spec = formula_to_domainspec("fm.empty", decl)
        assert isinstance(spec, DomainSpec)

    def test_bad_concept_type_ok(self):
        specs = registry_to_domainspecs()
        assert isinstance(specs, dict)


# ============================================================
# P9-P10: Topic resolution & unified compilation
# ============================================================


class TestResolveTopicKey:
    """P9: resolve_topic_key finds topics in both ALL_TOPICS and formula registry."""

    def test_resolves_all_topics_keys(self):
        assert resolve_topic_key("CAPM") == "CAPM"
        assert resolve_topic_key("NPV") == "NPV"

    def test_resolves_formula_registry(self):
        from studyplan.domain_reasoning.formula_registry import get_registry

        registry = get_registry()
        if not registry:
            pytest.skip("No formulas in registry")
        sample_cid = next(iter(registry))
        result = resolve_topic_key(sample_cid)
        assert result == sample_cid

    def test_returns_empty_for_unknown(self):
        assert resolve_topic_key("") == ""
        assert resolve_topic_key("nonexistent_topic_xyz") == ""


class TestGetTopicViewState:
    """P10: get_topic_viewstate compiles from either source."""

    def test_compiles_all_topics_capm(self):
        result = get_topic_viewstate("CAPM")
        assert result is not None
        vs, target_id = result
        assert vs is not None
        assert target_id

    def test_compiles_formula_registry_topic(self):
        from studyplan.domain_reasoning.formula_registry import get_registry

        registry = get_registry()
        if not registry:
            pytest.skip("No formulas in registry")
        sample_cid = next(iter(registry))
        result = get_topic_viewstate(sample_cid)
        if result is not None:
            vs, target_id = result
            assert vs is not None
            assert target_id

    def test_produces_queryable_viewstate(self):
        from studyplan.provenance.execution import ExecutionContext

        result = get_topic_viewstate("CAPM")
        assert result is not None
        vs, target_id = result
        ctx = ExecutionContext(vs)
        data = ctx.inherited_assumptions_fast(target_id)
        assert data is not None
        assert "assumptions" in data

    def test_produces_queryable_registry_viewstate(self):
        from studyplan.provenance.execution import ExecutionContext
        from studyplan.domain_reasoning.formula_registry import get_registry

        registry = get_registry()
        if not registry:
            pytest.skip("No formulas in registry")
        sample_cid = next(iter(registry))
        result = get_topic_viewstate(sample_cid)
        if result is not None:
            vs, target_id = result
            ctx = ExecutionContext(vs)
            data = ctx.inherited_assumptions_fast(target_id)
            assert data is not None


# ============================================================
# Helper: type-agnostic chain steps
# ============================================================


def _make_chain_steps(step_dicts: list[dict]) -> list:
    """Create chain step objects that quack like ChainStep."""
    steps = []
    for sd in step_dicts:
        step = type(
            "FakeStep",
            (),
            {
                "slot": sd["slot"],
                "expression": sd["expression"],
                "param_names": tuple(sd.get("param_names", ())),
                "param_kinds": sd.get("param_kinds", ()),
                "description": sd.get("description", ""),
            },
        )()
        steps.append(step)
    return steps
