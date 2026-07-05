"""PlanExecutor — dynamic plan execution with result-threading between steps.

Solves the compose() result-threading gap (E3). Each step can reference prior
step results using ``$N.field`` syntax in kwargs. The executor resolves these
references at runtime and threads both ViewState and QueryResults through the plan.

This is the **core innovation of the Lab layer**: it allows multi-step query
plans where step N+1 dynamically depends on what step N discovered, without
requiring manual primitive chaining in the execution layer.

Usage::

    executor = PlanExecutor(vs, ec)
    vs_out, results = executor.execute([
        PlanStep("projection", {
            "filter_type": "transformation",
            "predicate": lambda t: any("constant_discount_rate" in c[1] for c in t.constraints),
        }),
        PlanStep("traversal", {
            "seed_set": "$0.transforms.output_ids",  # references step 0's transforms
            "edge_semantics": "transformational/generative_mapping",
            "depth_limit": "transitive",
        }),
    ])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    EvaluationContext,
    QueryResult,
    PREDEFINED_CONTEXTS,
    identity,
    projection,
    traversal,
    reduction,
    collect_inherited_constraints,
)


# ============================================================
# Plan definition
# ============================================================


@dataclass(frozen=True)
class PlanStep:
    """A single step in a query plan.

    Each step specifies a primitive and its kwargs. Kwarg values can be:
    - Static values (str, int, set, list, bool, None, Callable)
    - Result references: ``$N.field.subfield`` meaning "use step N's QueryResult.field.subfield"

    Supported field paths:
    - ``$0.artifacts`` — step N's result artifacts (frozenset[Artifact])
    - ``$0.transforms`` — step N's result transforms (frozenset[Transformation])
    - ``$0.transforms.output_ids`` — frozenset[str] of output_artifact_ids from step N's transforms
    - ``$0.artifacts.ids`` — frozenset[str] of artifact ids from step N's result
    - ``$0.metadata.key`` — value from step N's result metadata dict
    """

    primitive: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanResult:
    """Result of executing a complete query plan."""

    steps: list[PlanStep]
    step_results: list[QueryResult]
    final_viewstate: ViewState
    step_count: int

    @property
    def last(self) -> QueryResult:
        """Convenience: return the last step's QueryResult."""
        return self.step_results[-1] if self.step_results else QueryResult()

    def result_of(self, step_index: int) -> QueryResult:
        """Return the QueryResult of a specific step."""
        return self.step_results[step_index]

    def __repr__(self) -> str:
        return (
            f"PlanResult(steps={len(self.steps)}, "
            f"results={len(self.step_results)}, "
            f"final_vs_hash={self.final_viewstate.content_hash[:12]})"
        )


# ============================================================
# Reference resolution helpers
# ============================================================

_RESULT_FIELD_EXTRACTORS: dict[str, Callable[[QueryResult], Any]] = {
    "artifacts": lambda r: r.artifacts,
    "transforms": lambda r: r.transforms,
}

_DERIVED_FIELD_EXTRACTORS: dict[str, Callable[[QueryResult], Any]] = {
    "artifacts.ids": lambda r: frozenset(a.id for a in r.artifacts),
    "transforms.ids": lambda r: frozenset(t.id for t in r.transforms),
    "transforms.output_ids": lambda r: frozenset(t.output_artifact_id for t in r.transforms),
    "transforms.input_ids": lambda r: frozenset(t.input_artifact_id for t in r.transforms),
}

_ALL_EXTRACTORS: dict[str, Callable[[QueryResult], Any]] = {}
_ALL_EXTRACTORS.update(_RESULT_FIELD_EXTRACTORS)
_ALL_EXTRACTORS.update(_DERIVED_FIELD_EXTRACTORS)


