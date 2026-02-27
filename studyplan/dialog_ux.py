from dataclasses import dataclass
from enum import Enum
from typing import Any


class DisclosureLevel(str, Enum):
    """Progressive disclosure levels for tutor feedback."""
    SUMMARY = "summary"          # Only primary action + brief feedback
    STANDARD = "standard"        # Summary + details
    DEBUG = "debug"              # Everything (for dev/instructor)


@dataclass
class DialogFeedback:
    """Layered feedback for progressive disclosure."""
    
    primary_action: str           # e.g., "Try a different approach" (non-technical)
    summary_text: str             # Short, encouraging message
    details_text: str = ""        # Deeper explanation (hidden by default)
    debug_info: dict[str, Any] | None = None  # For dev only
    color_hint: str = "neutral"   # "success", "warning", "error" 
    keyboard_shortcut: str = ""   # e.g., "h" for hint, "s" for show details
    
    def render(self, level: DisclosureLevel = DisclosureLevel.STANDARD) -> dict[str, Any]:
        """Render feedback at requested disclosure level."""
        base = {
            "primary_action": self.primary_action,
            "summary": self.summary_text,
            "color": self.color_hint,
            "keyboard": self.keyboard_shortcut,
        }
        
        if level in {DisclosureLevel.STANDARD, DisclosureLevel.DEBUG}:
            base["details"] = self.details_text
        
        if level == DisclosureLevel.DEBUG and self.debug_info:
            base["debug"] = self.debug_info
        
        return base


class TutorDialogRenderer:
    """Formats assessment results and tutor responses for progressive disclosure."""
    
    @staticmethod
    def render_assessment_feedback(
        outcome: str,
        marks_awarded: float,
        marks_max: float,
        feedback_text: str,
        error_tags: tuple[str, ...] = (),
        disclosure: DisclosureLevel = DisclosureLevel.STANDARD,
    ) -> DialogFeedback:
        """Convert assessment result into progressive disclosure feedback."""
        
        # Primary action based on outcome
        if outcome == "correct":
            primary = "Great work! Move to the next question."
            color = "success"
            summary = f"✓ Correct. You earned {marks_awarded}/{marks_max} marks."
        elif outcome == "partial":
            primary = "You're on the right track—review the details."
            color = "warning"
            summary = f"⊗ Partial credit: {marks_awarded}/{marks_max} marks."
        else:  # incorrect
            primary = "Not quite. Give it another try or ask for a hint."
            color = "error"
            summary = f"✗ Incorrect. Let's learn from this."
        
        # Detail text (non-technical explanation)
        details = feedback_text or "Review the concept and try again."
        if error_tags:
            details += f"\n\nHint: Focus on {', '.join(error_tags[:2])}."
        
        # Debug info (for instructors)
        debug = {
            "outcome": outcome,
            "marks": {"awarded": marks_awarded, "max": marks_max},
            "error_tags": list(error_tags),
        }
        
        return DialogFeedback(
            primary_action=primary,
            summary_text=summary,
            details_text=details,
            debug_info=debug,
            color_hint=color,
            keyboard_shortcut="h" if outcome != "correct" else "",
        )
    
    @staticmethod
    def render_tutor_response(
        response_text: str,
        mode: str = "teach",
        disclosure: DisclosureLevel = DisclosureLevel.STANDARD,
    ) -> DialogFeedback:
        """Format tutor response with keyboard navigation hints."""
        
        action_map = {
            "teach": "Read the explanation below.",
            "guided_practice": "Try the practice question.",
            "error_clinic": "Review the error and try again.",
            "challenge": "Solve this stretch question.",
        }
        
        primary = action_map.get(mode, "Read the response.")
        
        return DialogFeedback(
            primary_action=primary,
            summary_text=response_text[:100] + ("..." if len(response_text) > 100 else ""),
            details_text=response_text,
            color_hint="neutral",
            keyboard_shortcut="n",  # next
        )

    @staticmethod
    def _confidence_band(evidence_confidence: float) -> tuple[str, str]:
        score = max(0.0, min(1.0, float(evidence_confidence or 0.0)))
        if score >= 0.8:
            return "High confidence", "Grounded in syllabus-linked evidence."
        if score >= 0.6:
            return "Moderate confidence", "Mostly grounded; verify key assumptions."
        return "Low confidence", "Limited grounding; verify with syllabus before relying on this."

    @staticmethod
    def render_grounded_tutor_response(
        response_text: str,
        *,
        mode: str = "teach",
        evidence_confidence: float = 0.0,
        citations_count: int = 0,
    ) -> DialogFeedback:
        """Render tutor response with learner-trust confidence wording."""
        base = TutorDialogRenderer.render_tutor_response(response_text=response_text, mode=mode)
        band, note = TutorDialogRenderer._confidence_band(evidence_confidence)
        cits = max(0, int(citations_count or 0))
        evidence_line = f"{band}. {note} Citations used: {cits}."
        details = f"{base.details_text}\n\nEvidence: {evidence_line}".strip()
        return DialogFeedback(
            primary_action=base.primary_action,
            summary_text=f"{base.summary_text} [{band}]",
            details_text=details,
            debug_info={
                "evidence_confidence": max(0.0, min(1.0, float(evidence_confidence or 0.0))),
                "citations_count": cits,
            },
            color_hint=base.color_hint,
            keyboard_shortcut=base.keyboard_shortcut,
        )

    @staticmethod
    def render_next_action_guidance(
        *,
        outcome: str,
        reason: str,
        next_action: str,
        urgent: bool = False,
    ) -> DialogFeedback:
        """Render explicit next-step guidance for the practice loop."""
        outcome_key = str(outcome or "").strip().lower()
        color = "neutral"
        if outcome_key == "correct":
            color = "success"
        elif outcome_key == "partial":
            color = "warning"
        elif outcome_key == "incorrect":
            color = "error"
        urgency_prefix = "Now: " if bool(urgent) else "Next: "
        summary = f"{urgency_prefix}{next_action}"
        details = f"Reason: {str(reason or 'No reason provided.').strip()}"
        return DialogFeedback(
            primary_action=next_action,
            summary_text=summary,
            details_text=details,
            color_hint=color,
            keyboard_shortcut="n",
        )
