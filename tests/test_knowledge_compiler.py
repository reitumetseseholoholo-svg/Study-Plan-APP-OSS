"""Knowledge Compiler tests — structured domain, not flat graph.

Validates:
  1. FMKnowledgeBase has proper structure (chapter, formulas, pedagogical sets)
  2. Knowledge Compiler bridge produces correct TopicSpecs
  3. Domain Compiler produces valid ViewStates
  4. Teaching Planner chooses correct strategy based on mastery
  5. Full pipeline works end-to-end
"""

from studyplan.provenance.knowledge_ir import (
    FMFormula,
    FormulaParam,
    Assumption,
    FMChapter,
)
from studyplan.provenance.knowledge_base import get_knowledge_base
from studyplan.provenance.knowledge_compiler import (
    formula_to_topic_spec,
    compile_formula,
    compile_all,
)
from studyplan.provenance.compiler import DomainCompiler
from studyplan.provenance.kernel import ViewState


class TestKnowledgeIR:
    """Structured IR types are well-formed."""

    def test_formula_has_all_fields(self):
        f = FMFormula(
            concept_id="fm.test",
            label="Test",
            description="A test formula",
            expression="a + b",
            params=(FormulaParam("a", "value", "input_a"), FormulaParam("b", "percent", "input_b")),
            output_concept_id="fm.test",
            assumes=(Assumption("const", "constant rate"),),
            dependencies=("fm.prereq",),
            diagnostic_tags=("error_a",),
            centrality=0.5,
            source_ids=("src_a",),
        )
        assert f.concept_id == "fm.test"
        assert len(f.params) == 2
        assert len(f.assumes) == 1
        assert "fm.prereq" in f.dependencies

    def test_kb_has_structure(self):
        kb = get_knowledge_base()
        assert isinstance(kb.chapter, FMChapter)
        assert kb.chapter.id == "investment_appraisal"
        assert len(kb.formulas) >= 5
        assert len(kb.pedagogical) >= 5
        assert len(kb.sources) >= 3

    def test_pedagogical_set_has_grouped_artifacts(self):
        kb = get_knowledge_base()
        ped = kb.pedagogical_for("fm.npv")
        assert ped is not None
        assert len(ped.definitions) == 1
        assert len(ped.worked_examples) == 1
        assert len(ped.misconceptions) == 1

    def test_source_is_first_class(self):
        kb = get_knowledge_base()
        src = kb.source("src_study_text")
        assert src is not None
        assert src.kind == "study_text"
        assert src.authority > 0.5


class TestKnowledgeBase:
    """FMKnowledgeBase content is correct."""

    def test_core_formulas_exist(self):
        kb = get_knowledge_base()
        for cid in (
            "fm.npv",
            "fm.payback",
            "fm.irr",
            "fm.arr",
            "fm.profitability_index",
            "fm.discounted_payback",
            "fm.perpetuity_npv",
            "fm.equivalent_annual_cost",
        ):
            assert kb.formula_for(cid) is not None, f"Missing formula: {cid}"

    def test_npv_formula_structure(self):
        kb = get_knowledge_base()
        npv = kb.formula_for("fm.npv")
        assert npv is not None
        assert len(npv.params) == 3
        assert npv.params[1].role == "discount_rate"
        assert "constant_discount_rate" in [a.condition for a in npv.assumes]

    def test_irr_depends_on_npv(self):
        kb = get_knowledge_base()
        irr = kb.formula_for("fm.irr")
        assert irr is not None
        assert "fm.npv" in irr.dependencies

    def test_pedagogical_content_links_to_sources(self):
        kb = get_knowledge_base()
        ped = kb.pedagogical_for("fm.npv")
        assert ped is not None
        for defn in ped.definitions:
            assert kb.source(defn.source_id) is not None, f"Missing source: {defn.source_id}"

    def test_learning_objectives_exist(self):
        kb = get_knowledge_base()
        assert len(kb.chapter.learning_objectives) >= 5


