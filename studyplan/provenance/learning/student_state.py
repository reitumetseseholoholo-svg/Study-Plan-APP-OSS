from __future__ import annotations

import math
from dataclasses import dataclass, field

from studyplan.provenance.learning.trace import FMAttemptTrace


@dataclass
class FMStudentState:
    concept_id: str
    formula_id: str

    mastery_mean: float = 0.5
    mastery_var: float = 0.083

    confidence: float = 0.5

    error_beliefs: dict[str, float] = field(default_factory=lambda: {"none": 1.0})

    dependency_beliefs: dict[str, tuple[float, float]] = field(default_factory=dict)

    last_trace: FMAttemptTrace | None = None

    def copy(self) -> FMStudentState:
        return FMStudentState(
            concept_id=self.concept_id,
            formula_id=self.formula_id,
            mastery_mean=self.mastery_mean,
            mastery_var=self.mastery_var,
            confidence=self.confidence,
            error_beliefs=dict(self.error_beliefs),
            dependency_beliefs=dict(self.dependency_beliefs),
            last_trace=self.last_trace,
        )


def compute_confidence(variance: float) -> float:
    if variance <= 0:
        return 1.0
    return 1.0 - math.sqrt(variance)


def bayesian_mean_update(
    prior_mean: float,
    prior_var: float,
    surprise: float,
    learning_rate: float = 0.3,
) -> tuple[float, float]:
    delta = learning_rate * surprise
    new_mean = prior_mean + delta
    new_mean = max(0.01, min(0.99, new_mean))
    new_var = prior_var * (1.0 - abs(delta))
    new_var = max(0.001, min(0.25, new_var))
    return new_mean, new_var


def beta_bernoulli_update(
    alpha: float,
    beta: float,
    correct: bool,
) -> tuple[float, float]:
    if correct:
        return alpha + 1.0, beta
    else:
        return alpha, beta + 1.0


def compute_surprise(
    mastery_mean: float,
    mastery_var: float,
    correct: bool,
) -> float:
    expected = mastery_mean
    actual = 1.0 if correct else 0.0
    dev = actual - expected
    if mastery_var < 0.001:
        return dev
    return dev / math.sqrt(mastery_var + 0.001)


def update_error_profile(
    error_beliefs: dict[str, float],
    error_label: str,
    decay: float = 0.95,
) -> dict[str, float]:
    updated: dict[str, float] = {}
    for k, v in error_beliefs.items():
        updated[k] = v * decay
    updated[error_label] = updated.get(error_label, 0.0) + (1.0 - decay)
    total = sum(updated.values())
    if total > 0:
        for k in updated:
            updated[k] = updated[k] / total
    return updated


def initial_state(
    concept_id: str,
    formula_id: str,
    dependency_ids: tuple[str, ...] = (),
) -> FMStudentState:
    deps: dict[str, tuple[float, float]] = {}
    for dep_id in dependency_ids:
        deps[dep_id] = (2.0, 2.0)
    return FMStudentState(
        concept_id=concept_id,
        formula_id=formula_id,
        mastery_mean=0.5,
        mastery_var=0.25 / 3.0,
        confidence=0.5,
        error_beliefs={"none": 1.0},
        dependency_beliefs=deps,
    )
