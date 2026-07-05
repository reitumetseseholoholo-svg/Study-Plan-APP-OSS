"""ProvenanceLab — unified Lab API for provenance queries.

Wraps PlanExecutor, ExecutionContext, and ArtifactStore into a single
interface used by Tutor, Debugger, and interactive exploration.

The Lab is Layer 3 of the provenance architecture:
  Layer 0: Kernel data model (types.py)
  Layer 1: Kernel primitives (primitives.py)
  Layer 2: Execution context (execution.py)
  Layer 3: Lab (this module) — plan execution, templates, storage, integration

Usage::

    from studyplan.provenance.lab import ProvenanceLab
    lab = ProvenanceLab(vs)

    # Execute a raw plan with result-threading
    result = lab.execute([
        PlanStep("projection", {"filter_type": "transformation",
                 "predicate": lambda t: any("discount" in c[1] for c in t.constraints)}),
        PlanStep("traversal", {"seed_set": "$0.transforms.output_ids",
                 "edge_semantics": "transformational/generative_mapping",
                 "depth_limit": "transitive"}),
    ])

    # Use a named query template
    result = lab.ask("downstream_impact", constraint_text="constant_discount_rate",
                     edge_semantics="transformational/generative_mapping")

    # Save and load results via ArtifactStore
    key = lab.save(result)
    loaded = lab.load(key)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from studyplan.provenance.kernel import (
    ViewState,
)
from studyplan.provenance.execution import ExecutionContext, ReasoningTrace

from studyplan.provenance.lab.planner import PlanExecutor, PlanStep, PlanResult


# ============================================================
# LabResult — unified output type
# ============================================================


@dataclass
class LabResult:
    """Result of a Lab query — combines plan results with contextual info.

    Carries the plan steps that produced it, the execution result,
    a summary dict for UI consumption, and optional annotations.
    """

    question: str
    target: str
    plan_result: PlanResult
    summary: dict[str, Any] = field(default_factory=dict)
    annotations: list[str] = field(default_factory=list)
    dependency_path: tuple[str, ...] = ()
    assumptions: frozenset[tuple[str, str]] = frozenset()

    @property
    def steps(self) -> list[PlanStep]:
        return self.plan_result.steps

    @property
    def last(self) -> Any:
        return self.plan_result.last

    @property
    def step_count(self) -> int:
        return self.plan_result.step_count

    def __repr__(self) -> str:
        return f"LabResult(question='{self.question}', target='{self.target}', steps={self.step_count})"


# ============================================================
# Query templates — reusable plan builders
# ============================================================


class QueryTemplates:
    """Reusable query plan templates.

    Each template is a static method that returns (plan, summary_extractor).
    The summary_extractor converts a PlanResult into a LabResult summary dict.
    """

    @staticmethod
    def inherited_assumptions(
        artifact_id: str,
    ) -> tuple[list[PlanStep], Callable[[PlanResult], dict[str, Any]]]:
        """Plan: find all constraints inherited by an artifact."""
        steps = [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.id == artifact_id,
                },
            ),
            PlanStep(
                "collect_inherited_constraints",
                {
                    "artifact_id": artifact_id,
                },
            ),
        ]

        def extract(pr: PlanResult) -> dict[str, Any]:
            constraints = pr.step_results[1]
            ass = sorted(
                (c for c in constraints.artifacts if c.metadata_dict().get("constraint_key") == "assumption"),
                key=lambda a: a.id,
            )
            cons = sorted(
                (c for c in constraints.artifacts if c.metadata_dict().get("constraint_key") == "consumes"),
                key=lambda a: a.id,
            )
            return {
                "artifact": artifact_id,
                "total_constraints": len(constraints.artifacts),
                "assumptions": [a.target.split(":")[-1] for a in ass],
                "consumes": [c.target.split(":")[-1] for c in cons],
            }

        return steps, extract

    @staticmethod
    def downstream_impact(
        constraint_text: str,
        edge_semantics: str = "transformational/generative_mapping",
    ) -> tuple[list[PlanStep], Callable[[PlanResult], dict[str, Any]]]:
        """Plan: find all artifacts impacted by removing a constraint."""
        text = constraint_text
        steps = [
            PlanStep(
                "projection",
                {
                    "filter_type": "transformation",
                    "predicate": lambda t: any(text in c[1] for c in t.constraints),
                },
            ),
            PlanStep(
                "traversal",
                {
                    "seed_set": "$0.transforms.output_ids",
                    "edge_semantics": edge_semantics,
                    "depth_limit": "transitive",
                },
            ),
        ]

        def extract(pr: PlanResult) -> dict[str, Any]:
            impacted = pr.step_results[1]
            return {
                "constraint": constraint_text,
                "impacted_artifacts": sorted(a.id for a in impacted.artifacts),
                "impact_count": len(impacted.artifacts),
            }

        return steps, extract

    @staticmethod
    def upstream_artifacts(
        artifact_id: str,
    ) -> tuple[list[PlanStep], Callable[[PlanResult], dict[str, Any]]]:
        """Plan: find all upstream artifacts (no type filter)."""
        steps = [
            PlanStep(
                "collect_inherited_constraints",
                {
                    "artifact_id": artifact_id,
                },
            ),
        ]

        def extract(pr: PlanResult) -> dict[str, Any]:
            # collect_inherited_constraints returns constraints, not artifacts.
            # The upstream artifacts are discovered through the constraints.
            constraints = pr.step_results[0]
            upstream = frozenset(
                c.target.split(":")[-1]
                for c in constraints.artifacts
                if c.metadata_dict().get("constraint_key") != "consumes"
            )
            return {
                "artifact": artifact_id,
                "upstream_artifacts": sorted(upstream),
                "count": len(upstream),
            }

        return steps, extract

    @staticmethod
    def base_prerequisites(
        artifact_id: str,
        prerequisite_type: str = "config_value",
    ) -> tuple[list[PlanStep], Callable[[PlanResult], dict[str, Any]]]:
        """Plan: find base prerequisites of a specific type.

        Delegates to ExecutionContext for the FM-specific type filter.
        This template exists so the Lab can answer the same question
        as base_prerequisites without bypassing the plan system.
        """
        target_type = prerequisite_type
        steps = [
            PlanStep(
                "projection",
                {
                    "filter_type": "artifact",
                    "predicate": lambda a: a.type == target_type,
                },
            ),
        ]

        def extract(pr: PlanResult) -> dict[str, Any]:
            prereqs = pr.step_results[0]
            return {
                "artifact": artifact_id,
                "base_prerequisites": sorted(a.id for a in prereqs.artifacts),
                "count": len(prereqs.artifacts),
            }

        return steps, extract


# ============================================================
# ProvenanceLab
# ============================================================


class ProvenanceLab:
    """Unified Lab API for provenance queries.

    Three ways to query:
    1. ``execute(plan)`` — raw PlanStep list with result-threading
    2. ``ask(question, **params)`` — named query template
    3. ``query(method, **params)`` — pass through to ExecutionContext

    Storage integration via ArtifactStore (optional):
    - ``save(result)`` → key (content_hash of final ViewState)
    - ``load(key)`` → LabResult (reconstructed from store)
    """

    def __init__(self, vs: ViewState, store: Any | None = None, ec: Any | None = None):
        self.vs = vs
        self.ctx = ExecutionContext(vs, ec)
        self.executor = PlanExecutor(vs, ec)
        self.store = store
        self.templates = QueryTemplates()

    # ── Execution ─────────────────────────────────────────────

    def execute(self, steps: list[PlanStep]) -> PlanResult:
        """Execute a raw plan with result-threading."""
        return self.executor.execute(steps)

    # ── Query templates ───────────────────────────────────────

    def ask(self, question: str, **params: Any) -> LabResult:
        """Run a named query template.

        Supported questions:
        - ``inherited_assumptions`` — params: artifact_id
        - ``downstream_impact`` — params: constraint_text, [edge_semantics]
        - ``upstream_artifacts`` — params: artifact_id
        - ``base_prerequisites`` — params: artifact_id, [prerequisite_type]
        For ``dependency_path``, use ``lab.query("dependency_path", ...)``.
        """
        template_map: dict[str, Callable[..., tuple[list[PlanStep], Callable]]] = {
            "inherited_assumptions": self.templates.inherited_assumptions,
            "downstream_impact": self.templates.downstream_impact,
            "upstream_artifacts": self.templates.upstream_artifacts,
            "base_prerequisites": self.templates.base_prerequisites,
        }

        builder = template_map.get(question)
        if builder is None:
            valid = sorted(template_map.keys())
            raise ValueError(f"Unknown question: '{question}'. Valid: {valid}")

        steps, extractor = builder(**params)
        plan_result = self.executor.execute(steps)
        summary = extractor(plan_result)

        target = params.get("artifact_id") or params.get("constraint_text") or ""

        return LabResult(
            question=question,
            target=target,
            plan_result=plan_result,
            summary=summary,
        )

    # ── ExecutionContext pass-through ─────────────────────────

    def query(self, method: str, **params: Any) -> ReasoningTrace:
        """Pass through to an ExecutionContext query method.

        Provides a bridge between the Lab's plan-based queries and
        the ExecutionContext's pre-built query methods.

        Supported methods: inherited_assumptions, downstream_impact,
        base_prerequisites, upstream_artifacts, dependency_path.
        """
        fn = getattr(self.ctx, method, None)
        if fn is None:
            valid = [
                "inherited_assumptions",
                "downstream_impact",
                "base_prerequisites",
                "upstream_artifacts",
                "dependency_path",
            ]
            raise ValueError(f"Unknown ExecutionContext method: '{method}'. Valid: {valid}")
        return fn(**params)

    # ── Storage ───────────────────────────────────────────────

    def save(self, result: LabResult | PlanResult) -> str | None:
        """Save the final ViewState to the artifact store.

        Returns the content_hash key, or None if no store is configured.
        """
        if self.store is None:
            return None
        final_vs = result.final_viewstate if isinstance(result, PlanResult) else result.plan_result.final_viewstate
        return self.store.save(final_vs)

    def load(self, key: str) -> ViewState | None:
        """Load a ViewState from the artifact store."""
        if self.store is None:
            return None
        return self.store.load(key)

    @property
    def store_available(self) -> bool:
        """Whether an artifact store is configured."""
        return self.store is not None
