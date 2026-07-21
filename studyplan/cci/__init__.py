"""Cognitive Runtime — drives state evolution, emits immutable traces.

Minimal core::

    runtime = CognitiveRuntime()
    trace = runtime.execute(process, inputs)

All interpretation is downstream via TraceInterpreter subclasses.
Causal structure is reconstructible via CanonicalTraceReconstructor.
"""

from studyplan.cci.event import CCI_TRACE_VERSION, CognitiveEvent, ExecutionTrace
from studyplan.cci.executor import CognitiveExecutor, Transition
from studyplan.cci.ir import CognitiveCommit, commit_from_executor_result
from studyplan.cci.process import CognitiveProcess
from studyplan.cci.runtime import CognitiveRuntime
from studyplan.cci.interpreters import (
    TraceInterpreter,
    ComputationResultInterpreter,
    ComputationErrorInterpreter,
    ComputationStepEvaluator,
    ClassificationResultInterpreter,
    ClassificationStepEvaluator,
    ClassificationAuditor,
    EvaluationResultInterpreter,
    EvaluationStepEvaluator,
    DiagnosticResultInterpreter,
    DiagnosticStepEvaluator,
    DiagnosticErrorInterpreter,
)
from studyplan.cci.reconstructor import (
    CanonicalTraceReconstructor,
    ReconstructedGraph,
    is_linearly_representable,
    structurally_equivalent,
)

__all__ = [
    "CCI_TRACE_VERSION",
    "CognitiveCommit",
    "CognitiveEvent",
    "CognitiveExecutor",
    "ExecutionTrace",
    "CognitiveProcess",
    "CognitiveRuntime",
    "CognitiveCommit",
    "Transition",
    "commit_from_executor_result",
    "TraceInterpreter",
    "ComputationResultInterpreter",
    "ComputationErrorInterpreter",
    "ComputationStepEvaluator",
    "ClassificationResultInterpreter",
    "ClassificationStepEvaluator",
    "EvaluationResultInterpreter",
    "EvaluationStepEvaluator",
    "ClassificationAuditor",
    "DiagnosticResultInterpreter",
    "DiagnosticStepEvaluator",
    "DiagnosticErrorInterpreter",
    "CanonicalTraceReconstructor",
    "ReconstructedGraph",
    "is_linearly_representable",
    "structurally_equivalent",
]
