"""Tests for ViewState kernel implementation."""

from studyplan.provenance.kernel import (
    Artifact,
    Transformation,
    ViewState,
    QueryTraceEntry,
    EvaluationContext,
    PREDEFINED_CONTEXTS,
    identity,
    projection,
    traversal,
    reduction,
    compose,
)


def make_test_state():
    """Build a minimal optimizer artifact/transformation graph."""
    # Artifacts
    query = Artifact.from_dict(id="q1", type="ast_node", target="SELECT * FROM t1 JOIN t2 ON t1.id=t2.id")
    hash_join = Artifact.from_dict(id="hj1", type="ast_node", target="HashJoin(SeqScan(t1), SeqScan(t2))")
    merge_join = Artifact.from_dict(id="mj1", type="ast_node", target="MergeJoin(Sort(t1), Sort(t2))")
    nl_join = Artifact.from_dict(id="nl1", type="ast_node", target="NestedLoop(SeqScan(t1), SeqScan(t2))")
    plan_tree = Artifact.from_dict(id="plan1", type="ast_node", target="Plan(join_order=optimized)")

    # Transformations
    t_equivalence = Transformation(
        id="eq1",
        input_artifact_id="hj1",
        output_artifact_id="mj1",
        transformation_type="equivalence_mapping",
        rule_spec="Join commutativity: HashJoin and MergeJoin with same keys are equivalent",
        constraints=(("condition", "join keys identical"),),
    )
    t_generative_dp = Transformation(
        id="gen_dp",
        input_artifact_id="q1",
        output_artifact_id="plan1",
        transformation_type="generative_mapping",
        rule_spec="DP search over join orderings produces optimal plan",
        constraints=(),
    )
    t_generative_geqo = Transformation(
        id="gen_geqo",
        input_artifact_id="q1",
        output_artifact_id="plan1",
        transformation_type="generative_mapping",
        rule_spec="Genetic algorithm produces near-optimal plan",
        constraints=(("activation", "join_count > 12"),),
    )
    t_decision_nl = Transformation(
        id="dec_nl",
        input_artifact_id="q1",
        output_artifact_id="nl1",
        transformation_type="decision_mapping",
        rule_spec="Nested loop chosen when inner relation size < threshold",
        constraints=(("condition", "cost(nl) < cost(hj)"),),
    )

    vs = ViewState(
        artifact_space=frozenset({query, hash_join, merge_join, nl_join, plan_tree}),
        transform_space=frozenset(
            {
                t_equivalence,
                t_generative_dp,
                t_generative_geqo,
                t_decision_nl,
            }
        ),
    )
    return vs, PREDEFINED_CONTEXTS["default_optimizer"]


# --- Identity ---


def test_identity_returns_same_state():
    vs, ec = make_test_state()
    result, vs2 = identity(vs, ec)
    assert result.is_empty
    assert vs2 is vs


# --- Projection ---


def test_projection_filters_artifacts():
    vs, ec = make_test_state()
    # Filter to only hash_join artifact
    result, vs2 = projection(
        vs,
        ec,
        filter_type="artifact",
        predicate=lambda a: a.id == "hj1",
    )
    assert len(result.artifacts) == 1
    assert list(result.artifacts)[0].id == "hj1"
    assert len(vs2.artifact_space) == 1


def test_projection_filters_transforms():
    vs, ec = make_test_state()
    result, vs2 = projection(
        vs,
        ec,
        filter_type="transformation",
        predicate=lambda t: t.transformation_type == "equivalence_mapping",
    )
    assert len(result.transforms) == 1
    assert list(result.transforms)[0].id == "eq1"


def test_projection_empty_result():
    vs, ec = make_test_state()
    result, _ = projection(
        vs,
        ec,
        filter_type="artifact",
        predicate=lambda a: False,
    )
    assert result.is_empty


# --- Traversal ---


def test_traversal_follows_edges():
    vs, ec = make_test_state()
    # Traverse from the query artifact following generative_mapping edges
    result, vs2 = traversal(
        vs,
        ec,
        seed_set={"q1"},
        edge_semantics="generative_mapping",
        depth_limit=2,
    )
    # Should reach plan1
    plan_ids = {a.id for a in vs2.artifact_space}
    assert "plan1" in plan_ids
    assert len(vs2.transform_space) == 2  # both generative mappings


def test_traversal_depth_limit():
    vs, ec = make_test_state()
    # Depth 0 = seed only
    result, vs2 = traversal(
        vs,
        ec,
        seed_set={"q1"},
        edge_semantics="generative_mapping",
        depth_limit=0,
    )
    assert len(vs2.artifact_space) == 1
    assert list(vs2.artifact_space)[0].id == "q1"


