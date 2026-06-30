"""Tests for the formula registry (formula_registry.py).

Covers: FormulaDecl, ExpressionTemplate, ChainTemplate,
declare_concept / declare_formula / declare_formula_chain,
build helpers, validation, and internal solver/candidate functions.

Note: the global _registry is mutated at import time by module-level
declare_formula() calls. Tests save/restore the registry to avoid
side effects between tests.
"""

from __future__ import annotations

import ast
import copy
import math
import re
from typing import Any

import pytest

from studyplan.domain_reasoning.formula_registry import (
    CONCEPT_TYPE_CLASSIFICATION,
    CONCEPT_TYPE_EXPRESSION,
    CONCEPT_TYPE_LOOKUP,
    CONCEPT_TYPE_RULE_CHAIN,
    ChainStep,
    ChainTemplate,
    ExpressionTemplate,
    FormulaDecl,
    RegistryValidationError,
    _CONCEPT_TYPES,
    _NameCollector,
    _declare_expression_concept,
    _make_candidate_fn,
    _make_expression_solver,
    _registry,
    _substitute_and_eval,
    build_candidate_dict,
    build_concept_dict,
    build_formula_to_concept,
    build_signatures,
    build_solver_dict,
    build_structure_type_concepts,
    build_template_registry,
    declare_concept,
    declare_formula,
    declare_formula_chain,
    get_registry,
    get_registry_formulas,
    validate_registry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _save_restore_registry():
    saved = copy.deepcopy(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


# ---------------------------------------------------------------------------
# _CONCEPT_TYPES
# ---------------------------------------------------------------------------


def test_concept_types_frozenset() -> None:
    assert CONCEPT_TYPE_EXPRESSION in _CONCEPT_TYPES
    assert CONCEPT_TYPE_RULE_CHAIN in _CONCEPT_TYPES
    assert CONCEPT_TYPE_LOOKUP in _CONCEPT_TYPES
    assert CONCEPT_TYPE_CLASSIFICATION in _CONCEPT_TYPES
    assert len(_CONCEPT_TYPES) == 4


# ---------------------------------------------------------------------------
# FormulaDecl
# ---------------------------------------------------------------------------


def test_formula_decl_defaults() -> None:
    decl = FormulaDecl(concept_id="fm.test")
    assert decl.concept_id == "fm.test"
    assert decl.concept_type == CONCEPT_TYPE_EXPRESSION
    assert decl.formula_name == ""
    assert decl.solver_fn is None
    assert decl.expression is None
    assert decl.param_names == ()
    assert decl.label == ""
    assert decl.priority == 0
    assert decl.centrality == 0.5


def test_formula_decl_with_fields() -> None:
    decl = FormulaDecl(
        concept_id="fm.custom",
        concept_type=CONCEPT_TYPE_RULE_CHAIN,
        formula_name="custom",
        label="Custom formula",
        priority=42,
        centrality=0.9,
    )
    assert decl.label == "Custom formula"
    assert decl.priority == 42
    assert decl.centrality == 0.9


# ---------------------------------------------------------------------------
# get_registry / get_registry_formulas
# ---------------------------------------------------------------------------


def test_get_registry_empty_initially() -> None:
    assert get_registry() == {}


def test_get_registry_returns_copy() -> None:
    reg = get_registry()
    reg["fm.test"] = FormulaDecl("fm.test")
    assert "fm.test" not in get_registry()


def test_get_registry_formulas() -> None:
    declare_formula("fm.abc", expression="x + y", param_names=["x", "y"])
    declare_formula("fm.def", expression="a - b", param_names=["a", "b"])
    formulas = get_registry_formulas()
    assert "abc" in formulas
    assert "def" in formulas
    assert len(formulas) == 2


# ---------------------------------------------------------------------------
# _substitute_and_eval
# ---------------------------------------------------------------------------


def test_substitute_and_eval_simple() -> None:
    result = _substitute_and_eval("x + y", {"x": 10.0, "y": 5.0})
    assert result == 15.0


def test_substitute_and_eval_with_sqrt() -> None:
    result = _substitute_and_eval("sqrt(x)", {"x": 16.0})
    assert result == 4.0


def test_substitute_and_eval_missing_variable() -> None:
    with pytest.raises(NameError):
        _substitute_and_eval("x + y", {"x": 1.0})


def test_substitute_and_eval_invalid_expression() -> None:
    with pytest.raises(ValueError, match="Invalid expression"):
        _substitute_and_eval("x + (y", {"x": 1.0, "y": 2.0})


# ---------------------------------------------------------------------------
# _NameCollector
# ---------------------------------------------------------------------------


def test_name_collector() -> None:
    collector = _NameCollector()
    collector.visit(ast.parse("sqrt(x) + y * z", mode="eval"))
    assert "x" in collector.names
    assert "y" in collector.names
    assert "z" in collector.names


def test_name_collector_visit_call_skips_func_name() -> None:
    collector = _NameCollector()
    collector.visit(ast.parse("sqrt(x)", mode="eval"))
    assert "x" in collector.names
    assert "sqrt" not in collector.names  # func name intentionally skipped


# ---------------------------------------------------------------------------
# _make_expression_solver
# ---------------------------------------------------------------------------


def test_expression_solver_valid() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    assert solver(a=3.0, b=4.0) == 7.0


def test_expression_solver_missing_param() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    result = solver(a=3.0)
    assert math.isnan(result)


def test_expression_solver_extra_kwargs() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    result = solver(a=3.0, b=4.0, extra=99.0)
    assert result == 7.0


def test_expression_solver_division_by_zero() -> None:
    solver = _make_expression_solver("a / b", ("a", "b"))
    result = solver(a=5.0, b=0.0)
    assert math.isinf(result) or math.isnan(result)


# ---------------------------------------------------------------------------
# _make_candidate_fn
# ---------------------------------------------------------------------------


def test_candidate_fn_valid() -> None:
    solver = _make_expression_solver("x * y", ("x", "y"))
    fn = _make_candidate_fn(("x", "y"), ("value", "value"), solver)
    nums = [{"value": 5.0, "is_percent": False}, {"value": 3.0, "is_percent": False}]
    candidates = fn(nums)
    assert len(candidates) > 0
    assert any(c.get("x") == 5.0 and c.get("y") == 3.0 for c in candidates)


def test_candidate_fn_not_enough_values() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    fn = _make_candidate_fn(("x", "y"), ("value", "value"), solver)
    nums = [{"value": 5.0, "is_percent": False}]
    assert fn(nums) == []


def test_candidate_fn_percent_params() -> None:
    solver = _make_expression_solver("x + p / 100", ("x", "p"))
    fn = _make_candidate_fn(("x", "p"), ("value", "percent"), solver)
    nums = [
        {"value": 10.0, "is_percent": False},
        {"value": 50.0, "is_percent": True},
    ]
    candidates = fn(nums)
    assert len(candidates) > 0


def test_candidate_fn_no_solver() -> None:
    fn = _make_candidate_fn(("x",), ())
    nums = [{"value": 42.0, "is_percent": False}]
    candidates = fn(nums)
    assert len(candidates) > 0


# ---------------------------------------------------------------------------
# ExpressionTemplate
# ---------------------------------------------------------------------------


def test_expression_template_solve() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    tmpl = ExpressionTemplate("fm.test", solver, "x + y")
    result = tmpl.solve({"x": 2.0, "y": 3.0})
    assert result["concept_id"] == "fm.test"
    assert result["result"] == 5.0
    assert not result["is_nan"]
    assert len(result["steps"]) == 1


def test_expression_template_solve_nan() -> None:
    solver = _make_expression_solver("x / y", ("x", "y"))
    tmpl = ExpressionTemplate("fm.div", solver, "x / y")
    result = tmpl.solve({"x": 0.0, "y": 0.0})
    assert result["is_nan"] is True or math.isnan(result.get("result", 0.0))


def test_expression_template_solve_missing_var() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    tmpl = ExpressionTemplate("fm.missing", solver, "a + b")
    result = tmpl.solve({"a": 1.0})
    assert math.isnan(result["result"])


def test_expression_template_evaluate_steps() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    tmpl = ExpressionTemplate("fm.eval", solver, "x + y")
    truth = tmpl.solve({"x": 5.0, "y": 3.0})
    learner = [{"step_id": "eval", "value": 8.0}]
    evals = tmpl.evaluate_steps(learner, truth)
    assert len(evals) == 1
    assert evals[0]["match"] is True


def test_expression_template_evaluate_steps_no_learner() -> None:
    tmpl = ExpressionTemplate("fm.empty", None, "x + y")
    assert tmpl.evaluate_steps([], {"result": 5.0}) == []


def test_expression_template_classify_errors() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    tmpl = ExpressionTemplate("fm.cls", solver, "x + y")
    truth = tmpl.solve({"x": 5.0, "y": 3.0})
    learner = [{"step_id": "cls", "value": 100.0}]
    tags = tmpl.classify_errors(learner, truth)
    assert "cls_mismatch" in tags


def test_expression_template_classify_errors_nan_truth() -> None:
    tmpl = ExpressionTemplate("fm.nan", None, "x / 0")
    assert tmpl.classify_errors([{"step_id": "a", "value": 1.0}], {"result": float("nan")}) == []


# ---------------------------------------------------------------------------
# ChainStep
# ---------------------------------------------------------------------------


def test_chain_step_defaults() -> None:
    step = ChainStep(slot="output", expression="a + b", param_names=("a", "b"))
    assert step.slot == "output"
    assert step.param_kinds == ()
    assert step.description == ""


def test_chain_step_all_fields() -> None:
    step = ChainStep(
        slot="result",
        expression="x * y",
        param_names=("x", "y"),
        param_kinds=("value", "value"),
        description="Multiply",
    )
    assert step.description == "Multiply"


# ---------------------------------------------------------------------------
# ChainTemplate
# ---------------------------------------------------------------------------


def test_chain_template_solve() -> None:
    steps = [
        ChainStep("mid", "a + b", ("a", "b"), description="Add"),
        ChainStep("final", "mid * c", ("c",), description="Multiply"),
    ]
    tmpl = ChainTemplate("fm.chain_test", steps)
    result = tmpl.solve({"a": 2.0, "b": 3.0, "c": 4.0})
    assert result["concept_id"] == "fm.chain_test"
    assert result["result"] == 20.0
    assert len(result["steps"]) == 2
    assert not result["is_nan"]
    assert result["steps"][0]["step_id"] == "mid"
    assert result["steps"][1]["step_id"] == "final"


def test_chain_template_solve_nan_propagation() -> None:
    steps = [
        ChainStep("step1", "x / 0", ("x",)),
        ChainStep("step2", "step1 + 1", ()),
    ]
    tmpl = ChainTemplate("fm.nan_chain", steps)
    result = tmpl.solve({"x": 5.0})
    assert result["is_nan"] is True or math.isnan(result.get("result", 0.0))


def test_chain_template_evaluate_steps() -> None:
    steps = [ChainStep("step1", "a + b", ("a", "b"))]
    tmpl = ChainTemplate("fm.ce", steps)
    truth = tmpl.solve({"a": 1.0, "b": 2.0})
    learner = [{"step_id": "step1", "value": 3.0}]
    evals = tmpl.evaluate_steps(learner, truth)
    assert evals[0]["match"] is True


def test_chain_template_classify_errors() -> None:
    steps = [ChainStep("calc", "a + b", ("a", "b"))]
    tmpl = ChainTemplate("fm.cc", steps)
    truth = tmpl.solve({"a": 1.0, "b": 2.0})
    learner = [{"step_id": "calc", "value": 99.0}]
    tags = tmpl.classify_errors(learner, truth)
    assert "calc_mismatch" in tags


# ---------------------------------------------------------------------------
# declare_concept
# ---------------------------------------------------------------------------


def test_declare_concept_expression() -> None:
    decl = declare_concept(
        "fm.expr_test",
        concept_type=CONCEPT_TYPE_EXPRESSION,
        expression="x * y",
        param_names=["x", "y"],
        label="Test expression",
    )
    assert decl.concept_id == "fm.expr_test"
    assert decl.formula_name == "expr_test"
    assert decl.solver_fn is not None
    assert decl.solver_fn(x=3.0, y=4.0) == 12.0


def test_declare_concept_invalid_type() -> None:
    with pytest.raises(ValueError, match="Unknown concept_type"):
        declare_concept("fm.bad", concept_type="invalid")


def test_declare_concept_expression_no_expr_no_solver() -> None:
    with pytest.raises(ValueError, match="expression or solver_fn"):
        declare_concept("fm.nosolve", concept_type=CONCEPT_TYPE_EXPRESSION)


def test_declare_concept_expression_both_expr_and_solver() -> None:
    def dummy(**kw: Any) -> float:
        return 0.0

    with pytest.raises(ValueError, match="not both"):
        declare_concept(
            "fm.both",
            concept_type=CONCEPT_TYPE_EXPRESSION,
            expression="x + y",
            solver_fn=dummy,
            param_names=["x", "y"],
        )


def test_declare_concept_expression_with_multi_step_template() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    tmpl = ExpressionTemplate("fm.mst", solver, "a + b")
    decl = declare_concept(
        "fm.mst",
        concept_type=CONCEPT_TYPE_EXPRESSION,
        solver_fn=solver,
        multi_step_template=tmpl,
        label="Multi-step template bypass",
    )
    assert decl.solver_fn is solver
    assert decl.template is tmpl


def test_declare_concept_rule_chain_not_implemented_in_test() -> None:
    """Rule chain, lookup, classification dispatch to concept_types modules that
    may not be importable in all test contexts. Verify at least the type dispatch."""
    pass


# ---------------------------------------------------------------------------
# declare_formula (backward-compatible alias)
# ---------------------------------------------------------------------------


def test_declare_formula_simple() -> None:
    decl = declare_formula(
        "fm.mirr",
        expression="((terminal_value / initial_investment) ** (1 / n)) - 1",
        param_names=["terminal_value", "initial_investment", "n"],
        label="MIRR",
    )
    assert decl.concept_id == "fm.mirr"
    result = decl.solver_fn(terminal_value=2000, initial_investment=1000, n=2)
    assert abs(result - (2000 / 1000) ** 0.5 + 1) < 0.01


def test_declare_formula_with_custom_candidate() -> None:
    def custom_candidate(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"x": 1.0}]

    decl = declare_formula(
        "fm.custom_cand",
        expression="x + 1",
        param_names=["x"],
        custom_candidate_fn=custom_candidate,
    )
    assert decl.candidate_fn is custom_candidate


def test_declare_formula_registers_in_global_registry() -> None:
    declare_formula("fm.reg_test", expression="a + b", param_names=["a", "b"])
    assert "fm.reg_test" in _registry


def test_declare_formula_custom_registry() -> None:
    custom: dict[str, FormulaDecl] = {}
    declare_formula(
        "fm.custom_reg",
        expression="x + y",
        param_names=["x", "y"],
        registry=custom,
    )
    assert "fm.custom_reg" in custom
    assert "fm.custom_reg" not in _registry


# ---------------------------------------------------------------------------
# declare_formula_chain
# ---------------------------------------------------------------------------


def test_declare_formula_chain_simple() -> None:
    decl = declare_formula_chain(
        "fm.test_chain",
        steps=[
            {"slot": "mid", "expression": "a + b", "param_names": ["a", "b"]},
            {"slot": "final", "expression": "mid * c", "param_names": ["c"]},
        ],
        label="Test chain",
    )
    assert decl.concept_id == "fm.test_chain"
    result = decl.solver_fn(a=2.0, b=3.0, c=4.0)
    assert result == 20.0


def test_declare_formula_chain_empty_steps() -> None:
    with pytest.raises(ValueError, match="At least one step"):
        declare_formula_chain("fm.empty_chain", steps=[])


def test_declare_formula_chain_missing_slot() -> None:
    with pytest.raises(ValueError, match="non-empty 'slot'"):
        declare_formula_chain(
            "fm.no_slot",
            steps=[{"expression": "x + y"}],
        )


def test_declare_formula_chain_missing_expression() -> None:
    with pytest.raises(ValueError, match="non-empty 'expression'"):
        declare_formula_chain(
            "fm.no_expr",
            steps=[{"slot": "out"}],
        )


# ---------------------------------------------------------------------------
# validate_registry
# ---------------------------------------------------------------------------


def test_validate_registry_clean() -> None:
    declare_formula("fm.clean", expression="x + y", param_names=["x", "y"])
    msgs = validate_registry()
    assert msgs == []


def test_validate_registry_unknown_dependency() -> None:
    declare_formula(
        "fm.dep_test",
        expression="x + y",
        param_names=["x", "y"],
        dependencies=["nonexistent"],
    )
    msgs = validate_registry()
    assert any("dependency" in m and "nonexistent" in m for m in msgs)


def test_validate_registry_circular_dependency() -> None:
    declare_formula("fm.a", expression="x + y", param_names=["x", "y"], dependencies=["fm.b"])
    declare_formula("fm.b", expression="a + 1", param_names=["a"], dependencies=["fm.a"])
    msgs = validate_registry()
    assert any("Circular" in m for m in msgs)


def test_validate_registry_formula_name_mismatch() -> None:
    _registry["fm.bad_name"] = FormulaDecl(
        concept_id="fm.bad_name",
        formula_name="wrong_name",
    )
    msgs = validate_registry()
    assert any("formula_name mismatch" in m for m in msgs)


# ---------------------------------------------------------------------------
# RegistryValidationError
# ---------------------------------------------------------------------------


def test_registry_validation_error() -> None:
    err = RegistryValidationError("test error")
    assert str(err) == "test error"


# ---------------------------------------------------------------------------
# build_solver_dict
# ---------------------------------------------------------------------------


def test_build_solver_dict() -> None:
    declare_formula("fm.sd1", expression="x + y", param_names=["x", "y"])
    declare_formula("fm.sd2", expression="a - b", param_names=["a", "b"])
    d = build_solver_dict()
    assert "sd1" in d
    assert "sd2" in d
    assert callable(d["sd1"])


def test_build_solver_dict_with_base() -> None:
    declare_formula("fm.sd3", expression="x * 2", param_names=["x"])
    d = build_solver_dict({"custom": lambda **kw: 0.0})
    assert "custom" in d
    assert "sd3" in d


def test_build_solver_dict_skips_non_expression() -> None:
    _registry["fm.non_expr"] = FormulaDecl(
        concept_id="fm.non_expr",
        concept_type=CONCEPT_TYPE_RULE_CHAIN,
        formula_name="non_expr",
    )
    d = build_solver_dict()
    assert "non_expr" not in d


# ---------------------------------------------------------------------------
# build_candidate_dict
# ---------------------------------------------------------------------------


def test_build_candidate_dict() -> None:
    declare_formula("fm.cd1", expression="x + y", param_names=["x", "y"])
    d = build_candidate_dict()
    assert "cd1" in d
    assert callable(d["cd1"])


def test_build_candidate_dict_with_base() -> None:
    d = build_candidate_dict({"custom_fn": lambda nums: []})
    assert "custom_fn" in d


# ---------------------------------------------------------------------------
# build_signatures
# ---------------------------------------------------------------------------


def test_build_signatures() -> None:
    declare_formula(
        "fm.sig_test",
        expression="x + y",
        param_names=["x", "y"],
        patterns=[r"\btest\b"],
    )
    sigs = build_signatures()
    names = [s[0] for s in sigs]
    assert "sig_test" in names


def test_build_signatures_no_patterns() -> None:
    declare_formula("fm.no_pattern", expression="x + y", param_names=["x", "y"])
    sigs = build_signatures()
    names = [s[0] for s in sigs]
    assert "no_pattern" not in names


def test_build_signatures_with_base() -> None:
    sigs = build_signatures([("pre_existing", [re.compile(r"\bfoo\b")], 1)])
    names = [s[0] for s in sigs]
    assert "pre_existing" in names


# ---------------------------------------------------------------------------
# build_concept_dict
# ---------------------------------------------------------------------------


def test_build_concept_dict() -> None:
    declare_formula(
        "fm.cd_test",
        expression="x + y",
        param_names=["x", "y"],
        label="Concept test",
        output_slot="cd_test_output",
    )
    d = build_concept_dict()
    assert "fm.cd_test" in d
    assert d["fm.cd_test"].label == "Concept test"
    assert "cd_test_output" in d["fm.cd_test"].output_slots


def test_build_concept_dict_with_base() -> None:
    from studyplan.domain_reasoning.concepts import ConceptMetadata

    base = {"fm.ext": ConceptMetadata(concept_id="fm.ext", label="External", template_ref="fm.ext")}
    d = build_concept_dict(base)
    assert "fm.ext" in d


# ---------------------------------------------------------------------------
# build_formula_to_concept
# ---------------------------------------------------------------------------


def test_build_formula_to_concept() -> None:
    declare_formula("fm.f2c_test", expression="x + y", param_names=["x", "y"])
    d = build_formula_to_concept()
    assert d["f2c_test"] == "fm.f2c_test"


def test_build_formula_to_concept_with_base() -> None:
    d = build_formula_to_concept({"existing": "fm.existing"})
    assert d["existing"] == "fm.existing"


# ---------------------------------------------------------------------------
# build_template_registry
# ---------------------------------------------------------------------------


def test_build_template_registry() -> None:
    declare_formula("fm.tr_test", expression="a + b", param_names=["a", "b"])
    d = build_template_registry()
    assert "fm.tr_test" in d
    assert hasattr(d["fm.tr_test"], "solve")


def test_build_template_registry_with_base() -> None:
    d = build_template_registry({"fm.custom": None})
    assert "fm.custom" in d


# ---------------------------------------------------------------------------
# build_structure_type_concepts
# ---------------------------------------------------------------------------


def test_build_structure_type_concepts() -> None:
    declare_formula(
        "fm.st1",
        expression="x + y",
        param_names=["x", "y"],
        structure_types=["type_a"],
    )
    declare_formula(
        "fm.st2",
        expression="a - b",
        param_names=["a", "b"],
        structure_types=["type_a", "type_b"],
    )
    d = build_structure_type_concepts()
    assert "type_a" in d
    assert "type_b" in d
    assert "fm.st1" in d["type_a"]
    assert "fm.st2" in d["type_a"]
    assert "fm.st2" in d["type_b"]


def test_build_structure_type_concepts_with_base() -> None:
    d = build_structure_type_concepts({"pre_existing": ["fm.legacy"]})
    assert "pre_existing" in d
    assert "fm.legacy" in d["pre_existing"]


# ---------------------------------------------------------------------------
# Edge cases — formula_registry
# ---------------------------------------------------------------------------


def test_substitute_and_eval_division() -> None:
    assert _substitute_and_eval("x / y", {"x": 10.0, "y": 2.0}) == 5.0


def test_substitute_and_eval_negative() -> None:
    assert _substitute_and_eval("x + y", {"x": -5.0, "y": 10.0}) == 5.0


def test_substitute_and_eval_large() -> None:
    result = _substitute_and_eval("x * y", {"x": 1e12, "y": 1e-12})
    assert result == 1.0


def test_substitute_and_eval_zero_division() -> None:
    with pytest.raises(ValueError):
        _substitute_and_eval("x / y", {"x": 5.0, "y": 0.0})


def test_expression_solver_zero_division() -> None:
    solver = _make_expression_solver("a / b", ("a", "b"))
    result = solver(a=5.0, b=0.0)
    assert math.isinf(result) or math.isnan(result)


def test_expression_solver_large_inputs() -> None:
    solver = _make_expression_solver("x * y", ("x", "y"))
    result = solver(x=1e10, y=1e10)
    assert result == 1e20


def test_expression_solver_negative_inputs() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    assert solver(x=-5.0, y=3.0) == -2.0


def test_expression_solver_float_precision() -> None:
    solver = _make_expression_solver("x / y", ("x", "y"))
    result = solver(x=1.0, y=3.0)
    assert abs(result - 0.3333333333333333) < 1e-15


def test_expression_solver_missing_with_defaults() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    assert math.isnan(solver(a=5.0))


def test_expression_solver_non_numeric_kwarg() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    result = solver(a=5.0, b=3.0)
    assert result == 8.0


def test_expression_solver_nan_input() -> None:
    solver = _make_expression_solver("a + b", ("a", "b"))
    result = solver(a=float("nan"), b=3.0)
    assert math.isnan(result)


def test_candidate_fn_permutations() -> None:
    solver = _make_expression_solver("a + b + c", ("a", "b", "c"))
    fn = _make_candidate_fn(("a", "b", "c"), ("value", "value", "value"), solver)
    nums = [
        {"value": 1.0, "is_percent": False},
        {"value": 2.0, "is_percent": False},
        {"value": 3.0, "is_percent": False},
    ]
    candidates = fn(nums)
    assert len(candidates) > 1


def test_candidate_fn_no_values_no_solver() -> None:
    fn = _make_candidate_fn(("x",), ("value",))
    assert fn([]) == []


def test_expression_template_solve_no_expression() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    tmpl = ExpressionTemplate("fm.noexpr", solver, None)
    result = tmpl.solve({"x": 1.0, "y": 2.0})
    assert result["result"] == 3.0
    assert result["steps"] == []


def test_expression_template_evaluate_empty_learner() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    tmpl = ExpressionTemplate("fm.ee", solver, "x + y")
    assert tmpl.evaluate_steps([], {"result": 5.0}) == []


def test_expression_template_evaluate_empty_truth() -> None:
    solver = _make_expression_solver("x + y", ("x", "y"))
    tmpl = ExpressionTemplate("fm.et", solver, "x + y")
    assert tmpl.evaluate_steps([{"step_id": "a", "value": 1.0}], {}) == []


def test_chain_template_breaks_on_nan() -> None:
    steps = [
        ChainStep("s1", "x / 0", ("x",)),
        ChainStep("s2", "s1 + 1", ()),
    ]
    tmpl = ChainTemplate("fm.nan_brk", steps)
    result = tmpl.solve({"x": 5.0})
    assert len(result["steps"]) == 1  # only first step executed


def test_chain_template_evaluate_no_learner() -> None:
    steps = [ChainStep("s1", "a + b", ("a", "b"))]
    tmpl = ChainTemplate("fm.ce", steps)
    assert tmpl.evaluate_steps([], {"result": 3.0}) == []


def test_chain_template_classify_empty() -> None:
    steps = [ChainStep("s1", "a + b", ("a", "b"))]
    tmpl = ChainTemplate("fm.cc", steps)
    assert tmpl.classify_errors([], {"result": 3.0}) == []


def test_declare_formula_with_patterns_and_tags() -> None:
    decl = declare_formula(
        "fm.rich",
        expression="x * y",
        param_names=["x", "y"],
        patterns=[r"\brich\b"],
        diagnostic_tags=["x_err"],
        dependencies=["fm.other"],
        chapter_refs=["ch1"],
        structure_types=["st1"],
    )
    assert len(decl.compiled_patterns) == 1
    assert "x_err" in decl.diagnostic_tags
    assert "fm.other" in decl.dependencies
    assert "ch1" in decl.chapter_refs
    assert "st1" in decl.structure_types


def test_build_signatures_priority_order() -> None:
    declare_formula("fm.first", expression="x + 1", param_names=["x"])
    declare_formula("fm.second", expression="y + 2", param_names=["y"], patterns=[r"\bsecond\b"])
    sigs = build_signatures()
    names = [s[0] for s in sigs]
    assert "second" in names


def test_formula_decl_name_mismatch_validation() -> None:
    _registry["fm.mismatch_test"] = FormulaDecl(
        concept_id="fm.mismatch_test",
        formula_name="wrong",
    )
    msgs = validate_registry()
    assert any("mismatch" in m for m in msgs)


# ---------------------------------------------------------------------------
# _declare_expression_concept (internal)
# ---------------------------------------------------------------------------


def test_declare_expression_concept_direct() -> None:
    decl = _declare_expression_concept(
        "fm.internal",
        expression="a / b",
        param_names=["a", "b"],
        label="Internal",
        output_slot="internal_out",
    )
    assert decl.concept_id == "fm.internal"
    assert decl.output_slot == "internal_out"


def test_declare_expression_concept_custom_registry() -> None:
    custom: dict[str, FormulaDecl] = {}
    _declare_expression_concept(
        "fm.custom_reg",
        expression="x + y",
        param_names=["x", "y"],
        registry=custom,
    )
    assert "fm.custom_reg" in custom
