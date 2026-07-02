"""Downstream interpreters — consume immutable ExecutionTraces.

Interpreters are pure functions over traces.  They have no access to the
process that produced the trace.  Multiple interpreters can process the
same trace independently.
"""

from __future__ import annotations

import math
from typing import Any

from studyplan.cognitive_runtime.event import ExecutionTrace


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class TraceInterpreter:
    """Abstract base for all trace interpreters."""

    def interpret(self, trace: ExecutionTrace, **kwargs: Any) -> Any:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Computation interpreters
# ---------------------------------------------------------------------------


class ComputationResultInterpreter(TraceInterpreter):
    """Read a ComputationProcess trace → standard result dict.

    Produces the same shape as ``ExpressionTemplate.solve()``::

        {concept_id, result, inputs, is_nan, steps}
    """

    def __init__(self, concept_id: str, expression: str | None = None) -> None:
        self._concept_id = concept_id
        self._expression = expression

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = None
        is_nan = True
        inputs: dict[str, Any] = {}

        for event in trace.events:
            payload = event.payload
            if event.type == "initialize":
                inputs = payload.get("state", {}).get("inputs", {})
            elif event.type == "step":
                transition = payload.get("transition", {})
                result = transition.get("result")
                is_nan = isinstance(result, float) and math.isnan(result)
            elif event.type == "terminate":
                if result is None:
                    result = payload.get("result")

        steps: list[dict[str, Any]] = []
        if self._expression and result is not None:
            display_expr = self._expression
            for k, v in inputs.items():
                if isinstance(v, (int, float)):
                    display_expr = display_expr.replace(k, f"{v}")
            step_id = self._concept_id.replace("fm.", "", 1)
            steps.append(
                {
                    "step_id": step_id,
                    "description": f"{self._concept_id} formula",
                    "value": result,
                    "formula": display_expr,
                }
            )

        return {
            "concept_id": self._concept_id,
            "result": result,
            "inputs": dict(inputs),
            "is_nan": is_nan,
            "steps": steps,
        }


class ComputationErrorInterpreter(TraceInterpreter):
    """Read a ComputationProcess trace + learner steps → error tags.

    Produces the same output as ``ExpressionTemplate.classify_errors()``.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[str]:
        tags: list[str] = []
        truth_result = None
        for event in trace.events:
            if event.type == "step":
                transition = event.payload.get("transition", {})
                truth_result = transition.get("result")

        if truth_result is None or (isinstance(truth_result, float) and math.isnan(truth_result)):
            return tags

        learner_steps: list[dict[str, Any]] = kwargs.get("learner_steps", [])
        for step in learner_steps:
            step_val = step.get("value")
            step_id = step.get("step_id", "")
            if step_id and step_val is not None:
                try:
                    diff = abs(float(step_val) - float(truth_result))
                    if diff > max(0.01, abs(float(truth_result)) * 0.005):
                        tags.append(f"{step_id}_mismatch")
                except (ValueError, TypeError):
                    tags.append(f"{step_id}_parse_error")
        return tags


class ComputationStepEvaluator(TraceInterpreter):
    """Read a ComputationProcess trace + learner steps → step evaluations.

    Produces the same output as ``ExpressionTemplate.evaluate_steps()``.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        truth_result = None
        for event in trace.events:
            if event.type == "step":
                transition = event.payload.get("transition", {})
                truth_result = transition.get("result")

        results: list[dict[str, Any]] = []
        learner_steps: list[dict[str, Any]] = kwargs.get("learner_steps", [])
        for step in learner_steps:
            step_val = step.get("value")
            match = False
            if step_val is not None and truth_result is not None:
                match = abs(float(step_val) - float(truth_result)) < max(0.01, abs(float(truth_result)) * 0.005)
            results.append(
                {
                    "step_id": step.get("step_id", ""),
                    "expected": truth_result,
                    "actual": step_val,
                    "match": match,
                }
            )
        return results


# ---------------------------------------------------------------------------
# Classification interpreters
# ---------------------------------------------------------------------------


