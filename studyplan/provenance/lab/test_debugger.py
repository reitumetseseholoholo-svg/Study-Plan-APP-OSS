"""Tests for Debugger (Layer 6) — breakpoints, step-through, execution comparison."""

from __future__ import annotations

import pytest

from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    Transformation,
    QueryResult,
)
from studyplan.provenance.lab.planner import PlanStep, PlanResult
from studyplan.provenance.lab.debugger import (
    Breakpoint,
    ExecutionSnapshot,
    StepController,
    DebugExecutor,
)


# ── Fixtures ──


@pytest.fixture
def sample_vs() -> ViewState:
    return ViewState(
        artifact_space=frozenset(
            {
                Artifact(id="a1", type="config_value", target="test"),
                Artifact(id="a2", type="config_value", target="test"),
            }
        ),
        transform_space=frozenset(
            {
                Transformation(
                    id="t1",
                    input_artifact_id="a1",
                    output_artifact_id="a2",
                    transformation_type="generative_mapping",
                    rule_spec="test",
                ),
            }
        ),
    )


SAMPLE_STEPS = [
    PlanStep("identity", {}),
    PlanStep(
        "projection",
        {
            "filter_type": "artifact",
            "predicate": lambda a: a.id == "a1",
        },
    ),
]


# ── Breakpoint ──


class TestBreakpoint:
    def test_triggers_on_specific_step(self, sample_vs):
        bp = Breakpoint(step_index=1)
        step = PlanStep("projection", {})
        assert bp.should_break(1, step, sample_vs, []) is True
        assert bp.should_break(0, step, sample_vs, []) is False

    def test_triggers_on_any_step(self, sample_vs):
        bp = Breakpoint()
        step = PlanStep("projection", {})
        assert bp.should_break(0, step, sample_vs, []) is True
        assert bp.should_break(99, step, sample_vs, []) is True

    def test_disabled_does_not_trigger(self, sample_vs):
        bp = Breakpoint(step_index=0, enabled=False)
        step = PlanStep("identity", {})
        assert bp.should_break(0, step, sample_vs, []) is False

    def test_condition_expression(self, sample_vs):
        bp = Breakpoint(condition="step_idx >= 1")
        step = PlanStep("projection", {})
        assert bp.should_break(0, step, sample_vs, []) is False
        assert bp.should_break(1, step, sample_vs, []) is True

    def test_condition_eval_failure_does_not_break(self, sample_vs):
        bp = Breakpoint(condition="1/0")
        step = PlanStep("identity", {})
        assert bp.should_break(0, step, sample_vs, []) is False

    def test_condition_accesses_vs_and_results(self, sample_vs):
        bp = Breakpoint(condition="len(vs.artifact_space) == 2")
        step = PlanStep("identity", {})
        assert bp.should_break(0, step, sample_vs, []) is True
        empty_vs = ViewState()
        assert bp.should_break(0, step, empty_vs, []) is False


# ── ExecutionSnapshot ──


class TestExecutionSnapshot:
    def test_summary_includes_step_and_primitive(self, sample_vs):
        result = QueryResult(artifacts=frozenset({Artifact(id="x", type="config_value", target="t")}))
        snap = ExecutionSnapshot(
            step_index=0,
            step=PlanStep("projection", {"filter_type": "artifact"}),
            vs_before=sample_vs,
            vs_after=sample_vs,
            result=result,
            resolved_kwargs={},
        )
        summary = snap.summary
        assert "Step 0" in summary
        assert "projection" in summary
        assert "1 arts" in summary

    def test_diff_vs_adds_and_removes(self, sample_vs):
        vs1 = ViewState(
            artifact_space=frozenset(
                {
                    Artifact(id="a", type="config_value", target="t"),
                }
            )
        )
        vs2 = ViewState(
            artifact_space=frozenset(
                {
                    Artifact(id="a", type="config_value", target="t"),
                    Artifact(id="b", type="config_value", target="t"),
                }
            )
        )
        snap1 = ExecutionSnapshot(
            step_index=0,
            step=PlanStep("identity", {}),
            vs_before=vs1,
            vs_after=vs1,
            result=QueryResult(),
            resolved_kwargs={},
        )
        snap2 = ExecutionSnapshot(
            step_index=1,
            step=PlanStep("projection", {}),
            vs_before=vs1,
            vs_after=vs2,
            result=QueryResult(),
            resolved_kwargs={},
        )
        diff = snap1.diff_vs(snap2)
        assert "b" in diff["added_artifacts"]
        assert diff["common_artifact_count"] == 1


# ── StepController ──


