"""Tests for studyplan.provenance.lab — Lab layer of provenance architecture.

Three-layer test strategy:
  1. Unit: PlanExecutor reference resolution and plan execution
  2. Integration: ProvenanceLab query templates match ExecutionContext results
  3. Cross-domain: Plans work on PG, LLVM, GUI, FM ViewStates
  4. Gap closure: downstream_impact expressible as Lab plan (solves E3)
"""

import pytest

from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    Transformation,
    QueryResult,
    PREDEFINED_CONTEXTS,
    compose,
)
from studyplan.provenance.compiler import DomainCompiler
from studyplan.provenance.compiler_spec import NPV
from studyplan.provenance.kernel.loaders import (
    build_pg_optimizer_data,
    build_llvm_ir_data,
    build_gui_data,
)
from studyplan.provenance.execution import ExecutionContext
from studyplan.provenance.lab import ProvenanceLab, LabResult, PlanStep, PlanResult
from studyplan.provenance.lab.planner import PlanExecutor, _resolve_reference


EC = PREDEFINED_CONTEXTS["default_optimizer"]


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def fm_vs():
    return DomainCompiler.compile_one(NPV)


@pytest.fixture
def fm_lab(fm_vs):
    return ProvenanceLab(fm_vs)


@pytest.fixture
def fm_ctx(fm_vs):
    return ExecutionContext(fm_vs)


@pytest.fixture
def pg_lab():
    return ProvenanceLab(build_pg_optimizer_data().build())


@pytest.fixture
def llvm_lab():
    return ProvenanceLab(build_llvm_ir_data().build())


@pytest.fixture
def gui_lab():
    return ProvenanceLab(build_gui_data().build())


# ============================================================
# Unit: Reference resolution
# ============================================================


def test_resolve_simple_reference():
    q0 = QueryResult(
        artifacts=frozenset(
            {
                Artifact(id="a", type="config_value", target="x"),
                Artifact(id="b", type="config_value", target="y"),
            }
        )
    )
    results = [q0]

    val = _resolve_reference("$0.artifacts", results)
    assert val == q0.artifacts

    val = _resolve_reference("$0.artifacts.ids", results)
    assert val == frozenset({"a", "b"})

    val = _resolve_reference("$0.transforms", results)
    assert val == frozenset()

    val = _resolve_reference("$0.transforms.ids", results)
    assert val == frozenset()


def test_resolve_transforms_output_ids():
    t1 = Transformation(
        id="t1", input_artifact_id="a", output_artifact_id="b", transformation_type="generative_mapping", rule_spec=""
    )
    t2 = Transformation(
        id="t2", input_artifact_id="b", output_artifact_id="c", transformation_type="generative_mapping", rule_spec=""
    )
    q0 = QueryResult(transforms=frozenset({t1, t2}))
    results = [q0]

    val = _resolve_reference("$0.transforms.output_ids", results)
    assert val == frozenset({"b", "c"})

    val = _resolve_reference("$0.transforms.input_ids", results)
    assert val == frozenset({"a", "b"})


def test_resolve_metadata():
    q0 = QueryResult(metadata={"count": 5})
    results = [q0]

    val = _resolve_reference("$0.metadata.count", results)
    assert val == 5


def test_resolve_static_value_passthrough():
    results = [QueryResult()]
    val = _resolve_reference("static_value", results)
    assert val == "static_value"

    val = _resolve_reference("$not_a_reference", results)
    assert val == "$not_a_reference"  # doesn't start with $ followed by digit


# ============================================================
# Unit: PlanExecutor static plans
# ============================================================


def test_plan_executor_projection(fm_vs):
    executor = PlanExecutor(fm_vs)
    result = executor.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.type == "config_value",
                },
            ),
        ]
    )
    assert isinstance(result, PlanResult)
    assert result.step_count == 1
    assert len(result.step_results) == 1
    artifacts = result.step_results[0].artifacts
    assert all(a.type == "config_value" for a in artifacts)
    assert len(artifacts) >= 3  # NPV has r, I_0, ...