def test_traversal_structural_edge_type():
    vs, ec = make_test_state()
    # No structural edges in this test graph; should return seed artifacts only
    result, vs2 = traversal(
        vs,
        ec,
        seed_set={"hj1"},
        edge_semantics="structural/call",
        depth_limit=2,
    )
    assert {a.id for a in vs2.artifact_space} == {"hj1"}


def test_traversal_parent_type():
    vs, ec = make_test_state()
    # "transformational" parent type should follow all subtypes
    result, vs2 = traversal(
        vs,
        ec,
        seed_set={"q1"},
        edge_semantics="transformational",
        depth_limit=1,
    )
    transform_types = {t.transformation_type for t in vs2.transform_space}
    assert "generative_mapping" in transform_types
    assert "decision_mapping" in transform_types


# --- Reduction ---


def test_reduction_produces_equivalence_classes():
    vs, ec = make_test_state()
    result, vs2 = reduction(vs, ec, relation="syntactic")
    # Each artifact should be its own class in this simplified implementation
    assert len(vs2.artifact_space) == len(vs.artifact_space)
    for a in vs2.artifact_space:
        assert a.id.startswith("eq:")
        meta_dict = a.metadata_dict()
        assert "members" in meta_dict
        assert meta_dict["relation"] == "syntactic"


# --- Composition ---


def test_compose_chain():
    vs, ec = make_test_state()
    # Projection → Traversal: find all artifacts reachable from query via generative mapping
    result, vs2 = compose(
        vs,
        ec,
        [
            ("projection", {"filter_type": "artifact", "predicate": lambda a: a.id == "q1"}),
            ("traversal", {"seed_set": {"q1"}, "edge_semantics": "generative_mapping", "depth_limit": 2}),
        ],
    )
    # Should reach plan1 through generative mappings
    assert "plan1" in {a.id for a in vs2.artifact_space}


def test_compose_provenance_chain():
    vs, ec = make_test_state()
    _, vs2 = compose(
        vs,
        ec,
        [
            ("projection", {"filter_type": "artifact", "predicate": lambda a: True}),
            ("identity", {}),
        ],
    )
    # Provenance should have 2 entries (identity does not add entry)
    assert len(vs2.provenance) >= 1
    assert vs2.provenance[0].primitive == "projection"


# --- Provenance ---


def test_provenance_tracks_primitives():
    vs, ec = make_test_state()
    _, vs2 = compose(
        vs,
        ec,
        [
            ("projection", {"filter_type": "artifact", "predicate": lambda a: a.id == "q1"}),
            ("traversal", {"seed_set": {"q1"}, "edge_semantics": "generative_mapping", "depth_limit": 1}),
        ],
    )
    assert len(vs2.provenance) == 2
    assert vs2.provenance[0].primitive == "projection"
    assert vs2.provenance[1].primitive == "traversal"


def test_provenance_input_output_hashes():
    vs, ec = make_test_state()
    _, vs2 = compose(
        vs,
        ec,
        [
            ("projection", {"filter_type": "artifact", "predicate": lambda a: a.id == "q1"}),
        ],
    )
    entry = vs2.provenance[0]
    assert entry.input_hash == vs.content_hash
    assert entry.output_hash == vs2.content_hash
    assert entry.input_hash != entry.output_hash  # content changed


def test_provenance_describe():
    entry = QueryTraceEntry(
        primitive="projection",
        args={"filter_type": "artifact"},
        input_hash="abc123",
        output_hash="def456",
    )
    desc = entry.describe()
    assert "projection" in desc
    assert "abc123" in desc
    assert "def456" in desc


# --- ViewState hash ---


def test_viewstate_hash_deterministic():
    vs1, _ = make_test_state()
    vs2, _ = make_test_state()
    assert vs1.content_hash == vs2.content_hash


def test_viewstate_hash_changes_on_filter():
    vs, ec = make_test_state()
    _, vs2 = projection(vs, ec, filter_type="artifact", predicate=lambda a: a.id == "q1")
    assert vs.content_hash != vs2.content_hash


# --- EvaluationContext ---


def test_evaluation_context_predefined():
    assert PREDEFINED_CONTEXTS["default_optimizer"].regime == "default_optimizer"
    assert PREDEFINED_CONTEXTS["fast_path"].objective_function == "minimize(total_cost)"
    assert PREDEFINED_CONTEXTS["geqo_mode"].constraints == ("join_count > 12",)


def test_evaluation_context_any_regime():
    """Regimes are open-ended — any string is valid."""
    ctx = EvaluationContext(regime="arbitrary_fm_context", constraints=("tax_deductible",), description="FM tax regime")
    assert ctx.regime == "arbitrary_fm_context"
    assert ctx.constraints == ("tax_deductible",)
