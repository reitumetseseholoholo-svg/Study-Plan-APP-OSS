from __future__ import annotations

from gi.repository import Gtk

from ._panel_base import GTK4StatusPanel


class UserProfileWidget(GTK4StatusPanel):
    """Displays the learner profile snapshot with key preferences and analytics."""

    def __init__(self, main_window: Gtk.ApplicationWindow) -> None:
        super().__init__(
            main_window,
            title="User Profile",
            intro="Your learner profile, preferences, and session analytics.",
        )
        self.update_display()

    def update_display(self) -> None:
        learner_store = self.main_window.get_learner_store()
        profile = learner_store.get_or_create_profile(learner_id="default", module="ACCA")

        misconceptions = ", ".join(profile.misconception_tags_top) if profile.misconception_tags_top else "none"
        weak_caps = ", ".join(profile.weak_capabilities_top) if profile.weak_capabilities_top else "none"
        last_updated = profile.last_updated_ts or "never"
        last_outcome = profile.last_practice_outcome or "none"

        lines = [
            "── Identity ──",
            f"Learner ID: {profile.learner_id or 'default'}",
            f"Module: {profile.module or 'ACCA'}",
            "",
            "── Preferences ──",
            f"Explanation style: {profile.preferred_explanation_style}",
            f"Response speed tier: {profile.response_speed_tier}",
            "",
            "── Analytics ──",
            f"Confidence calibration bias: {profile.confidence_calibration_bias:+.2f}",
            f"Chat-to-quiz transfer score: {profile.chat_to_quiz_transfer_score:.2f}",
            f"Last practice outcome: {last_outcome}",
            f"Last updated: {last_updated}",
            "",
            "── Learning Gaps ──",
            f"Top misconceptions: {misconceptions}",
            f"Weak capabilities: {weak_caps}",
        ]
        self.set_body("\n".join(lines))