class TestStepController:
    def test_records_snapshots(self, sample_vs):
        ctrl = StepController()
        step = PlanStep("identity", {})
        ctrl.pre_step_hook(0, step, sample_vs, [])
        assert len(ctrl.snapshots) == 1
        s = ctrl.snapshots[0]
        assert s.step_index == 0
        assert s.vs_before is sample_vs

    def test_updates_snapshot_after_step(self, sample_vs):
        ctrl = StepController()
        step = PlanStep("projection", {"filter_type": "artifact"})
        ctrl.pre_step_hook(0, step, sample_vs, [])
        result = QueryResult(artifacts=frozenset({Artifact(id="x", type="config_value", target="t")}))
        ctrl.post_step_hook(0, step, sample_vs, result)
        s = ctrl.snapshots[0]
        assert s.result is result
        assert s.vs_after is sample_vs

    def test_add_remove_breakpoint(self):
        ctrl = StepController()
        bp = Breakpoint(step_index=0)
        idx = ctrl.add_breakpoint(bp)
        assert idx == 0
        assert len(ctrl.breakpoints) == 1
        ctrl.remove_breakpoint(0)
        assert len(ctrl.breakpoints) == 0

    def test_clear_breakpoints(self):
        ctrl = StepController()
        ctrl.add_breakpoint(Breakpoint(step_index=0))
        ctrl.add_breakpoint(Breakpoint(step_index=1))
        ctrl.clear_breakpoints()
        assert len(ctrl.breakpoints) == 0

    def test_remove_out_of_range_is_noop(self):
        ctrl = StepController()
        ctrl.remove_breakpoint(99)
        ctrl.remove_breakpoint(-1)


# ── DebugExecutor ──


class TestDebugExecutor:
    def test_executes_plan_and_records_snapshots(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        result = dx.execute(SAMPLE_STEPS)
        assert isinstance(result, PlanResult)
        assert result.step_count == 2
        assert len(dx.snapshots) == 2

    def test_snapshots_have_correct_steps(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.execute(SAMPLE_STEPS)
        assert dx.snapshots[0].step_index == 0
        assert dx.snapshots[0].step.primitive == "identity"
        assert dx.snapshots[1].step_index == 1
        assert dx.snapshots[1].step.primitive == "projection"

    def test_snapshot_has_results_after_step(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.execute(SAMPLE_STEPS)
        for snap in dx.snapshots:
            assert snap.result is not None

    def test_add_breakpoint(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        idx = dx.add_breakpoint(Breakpoint(step_index=0))
        assert idx == 0
        assert len(dx.breakpoints) == 1

    def test_remove_breakpoint(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.add_breakpoint(Breakpoint(step_index=0))
        dx.remove_breakpoint(0)
        assert len(dx.breakpoints) == 0

    def test_clear_breakpoints(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.add_breakpoint(Breakpoint(step_index=0))
        dx.add_breakpoint(Breakpoint(step_index=1))
        dx.clear_breakpoints()
        assert len(dx.breakpoints) == 0

    def test_breakpoint_pauses_execution(self, sample_vs):
        """Breakpoint pauses but does not cancel execution."""
        dx = DebugExecutor(sample_vs)
        dx.add_breakpoint(Breakpoint(step_index=0))
        result = dx.execute(SAMPLE_STEPS)
        assert result.step_count == 2

    def test_breakpoint_pauses_on_condition(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.add_breakpoint(Breakpoint(condition="step_idx == 1"))
        result = dx.execute(SAMPLE_STEPS)
        assert result.step_count == 2


# ── step_through ──


class TestStepThrough:
    def test_yields_before_each_step(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        gen = dx.step_through(SAMPLE_STEPS)
        snapshots = list(gen)
        assert len(snapshots) == 2
        for i, snap in enumerate(snapshots):
            assert snap.step_index == i

    def test_snapshots_have_before_state(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        snaps = list(dx.step_through(SAMPLE_STEPS))
        for snap in snaps:
            assert snap.vs_before is not None


# ── compare_snapshots ──


class TestCompareSnapshots:
    def test_compare_same_index_returns_no_diff(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.execute(SAMPLE_STEPS)
        diff = dx.compare_snapshots(0, 0)
        assert diff is not None
        assert diff["added_artifacts"] == []
        assert diff["removed_artifacts"] == []

    def test_compare_out_of_range_returns_none(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.execute(SAMPLE_STEPS)
        assert dx.compare_snapshots(0, 99) is None
        assert dx.compare_snapshots(99, 0) is None
        assert dx.compare_snapshots(-1, 0) is None

    def test_compare_different_snapshots(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        # First step is identity (no change), second is projection
        dx.execute(
            [
                PlanStep("identity", {}),
                PlanStep(
                    "projection",
                    {
                        "filter_type": "artifact",
                        "predicate": lambda a: a.id == "nonexistent",
                    },
                ),
            ]
        )
        if len(dx.snapshots) >= 2:
            diff = dx.compare_snapshots(0, 1)
            assert diff is not None
            assert isinstance(diff["added_artifacts"], list)


# ── snapshot_at ──


class TestSnapshotAt:
    def test_returns_snapshot_by_step_index(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.execute(SAMPLE_STEPS)
        snap = dx.snapshot_at(0)
        assert snap is not None
        assert snap.step_index == 0

    def test_returns_none_for_missing_step(self, sample_vs):
        dx = DebugExecutor(sample_vs)
        dx.execute(SAMPLE_STEPS)
        assert dx.snapshot_at(99) is None
