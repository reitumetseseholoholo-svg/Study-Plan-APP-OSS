from __future__ import annotations

from gi.repository import Gtk

from studyplan.practice_loop_controller import PracticeLoopSessionState
from studyplan.hint_system import HintBank

from ._panel_base import GTK4StatusPanel


class HintSystemWidget(GTK4StatusPanel):
    def __init__(self, main_window: Gtk.ApplicationWindow) -> None:
        super().__init__(
            main_window,
            title="Hint System",
            intro="Progressive hints are generated from the current practice item.",
        )
        self.update_display()

    def update_display(self) -> None:
        practice_session = getattr(self.main_window, "practice_session", None)
        item = getattr(practice_session, "current_item", None)
        if item is None:
            self.set_body("Start a practice session to unlock progressive hints.")
            return

        result = getattr(practice_session, "current_result", None)
        loop_state = practice_session._create_loop_state() if hasattr(practice_session, "_create_loop_state") else None
        if isinstance(loop_state, PracticeLoopSessionState):
            hint = self.main_window.get_practice_controller().get_next_hint(
                loop_state,
                item,
                has_attempted=result is not None,
                error_tags=getattr(result, "error_tags", ()) if result is not None else (),
            )
        else:
            bank = HintBank(
                topic=item.topic,
                concept=item.prompt[:50] if item.prompt else "concept",
                item_type=item.item_type or "short_answer",
                expected_answer="",
                error_tags=getattr(result, "error_tags", ()) if result is not None else (),
            )
            hint = bank.get_hint(0)

        lines = [
            f"Topic: {item.topic}",
            f"Hint level: {hint.level + 1}/5",
            f"Label: {hint.label}",
            "",
            hint.text,
        ]
        self.set_body("\n".join(lines))
