import types

from studyplan.cognitive_state import CognitiveState
from studyplan.mastery_kernel import MasteryKernel
from studyplan.coach_fsm import SocraticFSM
from studyplan.working_memory_service import WorkingMemoryService


def test_cognitive_state_hydrates_from_legacy_data_and_roundtrips():
    legacy = {
        "competence": {"Topic A": 75, "Topic B": 20},
        "difficulty_counts": {"Topic A": {"easy": 2, "hard": 3}, "Topic B": 1},
        "chapter_miss_streak": {"Topic B": 3},
        "study_days": ["2026-03-01", "2026-03-03"],
    }
    cfg = {"chapter_flow": {"Topic B": ["Topic A"]}}
    state = CognitiveState.from_legacy_data(legacy, cfg)
    assert "Topic A" in state.posteriors
    assert "Topic B" in state.posteriors
    assert 0.0 < state.posteriors["Topic A"].mean < 1.0
    assert state.confusion_links.get("Topic B") == {"Topic A"}

    snap = state.to_json_snapshot()
    restored = CognitiveState.from_snapshot(snap)
    assert restored.posteriors["Topic A"].alpha == state.posteriors["Topic A"].alpha
    assert restored.working_memory.socratic_state == "DIAGNOSE"
    assert restored.confusion_links.get("Topic B") == {"Topic A"}


def test_working_memory_service_captures_attempts_and_quiz_state():
    state = CognitiveState()
    svc = WorkingMemoryService(state)
    svc.set_active_question(chapter="Topic A", question_id="q:abc123")
    assert state.quiz_active is True
    assert state.working_memory.active_question_id == "q:abc123"
    svc.capture_attempt("Topic A", "q:abc123", False, latency_ms=60000.0, hints_used=2)
    assert state.working_memory.struggle_flags["error_streak"] is True
    assert state.working_memory.struggle_flags["latency_spike"] is True
    assert state.working_memory.struggle_flags["hint_dependency"] is True
    ctx = svc.get_context_string()
    assert "Quiz state: active question" in ctx
    assert "Recent session attempts" in ctx
    svc.clear_active_question()
    assert state.quiz_active is False
    assert state.working_memory.active_question_id is None


def test_tutor_helpers_share_the_same_state_lock():
    state = CognitiveState()

    svc = WorkingMemoryService(state)
    fsm = SocraticFSM(state)
    kernel = MasteryKernel(types.SimpleNamespace(CHAPTER_FLOW={}), state)

    assert svc._state_lock is fsm._state_lock
    assert kernel._state_lock is svc._state_lock


def test_socratic_fsm_enforces_quiz_guard_and_mastery_progression():
    state = CognitiveState()
    state.posteriors["Topic A"] = types.SimpleNamespace(mean=0.9, variance=0.01)  # type: ignore[assignment]
    fsm = SocraticFSM(state)

    state.quiz_active = True
    decision = fsm.transition("TUTOR_REQUEST", {"chapter": "Topic A"})
    assert decision.state == "PRODUCTIVE_STRUGGLE"
    assert decision.permission == "socratic_only"

    state.quiz_active = False
    state.struggle_mode = False
    decision = fsm.transition("TUTOR_REQUEST", {"chapter": "Topic A"})
    assert decision.state == "CHALLENGE"
    assert decision.permission == "explain_ok"

    state.struggle_mode = True
    decision = fsm.transition("TUTOR_REQUEST", {"chapter": "Topic A"})
    assert decision.state == "PRODUCTIVE_STRUGGLE"
    assert decision.permission == "socratic_only"


def test_cognitive_state_transfer_eligibility_uses_structure_posteriors_and_flags():
    state = CognitiveState()
    post = state.get_structure_posterior("npv_annuity_timing_v1")
    post.alpha = 10.0
    post.beta = 2.0
    assert state.should_offer_transfer_test(
        structure_id="npv_annuity_timing_v1",
        base_correct=True,
        hint_penalty=1.0,
    ) is True

    state.quiz_active = True
    assert state.should_offer_transfer_test(
        structure_id="npv_annuity_timing_v1",
        base_correct=True,
        hint_penalty=1.0,
    ) is False
    state.quiz_active = False

    state.struggle_mode = True
    assert state.should_offer_transfer_test(
        structure_id="npv_annuity_timing_v1",
        base_correct=True,
        hint_penalty=1.0,
    ) is False
    state.struggle_mode = False

    assert state.should_offer_transfer_test(
        structure_id="npv_annuity_timing_v1",
        base_correct=True,
        hint_penalty=0.3,
    ) is False


def test_cognitive_state_transfer_tracking_roundtrips_snapshot():
    state = CognitiveState()
    state.record_transfer_exposure("wacc_optimization_v1", attempt_id="t-1")
    state.record_transfer_exposure("wacc_optimization_v1", attempt_id="t-2")
    post = state.get_structure_posterior("wacc_optimization_v1")
    post.alpha = 5.0
    post.beta = 1.5
    snap = state.to_json_snapshot()
    restored = CognitiveState.from_snapshot(snap)
    assert restored.structure_exposure_counts.get("wacc_optimization_v1") == 2
    assert "t-2" in restored.transfer_attempt_ids
    assert "wacc_optimization_v1" in restored.structure_posteriors
