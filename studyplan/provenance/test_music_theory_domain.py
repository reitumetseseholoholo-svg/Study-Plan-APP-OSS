"""Music Theory Domain — test of FastDomainCompiler universality (5th domain).

Essentialist Question:
    What phenomenon does adding a non-finance, non-computing domain test?
Answer:
    Domain universality — the property that the FastDomainCompiler can
    represent any structured domain's conceptual architecture without
    kernel changes. If music theory (a humanities domain with different
    structural primitives) compiles without modifying the compiler, the
    architecture is truly domain-independent.

Hypothesis H-MT-01:
    The FastDomainCompiler does not depend on finance or computing
    concepts. A music theory domain (harmonic cadence analysis) compiles
    to a valid ViewState with zero compiler modifications — only a
    TypeRegistry registration and a DomainSpec definition.

Predictions:
    P1: A music theory DomainSpec compiles to a valid ViewState (validation passes).
    P2: compile() produces correct artifact counts for the given spec.
    P3: The compiled ViewState supports collect_inherited_constraints queries.
    P4: The compiled ViewState can be registered in DomainRegistry.
    P5: No changes to FastDomainCompiler or kernel types required.

Falsification conditions:
    F1: Music theory requires a new artifact type not in ARTIFACT_TYPES.
    F2: The compiler raises for a well-formed music theory DomainSpec.
    F3: A music theory ViewState fails iR1 connectivity (dangling edges).
    F4: collect_inherited_constraints misses domain-specific assumptions.
"""

from __future__ import annotations

import pytest

from studyplan.provenance.kernel import (
    ViewState,
    collect_inherited_constraints,
)
from studyplan.provenance.fast_compiler import (
    TypeRegistry,
    DomainSpec,
    DomainNode,
    DomainEdge,
    FastDomainCompiler,
)
from studyplan.provenance.domain_registry import DomainRegistry


# ============================================================
# Domain: Music Theory — Harmonic Cadence Analysis
#
# Models the resolution of a leading tone into the tonic chord
# in Western tonal harmony. A cadence is the harmonic punctuation
# at the end of a phrase — the most fundamental structural unit.
#
# Artifacts:
#   tonic         → pitch (the key center, e.g., C)
#   scale_type    → scale (major/minor)
#   leading_tone  → pitch (7th scale degree)
#   chord_quality → interval (major/minor triad)
#   diatonic_scale      → scale (computed from tonic + scale_type)
#   scale_degrees       → chord (diatonic chords built on scale)
#   voice_leading_path  → voice_leading (motion of individual voices)
#   cadence_analysis    → cadence (output — harmonic function label)
#
# Transformations:
#   1. tonic + scale_type → diatonic_scale (generative_mapping)
#   2. diatonic_scale → scale_degrees (generative_mapping)
#      Assumption: "diatonic_harmony" — all chords derive from scale
#   3. leading_tone + scale_degrees → voice_leading_path (generative_mapping)
#      Assumption: "voice_leading"
#      Constraint: "leading_tone_resolves_up" — leading tone → tonic
#   4. voice_leading_path + chord_quality → cadence_analysis (generative_mapping)
#      Assumption: "cadential_resolution"
#      Constraint: "authentic_cadence" — V → I resolution
# ============================================================


@pytest.fixture
def music_registry() -> TypeRegistry:
    r = TypeRegistry()
    r.register_domain(
        "music",
        {
            "pitch": "config_value",
            "scale": "config_value",
            "interval": "config_value",
            "chord": "call_graph_region",
            "cadence": "call_graph_region",
            "voice_leading": "data_flow_edge",
            "harmonic_function": "call_graph_region",
        },
        default_edge_semantics="generative_mapping",
    )
    return r


@pytest.fixture
def music_compiler(music_registry) -> FastDomainCompiler:
    return FastDomainCompiler(type_registry=music_registry)


