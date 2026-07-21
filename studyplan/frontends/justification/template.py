"""Justification Algebra problem definition — beliefs and justifications."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JustificationBelief:
    """One propositional belief in the justification network.

    A **premise** (``is_premise=True``) is always active — it needs no
    justification.  A **derived** belief is active only when at least
    one valid justification exists.
    """

    id: str
    label: str
    is_premise: bool = False


@dataclass(frozen=True)
class Justification:
    """A justification rule: *consequent* is supported iff conditions are met.

    A justification is **valid** when::

        all(in_supporters are ACTIVE) AND all(out_supporters are INACTIVE)
    """

    consequent: str
    in_supporters: list[str] = field(default_factory=list)
    out_supporters: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class JustificationTemplate:
    """Defines the initial belief set and justification network."""

    concept_id: str
    initial_beliefs: list[JustificationBelief] = field(default_factory=list)
    initial_justifications: list[Justification] = field(default_factory=list)