class ClassificationResultInterpreter(TraceInterpreter):
    """Read a ClassificationProcess trace → standard result dict.

    Produces the same shape as ``ClassificationTemplate.solve()``::

        {concept_id, result, inputs, is_nan, steps, classification_path}
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = None
        is_nan = True
        inputs: dict[str, Any] = {}
        steps: list[dict[str, Any]] = []
        classification_path: list[str] = []

        for event in trace.events:
            if event.type == "initialize":
                inputs = event.payload.get("state", {}).get("inputs", {})
            elif event.type == "step":
                t = event.payload.get("transition", {})
                result = t.get("result")
                is_nan = t.get("is_nan", True)
                steps = t.get("steps", [])
                classification_path = t.get("classification_path", [])

        return {
            "concept_id": kwargs.get("concept_id", ""),
            "result": result,
            "inputs": dict(inputs),
            "is_nan": is_nan,
            "steps": list(steps),
            "classification_path": list(classification_path),
        }


class ClassificationStepEvaluator(TraceInterpreter):
    """Read a ClassificationProcess trace + learner steps → evaluations.

    Produces the same output as ``ClassificationTemplate.evaluate_steps()``.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        truth_result = None
        for event in trace.events:
            if event.type == "step":
                truth_result = event.payload.get("transition", {}).get("result")

        results: list[dict[str, Any]] = []
        learner_steps = kwargs.get("learner_steps", [])
        for step in learner_steps:
            step_val = step.get("value")
            match = False
            if step_val is not None and truth_result is not None:
                match = step_val == truth_result
            results.append(
                {
                    "step_id": step.get("step_id", ""),
                    "expected": truth_result,
                    "actual": step_val,
                    "match": match,
                }
            )
        return results


# ---------------------------------------------------------------------------
# Evaluation interpreters
# ---------------------------------------------------------------------------


class EvaluationResultInterpreter(TraceInterpreter):
    """Read an EvaluationProcess trace → standard result dict.

    Produces the same shape as ``EvaluationTemplate.solve()``::

        {concept_id, judgment, scores, ranked, confidence,
         justification, contributions, entropy, result, inputs, is_nan}
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> dict[str, Any]:
        judgment = None
        scores = {}
        ranked: list = []
        confidence = 0.0
        justification: list = []
        contributions: list = []
        entropy = 0.0
        is_nan = False
        inputs: dict[str, Any] = {}

        for event in trace.events:
            if event.type == "initialize":
                inputs = event.payload.get("state", {}).get("inputs", {})
            elif event.type == "step":
                t = event.payload.get("transition", {})
                judgment = t.get("judgment")
                scores = t.get("scores", {})
                ranked = t.get("ranked", [])
                confidence = t.get("confidence", 0.0)
                justification = t.get("justification", [])
                contributions = t.get("contributions", [])
                entropy = t.get("entropy", 0.0)
                is_nan = t.get("is_nan", False)

        return {
            "concept_id": kwargs.get("concept_id", ""),
            "judgment": judgment,
            "scores": scores,
            "ranked": ranked,
            "confidence": confidence,
            "justification": justification,
            "contributions": contributions,
            "entropy": entropy,
            "result": {"judgment": judgment, "confidence": confidence},
            "inputs": dict(inputs),
            "is_nan": is_nan,
        }


class EvaluationStepEvaluator(TraceInterpreter):
    """Read an EvaluationProcess trace + learner steps → evaluations.

    Produces the same output as ``EvaluationTemplate.evaluate_steps()``.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        truth_judgment = None
        for event in trace.events:
            if event.type == "step":
                truth_judgment = event.payload.get("transition", {}).get("judgment")

        results: list[dict[str, Any]] = []
        learner_steps = kwargs.get("learner_steps", [])
        for step in learner_steps:
            step_val = step.get("judgment") or step.get("value")
            match = False
            if isinstance(step_val, str) and isinstance(truth_judgment, str):
                match = step_val.strip().lower() == truth_judgment.strip().lower()
            results.append(
                {
                    "step_id": step.get("step_id", ""),
                    "expected": truth_judgment,
                    "actual": step_val,
                    "match": match,
                }
            )
        return results