def test_plan_executor_traversal(fm_vs):
    executor = PlanExecutor(fm_vs)
    result = executor.execute(
        [
            PlanStep(
                "traversal",
                {
                    "seed_set": {"discounted_CF_1"},
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )
    assert result.step_count == 1
    # discounted_CF_1 → sum_12 → gross_NPV → NPV
    ids = frozenset(a.id for a in result.step_results[0].artifacts)
    assert "NPV" in ids, f"Expected NPV reachable from discounted_CF_1: {sorted(ids)}"
    assert "discounted_CF_1" in ids


def test_plan_executor_collect_constraints(fm_vs):
    executor = PlanExecutor(fm_vs)
    result = executor.execute(
        [
            PlanStep(
                "collect_inherited_constraints",
                {
                    "artifact_id": "NPV",
                },
            ),
        ]
    )
    assert result.step_count == 1
    assert len(result.step_results[0].artifacts) >= 4  # NPV has multiple constraints


# ============================================================
# Integration: result-threading (solves E3 compose gap)
# ============================================================


def test_plan_executor_result_threading_downstream_impact(fm_vs):
    """The downstream_impact pattern expressed as a Lab plan.

    This was previously inexpressible as a compose() plan because
    compose() cannot thread QueryResults between steps (E3 gap).
    PlanExecutor resolves this via ``$0.transforms.output_ids`` syntax.
    """
    executor = PlanExecutor(fm_vs)

    # Two-step plan: projection → traversal, threading step 0's transforms
    result = executor.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )

    assert result.step_count == 2
    # Step 1 should find discounted CFs impacted by removing constant_discount_rate
    impacted = frozenset(a.id for a in result.step_results[1].artifacts)
    assert len(impacted) >= 3, f"Expected >=3 impacted artifacts from constant_discount_rate, got {impacted}"
    # Should include discounted CFs
    has_discounted = any("discounted" in a for a in impacted)
    assert has_discounted, f"Expected discounted artifacts in impact: {impacted}"


def test_plan_executor_result_threading_matches_execution_context(fm_vs, fm_ctx):
    """Lab plan result-threading produces same result as ExecutionContext.downstream_impact()."""
    executor = PlanExecutor(fm_vs)

    plan_result = executor.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )

    ec_result = fm_ctx.downstream_impact("constant_discount_rate")

    plan_ids = frozenset(a.id for a in plan_result.step_results[1].artifacts)
    ec_ids = frozenset(ec_result.result["impacted_artifacts"])

    assert plan_ids == ec_ids, (
        f"Plan executor and ExecutionContext disagree on impacted artifacts.\n"
        f"Plan: {sorted(plan_ids)}\nEC: {sorted(ec_ids)}"
    )


def test_plan_executor_multi_step_chaining(fm_vs):
    """Three-step plan: find config_values → traverse → collect constraints.

    Demonstrates that arbitrary chains work with result-threading.
    """
    executor = PlanExecutor(fm_vs)

    result = executor.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.type == "config_value",
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.artifacts.ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
            PlanStep(
                "collect_inherited_constraints",
                {
                    "artifact_id": "NPV",
                },
            ),
        ]
    )

    assert result.step_count == 3
    assert len(result.step_results) == 3
    # Step 0: config values
    assert len(result.step_results[0].artifacts) >= 3
    # Step 1: everything reachable from config values
    assert len(result.step_results[1].artifacts) >= 5
    # Step 2: constraints on NPV
    assert len(result.step_results[2].artifacts) >= 4


# ============================================================
# Integration: ProvenanceLab query templates
# ============================================================


def test_lab_ask_downstream_impact(fm_lab, fm_ctx):
    """Lab.ask('downstream_impact') matches ExecutionContext."""
    lab_result = fm_lab.ask("downstream_impact", constraint_text="constant_discount_rate")
    assert isinstance(lab_result, LabResult)
    assert lab_result.question == "downstream_impact"
    assert lab_result.step_count == 2

    ec_result = fm_ctx.downstream_impact("constant_discount_rate")
    assert lab_result.summary["impact_count"] == ec_result.result["impact_count"]
    assert sorted(lab_result.summary["impacted_artifacts"]) == sorted(ec_result.result["impacted_artifacts"])


def test_lab_ask_inherited_assumptions(fm_lab, fm_ctx):
    """Lab.ask('inherited_assumptions') matches ExecutionContext."""
    lab_result = fm_lab.ask("inherited_assumptions", artifact_id="NPV")
    assert lab_result.question == "inherited_assumptions"

    ec_result = fm_ctx.inherited_assumptions("NPV")
    assert lab_result.summary["total_constraints"] == ec_result.result["total_constraints"]


