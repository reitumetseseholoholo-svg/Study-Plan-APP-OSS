from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable


@dataclass
class TutorWorkspaceController:
    """Thin command boundary around tutor workspace runtime state."""

    run_state: Any

    def start_turn(
        self,
        *,
        user_prompt: str,
        model: str,
        cancel_event: threading.Event,
        set_running: Callable[[bool], None] | None = None,
        render_transcript: Callable[..., None] | None = None,
    ) -> int:
        state = self.run_state
        if hasattr(state, "begin_turn"):
            job_id = int(state.begin_turn(user_prompt=user_prompt, model=model, cancel_event=cancel_event))
        else:
            state["job_id"] = int(state.get("job_id", 0) or 0) + 1
            job_id = int(state.get("job_id", 0) or 0)
            state["cancel_event"] = cancel_event
            state["model"] = str(model or "")
            state["draft_user"] = str(user_prompt or "")
            state["draft_assistant"] = ""
        if hasattr(state, "reset_stream_runtime"):
            state.reset_stream_runtime()
        state["follow_live"] = True
        state["follow_manual_override"] = False
        if callable(set_running):
            set_running(True)
        if callable(render_transcript):
            render_transcript(force_scroll=True)
        return job_id

    def finish_turn(
        self,
        *,
        job_id: int,
        set_running: Callable[[bool], None] | None = None,
    ) -> tuple[str, str] | None:
        state = self.run_state
        drafts: tuple[str, str] | None
        if hasattr(state, "consume_turn_drafts_for_finish"):
            drafts = state.consume_turn_drafts_for_finish(job_id=job_id)
        else:
            if int(state.get("job_id", 0) or 0) != int(job_id):
                return None
            drafts = (
                str(state.get("draft_user", "") or "").strip(),
                str(state.get("draft_assistant", "") or "").strip(),
            )
            state["cancel_event"] = None
            state["draft_user"] = ""
            state["draft_assistant"] = ""
            state["turn_started_at"] = 0.0
            state["turn_user_prompt"] = ""
            state["turn_full_prompt"] = ""
            state["turn_model_candidates"] = []
            state["turn_llm_purpose"] = ""
            state["turn_backend"] = ""
            state.pop("auto_resume_mode", None)
        if drafts is None:
            return None
        if callable(set_running):
            set_running(False)
        return drafts

    def pause_turn(
        self,
        *,
        reason: str,
        pause_fn: Callable[..., dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        return pause_fn(reason=reason)

    def resume_turn(self) -> dict[str, Any] | None:
        state = self.run_state
        getter = getattr(state, "paused_tutor_turn", None)
        if not callable(getter):
            return None
        snapshot_any = getter()
        if snapshot_any is None:
            return None
        if not isinstance(snapshot_any, dict):
            return None
        clearer = getattr(state, "clear_paused_tutor_turn", None)
        if callable(clearer):
            clearer()
        return snapshot_any

    def discard_paused_turn(self) -> bool:
        state = self.run_state
        getter = getattr(state, "paused_tutor_turn", None)
        if not callable(getter):
            return False
        if getter() is None:
            return False
        clearer = getattr(state, "clear_paused_tutor_turn", None)
        if callable(clearer):
            clearer()
            return True
        return False
