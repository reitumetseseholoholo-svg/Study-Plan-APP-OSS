"""Justification Algebra topology tests — support network invariants.

Tests specific to algebra 6 (Justification Algebra):

    I1  Every premise is always active (inviolable).
    I2  Every active belief has at least one valid justification.
    I3  Every inactive belief has no valid justification.
    I4  Retraction propagates forward through the support network.
    I5  A node with multiple justifications is active if *any* is valid.
    I6  Out-supporters enable non-monotonic reasoning.
    I7  Premises reject retraction attempts.
"""

from __future__ import annotations

from studyplan.cci import CognitiveRuntime
from studyplan.frontends.justification import (
    JustificationBelief,
    Justification,
    JustificationExecutor,
    JustificationTemplate,
)


def _runtime() -> CognitiveRuntime:
    return CognitiveRuntime()


def _get_beliefs(state: dict) -> dict[str, str]:
    return {bid: nd["status"] for bid, nd in state["nodes"].items()}


# =========================================================================
# I2, I3 — Chain propagation (I1: premises are always IN)
# =========================================================================


def test_tms_chain_propagation() -> None:
    """A premise → B → C: all derived nodes become IN via valid justifications."""
    template = JustificationTemplate(
        "test.chain",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
            JustificationBelief(id="C", label="Derived C"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["A"]),
            Justification(consequent="C", in_supporters=["B"]),
        ],
    )
    executor = JustificationExecutor(template)
    trace = _runtime().execute(executor, {})
    result = trace.events[-1].payload.get("result")

    assert result is not None
    assert result["belief_set"]["A"] == "ACTIVE", "Premise A should be IN"
    assert result["belief_set"]["B"] == "ACTIVE", "Derived B should be IN"
    assert result["belief_set"]["C"] == "ACTIVE", "Derived C should be IN"
    assert result["active_count"] == 3


