"""BFS executor — novel test structure for zero-shot algebra recognition.

Breadth-First Search over a static adjacency graph.  Each ``step()``
dequeues one node and enqueues its unvisited neighbours.

This is NOT a known algebra — it exists to test whether the observatory
can recognise ``Unknown`` or identify the *closest* known algebra.

State machine::

    dequeue → enqueue_neighbors → dequeue → … → commit

Phases:

``dequeue``
    Pop the next node from the frontier queue.  Mark as visited.

``enqueue_neighbors``
    Look up neighbours in the static adjacency list.  Enqueue any
    not yet visited.

``commit``
    Frontier empty — done.  Return visited order.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from studyplan.cci.executor import CognitiveExecutor, Transition


def _tr(
    action: str,
    rationale: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return asdict(Transition(action=action, rationale=rationale, evidence=evidence or {}))


class BfsExecutor(CognitiveExecutor):
    """Breadth-First Search over a static adjacency graph.

    The template is simply an adjacency dict ``{node: [neighbour, ...]}``
    and a start node.
    """

    def __init__(self, template: dict[str, Any]) -> None:
        self._template = template
        self._adjacency: dict[str, list[str]] = dict(template.get("adjacency", {}))
        self._start: str = template.get("start", "")

    @property
    def concept_id(self) -> str:
        return f"BFS({self._start})"

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "phase": "dequeue",
            "adjacency": dict(self._adjacency),
            "frontier": [self._start],
            "visited": [],
            "visited_set": {self._start},
            "current_node": None,
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["done"]:
            return {"next_state": state}

        phase = state["phase"]
        if phase == "dequeue":
            return self._step_dequeue(state)
        if phase == "enqueue_neighbors":
            return self._step_enqueue(state)
        if phase == "commit":
            return self._step_commit(state)
        return {"next_state": state}

    def _step_dequeue(self, state: dict[str, Any]) -> dict[str, Any]:
        frontier = state["frontier"]
        if not frontier:
            state["phase"] = "commit"
            return {
                "next_state": state,
                "transition": _tr(
                    action="frontier_exhausted",
                    rationale="No more nodes to explore",
                    evidence={"visited_count": len(state["visited"])},
                ),
            }

        node = frontier.pop(0)
        state["current_node"] = node
        state["visited"].append(node)
        state["phase"] = "enqueue_neighbors"

        return {
            "next_state": state,
            "transition": _tr(
                action="dequeue_node",
                rationale=f"Visiting '{node}'",
                evidence={
                    "node": node,
                    "visited_count": len(state["visited"]),
                    "frontier_size": len(frontier),
                },
            ),
        }

    def _step_enqueue(self, state: dict[str, Any]) -> dict[str, Any]:
        node = state["current_node"]
        if node is None:
            state["phase"] = "dequeue"
            return {"next_state": state}

        neighbours = state["adjacency"].get(node, [])
        visited_set = state["visited_set"]
        frontier = state["frontier"]
        enqueued: list[str] = []

        for neighbour in neighbours:
            if neighbour not in visited_set:
                visited_set.add(neighbour)
                frontier.append(neighbour)
                enqueued.append(neighbour)

        state["phase"] = "dequeue"

        return {
            "next_state": state,
            "transition": _tr(
                action="enqueue_neighbors",
                rationale=f"Enqueued {len(enqueued)} neighbour(s) of '{node}'",
                evidence={
                    "node": node,
                    "enqueued": enqueued,
                    "frontier_size": len(frontier),
                },
            ),
        }

    def _step_commit(self, state: dict[str, Any]) -> dict[str, Any]:
        state["done"] = True
        state["result"] = {
            "visited_order": list(state["visited"]),
            "node_count": len(state["visited"]),
        }
        return {
            "next_state": state,
            "transition": _tr(
                action="commit_bfs",
                rationale=f"BFS complete — visited {len(state['visited'])} nodes",
                evidence={
                    "visited_count": len(state["visited"]),
                    "visited_order": list(state["visited"]),
                },
            ),
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("done"):
            return None
        return dict(state.get("result", {}))
