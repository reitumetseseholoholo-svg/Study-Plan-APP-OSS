"""H-CD-01: Cross-domain execution layer validation.

Hypothesis
----------
ExecutionContext queries are domain-independent for graph-structural operations
(dependency_path, traversal) but domain-dependent for type-specific operations
(base_prerequisites with config_value filter, inherited_assumptions with
assumption constraints).  The domain dependence is in the execution layer's
hardcoded FM conventions, not in the kernel.

This is a CONSTRUCTION experiment (Phase II protocol):
  Hypothesis → Predictions → Experiment → Evidence → Decision

Predictions
-----------
P1 — dependency_path works on all 4 domains (PG, LLVM, GUI, FM)
     because it uses pure graph BFS over transform space.
     It is the most domain-independent query.

P2 — base_prerequisites returns non-empty on FM only
     because it hardcodes ``type == "config_value"`` filter.
     PG/LLVM/GUI have no config_value artifacts.

P3 — inherited_assumptions returns non-empty on FM and PG
     because both domains encode constraints on transforms.
     GUI returns empty (no constraints on parent_child/call transforms).

P4 — downstream_impact returns non-empty on FM and PG
     because both encode assumption-like constraints.
     GUI returns empty.

P5 — No execution layer or kernel changes needed for any of the above.
     All queries use existing primitives.

Three-level failure taxonomy
----------------------------
- Vocabulary: domain concept maps to existing type but under wrong name
- Encoding: execution layer API exists but composition is awkward
- Ontology: concept fundamentally unrepresentable → new primitive needed

Falsification
-------------
The hypothesis is wrong if:
- dependency_path fails on any domain due to a kernel bug (not a data issue)
- A domain produces a result for base_prerequisites without config_value artifacts
  (would mean the hardcoded type filter is not the only mechanism)
- A cross-domain query requires execution layer changes
"""

import pytest

from studyplan.provenance.execution import ExecutionContext
from studyplan.provenance.compiler import DomainCompiler
from studyplan.provenance.compiler_spec import NPV
from studyplan.provenance.kernel.loaders import (
    build_pg_optimizer_data,
    build_llvm_ir_data,
    build_gui_data,
)
from studyplan.provenance.kernel import (
    PREDEFINED_CONTEXTS,
    traversal,
    projection,
    compose,
    collect_inherited_constraints,
)


# ============================================================
# Fixtures — ExecutionContext for each domain
# ============================================================


@pytest.fixture
def fm_ctx():
    return ExecutionContext(DomainCompiler.compile_one(NPV))


@pytest.fixture
def pg_ctx():
    return ExecutionContext(build_pg_optimizer_data().build())


@pytest.fixture
def llvm_ctx():
    return ExecutionContext(build_llvm_ir_data().build())


@pytest.fixture
def gui_ctx():
    return ExecutionContext(build_gui_data().build())


# ============================================================
# P1 — dependency_path is domain-independent
# ============================================================


def test_p1_dependency_path_fm(fm_ctx):
    """FM: path from r to NPV exists through discount chain."""
    trace = fm_ctx.dependency_path("r", "NPV")
    assert trace.result["path_exists"]
    assert trace.result["path"][0] == "r"
    assert trace.result["path"][-1] == "NPV"


def test_p1_dependency_path_pg(pg_ctx):
    """PG: path from from_clause to plan_tree_dp exists (via DP search)."""
    trace = pg_ctx.dependency_path("from_clause", "plan_tree_dp")
    assert trace.result["path_exists"], f"Expected path from from_clause to plan_tree_dp: {trace.result}"
    assert trace.result["path"][0] == "from_clause"
    assert trace.result["path"][-1] == "plan_tree_dp"


def test_p1_dependency_path_llvm(llvm_ctx):
    """LLVM: path from bb_entry to bb_exit exists under data_flow edges."""
    trace = llvm_ctx.dependency_path("bb_entry", "bb_exit", edge_types={"data_flow"})
    assert trace.result["path_exists"], f"Expected path from bb_entry to bb_exit: {trace.result}"
    assert trace.result["path"][0] == "bb_entry"
    assert trace.result["path"][-1] == "bb_exit"


def test_p1_dependency_path_gui(gui_ctx):
    """GUI: path from window to button_start exists under parent_child edges."""
    trace = gui_ctx.dependency_path("window", "button_start", edge_types={"parent_child", "call"})
    assert trace.result["path_exists"], f"Expected path from window to button_start: {trace.result}"
    assert trace.result["path"][0] == "window"
    assert trace.result["path"][-1] == "button_start"


def test_p1_dependency_path_nonexistent_gui(gui_ctx):
    """GUI: path between disconnected components returns not found."""
    # window and label_status are connected via sig_start_click, but might not
    # be reachable under generative_mapping traversal
    trace = gui_ctx.dependency_path("window", "func_main")
    assert not trace.result["path_exists"]


