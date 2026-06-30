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


# ===================================================================
# _recover_partial_questions (partial JSON recovery)
# ===================================================================


class TestRecoverPartialQuestions:
    def test_extracts_individual_objects_from_malformed_json(self):
        text = """Here are some questions:
        {"question": "Q1?", "options": ["A","B","C","D"], "correct": "A", "explanation": "E1."}
        some garbage text
        {"question": "Q2?", "options": ["W","X","Y","Z"], "correct": "Z", "explanation": "E2."}
        """
        result = StudyPlanGUI._recover_partial_questions(text)
        assert len(result) == 2
        assert result[0]["question"] == "Q1?"
        assert result[1]["question"] == "Q2?"

    def test_empty_text_returns_empty_list(self):
        assert StudyPlanGUI._recover_partial_questions("") == []

    def test_no_valid_object_returns_empty(self):
        assert StudyPlanGUI._recover_partial_questions("Just some random text without braces") == []

    def test_skips_objects_without_question_key(self):
        text = '{"foo": "bar"} {"question": "Q?", "options": ["A","B","C","D"], "correct": "A", "explanation": "E."}'
        result = StudyPlanGUI._recover_partial_questions(text)
        assert len(result) == 1
        assert result[0]["question"] == "Q?"

    def test_deeply_nested_braces_dont_confuse_depth_tracking(self):
        text = '{"question": "Q?", "options": ["A","B","C","D"], "correct": "A", "explanation": "Nested {like this}"}'
        result = StudyPlanGUI._recover_partial_questions(text)
        assert len(result) == 1
        assert result[0]["question"] == "Q?"


# ===================================================================
# _tag_question_metadata
# ===================================================================


class TestTagQuestionMetadata:
    def test_adds_difficulty_and_concept_ids(self):
        dummy = types.SimpleNamespace()
        question = {
            "question": "Calculate the net present value given cashflows of $10k.",
            "options": ["$12,500", "$11,000", "$13,200", "$14,800"],
            "correct": "$12,500",
            "explanation": "NPV is the sum of discounted cashflows.",
        }
        tagged = StudyPlanGUI._tag_question_metadata(dummy, question, "investment_appraisal")
        assert "_difficulty" in tagged
        assert tagged["_difficulty"] in ("easy", "medium", "hard")
        assert "_concept_ids" in tagged
        assert isinstance(tagged["_concept_ids"], list)
        assert "_learning_stage" in tagged

    def test_non_formula_question_gets_recall_stage(self):
        dummy = types.SimpleNamespace()
        question = {
            "question": "What is a share?",
            "options": ["Equity", "Debt", "Cash", "Asset"],
            "correct": "Equity",
            "explanation": "A share represents equity ownership.",
        }
        tagged = StudyPlanGUI._tag_question_metadata(dummy, question, "Topic A")
        assert tagged["_learning_stage"] == "recall"
        assert tagged["_difficulty"] == "medium"

    def test_analysis_question_gets_analysis_stage(self):
        dummy = types.SimpleNamespace()
        question = {
            "question": "Compare the advantages of NPV over IRR for project appraisal.",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct": "Option A",
            "explanation": "NPV handles non-conventional cashflows better.",
        }
        tagged = StudyPlanGUI._tag_question_metadata(dummy, question, "investment_appraisal")
        assert tagged["_learning_stage"] == "analysis"

    def test_calculation_question_gets_application_stage(self):
        dummy = types.SimpleNamespace()
        question = {
            "question": "Compute the WACC using the CAPM formula.",
            "options": ["10.5%", "11.2%", "9.8%", "12.1%"],
            "correct": "10.5%",
            "explanation": "WACC = Ke*E/(E+D) + Kd*(1-T)*D/(E+D).",
        }
        tagged = StudyPlanGUI._tag_question_metadata(dummy, question, "cost_of_capital")
        assert tagged["_learning_stage"] == "application"

    def test_survives_domain_reasoning_import_failure(self, monkeypatch):
        dummy = types.SimpleNamespace()
        question = {
            "question": "Some question without domain concepts.",
            "options": ["A", "B", "C", "D"],
            "correct": "A",
            "explanation": "Explanation.",
        }
        monkeypatch.setattr("studyplan.domain_reasoning.concepts.BUILTIN_CONCEPTS", {})
        tagged = StudyPlanGUI._tag_question_metadata(dummy, question, "Topic A")
        assert tagged["_concept_ids"] == []
        assert tagged["_difficulty"] == "medium"


# ===================================================================
# _record_generation_rejection / rejection history persistence
# ===================================================================


class TestGenerationRejectionHistory:
    def test_records_and_loads_rejection_history(self, tmp_path, monkeypatch):
        import os
        from studyplan_app import Config

        config_home = str(tmp_path / ".config" / "studyplan")
        monkeypatch.setattr(Config, "CONFIG_HOME", config_home)
        path = os.path.join(config_home, "generation_rejection_history.json")

        dummy = types.SimpleNamespace()
        dummy._generation_rejection_history_path = path
        dummy._generation_rejection_history = {}
        dummy._save_generation_rejection_history = types.MethodType(
            StudyPlanGUI._save_generation_rejection_history, dummy
        )
        StudyPlanGUI._record_generation_rejection(
            dummy, ["question_too_short", "options_not_four", "question_too_short"]
        )
        assert dummy._generation_rejection_history.get("question_too_short") == 2
        assert dummy._generation_rejection_history.get("options_not_four") == 1

        # Load from disk in a new instance
        dummy2 = types.SimpleNamespace()
        dummy2._generation_rejection_history_path = path
        StudyPlanGUI._load_generation_rejection_history(dummy2)
        assert dummy2._generation_rejection_history.get("question_too_short") == 2

    def test_empty_history_when_file_missing(self):
        dummy = types.SimpleNamespace()
        dummy._generation_rejection_history_path = "/nonexistent/path.json"
        dummy._generation_rejection_history = {}
        StudyPlanGUI._load_generation_rejection_history(dummy)
        assert dummy._generation_rejection_history == {}

    def test_records_without_side_effects_when_path_not_set(self):
        dummy = types.SimpleNamespace()
        dummy._generation_rejection_history_path = ""
        dummy._generation_rejection_history = {}
        StudyPlanGUI._record_generation_rejection(dummy, ["reason_a"])

    def test_clear_increments_existing_counters(self):
        dummy = types.SimpleNamespace()
        dummy._generation_rejection_history_path = ""
        dummy._generation_rejection_history = {"existing_reason": 5}
        StudyPlanGUI._record_generation_rejection(dummy, ["existing_reason", "new_reason"])
        assert dummy._generation_rejection_history.get("existing_reason") == 6
        assert dummy._generation_rejection_history.get("new_reason") == 1


