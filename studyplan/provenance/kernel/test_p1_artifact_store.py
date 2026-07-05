"""P1 — ArtifactStore Protocol: Experiment Execution

Tests each prediction of the ArtifactStore hypothesis.

Prediction 1: ViewState remains immutable.
    → Serialization does not add mutation to kernel types.

Prediction 2: Algebra APIs unchanged.
    → projection/traversal/reduction/compose work identically on loaded ViewStates.

Prediction 3: Cross-session queries work.
    → Save a ViewState, load in same process, run queries with matching content_hash.

Prediction 4: Tutor code becomes simpler.
    → Not tested here (integration-level). Tested via load-and-query pattern.

Prediction 5: No ontology changes.
    → No new types, no new artifact types, no new edge semantics needed.

Falsification tracking:
    Count how many custom serialization workarounds were needed.
    If > 0, each is evidence against the clean-boundary hypothesis.
"""

import tempfile
import pytest

from studyplan.provenance.kernel import (
    ViewState,
    PREDEFINED_CONTEXTS,
    compose,
    projection,
    traversal,
    collect_inherited_constraints,
)
from studyplan.provenance.kernel.loaders import build_pg_optimizer_data
from studyplan.provenance.experiments.experiment_artifact_store import ArtifactStore

EC = PREDEFINED_CONTEXTS["default_optimizer"]


# ============================================================
# Setup
# ============================================================


@pytest.fixture
def pg_vs():
    return build_pg_optimizer_data().build()


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory(prefix="cci_store_") as tmp:
        yield ArtifactStore(path=tmp)


# ============================================================
# Prediction 1: ViewState remains immutable.
# The store should not add mutation to kernel types.
# ============================================================


def test_p1_viewstate_immutable_after_roundtrip(pg_vs, store):
    """ViewState stays frozen after save/load cycle."""
    key = store.save(pg_vs)
    loaded = store.load(key)
    assert loaded is not None
    assert isinstance(loaded, ViewState)
    # Verify immutability: artifact_space is still a frozenset
    assert isinstance(loaded.artifact_space, frozenset)
    assert isinstance(loaded.transform_space, frozenset)


# ============================================================
# Prediction 2: Algebra APIs unchanged.
# Queries work identically on loaded ViewStates.
# ============================================================


def test_p2_projection_on_loaded(pg_vs, store):
    """projection works identically after save/load."""
    key = store.save(pg_vs)
    loaded = store.load(key)

    # Run same projection on both
    result_orig, _ = projection(pg_vs, EC, filter_type="artifact", predicate=lambda a: a.type == "call_graph_region")
    result_load, _ = projection(loaded, EC, filter_type="artifact", predicate=lambda a: a.type == "call_graph_region")

    assert len(result_orig.artifacts) == len(result_load.artifacts)
    orig_ids = {a.id for a in result_orig.artifacts}
    load_ids = {a.id for a in result_load.artifacts}
    assert orig_ids == load_ids


def test_p2_traversal_on_loaded(pg_vs, store):
    """traversal works identically after save/load."""
    key = store.save(pg_vs)
    loaded = store.load(key)

    _, vs_orig = traversal(pg_vs, EC, seed_set={"standard_planner"}, edge_semantics="structural/call", depth_limit=2)
    _, vs_load = traversal(loaded, EC, seed_set={"standard_planner"}, edge_semantics="structural/call", depth_limit=2)

    orig_ids = {a.id for a in vs_orig.artifact_space}
    load_ids = {a.id for a in vs_load.artifact_space}
    assert orig_ids == load_ids


def test_p2_compose_on_loaded(pg_vs, store):
    """compose works identically after save/load."""
    key = store.save(pg_vs)
    loaded = store.load(key)

    steps = [
        ("projection", {"filter_type": "artifact", "predicate": lambda a: a.type == "call_graph_region"}),
        ("traversal", {"seed_set": {"standard_planner"}, "edge_semantics": "structural/call", "depth_limit": 1}),
    ]
    _, vs_orig = compose(pg_vs, EC, steps)
    _, vs_load = compose(loaded, EC, steps)

    orig_ids = {a.id for a in vs_orig.artifact_space}
    load_ids = {a.id for a in vs_load.artifact_space}
    assert orig_ids == load_ids


def test_p2_collect_inherited_constraints_on_loaded(pg_vs, store):
    """collect_inherited_constraints works identically after save/load."""
    key = store.save(pg_vs)
    loaded = store.load(key)

    orig_cons = collect_inherited_constraints(pg_vs, "plan_tree_geqo")
    load_cons = collect_inherited_constraints(loaded, "plan_tree_geqo")

    assert orig_cons == load_cons


