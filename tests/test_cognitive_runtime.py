"""Test the CognitiveRuntime + ComputationProcess identity with ExpressionTemplate.

This test proves that the new runtime, process, and interpreters produce
*identical* output to the existing ExpressionTemplate for the same inputs.
If this test passes, the runtime is a valid replacement for the computation
path (behavioral identity proven).
"""

import math

from studyplan.domain_reasoning import declare_formula

from studyplan.cognitive_runtime import (
    CognitiveRuntime,
    ComputationProcess,
    ClassificationProcess,
    EvaluationProcess,
    ComputationResultInterpreter,
    ComputationErrorInterpreter,
    ComputationStepEvaluator,
    ClassificationResultInterpreter,
    ClassificationStepEvaluator,
    EvaluationResultInterpreter,
    EvaluationStepEvaluator,
)


# =========================================================================
# Fixtures — register standard formulas
# =========================================================================

# Use existing declare_formula to register concepts
NPV_CONCEPT = "test.rt_npv"
WACC_CONCEPT = "test.rt_wacc"


def setup_module():
    """Register test formulas once for the module."""
    declare_formula(
        NPV_CONCEPT,
        expression="cash_flow / (1 + rate) ** years",
        param_names=["cash_flow", "rate", "years"],
        param_kinds=["value", "percent", "value"],
        output_slot="npv",
    )
    declare_formula(
        WACC_CONCEPT,
        expression="ke * eq + kd * (1 - tx) * debt",
        param_names=["ke", "eq", "kd", "tx", "debt"],
        param_kinds=["percent", "percent", "percent", "percent", "percent"],
        output_slot="wacc",
    )


def teardown_module():
    """Clean up registered formulas."""
    from studyplan.domain_reasoning.formula_registry import _registry

    for cid in [NPV_CONCEPT, WACC_CONCEPT]:
        _registry.pop(cid, None)


# =========================================================================
# Identity test: solve()
# =========================================================================


def _get_solver_and_expr(concept_id: str):
    """Retrieve solver function and expression string from the registry."""
    from studyplan.domain_reasoning.formula_registry import _registry, FormulaDecl

    decl: FormulaDecl = _registry[concept_id]
    template = decl.template
    # ExpressionTemplate stores _solver and _expression
    return template._solver, template._expression


def test_runtime_computation_identity_npv():
    """Runtime + interpreter produce identical result to ExpressionTemplate."""
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    inputs = {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0}

    # --- Old path ---
    from studyplan.domain_reasoning.formula_registry import ExpressionTemplate

    old_tpl = ExpressionTemplate(NPV_CONCEPT, solver, expr)
    old_result = old_tpl.solve(inputs)

    # --- New path ---
    runtime = CognitiveRuntime()
    process = ComputationProcess(NPV_CONCEPT, solver, expr)
    trace = runtime.execute(process, inputs)
    interpreter = ComputationResultInterpreter(NPV_CONCEPT, expr)
    new_result = interpreter.interpret(trace)

    # --- Identity check ---
    assert old_result["concept_id"] == new_result["concept_id"]
    assert abs(old_result["result"] - new_result["result"]) < 1e-9
    assert old_result["inputs"] == new_result["inputs"]
    assert old_result["is_nan"] == new_result["is_nan"]
    assert len(old_result["steps"]) == len(new_result["steps"])
    for old_step, new_step in zip(old_result["steps"], new_result["steps"], strict=True):
        assert abs(old_step["value"] - new_step["value"]) < 1e-9
        assert old_step["formula"] == new_step["formula"]


def test_runtime_computation_identity_wacc():
    """Identity holds for a different formula (WACC)."""
    solver, expr = _get_solver_and_expr(WACC_CONCEPT)
    inputs = {"ke": 0.12, "eq": 0.6, "kd": 0.08, "tx": 0.30, "debt": 0.4}

    from studyplan.domain_reasoning.formula_registry import ExpressionTemplate

    old_tpl = ExpressionTemplate(WACC_CONCEPT, solver, expr)
    old_result = old_tpl.solve(inputs)

    runtime = CognitiveRuntime()
    process = ComputationProcess(WACC_CONCEPT, solver, expr)
    trace = runtime.execute(process, inputs)
    interpreter = ComputationResultInterpreter(WACC_CONCEPT, expr)
    new_result = interpreter.interpret(trace)

    assert abs(old_result["result"] - new_result["result"]) < 1e-9