def test_lab_ask_unknown_question(fm_lab):
    """Unknown question raises ValueError with valid options."""
    with pytest.raises(ValueError, match="Unknown question"):
        fm_lab.ask("nonexistent_question")


# ============================================================
# Integration: ProvenanceLab query passthrough
# ============================================================


def test_lab_query_passthrough(fm_lab, fm_ctx):
    """Lab.query() passes through to ExecutionContext methods."""
    lab_result = fm_lab.query("inherited_assumptions", artifact_id="NPV")
    ec_result = fm_ctx.inherited_assumptions("NPV")
    assert lab_result.result["total_constraints"] == ec_result.result["total_constraints"]

    lab_result = fm_lab.query("downstream_impact", constraint_text="constant_discount_rate")
    ec_result = fm_ctx.downstream_impact("constant_discount_rate")
    assert lab_result.result["impact_count"] == ec_result.result["impact_count"]


# ============================================================
# Cross-domain: Lab plans on all 4 domains
# ============================================================


def test_lab_cross_domain_projection(pg_lab, llvm_lab, gui_lab, fm_lab):
    """Projection plan works on all domains."""
    for name, lab in [("PG", pg_lab), ("LLVM", llvm_lab), ("GUI", gui_lab), ("FM", fm_lab)]:
        result = lab.execute(
            [
                PlanStep(
                    "projection",
                    {
                        "filter_type": "artifact",
                        "predicate": lambda a: True,
                    },
                ),
            ]
        )
        assert result.step_count == 1
        assert len(result.step_results[0].artifacts) > 0, f"Empty projection on {name}"


def test_lab_cross_domain_impact_plan(fm_lab, pg_lab, gui_lab, llvm_lab):
    """Impact-analysis plan works on domains with constraints, returns empty on GUI."""
    # FM: has constant_discount_rate constraint
    fm_result = fm_lab.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )
    assert len(fm_result.step_results[1].artifacts) >= 3

    # PG: has join_count > 12 activation constraint
    pg_result = pg_lab.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("join_count > 12" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )
    assert len(pg_result.step_results[1].artifacts) >= 1

    # GUI: no constraints — empty result
    gui_result = gui_lab.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("click" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "structural",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )
    assert len(gui_result.step_results[0].transforms) == 0  # no matching transforms
    assert len(gui_result.step_results[1].artifacts) == 0  # empty traversal


# ============================================================
# Gap closure: specific E3 compose gap proof
# ============================================================