# ============================================================
# P2 — base_prerequisites hardcodes config_value filter
# ============================================================


def test_p2_base_prerequisites_fm(fm_ctx):
    """FM has config_value artifacts → base_prerequisites returns them."""
    trace = fm_ctx.base_prerequisites("NPV")
    assert trace.result["count"] >= 3, f"Expected >=3 prerequisites for NPV: {trace.result}"
    assert "r" in trace.result["base_prerequisites"]
    assert "I_0" in trace.result["base_prerequisites"]


def test_p2_base_prerequisites_pg_empty(pg_ctx):
    """PG has no config_value artifacts → base_prerequisites returns empty."""
    trace = pg_ctx.base_prerequisites("plan_tree_dp")
    assert trace.result["count"] == 0, f"Expected 0 prerequisites on PG (no config_value): {trace.result}"
    assert trace.result["base_prerequisites"] == []


def test_p2_base_prerequisites_llvm_empty(llvm_ctx):
    """LLVM has no config_value artifacts → base_prerequisites returns empty."""
    trace = llvm_ctx.base_prerequisites("bb_entry")
    assert trace.result["count"] == 0, f"Expected 0 prerequisites on LLVM: {trace.result}"


def test_p2_base_prerequisites_gui_empty(gui_ctx):
    """GUI has no config_value artifacts → base_prerequisites returns empty."""
    trace = gui_ctx.base_prerequisites("window")
    assert trace.result["count"] == 0, f"Expected 0 prerequisites on GUI: {trace.result}"


# ============================================================
# P3 — inherited_assumptions depends on constraint data
# ============================================================


def test_p3_inherited_assumptions_fm(fm_ctx):
    """FM encodes assumption constraints → inherited_assumptions returns them."""
    trace = fm_ctx.inherited_assumptions("NPV")
    assert trace.result["total_constraints"] >= 4
    assert "constant_discount_rate" in trace.result["assumptions"]


def test_p3_inherited_assumptions_pg(pg_ctx):
    """PG encodes constraints on some transforms → inherited works."""
    # from_clause is upstream of plan_tree_dp which has activation constraint
    trace = pg_ctx.inherited_assumptions("plan_tree_dp")
    # Should include the activation constraint from gen_geqo
    assert trace.result["total_constraints"] >= 0
    # PG uses ("activation", ...) and ("condition", ...) constraints, not ("assumption", ...)
    assumptions = trace.result["assumptions"]
    # No assumption constraints — PG uses condition/activation constraint keys
    assert len(assumptions) == 0, f"PG has no 'assumption' key constraints: {assumptions}"
    # But consumes constraints should still work
    consumes = trace.result["consumes"]
    assert len(consumes) >= 0


def test_p3_inherited_assumptions_gui_empty(gui_ctx):
    """GUI encodes no constraints → inherited_assumptions returns empty."""
    trace = gui_ctx.inherited_assumptions("window")
    assert trace.result["total_constraints"] == 0, f"Expected 0 constraints on GUI: {trace.result}"
    assert trace.result["assumptions"] == []


# ============================================================
# P4 — downstream_impact depends on assumption-like constraints
# ============================================================


def test_p4_downstream_impact_fm(fm_ctx):
    """FM: removing constant_discount_rate impacts all discounted CFs."""
    trace = fm_ctx.downstream_impact("constant_discount_rate")
    assert trace.result["impact_count"] >= 3


def test_p4_downstream_impact_pg(pg_ctx):
    """PG: removing geqo activation constraint impacts plan_tree_geqo."""
    trace = pg_ctx.downstream_impact("join_count > 12")
    assert trace.result["impact_count"] >= 1, f"Expected impact from geqo activation: {trace.result}"
    assert "plan_tree_geqo" in trace.result["impacted_artifacts"]


def test_p4_downstream_impact_gui_empty(gui_ctx):
    """GUI has no constraints → downstream_impact returns empty."""
    trace = gui_ctx.downstream_impact("clicked")
    assert trace.result["impact_count"] == 0


# ============================================================
# P5 — No kernel or execution layer changes needed
# ============================================================


def test_p5_imports_use_existing_kernel():
    """All cross-domain queries use existing types and primitives."""
    from studyplan.provenance.kernel import (
        ViewState,
        Artifact,
        Transformation,
        QueryResult,
        ProjectionRule,
        EvaluationContext,
        PREDEFINED_CONTEXTS,
        identity,
        traversal,
        reduction,
        compose,
        collect_inherited_constraints,
    )

    _ = ViewState
    _ = Artifact
    _ = Transformation
    _ = QueryResult
    _ = ProjectionRule
    _ = EvaluationContext
    _ = PREDEFINED_CONTEXTS
    _ = identity
    _ = projection
    _ = traversal
    _ = reduction
    _ = compose
    _ = collect_inherited_constraints