# =========================================================================
# Identity test: evaluate_steps()
# =========================================================================


def test_runtime_computation_evaluate_steps_identity():
    """Runtime + step evaluator produce identical evaluate_steps output."""
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    inputs = {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0}

    from studyplan.domain_reasoning.formula_registry import ExpressionTemplate

    old_tpl = ExpressionTemplate(NPV_CONCEPT, solver, expr)
    truth = old_tpl.solve(inputs)

    learner_steps = [
        {"step_id": "npv", "value": 909.09},
        {"step_id": "wrong_step", "value": 1000.0},
    ]

    # Old path
    old_evals = old_tpl.evaluate_steps(learner_steps, truth)

    # New path
    runtime = CognitiveRuntime()
    process = ComputationProcess(NPV_CONCEPT, solver, expr)
    trace = runtime.execute(process, inputs)
    evaluator = ComputationStepEvaluator()
    new_evals = evaluator.interpret(trace, learner_steps=learner_steps)

    # Identity
    assert len(old_evals) == len(new_evals)
    for o, n in zip(old_evals, new_evals, strict=True):
        assert o["step_id"] == n["step_id"]
        assert o["match"] == n["match"]


# =========================================================================
# Identity test: classify_errors()
# =========================================================================


def test_runtime_computation_classify_errors_identity():
    """Runtime + error interpreter produce identical error tags."""
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    inputs = {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0}

    from studyplan.domain_reasoning.formula_registry import ExpressionTemplate

    old_tpl = ExpressionTemplate(NPV_CONCEPT, solver, expr)
    truth = old_tpl.solve(inputs)

    # Wrong answer
    learner_steps = [
        {"step_id": "npv", "value": 800.0},
    ]

    # Old path
    old_tags = old_tpl.classify_errors(learner_steps, truth)

    # New path
    runtime = CognitiveRuntime()
    process = ComputationProcess(NPV_CONCEPT, solver, expr)
    trace = runtime.execute(process, inputs)
    error_interp = ComputationErrorInterpreter()
    new_tags = error_interp.interpret(trace, learner_steps=learner_steps)

    assert old_tags == new_tags


# =========================================================================
# Runtime behaviour tests
# =========================================================================


def test_runtime_trace_structure():
    """Trace contains exactly initialize, step, terminate events."""
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    inputs = {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0}

    runtime = CognitiveRuntime()
    process = ComputationProcess(NPV_CONCEPT, solver, expr)
    trace = runtime.execute(process, inputs)

    assert len(trace) == 3
    assert trace.events[0].type == "initialize"
    assert trace.events[1].type == "step"
    assert trace.events[2].type == "terminate"


def test_runtime_trace_immutable():
    """Trace events list is a copy — original is not mutable from outside."""
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    runtime = CognitiveRuntime()
    process = ComputationProcess(NPV_CONCEPT, solver, expr)
    trace = runtime.execute(process, {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0})

    events = trace.events
    events.clear()
    assert len(trace.events) == 3  # original unchanged


def test_runtime_nan_result():
    """Missing inputs produce is_nan=True result."""
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    inputs = {"cash_flow": 1000.0, "rate": 0.10}  # missing "years"

    runtime = CognitiveRuntime()
    process = ComputationProcess(NPV_CONCEPT, solver, expr)
    trace = runtime.execute(process, inputs)
    interpreter = ComputationResultInterpreter(NPV_CONCEPT, expr)
    result = interpreter.interpret(trace)

    assert result["is_nan"] is True
    assert result["result"] is None or (isinstance(result["result"], float) and math.isnan(result["result"]))


