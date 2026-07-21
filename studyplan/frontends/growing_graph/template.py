"""Growing graph problem definition — goal tree with expansion rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExpansionRule:
    """Defines how one goal type expands into subtasks.

    When the executor encounters a node whose ``type`` matches
    ``parent_type``, it creates child nodes for each entry in
    ``children`` and connects them via dependency edges.
    """

    parent_type: str
    children: list[tuple[str, str]]  # [(child_type, child_label), ...]
    edge_type: str = "requires"


@dataclass(frozen=True)
class GrowingGraphTemplate:
    """Defines a planning / construction problem.

    ``initial_goal_type``
        The type of the root goal node.

    ``expansion_rules``
        Rules dictating how each node type expands.

    ``context``
        Arbitrary metadata carried through execution.
    """

    concept_id: str
    initial_goal_type: str = "root"
    expansion_rules: list[ExpansionRule] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
