from decimal import Decimal
from pathlib import Path

from studyplan.contracts import (
    AppStateSnapshot,
    ProblemStructure,
    StructureType,
    SurfaceVariant,
    TransferAttempt,
    TutorAssessmentSubmission,
    TutorAssessmentResult,
    TutorLearnerProfileSnapshot,
    TutorLoopTurnRequest,
    TutorPracticeItem,
    TutorSessionState,
)
from studyplan.services import (
    DeterministicTransferVariantGenerator,
    DeterministicTutorPolicyTuningService,
    DeterministicTutorAssessmentService,
    DeterministicTutorInterventionPolicyService,
    DeterministicTutorPracticeService,
    DeterministicTutorStrugglePolicyService,
    FMModuleAdapter,
    InMemoryTutorLearnerModelStore,
    InMemoryTutorSessionController,
    ModuleAdapterRegistry,
    NullModuleAdapter,
    RuleBasedRagEvidencePolicyService,
    RuleBasedTutorLearningLoopService,
    StructureRegistry,
    TransferAttemptLogService,
    TransferScoringService,
    TutorLoopPolicyThresholds,
    resolve_module_adapter,
)


def test_tutor_contracts_roundtrip_profile_and_session():
    profile = TutorLearnerProfileSnapshot(
        learner_id="u1",
        module="FM",
        misconception_tags_top=("wc_policy", "inventory_buffer"),
        weak_capabilities_top=("E", "C"),
        confidence_calibration_bias=1.25,
        chat_to_quiz_transfer_score=0.4,
    )
    profile_rt = TutorLearnerProfileSnapshot.from_dict(profile.to_dict())
    assert profile_rt.learner_id == "u1"
    assert profile_rt.module == "FM"
    assert profile_rt.misconception_tags_top[:1] == ("wc_policy",)

    session = TutorSessionState(
        session_id="s1",
        module="FM",
        topic="Cash Management",
        mode="teach",
        loop_phase="practice",
        session_objective="Understand Miller-Orr",
        target_concepts=("Miller-Orr", "Baumol"),
        active=True,
    )
    session_rt = TutorSessionState.from_dict(session.to_dict())
    assert session_rt.session_id == "s1"
    assert session_rt.loop_phase == "practice"
    assert session_rt.target_concepts == ("Miller-Orr", "Baumol")


def test_tutor_practice_item_roundtrip_preserves_metadata():
    item = TutorPracticeItem(
        item_id="p1",
        item_type="short_answer",
        prompt="Define the cash operating cycle.",
        topic="Working Capital Management",
        capability_tags=("A", "E"),
        rubric_hints=("definition", "components"),
        meta={"difficulty_seed": 2},
    )
    restored = TutorPracticeItem.from_dict(item.to_dict())
    assert restored.item_id == "p1"
    assert restored.capability_tags == ("A", "E")
    assert restored.meta["difficulty_seed"] == 2


def test_in_memory_tutor_session_controller_lifecycle():
    store = InMemoryTutorSessionController()
    state = store.get_or_create_session(session_id="sess-1", module="FM", topic="Risk Management")
    assert state.session_id == "sess-1"
    assert state.topic == "Risk Management"
    assert state.active is False

    started = store.start_or_resume_session(
        session_id="sess-1",
        module="FM",
        topic="Risk Management",
        mode="guided_practice",
        session_objective="Apply CAPM",
        target_concepts=("CAPM", "beta"),
    )
    assert started.active is True
    assert started.mode == "guided_practice"
    assert started.target_concepts == ("CAPM", "beta")

    advanced = store.advance_phase("sess-1", "assess")
    assert advanced.loop_phase == "assess"

    scored = store.record_assessment_outcome(
        "sess-1",
        outcome="incorrect",
        practice_item_id="itm-1",
        increment_streak=True,
    )
    assert scored.last_assessment_outcome == "incorrect"
    assert scored.loop_phase == "teach"
    assert scored.practice_streak == 0
    assert scored.recent_failures >= 1
    assert scored.active_practice_item_id == "itm-1"

    store.reset_session("sess-1")
    recreated = store.get_or_create_session(session_id="sess-1", module="FM", topic="Risk Management")
    assert recreated.active is False
    assert recreated.practice_streak == 0