# ===================================================================
# Prompt injection: validation feedback loop
# ===================================================================


class TestGapPromptWithRejectionHistory:
    def _make_prompt_dummy(self, rejection_history=None):
        dummy = types.SimpleNamespace(
            module_title="FM",
            module_id="acca_fm",
            current_topic="Topic A",
            _ai_tutor_autopilot_stats={},
            _generation_rejection_history=rejection_history or {},
        )
        dummy._build_concept_generation_context = types.MethodType(
            StudyPlanGUI._build_concept_generation_context, dummy
        )
        return dummy

    def test_rejection_history_injected_when_present(self):
        dummy = self._make_prompt_dummy(rejection_history={"question_too_short": 3, "options_not_four": 1})
        snapshot = {
            "weak_concept_ids_top": [],
            "weak_topics_top3": [],
            "risk_snapshot_top3": [],
            "learning_context": "",
            "concept_error_summary": [],
        }
        prompt = StudyPlanGUI._build_gap_generation_prompt(
            dummy, "investment_appraisal", AI_TUTOR_GAP_GENERATION_DEFAULT_QUESTIONS, snapshot=snapshot
        )
        assert "question_too_short" in prompt
        assert "3 time(s)" in prompt
        assert "validation failures" in prompt

    def test_rejection_history_absent_when_empty(self):
        dummy = self._make_prompt_dummy(rejection_history={})
        snapshot = {
            "weak_concept_ids_top": [],
            "weak_topics_top3": [],
            "risk_snapshot_top3": [],
            "learning_context": "",
            "concept_error_summary": [],
        }
        prompt = StudyPlanGUI._build_gap_generation_prompt(
            dummy, "investment_appraisal", AI_TUTOR_GAP_GENERATION_DEFAULT_QUESTIONS, snapshot=snapshot
        )
        assert "validation failures" not in prompt

    def test_top_5_rejections_only(self):
        dummy = self._make_prompt_dummy(
            rejection_history={
                "r1": 10,
                "r2": 9,
                "r3": 8,
                "r4": 7,
                "r5": 6,
                "r6": 5,
            }
        )
        snapshot = {
            "weak_concept_ids_top": [],
            "weak_topics_top3": [],
            "risk_snapshot_top3": [],
            "learning_context": "",
            "concept_error_summary": [],
        }
        prompt = StudyPlanGUI._build_gap_generation_prompt(
            dummy, "investment_appraisal", AI_TUTOR_GAP_GENERATION_DEFAULT_QUESTIONS, snapshot=snapshot
        )
        assert "r1" in prompt
        assert "r6" not in prompt  # only top 5


# ===================================================================
# _save_generated_gap_questions — metadata tagging integration
# ===================================================================


class TestSaveGeneratedGapQuestionsTagsMetadata:
    def test_tagged_rows_passed_to_engine_add(self, monkeypatch):
        engine = types.SimpleNamespace(
            CHAPTERS=["Topic A"],
            QUESTIONS={},
            _add_questions_with_stats=lambda chapter, rows: (len(rows), {}),
            save_questions=lambda: None,
            save_data=lambda: None,
        )
        dummy = types.SimpleNamespace(
            engine=engine,
            _generation_rejection_history={},
            _generation_rejection_history_path="",
        )
        dummy._tag_question_metadata = types.MethodType(StudyPlanGUI._tag_question_metadata, dummy)
        questions = [
            {
                "question": "Calculate the WACC given cost of equity 10% and debt 5%.",
                "options": ["8.2%", "7.5%", "9.1%", "6.8%"],
                "correct": "8.2%",
                "explanation": "WACC = weighted average of 8.2%.",
            }
        ]
        added, failed = StudyPlanGUI._save_generated_gap_questions(dummy, "Topic A", questions)
        assert added == 1
        assert failed is False


# ===================================================================
# formula discovery TS persistence
# ===================================================================


class TestFormulaDiscoveryTsPersistence:
    def test_load_returns_zero_when_missing(self, tmp_path, monkeypatch):
        from studyplan_app import Config

        monkeypatch.setattr(Config, "CONFIG_HOME", str(tmp_path / ".config" / "studyplan"))
        ts = StudyPlanGUI._load_formula_discovery_ts(None)
        assert ts == 0.0

    def test_save_then_load_roundtrip(self, tmp_path, monkeypatch):
        from studyplan_app import Config

        config_home = str(tmp_path / ".config" / "studyplan")
        monkeypatch.setattr(Config, "CONFIG_HOME", config_home)
        dummy = types.SimpleNamespace()
        dummy._last_formula_discovery_ts = 1234567.89
        StudyPlanGUI._save_formula_discovery_ts(dummy)
        loaded = StudyPlanGUI._load_formula_discovery_ts(None)
        assert loaded == 1234567.89
