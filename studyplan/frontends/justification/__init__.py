"""Justification Algebra — belief support and revision via justification networks.

This algebra is the first that explicitly models **why** a belief is held,
not just what the belief is.  The state is a bipartite justification
network (evidence ↔ beliefs ↔ rules), and execution consists of support
changes propagating through the network.

Conserved quantity
━━━━━━━━━━━━━━━━

    Every active belief has at least one valid justification.

Mutation operators
━━━━━━━━━━━━━━━━

    support     — activate a belief via a valid justification
    retract     — remove support from a belief
    derive      — propagate activation through dependent justifications
    collapse    — deactivate a belief when all justifications are lost
    evaluate    — test whether a justification is currently valid

Reference topology
━━━━━━━━━━━━━━━━

Justification-based truth maintenance (Doyle 1979, Forbus & de Kleer 1993),
framed as a support algebra rather than a dependency graph.

A belief persists as long as **any** valid justification exists.
Multiple justifications provide alternative support — losing one
does not necessarily kill the belief.
"""

from studyplan.frontends.justification.template import JustificationBelief, Justification, JustificationTemplate
from studyplan.frontends.justification.executor import JustificationExecutor

__all__ = [
    "JustificationBelief",
    "Justification",
    "JustificationTemplate",
    "JustificationExecutor",
]
