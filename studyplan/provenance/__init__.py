"""Domain compilation and provenance — compile spec to ViewState, query dependency graph.

Components::

  DomainCompiler     — transforms TopicSpec → ViewState
  ExecutionContext   — query runtime over ViewState (assumptions, dependencies, prerequisites)
  ViewState          — immutable artifact+transform graph
  collect_inherited_constraints — BFS constraint propagation (kernel primitive)

This package is architecturally separate from ``studyplan.cci`` (Cognitive
Runtime — transition-system algebra for decision process traces). The two
answer different questions: ``provenance`` answers "what does this concept
depend on?" (static structure), while ``cci`` answers "how did this decision
unfold?" (dynamic execution).
"""

from studyplan.provenance.compiler import DomainCompiler, TopicSpec, ComputationStep
from studyplan.provenance.execution import ExecutionContext, ReasoningTrace
from studyplan.provenance.kernel import (
    ViewState,
    Artifact,
    Transformation,
    identity,
    projection,
    traversal,
    reduction,
    compose,
    collect_inherited_constraints,
)

__all__ = [
    "DomainCompiler",
    "TopicSpec",
    "ComputationStep",
    "ExecutionContext",
    "ReasoningTrace",
    "ViewState",
    "Artifact",
    "Transformation",
    "identity",
    "projection",
    "traversal",
    "reduction",
    "compose",
    "collect_inherited_constraints",
]
