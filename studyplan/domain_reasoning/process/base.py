"""Abstract base for all cognitive process templates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ProcessTemplate(ABC):
    """Contract for all cognitive process templates.

    Every template — whether computation, diagnosis, evaluation, or
    construction — exposes the same three-method interface that the
    reasoning engine calls during plan execution.
    """

    concept_id: str
    template_version: str = "1.0.0"

    @abstractmethod
    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the process with *inputs* and return structured result.

        The result dict must include at minimum:
          - ``concept_id``
          - ``result``       — the primary output
          - ``inputs``       — the inputs that were actually used
          - ``is_nan``       — True if execution failed
          - ``steps``        — list of step dicts for step-by-step diagnosis
        """
        ...

    @abstractmethod
    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Compare a learner's reasoning steps against ground truth.

        Returns one dict per step with keys ``step_id``, ``expected``,
        ``actual``, ``match``.
        """
        ...

    @abstractmethod
    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]:
        """Classify errors found in the learner's steps.

        Returns a list of error tag strings (e.g. ``wrong_diagnosis``,
        ``hypothesis_not_considered``, ``insufficient_evidence``).
        """
        ...