def test_in_memory_tutor_learner_model_store_updates_tags_and_calibration():
    store = InMemoryTutorLearnerModelStore(max_tags=4)
    base = store.get_or_create_profile("u1", "FM")
    assert base.learner_id == "u1"
    assert base.module == "FM"

    assessment = TutorAssessmentResult(
        item_id="p1",
        outcome="incorrect",
        marks_awarded=1.0,
        marks_max=4.0,
        feedback="Missed formula direction and recommendation.",
        error_tags=("formula_direction", "recommendation"),
        misconception_tags=("wc_policy_confusion",),
        retry_recommended=True,
    )
    updated = store.note_assessment("u1", "FM", assessment, confidence=5)
    assert "wc_policy_confusion" in updated.misconception_tags_top
    assert "formula_direction" in updated.weak_capabilities_top
    assert updated.last_practice_outcome == "incorrect"
    assert -5.0 <= updated.confidence_calibration_bias <= 5.0
    assert -1.0 <= updated.chat_to_quiz_transfer_score <= 1.0

    assessment2 = TutorAssessmentResult(
        item_id="p2",
        outcome="correct",
        marks_awarded=4.0,
        marks_max=4.0,
        feedback="Good application.",
        error_tags=("formula_direction", "time_pressure"),
        misconception_tags=("wc_policy_confusion", "capm_rf_usage"),
    )
    updated2 = store.note_assessment("u1", "FM", assessment2, confidence=2)
    assert len(updated2.misconception_tags_top) <= 4
    assert len(updated2.weak_capabilities_top) <= 4
    # Existing tags stay stable; duplicates should not accumulate.
    assert updated2.misconception_tags_top.count("wc_policy_confusion") == 1
    loop_metrics = dict(updated2.meta.get("learning_loop_metrics", {}) or {})
    assert int(loop_metrics.get("assessments_total", 0) or 0) >= 2
    assert int(loop_metrics.get("misconception_recurrence_count", 0) or 0) >= 1
    assert 0.0 <= float(loop_metrics.get("avg_score_ratio_ema", 0.0) or 0.0) <= 1.0


def test_phase8_learner_model_store_tracks_learning_loop_metrics_recurrence_and_streaks():
    store = InMemoryTutorLearnerModelStore(max_tags=6)
    incorrect = TutorAssessmentResult(
        item_id="x1",
        outcome="incorrect",
        marks_awarded=0.0,
        marks_max=2.0,
        feedback="Missed risk link.",
        error_tags=("missing_risk",),
        misconception_tags=("wc_policy_risk_ignored",),
    )
    p1 = store.note_assessment("u8", "FM", incorrect, confidence=5)
    partial = TutorAssessmentResult(
        item_id="x2",
        outcome="partial",
        marks_awarded=1.0,
        marks_max=2.0,
        feedback="Better but still weak risk framing.",
        error_tags=("missing_risk",),
        misconception_tags=("wc_policy_risk_ignored",),
    )
    p2 = store.note_assessment("u8", "FM", partial, confidence=4)
    metrics = dict(p2.meta.get("learning_loop_metrics", {}) or {})
    assert int(metrics.get("assessments_total", 0) or 0) == 2
    assert int(metrics.get("incorrect_count", 0) or 0) >= 1
    assert int(metrics.get("partial_count", 0) or 0) >= 1
    assert int(metrics.get("misconception_recurrence_count", 0) or 0) >= 1
    assert int(metrics.get("consecutive_correct", 0) or 0) >= 1  # partial counts as progress
    assert 0 <= int(metrics.get("confidence_samples", 0) or 0) <= 2


def _loop_request(
    *,
    user_message: str,
    session_state: TutorSessionState | None = None,
    learner_profile: TutorLearnerProfileSnapshot | None = None,
    app_snapshot: AppStateSnapshot | None = None,
    mode_override: str = "auto",
    autonomy_mode: str = "assist",
) -> TutorLoopTurnRequest:
    snap = app_snapshot or AppStateSnapshot(
        module="FM",
        current_topic="Cash Management",
        coach_pick="Cash Management",
        days_to_exam=42,
        must_review_due=0,
        overdue_srs_count=0,
        weak_topics_top3=("AR/AP Management", "Risk Management"),
    )
    sess = session_state or TutorSessionState(
        session_id="s-loop",
        module=snap.module,
        topic=snap.current_topic,
        mode="auto",
        loop_phase="observe",
        active=False,
    )
    profile = learner_profile or TutorLearnerProfileSnapshot(
        learner_id="u-loop",
        module=snap.module,
    )
    return TutorLoopTurnRequest(
        user_message=user_message,
        app_snapshot=snap,
        session_state=sess,
        learner_profile=profile,
        mode_override=mode_override,
        autonomy_mode=autonomy_mode,
    )


def test_phase2_learning_loop_service_selects_teach_mode_for_explanation_prompt():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    service = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
    )
    result = service.run_turn(_loop_request(user_message="Explain Miller-Orr model simply."))
    assert result.mode_used == "teach"
    assert result.phase_after_turn in {"teach", "practice"}
    assert result.session_state.active is True
    assert "Planner mode: teach" in result.response_text


def test_phase2_learning_loop_service_selects_error_clinic_from_failures_and_misconceptions():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    service = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
    )
    session = TutorSessionState(
        session_id="s2",
        module="FM",
        topic="Working Capital Management",
        mode="auto",
        loop_phase="observe",
        recent_failures=3,
        active=True,
    )
    profile = TutorLearnerProfileSnapshot(
        learner_id="u2",
        module="FM",
        misconception_tags_top=("wc_policy_confusion", "cash_cycle_confusion"),
    )
    result = service.run_turn(
        _loop_request(
            user_message="I still keep getting this wrong.",
            session_state=session,
            learner_profile=profile,
        )
    )
    assert result.mode_used == "error_clinic"
    assert result.phase_after_turn in {"teach", "reinforce"}
    assert result.action_intent is not None
    assert result.action_intent.action in {"drill_start", "review_start"}


