from __future__ import annotations

import datetime
from typing import Any

from .cognitive_state import CognitiveState, CompetencyPosterior
from .state_locking import bind_cognitive_state_lock, locked_cognitive_state


class MasteryKernel:
    """Shadow-mode Bayesian mastery updates for cognitive runtime only.

    This does not replace legacy SRS scheduling. It updates cognitive posteriors,
    struggle flags, and confusion links to improve tutoring policy decisions.
    """

    def __init__(self, engine: Any, cognitive_state: CognitiveState, state_lock: Any | None = None):
        self.engine = engine
        self.cognitive_state = cognitive_state
        self._state_lock = bind_cognitive_state_lock(cognitive_state, state_lock)

    def record_attempt(
        self,
        *,
        chapter: str,
        question_id: str | None = None,
        correct: bool,
        latency_ms: float | None = None,
        hints_used: int = 0,
    ) -> None:
        chapter_name = str(chapter or "").strip()
        if not chapter_name:
            return
        with locked_cognitive_state(self.cognitive_state, self._state_lock):
            post = self.cognitive_state.posteriors.get(chapter_name)
            if not isinstance(post, CompetencyPosterior):
                post = CompetencyPosterior()
                self.cognitive_state.posteriors[chapter_name] = post

            try:
                latency_val = float(latency_ms) if latency_ms is not None else 0.0
            except Exception:
                latency_val = 0.0
            try:
                hints = max(0, int(hints_used or 0))
            except Exception:
                hints = 0

            attention = self._attention_weight(latency_val)
            hint_discount = 0.7 ** hints
            post.hint_penalty = max(0.0, min(1.0, float(post.hint_penalty) * float(hint_discount)))

            if bool(correct):
                weight = float(attention) * (1.0 if hints <= 0 else 0.5)
                post.alpha = max(0.5, float(post.alpha) + max(0.1, weight))
            else:
                post.beta = max(0.5, float(post.beta) + 1.0)
                self._update_confusion_links(chapter_name, latency_val)
            post.last_observation = datetime.datetime.now().isoformat(timespec="seconds")

            self._update_struggle_signals(
                chapter=chapter_name,
                correct=bool(correct),
                latency_ms=latency_val,
                hints_used=hints,
            )

            wm = self.cognitive_state.working_memory
            if chapter_name:
                wm.active_chapter = chapter_name
            if question_id:
                wm.active_question_id = str(question_id)

    def get_posterior_summary(self, chapter: str) -> dict[str, float]:
        chapter_name = str(chapter or "").strip()
        with locked_cognitive_state(self.cognitive_state, self._state_lock):
            post = self.cognitive_state.posteriors.get(chapter_name)
        if not isinstance(post, CompetencyPosterior):
            return {"mean": 0.5, "variance": 0.0, "alpha": 0.0, "beta": 0.0}
        return {
            "mean": float(post.mean),
            "variance": float(post.variance),
            "alpha": float(post.alpha),
            "beta": float(post.beta),
        }

    def _attention_weight(self, latency_ms: float) -> float:
        if latency_ms <= 0.0:
            return 1.0
        scaled = float(latency_ms) / 10000.0
        return 1.0 / (1.0 + (scaled * scaled))

    def _update_confusion_links(self, chapter: str, latency_ms: float) -> None:
        # Fast wrong answers often indicate misconception/confusion, not slow uncertainty.
        if latency_ms <= 0.0 or latency_ms > 5000.0:
            return
        raw_flow = getattr(self.engine, "CHAPTER_FLOW", {})
        if not isinstance(raw_flow, dict):
            return
        prereqs = raw_flow.get(chapter)
        if not isinstance(prereqs, (list, tuple, set)):
            return
        links = self.cognitive_state.confusion_links.setdefault(chapter, set())
        for item in prereqs:
            text = str(item or "").strip()
            if text:
                links.add(text)

    def _update_struggle_signals(
        self,
        *,
        chapter: str,
        correct: bool,
        latency_ms: float,
        hints_used: int,
    ) -> None:
        wm = self.cognitive_state.working_memory
        wm.struggle_flags["latency_spike"] = bool(latency_ms >= 45000.0) if latency_ms > 0.0 else bool(
            wm.struggle_flags.get("latency_spike", False)
        )
        if correct:
            wm.struggle_flags["error_streak"] = False
        else:
            wm.struggle_flags["error_streak"] = True
        wm.struggle_flags["hint_dependency"] = bool(hints_used >= 2)

        fast_error = (not correct) and latency_ms > 0.0 and latency_ms < 3000.0
        self.cognitive_state.struggle_mode = bool(
            fast_error
            or wm.struggle_flags.get("hint_dependency", False)
            or wm.struggle_flags.get("error_streak", False)
        )
