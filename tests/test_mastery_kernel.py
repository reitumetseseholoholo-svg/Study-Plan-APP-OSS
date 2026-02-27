from studyplan.cognitive_state import CognitiveState, CompetencyPosterior
from studyplan.mastery_kernel import MasteryKernel


class _DummyEngine:
    CHAPTER_FLOW = {
        "Topic B": ["Topic A"],
    }


def test_mastery_kernel_updates_beta_posterior_and_struggle_flags():
    state = CognitiveState()
    kernel = MasteryKernel(_DummyEngine(), state)

    kernel.record_attempt(
        chapter="Topic B",
        question_id="q:test",
        correct=False,
        latency_ms=2500.0,
        hints_used=2,
    )
    post = state.posteriors["Topic B"]
    assert isinstance(post, CompetencyPosterior)
    assert post.beta > 2.0
    assert state.struggle_mode is True
    assert state.working_memory.struggle_flags["error_streak"] is True
    assert state.working_memory.struggle_flags["hint_dependency"] is True
    assert state.confusion_links.get("Topic B") == {"Topic A"}


def test_mastery_kernel_correct_attempt_increases_alpha_and_clears_error_streak():
    state = CognitiveState()
    state.working_memory.struggle_flags["error_streak"] = True
    kernel = MasteryKernel(_DummyEngine(), state)

    kernel.record_attempt(
        chapter="Topic A",
        question_id="q:ok",
        correct=True,
        latency_ms=12000.0,
        hints_used=0,
    )
    post = state.posteriors["Topic A"]
    assert post.alpha > 2.0
    assert post.last_observation
    assert state.working_memory.struggle_flags["error_streak"] is False
    assert state.working_memory.active_question_id == "q:ok"
    summary = kernel.get_posterior_summary("Topic A")
    assert 0.0 <= summary["mean"] <= 1.0


def test_mastery_kernel_records_misconception_and_remediation_for_fast_error():
    state = CognitiveState()
    kernel = MasteryKernel(_DummyEngine(), state)

    kernel.record_attempt(
        chapter="Topic B",
        question_id="q:fast-wrong",
        correct=False,
        latency_ms=1500.0,
        hints_used=0,
    )

    chapter_counts = state.misconception_counts.get("Topic B", {})
    assert chapter_counts.get("impulsive_formula_selection", 0) >= 1
    remediation = str(state.remediation_by_chapter.get("Topic B", "")).strip().lower()
    assert "formula" in remediation or "requirement" in remediation