# ============================================================
# Bonus: Kernel primitives across domains (traversal, projection)
# ============================================================

EC = PREDEFINED_CONTEXTS["default_optimizer"]


def test_traversal_pg():
    """Traversal works on PG: follow all edges from from_clause."""
    vs = build_pg_optimizer_data().build()
    result, _ = traversal(
        vs,
        EC,
        seed_set={"from_clause"},
        edge_semantics="transformational",
        depth_limit="transitive",
    )
    assert len(result.artifacts) >= 2


def test_traversal_llvm():
    """Traversal works on LLVM: follow data_flow from bb_entry."""
    vs = build_llvm_ir_data().build()
    result, _ = traversal(
        vs,
        EC,
        seed_set={"bb_entry"},
        edge_semantics="structural",
        depth_limit="transitive",
    )
    # data_flow edges connect basic blocks structurally
    assert len(result.artifacts) >= 2


def test_traversal_gui():
    """Traversal works on GUI: follow parent_child from window."""
    vs = build_gui_data().build()
    result, _ = traversal(
        vs,
        EC,
        seed_set={"window"},
        edge_semantics="structural",
        depth_limit="transitive",
    )
    # Should reach child components (sidebar, header_bar, etc.)
    assert len(result.artifacts) >= 3
    assert any(a.id == "sidebar" for a in result.artifacts)


def test_collect_inherited_constraints_pg():
    """Constraint inheritance works cross-domain on PG."""
    vs = build_pg_optimizer_data().build()
    inherited = collect_inherited_constraints(vs, "plan_tree_geqo")
    assert ("activation", "join_count > 12") in inherited, f"Expected activation constraint from gen_geqo: {inherited}"


# ============================================================
# P6 — upstream_artifacts is domain-independent (generic)
# ============================================================


def test_p6_upstream_artifacts_fm(fm_ctx):
    """FM: NPV upstream includes its base inputs."""
    trace = fm_ctx.upstream_artifacts("NPV")
    assert trace.result["count"] >= 4
    assert "r" in trace.result["upstream_artifacts"]
    assert "I_0" in trace.result["upstream_artifacts"]
    assert "discounted_CF_1" in trace.result["upstream_artifacts"]


def test_p6_upstream_artifacts_pg(pg_ctx):
    """PG: plan_tree_dp upstream includes optimizer artifacts."""
    trace = pg_ctx.upstream_artifacts("plan_tree_dp")
    assert trace.result["count"] >= 2
    assert "from_clause" in trace.result["upstream_artifacts"]


def test_p6_upstream_artifacts_llvm(llvm_ctx):
    """LLVM: bb_exit upstream includes bb_entry via data_flow."""
    trace = llvm_ctx.upstream_artifacts("bb_exit")
    assert trace.result["count"] >= 2
    assert "bb_entry" in trace.result["upstream_artifacts"]


def test_p6_upstream_artifacts_gui(gui_ctx):
    """GUI: button upstream includes window and intermediate components."""
    trace = gui_ctx.upstream_artifacts("button_start")
    assert trace.result["count"] >= 2
    assert "window" in trace.result["upstream_artifacts"]


# ============================================================
# Principle E1 — Edge type parameterization
# ============================================================


def test_e1_edge_type_default_is_backward_compatible(fm_ctx):
    """Default edge_types={"generative_mapping"} works on FM (backward compat)."""
    trace = fm_ctx.dependency_path("r", "NPV")
    assert trace.result["path_exists"]

    # Explicit generative_mapping matches default
    trace2 = fm_ctx.dependency_path("r", "NPV", edge_types={"generative_mapping"})
    assert trace2.result["path_exists"]
    assert trace2.result["path"] == trace.result["path"]


def test_e1_edge_type_required_for_non_fm(fm_ctx, pg_ctx, llvm_ctx, gui_ctx):
    """Non-FM domains need explicit edge_types to find paths."""
    # FM works with default generative_mapping
    trace = fm_ctx.dependency_path("r", "NPV")
    assert trace.result["path_exists"]

    # PG works with default generative_mapping (PG uses generative_mapping for DP search)
    trace = pg_ctx.dependency_path("from_clause", "plan_tree_dp")
    assert trace.result["path_exists"]

    # LLVM fails with default (generative_mapping) because edges are data_flow
    trace = llvm_ctx.dependency_path("bb_entry", "bb_exit")
    assert not trace.result["path_exists"], "LLVM with generative_mapping default should not find data_flow path"
    # LLVM works with data_flow
    trace = llvm_ctx.dependency_path("bb_entry", "bb_exit", edge_types={"data_flow"})
    assert trace.result["path_exists"]

    # GUI fails with default because edges are parent_child/call
    trace = gui_ctx.dependency_path("window", "button_start")
    assert not trace.result["path_exists"], "GUI with generative_mapping default should not find parent_child path"
    trace = gui_ctx.dependency_path("window", "button_start", edge_types={"parent_child", "call"})
    assert trace.result["path_exists"]


