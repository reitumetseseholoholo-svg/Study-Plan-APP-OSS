from studyplan.cognitive_state import CognitiveState, CompetencyPosterior
from studyplan.contracts import (
    TutorPracticeItem,
    TutorAssessmentSubmission,
    TutorAssessmentResult,
    TutorLearnerProfileSnapshot,
    TutorActionIntent,
    TutorSessionState,
)


def _snapshot_wo_timestamp(state: CognitiveState) -> dict:
    snap = state.to_json_snapshot()
    snap.pop("timestamp", None)
    return snap


def test_persistence_atomic_write(persistence, sample_state):
    learner = "learner123"
    success = persistence.save_state_atomic(learner, sample_state)
    assert success
    loaded = persistence.load_state(learner)
    assert isinstance(loaded, CognitiveState)
    assert _snapshot_wo_timestamp(loaded) == _snapshot_wo_timestamp(sample_state)


def test_load_nonexistent_returns_new(persistence):
    loaded = persistence.load_state("no-such")
    assert isinstance(loaded, CognitiveState)
    assert loaded.posteriors == {}


def test_persistence_cognitive_state_round_trip_with_nondefault_fields(persistence):
    learner = "learner-rich"
    state = CognitiveState()
    state.posteriors["npv"] = CompetencyPosterior(
        alpha=6.0,
        beta=2.0,
        last_observation="2026-02-27",
        hint_penalty=0.8,
    )
    state.structure_posteriors["npv_structure"] = CompetencyPosterior(
        alpha=5.0,
        beta=3.0,
        last_observation="2026-02-26",
        hint_penalty=0.7,
    )
    state.working_memory.active_question_id = "q-1"
    state.working_memory.active_chapter = "npv"
    state.working_memory.context_chunks = ["a", "b"]
    state.working_memory.struggle_flags["error_streak"] = True
    state.confusion_links["npv"] = {"discount_rate", "timing"}
    state.prerequisite_gaps = {"time_value"}
    state.claim_confidence["npv"] = 0.72
    state.structure_exposure_counts["npv_structure"] = 2
    state.transfer_attempt_ids = ["t1", "t2"]
    state.quiz_active = True
    state.struggle_mode = True

    assert persistence.save_state_atomic(learner, state)
    loaded = persistence.load_state(learner)
    assert isinstance(loaded, CognitiveState)
    assert _snapshot_wo_timestamp(loaded) == _snapshot_wo_timestamp(state)


def test_contracts_round_trip_practice_submission_result():
    item = TutorPracticeItem.from_dict(
        {
            "item_id": " i-1 ",
            "item_type": "short_answer",
            "prompt": " Explain NPV ",
            "topic": "NPV",
            "capability_tags": ["calc", "calc", ""],
            "rubric_hints": ["show formula", ""],
            "meta": {"k": 1},
        }
    )
    item_rt = TutorPracticeItem.from_dict(item.to_dict())
    assert item_rt.to_dict() == item.to_dict()

    submission = TutorAssessmentSubmission.from_dict(
        {
            "item_id": "i-1",
            "answer_text": "answer",
            "confidence": 99,
            "response_time_seconds": -5,
            "attempt_index": 999,
            "meta": {"raw": True},
        }
    )
    submission_rt = TutorAssessmentSubmission.from_dict(submission.to_dict())
    assert submission_rt.to_dict() == submission.to_dict()
    assert submission.confidence == 5
    assert submission.response_time_seconds == 0.0
    assert submission.attempt_index == 20

    result = TutorAssessmentResult.from_dict(
        {
            "item_id": "i-1",
            "outcome": "partial",
            "marks_awarded": 9.0,
            "marks_max": 2.0,
            "feedback": "ok",
            "error_tags": ["formula_error", ""],
            "misconception_tags": ["timing"],
            "retry_recommended": 1,
            "next_difficulty": "harder",
            "meta": {"s": 1},
        }
    )
    result_rt = TutorAssessmentResult.from_dict(result.to_dict())
    assert result_rt.to_dict() == result.to_dict()
    assert result.marks_awarded == 2.0


def test_contracts_round_trip_profile_intent_session_with_clamps():
    profile = TutorLearnerProfileSnapshot.from_dict(
        {
            "learner_id": "u1",
            "module": "m1",
            "confidence_calibration_bias": 999,
            "chat_to_quiz_transfer_score": -9,
            "misconception_tags_top": ["sign_error", ""],
            "meta": {"x": 1},
        }
    )
    profile_rt = TutorLearnerProfileSnapshot.from_dict(profile.to_dict())
    assert profile_rt.to_dict() == profile.to_dict()
    assert profile.confidence_calibration_bias == 5.0
    assert profile.chat_to_quiz_transfer_score == -1.0

    intent = TutorActionIntent.from_dict(
        {
            "action": "start_quiz",
            "duration_minutes": 9999,
            "confidence": 9.0,
            "requires_confirmation": 1,
            "evidence": ["due", ""],
            "meta": {"y": 2},
        }
    )
    intent_rt = TutorActionIntent.from_dict(intent.to_dict())
    assert intent_rt.to_dict() == intent.to_dict()
    assert intent.duration_minutes == 360
    assert intent.confidence == 1.0

    session = TutorSessionState.from_dict(
        {
            "session_id": "s1",
            "module": "m1",
            "topic": "npv",
            "practice_streak": -3,
            "recent_failures": 999999,
            "target_concepts": ["timing", ""],
            "active": 1,
            "meta": {"z": 3},
        }
    )
    session_rt = TutorSessionState.from_dict(session.to_dict())
    assert session_rt.to_dict() == session.to_dict()
    assert session.practice_streak == 0
    assert session.recent_failures == 10_000