def test_phase2_learning_loop_service_emits_review_action_under_due_pressure():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    service = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
    )
    snap = AppStateSnapshot(
        module="FM",
        current_topic="Risk Management",
        coach_pick="Risk Management",
        days_to_exam=18,
        must_review_due=12,
        overdue_srs_count=7,
        weak_topics_top3=("Risk Management",),
    )
    result = service.run_turn(
        _loop_request(
            user_message="What should I do next?",
            app_snapshot=snap,
            autonomy_mode="assist",
        )
    )
    assert result.mode_used == "revision_planner"
    assert result.action_intent is not None
    assert result.action_intent.action == "review_start"
    assert result.action_intent.requires_confirmation is True
    assert "must_review_due" in " ".join(result.action_intent.evidence)


def test_phase2_learning_loop_service_respects_mode_override_and_section_c_request():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    service = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
    )
    res_override = service.run_turn(
        _loop_request(
            user_message="Teach me this via practice.",
            mode_override="guided_practice",
        )
    )
    assert res_override.mode_used == "guided_practice"

    res_section_c = service.run_turn(
        _loop_request(
            user_message="Let's do a Section C constructed response on WACC.",
        )
    )
    assert res_section_c.mode_used == "section_c_coach"


def test_phase8_learning_loop_service_tunes_mode_from_metrics_progress():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    service = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
    )
    profile = TutorLearnerProfileSnapshot(
        learner_id="u-tune",
        module="FM",
        chat_to_quiz_transfer_score=0.2,
        meta={
            "learning_loop_metrics": {
                "assessments_total": 6,
                "correct_count": 4,
                "partial_count": 2,
                "incorrect_count": 0,
                "consecutive_correct": 3,
                "consecutive_incorrect": 0,
                "misconception_recurrence_count": 0,
                "avg_score_ratio_ema": 0.83,
                "confidence_bias_abs_ema": 0.4,
            }
        },
    )
    result = service.run_turn(
        _loop_request(
            user_message="What should I do next?",
            learner_profile=profile,
        )
    )
    assert result.mode_used in {"retrieval_drill", "guided_practice"}
    assert str(result.telemetry.get("loop_assessments_total", 0)) != "0"


def test_phase3_practice_service_generates_micro_items_for_guided_practice():
    svc = DeterministicTutorPracticeService()
    items = svc.build_practice_items(
        session_state=TutorSessionState(
            session_id="s3",
            module="FM",
            topic="Cash Management",
            mode="guided_practice",
            loop_phase="practice",
            active=True,
        ),
        learner_profile=TutorLearnerProfileSnapshot(
            learner_id="u3",
            module="FM",
            misconception_tags_top=("cash_cycle_confusion",),
            weak_capabilities_top=("E",),
        ),
        app_snapshot=AppStateSnapshot(
            module="FM",
            current_topic="Cash Management",
            coach_pick="Cash Management",
            days_to_exam=30,
            must_review_due=0,
            overdue_srs_count=0,
            weak_topics_top3=("AR/AP Management", "Cash Management"),
        ),
        max_items=3,
    )
    assert 1 <= len(items) <= 3
    assert any(item.item_type == "teach_back" for item in items)
    assert any(item.item_type in {"short_answer", "mcq"} for item in items)
    assert all(item.topic for item in items)


