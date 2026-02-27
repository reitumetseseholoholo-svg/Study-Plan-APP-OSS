from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cognitive_state import CognitiveState


SOCRATIC_PERMISSION_VALUES = {"socratic_only", "hint_ok", "explain_ok"}


@dataclass(frozen=True)
class SocraticDecision:
    state: str
    permission: str


class SocraticFSM:
    STATES = ("DIAGNOSE", "PRODUCTIVE_STRUGGLE", "SCAFFOLD", "CONSOLIDATE", "REFLECT", "CHALLENGE")

    def __init__(self, cognitive_state: CognitiveState):
        self._state = cognitive_state

    def transition(self, event: str, metadata: dict[str, Any] | None = None) -> SocraticDecision:
        meta = metadata if isinstance(metadata, dict) else {}
        current = self._normalize_state(self._state.working_memory.socratic_state)
        event_key = str(event or "").strip().upper()
        topic = str(meta.get("chapter", self._state.working_memory.active_chapter) or "").strip()
        load_score = self._safe_load_score()
        if self._state.quiz_active and event_key == "TUTOR_REQUEST":
            return self._apply("PRODUCTIVE_STRUGGLE")
        posterior = self._state.posteriors.get(topic) if topic else None
        mastery = posterior.mean if posterior is not None else None
        variance = posterior.variance if posterior is not None else None
        if event_key == "REFLECTION_DONE":
            if mastery is not None and mastery >= 0.85 and load_score < 0.72 and not bool(self._state.struggle_mode):
                return self._apply("CHALLENGE")
            return self._apply("CONSOLIDATE")
        if event_key in {"QUIZ_START", "REVIEW_START"}:
            return self._apply("PRODUCTIVE_STRUGGLE")
        if event_key in {"QUIZ_END", "REVIEW_END"}:
            if mastery is not None and mastery >= 0.8:
                return self._apply("CHALLENGE")
            return self._apply("DIAGNOSE")
        if event_key in {"ERROR", "INCORRECT_ATTEMPT"}:
            return self._apply("PRODUCTIVE_STRUGGLE")
        if event_key in {"CORRECT_ATTEMPT", "PARTIAL_CORRECT"}:
            if current == "PRODUCTIVE_STRUGGLE":
                return self._apply("SCAFFOLD")
            if self._has_reflection_prompt() and mastery is not None and mastery >= 0.65:
                return self._apply("REFLECT")
            if mastery is not None and mastery >= 0.85 and not bool(self._state.struggle_mode):
                return self._apply("CHALLENGE")
            return self._apply("CONSOLIDATE")
        if mastery is not None:
            if bool(self._state.struggle_mode) or mastery < 0.40 or load_score >= 0.72:
                return self._apply("PRODUCTIVE_STRUGGLE")
            if mastery > 0.85 and not bool(self._state.struggle_mode) and load_score < 0.72:
                return self._apply("CHALLENGE")
            if current == "PRODUCTIVE_STRUGGLE" and mastery >= 0.55:
                return self._apply("SCAFFOLD")
            if variance is not None and variance <= 0.02 and mastery >= 0.65:
                if self._has_reflection_prompt():
                    return self._apply("REFLECT")
                return self._apply("CONSOLIDATE")
        return self._apply(current)

    def get_system_prompt_suffix(self) -> str:
        state = self._normalize_state(self._state.working_memory.socratic_state)
        load_score = self._safe_load_score()
        load_hint = ""
        if load_score >= 0.72:
            load_hint = " Keep response chunks short and ask one step at a time."
        elif load_score >= 0.42:
            load_hint = " Use compact steps and frequent checks."
        constraint = {
            "DIAGNOSE": "Ask one specific clarifying question first. Do not explain the full concept yet.",
            "PRODUCTIVE_STRUGGLE": "Guide via Socratic questioning only. Do not give the direct answer. Keep responses brief.",
            "SCAFFOLD": "Provide a hint or partial step, then ask what comes next.",
            "CONSOLIDATE": "Confirm understanding with a quick check before moving on.",
            "REFLECT": "Ask for a brief self-explanation of the strategy and one boundary condition where it fails.",
            "CHALLENGE": "Present a harder variant, edge case, or transfer application. Be concise.",
        }.get(state, "Use guided tutoring and check understanding.")
        return f"[Socratic state: {state}] {constraint}{load_hint}"

    def _apply(self, state: str) -> SocraticDecision:
        normalized = self._normalize_state(state)
        self._state.working_memory.socratic_state = normalized
        permission = self._permission_for_state(normalized)
        return SocraticDecision(state=normalized, permission=permission)

    def _normalize_state(self, state: str | None) -> str:
        candidate = str(state or "").strip().upper()
        if candidate in self.STATES:
            return candidate
        return "DIAGNOSE"

    def _permission_for_state(self, state: str) -> str:
        permission = {
            "DIAGNOSE": "socratic_only",
            "PRODUCTIVE_STRUGGLE": "socratic_only",
            "SCAFFOLD": "hint_ok",
            "CONSOLIDATE": "explain_ok",
            "REFLECT": "hint_ok",
            "CHALLENGE": "explain_ok",
        }.get(state, "hint_ok")
        if permission not in SOCRATIC_PERMISSION_VALUES:
            return "hint_ok"
        return permission

    def _has_reflection_prompt(self) -> bool:
        prompt = self._state.peek_reflection_prompt()
        return isinstance(prompt, str) and bool(prompt.strip())

    def _safe_load_score(self) -> float:
        try:
            return max(0.0, min(1.0, float(getattr(self._state, "cognitive_load_score", 0.0) or 0.0)))
        except Exception:
            return 0.0