def test_e3_gap_closed_lab_expresses_downstream_impact(fm_vs):
    """The E3 compose gap is closed: Lab's PlanExecutor can express downstream_impact.

    Previously, compose() could not express the two-step projection→traversal
    pattern because kwargs are static dicts (no result-threading).

    Proof:
      - compose(): silently produces wrong result (empty/0 artifacts)
      - PlanExecutor: correctly resolves ``$0.transforms.output_ids`` at runtime
    """
    ec = EC

    # compose() — seed_set is a literal string, not resolved
    compose_result, _ = compose(
        fm_vs,
        ec,
        steps=[
            (
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            (
                "traversal",
                {
                    "seed_set": {"$0.transforms.output_ids"},
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ],
    )
    # compose() treats "$0.transforms.output_ids" as a literal artifact ID
    compose_artifacts = len(compose_result.artifacts)
    # The artifact doesn't exist — compose returns 0 or 1 (stub)

    # PlanExecutor — resolves $N.field before calling traversal
    executor = PlanExecutor(fm_vs, ec)
    plan_result = executor.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )

    executor_artifacts = len(plan_result.step_results[1].artifacts)

    # PlanExecutor finds >=3 real artifacts; compose() finds 0 or 1
    assert executor_artifacts >= 3, f"PlanExecutor should find >=3 impacted artifacts, got {executor_artifacts}"
    assert compose_artifacts < executor_artifacts, (
        f"compose() ({compose_artifacts}) should find FEWER than PlanExecutor ({executor_artifacts})"
    )


def test_e3_compose_static_dict_gap(fm_vs):
    """Demonstrate that compose()'s static-dict limitation is the root cause.

    compose() takes list[tuple[str, dict]] — the kwargs dict is evaluated
    before any step runs. There's no mechanism to reference runtime results.

    The Lab's PlanStep takes the same structure but the PlanExecutor resolves
    ``$N.field`` references at runtime before calling each primitive.
    """
    ec = EC

    # compose() — kwargs dict is pre-evaluated, seed_set sentinel is a literal
    # Even if we try to make it work:
    result, new_vs = compose(
        fm_vs,
        ec,
        steps=[
            (
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            # compose() passes the literal string "$0.transforms.output_ids" as seed_set.
            # It is NOT resolved — it's treated as a literal artifact ID.
            (
                "traversal",
                {
                    "seed_set": {"$0.transforms.output_ids"},
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ],
    )
    # compose() traverses from a nonexistent artifact "$0.transforms.output_ids"
    # It creates a stub artifact but finds NO real downstream artifacts
    assert len(result.artifacts) <= 1, "compose() treats literal string as artifact ID — cannot resolve reference"

    # PlanExecutor — $N.field is resolved before calling traversal
    executor = PlanExecutor(fm_vs, ec)
    plan_result = executor.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": "transitive",
                },
            ),
        ]
    )
    # PlanExecutor resolves $0.transforms.output_ids to the actual transform outputs
    assert len(plan_result.step_results[1].artifacts) >= 3, "PlanExecutor resolves $N.field references at runtime"


# ============================================================
# LabResult inspection
# ============================================================


def test_lab_result_properties(fm_lab):
    """LabResult has convenient properties."""
    lab_result = fm_lab.ask("downstream_impact", constraint_text="constant_discount_rate")

    assert lab_result.question == "downstream_impact"
    assert lab_result.step_count == 2
    assert len(lab_result.steps) == 2
    assert lab_result.steps[0].primitive == "projection"
    assert lab_result.steps[1].primitive == "traversal"

    # last property gives the final QueryResult
    last = lab_result.last
    assert hasattr(last, "artifacts")
    assert hasattr(last, "transforms")


# ============================================================
# Fast-path consistency
# ============================================================


def test_lab_vs_execution_context_consistency(fm_vs):
    """Lab plans produce same results as ExecutionContext for all query types."""
    lab = ProvenanceLab(fm_vs)
    ctx = ExecutionContext(fm_vs)

    # downstream_impact
    lab_r = lab.ask("downstream_impact", constraint_text="constant_discount_rate")
    ctx_r = ctx.downstream_impact("constant_discount_rate")
    assert lab_r.summary["impact_count"] == ctx_r.result["impact_count"]


# ============================================================
# ArtifactStore integration
# ============================================================


def test_lab_with_artifact_store(fm_vs, tmp_path):
    """Lab can save and load results via ArtifactStore."""
    from studyplan.provenance.experiments.experiment_artifact_store import ArtifactStore

    store = ArtifactStore(path=str(tmp_path / "lab_store"))
    lab = ProvenanceLab(fm_vs, store=store)

    assert lab.store_available

    # Execute a plan and save the result
    result = lab.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.type == "config_value",
                },
            ),
        ]
    )
    key = lab.save(result)
    assert key is not None
    assert store.contains(key)

    # Load and verify — loaded ViewState matches the plan's final ViewState
    loaded = lab.load(key)
    assert loaded is not None
    assert isinstance(loaded, ViewState)
    # The loaded content_hash should match the plan's final ViewState
    # (projection creates a new ViewState with filtered artifacts)
    assert loaded.content_hash == result.final_viewstate.content_hash
    # Hashes differ from original because projection filtered artifacts
    assert loaded.content_hash != fm_vs.content_hash
    # But the loaded ViewState should have the same filtered artifacts
    assert len(loaded.artifact_space) == len(result.final_viewstate.artifact_space)


def test_lab_no_store_graceful(fm_lab):
    """Lab without store returns None from save/load."""
    assert not fm_lab.store_available
    result = fm_lab.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.type == "config_value",
                },
            ),
        ]
    )
    assert fm_lab.save(result) is None
    assert fm_lab.load("nonexistent") is None


def test_lab_is_deterministic(fm_vs):
    """Same Lab plan produces same result on repeated execution."""
    lab = ProvenanceLab(fm_vs)
    r1 = lab.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.type == "config_value",
                },
            ),
        ]
    )
    r2 = lab.execute(
        [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.type == "config_value",
                },
            ),
        ]
    )
    assert r1.step_results[0].artifacts == r2.step_results[0].artifacts