def test_process_is_stateless():
    """Multiple execute() calls on the same process produce independent traces."""
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    process = ComputationProcess(NPV_CONCEPT, solver, expr)
    runtime = CognitiveRuntime()

    trace1 = runtime.execute(process, {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0})
    trace2 = runtime.execute(process, {"cash_flow": 2000.0, "rate": 0.10, "years": 2.0})

    interp = ComputationResultInterpreter(NPV_CONCEPT, expr)
    r1 = interp.interpret(trace1)
    r2 = interp.interpret(trace2)

    assert abs(r1["result"] - 909.09) < 0.1
    assert abs(r2["result"] - 1652.89) < 0.1


# =========================================================================
# Classification identity tests
# =========================================================================


def _make_classification_tree():
    """Build a simple classification tree for testing."""
    from studyplan.domain_reasoning.concept_types.classification_concept import (
        ClassificationNode,
        Branch,
        ClassificationConfig,
        ClassificationTemplate,
    )

    tree = ClassificationNode(
        question="Is the amount material?",
        branches=[
            Branch(condition="amount > 1000", result="material"),
            Branch(condition="True", result="immaterial"),
        ],
    )
    config = ClassificationConfig(tree=tree, output_slot="materiality")
    return ClassificationTemplate("test.class_materiality", config)


def test_runtime_classification_identity_solve():
    """ClassificationProcess + interpreter produce identical result to template."""
    template = _make_classification_tree()
    inputs = {"amount": 5000.0}

    # Old path
    old_result = template.solve(inputs)

    # New path
    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)
    interpreter = ClassificationResultInterpreter()

    # Need concept_id since our interpreter doesn't store it
    new_result = interpreter.interpret(trace, concept_id=template.concept_id)

    assert old_result["result"] == new_result["result"]
    assert old_result["is_nan"] == new_result["is_nan"]
    assert old_result["classification_path"] == new_result["classification_path"]
    assert len(old_result["steps"]) == len(new_result["steps"])


def test_runtime_classification_identity_no_match():
    """When no branch matches, result is None and is_nan is True."""
    from studyplan.domain_reasoning.concept_types.classification_concept import (
        ClassificationNode,
        Branch,
        ClassificationConfig,
        ClassificationTemplate,
    )

    # Tree with no catch-all — won't match
    tree = ClassificationNode(
        question="Is it urgent?",
        branches=[
            Branch(condition="urgency > 100", result="urgent"),
        ],
    )
    config = ClassificationConfig(tree=tree)
    template = ClassificationTemplate("test.urgency", config)
    inputs = {"urgency": 10.0}

    old_result = template.solve(inputs)

    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)
    interpreter = ClassificationResultInterpreter()
    new_result = interpreter.interpret(trace, concept_id=template.concept_id)

    assert old_result["result"] is None
    assert new_result["result"] is None
    assert old_result["is_nan"] is True
    assert new_result["is_nan"] is True


def test_runtime_classification_evaluate_steps():
    """Classification step evaluator matches template behavior."""
    template = _make_classification_tree()
    inputs = {"amount": 5000.0}
    truth = template.solve(inputs)

    learner_steps = [
        {"step_id": "materiality", "value": "material"},
        {"step_id": "wrong", "value": "immaterial"},
    ]

    old_evals = template.evaluate_steps(learner_steps, truth)

    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)
    evaluator = ClassificationStepEvaluator()
    new_evals = evaluator.interpret(trace, learner_steps=learner_steps)

    assert len(old_evals) == len(new_evals)
    for o, n in zip(old_evals, new_evals, strict=True):
        assert o["match"] == n["match"]


# =========================================================================
# Evaluation identity tests
# =========================================================================


def _make_evaluation_template():
    """Build a simple evaluation template for testing."""
    from studyplan.domain_reasoning.process import (
        EvaluationConfig,
        EvaluationCriterion,
        EvaluationTemplate,
    )

    config = EvaluationConfig(
        criteria=[
            EvaluationCriterion(id="cost", weight=0.6),
            EvaluationCriterion(id="quality", weight=0.4),
        ],
        candidates=["option_a", "option_b"],
    )
    return EvaluationTemplate("test.eval_identity", config)


