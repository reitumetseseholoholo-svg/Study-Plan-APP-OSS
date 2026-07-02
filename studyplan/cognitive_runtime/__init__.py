"""Cognitive Runtime — drives state evolution, emits immutable traces.

Minimal core::

    runtime = CognitiveRuntime()
    trace = runtime.execute(process, inputs)

All interpretation is downstream via TraceInterpreter subclasses.
"""

from studyplan.cognitive_runtime.event import CognitiveEvent, ExecutionTrace
from studyplan.cognitive_runtime.process import CognitiveProcess
from studyplan.cognitive_runtime.runtime import CognitiveRuntime
from studyplan.cognitive_runtime.computation import ComputationProcess
from studyplan.cognitive_runtime.classification import ClassificationProcess
from studyplan.cognitive_runtime.evaluation import EvaluationProcess
from studyplan.cognitive_runtime.interpreters import (
    TraceInterpreter,
    ComputationResultInterpreter,
    ComputationErrorInterpreter,
    ComputationStepEvaluator,
    ClassificationResultInterpreter,
    ClassificationStepEvaluator,
    EvaluationResultInterpreter,
    EvaluationStepEvaluator,
)

__all__ = [
    "CognitiveEvent",
    "ExecutionTrace",
    "CognitiveProcess",
    "CognitiveRuntime",
    "ComputationProcess",
    "ClassificationProcess",
    "EvaluationProcess",
    "TraceInterpreter",
    "ComputationResultInterpreter",
    "ComputationErrorInterpreter",
    "ComputationStepEvaluator",
    "ClassificationResultInterpreter",
    "ClassificationStepEvaluator",
    "EvaluationResultInterpreter",
    "EvaluationStepEvaluator",
]
