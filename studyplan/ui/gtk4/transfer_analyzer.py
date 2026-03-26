from __future__ import annotations

from gi.repository import Gtk

from ._panel_base import GTK4StatusPanel


class TransferAnalyzerWidget(GTK4StatusPanel):
    def __init__(self, main_window: Gtk.ApplicationWindow) -> None:
        super().__init__(
            main_window,
            title="Transfer Analyzer",
            intro="Transfer tasks become available once a concept is answered correctly.",
        )
        self.update_display()

    def update_display(self) -> None:
        practice_session = getattr(self.main_window, "practice_session", None)
        item = getattr(practice_session, "current_item", None)
        result = getattr(practice_session, "current_result", None)

        if item is None:
            self.set_body("Complete a practice item to generate a transfer check.")
            return

        lines = [
            f"Current topic: {item.topic}",
            f"Latest outcome: {getattr(result, 'outcome', 'none') or 'none'}",
        ]

        if getattr(result, "outcome", "") == "correct":
            transfer_task = self.main_window.get_practice_controller().generate_transfer_task(item)
            lines.extend(["", "Suggested transfer task:", transfer_task])
        else:
            lines.extend(["", "Finish the current concept cleanly to unlock transfer analysis."])

        self.set_body("\n".join(lines))
