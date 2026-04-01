from __future__ import annotations

from typing import Any

from .cognitive_state import CognitiveState
from .state_locking import bind_cognitive_state_lock, locked_cognitive_state


class WorkingMemoryService:
    def __init__(self, cognitive_state: CognitiveState, state_lock: Any | None = None):
        self._state = cognitive_state
        self._state_lock = bind_cognitive_state_lock(cognitive_state, state_lock)

    @property
    def cognitive_state(self) -> CognitiveState:
        return self._state

    def capture_attempt(
        self,
        chapter: str,
        question_id: str | None,
        correct: bool,
        *,
        latency_ms: float | None = None,
        hints_used: int = 0,
    ) -> None:
        chapter_name = str(chapter or "").strip()
        qid = str(question_id or "").strip()
        if not chapter_name:
            return
        with locked_cognitive_state(self._state, self._state_lock):
            mark = "✓" if bool(correct) else "✗"
            row = f"{mark} {chapter_name}"
            if qid:
                row += f" [{qid}]"
            self._state.working_memory.push_context(row)
            self._state.working_memory.active_chapter = chapter_name
            flags = self._state.working_memory.struggle_flags
            if not bool(correct):
                flags["error_streak"] = True
            elif bool(flags.get("error_streak", False)):
                flags["error_streak"] = False
            try:
                latency_val = float(latency_ms) if latency_ms is not None else 0.0
            except Exception:
                latency_val = 0.0
            if latency_val > 0.0:
                flags["latency_spike"] = latency_val >= 45000.0
            try:
                hints = int(hints_used or 0)
            except Exception:
                hints = 0
            flags["hint_dependency"] = hints >= 2

    def set_active_question(
        self,
        *,
        chapter: str,
        question_id: str | None = None,
    ) -> None:
        with locked_cognitive_state(self._state, self._state_lock):
            chapter_name = str(chapter or "").strip()
            if chapter_name:
                self._state.working_memory.active_chapter = chapter_name
            qid = str(question_id or "").strip()
            self._state.working_memory.active_question_id = qid or None
            self._state.quiz_active = True

    def clear_active_question(self) -> None:
        with locked_cognitive_state(self._state, self._state_lock):
            self._state.quiz_active = False
            self._state.working_memory.active_question_id = None

    def get_context_string(self, max_items: int = 2) -> str:
        with locked_cognitive_state(self._state, self._state_lock):
            wm = self._state.working_memory
            rows: list[str] = []
            try:
                cap = max(1, min(4, int(max_items)))
            except Exception:
                cap = 2
            chunks = [str(v).strip() for v in list(wm.context_chunks or []) if str(v).strip()]
            if chunks:
                rows.append("Recent session attempts:")
                rows.extend([f"- {item}" for item in chunks[-cap:]])
            if wm.active_chapter:
                rows.append(f"Active chapter: {wm.active_chapter}")
            if wm.active_question_id and self._state.quiz_active:
                rows.append("Quiz state: active question in progress (do not reveal direct answer)")
            if bool(wm.struggle_flags.get("error_streak", False)):
                rows.append("Signal: recent error streak; prioritize Socratic prompting and short hints.")
            if bool(wm.struggle_flags.get("hint_dependency", False)):
                rows.append("Signal: hint dependency detected; fade hints gradually.")
            if not rows:
                return ""
            return "\n".join(rows).strip()

    def apply_quiz_active(self, active: bool) -> None:
        with locked_cognitive_state(self._state, self._state_lock):
            self._state.quiz_active = bool(active)
            if not bool(active):
                self._state.working_memory.active_question_id = None

    def note_tutor_exchange(self, role: str, content: str) -> None:
        role_name = str(role or "").strip().lower()
        text = str(content or "").strip()
        if role_name not in {"user", "assistant"} or not text:
            return
        with locked_cognitive_state(self._state, self._state_lock):
            prefix = "U" if role_name == "user" else "T"
            clipped = text.replace("\n", " ").strip()
            if len(clipped) > 120:
                clipped = f"{clipped[:117].rstrip()}..."
            self._state.working_memory.push_context(f"{prefix}: {clipped}")