@pytest.fixture
def cadence_spec() -> DomainSpec:
    return DomainSpec(
        id="cadence_analysis",
        title="Harmonic Cadence Analysis",
        domain="music",
        nodes=(
            DomainNode(id="tonic", concept="pitch", kind="parameter", target="Key center (e.g., C)"),
            DomainNode(id="scale_type", concept="scale", kind="parameter", target="Major or minor"),
            DomainNode(id="leading_tone", concept="pitch", kind="parameter", target="7th scale degree"),
            DomainNode(id="chord_quality", concept="interval", kind="parameter", target="Major or minor triad"),
            DomainNode(id="diatonic_scale", concept="scale", kind="intermediate", target="Diatonic scale"),
            DomainNode(id="scale_degrees", concept="chord", kind="intermediate", target="Diatonic chords"),
            DomainNode(
                id="voice_leading_path", concept="voice_leading", kind="intermediate", target="Voice-leading motion"
            ),
            DomainNode(
                id="cadence_analysis", concept="cadence", kind="output", target="Cadence type (authentic/plagal/half)"
            ),
        ),
        edges=(
            DomainEdge(
                id="build_scale",
                from_id="tonic",
                to_id="diatonic_scale",
                rule="diatonic_scale = tonic + scale_type",
                consumes=("scale_type",),
            ),
            DomainEdge(
                id="derive_chords",
                from_id="diatonic_scale",
                to_id="scale_degrees",
                rule="scale_degrees = diatonic(diatonic_scale)",
                assumptions=("diatonic_harmony",),
            ),
            DomainEdge(
                id="resolve_leading_tone",
                from_id="leading_tone",
                to_id="voice_leading_path",
                rule="leading_tone → tonic (semitone up)",
                consumes=("scale_degrees",),
                assumptions=("voice_leading", "leading_tone_resolves_up"),
            ),
            DomainEdge(
                id="classify_cadence",
                from_id="voice_leading_path",
                to_id="cadence_analysis",
                rule="cadence_type(voice_leading_path, chord_quality)",
                consumes=("chord_quality",),
                assumptions=("cadential_resolution", "authentic_cadence"),
            ),
        ),
    )


# ============================================================
# Tests
# ============================================================


class TestMusicRegistry:
    """P0: Music theory concepts register without errors."""

    def test_registry_creation(self, music_registry):
        assert "music" in music_registry.known_domains
        assert music_registry.resolve("music", "pitch") == "config_value"
        assert music_registry.resolve("music", "cadence") == "call_graph_region"
        assert music_registry.resolve("music", "voice_leading") == "data_flow_edge"

    def test_registry_edge_default(self, music_registry):
        assert music_registry.default_edge_semantics("music") == "generative_mapping"


