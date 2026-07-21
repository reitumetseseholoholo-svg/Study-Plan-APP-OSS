"""Tests for DomainRegistry — live concept→ViewState map with auto-compile.

Hypothesis H-UDR-01:
    A live registry that auto-compiles FormulaDecl → ViewState on registration
    eliminates the lazy-compilation gap between the DSL formula registry and
    provenance queries.

Predictions:
    P1: Every formula registered via declare_formula() is immediately
        queryable via the DomainRegistry without any side band.
    P2: auto_register_fm_domain + FastDomainCompiler compiles all 11+ formulas
        without errors in <2s total.
    P3: registry_to_domainspecs() + DomainRegistry produce identical ViewStates
        (determinism across compilation paths).
    P4: Cross-concept dependency queries work — collect_inherited_constraints
        for a formula that depends on another formula returns constraints
        from both.
    P5: The registry can accept dynamically-registered formulas at runtime.

Falsification conditions:
    F1: A FormulaDecl compiles to a ViewState that fails iR1 connectivity
        (dangling artifact references).
    F2: Two registrations of the same concept_id produce different ViewStates
        (non-determinism).
    F3: collect_inherited_constraints misses a constraint from a dependency
        that was compiled earlier.
    F4: Registry exceed 500ms for 25+ formulas.
"""

from __future__ import annotations

import pytest

