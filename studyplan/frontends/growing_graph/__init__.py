"""Growing Graph — graph expansion topology.

This algebra tests whether the protocol survives a state that
**expands during execution**.  Nodes and edges appear dynamically
as the executor explores a goal tree.  The graph topology is not
known when execution starts — it is *discovered*.

Reference topology: planning, proof search, construction.
"""

from studyplan.frontends.growing_graph.template import ExpansionRule, GrowingGraphTemplate
from studyplan.frontends.growing_graph.executor import GrowingGraphExecutor

__all__ = [
    "ExpansionRule",
    "GrowingGraphTemplate",
    "GrowingGraphExecutor",
]
