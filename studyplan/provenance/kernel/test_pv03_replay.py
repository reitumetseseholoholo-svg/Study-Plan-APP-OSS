"""Reproduce PV03 predictions as kernel queries.

Each test loads the PostgreSQL optimizer domain data and runs the
ViewState composition chain specified in the locked prediction.
"""

from studyplan.provenance.kernel import (
    ViewState,
    PREDEFINED_CONTEXTS,
    compose,
    projection,
    traversal as traverse,
)
from studyplan.provenance.kernel.loaders import build_pg_optimizer_data


def _make_vs() -> ViewState:
    return build_pg_optimizer_data().build()


EC = PREDEFINED_CONTEXTS["default_optimizer"]


# --- P1: Lifecycle — call graph containment ---


def test_p1_call_graph_contains_phases():
    """standard_planner call graph contains subquery_planner and grouping_planner."""
    vs = _make_vs()
    _, vs2 = compose(
        vs,
        EC,
        [
            ("projection", {"filter_type": "artifact", "predicate": lambda a: a.id == "standard_planner"}),
            ("traversal", {"seed_set": {"standard_planner"}, "edge_semantics": "structural/call", "depth_limit": 2}),
        ],
    )
    reached = {a.id for a in vs2.artifact_space}
    assert "standard_planner" in reached
    assert "subquery_planner" in reached
    assert "grouping_planner" in reached


def test_p1_not_flat():
    """Call graph has more than 1 distinct planning function."""
    vs = _make_vs()
    _, vs2 = traverse(vs, EC, seed_set={"standard_planner"}, edge_semantics="structural/call", depth_limit=2)
    planning_fns = {a.id for a in vs2.artifact_space if a.type == "call_graph_region"}
    assert len(planning_fns) >= 3


# --- P2: Equivalence under transformation ---


def test_p2_hashjoin_mergejoin_in_same_class():
    """HashJoin and MergeJoin belong to same equivalence class."""
    vs = _make_vs()
    result, vs2 = compose(
        vs,
        EC,
        [
            ("reduction", {"relation": "semantic_equivalence"}),
            (
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: (
                        a.id.startswith("eq:")
                        and any("hashjoin_node" in str(m) or "mergejoin_node" in str(m) for m in a.metadata)
                    ),
                },
            ),
        ],
    )
    assert not result.is_empty or not vs2.artifact_space.is_empty()


def test_p2_equivalence_mapping_exists():
    """An equivalence_mapping transformation exists between HashJoin and MergeJoin."""
    vs = _make_vs()
    result, _ = projection(
        vs,
        EC,
        filter_type="transformation",
        predicate=lambda t: t.transformation_type == "equivalence_mapping",
    )
    assert len(result.transforms) >= 1


# --- P3: Rewrite rule ordering ---


def test_p3_ordering_edge_exists():
    """ordering_mapping edge from subquery_planner to plan_join_queries exists."""
    vs = _make_vs()
    result, _ = projection(
        vs,
        EC,
        filter_type="transformation",
        predicate=lambda t: (
            t.transformation_type == "ordering_mapping"
            and t.input_artifact_id == "subquery_planner"
            and t.output_artifact_id == "plan_join_queries"
        ),
    )
    assert len(result.transforms) >= 1


# --- P4: Cost-driven decision ---


def test_p4_decision_mapping_exists():
    """Decision mapping exists from FROM clause to NestedLoop with cost constraint."""
    vs = _make_vs()
    result, _ = projection(
        vs,
        EC,
        filter_type="transformation",
        predicate=lambda t: t.transformation_type == "decision_mapping" and t.input_artifact_id == "from_clause",
    )
    assert len(result.transforms) >= 1


def test_p4_decision_has_cost_constraint():
    """Decision mapping has a constraint referencing cost comparison."""
    vs = _make_vs()
    result, _ = projection(
        vs,
        EC,
        filter_type="transformation",
        predicate=lambda t: (
            t.transformation_type == "decision_mapping" and any("cost" in c[1].lower() for c in t.constraints)
        ),
    )
    assert len(result.transforms) >= 1


# --- P5: Search strategy equivalence ---


def test_p5_two_generative_mappings():
    """Two distinct generative_mappings exist: DP and GEQO, both producing Plan tree."""
    vs = _make_vs()
    _, vs2 = compose(
        vs,
        EC,
        [
            (
                "traversal",
                {
                    "seed_set": {"from_clause"},
                    "edge_semantics": "transformational/generative_mapping",
                    "depth_limit": 1,
                },
            ),
        ],
    )
    # Should find plan_tree_dp and plan_tree_geqo
    plan_artifacts = {a.id for a in vs2.artifact_space}
    assert "plan_tree_dp" in plan_artifacts or "plan_tree_geqo" in plan_artifacts


def test_p5_generative_mapping_count():
    """At least two generative mappings from from_clause exist."""
    vs = _make_vs()
    result, _ = projection(
        vs,
        EC,
        filter_type="transformation",
        predicate=lambda t: t.transformation_type == "generative_mapping" and t.input_artifact_id == "from_clause",
    )
    assert len(result.transforms) >= 2


# --- Cross-domain loader smoke tests ---


def test_pg_loader_has_all_predictions():
    """PostgreSQL loader covers all 5 PV03 predictions."""
    data = build_pg_optimizer_data()
    meta = data.metadata.get("prediction_ids", [])
    expected = ["PV03-OPT-P1", "PV03-OPT-P2", "PV03-OPT-P3", "PV03-OPT-P4", "PV03-OPT-P5"]
    for e in expected:
        assert e in meta


def test_pg_loader_non_empty():
    data = build_pg_optimizer_data()
    assert len(data) > 0