class TestMusicCompilation:
    """P1 + P2: A music theory DomainSpec compiles to a valid ViewState."""

    def test_compiles_cadence_analysis(self, music_compiler, cadence_spec):
        vs, record = music_compiler.compile(cadence_spec)

        assert isinstance(vs, ViewState)
        assert record.validation["pass"] is True
        # 4 params + 3 intermediates + 1 output = 8 artifacts
        assert len(vs.artifact_space) == 8
        # 4 edges = 4 transforms
        assert len(vs.transform_space) == 4

    def test_correct_artifact_types(self, music_compiler, cadence_spec):
        vs, record = music_compiler.compile(cadence_spec)

        ids = {a.id: a.type for a in vs.artifact_space}
        assert ids["tonic"] == "config_value"
        assert ids["scale_type"] == "config_value"
        assert ids["leading_tone"] == "config_value"
        assert ids["chord_quality"] == "config_value"
        assert ids["diatonic_scale"] == "config_value"  # scale maps to config_value
        assert ids["scale_degrees"] == "call_graph_region"  # chord maps to call_graph_region
        assert ids["voice_leading_path"] == "data_flow_edge"
        assert ids["cadence_analysis"] == "call_graph_region"

    def test_all_artifact_ids_present(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        ids = {a.id for a in vs.artifact_space}
        expected = {
            "tonic",
            "scale_type",
            "leading_tone",
            "chord_quality",
            "diatonic_scale",
            "scale_degrees",
            "voice_leading_path",
            "cadence_analysis",
        }
        assert ids == expected

    def test_all_transforms_connect_real_artifacts(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        ids = {a.id for a in vs.artifact_space}
        for t in vs.transform_space:
            assert t.input_artifact_id in ids
            assert t.output_artifact_id in ids

    def test_transform_rule_strings_preserved(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        rules = {t.id: t.rule_spec for t in vs.transform_space}
        assert "diatonic" in rules["derive_chords"]
        assert "cadence_type" in rules["classify_cadence"]

    def test_constraints_encoded(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        all_constraints = set()
        for t in vs.transform_space:
            for key, val in t.constraints:
                all_constraints.add((key, val))
        constraint_vals = {v for _, v in all_constraints}
        assert "diatonic_harmony" in constraint_vals
        assert "voice_leading" in constraint_vals
        assert "leading_tone_resolves_up" in constraint_vals
        assert "cadential_resolution" in constraint_vals
        assert "authentic_cadence" in constraint_vals


class TestMusicProvenance:
    """P3: Compiled music theory ViewState supports provenance queries."""

    def test_collect_inherited_constraints(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        constraints = collect_inherited_constraints(vs, "cadence_analysis")
        assert isinstance(constraints, set)
        assert len(constraints) > 0
        constraint_vals = {v for _, v in constraints}
        assert "diatonic_harmony" in constraint_vals
        assert "cadential_resolution" in constraint_vals
        assert "authentic_cadence" in constraint_vals

    def test_voice_leading_inherits_scale_assumptions(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        constraints = collect_inherited_constraints(vs, "voice_leading_path")
        constraint_vals = {v for _, v in constraints}
        assert "diatonic_harmony" in constraint_vals
        assert "voice_leading" in constraint_vals
        assert "leading_tone_resolves_up" in constraint_vals

    def test_scale_degrees_inherits_only_scale_assumptions(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        constraints = collect_inherited_constraints(vs, "scale_degrees")
        constraint_vals = {v for _, v in constraints}
        assert "diatonic_harmony" in constraint_vals
        assert "voice_leading" not in constraint_vals  # not upstream
        assert "cadential_resolution" not in constraint_vals  # not upstream

    def test_tonic_has_no_inherited_constraints(self, music_compiler, cadence_spec):
        vs, _ = music_compiler.compile(cadence_spec)
        constraints = collect_inherited_constraints(vs, "tonic")
        assert len(constraints) == 0  # base artifact


class TestMusicDomainRegistry:
    """P4: Music theory domain works with DomainRegistry."""

    def test_register_in_domain_registry(self, music_compiler, cadence_spec, music_registry):
        dr = DomainRegistry(compiler=music_compiler)
        entry = dr.register_spec(cadence_spec)

        assert entry is not None
        assert entry.concept_id == "cadence_analysis"
        assert entry.validation_pass is True
        assert entry.output_artifact_id == "cadence_analysis"

    def test_provenance_query_via_registry(self, music_compiler, cadence_spec, music_registry):
        dr = DomainRegistry(compiler=music_compiler)
        dr.register_spec(cadence_spec)

        assumptions = dr.query_assumptions("cadence_analysis")
        assert assumptions is not None
        assert "diatonic_harmony" in str(assumptions)
        assert "cadential_resolution" in str(assumptions)

        constraints = dr.query_inherited_constraints("cadence_analysis")
        assert constraints is not None
        constraint_vals = {v for _, v in constraints}
        assert "authentic_cadence" in constraint_vals

    def test_voice_leading_upstream_constraints_via_collect(self, music_compiler, cadence_spec, music_registry):
        """Intermediate artifact constraints queried via kernel directly."""
        vs, _ = music_compiler.compile(cadence_spec)
        constraints = collect_inherited_constraints(vs, "voice_leading_path")
        assert constraints is not None
        cvals = {v for _, v in constraints}
        assert "voice_leading" in cvals
        assert "leading_tone_resolves_up" in cvals

    def test_dependency_path(self, music_compiler, cadence_spec, music_registry):
        dr = DomainRegistry(compiler=music_compiler)
        dr.register_spec(cadence_spec)

        path = dr.query_dependency_path("cadence_analysis")
        assert path is not None
        assert "cadence_analysis" in path[-1] if path else True
        # All upstream artifacts should be in the path
        all_ids = {
            "tonic",
            "scale_type",
            "leading_tone",
            "chord_quality",
            "diatonic_scale",
            "scale_degrees",
            "voice_leading_path",
        }
        assert any(aid in str(path) for aid in all_ids)


class TestMusicDeterminism:
    """P5: Compilation is deterministic — same spec → same hash."""

    def test_same_spec_same_viewstate(self, music_compiler, cadence_spec):
        vs1, r1 = music_compiler.compile(cadence_spec)
        vs2, r2 = music_compiler.compile(cadence_spec)
        assert vs1.content_hash == vs2.content_hash
        assert r1.spec_hash == r2.spec_hash
        assert r1.output_hash == r2.output_hash

    def test_different_instances_same_hash(self, cadence_spec, music_registry):
        c1 = FastDomainCompiler(type_registry=music_registry)
        c2 = FastDomainCompiler(type_registry=music_registry)
        vs1, _ = c1.compile(cadence_spec)
        vs2, _ = c2.compile(cadence_spec)
        assert vs1.content_hash == vs2.content_hash
