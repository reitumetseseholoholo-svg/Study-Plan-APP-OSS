"""Constraint Satisfaction — structural mutation topology.

This module tests whether the CognitiveExecutor protocol survives an
algebra where the **structure of the state participates in computation**:

    * Domain propagation changes which values are reachable.
    * Backtracking unwinds parts of the state (non-monotonic).
    * The constraint graph evolves as variables become assigned.

Reference topology: constraint satisfaction / truth maintenance.
"""

from studyplan.frontends.csp.template import CspConstraint, CspTemplate, CspVariable
from studyplan.frontends.csp.executor import CspExecutor

__all__ = [
    "CspConstraint",
    "CspTemplate",
    "CspVariable",
    "CspExecutor",
]
