"""Growing graph executor — graph expansion topology.

State machine (each ``step()`` is one atomic transition)::

    activate → expand_or_complete → descend → activate → …
                                  ↘
                                    ascend → activate → …
                                         ↘
                                           commit → done

Four phases:

``activate``
    Mark the focus node as active.  Look up its expansion rule.

``expand_or_complete``
    If a rule exists, create child nodes (graph grows).  Otherwise
    mark the node as satisfied (leaf).

``descend``
    Pick the next pending child as the new focus.

``ascend``
    Return focus to the parent.  Check whether sibling or parent
    can transition.

``commit``
    Root goal satisfied — extract solution.

Invariants of this algebra
━━━━━━━━━━━━━━━━━━━━━━━━━━

    I1  The graph is always a rooted tree (no cycles, no multi-parent).
    I2  Every node is reachable from the root via parent edges.
    I3  A node is satisfied only when all its children are satisfied.
    I4  Nodes appear only during ``expand_or_complete`` transitions.
    I5  The graph is finite — expansion terminates.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from studyplan.cci.executor import CognitiveExecutor, Transition
from studyplan.frontends.growing_graph.template import GrowingGraphTemplate


def _tr(action: str, rationale: str | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return asdict(Transition(action=action, rationale=rationale, evidence=evidence or {}))


_NEXT_ID = 0


def _fresh_id(prefix: str = "n") -> str:
    global _NEXT_ID
    _NEXT_ID += 1
    return f"{prefix}{_NEXT_ID}"


class GrowingGraphExecutor(CognitiveExecutor):
    """Depth-first expansion of a goal tree.

    Each call to ``step()`` advances the graph by exactly one atomic
    operation (activate a node, expand a node, descend to a child,
    ascend to a parent, or commit).
    """

    def __init__(self, template: GrowingGraphTemplate) -> None:
        self._template = template

    @property
    def concept_id(self) -> str:
        return self._template.concept_id

    # -----------------------------------------------------------------
    # Expansion rule lookup
    # -----------------------------------------------------------------

    def _rule_for(self, node_type: str) -> list[tuple[str, str]] | None:
        """Return child definitions for *node_type*, or None if leaf."""
        for rule in self._template.expansion_rules:
            if rule.parent_type == node_type:
                return list(rule.children)
        return None

    # -----------------------------------------------------------------
    # Child status helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _child_status(node: dict, nodes: dict[str, dict]) -> str:
        """Return the aggregate status of *node*'s children: satisfied, pending, failed."""
        child_ids = node.get("children", [])
        if not child_ids:
            return "leaf"
        statuses = [nodes[cid]["status"] for cid in child_ids]
        if all(s == "satisfied" for s in statuses):
            return "satisfied"
        if any(s == "failed" for s in statuses):
            return "failed"
        return "pending"

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        root_id = _fresh_id("g")
        root_node = {
            "id": root_id,
            "type": self._template.initial_goal_type,
            "label": self._template.initial_goal_type,
            "status": "pending",
            "children": [],
            "parent": None,
        }
        return {
            "nodes": {root_id: root_node},
            "focus": root_id,
            "phase": "activate",
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["done"]:
            return {"next_state": state}

        phase = state["phase"]
        if phase == "activate":
            return self._step_activate(state)
        if phase == "expand_or_complete":
            return self._step_expand_or_complete(state)
        if phase == "descend":
            return self._step_descend(state)
        if phase == "ascend":
            return self._step_ascend(state)
        if phase == "commit":
            return self._step_commit(state)

        return {"next_state": state}

    # ── Phase: activate ────────────────────────────────────────────────

    def _step_activate(self, state: dict[str, Any]) -> dict[str, Any]:
        fid = state["focus"]
        node = state["nodes"][fid]

        if node["status"] == "pending":
            node["status"] = "active"

        state["phase"] = "expand_or_complete"
        return {
            "next_state": state,
            "transition": _tr(
                action="activate_goal",
                rationale=f"Activated '{node['label']}' ({node['type']})",
                evidence={"node_id": fid, "node_type": node["type"]},
            ),
        }

    # ── Phase: expand_or_complete ──────────────────────────────────────

    def _step_expand_or_complete(self, state: dict[str, Any]) -> dict[str, Any]:
        fid = state["focus"]
        node = state["nodes"][fid]
        children = self._rule_for(node["type"])

        if children is not None:
            # Expand: create child nodes
            created: list[str] = []
            for child_type, child_label in children:
                cid = _fresh_id("n")
                state["nodes"][cid] = {
                    "id": cid,
                    "type": child_type,
                    "label": child_label,
                    "status": "pending",
                    "children": [],
                    "parent": fid,
                }
                node["children"].append(cid)
                created.append(cid)

            state["phase"] = "descend"
            return {
                "next_state": state,
                "transition": _tr(
                    action="expand_goal",
                    rationale=f"Expanded '{node['label']}' → {len(created)} subtasks",
                    evidence={
                        "node_id": fid,
                        "children_created": len(created),
                        "child_ids": created,
                    },
                ),
            }

        # Leaf: mark as satisfied
        node["status"] = "satisfied"
        state["phase"] = "ascend"
        return {
            "next_state": state,
            "transition": _tr(
                action="complete_leaf",
                rationale=f"Leaf '{node['label']}' completed",
                evidence={"node_id": fid},
            ),
        }

    # ── Phase: descend ─────────────────────────────────────────────────

    def _step_descend(self, state: dict[str, Any]) -> dict[str, Any]:
        fid = state["focus"]
        node = state["nodes"][fid]

        for cid in node.get("children", []):
            child = state["nodes"].get(cid)
            if child and child["status"] == "pending":
                state["focus"] = cid
                state["phase"] = "activate"
                return {
                    "next_state": state,
                    "transition": _tr(
                        action="descend",
                        rationale=f"Descend to '{child['label']}'",
                        evidence={"parent_id": fid, "child_id": cid},
                    ),
                }

        # No pending children — ascend
        state["phase"] = "ascend"
        return {
            "next_state": state,
            "transition": _tr(
                action="no_pending_child",
                rationale=f"No pending children for '{node['label']}'",
                evidence={"node_id": fid},
            ),
        }

    # ── Phase: ascend ─────────────────────────────────────────────────

    def _step_ascend(self, state: dict[str, Any]) -> dict[str, Any]:
        fid = state["focus"]
        node = state["nodes"][fid]
        parent_id = node.get("parent")

        cstatus = self._child_status(node, state["nodes"])

        if cstatus == "satisfied" or cstatus == "leaf":
            node["status"] = "satisfied"
        elif cstatus == "failed":
            node["status"] = "failed"
        else:
            pass

        if parent_id is None:
            if node["status"] == "satisfied":
                state["phase"] = "commit"
                return {
                    "next_state": state,
                    "transition": _tr(
                        action="root_satisfied",
                        rationale="Root goal satisfied",
                        evidence={"root_id": fid},
                    ),
                }
            state["done"] = True
            state["result"] = {"solved": False, "nodes": len(state["nodes"])}
            return {
                "next_state": state,
                "transition": _tr(
                    action="search_exhausted",
                    rationale="Root goal could not be satisfied",
                    evidence={"root_id": fid},
                ),
            }

        state["focus"] = parent_id

        # Check if parent has other pending children to descend into
        parent = state["nodes"][parent_id]
        pending = [cid for cid in parent.get("children", []) if state["nodes"].get(cid, {}).get("status") == "pending"]
        if pending:
            state["phase"] = "descend"
            return {
                "next_state": state,
                "transition": _tr(
                    action="sibling_pending",
                    rationale=f"{len(pending)} sibling(s) pending under parent",
                    evidence={
                        "child_id": fid,
                        "parent_id": parent_id,
                        "pending_siblings": len(pending),
                    },
                ),
            }

        state["phase"] = "ascend"
        return {
            "next_state": state,
            "transition": _tr(
                action="ascend",
                rationale=f"Return to parent of '{node['label']}' (status={cstatus})",
                evidence={
                    "child_id": fid,
                    "parent_id": parent_id,
                    "child_status": cstatus,
                },
            ),
        }

    # ── Phase: commit ──────────────────────────────────────────────────

    def _step_commit(self, state: dict[str, Any]) -> dict[str, Any]:
        solution = {
            nid: {
                "label": nd["label"],
                "type": nd["type"],
                "status": nd["status"],
            }
            for nid, nd in state["nodes"].items()
            if nd["status"] == "satisfied"
        }
        state["done"] = True
        state["result"] = {
            "solution": solution,
            "node_count": len(state["nodes"]),
            "solved": True,
            "is_nan": False,
        }
        return {
            "next_state": state,
            "transition": _tr(
                action="commit_plan",
                rationale=f"Plan committed ({len(solution)} satisfied nodes)",
                evidence={"satisfied_count": len(solution)},
            ),
        }

    # ── finished / result ──────────────────────────────────────────────

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("done"):
            return None
        return dict(state.get("result", {}))
