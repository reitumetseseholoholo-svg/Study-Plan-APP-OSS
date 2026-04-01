from __future__ import annotations

from gi.repository import Gtk

from ._panel_base import GTK4StatusPanel


class CognitiveDashboard(GTK4StatusPanel):
    def __init__(self, main_window: Gtk.ApplicationWindow) -> None:
        super().__init__(
            main_window,
            title="Cognitive Dashboard",
            intro="Learning state, topic confidence, and session signals appear here.",
        )
        self.update_display()

    def update_display(self) -> None:
        state = self.main_window.get_cognitive_state()
        practice_session = getattr(self.main_window, "practice_session", None)
        current_topic = getattr(getattr(practice_session, "current_item", None), "topic", "General")
        posteriors = sorted(state.posteriors.items(), key=lambda item: item[1].mean, reverse=True)

        lines = [
            f"Current topic: {current_topic}",
            f"Quiz active: {'yes' if state.quiz_active else 'no'}",
            f"Struggle mode: {'yes' if state.struggle_mode else 'no'}",
            f"Working memory state: {state.working_memory.socratic_state}",
            f"Active question: {state.working_memory.active_question_id or 'none'}",
            "",
            "Top topic posteriors:",
        ]
        if posteriors:
            lines.extend(f"- {topic}: {posterior.mean:.0%} mean confidence" for topic, posterior in posteriors[:5])
        else:
            lines.append("- No topic posteriors yet.")

        self.set_body("\n".join(lines))
