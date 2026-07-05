"""E3 — Provenance Observatory Bridge: tests.

Verifies all 5 predictions::

    P1 — Valid trace: ProvenanceQueryExecutor produces profile-able trace.
    P2 — High key persistence: key_persistence == 1.0, no structural mutation.
    P3 — linear_plan topology: clear match with confidence > 0.5.
    P4 — dispatch dynamics: clear match with confidence > 0.5.
    P5 — Differentiable: all 6 existing-algebra meta flags are False.

See experiment_provenance_observatory.py for full hypothesis, predictions,
and failure taxonomy.
"""

from __future__ import annotations

from studyplan.provenance.experiments.experiment_provenance_observatory import (
    build_test_viewstate,
    build_query_plan,
    build_mixed_query_plan,
    run_provenance_executor,
    profile_provenance_trace,
)
from studyplan.cci import ExecutionTrace

try:
    from tools.algebra_observatory import AlgebraObservatory

    _HAS_OBSERVATORY = True
except ImportError:
    _HAS_OBSERVATORY = False

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def viewstate():
    return build_test_viewstate()


@pytest.fixture
def projection_plan():
    return build_query_plan("projection")


@pytest.fixture
def traversal_plan():
    return build_query_plan("traversal")


@pytest.fixture
def mixed_plan():
    return build_mixed_query_plan()


@pytest.fixture
def observatory():
    if not _HAS_OBSERVATORY:
        pytest.skip("AlgebraObservatory not available (tools/ not on path)")
    return AlgebraObservatory()


# ====================================================================
# P1 — Valid trace
# ====================================================================


class TestP1ValidTrace:
    """ProvenanceQueryExecutor produces valid ExecutionTraces."""

    def test_p1a_executor_runs(self, viewstate, projection_plan):
        """Executor completes without error through CognitiveRuntime."""
        trace = run_provenance_executor(viewstate, projection_plan)
        assert isinstance(trace, ExecutionTrace)
        assert len(trace.events) >= 4  # init + 3 steps + terminate

    def test_p1b_trace_has_correct_event_count(self, viewstate, projection_plan):
        """Trace has exactly (2 + N) events: init, terminate, N steps."""
        plan_len = len(projection_plan)
        trace = run_provenance_executor(viewstate, projection_plan)
        event_types = [ev.type for ev in trace.events]
        assert event_types[0] == "initialize"
        assert event_types[-1] == "terminate"
        step_events = [t for t in event_types if t == "step"]
        assert len(step_events) == plan_len

    def test_p1c_observatory_profiles(self, viewstate, projection_plan, observatory):
        """AlgebraObservatory.profile_trace() accepts the trace."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p1c")
        assert profile is not None
        assert profile.step_count == len(projection_plan)

    def test_p1d_all_primitive_types_run(self, viewstate, observatory):
        """Each primitive type (projection, traversal, collect) produces a valid trace."""
        for primitive in ("projection", "traversal", "collect_constraints"):
            plan = build_query_plan(primitive)
            trace = run_provenance_executor(viewstate, plan)
            profile = profile_provenance_trace(observatory, trace, primitive)
            assert profile.step_count == len(plan), f"{primitive} failed"

    def test_p1e_mixed_plan_runs(self, viewstate, mixed_plan, observatory):
        """A mixed query plan (projection + traversal + collect) runs cleanly."""
        trace = run_provenance_executor(viewstate, mixed_plan)
        profile = profile_provenance_trace(observatory, trace, "mixed")
        assert profile.step_count == len(mixed_plan)
        expected_actions = {"projection", "traversal", "collect_constraints"}
        assert expected_actions.issubset(set(profile.unique_actions)), f"Missing actions. Has: {profile.unique_actions}"


# ====================================================================
# P2 — High key persistence
# ====================================================================


class TestP2HighKeyPersistence:
    """Provenance profiles show stable state structure."""

    def test_p2a_key_persistence_is_one(self, viewstate, projection_plan, observatory):
        """All state keys persist across every step."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p2a")
        assert profile.key_persistence == 1.0, f"Expected 1.0, got {profile.key_persistence}"

    def test_p2b_no_structural_mutation(self, viewstate, projection_plan, observatory):
        """State keys never grow or shrink."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p2b")
        assert not profile.has_growing_keys
        assert not profile.has_shrinking_keys

    def test_p2c_value_mutation_present(self, viewstate, projection_plan, observatory):
        """Values mutate (query_index increments) but structure is stable."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p2c")
        assert profile.has_value_mutation

    def test_p2d_inside_growth_present(self, viewstate, projection_plan, observatory):
        """The completed_primitives list grows inside a stable key."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p2d")
        assert profile.has_inside_growth

    def test_p2e_not_a_traversal(self, viewstate, projection_plan, observatory):
        """Provenance queries are not tree traversals."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p2e")
        assert not profile.is_traversal


