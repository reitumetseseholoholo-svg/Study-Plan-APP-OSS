"""CSP executor — structural mutation topology.

State machine (each ``step()`` is one atomic transition)::

    select_variable
         │
         ▼
    assign_value
         │
         ▼
    propagate ──→ (domain wipeout?) ──→ backtrack
         │                                  │
         │ (no wipeout)                     │
         ▼                                  │
    (all assigned?) ──→ commit_solution     │
         │                                  │
         │ (not all)                        │
         └──── back to select ──────────────┘

Invariants of this algebra
━━━━━━━━━━━━━━━━━━━━━━━━━━

    I1  Every assigned value satisfies all constraints.
    I2  Every unassigned variable has a non-empty domain (otherwise the
        executor backtracks before yielding control).
    I3  The assignment stack is a complete history of (variable, value,
        domains-snapshot) triples — replayable for undo.
    I4  No value is tried twice for the same variable during a
        continuous search path.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from studyplan.cci.executor import CognitiveExecutor, Transition
from studyplan.frontends.csp.template import CspConstraint, CspTemplate


def _tr(action: str, rationale: str | None = None, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return asdict(Transition(action=action, rationale=rationale, evidence=evidence or {}))


def _domain_frozenset(domain: Any) -> frozenset:
    if isinstance(domain, frozenset):
        return domain
    return frozenset(domain)


class CspExecutor(CognitiveExecutor):
    """Chronological backtracking search over a CSP.

    Each call to ``step()`` advances the search by exactly one atomic
    operation.  The search is deterministic given fixed heuristics
    (MRV for variable selection, LCV for value selection).
    """

    def __init__(self, template: CspTemplate) -> None:
        self._template = template

    @property
    def concept_id(self) -> str:
        return self._template.concept_id

    # -----------------------------------------------------------------
    # Heuristics
    # -----------------------------------------------------------------

    @staticmethod
    def _mrv_select(unassigned: dict[str, dict], failed: dict[str, set]) -> str | None:
        """Minimum Remaining Values — pick the variable with smallest domain."""
        best = None
        best_size = 10**9
        for vid, vdata in unassigned.items():
            remaining = [v for v in vdata["domain"] if v not in failed.get(vid, set())]
            if not remaining:
                return vid  # dead end — this variable must be backtracked
            if len(remaining) < best_size:
                best_size = len(remaining)
                best = vid
        return best

    @staticmethod
    def _lcv_select(
        vid: str, domain: frozenset, constraints: list[CspConstraint], variables: dict[str, dict]
    ) -> list[Any]:
        """Least Constraining Value — order values by how few options they remove."""
        scores: list[tuple[int, Any]] = []
        for val in domain:
            removed = 0
            for con in constraints:
                if vid not in con.variables:
                    continue
                other_ids = [v for v in con.variables if v != vid]
                for oid in other_ids:
                    if oid not in variables or variables[oid]["value"] is not None:
                        continue
                    for oval in variables[oid]["domain"]:
                        if not CspExecutor._check_constraint(con, {vid: val, oid: oval}, variables):
                            removed += 1
            scores.append((removed, val))
        scores.sort()
        return [v for _, v in scores]

    # -----------------------------------------------------------------
    # Constraint checking
    # -----------------------------------------------------------------

    @staticmethod
    def _check_constraint(con: CspConstraint, assignments: dict[str, Any], variables: dict[str, dict]) -> bool:
        """Return True if *con* is satisfied by the partial *assignments*."""
        if con.type == "all_different":
            vals = [assignments.get(v) for v in con.variables if v in assignments]
            vals = [v for v in vals if v is not None]
            return len(vals) == len(set(vals))

        if con.type == "binary_not_equal":
            a = assignments.get(con.variables[0])
            b = assignments.get(con.variables[1])
            if a is None or b is None:
                return True
            return a != b

        if con.type == "unary_allowed":
            v = assignments.get(con.variables[0])
            if v is None:
                return True
            allowed = _domain_frozenset(con.params.get("allowed", frozenset()))
            return v in allowed

        return True  # unknown constraint type — ignore

    @staticmethod
    def _propagate(
        vid: str, value: Any, variables: dict[str, dict], constraints: list[CspConstraint]
    ) -> dict[str, frozenset]:
        """Forward-check: reduce domains of unassigned vars connected to *vid*.

        Returns a dict of ``{var_id: new_domain}`` for domains that changed,
        or an empty dict if no changes.  If any domain becomes empty, the
        result includes that var with an empty frozenset.
        """
        changes: dict[str, frozenset] = {}
        for con in constraints:
            if vid not in con.variables:
                continue
            other_ids = [v for v in con.variables if v != vid]
            for oid in other_ids:
                odata = variables.get(oid)
                if odata is None or odata["value"] is not None:
                    continue
                reduced = set()
                for oval in odata["domain"]:
                    trial = {vid: value, oid: oval}
                    if CspExecutor._check_constraint(con, trial, variables):
                        reduced.add(oval)
                old = odata["domain"]
                new_dom = frozenset(reduced)
                if new_dom != old:
                    changes[oid] = new_dom
        return changes

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def initialize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        variables: dict[str, dict] = {}
        for v in self._template.variables:
            variables[v.id] = {
                "domain": _domain_frozenset(v.domain),
                "value": None,
            }

        constraints = list(self._template.constraints)

        return {
            "phase": "select",
            "variables": variables,
            "constraints": constraints,
            "assignment_stack": [],
            "failed_values": {},
            "solution": None,
            "done": False,
            "result": None,
        }

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["done"]:
            return {"next_state": state}

        unassigned = {vid: vd for vid, vd in state["variables"].items() if vd["value"] is None}

        phase = state["phase"]
        if phase == "select":
            return self._step_select(state, unassigned)
        if phase == "assign":
            return self._step_assign(state)
        if phase == "propagate":
            return self._step_propagate(state)
        if phase == "backtrack":
            return self._step_backtrack(state)
        if phase == "commit":
            return self._step_commit(state)

        return {"next_state": state}

    # ── Phase helpers ──────────────────────────────────────────────────

    def _step_select(self, state: dict[str, Any], unassigned: dict[str, dict]) -> dict[str, Any]:
        if not unassigned:
            state["phase"] = "commit"
            state["solution"] = {vid: vd["value"] for vid, vd in state["variables"].items()}
            return {
                "next_state": state,
                "transition": _tr(
                    action="all_vars_assigned",
                    rationale="No unassigned variables remain",
                    evidence={"assigned_count": len(state["variables"])},
                ),
            }

        vid = self._mrv_select(unassigned, state["failed_values"])
        if vid is None:
            state["done"] = True
            return {
                "next_state": state,
                "transition": _tr(
                    action="search_exhausted",
                    rationale="No remaining viable variables",
                    evidence={},
                ),
            }

        state["_selected_var"] = vid
        state["phase"] = "assign"

        return {
            "next_state": state,
            "transition": _tr(
                action="select_variable",
                rationale=f"Selected '{vid}' (domain size={len(unassigned[vid]['domain'])})",
                evidence={
                    "variable": vid,
                    "domain_size": len(unassigned[vid]["domain"]),
                },
            ),
        }

    def _step_assign(self, state: dict[str, Any]) -> dict[str, Any]:
        vid = state.get("_selected_var")
        if not vid:
            state["done"] = True
            return {"next_state": state}

        vdata = state["variables"][vid]
        domain = vdata["domain"]
        failed = state["failed_values"].get(vid, set())

        remaining = [v for v in domain if v not in failed]
        if not remaining:
            state["_failed_var"] = vid
            state["phase"] = "backtrack"
            return {
                "next_state": state,
                "transition": _tr(
                    action="no_values_remaining",
                    rationale=f"No untried values for '{vid}'",
                    evidence={"variable": vid, "tried": list(failed)},
                ),
            }

        ordered = self._lcv_select(vid, frozenset(remaining), state["constraints"], state["variables"])
        val = ordered[0]

        snapshot = {oid: odata["domain"] for oid, odata in state["variables"].items() if odata["value"] is None}
        vdata["value"] = val
        state["assignment_stack"].append((vid, val, snapshot))
        state["phase"] = "propagate"

        return {
            "next_state": state,
            "transition": _tr(
                action="assign_value",
                rationale=f"Assigned '{vid}' = {val!r}",
                evidence={
                    "variable": vid,
                    "value": val,
                    "stack_depth": len(state["assignment_stack"]),
                },
            ),
        }

    def _step_propagate(self, state: dict[str, Any]) -> dict[str, Any]:
        vid = state.get("_selected_var")
        if not vid:
            state["done"] = True
            return {"next_state": state}

        val = state["variables"][vid]["value"]
        changes = self._propagate(vid, val, state["variables"], state["constraints"])

        wiped_var: str | None = None
        changed_list: list[str] = []
        for oid, new_dom in changes.items():
            if not new_dom:
                wiped_var = oid
            state["variables"][oid]["domain"] = new_dom
            changed_list.append(oid)

        if wiped_var is not None:
            state["_failed_var"] = wiped_var
            state["_wipeout_cause"] = (vid, val)
            state["phase"] = "backtrack"
            return {
                "next_state": state,
                "transition": _tr(
                    action="domain_wipeout",
                    rationale=f"'{vid}'={val!r} wiped domain of '{wiped_var}'",
                    evidence={
                        "cause_variable": vid,
                        "cause_value": val,
                        "wiped_variable": wiped_var,
                    },
                ),
            }

        state["phase"] = "select"
        return {
            "next_state": state,
            "transition": _tr(
                action="propagate",
                rationale=f"Reduced domains: {len(changes)} variables affected",
                evidence={
                    "affected_variables": changed_list,
                    "reduction_count": len(changes),
                },
            ),
        }

    def _step_backtrack(self, state: dict[str, Any]) -> dict[str, Any]:
        if not state["assignment_stack"]:
            state["done"] = True
            return {
                "next_state": state,
                "transition": _tr(
                    action="search_exhausted",
                    rationale="Backtrack stack empty — no solution exists",
                    evidence={},
                ),
            }

        undone_var, undone_val, snapshot = state["assignment_stack"].pop()

        for oid, domain in snapshot.items():
            if oid in state["variables"]:
                state["variables"][oid]["domain"] = domain

        failed = state["failed_values"].setdefault(undone_var, set())
        failed.add(undone_val)

        if undone_var in state["variables"]:
            state["variables"][undone_var]["value"] = None

        fv = state.pop("_failed_var", None)
        if fv and fv != undone_var:
            state["failed_values"].setdefault(fv, set())

        state["_selected_var"] = undone_var
        state["phase"] = "assign"

        return {
            "next_state": state,
            "transition": _tr(
                action="backtrack",
                rationale=f"Undid '{undone_var}'={undone_val!r} (stack depth={len(state['assignment_stack'])})",
                evidence={
                    "undone_variable": undone_var,
                    "undone_value": undone_val,
                    "stack_depth": len(state["assignment_stack"]),
                },
            ),
        }

    def _step_commit(self, state: dict[str, Any]) -> dict[str, Any]:
        solution = state.get("solution", {})
        state["done"] = True
        state["result"] = {
            "solution": solution,
            "assigned_count": len(solution),
        }
        return {
            "next_state": state,
            "transition": _tr(
                action="commit_solution",
                rationale=f"Solution found ({len(solution)} assignments)",
                evidence={"solution": solution},
            ),
        }

    def finished(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))

    def result(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state.get("done"):
            return None
        if state.get("solution"):
            return {
                "concept_id": self._template.concept_id,
                "result": state["solution"],
                "solved": True,
                "backtracks": sum(1 for _ in state.get("assignment_stack", [])),
                "is_nan": False,
            }
        return {
            "concept_id": self._template.concept_id,
            "result": None,
            "solved": False,
            "backtracks": sum(1 for _ in state.get("assignment_stack", [])),
            "is_nan": True,
        }
