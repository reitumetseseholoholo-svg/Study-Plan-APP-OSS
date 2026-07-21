"""Lab — Layer 3 of the provenance architecture.

The Lab is the application layer: it wraps PlanExecutor, ExecutionContext,
and ArtifactStore into a unified interface for Tutor, Debugger, and
interactive provenance exploration.

Key innovation: PlanExecutor bridges the compose() result-threading gap (E3)
by resolving ``$N.field`` references at runtime, enabling multi-step query
plans where step N+1 dynamically depends on step N's discovered results.

Usage::

    from studyplan.provenance.lab import ProvenanceLab, PlanStep, PlanResult
    lab = ProvenanceLab(vs)

    # Named query template
    result = lab.ask("downstream_impact", constraint_text="constant_discount_rate")
    print(result.summary)

    # Raw plan with result-threading
    plan_result = lab.execute([
        PlanStep("projection", {"filter_type": "transformation",
                 "predicate": lambda t: any("discount" in c[1] for c in t.constraints)}),
        PlanStep("traversal", {"seed_set": "$0.transforms.output_ids",
                 "edge_semantics": "transformational/generative_mapping",
                 "depth_limit": "transitive"}),
    ])
"""

from studyplan.provenance.lab.lab import ProvenanceLab, LabResult
from studyplan.provenance.lab.planner import PlanExecutor, PlanStep, PlanResult

__all__ = [
    "ProvenanceLab",
    "LabResult",
    "PlanExecutor",
    "PlanStep",
    "PlanResult",
]