def test_phase3_assessment_service_marks_mcq_and_keyword_short_answer():
    assessor = DeterministicTutorAssessmentService()
    mcq_item = TutorPracticeItem(
        item_id="mcq-1",
        item_type="mcq",
        prompt="Pick one",
        topic="Risk Management",
        meta={"correct_option": "B", "marks_max": 1.0, "error_tags_by_option": {"A": "passive_review_bias"}},
    )
    mcq_ok = assessor.assess(
        item=mcq_item,
        submission=TutorAssessmentSubmission(item_id="mcq-1", answer_text="B"),
        session_state=TutorSessionState(session_id="s", module="FM", topic="Risk Management"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u", module="FM"),
    )
    assert mcq_ok.outcome == "correct"
    assert mcq_ok.marks_awarded == 1.0

    mcq_bad = assessor.assess(
        item=mcq_item,
        submission=TutorAssessmentSubmission(item_id="mcq-1", answer_text="A"),
        session_state=TutorSessionState(session_id="s", module="FM", topic="Risk Management"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u", module="FM"),
    )
    assert mcq_bad.outcome == "incorrect"
    assert "passive_review_bias" in mcq_bad.error_tags

    short_item = TutorPracticeItem(
        item_id="sa-1",
        item_type="short_answer",
        prompt="Define and apply working capital policy",
        topic="Working Capital Management",
        rubric_hints=("policy", "working capital", "risk"),
        meta={
            "keywords": ["working capital", "policy", "risk"],
            "marks_max": 3.0,
            "misconception_tags_by_missing_keyword": {"risk": "wc_policy_risk_ignored"},
        },
    )
    short_partial = assessor.assess(
        item=short_item,
        submission=TutorAssessmentSubmission(item_id="sa-1", answer_text="It is a policy for managing working capital."),
        session_state=TutorSessionState(session_id="s", module="FM", topic="Working Capital Management"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u", module="FM"),
    )
    assert short_partial.outcome in {"partial", "correct"}
    if short_partial.outcome != "correct":
        assert "wc_policy_risk_ignored" in short_partial.misconception_tags


def test_phase3_assessment_service_marks_calculation_with_tolerance():
    assessor = DeterministicTutorAssessmentService()
    calc_item = TutorPracticeItem(
        item_id="calc-1",
        item_type="calculation_step",
        prompt="Compute the answer.",
        topic="Cost of Capital",
        meta={"numeric_answer": 12.5, "tolerance": 0.05, "marks_max": 2.0},
    )
    res_close = assessor.assess(
        item=calc_item,
        submission=TutorAssessmentSubmission(item_id="calc-1", answer_text="12.52%"),
        session_state=TutorSessionState(session_id="s", module="FM", topic="Cost of Capital"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u", module="FM"),
    )
    assert res_close.outcome == "correct"
    assert res_close.marks_awarded == 2.0

    res_far = assessor.assess(
        item=calc_item,
        submission=TutorAssessmentSubmission(item_id="calc-1", answer_text="10.0"),
        session_state=TutorSessionState(session_id="s", module="FM", topic="Cost of Capital"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u", module="FM"),
    )
    assert res_far.outcome == "incorrect"
    assert "numeric_mismatch" in res_far.error_tags or "numeric_precision" in res_far.error_tags


def test_phase3_loop_service_can_attach_practice_items_from_practice_service():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    practice = DeterministicTutorPracticeService()
    loop = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
        practice_service=practice,
        max_practice_items=2,
    )
    result = loop.run_turn(_loop_request(user_message="Explain this, then test me quickly."))
    assert result.mode_used in {"teach", "retrieval_drill", "guided_practice"}
    # teach mode may move to teach or practice depending prior phase; when practice is selected, items should be attached.
    if result.phase_after_turn in {"practice", "reinforce", "assess"}:
        assert len(result.practice_items) >= 1


def test_sprint_a_practice_service_builds_retest_variant_for_incorrect_short_answer():
    practice = DeterministicTutorPracticeService()
    item = TutorPracticeItem(
        item_id="wc-short-1",
        item_type="short_answer",
        prompt="Define working capital policy and mention one risk.",
        topic="Working Capital Management",
        expected_format="1-3 lines",
        difficulty="medium",
        rubric_hints=("policy", "risk"),
        meta={
            "keywords": ["working capital", "policy", "risk"],
            "marks_max": 3.0,
        },
    )
    result = TutorAssessmentResult(
        item_id="wc-short-1",
        outcome="incorrect",
        marks_awarded=0.0,
        marks_max=3.0,
        feedback="Missed the risk point.",
        error_tags=("missing_risk",),
        misconception_tags=("wc_policy_risk_ignored",),
        retry_recommended=True,
        next_difficulty="same",
    )
    variant = practice.build_retest_variant(
        item=item,
        assessment_result=result,
        session_state=TutorSessionState(session_id="s-var", module="FM", topic="Working Capital Management"),
        learner_profile=TutorLearnerProfileSnapshot(
            learner_id="u-var",
            module="FM",
            misconception_tags_top=("wc_policy_risk_ignored",),
        ),
        app_snapshot=AppStateSnapshot(
            module="FM",
            current_topic="Working Capital Management",
            coach_pick="Working Capital Management",
            days_to_exam=28,
            must_review_due=0,
            overdue_srs_count=0,
        ),
    )
    assert variant is not None
    assert variant.item_id != item.item_id
    assert variant.prompt != item.prompt
    assert variant.source == "tutor_micro_variant"
    assert str(variant.meta.get("variant_of", "")) == "wc-short-1"
    assert int(variant.meta.get("variant_round", 0) or 0) >= 1
    assert str(variant.meta.get("transfer_level", "")) in {"near", "far"}


def test_sprint_a_practice_service_builds_retest_variant_for_mcq_with_metadata():
    practice = DeterministicTutorPracticeService()
    item = TutorPracticeItem(
        item_id="mcq-loop-1",
        item_type="mcq",
        prompt="Pick one",
        topic="Cash Management",
        meta={"correct_option": "B", "marks_max": 1.0},
    )
    result = TutorAssessmentResult(
        item_id="mcq-loop-1",
        outcome="partial",
        marks_awarded=0.0,
        marks_max=1.0,
        feedback="Try again on a new wording.",
        retry_recommended=True,
        next_difficulty="same",
    )
    variant = practice.build_retest_variant(
        item=item,
        assessment_result=result,
        session_state=TutorSessionState(session_id="s-var2", module="FM", topic="Cash Management"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u-var2", module="FM"),
        app_snapshot=AppStateSnapshot(
            module="FM",
            current_topic="Cash Management",
            coach_pick="Cash Management",
            days_to_exam=21,
            must_review_due=0,
            overdue_srs_count=0,
        ),
    )
    assert variant is not None
    assert variant.item_type == "mcq"
    assert "Variant re-test" in variant.prompt
    assert str(variant.meta.get("variant_kind", "")).strip() == "mcq_rephrase"
    assert str(variant.meta.get("variant_of", "")).strip() == "mcq-loop-1"


def test_sprint_b_intervention_policy_selects_worked_example_for_recurring_misconception():
    policy = DeterministicTutorInterventionPolicyService()
    decision = policy.choose_intervention(
        item=TutorPracticeItem(
            item_id="p-int-1",
            item_type="short_answer",
            prompt="Explain policy and risk.",
            topic="Working Capital Management",
        ),
        assessment_result=TutorAssessmentResult(
            item_id="p-int-1",
            outcome="incorrect",
            marks_awarded=0.0,
            marks_max=3.0,
            feedback="Missed risk point again.",
            error_tags=("missing_risk",),
            misconception_tags=("wc_policy_risk_ignored",),
            retry_recommended=True,
        ),
        session_state=TutorSessionState(session_id="s-int", module="FM", topic="Working Capital Management"),
        learner_profile=TutorLearnerProfileSnapshot(
            learner_id="u-int",
            module="FM",
            misconception_tags_top=("wc_policy_risk_ignored",),
            meta={
                "learning_loop_metrics": {
                    "misconception_recurrence_count": 2,
                    "consecutive_incorrect": 2,
                }
            },
        ),
        app_snapshot=AppStateSnapshot(
            module="FM",
            current_topic="Working Capital Management",
            coach_pick="Working Capital Management",
            days_to_exam=20,
            must_review_due=0,
            overdue_srs_count=0,
        ),
    )
    assert str(decision.get("intervention_type", "")) == "worked_example_then_retest"
    assert bool(decision.get("recommended_variant", False)) is True
    assert "recurring" in str(decision.get("rationale", "")).lower()


def test_sprint_b_variant_generation_ladders_difficulty_for_correct_answer():
    practice = DeterministicTutorPracticeService()
    item = TutorPracticeItem(
        item_id="teachback-1",
        item_type="teach_back",
        prompt="Explain CAPM in 2 lines.",
        topic="Risk Management",
        difficulty="medium",
        rubric_hints=("formula", "use"),
        meta={"keywords": ["capm", "beta"], "marks_max": 2.0},
    )
    result = TutorAssessmentResult(
        item_id="teachback-1",
        outcome="correct",
        marks_awarded=2.0,
        marks_max=2.0,
        feedback="Good answer.",
        next_difficulty="harder",
        retry_recommended=False,
    )
    variant = practice.build_retest_variant(
        item=item,
        assessment_result=result,
        session_state=TutorSessionState(session_id="s-capm", module="FM", topic="Risk Management"),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="u-capm", module="FM"),
        app_snapshot=AppStateSnapshot(
            module="FM",
            current_topic="Risk Management",
            coach_pick="Risk Management",
            days_to_exam=15,
            must_review_due=0,
            overdue_srs_count=0,
        ),
    )
    assert variant is not None
    assert variant.difficulty in {"hard", "medium"}
    assert str(variant.meta.get("variant_of", "")) == "teachback-1"


def test_m6_policy_tuning_service_is_deterministic_and_clamped():
    tuner = DeterministicTutorPolicyTuningService()
    base = TutorLoopPolicyThresholds(
        min_assessments_for_metrics=4,
        error_incorrect_rate_threshold=0.5,
        retrieval_correct_rate_threshold=0.72,
        retrieval_min_streak=2,
        retrieval_score_ema_min=0.55,
        calibration_bias_guard=1.4,
        review_pressure_guard_total=8,
    )
    profile = TutorLearnerProfileSnapshot(learner_id="u1", module="FM", chat_to_quiz_transfer_score=-0.2)
    snapshot = AppStateSnapshot(
        module="FM",
        current_topic="Working Capital",
        coach_pick="Working Capital",
        days_to_exam=20,
        must_review_due=2,
        overdue_srs_count=1,
    )
    metrics = {
        "assessments_total": 10,
        "incorrect_count": 6,
        "misconception_recurrence_count": 3,
        "consecutive_correct": 0,
        "consecutive_incorrect": 2,
        "accuracy_like": 0.4,
        "avg_score_ratio_ema": 0.42,
        "confidence_bias_abs_ema": 2.2,
    }
    tuned1, meta1 = tuner.tune(
        base_thresholds=base,
        loop_metrics=metrics,
        learner_profile=profile,
        app_snapshot=snapshot,
    )
    tuned2, meta2 = tuner.tune(
        base_thresholds=base,
        loop_metrics=metrics,
        learner_profile=profile,
        app_snapshot=snapshot,
    )
    assert tuned1 == tuned2
    assert meta1["reason"] == meta2["reason"]
    assert float(tuned1.error_incorrect_rate_threshold) <= 0.5
    assert float(tuned1.retrieval_correct_rate_threshold) >= 0.72
    assert 0.4 <= float(tuned1.calibration_bias_guard) <= 3.5


def test_m6_rule_based_loop_exposes_active_thresholds_and_tuning_meta():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    loop = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
        practice_service=None,
        policy_thresholds=TutorLoopPolicyThresholds(),
        policy_tuning_service=DeterministicTutorPolicyTuningService(),
    )
    profile = TutorLearnerProfileSnapshot(
        learner_id="u-m6",
        module="FM",
        meta={
            "learning_loop_metrics": {
                "assessments_total": 8,
                "correct_count": 1,
                "partial_count": 1,
                "incorrect_count": 6,
                "misconception_recurrence_count": 2,
                "consecutive_correct": 0,
                "consecutive_incorrect": 2,
                "avg_score_ratio_ema": 0.4,
                "confidence_bias_abs_ema": 1.8,
            }
        },
    )
    req = _loop_request(user_message="Help me", learner_profile=profile)
    result = loop.run_turn(req)
    thresholds = loop.get_active_policy_thresholds()
    tuning_meta = loop.get_policy_tuning_meta()
    assert isinstance(thresholds, dict)
    assert "error_incorrect_rate_threshold" in thresholds
    assert "retrieval_correct_rate_threshold" in thresholds
    assert isinstance(tuning_meta, dict)
    assert str(tuning_meta.get("status", "")) in {"stable", "tuned", "insufficient_data"}
    assert "loop_thresholds" in result.telemetry
    assert "loop_tuning_reason" in result.telemetry


def test_module_adapter_registry_and_resolve_fallback():
    registry = ModuleAdapterRegistry()
    fm = FMModuleAdapter()
    registry.register(fm)
    assert registry.get("fm") is fm
    assert registry.get("FM") is fm
    assert registry.get("xx") is None

    fallback = resolve_module_adapter("FR", registry=registry)
    assert isinstance(fallback, NullModuleAdapter)
    assert fallback.descriptor().module_code == "FR"


def test_fm_module_adapter_infers_transfer_structure_ids_from_topic_and_tags():
    adapter = FMModuleAdapter()
    inferred_npv = adapter.infer_transfer_structure(
        topic_id="Investment Appraisal",
        question_type="short_answer",
        tags=("npv", "annuity"),
        meta={},
    )
    inferred_wacc = adapter.infer_transfer_structure(
        topic_id="Cost of Capital",
        question_type="mcq",
        tags=("wacc",),
        meta={},
    )
    inferred_wc = adapter.infer_transfer_structure(
        topic_id="Working Capital Management",
        question_type="section_c_part",
        tags=("cash_management",),
        meta={},
    )
    assert inferred_npv == "npv_annuity_timing_v1"
    assert inferred_wacc == "wacc_optimization_v1"
    assert inferred_wc == "working_capital_cycle_v1"


def test_null_module_adapter_does_not_infer_transfer_structure():
    adapter = NullModuleAdapter()
    inferred = adapter.infer_transfer_structure(
        topic_id="Any Topic",
        question_type="mcq",
        tags=("npv",),
        meta={},
    )
    assert inferred is None


def test_transfer_attempt_log_service_roundtrips_recent_attempts(tmp_path: Path):
    svc = TransferAttemptLogService()
    log_path = tmp_path / "transfer_attempts.jsonl"
    attempt = TransferAttempt(
        attempt_id="a1",
        student_id="u1",
        base_question_id="q-base",
        variant_question_id="q-var",
        structure_id="npv_annuity_timing_v1",
        base_result="correct",
        variant_result="incorrect",
        base_latency_seconds=9.0,
        variant_latency_seconds=13.5,
        base_hint_penalty=1.0,
        variant_hint_penalty=0.7,
    )
    assert svc.append_attempt(str(log_path), attempt) is True
    loaded = svc.load_recent_attempts(str(log_path), max_rows=10)
    assert len(loaded) == 1
    row = loaded[0]
    assert row.attempt_id == "a1"
    assert row.student_id == "u1"
    assert row.structure_id == "npv_annuity_timing_v1"
    assert row.variant_result == "incorrect"


def test_transfer_attempt_log_service_ignores_bad_lines(tmp_path: Path):
    svc = TransferAttemptLogService()
    log_path = tmp_path / "transfer_attempts.jsonl"
    log_path.write_text("{bad json}\n" + "{\"attempt_id\":\"ok1\",\"student_id\":\"u1\",\"base_question_id\":\"b\",\"variant_question_id\":\"v\",\"structure_id\":\"s\",\"base_result\":\"correct\",\"variant_result\":\"correct\",\"base_latency_seconds\":1,\"variant_latency_seconds\":1,\"base_hint_penalty\":1,\"variant_hint_penalty\":1}\n", encoding="utf-8")
    loaded = svc.load_recent_attempts(str(log_path), max_rows=10)
    assert len(loaded) == 1
    assert loaded[0].attempt_id == "ok1"


def test_rule_based_loop_can_use_module_adapter_topic_default_mode():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    loop = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
        module_adapter=FMModuleAdapter(),
    )
    snap = AppStateSnapshot(
        module="FM",
        current_topic="WACC",
        coach_pick="WACC",
        days_to_exam=50,
        must_review_due=0,
        overdue_srs_count=0,
        weak_topics_top3=("AR/AP Management", "Risk Management"),
    )
    req = _loop_request(user_message="Help me on this topic.", app_snapshot=snap)
    result = loop.run_turn(req)
    assert result.mode_used == "guided_practice"
    assert str(result.telemetry.get("mode_reason", "")) == "module_adapter_topic_default"


def test_rag_evidence_policy_strong_grounding_when_target_hits_present():
    svc = RuleBasedRagEvidencePolicyService()
    decision = svc.evaluate(
        rag_meta={
            "method": "hybrid",
            "snippet_count": 5,
            "source_count": 2,
            "target_query_count": 3,
            "target_hit_snippets": 3,
            "sources": ["syllabus.pdf", "notes.pdf"],
            "errors": [],
        },
        user_prompt="Explain the WACC rule and assumptions.",
        current_topic="WACC",
    )
    assert str(decision.get("policy_mode", "")) == "strong_grounding"
    assert float(decision.get("confidence_score", 0.0) or 0.0) >= 0.72
    assert bool(decision.get("insufficient", False)) is False
    assert "RAG evidence strong" in str(decision.get("planner_brief_line", ""))


def test_rag_evidence_policy_weak_grounding_with_no_target_hits_and_errors():
    svc = RuleBasedRagEvidencePolicyService()
    decision = svc.evaluate(
        rag_meta={
            "method": "lexical",
            "snippet_count": 2,
            "source_count": 1,
            "target_query_count": 2,
            "target_hit_snippets": 0,
            "errors": ["pdf parse timeout"],
        },
        user_prompt="What does IAS 16 require for revaluation surplus?",
        current_topic="Non-current assets",
    )
    assert str(decision.get("policy_mode", "")) == "weak_grounding"
    assert bool(decision.get("insufficient", False)) is True
    assert "assumptions" in str(decision.get("planner_brief_line", "")).lower()
    assert "uncertainty" in str(decision.get("planner_brief_line", "")).lower()


def test_rag_evidence_policy_disabled_mode_is_bounded_and_explicit():
    svc = RuleBasedRagEvidencePolicyService()
    decision = svc.evaluate(
        rag_meta={"method": "disabled", "snippet_count": 0, "source_count": 0},
        user_prompt="Teach me CAPM.",
        current_topic="Risk Management",
    )
    assert str(decision.get("policy_mode", "")) == "disabled"
    assert 0.0 <= float(decision.get("confidence_score", 0.0) or 0.0) <= 0.35
    assert "unavailable" in str(decision.get("planner_brief_line", "")).lower()


def test_phase6_cognitive_runtime_meta_can_shift_mode_to_retrieval_drill():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    loop = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
    )
    req = _loop_request(
        user_message="Help me on this topic.",
        app_snapshot=AppStateSnapshot(
            module="FM",
            current_topic="WACC",
            coach_pick="WACC",
            days_to_exam=30,
            must_review_due=0,
            overdue_srs_count=0,
        ),
    )
    req = TutorLoopTurnRequest(
        **{
            **req.__dict__,
            "meta": {
                "surface": "tutor_workspace",
                "cognitive_runtime": {
                    "enabled": True,
                    "posterior_mean": 0.9,
                    "posterior_variance": 0.02,
                    "struggle_mode": False,
                    "quiz_active": False,
                },
            },
        }
    )
    result = loop.run_turn(req)
    assert result.mode_used == "retrieval_drill"
    assert str(result.telemetry.get("mode_reason", "")) == "cognitive_high_mastery_low_variance"
    assert str((result.session_state.meta or {}).get("difficulty_hint", "")) == "harder"


def test_phase6_cognitive_runtime_struggle_mode_sets_guided_practice_and_easier_difficulty():
    sessions = InMemoryTutorSessionController()
    learners = InMemoryTutorLearnerModelStore()
    practice = DeterministicTutorPracticeService()
    loop = RuleBasedTutorLearningLoopService(
        session_controller=sessions,
        learner_model_store=learners,
        practice_service=practice,
    )
    base_req = _loop_request(user_message="Help me with this concept")
    req = TutorLoopTurnRequest(
        **{
            **base_req.__dict__,
            "meta": {
                "cognitive_runtime": {
                    "enabled": True,
                    "posterior_mean": 0.35,
                    "posterior_variance": 0.12,
                    "struggle_mode": True,
                    "quiz_active": False,
                }
            },
        }
    )
    result = loop.run_turn(req)
    assert result.mode_used == "guided_practice"
    assert str(result.telemetry.get("mode_reason", "")) == "cognitive_struggle_mode"
    assert str((result.session_state.meta or {}).get("difficulty_hint", "")) == "easier"
    assert result.practice_items
    first_item = result.practice_items[0]
    assert str(getattr(first_item, "difficulty", "") or "") in {"easy", "medium"}


def test_struggle_policy_denies_hint_before_attempt_when_not_struggling():
    svc = DeterministicTutorStrugglePolicyService()
    decision, state = svc.evaluate_hint_access(
        item_id="itm-1",
        state={},
        has_assessment=False,
        cognitive_runtime={"enabled": True, "struggle_mode": False, "quiz_active": False},
        now_monotonic=100.0,
    )
    assert bool(decision.get("allow", False)) is False
    assert str(decision.get("reason", "")) == "attempt_first"
    assert "take one attempt first" in str(decision.get("status", "")).lower()
    assert str(state.get("item_id", "")) == "itm-1"


def test_struggle_policy_allows_pre_attempt_hint_when_struggling_and_consumes_token():
    svc = DeterministicTutorStrugglePolicyService()
    decision, state = svc.evaluate_hint_access(
        item_id="itm-2",
        state={},
        has_assessment=False,
        cognitive_runtime={"enabled": True, "struggle_mode": True, "quiz_active": False},
        now_monotonic=10.0,
    )
    assert bool(decision.get("allow", False)) is True
    assert str(decision.get("reason", "")) == "struggle_priority"
    assert int(decision.get("tokens_remaining", 0) or 0) == 0
    assert int(state.get("tokens", 0) or 0) == 0


def test_struggle_policy_applies_post_attempt_bonus_and_cooldown_then_budget():
    svc = DeterministicTutorStrugglePolicyService(refill_seconds=30.0, min_spacing_seconds=4.0)
    state: dict[str, object] = {}
    # First request after assessment should be allowed with post-assessment bonus.
    d1, state = svc.evaluate_hint_access(
        item_id="itm-3",
        state=state,
        has_assessment=True,
        cognitive_runtime={"enabled": True, "struggle_mode": False, "quiz_active": False},
        now_monotonic=50.0,
    )
    assert bool(d1.get("allow", False)) is True
    # Immediate repeat request should hit cooldown.
    d2, state = svc.evaluate_hint_access(
        item_id="itm-3",
        state=state,
        has_assessment=True,
        cognitive_runtime={"enabled": True, "struggle_mode": False, "quiz_active": False},
        now_monotonic=51.0,
    )
    assert bool(d2.get("allow", False)) is False
    assert str(d2.get("reason", "")) == "cooldown"
    # After cooldown, consume remaining token.
    d3, state = svc.evaluate_hint_access(
        item_id="itm-3",
        state=state,
        has_assessment=True,
        cognitive_runtime={"enabled": True, "struggle_mode": False, "quiz_active": False},
        now_monotonic=55.0,
    )
    assert bool(d3.get("allow", False)) is True
    # Next request after cooldown should hit budget exhaustion (before refill).
    d4, state = svc.evaluate_hint_access(
        item_id="itm-3",
        state=state,
        has_assessment=True,
        cognitive_runtime={"enabled": True, "struggle_mode": False, "quiz_active": False},
        now_monotonic=60.0,
    )
    assert bool(d4.get("allow", False)) is False
    assert str(d4.get("reason", "")) == "budget_exhausted"


def test_transfer_variant_generator_is_deterministic_for_same_inputs():
    generator = DeterministicTransferVariantGenerator()
    structure = ProblemStructure(
        structure_id="npv_annuity_timing_v1",
        structure_type=StructureType.NPV_ANNUITY_TIMING,
        required_operations=("discount", "annuity_factor"),
        misconception_exposure_class="time_value_timing",
    )
    v1 = generator.generate(structure, exclude_variants=(), seed_offset=0)
    v2 = generator.generate(structure, exclude_variants=(), seed_offset=0)
    assert v1.variant_id == v2.variant_id
    assert v1.domain == v2.domain
    assert v1.numeric_range == v2.numeric_range
    assert v1.context_seed == v2.context_seed


def test_transfer_variant_generator_rotates_domain_when_excluded():
    generator = DeterministicTransferVariantGenerator()
    structure = ProblemStructure(
        structure_id="wacc_optimization_v1",
        structure_type=StructureType.WACC_OPTIMIZATION,
        required_operations=("component_cost", "weighting"),
        misconception_exposure_class="capital_structure_weights",
    )
    excluded = SurfaceVariant(
        variant_id="wacc_optimization_v1__corporate__0",
        base_structure_id="wacc_optimization_v1",
        domain="corporate",
        numeric_range=(Decimal("1"), Decimal("2")),
        entity_type="listed",
        context_seed="tight credit",
        metadata={"domain": "corporate"},
    )
    next_variant = generator.generate(structure, exclude_variants=(excluded,), seed_offset=1)
    assert str(next_variant.metadata.get("domain", "")) != "corporate"


def test_transfer_scoring_service_computes_transfer_and_brittleness():
    scorer = TransferScoringService()
    scorer.record_attempt(
        TransferAttempt(
            attempt_id="a1",
            student_id="u1",
            base_question_id="b1",
            variant_question_id="v1",
            structure_id="npv_annuity_timing_v1",
            base_result="correct",
            variant_result="correct",
            base_latency_seconds=10.0,
            variant_latency_seconds=12.0,
            base_hint_penalty=1.0,
            variant_hint_penalty=1.0,
        )
    )
    scorer.record_attempt(
        TransferAttempt(
            attempt_id="a2",
            student_id="u1",
            base_question_id="b2",
            variant_question_id="v2",
            structure_id="npv_annuity_timing_v1",
            base_result="correct",
            variant_result="incorrect",
            base_latency_seconds=9.0,
            variant_latency_seconds=14.0,
            base_hint_penalty=1.0,
            variant_hint_penalty=1.0,
        )
    )
    score = scorer.get_score("u1", "npv_annuity_timing_v1")
    assert score is not None
    assert score.transfer_rate == 0.5
    assert score.brittleness_index == 0.5
    brittle = scorer.get_brittle_concepts("u1", threshold=0.3)
    assert brittle and brittle[0]["risk_level"] == "high"


def test_structure_registry_infers_default_fm_structures_from_topic_and_tags():
    registry = StructureRegistry()
    s1 = registry.infer_from_topic_and_item(topic_id="Investment Appraisal", question_type="mcq", tags=("npv",))
    s2 = registry.infer_from_topic_and_item(topic_id="Cost of Capital", question_type="short_answer", tags=("wacc",))
    s3 = registry.infer_from_topic_and_item(topic_id="Working Capital Management", question_type="teach_back", tags=())
    assert s1 is not None and s1.structure_type == StructureType.NPV_ANNUITY_TIMING
    assert s2 is not None and s2.structure_type == StructureType.WACC_OPTIMIZATION
    assert s3 is not None and s3.structure_type == StructureType.WORKING_CAPITAL_CYCLE
