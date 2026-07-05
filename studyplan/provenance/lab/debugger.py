"""Debugger (Layer 6) — breakpoints, step-through, execution comparison.

Essentialist Question:
    What phenomenon does a provenance debugger exist to preserve?
Answer:
    Execution observability — the ability to pause, inspect, and compare
    plan execution at any step without modifying the plan or kernel.

Architecture:
    The Debugger wraps PlanExecutor via optional hook callbacks. It does
    NOT modify the executor's core loop — hooks are an add-only API.
    All debugger state (breakpoints, snapshots) lives in the Debugger,
    not in the executor.

Layer 6 of the Observable Cognition Platform:
    - Layer 1: Kernel (QueryTraceEntry)
    - Layer 2: Execution (ReasoningTrace)
    - Layer 3: Lab (PlanExecutor → PlanResult)
    - Layer 4: Compiler (DomainSpec → ViewState → CompilationRecord)
    - Layer 5: iR (0–4 representation layers)
    - Layer 6: Debugger (breakpoints, step-through, comparison)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator

from studyplan.provenance.kernel import (
    ViewState,
    QueryResult,
    EvaluationContext,
    PREDEFINED_CONTEXTS,
)
from studyplan.provenance.lab.planner import PlanExecutor, PlanStep, PlanResult


# ============================================================
# ExecutionSnapshot — immutable step record
# ============================================================


@dataclass(frozen=True)
class ExecutionSnapshot:
    """Captures full execution state at one step boundary.

    Stored between steps so the debugger can inspect, compare,
    and restore execution state at any point.
    """

    step_index: int
    step: PlanStep
    vs_before: ViewState
    vs_after: ViewState
    result: QueryResult | None
    resolved_kwargs: dict[str, Any]

    @property
    def summary(self) -> str:
        r = self.result
        r_summary = f"{len(r.artifacts)} arts, {len(r.transforms)} xforms" if r else "no result"
        return f"Step {self.step_index}: {self.step.primitive}({self.step.kwargs}) → {r_summary}"

    def diff_vs(self, other: ExecutionSnapshot) -> dict[str, Any]:
        """Diff this snapshot's ViewState against another's."""
        before_ids = {a.id for a in self.vs_after.artifact_space}
        after_ids = {a.id for a in other.vs_after.artifact_space}
        return {
            "added_artifacts": sorted(after_ids - before_ids),
            "removed_artifacts": sorted(before_ids - after_ids),
            "common_artifact_count": len(before_ids & after_ids),
        }


# ============================================================
# Breakpoint — condition to pause execution
# ============================================================


@dataclass(frozen=True)
class Breakpoint:
    """A condition that pauses plan execution.

    If ``step_index`` is >= 0, the breakpoint triggers only on that
    specific step. If -1, it triggers on any step. The optional
    ``condition`` is a Python expression evaluated against the plan
    state dict (available locals: step_idx, step, vs, results).
    """

    step_index: int = -1
    condition: str | None = None
    enabled: bool = True

    def should_break(self, step_idx: int, step: PlanStep, vs: ViewState, results: list[QueryResult]) -> bool:
        """Check if execution should pause at this point."""
        if not self.enabled:
            return False
        if self.step_index >= 0 and self.step_index != step_idx:
            return False
        if self.condition:
            try:
                return bool(
                    eval(
                        self.condition,
                        {
                            "step_idx": step_idx,
                            "step": step,
                            "vs": vs,
                            "results": results,
                        },
                    )
                )
            except Exception:
                return False
        return True


# ============================================================
# StepController — manages breakpoints and step-through state
# ============================================================


class StepController:
    """Controls step-through execution and breakpoint management.

    Used as the hook backend for DebugExecutor. Manages pause/resume
    state and breakpoint conditions.
    """

    def __init__(self):
        self._breakpoints: list[Breakpoint] = []
        self._paused: bool = False
        self._current_step: int = -1
        self._steps_total: int = 0
        self._snapshots: list[ExecutionSnapshot] = []

    @property
    def snapshots(self) -> list[ExecutionSnapshot]:
        return list(self._snapshots)

    @property
    def breakpoints(self) -> list[Breakpoint]:
        return list(self._breakpoints)

    def add_breakpoint(self, bp: Breakpoint) -> int:
        self._breakpoints.append(bp)
        return len(self._breakpoints) - 1

    def remove_breakpoint(self, index: int) -> None:
        if 0 <= index < len(self._breakpoints):
            self._breakpoints.pop(index)

    def clear_breakpoints(self) -> None:
        self._breakpoints.clear()

    def pre_step_hook(self, step_idx: int, step: PlanStep, vs: ViewState, results: list[QueryResult]) -> None:
        """Called by PlanExecutor before each step. Checks breakpoints."""
        self._current_step = step_idx

        # Record pre-step snapshot
        snap = ExecutionSnapshot(
            step_index=step_idx,
            step=step,
            vs_before=vs,
            vs_after=vs,
            result=None,
            resolved_kwargs=dict(step.kwargs),
        )
        self._snapshots.append(snap)

        for bp in self._breakpoints:
            if bp.should_break(step_idx, step, vs, results):
                self._paused = True

    def post_step_hook(self, step_idx: int, step: PlanStep, vs: ViewState, result: QueryResult) -> None:
        """Called by PlanExecutor after each step. Updates snapshot."""
        if 0 <= step_idx < len(self._snapshots):
            old = self._snapshots[step_idx]
            self._snapshots[step_idx] = ExecutionSnapshot(
                step_index=old.step_index,
                step=old.step,
                vs_before=old.vs_before,
                vs_after=vs,
                result=result,
                resolved_kwargs=old.resolved_kwargs,
            )

    def resume(self) -> None:
        self._paused = False


# ============================================================
# DebugExecutor — plan executor with debugger hooks
# ============================================================


class DebugExecutor:
    """Plan executor with breakpoints, snapshots, and step-through.

    Wraps PlanExecutor with debugger hooks. Provides both bulk
    execution (with breakpoints) and generator-based step-through
    for interactive debugging.
    """

    def __init__(self, vs: ViewState, ec: EvaluationContext | None = None):
        self.controller = StepController()
        self._executor = PlanExecutor(
            vs,
            ec or PREDEFINED_CONTEXTS["default_optimizer"],
            pre_step_hook=self.controller.pre_step_hook,
            post_step_hook=self.controller.post_step_hook,
        )

    @property
    def snapshots(self) -> list[ExecutionSnapshot]:
        return self.controller.snapshots

    @property
    def breakpoints(self) -> list[Breakpoint]:
        return self.controller.breakpoints

    def add_breakpoint(self, bp: Breakpoint) -> int:
        """Add a breakpoint. Returns its index."""
        return self.controller.add_breakpoint(bp)

    def remove_breakpoint(self, index: int) -> None:
        self.controller.remove_breakpoint(index)

    def clear_breakpoints(self) -> None:
        self.controller.clear_breakpoints()

    def execute(self, steps: list[PlanStep]) -> PlanResult:
        """Execute plan with breakpoint checking.

        Execution pauses (via pre_step_hook) when a breakpoint condition
        is met. Use ``resume()`` to continue. Returns the final PlanResult.
        """
        return self._executor.execute(steps)

    def step_through(self, steps: list[PlanStep]) -> Generator[ExecutionSnapshot, None, PlanResult]:
        """Generator-based step-through execution.

        Yields an ExecutionSnapshot before each step, allowing the
        caller to inspect state and decide whether to continue.
        After the last step yields, returns the final PlanResult.
        """
        from studyplan.provenance.lab.planner import _resolve_kwargs

        current_vs = self._executor.vs
        results: list[QueryResult] = []

        for step_idx, step in enumerate(steps):
            resolved = _resolve_kwargs(step.kwargs, results)

            snap = ExecutionSnapshot(
                step_index=step_idx,
                step=step,
                vs_before=current_vs,
                vs_after=current_vs,
                result=None,
                resolved_kwargs=resolved,
            )
            # Store in controller for later comparison
            while len(self.controller._snapshots) <= step_idx:
                self.controller._snapshots.append(None)  # type: ignore
            self.controller._snapshots[step_idx] = snap

            yield snap

            # Execute the step (caller resumed)
            primitive = step.primitive
            ec = self._executor.ec
            vs = current_vs

            if primitive == "projection":
                from studyplan.provenance.kernel import projection as _proj

                result, current_vs = _proj(vs, ec, **resolved)
            elif primitive == "traversal":
                from studyplan.provenance.kernel import traversal as _trav

                result, current_vs = _trav(vs, ec, **resolved)
            elif primitive == "reduction":
                from studyplan.provenance.kernel import reduction as _red

                result, current_vs = _red(vs, ec, **resolved)
            elif primitive == "identity":
                from studyplan.provenance.kernel import identity as _id

                result, current_vs = _id(vs, ec)
            elif primitive == "collect_inherited_constraints":
                from studyplan.provenance.kernel import collect_inherited_constraints as _cic
                from studyplan.provenance.kernel.types import Artifact

                constraints = _cic(current_vs, **resolved)
                constraint_artifacts = frozenset(
                    Artifact(
                        id=f"c:{k}:{v}",
                        type="config_value",
                        target=f"constraint:{k}={v}",
                        metadata=(("constraint_key", k), ("constraint_value", v)),
                    )
                    for k, v in constraints
                )
                result = QueryResult(artifacts=constraint_artifacts)
            else:
                raise ValueError(f"Unknown primitive: '{primitive}'")

            results.append(result)

            # Update snapshot with after-state
            self.controller._snapshots[step_idx] = ExecutionSnapshot(
                step_index=step_idx,
                step=step,
                vs_before=snap.vs_before,
                vs_after=current_vs,
                result=result,
                resolved_kwargs=resolved,
            )

        return PlanResult(
            steps=steps,
            step_results=results,
            final_viewstate=current_vs,
            step_count=len(steps),
        )

    def resume(self) -> None:
        """Resume execution after a breakpoint pause."""
        self.controller.resume()

    def compare_snapshots(self, idx_a: int, idx_b: int) -> dict[str, Any] | None:
        """Compare two execution snapshots.

        Returns a dict with added/removed artifacts between the two
        snapshots' ViewStates, or None if either index is out of range.
        """
        if idx_a < 0 or idx_a >= len(self.controller.snapshots):
            return None
        if idx_b < 0 or idx_b >= len(self.controller.snapshots):
            return None
        snap_a = self.controller.snapshots[idx_a]
        snap_b = self.controller.snapshots[idx_b]
        return snap_a.diff_vs(snap_b)

    def snapshot_at(self, step_index: int) -> ExecutionSnapshot | None:
        """Return the snapshot for a given step, if available."""
        for snap in self.controller.snapshots:
            if snap.step_index == step_index:
                return snap
        return None