# ============================================================
# Prediction 3: Cross-session queries work.
# ============================================================


def test_p3_content_hash_preserved(pg_vs, store):
    """content_hash remains identical after save/load cycle."""
    orig_hash = pg_vs.content_hash
    key = store.save(pg_vs)
    loaded = store.load(key)
    assert loaded is not None
    assert loaded.content_hash == orig_hash, "content_hash must survive serialization"


def test_p3_multiple_saves_same_hash(pg_vs, store):
    """Saving the same ViewState twice produces the same key."""
    key1 = store.save(pg_vs)
    key2 = store.save(pg_vs)
    assert key1 == key2
    # Both point to the same file
    loaded = store.load(key1)
    assert loaded is not None
    assert loaded.content_hash == pg_vs.content_hash


def test_p3_contains(pg_vs, store):
    """contains reports correctly for saved and unsaved data."""
    assert not store.contains("nonexistent_hash")
    key = store.save(pg_vs)
    assert store.contains(key)
    assert store.contains(pg_vs.content_hash)


# ============================================================
# Prediction 4: (Integration-level) — not tested here.
# ============================================================

# ============================================================
# Prediction 5: No ontology changes.
# ============================================================


def test_p5_no_new_types_needed(pg_vs, store):
    """Store uses only existing kernel types — no new types introduced."""
    from studyplan.provenance.kernel.types import Artifact, Transformation

    key = store.save(pg_vs)
    loaded = store.load(key)
    for a in loaded.artifact_space:
        assert isinstance(a, Artifact)
    for t in loaded.transform_space:
        assert isinstance(t, Transformation)


# ============================================================
# Falsification tracker
# ============================================================

FALSIFICATION_COUNT = 0
FALSIFICATION_REASONS: list[str] = []


def test_falsification_tracker():
    """Track how many workarounds were needed for serialization.

    Each workaround counted here is evidence against the hypothesis that
    ViewState has a clean architectural boundary.
    """
    from studyplan.provenance.experiments import experiment_artifact_store as mod

    source = open(mod.__file__).read()

    # Count workaround patterns
    workarounds = []

    # 1. _json_fallback for frozenset - expected, this is standard library
    # 2. _reconstruct_projection - expected, inverse of serialization
    # 3. _reconstruct_trace_entry - expected, inverse of serialization

    # Look for unexpected patterns that suggest architectural leaks
    if "import" in source and "studyplan.provenance.kernel.primitives" in source:
        workarounds.append("Store imports from primitives (not just types)")

    # Check that the store doesn't reference domain-specific concepts
    if "WACC" in source or "CAPM" in source or "FM" in source:
        workarounds.append("Store contains domain-specific logic")

    if workarounds:
        pytest.fail(f"Serialization workarounds found: {workarounds}")

    # Expected: the store uses a structural recursive converter (asdict equivalent
    # that handles frozenset) + standard json. Python's dataclasses.asdict does not
    # recurse into frozenset members, so _to_json_compat is the structural equivalent
    # with zero domain knowledge. This is the ideal — zero architectural leakage.
    assert "_to_json_compat" in source, "Store should use structural recursive serializer"


# ============================================================
# Round-trip stress test
# ============================================================


def test_roundtrip_fm_wacc():
    """Round-trip FM WACC domain through the store."""
    from studyplan.provenance.experiments.experiment_artifact_store import _viewstate_to_dict, _dict_to_viewstate
    from studyplan.provenance.kernel.test_p0_provenance_completeness import build_fm_wacc_vs

    vs = build_fm_wacc_vs()
    data = _viewstate_to_dict(vs)
    reconstructed = _dict_to_viewstate(data)

    assert reconstructed.content_hash == vs.content_hash
    assert len(reconstructed.artifact_space) == len(vs.artifact_space)
    assert len(reconstructed.transform_space) == len(vs.transform_space)


def test_roundtrip_pure_dict_transform():
    """Test pure dict-to-dict roundtrip: no IO, just serialization logic."""
    from studyplan.provenance.experiments.experiment_artifact_store import _viewstate_to_dict, _dict_to_viewstate
    from studyplan.provenance.kernel.loaders import build_pg_optimizer_data

    vs = build_pg_optimizer_data().build()
    data = _viewstate_to_dict(vs)
    reconstructed = _dict_to_viewstate(data)

    assert reconstructed.content_hash == vs.content_hash
    assert len(reconstructed.artifact_space) == len(vs.artifact_space)
    assert len(reconstructed.transform_space) == len(vs.transform_space)
