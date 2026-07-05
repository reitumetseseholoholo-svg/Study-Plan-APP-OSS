"""JustificationExecutor — belief support and revision via justification networks.

State machine (each ``step()`` is one atomic operation)::

    evaluate → retract → evaluate → stabilise → commit
       ↓          ↑        ↓
    (quiescent) (inject) (cascade)

During **evaluate** a single justification is re-evaluated.
If its validity changed, the consequent's status is updated,
which may trigger further justifications to re-evaluate.

During **retract** a non-premise belief is deactivated,
which may trigger a cascade of status changes through
justifications that referenced it.

Beliefs persist as long as **any** valid justification exists.

Invariants of this algebra
━━━━━━━━━━━━━━━━━━━━━━━━━━

    I1  Every premise is always active (inviolable).
    I2  Every active belief has at least one valid justification.
    I3  Every inactive belief has no valid justification.
    I4  Justifications form a directed acyclic graph (template invariant).
    I5  Activation flows forward through the justification network.

Conserved quantity
━━━━━━━━━━━━━━━━

    Every active belief has at least one valid justification.
    This is never violated during execution.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from studyplan.cci.executor import CognitiveExecutor, Transition
from studyplan.frontends.justification.template import JustificationTemplate


def _tr(action: str, rationale: str | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return asdict(Transition(action=action, rationale=rationale, evidence=evidence or {}))


class JustificationExecutor(CognitiveExecutor):
    """Justification-based belief revision.

    Each call to ``step()`` processes exactly one atomic operation:
    evaluate one justification, retract one belief, or commit.
    """

    def __init__(self, template: JustificationTemplate) -> None:
        self._template = template

    @property
    def concept_id(self) -> str:
        return self._template.concept_id

    # -----------------------------------------------------------------
    # Justification validity
    # -----------------------------------------------------------------

    @staticmethod
    def _just_valid(j: dict, nodes: dict[str, dict]) -> bool:
        """Return True if *j* is valid given current node statuses."""
        for sid in j["in_supporters"]:
            s = nodes.get(sid)
            if s is None or s["status"] != "ACTIVE":
                return False
        for sid in j["out_supporters"]:
            s = nodes.get(sid)
            if s is None or s["status"] != "INACTIVE":
                return False
        return True

    # -----------------------------------------------------------------
    # Network helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _justs_referencing(belief_id: str, justifications: list[dict]) -> list[str]:
        """Return justification IDs that reference *belief_id* as a supporter."""
        affected: list[str] = []
        for j in justifications:
            if belief_id in j["in_supporters"] or belief_id in j["out_supporters"]:
                affected.append(j["id"])
        return affected

    @staticmethod
    def _has_valid_just(belief_id: str, nodes: dict[str, dict], justifications: list[dict]) -> bool:
        """Return True if at least one justification for *belief_id* is valid."""
        if nodes.get(belief_id, {}).get("is_premise"):
            return True
        for j in justifications:
            if j["consequent"] == belief_id:
                ins = j["in_supporters"]
                outs = j["out_supporters"]
                if all(nodes.get(s, {}).get("status") == "ACTIVE" for s in ins) and all(
                    nodes.get(s, {}).get("status") == "INACTIVE" for s in outs
                ):
                    return True
        return False

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        nodes: dict[str, dict] = {}
        for b in self._template.initial_beliefs:
            nodes[b.id] = {
                "label": b.label,
                "status": "ACTIVE" if b.is_premise else "UNKNOWN",
                "is_premise": b.is_premise,
            }

        justifications: list[dict] = []
        for i, j in enumerate(self._template.initial_justifications):
            justifications.append(
                {
                    "id": f"j{i}",
                    "consequent": j.consequent,
                    "in_supporters": list(j.in_supporters),
                    "out_supporters": list(j.out_supporters),
                }
            )

        # Initial queue: justifications whose consequent is UNKNOWN
        pending: list[str] = []
        for jf in justifications:
            cons = jf["consequent"]
            if nodes.get(cons, {}).get("status") == "UNKNOWN":
                pending.append(jf["id"])

        retractions = inputs.get("retract", [])
        if isinstance(retractions, str):
            retractions = [retractions]

        return {
            "nodes": nodes,
            "justifications": justifications,
            "pending_queue": pending,
            "retractions": list(retractions),
            "phase": "evaluate",
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["done"]:
            return {"next_state": state}

        phase = state["phase"]
        if phase == "evaluate":
            return self._step_evaluate(state)
        if phase == "retract":
            return self._step_retract(state)
        if phase == "stabilise":
            return self._step_stabilise(state)
        if phase == "commit":
            return self._step_commit(state)

        return {"next_state": state}

    # ── Phase: evaluate ──────────────────────────────────────────────

    def _step_evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        queue = state["pending_queue"]
        if not queue:
            return self._quiescent_transition(state)

        jid = queue.pop(0)
        j = self._find_just(state, jid)
        if j is None:
            return {"next_state": state}

        return self._eval_one_just(state, j, queue)

    def _quiescent_transition(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["retractions"]:
            state["phase"] = "retract"
            evidence = {
                "active_count": sum(1 for n in state["nodes"].values() if n["status"] == "ACTIVE"),
                "inactive_count": sum(1 for n in state["nodes"].values() if n["status"] == "INACTIVE"),
            }
        else:
            state["phase"] = "stabilise"
            evidence = {
                "active_count": sum(1 for n in state["nodes"].values() if n["status"] == "ACTIVE"),
            }
        return {
            "next_state": state,
            "transition": _tr(
                action="evaluation_quiescent",
                rationale="All justifications evaluated — network is stable",
                evidence=evidence,
            ),
        }

    @staticmethod
    def _find_just(state: dict[str, Any], jid: str) -> dict | None:
        for cand in state["justifications"]:
            if cand["id"] == jid:
                return cand
        return None

    def _eval_one_just(self, state: dict[str, Any], j: dict, queue: list[str]) -> dict[str, Any]:
        cons = j["consequent"]
        was_active = state["nodes"].get(cons, {}).get("status") == "ACTIVE"
        is_valid = self._just_valid(j, state["nodes"])

        if is_valid and not was_active:
            return self._support_belief(state, j, cons, queue)
        if not is_valid and was_active:
            return self._unsupport_belief(state, j, cons, queue)

        return {
            "next_state": state,
            "transition": _tr(
                action="check_justification",
                rationale=(f"Justification {j['id']} evaluated (valid={is_valid}) — no change"),
                evidence={
                    "justification_id": j["id"],
                    "valid": is_valid,
                    "consequent": cons,
                },
            ),
        }

    def _support_belief(self, state: dict[str, Any], j: dict, cons: str, queue: list[str]) -> dict[str, Any]:
        state["nodes"][cons]["status"] = "ACTIVE"
        deps = self._justs_referencing(cons, state["justifications"])
        for d in deps:
            if d not in queue:
                queue.append(d)
        return {
            "next_state": state,
            "transition": _tr(
                action="belief_derived",
                rationale=(f"'{state['nodes'][cons]['label']}' became ACTIVE via justification {j['id']}"),
                evidence={
                    "belief_id": cons,
                    "justification_id": j["id"],
                    "in_supporters": list(j["in_supporters"]),
                },
            ),
        }

    def _unsupport_belief(self, state: dict[str, Any], j: dict, cons: str, queue: list[str]) -> dict[str, Any]:
        still_has = self._has_valid_just(cons, state["nodes"], state["justifications"])
        if still_has:
            return {
                "next_state": state,
                "transition": _tr(
                    action="check_justification",
                    rationale=(f"Justification {j['id']} invalid but '{cons}' has alternative support"),
                    evidence={
                        "justification_id": j["id"],
                        "valid": False,
                        "consequent": cons,
                    },
                ),
            }
        state["nodes"][cons]["status"] = "INACTIVE"
        deps = self._justs_referencing(cons, state["justifications"])
        for d in deps:
            if d not in queue:
                queue.append(d)
        return {
            "next_state": state,
            "transition": _tr(
                action="belief_lost",
                rationale=(f"'{state['nodes'][cons]['label']}' became INACTIVE — all justifications lost"),
                evidence={
                    "belief_id": cons,
                    "justification_id": j["id"],
                },
            ),
        }

    # ── Phase: retract ───────────────────────────────────────────────

    def _step_retract(self, state: dict[str, Any]) -> dict[str, Any]:
        retractions = state["retractions"]
        if not retractions:
            state["phase"] = "evaluate"
            return {"next_state": state}

        bid = retractions.pop(0)
        node = state["nodes"].get(bid)
        if node is None or node.get("is_premise"):
            return {
                "next_state": state,
                "transition": _tr(
                    action="retract_skipped",
                    rationale=f"Cannot retract '{bid}' — not found or premise",
                    evidence={"belief_id": bid},
                ),
            }

        node["status"] = "INACTIVE"

        affected = self._justs_referencing(bid, state["justifications"])
        for jid in affected:
            if jid not in state["pending_queue"]:
                state["pending_queue"].append(jid)

        state["phase"] = "evaluate"

        return {
            "next_state": state,
            "transition": _tr(
                action="belief_retracted",
                rationale=(f"Retracted '{node['label']}' ({bid}) — {len(affected)} justifications affected"),
                evidence={
                    "belief_id": bid,
                    "label": node["label"],
                    "affected_justifications": len(affected),
                },
            ),
        }

    # ── Phase: stabilise ─────────────────────────────────────────────

    def _step_stabilise(self, state: dict[str, Any]) -> dict[str, Any]:
        active_count = sum(1 for n in state["nodes"].values() if n["status"] == "ACTIVE")
        inactive_count = sum(1 for n in state["nodes"].values() if n["status"] == "INACTIVE")
        unknown_count = sum(1 for n in state["nodes"].values() if n["status"] == "UNKNOWN")

        state["phase"] = "commit"
        return {
            "next_state": state,
            "transition": _tr(
                action="belief_network_stable",
                rationale=(
                    f"Network stabilised: {active_count} active, {inactive_count} inactive, {unknown_count} unknown"
                ),
                evidence={
                    "active_count": active_count,
                    "inactive_count": inactive_count,
                    "unknown_count": unknown_count,
                },
            ),
        }

    # ── Phase: commit ────────────────────────────────────────────────

    def _step_commit(self, state: dict[str, Any]) -> dict[str, Any]:
        belief_set = {bid: nd["status"] for bid, nd in state["nodes"].items()}
        active_count = sum(1 for s in belief_set.values() if s == "ACTIVE")
        inactive_count = sum(1 for s in belief_set.values() if s == "INACTIVE")
        state["done"] = True
        state["result"] = {
            "label": f"justification_set:{active_count}A/{inactive_count}I",
            "belief_set": belief_set,
            "active_count": active_count,
            "inactive_count": inactive_count,
            "is_nan": False,
        }
        return {
            "next_state": state,
            "transition": _tr(
                action="commit_belief_set",
                rationale=(f"Justification algebra committed ({active_count} active, {inactive_count} inactive)"),
                evidence={
                    "active_count": active_count,
                    "inactive_count": inactive_count,
                },
            ),
        }

    # ── finished / result ────────────────────────────────────────────

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("done"):
            return None
        return dict(state.get("result", {}))