def test_tms_unjustified_node_stays_unknown() -> None:
    """A node with no valid justification stays UNKNOWN."""
    template = JustificationTemplate(
        "test.unknown",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise", is_premise=True),
            JustificationBelief(id="B", label="Orphan B"),
        ],
    )
    result = _runtime().execute(JustificationExecutor(template), {}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["A"] == "ACTIVE"
    assert result["belief_set"]["B"] == "UNKNOWN"


# =========================================================================
# I4 — Retraction cascade
# =========================================================================


def test_tms_retraction_cascade() -> None:
    """A → B → C → D: retracting B cascades to C and D."""
    template = JustificationTemplate(
        "test.cascade",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
            JustificationBelief(id="C", label="Derived C"),
            JustificationBelief(id="D", label="Derived D"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["A"]),
            Justification(consequent="C", in_supporters=["B"]),
            Justification(consequent="D", in_supporters=["C"]),
        ],
    )
    result = _runtime().execute(JustificationExecutor(template), {"retract": "B"}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["A"] == "ACTIVE", "Premise A stays IN"
    assert result["belief_set"]["B"] == "INACTIVE", "B was explicitly retracted"
    assert result["belief_set"]["C"] == "INACTIVE", "C lost its only justification"
    assert result["belief_set"]["D"] == "INACTIVE", "D lost its only justification"
    assert result["active_count"] == 1


# =========================================================================
# I5 — Multiple justifications (alternative support)
# =========================================================================


def test_tms_multiple_justifications() -> None:
    """C has both A and B as valid justifications; retracting one leaves C IN."""
    template = JustificationTemplate(
        "test.multi",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise A", is_premise=True),
            JustificationBelief(id="X", label="Premise X", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
            JustificationBelief(id="C", label="Derived C"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["X"]),
            Justification(consequent="C", in_supporters=["A"]),
            Justification(consequent="C", in_supporters=["B"]),
        ],
    )
    # C should be IN since both justifications are valid
    result = _runtime().execute(JustificationExecutor(template), {}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["C"] == "ACTIVE", "C should be IN with two valid justifications"

    # Retract B: C should stay IN because A's justification is still valid
    result2 = _runtime().execute(JustificationExecutor(template), {"retract": "B"}).events[-1].payload.get("result")
    assert result2 is not None
    assert result2["belief_set"]["C"] == "ACTIVE", "C should stay IN when one justification remains valid"
    assert result2["belief_set"]["B"] == "INACTIVE", "B was retracted"
    assert result2["active_count"] == 3  # A + X + C


def test_tms_alternative_justification_takes_over() -> None:
    """C has two justifications; when one fails the other takes over."""
    template = JustificationTemplate(
        "test.alternative",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise A", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
            JustificationBelief(id="C", label="Derived C"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["A"]),
            Justification(consequent="C", in_supporters=["B"]),
            Justification(consequent="C", in_supporters=["A"], out_supporters=["B"]),
        ],
    )
    # Initially: A IN, B IN, C IN via B → C. j2 (C ← A & not B) invalid because B IN.
    result = _runtime().execute(JustificationExecutor(template), {}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["C"] == "ACTIVE", "C is ACTIVE via B → C"

    # Retract B: C loses j0 (B OUT), but gains j2 (A IN, B OUT) → C stays IN
    result2 = _runtime().execute(JustificationExecutor(template), {"retract": "B"}).events[-1].payload.get("result")
    assert result2 is not None
    assert result2["belief_set"]["C"] == "ACTIVE", "C switches to alternative justification"
    assert result2["belief_set"]["B"] == "INACTIVE"
    assert result2["active_count"] == 2  # A + C


# =========================================================================
# I6 — Out-supporter (non-monotonic reasoning)
# =========================================================================


def test_tms_out_supporter() -> None:
    """C is IN when B is OUT (out-supporter condition)."""
    template = JustificationTemplate(
        "test.out",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise A", is_premise=True),
            JustificationBelief(id="X", label="Premise X", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
            JustificationBelief(id="C", label="Derived C"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["X"]),
            Justification(consequent="C", in_supporters=["A"], out_supporters=["B"]),
        ],
    )
    # B is IN (justified by X), so C's justification is invalid → C stays UNKNOWN
    result = _runtime().execute(JustificationExecutor(template), {}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["C"] in ("UNKNOWN", "INACTIVE"), (
        f"C should not be IN (B is IN), got {result['belief_set']['C']}"
    )

    # Retract B: C's justification becomes valid → C becomes IN
    result2 = _runtime().execute(JustificationExecutor(template), {"retract": "B"}).events[-1].payload.get("result")
    assert result2 is not None
    assert result2["belief_set"]["C"] == "ACTIVE", "C should become IN after B is retracted"
    assert result2["belief_set"]["B"] == "INACTIVE"


# =========================================================================
# I7 — Premises reject retraction
# =========================================================================


def test_tms_premise_protection() -> None:
    """Attempting to retract a premise leaves it IN."""
    template = JustificationTemplate(
        "test.premise",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise A", is_premise=True),
        ],
    )
    result = _runtime().execute(JustificationExecutor(template), {"retract": "A"}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["A"] == "ACTIVE", "Premise should remain IN after retraction attempt"


# =========================================================================
# I1 — Premise inviolability (always IN)
# =========================================================================


def test_tms_premise_always_in() -> None:
    """All premises are always IN across any operation."""
    template = JustificationTemplate(
        "test.premises",
        initial_beliefs=[
            JustificationBelief(id="X", label="Premise X", is_premise=True),
            JustificationBelief(id="Y", label="Premise Y", is_premise=True),
        ],
    )
    # No justifications, no operations — premises just exist
    result = _runtime().execute(JustificationExecutor(template), {}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["X"] == "ACTIVE"
    assert result["belief_set"]["Y"] == "ACTIVE"
    assert result["active_count"] == 2

    # Retraction attempts on a non-existent belief
    result2 = _runtime().execute(JustificationExecutor(template), {"retract": "X"}).events[-1].payload.get("result")
    assert result2 is not None
    assert result2["belief_set"]["X"] == "ACTIVE", "Premise X should stay IN"
    assert result2["belief_set"]["Y"] == "ACTIVE", "Premise Y should stay IN"
    assert result2["active_count"] == 2


# =========================================================================
# Step-level inspection — verify the cascade order
# =========================================================================


def test_tms_cascade_step_order() -> None:
    """Trace reflects the correct cascade order: propagate → retract → propagate."""
    template = JustificationTemplate(
        "test.order",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise", is_premise=True),
            JustificationBelief(id="B", label="Derived B"),
        ],
        initial_justifications=[
            Justification(consequent="B", in_supporters=["A"]),
        ],
    )
    trace = _runtime().execute(JustificationExecutor(template), {"retract": "B"})

    actions = []
    for ev in trace.events:
        if ev.type == "step":
            trans = ev.payload.get("transition", {})
            actions.append(trans.get("action", "?"))

    # Order: evaluate → retract → evaluate → quiescent → stabilise → commit
    assert "belief_derived" in actions, f"Expected initial derivation, got {actions}"
    assert "belief_retracted" in actions, f"Expected retraction, got {actions}"
    assert "evaluation_quiescent" in actions, f"Expected quiescent, got {actions}"
    assert "belief_network_stable" in actions, f"Expected stabilisation, got {actions}"
    assert "commit_belief_set" in actions, f"Expected commit, got {actions}"

    # retraction must come after initial propagation
    retract_idx = next(i for i, a in enumerate(actions) if a == "belief_retracted")
    derive_idx = next(i for i, a in enumerate(actions) if a == "belief_derived")
    assert retract_idx > derive_idx, f"Retraction ({retract_idx}) should come after derivation ({derive_idx})"


# =========================================================================
# Edge case: retract non-existent belief
# =========================================================================


def test_tms_retract_nonexistent() -> None:
    """Retracting a non-existent belief is silently ignored."""
    template = JustificationTemplate(
        "test.nonexist",
        initial_beliefs=[
            JustificationBelief(id="A", label="Premise", is_premise=True),
        ],
    )
    result = _runtime().execute(JustificationExecutor(template), {"retract": "ZOMBIE"}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"]["A"] == "ACTIVE"
    assert result["active_count"] == 1


# =========================================================================
# Edge case: no beliefs at all
# =========================================================================


def test_tms_empty_belief_set() -> None:
    """An empty belief set produces a valid empty result."""
    template = JustificationTemplate(
        "test.empty",
        initial_beliefs=[],
        initial_justifications=[],
    )
    result = _runtime().execute(JustificationExecutor(template), {}).events[-1].payload.get("result")
    assert result is not None
    assert result["belief_set"] == {}
    assert result["active_count"] == 0
    assert result["inactive_count"] == 0
    assert result["is_nan"] is False