def _resolve_reference(ref: str, prior_results: list[QueryResult]) -> Any:
    """Resolve ``$N.field.path`` reference against prior results.

    Examples:
        "$0.transforms" → QueryResult.transforms of step 0
        "$1.artifacts.ids" → frozenset of artifact ids from step 1
        "$2.metadata.count" → prior_results[2].metadata.get("count")
    """
    if not ref.startswith("$") or len(ref) < 2 or not ref[1].isdigit():
        return ref

    body = ref[1:]
    dot = body.find(".")
    if dot == -1:
        step_idx = int(body)
        return prior_results[step_idx]

    step_str = body[:dot]
    field_path = body[dot + 1 :]

    step_idx = int(step_str)
    result = prior_results[step_idx]

    if field_path in _ALL_EXTRACTORS:
        return _ALL_EXTRACTORS[field_path](result)

    # Handle metadata paths: "metadata.key"
    if field_path.startswith("metadata."):
        key = field_path[9:]
        return result.metadata.get(key)

    raise ValueError(
        f"Unknown result field path: '{field_path}'. Supported: {sorted(_ALL_EXTRACTORS.keys())}, metadata.<key>"
    )


def _resolve_kwargs(kwargs: dict[str, Any], prior_results: list[QueryResult]) -> dict[str, Any]:
    """Resolve all ``$N.field`` references in a kwargs dict.

    Handles nested structures (dicts, lists) recursively.
    """
    resolved: dict[str, Any] = {}
    for k, v in kwargs.items():
        if isinstance(v, str) and v.startswith("$"):
            resolved[k] = _resolve_reference(v, prior_results)
        elif isinstance(v, dict):
            resolved[k] = _resolve_kwargs(v, prior_results)
        elif isinstance(v, (list, tuple)):
            resolved[k] = type(v)(
                _resolve_reference(item, prior_results) if isinstance(item, str) and item.startswith("$") else item
                for item in v
            )
        else:
            resolved[k] = v
    return resolved


# ============================================================
# PlanExecutor
# ============================================================


class PlanExecutor:
    """Executes query plans with result-threading between steps.

    Composes kernel primitives (projection, traversal, reduction,
    collect_inherited_constraints) into multi-step plans where each
    step can reference prior step results.

    This is the bridge between raw kernel primitives and the
    ExecutionContext's hardcoded query methods. Plans can express
    any query the execution layer supports, and more.
    """

    def __init__(
        self,
        vs: ViewState,
        ec: EvaluationContext | None = None,
        pre_step_hook: Callable[[int, PlanStep, ViewState, list[QueryResult]], None] | None = None,
        post_step_hook: Callable[[int, PlanStep, ViewState, QueryResult], None] | None = None,
    ):
        self.vs = vs
        self.ec = ec or PREDEFINED_CONTEXTS["default_optimizer"]
        self.pre_step_hook = pre_step_hook
        self.post_step_hook = post_step_hook

    def execute(self, steps: list[PlanStep]) -> PlanResult:
        """Execute a list of PlanSteps, threading ViewState and QueryResults.

        Each step's kwargs may reference prior results via ``$N.field``.
        Returns the final ViewState and list of per-step QueryResults.
        """
        current_vs = self.vs
        results: list[QueryResult] = []

        for step_idx, step in enumerate(steps):
            if self.pre_step_hook:
                self.pre_step_hook(step_idx, step, current_vs, results)

            resolved_kwargs = _resolve_kwargs(step.kwargs, results)

            if step.primitive == "projection":
                result, current_vs = projection(current_vs, self.ec, **resolved_kwargs)
            elif step.primitive == "traversal":
                result, current_vs = traversal(current_vs, self.ec, **resolved_kwargs)
            elif step.primitive == "reduction":
                result, current_vs = reduction(current_vs, self.ec, **resolved_kwargs)
            elif step.primitive == "identity":
                result, current_vs = identity(current_vs, self.ec)
            elif step.primitive == "collect_inherited_constraints":
                constraints = collect_inherited_constraints(current_vs, **resolved_kwargs)
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
                raise ValueError(
                    f"Unknown primitive: '{step.primitive}'. "
                    f"Supported: projection, traversal, reduction, "
                    f"identity, collect_inherited_constraints"
                )

            if self.post_step_hook:
                self.post_step_hook(step_idx, step, current_vs, result)

            results.append(result)

        return PlanResult(
            steps=steps,
            step_results=results,
            final_viewstate=current_vs,
            step_count=len(steps),
        )