# ====================================================================
# P3 — linear_plan topology
# ====================================================================


class TestP3LinearPlanTopology:
    """Provenance query traces classify as linear_plan topology."""

    OLD_TOPOLOGY_CLASSES = [
        "tree_traversal",
        "probability_distribution",
        "score_vector",
        "constraint_graph",
        "expanding_graph",
        "support_network",
    ]

    def test_p3a_linear_plan_is_best_topology(self, viewstate, projection_plan, observatory):
        """linear_plan is the highest-confidence topology."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p3a")
        assert profile.topology.best == "linear_plan", (
            f"Expected 'linear_plan' as best topology, got {profile.topology.best}"
        )
        assert profile.topology.confidence > 0.5, (
            f"linear_plan confidence {profile.topology.confidence:.3f} — should be > 0.5"
        )

    def test_p3b_old_topologies_below_threshold(self, viewstate, mixed_plan, observatory):
        """All 6 pre-existing topology classes have confidence < 0.5."""
        trace = run_provenance_executor(viewstate, mixed_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p3b")
        for cls in self.OLD_TOPOLOGY_CLASSES:
            conf = profile.topology.values.get(cls, 0.0)
            assert conf < 0.5, f"Known topology {cls} has confidence {conf:.3f} — should be < 0.5"

    def test_p3c_all_primitive_types_linear_plan(self, viewstate, observatory):
        """Each primitive type individually classifies as linear_plan."""
        for primitive in ("projection", "traversal", "collect_constraints"):
            plan = build_query_plan(primitive)
            trace = run_provenance_executor(viewstate, plan)
            profile = profile_provenance_trace(observatory, trace, primitive)
            assert profile.topology.best == "linear_plan", (
                f"{primitive}: expected 'linear_plan', got {profile.topology.best}"
            )
            for cls in self.OLD_TOPOLOGY_CLASSES:
                conf = profile.topology.values.get(cls, 0.0)
                assert conf < 0.5, f"{primitive}: topology {cls} has confidence {conf:.3f} — should be < 0.5"


# ====================================================================
# P4 — dispatch dynamics
# ====================================================================


class TestP4DispatchDynamics:
    """Provenance query traces classify as dispatch dynamics."""

    OLD_DYNAMICS_CLASSES = [
        "traverse",
        "reweight",
        "aggregate",
        "propagate",
        "expand",
        "support_retract",
    ]

    def test_p4a_dispatch_is_best_dynamics(self, viewstate, projection_plan, observatory):
        """dispatch is the highest-confidence dynamics."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p4a")
        assert profile.dynamics.best == "dispatch", f"Expected 'dispatch' as best dynamics, got {profile.dynamics.best}"
        assert profile.dynamics.confidence > 0.5, (
            f"dispatch confidence {profile.dynamics.confidence:.3f} — should be > 0.5"
        )

    def test_p4b_old_dynamics_below_threshold(self, viewstate, mixed_plan, observatory):
        """All 6 pre-existing dynamics classes have confidence < 0.5."""
        trace = run_provenance_executor(viewstate, mixed_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p4b")
        for cls in self.OLD_DYNAMICS_CLASSES:
            conf = profile.dynamics.values.get(cls, 0.0)
            assert conf < 0.5, f"Known dynamics {cls} has confidence {conf:.3f} — should be < 0.5"

    def test_p4c_all_primitive_types_dispatch(self, viewstate, observatory):
        """Each primitive type individually classifies as dispatch."""
        for primitive in ("projection", "traversal", "collect_constraints"):
            plan = build_query_plan(primitive)
            trace = run_provenance_executor(viewstate, plan)
            profile = profile_provenance_trace(observatory, trace, primitive)
            assert profile.dynamics.best == "dispatch", f"{primitive}: expected 'dispatch', got {profile.dynamics.best}"
            for cls in self.OLD_DYNAMICS_CLASSES:
                conf = profile.dynamics.values.get(cls, 0.0)
                assert conf < 0.5, f"{primitive}: dynamics {cls} has confidence {conf:.3f} — should be < 0.5"


# ====================================================================
# P5 — Differentiable from all 6 algebras
# ====================================================================


class TestP5Differentiable:
    """Provenance profiles have distinct feature vectors from all 6 known algebras.

    The 6 known algebras each set specific meta flags:
        Classification:   has_classification_path = True
        Diagnosis:        has_posterior = True
        Evaluation:       has_score_vector = True
        CSP:              has_domain_ops = True
        GrowingGraph:     has_expanding_nodes = True
        Justification:    has_justification_network = True

    Provenance profiles have ALL SIX flags set to False — a distinct
    feature signature that no existing algebra produces.
    """

    META_FLAGS = [
        "has_classification_path",
        "has_posterior",
        "has_score_vector",
        "has_domain_ops",
        "has_backtrack",
        "has_expanding_nodes",
        "has_focus_key",
        "has_nodes_key",
        "has_justification_network",
        "has_status_tracking",
    ]

    def test_p5a_all_meta_flags_false(self, viewstate, projection_plan, observatory):
        """All executor-specific meta flags are False (not matching any executor)."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p5a")
        for flag in self.META_FLAGS:
            val = getattr(profile, flag, None)
            if val is not None:
                assert val is False, f"Meta flag {flag} is {val} — should be False for provenance"

    def test_p5b_action_names_unique(self, viewstate, mixed_plan, observatory):
        """Action names don't overlap with known algebra action names."""
        known_actions = {
            "evaluate_condition",
            "commit_result",
            "descend",
            "bayesian_update",
            "commit_diagnosis",
            "observations_exhausted",
            "score_criterion",
            "criteria_exhausted",
            "resolve_judgment",
            "propagate",
            "select_variable",
            "assign_value",
            "backtrack",
            "expand_goal",
            "activate_goal",
            "complete_leaf",
            "belief_derived",
            "belief_retracted",
            "commit_belief_set",
        }
        trace = run_provenance_executor(viewstate, mixed_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p5b")
        provenance_actions = set(profile.unique_actions)
        overlap = provenance_actions & known_actions
        assert len(overlap) == 0, f"Provenance actions overlap with known algebras: {overlap}"

    def test_p5c_mixed_plan_differentiable(self, viewstate, mixed_plan, observatory):
        """Mixed plan profile also has all meta flags False."""
        trace = run_provenance_executor(viewstate, mixed_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p5c")
        for flag in self.META_FLAGS:
            val = getattr(profile, flag, None)
            if val is not None:
                assert val is False, f"Flag {flag} is {val} for mixed plan — should be False"

    def test_p5d_high_coherence(self, viewstate, projection_plan, observatory):
        """Provenance traces have high coherence (actions are repetitive)."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p5d")
        # Same action repeated = moderate coherence (0.5 for all-novel actions)
        assert profile.coherence >= 0.5, (
            f"Coherence {profile.coherence:.3f} — repetitive actions should produce at least moderate coherence"
        )

    def test_p5e_no_value_normalization(self, viewstate, projection_plan, observatory):
        """Provenance state values are not normalized (no distributions)."""
        trace = run_provenance_executor(viewstate, projection_plan)
        profile = profile_provenance_trace(observatory, trace, "test_p5e")
        assert not profile.has_normalized_sum
        assert not profile.has_non_negative_values
