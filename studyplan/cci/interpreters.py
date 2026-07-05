"""Downstream interpreters — consume immutable ExecutionTraces.

Interpreters are pure functions over traces.  They have no access to the
process that produced the trace.  Multiple interpreters can process the
same trace independently.
"""

from __future__ import annotations

import math
from typing import Any

from studyplan.cci.event import ExecutionTrace


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

    Reads directly from the immutable trace events (not from process
    internals).  Produces the same shape as ``ExpressionTemplate.solve()``::

        {concept_id, result, inputs, is_nan, steps}

    The result is extracted from the ``terminate`` event.  Inputs
    come from the ``initialize`` event.  No transition metadata is read.
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
        inputs: dict[str, Any] = {}

        for event in trace.events:
            payload = event.payload
            if event.type == "initialize":
                inputs = payload.get("state", {}).get("inputs", {})
            elif event.type == "terminate":
                result = payload.get("result")

        is_nan = result is None or (isinstance(result, float) and math.isnan(result))

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
    The ground truth result is read from the ``terminate`` event.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[str]:
        tags: list[str] = []
        truth_result = None
        for event in trace.events:
            if event.type == "terminate":
                truth_result = event.payload.get("result")

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
    The ground truth result is read from the ``terminate`` event.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        truth_result = None
        for event in trace.events:
            if event.type == "terminate":
                truth_result = event.payload.get("result")

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


# ---------------------------------------------------------------------------
# Classification auditor — tree topology from step payload
# ---------------------------------------------------------------------------


class ClassificationAuditor(TraceInterpreter):
    """Extract decision tree topology from classification trace payload.

    The canonical reconstructor is payload-agnostic — it sees 3 events
    (init, step, terminate) regardless of tree depth.  This auditor reads
    the enriched *steps* list (recorded by ``_traverse`` and
    ``_traverse_children``) to reconstruct the actual tree depth,
    decision count, and branching structure.

    Metrics produced::

        tree_depth         — number of decision levels visited
        decision_count     — total decision nodes visited
        leaf_result        — the terminal classification label
        matched_conditions — list of condition strings along the path
        path_richness      — ratio of non-root decisions to total depth
                             (0.0 = single-level, >0.0 = multi-level)
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        result = None

        for event in trace.events:
            if event.type == "step":
                t = event.payload.get("transition", {})
                steps = t.get("steps", [])
                result = t.get("result")

        decisions = [s for s in steps if s.get("step_id") == "decision"]
        matched: list[str] = []
        for d in decisions:
            mc = d.get("matched_condition")
            if mc and isinstance(mc, str):
                matched.append(mc)

        tree_depth = len(decisions)

        return {
            "concept_id": kwargs.get("concept_id", ""),
            "result": result,
            "tree_depth": tree_depth,
            "decision_count": len(decisions),
            "matched_conditions": matched,
            "path_richness": (tree_depth - 1) / max(tree_depth, 1),
        }


# ---------------------------------------------------------------------------
# Diagnostic interpreters
# ---------------------------------------------------------------------------


class DiagnosticResultInterpreter(TraceInterpreter):
    """Read a DiagnosticProcess trace → standard result dict.

    Produces the same shape as ``DiagnosticTemplate.solve()``::

        {concept_id, result, inputs, is_nan, steps,
         posterior_distribution, map_hypothesis, map_probability,
         entropy, recommended_investigations}
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> dict[str, Any]:
        result = None
        is_nan = True
        inputs: dict[str, Any] = {}
        posterior_distribution: dict[str, float] = {}
        map_hypothesis: str | None = None
        map_probability: float = 0.0
        entropy: float = 0.0
        recommended_investigations: list[dict[str, Any]] = []
        steps: list[dict[str, Any]] = []

        for event in trace.events:
            if event.type == "initialize":
                inputs = event.payload.get("state", {}).get("inputs", {})
            elif event.type == "step":
                t = event.payload.get("transition", {})
                result = t.get("map_hypothesis")
                is_nan = t.get("is_nan", True)
                map_hypothesis = t.get("map_hypothesis")
                map_probability = t.get("map_probability", 0.0)
                entropy = t.get("entropy", 0.0)
                posterior_distribution = t.get("posterior_distribution", {})
                recommended_investigations = t.get("recommended_investigations", [])
                steps = t.get("steps", [])

        return {
            "concept_id": kwargs.get("concept_id", ""),
            "result": result,
            "inputs": dict(inputs),
            "is_nan": is_nan,
            "posterior_distribution": dict(posterior_distribution),
            "map_hypothesis": map_hypothesis,
            "map_probability": map_probability,
            "entropy": entropy,
            "recommended_investigations": list(recommended_investigations),
            "steps": list(steps),
        }


class DiagnosticStepEvaluator(TraceInterpreter):
    """Read a DiagnosticProcess trace + learner steps → evaluations.

    Produces the same output as ``DiagnosticTemplate.evaluate_steps()``.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        truth_dx = None
        for event in trace.events:
            if event.type == "step":
                truth_dx = event.payload.get("transition", {}).get("map_hypothesis")

        results: list[dict[str, Any]] = []
        learner_steps = kwargs.get("learner_steps", [])
        for step in learner_steps:
            step_val = step.get("diagnosis") or step.get("value")
            match = False
            if isinstance(step_val, str) and isinstance(truth_dx, str):
                match = step_val.strip().lower() == truth_dx.strip().lower()
            results.append(
                {
                    "step_id": step.get("step_id", ""),
                    "expected": truth_dx,
                    "actual": step_val,
                    "match": match,
                }
            )
        return results


class DiagnosticErrorInterpreter(TraceInterpreter):
    """Read a DiagnosticProcess trace + learner steps → error tags.

    Produces the same output as ``DiagnosticTemplate.classify_errors()``.
    """

    def interpret(
        self,
        trace: ExecutionTrace,
        **kwargs: Any,
    ) -> list[str]:
        truth_dx = None
        for event in trace.events:
            if event.type == "step":
                truth_dx = event.payload.get("transition", {}).get("map_hypothesis")

        tags: list[str] = []
        learner_steps: list[dict[str, Any]] = kwargs.get("learner_steps", [])
        if not learner_steps:
            return tags

        hypotheses_considered: set[str] = set()
        final_answer: str | None = None
        for step in learner_steps:
            sv = step.get("diagnosis") or step.get("value")
            if isinstance(sv, str):
                svn = sv.strip().lower()
                hypotheses_considered.add(svn)
                final_answer = svn

        truth_lower = truth_dx.strip().lower() if truth_dx and isinstance(truth_dx, str) else None
        if truth_lower and final_answer and final_answer != truth_lower:
            if truth_lower not in hypotheses_considered:
                tags.append("hypothesis_not_considered")
            else:
                tags.append("wrong_diagnosis")

        evidence_count = sum(1 for s in learner_steps if s.get("type") == "observation" or s.get("feature"))
        if evidence_count < 2:
            tags.append("insufficient_evidence")

        return tags