def test_runtime_evaluation_identity_solve():
    """EvaluationProcess + interpreter produce identical result to template."""
    template = _make_evaluation_template()
    inputs = {
        "cost": {"option_a": 0.8, "option_b": 0.2},
        "quality": {"option_a": 0.3, "option_b": 0.7},
    }

    old_result = template.solve(inputs)

    runtime = CognitiveRuntime()
    process = EvaluationProcess(template)
    trace = runtime.execute(process, inputs)
    interpreter = EvaluationResultInterpreter()
    new_result = interpreter.interpret(trace, concept_id=template.concept_id)

    assert old_result["judgment"] == new_result["judgment"]
    assert old_result["confidence"] == new_result["confidence"]
    assert old_result["entropy"] == new_result["entropy"]
    assert old_result["scores"] == new_result["scores"]
    # Check ranked order
    assert old_result["ranked"][0][0] == new_result["ranked"][0][0]
    assert abs(old_result["ranked"][0][1] - new_result["ranked"][0][1]) < 1e-9
    # Check justification
    assert len(old_result["justification"]) == len(new_result["justification"])


def test_runtime_evaluation_evaluate_steps():
    """Evaluation step evaluator matches template behavior."""
    template = _make_evaluation_template()
    inputs = {
        "cost": {"option_a": 0.8, "option_b": 0.2},
        "quality": {"option_a": 0.3, "option_b": 0.7},
    }
    truth = template.solve(inputs)

    learner_steps = [
        {"step_id": "final", "judgment": "option_a"},
        {"step_id": "wrong", "judgment": "option_b"},
    ]

    old_evals = template.evaluate_steps(learner_steps, truth)

    runtime = CognitiveRuntime()
    process = EvaluationProcess(template)
    trace = runtime.execute(process, inputs)
    evaluator = EvaluationStepEvaluator()
    new_evals = evaluator.interpret(trace, learner_steps=learner_steps)

    assert len(old_evals) == len(new_evals)
    for o, n in zip(old_evals, new_evals, strict=True):
        assert o["match"] == n["match"]
        assert o["step_id"] == n["step_id"]


def test_runtime_all_algebras_same_substrate():
    """All three algebra types execute on the same runtime with same trace shape."""
    runtime = CognitiveRuntime()

    # Computation
    solver, expr = _get_solver_and_expr(NPV_CONCEPT)
    t1 = runtime.execute(
        ComputationProcess(NPV_CONCEPT, solver, expr),
        {"cash_flow": 1000.0, "rate": 0.10, "years": 1.0},
    )

    # Classification
    t2 = runtime.execute(
        ClassificationProcess(_make_classification_tree()),
        {"amount": 5000.0},
    )

    # Evaluation
    t3 = runtime.execute(
        EvaluationProcess(_make_evaluation_template()),
        {"cost": {"option_a": 0.8, "option_b": 0.2}, "quality": {"option_a": 0.3, "option_b": 0.7}},
    )

    # All traces have the same structure: init → step → terminate
    for trace in [t1, t2, t3]:
        assert len(trace) == 3
        assert trace.events[0].type == "initialize"
        assert trace.events[1].type == "step"
        assert trace.events[2].type == "terminate"


def test_runtime_trace_sufficiency():
    """A single trace can feed multiple independent interpreters."""
    template = _make_evaluation_template()
    inputs = {
        "cost": {"option_a": 0.8, "option_b": 0.2},
        "quality": {"option_a": 0.3, "option_b": 0.7},
    }

    runtime = CognitiveRuntime()
    process = EvaluationProcess(template)
    trace = runtime.execute(process, inputs)

    # Two interpreters, same trace
    result_interp = EvaluationResultInterpreter()
    step_interp = EvaluationStepEvaluator()

    result = result_interp.interpret(trace, concept_id=template.concept_id)
    evals = step_interp.interpret(
        trace,
        learner_steps=[
            {"step_id": "final", "judgment": "option_a"},
        ],
    )

    assert result["judgment"] == "option_a"
    assert evals[0]["match"] is True
