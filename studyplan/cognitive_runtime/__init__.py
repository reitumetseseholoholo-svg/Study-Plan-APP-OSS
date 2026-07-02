"""Cognitive Runtime — drives state evolution, emits immutable traces.

Minimal core::

    runtime = CognitiveRuntime()
    trace = runtime.execute(process, inputs)

All interpretation is downstream via TraceInterpreter subclasses.
"""

from studyplan.cognitive_runtime.event import CognitiveEvent, ExecutionTrace
from studyplan.cognitive_runtime.process import CognitiveProcess
from studyplan.cognitive_runtime.runtime import CognitiveRuntime
from studyplan.cognitive_runtime.interpreters import (
    TraceInterpreter,
    ComputationResultInterpreter,
    ComputationErrorInterpreter,
    ComputationStepEvaluator,
)
from studyplan.cognitive_runtime.computation import ComputationProcess

__all__ = [
    "CognitiveEvent",
    "ExecutionTrace",
    "CognitiveProcess",
    "CognitiveRuntime",
    "TraceInterpreter",
    "ComputationResultInterpreter",
    "ComputationErrorInterpreter",
    "ComputationStepEvaluator",
    "ComputationProcess",
]
