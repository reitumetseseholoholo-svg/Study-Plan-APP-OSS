import pytest

from studyplan.dialog_ux import DialogFeedback, DisclosureLevel, TutorDialogRenderer


def test_feedback_render_summary_level():
    """Test summary disclosure hides details."""
    feedback = DialogFeedback(
        primary_action="Try again",
        summary_text="Not quite right",
        details_text="Here's why...",
        debug_info={"key": "value"},
    )
    rendered = feedback.render(DisclosureLevel.SUMMARY)
    assert "primary_action" in rendered
    assert "summary" in rendered
    assert "details" not in rendered
    assert "debug" not in rendered


def test_feedback_render_standard_level():
    """Test standard disclosure shows details but not debug."""
    feedback = DialogFeedback(
        primary_action="Try again",
        summary_text="Not quite right",
        details_text="Here's why...",
        debug_info={"key": "value"},
    )
    rendered = feedback.render(DisclosureLevel.STANDARD)
    assert "details" in rendered
    assert rendered["details"] == "Here's why..."
    assert "debug" not in rendered


def test_feedback_render_debug_level():
    """Test debug disclosure shows everything."""
    feedback = DialogFeedback(
        primary_action="Try again",
        summary_text="Not quite right",
        details_text="Here's why...",
        debug_info={"key": "value"},
    )
    rendered = feedback.render(DisclosureLevel.DEBUG)
    assert "details" in rendered
    assert "debug" in rendered
    assert rendered["debug"]["key"] == "value"


def test_assessment_feedback_correct():
    """Test feedback for correct answer is encouraging."""
    fb = TutorDialogRenderer.render_assessment_feedback(
        outcome="correct",
        marks_awarded=5.0,
        marks_max=5.0,
        feedback_text="Well done!",
    )
    assert "Great work" in fb.primary_action
    assert fb.color_hint == "success"
    assert "✓" in fb.summary_text


def test_assessment_feedback_incorrect():
    """Test feedback for incorrect answer is supportive."""
    fb = TutorDialogRenderer.render_assessment_feedback(
        outcome="incorrect",
        marks_awarded=0.0,
        marks_max=5.0,
        feedback_text="Try again",
        error_tags=("concept_gap", "precision"),
    )
    assert "another try" in fb.primary_action
    assert fb.color_hint == "error"
    assert "Focus on" in fb.details_text
    assert "concept_gap" in fb.details_text


def test_assessment_feedback_partial():
    """Test feedback for partial credit."""
    fb = TutorDialogRenderer.render_assessment_feedback(
        outcome="partial",
        marks_awarded=2.5,
        marks_max=5.0,
        feedback_text="You're close",
    )
    assert "right track" in fb.primary_action
    assert fb.color_hint == "warning"
    assert "2.5" in fb.summary_text


def test_tutor_response_teach_mode():
    """Test tutor response formatting for teach mode."""
    fb = TutorDialogRenderer.render_tutor_response(
        "Long explanation here about the concept.",
        mode="teach",
    )
    assert "Read the explanation" in fb.primary_action
    assert fb.details_text == "Long explanation here about the concept."
    # Summary is first 100 chars, so short text is not truncated
    assert "explanation" in fb.summary_text


def test_tutor_response_keyboard_nav():
    """Test keyboard shortcuts are set."""
    fb = TutorDialogRenderer.render_tutor_response(
        "Here's the answer.",
        mode="guided_practice",
    )
    assert fb.keyboard_shortcut == "n"


def test_grounded_tutor_response_includes_confidence_band_and_evidence():
    fb = TutorDialogRenderer.render_grounded_tutor_response(
        "NPV discounts future cash flows to present value.",
        mode="teach",
        evidence_confidence=0.86,
        citations_count=3,
    )
    assert "High confidence" in fb.summary_text
    assert "Evidence:" in fb.details_text
    assert "Citations used: 3" in fb.details_text


def test_next_action_guidance_is_explicit_and_colored():
    fb = TutorDialogRenderer.render_next_action_guidance(
        outcome="incorrect",
        reason="Recurring sign error detected.",
        next_action="Review remediation, then retry a similar question.",
        urgent=True,
    )
    assert fb.color_hint == "error"
    assert fb.summary_text.startswith("Now:")
    assert "Reason:" in fb.details_text
