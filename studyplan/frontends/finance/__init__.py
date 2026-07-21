"""Finance frontend — ACCA-specific cognitive processes and executors.

Exports process implementations and executors for the ACCA domain::

    ComputationProcess       — pure-function evaluation (formulas, ratios…)
    ClassificationProcess    — decision-tree traversal (risk, classification…)
    EvaluationProcess        — weighted multi-criteria judgment
    DiagnosticProcess        — Bayesian belief revision
    ClassificationExecutor   — multi-step tree-walking executor

All classes that implement :class:`~studyplan.cci.process.CognitiveProcess`
or :class:`~studyplan.cci.executor.CognitiveExecutor` can be driven by
:class:`~studyplan.cci.runtime.CognitiveRuntime`.
"""

from studyplan.frontends.finance.computation import ComputationProcess
from studyplan.frontends.finance.classification import ClassificationProcess
from studyplan.frontends.finance.evaluation import EvaluationProcess
from studyplan.frontends.finance.diagnostic import DiagnosticProcess
from studyplan.frontends.finance.executors import (
    ClassificationExecutor,
    DiagnosticExecutor,
    EvaluationExecutor,
)

__all__ = [
    "ComputationProcess",
    "ClassificationProcess",
    "EvaluationProcess",
    "DiagnosticProcess",
    "ClassificationExecutor",
    "DiagnosticExecutor",
    "EvaluationExecutor",
]
