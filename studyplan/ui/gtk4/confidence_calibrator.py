from __future__ import annotations

from gi.repository import Gtk

from ._panel_base import GTK4StatusPanel


class ConfidenceCalibratorWidget(GTK4StatusPanel):
    def __init__(self, main_window: Gtk.ApplicationWindow) -> None:
        super().__init__(
            main_window,
            title="Confidence Calibrator",
            intro="Calibration tracks how stated confidence matches actual outcomes.",
        )
        self.update_display()

    def update_display(self) -> None:
        practice_session = getattr(self.main_window, "practice_session", None)
        recent_result = getattr(practice_session, "current_result", None)
        total_attempts = int(getattr(practice_session, "total_attempts", 0) or 0)
        correct_count = int(getattr(practice_session, "correct_count", 0) or 0)
        accuracy = (correct_count / total_attempts * 100.0) if total_attempts else 0.0
        confidence = int(getattr(getattr(practice_session, "confidence_slider", None), "get_value", lambda: 3.0)())
        perf_report = self.main_window.get_performance_monitor().report()

        lines = [
            f"Current confidence slider: {confidence}/5",
            f"Session accuracy: {accuracy:.1f}%",
            f"Total graded attempts: {total_attempts}",
            f"Recent outcome: {getattr(recent_result, 'outcome', 'none') or 'none'}",
            "",
            "Performance monitor:",
            f"- Recorded operations: {perf_report.get('total_recorded', 0)}",
            f"- Budget exceeded: {perf_report.get('budget_exceeded', 0)}",
        ]
        self.set_body("\n".join(lines))