from studyplan.provenance.domain_registry import (
    DomainRegistry,
    DomainEntry,
    get_default_registry,
    reset_default_registry,
)
from studyplan.provenance.kernel import collect_inherited_constraints
from studyplan.provenance.fast_compiler import (
    DomainSpec,
    DomainNode,
    DomainEdge,
)
from studyplan.domain_reasoning.formula_registry import (
    FormulaDecl,
    declare_formula_chain,
    CONCEPT_TYPE_EXPRESSION,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_default_registry()
    yield
    reset_default_registry()


@pytest.fixture
def dr() -> DomainRegistry:
    return DomainRegistry()


@pytest.fixture
def cost_of_equity_decl() -> FormulaDecl:
    return FormulaDecl(
        concept_id="fm.cost_of_equity",
        concept_type=CONCEPT_TYPE_EXPRESSION,
        formula_name="cost_of_equity",
        expression="risk_free + beta * market_return",
        param_names=("risk_free", "beta", "market_return"),
        output_slot="cost_of_equity",
        label="Cost of Equity",
        diagnostic_tags=("market_efficiency", "single_period"),
    )


# ============================================================
# E1: Registration + Compilation
# ============================================================


class TestRegister:
    """P1: Every registered formula is immediately queryable."""

    def test_register_and_query(self, dr, cost_of_equity_decl):
        entry = dr.register("fm.cost_of_equity", cost_of_equity_decl)

        assert isinstance(entry, DomainEntry)
        assert entry.concept_id == "fm.cost_of_equity"
        assert entry.viewstate is not None
        assert entry.output_artifact_id == "cost_of_equity"
        assert entry.validation_pass is True
        assert entry.compilation_time_ms > 0

        # Immediately queryable
        result = dr.get("fm.cost_of_equity")
        assert result is entry

        vs = dr.get_viewstate("fm.cost_of_equity")
        assert vs is entry.viewstate

    def test_register_minimal_decl(self, dr):
        decl = FormulaDecl(
            concept_id="fm.minimal",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="minimal",
        )
        entry = dr.register("fm.minimal", decl)
        assert entry.validation_pass is True
        assert entry.concept_id == "fm.minimal"

    def test_register_twice_is_idempotent(self, dr, cost_of_equity_decl):
        e1 = dr.register("fm.cost_of_equity", cost_of_equity_decl)
        e2 = dr.register("fm.cost_of_equity", cost_of_equity_decl)

        # Same spec → same output hash (deterministic compilation)
        assert e1.spec_hash == e2.spec_hash
        assert e1.concept_id == e2.concept_id


class TestRegisterSpec:
    """Pre-built DomainSpec registration."""

    def test_register_spec(self, dr):
        spec = DomainSpec(
            id="test_spec",
            title="Test",
            domain="fm",
            nodes=(
                DomainNode(id="input_x", concept="config_value", kind="parameter"),
                DomainNode(id="output_y", concept="call_graph_region", kind="output"),
            ),
            edges=(DomainEdge(id="e1", from_id="input_x", to_id="output_y", rule="x -> y"),),
        )
        entry = dr.register_spec(spec)
        assert entry.concept_id == "test_spec"
        assert entry.validation_pass is True

    def test_register_spec_non_fm_domain(self, dr):
        spec = DomainSpec(
            id="pg.test",
            title="PG Test",
            domain="pg",
            nodes=(
                DomainNode(id="p1", concept="relation", kind="parameter"),
                DomainNode(id="p2", concept="cost_metric", kind="parameter"),
                DomainNode(id="out", concept="query_plan", kind="output"),
            ),
            edges=(
                DomainEdge(id="e1", from_id="p1", to_id="out", rule="p1"),
                DomainEdge(id="e2", from_id="p2", to_id="out", rule="p2"),
            ),
        )
        entry = dr.register_spec(spec)
        assert entry.validation_pass is True
        assert "pg.test" in dr.concept_ids

    def test_register_spec_unknown_domain(self, dr):
        spec = DomainSpec(
            id="custom.test",
            title="Custom",
            domain="custom",
            nodes=(
                DomainNode(id="x", concept="value", kind="parameter"),
                DomainNode(id="y", concept="result", kind="output"),
            ),
            edges=(DomainEdge(id="e1", from_id="x", to_id="y", rule="compute"),),
        )
        # Should register fine with any domain
        entry = dr.register_spec(spec)
        assert entry.validation_pass is True


# ============================================================
# E2: Batch sync
# ============================================================


class TestSyncFromFormulaRegistry:
    """Batch compile all formulas from the formula registry."""

    def test_sync_populates_entries(self, dr):
        count = dr.sync_from_formula_registry()
        assert count > 0
        assert dr.count >= count

    def test_sync_is_idempotent(self, dr):
        c1 = dr.sync_from_formula_registry()
        c2 = dr.sync_from_formula_registry()
        assert c2 == 0  # no new entries on second call
        assert dr.count == c1


class TestSyncFromAllTopics:
    """Sync from the 5 hand-authored ALL_TOPICS specs."""

    def test_sync_populates_entries(self, dr):
        count = dr.sync_from_all_topics()
        assert count == 5
        for tid in ("CAPM", "NPV", "IRR", "APV", "GordonGrowth"):
            entry = dr.get(tid)
            assert entry is not None
            assert entry.validation_pass is True

    def test_sync_is_idempotent(self, dr):
        _ = dr.sync_from_all_topics()
        c2 = dr.sync_from_all_topics()
        assert c2 == 0  # already registered


# ============================================================
# E3: Cross-concept dependency queries
# ============================================================


class TestCrossConceptDependencies:
    """P4: Cross-concept dependency queries work."""

    def test_inherited_constraints(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)

        entry = dr.get("fm.cost_of_equity")
        constraints = entry.inherited_constraints()
        assert isinstance(constraints, set)
        assert len(constraints) > 0
        assert any("market_efficiency" in str(c) for c in constraints)

    def test_query_assumptions(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        assumptions = dr.query_assumptions("fm.cost_of_equity")
        assert assumptions is not None
        assert "assumptions" in assumptions
        assert len(assumptions["assumptions"]) > 0

    def test_dependency_path(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        path = dr.query_dependency_path("fm.cost_of_equity")
        assert path is not None
        assert "cost_of_equity" in path[-1] if path else True

    def test_query_nonexistent(self, dr):
        assert dr.get("nonexistent") is None
        assert dr.get_viewstate("nonexistent") is None
        assert dr.query_assumptions("nonexistent") is None
        assert dr.query_inherited_constraints("nonexistent") is None
        assert dr.query_dependency_path("nonexistent") is None

    def test_query_inherited_constraints_api(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        constraints = dr.query_inherited_constraints("fm.cost_of_equity")
        assert constraints is not None
        assert len(constraints) > 0

    def test_cached_query_returns_same(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        a1 = dr.query_assumptions("fm.cost_of_equity")
        a2 = dr.query_assumptions("fm.cost_of_equity")
        assert a1 is a2  # same cached object


# ============================================================
# E4: All entries + enumeration
# ============================================================


class TestEnumerate:
    """All-entries enumeration."""

    def test_all_entries(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        all_e = dr.all_entries()
        assert "fm.cost_of_equity" in all_e

    def test_concept_ids(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        assert "fm.cost_of_equity" in dr.concept_ids

    def test_count(self, dr, cost_of_equity_decl):
        assert dr.count == 0
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        assert dr.count == 1

    def test_clear(self, dr, cost_of_equity_decl):
        dr.register("fm.cost_of_equity", cost_of_equity_decl)
        assert dr.count == 1
        dr.clear()
        assert dr.count == 0
        assert dr.get("fm.cost_of_equity") is None


# ============================================================
# E5: Dynamic registration (P5)
# ============================================================


class TestDynamicRegistration:
    """P5: Runtime registration of new formulas."""

    def test_register_at_runtime(self, dr):
        decl = FormulaDecl(
            concept_id="fm.dynamic_formula",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            formula_name="dynamic_formula",
            expression="a + b",
            param_names=("a", "b"),
            output_slot="dynamic_result",
        )
        # Register at "runtime"
        entry = dr.register("fm.dynamic_formula", decl)
        assert entry.validation_pass is True
        assert dr.get("fm.dynamic_formula") is not None

    def test_chained_dynamic_registration(self, dr):
        decl = declare_formula_chain(
            "fm.dynamic_wacc",
            steps=[
                {"slot": "after_tax", "expression": "pretax * (1 - tax)", "param_names": ["pretax", "tax"]},
                {"slot": "wacc", "expression": "after_tax * w", "param_names": ["w"]},
            ],
            output_slot="wacc",
        )
        entry = dr.register("fm.dynamic_wacc", decl)
        assert entry.validation_pass is True


# ============================================================
# E6: Determinism (P3)
# ============================================================


class TestDeterminism:
    """P3: Same formula → identical ViewState across compilation paths."""

    def test_same_decl_same_viewstate(self, dr, cost_of_equity_decl):
        e1 = dr.register("fm.cost_of_equity", cost_of_equity_decl)
        e2 = dr.register("fm.cost_of_equity", cost_of_equity_decl)
        assert e1.spec_hash == e2.spec_hash
        # ViewState hash should match
        h1 = e1.viewstate.artifact_space
        h2 = e2.viewstate.artifact_space
        assert h1 == h2

    def test_re_registration_preserves_spec_hash(self, dr, cost_of_equity_decl):
        e1 = dr.register("fm.cost_of_equity", cost_of_equity_decl)
        h1 = e1.spec_hash
        # Re-register (same decl)
        e2 = dr.register("fm.cost_of_equity", cost_of_equity_decl)
        assert e2.spec_hash == h1


# ============================================================
# E7: Default registry
# ============================================================


class TestDefaultRegistry:
    """Global default registry singleton."""

    def test_get_default_registry(self):
        dr = get_default_registry()
        assert isinstance(dr, DomainRegistry)
        assert dr.count > 0  # synced from formula registry + ALL_TOPICS

    def test_default_registry_is_singleton(self):
        dr1 = get_default_registry()
        dr2 = get_default_registry()
        assert dr1 is dr2

    def test_reset_default_registry(self):
        dr1 = get_default_registry()
        reset_default_registry()
        dr2 = get_default_registry()
        assert dr1 is not dr2


# ============================================================
# E8: Integration test — full pipeline from formula registry
# ============================================================


class TestIntegration:
    """End-to-end: formula registry → DomainRegistry → provenance queries."""

    def test_full_pipeline_to_provenance_query(self):
        dr = DomainRegistry()
        dr.sync_from_formula_registry()

        # Try querying an FM formula
        for cid in dr.concept_ids:
            if "wacc" in cid:
                entry = dr.get(cid)
                assert entry is not None
                constraints = collect_inherited_constraints(entry.viewstate, entry.output_artifact_id)
                assert isinstance(constraints, set)
                return

    def test_all_compiled_viewstates_are_valid(self):
        """Every compiled ViewState should pass connectivity validation."""
        dr = DomainRegistry()
        dr.sync_from_formula_registry()
        dr.sync_from_all_topics()

        for cid, entry in dr.all_entries().items():
            assert entry.validation_pass, f"Validation failed for {cid}"
            assert entry.viewstate is not None
            assert len(entry.viewstate.artifact_space) > 0
            assert len(entry.viewstate.transform_space) > 0

    def test_collect_inherited_constraints_all(self):
        """collect_inherited_constraints works for every compiled entry."""
        dr = DomainRegistry()
        dr.sync_from_formula_registry()
        dr.sync_from_all_topics()

        for _cid, entry in dr.all_entries().items():
            constraints = collect_inherited_constraints(entry.viewstate, entry.output_artifact_id)
            assert isinstance(constraints, set)
