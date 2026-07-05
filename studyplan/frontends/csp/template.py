"""CSP problem definition — variables, domains, constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CspVariable:
    """One variable in the constraint satisfaction problem."""

    id: str
    domain: frozenset[Any]


@dataclass(frozen=True)
class CspConstraint:
    """A constraint restricting variable assignments.

    ``type`` is one of the following strings, each with specific semantics
    for ``variables`` and ``params``:

    ``"all_different"``
        All listed variables must receive distinct values.
        ``variables`` (list[str]): variables to enforce distinctness on.
        ``params``: ignored.

    ``"binary_not_equal"``
        Two variables must have different values.
        ``variables[0]``, ``variables[1]``: the two variables.
        ``params``: ignored.

    ``"unary_allowed"``
        A single variable's value must belong to a fixed set.
        ``variables[0]``: the variable.
        ``params["allowed"]``: ``frozenset`` of permissible values.
    """

    type: str
    variables: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CspTemplate:
    """Defines a constraint satisfaction problem: variables + constraints."""

    concept_id: str
    variables: list[CspVariable] = field(default_factory=list)
    constraints: list[CspConstraint] = field(default_factory=list)