class TestKnowledgeCompiler:
    """Formula → TopicSpec bridge."""

    def test_formula_to_topic_spec(self):
        kb = get_knowledge_base()
        npv = kb.formula_for("fm.npv")
        assert npv is not None
        spec = formula_to_topic_spec(npv)
        assert spec.id == "fm.npv"
        assert len(spec.parameters) == 3
        assert len(spec.computations) == 1
        assert len(spec.outputs) == 1
        assert "constant_discount_rate" in spec.computations[0].assumptions

    def test_compile_formula_to_viewstate(self):
        result = compile_formula(get_knowledge_base(), "fm.npv")
        assert result is not None
        spec, vs = result
        assert isinstance(vs, ViewState)

    def test_compile_all(self):
        results = compile_all(get_knowledge_base())
        assert len(results) >= 5
        for cid, spec in results:
            assert spec.id == cid

    def test_npv_viewstate_has_all_params(self):
        result = compile_formula(get_knowledge_base(), "fm.npv")
        assert result is not None
        spec, vs = result
        # 3 params + 1 output = 4 artifacts
        assert len(vs.artifact_space) == 4
        artifact_ids = {a.id for a in vs.artifact_space}
        assert "param_initial" in artifact_ids
        assert "param_r" in artifact_ids
        assert "param_cashflows" in artifact_ids
        assert "npv" in artifact_ids

    def test_irr_viewstate_includes_assumptions(self):
        result = compile_formula(get_knowledge_base(), "fm.irr")
        assert result is not None
        spec, vs = result
        comp = spec.computations[0]
        assert "single_irr" in comp.assumptions
        assert "periodic_cash_flows" in comp.assumptions


class TestTeachingPlanner:
    """Teaching Planner chooses strategies correctly."""

    def test_strategy_introduce_when_no_mastery(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, Strategy

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan("fm.npv", mastery={})

        assert plan.strategy == Strategy.REMEDIATE  # 0 mastery → remediate

    def test_strategy_introduce_when_partial_mastery(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, Strategy

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan(
            "fm.npv",
            mastery={
                "fm.npv": 0.4,
            },
        )

        assert plan.strategy == Strategy.INTRODUCE

    def test_strategy_reinforce_when_good_mastery(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, Strategy

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan(
            "fm.npv",
            mastery={
                "fm.npv": 0.7,
            },
        )

        assert plan.strategy == Strategy.REINFORCE

    def test_strategy_extend_when_high_mastery(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, Strategy

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan(
            "fm.npv",
            mastery={
                "fm.npv": 0.9,
            },
        )

        assert plan.strategy == Strategy.EXTEND

    def test_remediate_prereq_first(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, Strategy

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        # IRR depends on NPV. If NPV is weak, remediate it first.
        plan = planner.plan(
            "fm.irr",
            mastery={
                "fm.npv": 0.3,
            },
        )

        assert plan.strategy == Strategy.REMEDIATE
        assert "fm.npv" in plan.weak_prerequisites
        # Remediation steps should include NPV
        npv_steps = [s for s in plan.steps if "Net Present Value" in s.rationale]
        assert len(npv_steps) > 0

    def test_introduce_has_define_illustrate_test(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, Move

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan("fm.npv", mastery={"fm.npv": 0.4})

        step_moves = [s.move for s in plan.steps]
        assert Move.DEFINE in step_moves
        assert Move.ILLUSTRATE in step_moves
        assert Move.TEST in step_moves

    def test_reinforce_tests_first(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, Move

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan("fm.npv", mastery={"fm.npv": 0.7})

        assert plan.steps[0].move == Move.TEST  # Reinforce always tests first

    def test_all_steps_have_valid_artifacts(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan("fm.npv", mastery={"fm.npv": 0.4})

        for step in plan.steps:
            if step.artifact is not None:
                assert step.artifact.id
                assert step.artifact.content

    def test_format_plan_renders(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner, format_plan

        kb = get_knowledge_base()
        planner = TeachingPlanner(kb)
        plan = planner.plan("fm.npv", mastery={"fm.npv": 0.4})
        rendered = format_plan(plan)

        assert "Objective:" in rendered
        assert "Strategy:" in rendered
        assert "introduce" in rendered


class TestEndToEnd:
    """Full pipeline: KB → ViewState → Teaching Plan."""

    def test_kb_to_viewstate_to_plan(self):
        from studyplan.provenance.teaching_planner import TeachingPlanner

        kb = get_knowledge_base()

        # Compile
        result = compile_formula(kb, "fm.npv")
        assert result is not None
        spec, vs = result
        assert isinstance(vs, ViewState)

        # Plan
        planner = TeachingPlanner(kb)
        plan = planner.plan("fm.npv", mastery={"fm.npv": 0.4})
        assert plan.strategy.value == "introduce"
        assert len(plan.steps) >= 3

        # Every artifact in the plan exists in the KB
        for step in plan.steps:
            if step.artifact:
                ped = kb.pedagogical_for("fm.npv")
                assert ped is not None

    def test_all_formulas_compile(self):
        kb = get_knowledge_base()
        compiler = DomainCompiler()
        for cid in kb.formulas:
            spec = formula_to_topic_spec(kb.formulas[cid])
            vs = compiler.compile(spec)
            assert isinstance(vs, ViewState)
            assert len(vs.artifact_space) >= 2

    def test_pipeline_no_runtime_imports(self):
        kb = get_knowledge_base()
        result = compile_formula(kb, "fm.npv")
        assert result is not None
        spec, vs = result
        assert isinstance(vs, ViewState)
