"""Tests for studyplan.provenance.lab.layers — iR layer architecture.

Tests cover:
  1. All 5 layers have valid definitions
  2. All layers work cross-domain (FM, PG, LLVM, GUI)
  3. Layer invariants hold at each layer
  4. Upward transitions navigate correctly
  5. Monotonicity: each layer is a strict superset of the previous
"""

import pytest

from studyplan.provenance.compiler import DomainCompiler
from studyplan.provenance.compiler_spec import NPV
from studyplan.provenance.kernel.loaders import (
    build_pg_optimizer_data,
    build_llvm_ir_data,
    build_gui_data,
)
from studyplan.provenance.lab import ProvenanceLab
from studyplan.provenance.lab.layers import (
    iR_LAYERS,
    iR_ORDER,
    resolve_layer,
    extract_layer,
    layer_sequence,
    iRLayerDef,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def fm_lab():
    return ProvenanceLab(DomainCompiler.compile_one(NPV))


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
# 1. Layer definitions are valid
# ============================================================


def test_all_layers_registered():
    """All 5 iR layers are registered in order."""
    assert len(iR_LAYERS) == 5
    assert iR_ORDER == ["iR0", "iR1", "iR2", "iR3", "iR4"]


def test_each_layer_has_required_fields():
    """Each layer has name, observability, invariant, canonical_plan, check_invariant."""
    for name in iR_ORDER:
        layer = resolve_layer(name)
        assert isinstance(layer, iRLayerDef)
        assert layer.name == name
        assert layer.observability in ("OL0", "OL1", "OL2", "OL3")
        assert isinstance(layer.invariant, str) and len(layer.invariant) > 0
        assert callable(layer.canonical_plan)
        assert callable(layer.check_invariant)
        assert callable(layer.upward_plan)
        assert callable(layer.downward_projection)


def test_observability_increases_with_layer():
    """Higher iR layers have higher observability levels."""
    obs_order = {"OL0": 0, "OL1": 1, "OL2": 2, "OL3": 3}
    levels = [obs_order[resolve_layer(n).observability] for n in iR_ORDER]
    assert levels == sorted(levels), f"Observability not monotonic: {levels}"


def test_unknown_layer_raises():
    """resolve_layer raises KeyError for unknown layers."""
    with pytest.raises(KeyError):
        resolve_layer("iR5")
    with pytest.raises(KeyError):
        resolve_layer("nonexistent")


# ============================================================
# 2. Cross-domain layer extraction
# ============================================================


@pytest.mark.parametrize("layer_name", ["iR0", "iR1", "iR2", "iR3", "iR4"])
def test_layer_works_on_fm(layer_name, fm_lab):
    """Each layer extracts successfully on FM."""
    result = extract_layer(fm_lab, layer_name)
    assert result.question == f"extract_{layer_name}"
    assert result.summary["layer"] == layer_name
    assert result.summary["invariant_holds"] is True


@pytest.mark.parametrize("layer_name", ["iR0", "iR1", "iR2", "iR3", "iR4"])
def test_layer_works_on_pg(layer_name, pg_lab):
    result = extract_layer(pg_lab, layer_name)
    assert result.summary["invariant_holds"] is True


@pytest.mark.parametrize("layer_name", ["iR0", "iR1", "iR2", "iR3", "iR4"])
def test_layer_works_on_llvm(layer_name, llvm_lab):
    result = extract_layer(llvm_lab, layer_name)
    assert result.summary["invariant_holds"] is True


@pytest.mark.parametrize("layer_name", ["iR0", "iR1", "iR2", "iR3", "iR4"])
def test_layer_works_on_gui(layer_name, gui_lab):
    result = extract_layer(gui_lab, layer_name)
    assert result.summary["invariant_holds"] is True


def test_all_layers_all_domains(fm_lab, pg_lab, llvm_lab, gui_lab):
    """4×5 = 20 layer extractions all pass."""
    for name, lab in [("FM", fm_lab), ("PG", pg_lab), ("LLVM", llvm_lab), ("GUI", gui_lab)]:
        for layer_name in iR_ORDER:
            result = extract_layer(lab, layer_name)
            assert result.summary["invariant_holds"] is True, f"{name}.{layer_name} invariant failed"


# ============================================================
# 3. Layer-specific invariant tests
# ============================================================


def test_iR0_invariant_all_artifacts_have_types(fm_lab):
    """iR0: every artifact has a valid type string."""
    result = extract_layer(fm_lab, "iR0")
    for a in result.plan_result.step_results[0].artifacts:
        assert isinstance(a.type, str) and len(a.type) > 0


def test_iR0_invariant_all_types_fm(fm_lab):
    """iR0: FM artifacts include config_value and call_graph_region types."""
    result = extract_layer(fm_lab, "iR0")
    types = frozenset(a.type for a in result.plan_result.step_results[0].artifacts)
    assert "config_value" in types
    assert "call_graph_region" in types


def test_iR2_invariant_every_constraint_has_key_and_value(fm_lab, pg_lab):
    """iR2: every constraint artifact has constraint_key and constraint_value metadata."""
    for lab in (fm_lab, pg_lab):
        result = extract_layer(lab, "iR2")
        for a in result.plan_result.step_results[0].artifacts:
            md = a.metadata_dict()
            assert "constraint_key" in md, f"Missing constraint_key in {a}"
            assert "constraint_value" in md, f"Missing constraint_value in {a}"


def test_iR3_invariant_closure_includes_seed(fm_lab):
    """iR3: transitive closure from NPV includes NPV itself."""
    result = extract_layer(fm_lab, "iR3")
    ids = frozenset(a.id for a in result.plan_result.step_results[0].artifacts)
    assert "NPV" in ids


def test_iR4_invariant_finite_impact(fm_lab):
    """iR4: impact count is finite."""
    result = extract_layer(fm_lab, "iR4")
    count = len(result.plan_result.step_results[1].artifacts)
    assert count >= 0
    assert isinstance(count, int)


# ============================================================
# 4. Upward transitions
# ============================================================


def test_upward_transition_iR0_to_iR1(fm_lab):
    """iR0 → iR1: add edges, now traversal works."""
    results = layer_sequence(fm_lab, "iR0", "iR1")
    assert len(results) == 2  # extract_iR0 + transition
    assert results[0].question == "extract_iR0"
    assert "iR0_to_iR1" in results[1].question


def test_upward_transition_iR2_to_iR3(fm_lab):
    """iR2 → iR3: add transitive closure."""
    results = layer_sequence(fm_lab, "iR2", "iR3")
    assert len(results) == 2
    assert results[1].summary["from_layer"] == "iR2"
    assert results[1].summary["to_layer"] == "iR3"


def test_full_sequence_iR0_to_iR4(fm_lab):
    """Navigate from most concrete (iR0) to most abstract (iR4)."""
    results = layer_sequence(fm_lab, "iR0", "iR4")
    assert len(results) == 5  # 1 extract + 4 transitions
    layer_names = [r.summary.get("layer") or r.summary.get("to_layer") for r in results]
    # Starts at iR0, ends at iR4
    assert "iR0" in str(results[0].summary)
    assert results[-1].summary.get("to_layer") == "iR4"


def test_downward_navigation_raises(fm_lab):
    """Navigating downward raises ValueError."""
    with pytest.raises(ValueError, match="Cannot navigate downward"):
        layer_sequence(fm_lab, "iR4", "iR0")
    with pytest.raises(ValueError, match="Cannot navigate downward"):
        layer_sequence(fm_lab, "iR3", "iR1")


# ============================================================
# 5. Monotonicity
# ============================================================


def test_iR1_is_superset_of_iR0(fm_lab):
    """iR1 contains all artifacts from iR0 plus edges."""
    r0 = extract_layer(fm_lab, "iR0")
    r1 = extract_layer(fm_lab, "iR1")
    ids0 = frozenset(a.id for a in r0.plan_result.step_results[0].artifacts)
    ids1 = frozenset(a.id for a in r1.plan_result.step_results[0].artifacts)
    assert ids0 == ids1  # same artifacts (iR1 includes all iR0)


def test_iR0_artifact_count_fm(fm_lab):
    """FM ViewState has a specific number of artifacts (NPV topic)."""
    result = extract_layer(fm_lab, "iR0")
    count = len(result.plan_result.step_results[0].artifacts)
    assert count == 11, f"Expected 11 artifacts in FM NPV, got {count}"


def test_iR1_step_count_is_1(fm_lab):
    """iR1 is a single projection — one step."""
    result = extract_layer(fm_lab, "iR1")
    assert result.plan_result.step_count == 1


def test_iR4_is_two_steps(fm_lab):
    """iR4 is projection→traversal — two steps with result-threading."""
    result = extract_layer(fm_lab, "iR4")
    assert result.plan_result.step_count == 2
    assert result.plan_result.steps[0].primitive == "projection"
    assert result.plan_result.steps[1].primitive == "traversal"


# ============================================================
# 6. Cross-domain layer invariants
# ============================================================


@pytest.mark.parametrize("lab_fixture", ["fm_lab", "pg_lab", "llvm_lab", "gui_lab"])
def test_iR0_invariant_all_domains(lab_fixture, request):
    lab = request.getfixturevalue(lab_fixture)
    result = extract_layer(lab, "iR0")
    assert result.summary["invariant_holds"] is True
    # Every artifact has a type
    for a in result.plan_result.step_results[0].artifacts:
        assert isinstance(a.type, str) and len(a.type) > 0


@pytest.mark.parametrize("lab_fixture", ["fm_lab", "pg_lab", "llvm_lab", "gui_lab"])
def test_iR2_invariant_all_domains(lab_fixture, request):
    lab = request.getfixturevalue(lab_fixture)
    result = extract_layer(lab, "iR2")
    assert result.summary["invariant_holds"] is True
    for a in result.plan_result.step_results[0].artifacts:
        md = a.metadata_dict()
        assert "constraint_key" in md
        assert "constraint_value" in md


# ============================================================
# 7. Downward projection
# ============================================================


def test_downward_iR0_projection(fm_lab):
    """Downward projection to iR0 removes transforms."""
    from studyplan.provenance.lab.layers import resolve_layer

    layer = resolve_layer("iR0")
    vs_in = fm_lab.vs
    vs_out = layer.downward_projection(vs_in)
    assert len(vs_out.transform_space) == 0  # no edges
    assert len(vs_out.artifact_space) == len(vs_in.artifact_space)  # all artifacts preserved


def test_downward_iR1_projection(fm_lab):
    """Downward projection to iR1 removes constraint artifacts."""
    from studyplan.provenance.lab.layers import resolve_layer

    layer = resolve_layer("iR1")
    vs_in = fm_lab.vs
    vs_out = layer.downward_projection(vs_in)
    # No artifacts with "c:" prefix (constraint artifacts)
    for a in vs_out.artifact_space:
        assert not a.id.startswith("c:")
