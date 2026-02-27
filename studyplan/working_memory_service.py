from __future__ import annotations

from .cognitive_state import CognitiveState


class WorkingMemoryService:
    """Service for managing working memory and cognitive state transitions."""

    # Thresholds and limits
    LATENCY_SPIKE_MS = 45000.0  # 45 seconds
    MAX_HINTS_BEFORE_DEPENDENCY = 2
    MAX_CONTEXT_PREVIEW_CHARS = 120
    MAX_CONTEXT_ITEMS = 4
    DEFAULT_CONTEXT_ITEMS = 2
    REFLECTION_MAX_QUEUE = 8
    LOAD_HISTORY_MAX = 24
    MAX_DUAL_CODING_AIDS = 4
    DEFAULT_DUAL_CODING_AIDS = 2
    _DUAL_CODING_TOPIC_AIDS: tuple[tuple[str, str], ...] = (
        ("wacc", "Build a debt/equity weighting table and verify weights sum to 100%."),
        ("capm", "Sketch a return bridge: risk-free rate + beta x market risk premium."),
        ("npv", "Draw a cash-flow timeline, then map each flow to its discount period."),
        ("irr", "Use a sign-change timeline and interpolation table to bracket IRR."),
        ("discount", "Create a period/discount-factor table before computing present values."),
        ("working capital", "Map a cash-conversion-cycle timeline (inventory -> receivables -> payables)."),
        ("inventory", "Draw an inventory flow chart with reorder and holding cost points."),
        ("ar/ap", "Use an aging ladder for receivables/payables with collection/payment bands."),
        ("risk", "Use a best/base/worst scenario tree and annotate key assumptions."),
        ("fx", "Draw currency inflow/outflow lanes and hedge coverage by period."),
        ("ratio", "Build a ratio bridge table (profitability, liquidity, gearing, efficiency)."),
        ("valuation", "Use a value-driver tree linking cash flow, discount rate, and terminal value."),
    )
    _DUAL_CODING_MISCONCEPTION_AIDS: tuple[tuple[str, str], ...] = (
        ("timing", "Redraw the timeline and place every cash flow before discounting."),
        ("weight", "Rebuild the weighting table and reconcile to 100% before computing WACC."),
        ("sign", "Mark signs (+/-) explicitly in a calculation table to prevent direction errors."),
        ("units", "Add units to each line (%, years, currency) and check consistency."),
        ("assumption", "List assumptions in a 2-column table: stated vs implied."),
        ("formula", "Create a formula map with inputs and one worked numeric substitution."),
    )

    def __init__(self, cognitive_state: CognitiveState) -> None:
        self._state = cognitive_state

    @property
    def cognitive_state(self) -> CognitiveState:
        """Get the underlying cognitive state."""
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
        """Record a quiz attempt in working memory and update struggle flags."""
        chapter_name = str(chapter or "").strip()
        qid = str(question_id or "").strip()
        if not chapter_name:
            return
        mark = "✓" if correct else "✗"
        row = f"{mark} {chapter_name}"
        if qid:
            row += f" [{qid}]"
        self._state.working_memory.push_context(row)
        self._state.working_memory.active_chapter = chapter_name
        flags = self._state.working_memory.struggle_flags

        # Update error streak flag.
        if not correct:
            flags["error_streak"] = True
        elif flags.get("error_streak"):
            flags["error_streak"] = False

        # Process latency.
        if latency_ms is not None:
            try:
                latency_val = float(latency_ms)
                if latency_val > 0.0:
                    flags["latency_spike"] = latency_val >= self.LATENCY_SPIKE_MS
            except (ValueError, TypeError):
                pass

        # Process hints.
        try:
            hints = int(hints_used or 0)
            flags["hint_dependency"] = hints >= self.MAX_HINTS_BEFORE_DEPENDENCY
        except (ValueError, TypeError):
            hints = 0
            flags["hint_dependency"] = False

        # Adaptive hint fading signal by chapter.
        level = self._state.adapt_hint_fade_level(
            chapter_name,
            correct=bool(correct),
            hints_used=int(hints),
        )
        self._state.working_memory.push_context(f"H{level} {chapter_name}: hint support level")

        # Metacognitive reflection prompts after stable success.
        reflection = self._build_reflection_prompt(
            chapter=chapter_name,
            correct=bool(correct),
            hints_used=int(hints),
            latency_ms=latency_ms,
        )
        if reflection:
            self._state.queue_reflection_prompt(reflection, max_items=self.REFLECTION_MAX_QUEUE)
            self._state.working_memory.push_context(f"R: {reflection}")

        # Cognitive load estimation for adaptive tutoring/chunking.
        load_score = self._estimate_cognitive_load(
            correct=bool(correct),
            hints_used=int(hints),
            latency_ms=latency_ms,
        )
        self._state.set_cognitive_load(load_score, max_items=self.LOAD_HISTORY_MAX)
        if load_score >= 0.72:
            self._state.struggle_mode = True

    def set_active_question(
        self,
        *,
        chapter: str,
        question_id: str | None = None,
    ) -> None:
        """Set the currently active question."""
        chapter_name = str(chapter or "").strip()
        if chapter_name:
            self._state.working_memory.active_chapter = chapter_name
        qid = str(question_id or "").strip()
        self._state.working_memory.active_question_id = qid or None
        self._state.quiz_active = True

    def clear_active_question(self) -> None:
        """Clear the active question state."""
        self._state.quiz_active = False
        self._state.working_memory.active_question_id = None

    def get_context_string(self, max_items: int | None = None) -> str:
        """Build a context string for LLM prompting from working memory state."""
        wm = self._state.working_memory
        rows: list[str] = []

        try:
            dynamic_default = self._adaptive_context_items()
            raw_items = dynamic_default if max_items is None else int(max_items)
            cap = max(1, min(self.MAX_CONTEXT_ITEMS, raw_items))
        except (ValueError, TypeError):
            cap = self.DEFAULT_CONTEXT_ITEMS

        chunks = [str(v).strip() for v in list(wm.context_chunks or []) if str(v).strip()]
        if chunks:
            rows.append("Recent session attempts:")
            rows.extend(f"- {item}" for item in chunks[-cap:])
        if wm.active_chapter:
            rows.append(f"Active chapter: {wm.active_chapter}")
        if wm.active_question_id and self._state.quiz_active:
            rows.append("Quiz state: active question in progress (do not reveal direct answer)")
        if wm.struggle_flags.get("error_streak"):
            rows.append("Signal: recent error streak; prioritize Socratic prompting and short hints.")
        if wm.struggle_flags.get("hint_dependency"):
            rows.append("Signal: hint dependency detected; fade hints gradually.")
        if wm.active_chapter:
            level = self._state.get_hint_fade_level(wm.active_chapter, default=2)
            rows.append(f"Hint support level: H{level} (H1=minimal, H4=guided)")
            remediation = str(self._state.remediation_by_chapter.get(wm.active_chapter, "")).strip()
            if remediation:
                rows.append(f"Remediation focus: {remediation}")
            top_mis = self._state.top_misconceptions(wm.active_chapter, limit=2)
            if top_mis:
                rows.append(f"Misconception pattern: {', '.join(top_mis)}")
            aids = self.get_dual_coding_aids(chapter=wm.active_chapter, limit=2)
            if aids:
                rows.append("Dual-coding aids: " + " | ".join(aids))
        latest_reflection = self._state.peek_reflection_prompt()
        if latest_reflection:
            rows.append(f"Reflection prompt: {latest_reflection}")
        load_score = float(getattr(self._state, "cognitive_load_score", 0.0) or 0.0)
        load_band = self._state.get_cognitive_load_band(load_score)
        rows.append(f"Cognitive load: {load_band} ({load_score:.2f})")
        if not rows:
            return ""
        return "\n".join(rows)

    def apply_quiz_active(self, active: bool) -> None:
        """Update quiz active state and clean up question ID if inactive."""
        self._state.quiz_active = bool(active)
        if not active:
            self._state.working_memory.active_question_id = None

    def note_tutor_exchange(self, role: str, content: str) -> None:
        """Record a tutor-student exchange with truncated preview."""
        role_name = str(role or "").strip().lower()
        text = str(content or "").strip()
        if role_name not in {"user", "assistant"} or not text:
            return
        prefix = "U" if role_name == "user" else "T"
        clipped = text.replace("\n", " ").strip()
        if len(clipped) > self.MAX_CONTEXT_PREVIEW_CHARS:
            clipped = f"{clipped[: self.MAX_CONTEXT_PREVIEW_CHARS - 3].rstrip()}..."
        self._state.working_memory.push_context(f"{prefix}: {clipped}")

    def get_reflection_prompt(self, *, consume: bool = False) -> str:
        if bool(consume):
            return str(self._state.pop_reflection_prompt() or "").strip()
        return str(self._state.peek_reflection_prompt() or "").strip()

    def get_hint_support_level(self, chapter: str | None = None) -> int:
        topic = str(chapter or self._state.working_memory.active_chapter or "").strip()
        if not topic:
            return 2
        return int(self._state.get_hint_fade_level(topic, default=2))

    def get_cognitive_load(self) -> tuple[float, str]:
        score = float(getattr(self._state, "cognitive_load_score", 0.0) or 0.0)
        return score, self._state.get_cognitive_load_band(score)

    def get_dual_coding_aids(self, chapter: str | None = None, *, limit: int = DEFAULT_DUAL_CODING_AIDS) -> list[str]:
        chapter_key = str(chapter or self._state.working_memory.active_chapter or "").strip()
        topic = chapter_key.lower()
        try:
            cap = max(1, min(self.MAX_DUAL_CODING_AIDS, int(limit)))
        except (ValueError, TypeError):
            cap = self.DEFAULT_DUAL_CODING_AIDS

        picked: list[str] = []
        seen: set[str] = set()

        def _push(candidate: str) -> None:
            text = str(candidate or "").strip()
            if not text:
                return
            key = text.lower()
            if key in seen:
                return
            seen.add(key)
            picked.append(text)

        if topic:
            for token, aid in self._DUAL_CODING_TOPIC_AIDS:
                if token in topic:
                    _push(aid)
                if len(picked) >= cap:
                    return picked[:cap]

        if chapter_key:
            for tag in self._state.top_misconceptions(chapter_key, limit=3):
                tag_l = str(tag or "").strip().lower()
                if not tag_l:
                    continue
                for token, aid in self._DUAL_CODING_MISCONCEPTION_AIDS:
                    if token in tag_l:
                        _push(aid)
                    if len(picked) >= cap:
                        return picked[:cap]

        if not picked:
            _push("Use a compact worked-example table: inputs, method, answer, and one self-check.")
        return picked[:cap]

    def _build_reflection_prompt(
        self,
        *,
        chapter: str,
        correct: bool,
        hints_used: int,
        latency_ms: float | None,
    ) -> str:
        if not bool(correct):
            return ""
        if int(hints_used or 0) > 0:
            return ""
        if self._state.quiz_active:
            return ""
        latency_val = 0.0
        if latency_ms is not None:
            try:
                latency_val = float(latency_ms)
            except (ValueError, TypeError):
                latency_val = 0.0
        pace_hint = "quickly" if 0.0 < latency_val <= 15000.0 else "accurately"
        chapter_name = str(chapter or "").strip() or "this topic"
        return (
            f"What decision rule helped you solve {chapter_name} {pace_hint}, "
            "and when would that rule fail?"
        )

    def _adaptive_context_items(self) -> int:
        score = float(getattr(self._state, "cognitive_load_score", 0.0) or 0.0)
        if score >= 0.72:
            return 1
        if score >= 0.42:
            return 2
        return min(self.MAX_CONTEXT_ITEMS, 3)

    def _estimate_cognitive_load(
        self,
        *,
        correct: bool,
        hints_used: int,
        latency_ms: float | None,
    ) -> float:
        try:
            hints = max(0, int(hints_used or 0))
        except (ValueError, TypeError):
            hints = 0
        latency_val = 0.0
        if latency_ms is not None:
            try:
                latency_val = max(0.0, float(latency_ms))
            except (ValueError, TypeError):
                latency_val = 0.0
        wm = self._state.working_memory
        context_pressure = min(1.0, float(len(list(wm.context_chunks or []))) / 6.0)
        latency_pressure = min(1.0, latency_val / 60000.0) if latency_val > 0.0 else 0.0
        hint_pressure = min(1.0, float(hints) / 3.0)
        error_pressure = 1.0 if not bool(correct) else 0.0
        streak_pressure = 1.0 if bool(wm.struggle_flags.get("error_streak", False)) else 0.0

        score = (
            0.35 * latency_pressure
            + 0.20 * hint_pressure
            + 0.20 * error_pressure
            + 0.15 * context_pressure
            + 0.10 * streak_pressure
        )
        if bool(self._state.quiz_active):
            score = min(1.0, score + 0.05)
        return max(0.0, min(1.0, float(score)))
