"""Tests for domain-reasoning-prescribed question generation.

Covers _build_concept_generation_context, _domain_correct_generated_questions,
_check_distractor_coverage, _domain_verify_section_c_question, and prompt injection.
"""

import types


from studyplan_app import AI_TUTOR_GAP_GENERATION_DEFAULT_QUESTIONS, StudyPlanGUI

# ===================================================================
# _build_concept_generation_context
# ===================================================================


class TestBuildConceptGenerationContext:
    def test_returns_weak_concepts_as_required(self):
        dummy = types.SimpleNamespace()
        cids = ["fm.npv", "fm.wacc"]
        ctx = StudyPlanGUI._build_concept_generation_context(dummy, "", cids)
        assert len(ctx) >= 2
        npv = [e for e in ctx if e["concept_id"] == "fm.npv"]
        assert len(npv) == 1
        assert npv[0]["required"] is True
        assert npv[0]["label"] == "Net present value"
        assert "sign_error" in npv[0]["error_patterns"]

    def test_no_duplicates(self):
        dummy = types.SimpleNamespace()
        ctx = StudyPlanGUI._build_concept_generation_context(dummy, "", ["fm.npv", "fm.npv", "fm.capm"])
        ids = [e["concept_id"] for e in ctx]
        assert len(ids) == len(set(ids))
        assert ids.count("fm.npv") == 1

    def test_unknown_concept_returns_label_as_cid(self):
        dummy = types.SimpleNamespace()
        ctx = StudyPlanGUI._build_concept_generation_context(dummy, "", ["unknown.xyz"])
        assert any(e["concept_id"] == "unknown.xyz" for e in ctx)
        entry = [e for e in ctx if e["concept_id"] == "unknown.xyz"][0]
        assert entry["label"] == "unknown.xyz"
        assert entry["error_patterns"] == []

    def test_includes_chapter_concepts_as_non_required(self):
        dummy = types.SimpleNamespace()
        ctx = StudyPlanGUI._build_concept_generation_context(dummy, "cost_of_capital", [])
        capm_ids = [e["concept_id"] for e in ctx if e["concept_id"] in ("fm.capm", "fm.wacc") and not e["required"]]
        assert len(capm_ids) >= 2, f"expected cost_of_capital chapter concepts, got {[e['concept_id'] for e in ctx]}"

    def test_weak_concepts_stay_required_when_chapter_also_present(self):
        dummy = types.SimpleNamespace()
        ctx = StudyPlanGUI._build_concept_generation_context(dummy, "cost_of_capital", ["fm.npv"])
        npv = [e for e in ctx if e["concept_id"] == "fm.npv"]
        assert len(npv) == 1
        assert npv[0]["required"] is True
        capm_or_wacc = [e for e in ctx if e["concept_id"] in ("fm.capm", "fm.wacc")]
        assert len(capm_or_wacc) >= 1
        for e in capm_or_wacc:
            assert e["required"] is False

    def test_expression_formula_included_when_available(self):
        dummy = types.SimpleNamespace()
        ctx = StudyPlanGUI._build_concept_generation_context(dummy, "", ["fm.npv"])
        npv = [e for e in ctx if e["concept_id"] == "fm.npv"][0]
        assert isinstance(npv["formula_expression"], str)

    def test_empty_input_returns_empty(self):
        dummy = types.SimpleNamespace()
        ctx = StudyPlanGUI._build_concept_generation_context(dummy, "", [])
        assert ctx == []


# ===================================================================
# _check_distractor_coverage
# ===================================================================


class TestCheckDistractorCoverage:
    def test_returns_empty_when_no_concepts_match_chapter(self):
        dummy = types.SimpleNamespace()
        result = StudyPlanGUI._check_distractor_coverage(
            dummy, "non_existent_chapter", ["opt A", "opt B", "opt C", "opt D"], "opt A"
        )
        assert result == {}

    def test_returns_metadata_when_concepts_match(self):
        dummy = types.SimpleNamespace()
        options = [
            "Net present value of $12,500",
            "Sign error — negative NPV of -$12,500",
            "Incorrect discount rate applied",
            "Initial investment omitted",
        ]
        result = StudyPlanGUI._check_distractor_coverage(dummy, "investment_appraisal", options, options[0])
        assert isinstance(result, dict)
        assert "total_patterns" in result
        assert "coverage_pct" in result
        assert result["total_patterns"] > 0

    def test_no_options_returns_empty(self):
        dummy = types.SimpleNamespace()
        result = StudyPlanGUI._check_distractor_coverage(dummy, "investment_appraisal", [], "")
        assert result == {}

    def test_all_options_correct_returns_empty(self):
        dummy = types.SimpleNamespace()
        result = StudyPlanGUI._check_distractor_coverage(dummy, "investment_appraisal", ["same"], "same")
        assert result == {}