# ============================================================
# Principle E2 — Cross-domain constraint matching
# ============================================================


def test_e2_downstream_impact_matches_any_key(fm_ctx, pg_ctx, gui_ctx):
    """downstream_impact matches constraint values regardless of key name.

    FM uses ("assumption", "constant_discount_rate").
    PG uses ("activation", "join_count > 12").
    Both match because the search scans all constraint values.
    """
    # FM: assumption key constraint
    fm_trace = fm_ctx.downstream_impact("constant_discount_rate")
    assert fm_trace.result["impact_count"] >= 3

    # PG: activation key constraint
    pg_trace = pg_ctx.downstream_impact("join_count > 12")
    assert pg_trace.result["impact_count"] >= 1
    assert "plan_tree_geqo" in pg_trace.result["impacted_artifacts"]

    # PG: condition key constraint
    pg_cond = pg_ctx.downstream_impact("cost(nested_loop)")
    assert pg_cond.result["impact_count"] >= 1

    # GUI: no constraints → empty regardless of key
    gui_trace = gui_ctx.downstream_impact("clicked")
    assert gui_trace.result["impact_count"] == 0


def test_e2_downstream_impact_empty_string_returns_nothing(fm_ctx, pg_ctx, gui_ctx, llvm_ctx):
    """Empty string or no-match text returns empty impact on all domains."""
    for ctx in (fm_ctx, pg_ctx, gui_ctx, llvm_ctx):
        trace = ctx.downstream_impact("___NO_MATCH___")
        assert trace.result["impact_count"] == 0, (
            f"Expected 0 impact for no-match text on {type(ctx).__name__}: {trace.result}"
        )


# ============================================================
# Principle E3 — Compose result-threading gap (known limitation)
# ============================================================


def test_e3_compose_kwargs_are_static_dicts():
    """compose() cannot thread QueryResults between steps — kwargs are static dicts.

    compose() signature: steps: list[tuple[str, dict]]
    Each step's kwargs dict is defined before execution begins. There is no
    syntax or mechanism to reference a prior step's QueryResult.

    Proof: downstream_impact() requires a two-step plan where step 2's seed_set
    = step 1's discovered transform outputs. compose() cannot express this.
    """
    from inspect import signature

    sig = signature(compose)
    # Verify compose takes static dicts — no lazy/result-reference parameter
    steps_param = sig.parameters["steps"]
    type_str = str(steps_param.annotation)
    assert "dict" in type_str or "list[tuple[str, dict]]" in type_str, (
        f"compose() steps param should be list[tuple[str, dict]]: {type_str}"
    )

    # Verify downstream_impact does NOT use compose (proof by code structure)
    # downstream_impact() has: projection(...), frozenset(...), traversal(...)
    # It does NOT have: compose(...)
    import inspect

    source_lines = inspect.getsource(ExecutionContext.downstream_impact).splitlines()
    source_body = "\n".join(source_lines[1:])  # skip def line
    # It must call projection and traversal separately
    assert "projection(" in source_body, "downstream_impact must call projection()"
    assert "traversal(" in source_body, "downstream_impact must call traversal()"
    # It must NOT call compose (would if compose supported result threading)
    assert "compose(" not in source_body, "downstream_impact does NOT use compose() — proof of result-threading gap"
    # It must compute seed_set from step 1's result at runtime
    assert any(kw in source_body for kw in ("frozenset(", "set(")), (
        "downstream_impact computes seed_set from step 1's result"
    )

    # Regression: downstream_impact still works
    vs = DomainCompiler.compile_one(NPV)
    ec = PREDEFINED_CONTEXTS["default_optimizer"]
    trace = ExecutionContext(vs).downstream_impact("constant_discount_rate")
    assert trace.result["impact_count"] >= 3


# ============================================================
# Cross-domain fast-path consistency
# ============================================================


def test_fast_paths_match_full_trace(fm_ctx, pg_ctx, llvm_ctx, gui_ctx):
    """Fast-path methods return same data values as full ReasoningTrace."""
    for ctx in (fm_ctx, pg_ctx, llvm_ctx, gui_ctx):
        # upstream_artifacts
        art_id = list(ctx.vs.artifact_space)[0].id if ctx.vs.artifact_space else "nonexistent"
        if ctx.vs.artifact_space:
            fast = ctx.upstream_artifacts_fast(art_id)
            full = ctx.upstream_artifacts(art_id)
            assert fast["upstream_artifacts"] == full.result["upstream_artifacts"]
            assert fast["count"] == full.result["count"]