# ===================================================================
# _domain_correct_generated_questions
# ===================================================================


class FakeConceptEvaluation:
    """Minimal stand-in for ConceptEvaluation dataclass."""

    def __init__(self, result=None, is_nan=False, error_tags=None, confidence=0.0):
        self.result = result
        self.is_nan = is_nan
        self.error_tags = error_tags or []
        self.confidence = confidence


class FakeQuestionDiagnostic:
    """Minimal stand-in for QuestionDiagnostic dataclass."""

    def __init__(
        self,
        has_deterministic_truth=False,
        diagnostic_confidence=0.0,
        all_error_tags=None,
        concept_evaluations=None,
        primary_concept_id="",
    ):
        self.has_deterministic_truth = has_deterministic_truth
        self.diagnostic_confidence = diagnostic_confidence
        self.all_error_tags = all_error_tags or []
        self.concept_evaluations = concept_evaluations or []
        self.primary_concept_id = primary_concept_id


class TestDomainCorrectGeneratedQuestions:
    def test_no_questions_returns_unchanged(self):
        dummy = types.SimpleNamespace(engine=types.SimpleNamespace())
        result = StudyPlanGUI._domain_correct_generated_questions(dummy, "Topic A", [])
        assert result == []

    def test_no_engine_returns_unchanged(self):
        dummy = types.SimpleNamespace(engine=None)
        q = [{"question": "Q?", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": "E."}]
        result = StudyPlanGUI._domain_correct_generated_questions(dummy, "Topic A", q)
        assert result == q

    def test_corrects_wrong_answer_when_domain_computed_differs(self, monkeypatch):
        diag = FakeQuestionDiagnostic(
            has_deterministic_truth=True,
            diagnostic_confidence=0.9,
            all_error_tags=["npv_mismatch"],
            concept_evaluations=[FakeConceptEvaluation(result=12500.0)],
            primary_concept_id="fm.npv",
        )
        monkeypatch.setattr(
            "studyplan.domain_reasoning.evaluate_question",
            lambda *a, **kw: diag,
        )
        dummy = types.SimpleNamespace(
            engine=types.SimpleNamespace(),
            _ai_tutor_autopilot_stats={},
        )
        questions = [
            {
                "question": "Calculate the NPV given cashflows.",
                "options": ["$12,500", "$11,000", "$13,200", "$14,800"],
                "correct": "$11,000",
                "explanation": "NPV computed from discounted cashflows.",
            }
        ]
        result = StudyPlanGUI._domain_correct_generated_questions(dummy, "Topic A", questions)
        assert len(result) == 1
        assert result[0]["correct"] == "$12,500"

    def test_tracks_stats_when_correction_made(self, monkeypatch):
        diag = FakeQuestionDiagnostic(
            has_deterministic_truth=True,
            diagnostic_confidence=0.9,
            all_error_tags=["npv_mismatch"],
            concept_evaluations=[FakeConceptEvaluation(result=12500.0)],
            primary_concept_id="fm.npv",
        )
        monkeypatch.setattr(
            "studyplan.domain_reasoning.evaluate_question",
            lambda *a, **kw: diag,
        )
        dummy = types.SimpleNamespace(
            engine=types.SimpleNamespace(),
            _ai_tutor_autopilot_stats={},
        )
        questions = [
            {
                "question": "Calculate the NPV.",
                "options": ["$12,500", "$11,000", "$13,200", "$14,800"],
                "correct": "$11,000",
                "explanation": "NPV computed.",
            }
        ]
        StudyPlanGUI._domain_correct_generated_questions(dummy, "Topic A", questions)
        stats = getattr(dummy, "_ai_tutor_autopilot_stats", {})
        assert stats.get("domain_corrected_count", 0) == 1
        assert stats.get("domain_corrected_by_concept", {}).get("fm.npv", 0) == 1

    def test_leaves_correct_answer_unchanged_when_no_mismatch(self, monkeypatch):
        diag = FakeQuestionDiagnostic(
            has_deterministic_truth=True,
            diagnostic_confidence=0.9,
            all_error_tags=[],
            concept_evaluations=[FakeConceptEvaluation(result=12500.0)],
        )
        monkeypatch.setattr(
            "studyplan.domain_reasoning.evaluate_question",
            lambda *a, **kw: diag,
        )
        dummy = types.SimpleNamespace(
            engine=types.SimpleNamespace(),
            _ai_tutor_autopilot_stats={},
        )
        questions = [
            {
                "question": "Calculate the NPV.",
                "options": ["$12,500", "$11,000", "$13,200", "$14,800"],
                "correct": "$12,500",
                "explanation": "Correct.",
            }
        ]
        result = StudyPlanGUI._domain_correct_generated_questions(dummy, "Topic A", questions)
        assert result[0]["correct"] == "$12,500"


# ===================================================================
# _domain_verify_section_c_question
# ===================================================================


class TestDomainVerifySectionCQuestion:
    def test_non_dict_returns_unchanged(self):
        dummy = types.SimpleNamespace(engine=types.SimpleNamespace())
        result = StudyPlanGUI._domain_verify_section_c_question(dummy, "Topic A", None)
        assert result is None

    def test_no_engine_returns_unchanged(self):
        dummy = types.SimpleNamespace(engine=None)
        q = {"scenario": "Test.", "requirements": [], "model_answer_outline": []}
        result = StudyPlanGUI._domain_verify_section_c_question(dummy, "Topic A", q)
        assert result is q

    def test_annotates_verified_false_when_short_text(self):
        dummy = types.SimpleNamespace(engine=types.SimpleNamespace())
        q = {"scenario": "Hi", "requirements": [], "model_answer_outline": []}
        result = StudyPlanGUI._domain_verify_section_c_question(dummy, "Topic A", q)
        assert result["_domain_verified"] is False


# ===================================================================
# Prompt injection tests
# ===================================================================


class TestGapGenerationPromptWithContext:
    def _make_prompt_dummy(self, **overrides):
        dummy = types.SimpleNamespace(
            module_title="FM",
            module_id="acca_fm",
            current_topic="Topic A",
            _ai_tutor_autopilot_stats={},
        )
        dummy._build_concept_generation_context = types.MethodType(
            StudyPlanGUI._build_concept_generation_context, dummy
        )
        for k, v in overrides.items():
            setattr(dummy, k, v)
        return dummy

    def test_payload_includes_concept_formulas_when_weak_cids_present(self):
        dummy = self._make_prompt_dummy()
        snapshot = {
            "weak_concept_ids_top": ["fm.npv", "fm.capm"],
            "weak_topics_top3": [],
            "risk_snapshot_top3": [],
            "learning_context": "",
            "concept_error_summary": [],
        }
        prompt = StudyPlanGUI._build_gap_generation_prompt(
            dummy, "investment_appraisal", AI_TUTOR_GAP_GENERATION_DEFAULT_QUESTIONS, snapshot=snapshot
        )
        assert "concept_formulas" in prompt
        assert "fm.npv" in prompt
        assert "Net present value" in prompt

    def test_payload_includes_chapter_concepts_when_no_weak_cids(self):
        dummy = self._make_prompt_dummy()
        snapshot = {
            "weak_concept_ids_top": [],
            "weak_topics_top3": [],
            "risk_snapshot_top3": [],
            "learning_context": "",
            "concept_error_summary": [],
        }
        prompt = StudyPlanGUI._build_gap_generation_prompt(
            dummy, "cost_of_capital", AI_TUTOR_GAP_GENERATION_DEFAULT_QUESTIONS, snapshot=snapshot
        )
        assert "concept_formulas" in prompt
        assert "fm.capm" in prompt or "fm.wacc" in prompt

    def test_includes_correction_history_when_available(self):
        dummy = self._make_prompt_dummy(
            _ai_tutor_autopilot_stats={
                "domain_corrected_count": 3,
                "domain_corrected_by_concept": {"fm.npv": 2, "fm.wacc": 1},
            }
        )
        snapshot = {
            "weak_concept_ids_top": ["fm.npv"],
            "weak_topics_top3": [],
            "risk_snapshot_top3": [],
            "learning_context": "",
            "concept_error_summary": [],
        }
        prompt = StudyPlanGUI._build_gap_generation_prompt(
            dummy, "investment_appraisal", AI_TUTOR_GAP_GENERATION_DEFAULT_QUESTIONS, snapshot=snapshot
        )
        assert "domain_correction_history_count" in prompt
        assert "domain_correction_history_by_concept" in prompt
        assert "fm.npv (2x)" in prompt
        assert "fm.wacc (1x)" not in prompt  # wacc not in weak_cids, only npv is targeted

    def test_section_c_prompt_includes_concept_formulas(self):
        dummy = self._make_prompt_dummy()
        dummy._build_section_c_intelligence_snapshot = lambda chapter, snapshot=None: {
            "target_difficulty": "standard",
            "rubric_emphasis": "",
            "coaching_cues": [],
            "fragility_score": 0.0,
            "recent_section_c_avg_pct": 0.0,
            "recent_section_c_weakest_criterion": "",
        }
        snapshot = {
            "weak_concept_ids_top": ["fm.npv"],
            "weak_topics_top3": [],
            "must_review_due": 0,
        }
        prompt = StudyPlanGUI._build_section_c_generation_prompt(dummy, "investment_appraisal", snapshot=snapshot)
        assert "concept_formulas" in prompt
        assert "fm.npv" in prompt
