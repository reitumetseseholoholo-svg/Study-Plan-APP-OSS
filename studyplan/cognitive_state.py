from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime as _dt
from typing import Any


COGNITIVE_STATE_SCHEMA_VERSION = 3


@dataclass
class CompetencyPosterior:
    alpha: float = 2.0
    beta: float = 2.0
    last_observation: str | None = None
    hint_penalty: float = 1.0

    @property
    def mean(self) -> float:
        denom = float(self.alpha + self.beta)
        if denom <= 0.0:
            return 0.5
        return float(self.alpha) / denom

    @property
    def variance(self) -> float:
        a = max(0.0, float(self.alpha))
        b = max(0.0, float(self.beta))
        denom = (a + b) ** 2 * (a + b + 1.0)
        if denom <= 0.0:
            return 0.0
        return (a * b) / denom

    @classmethod
    def from_payload(cls, payload: Any) -> "CompetencyPosterior":
        if not isinstance(payload, dict):
            return cls()
        try:
            alpha = float(payload.get("alpha", 2.0) or 2.0)
        except Exception:
            alpha = 2.0
        try:
            beta = float(payload.get("beta", 2.0) or 2.0)
        except Exception:
            beta = 2.0
        if alpha <= 0.0:
            alpha = 0.5
        if beta <= 0.0:
            beta = 0.5
        last_observation = payload.get("last_observation")
        if not isinstance(last_observation, str) or not last_observation.strip():
            last_observation = None
        try:
            hint_penalty = float(payload.get("hint_penalty", 1.0) or 1.0)
        except Exception:
            hint_penalty = 1.0
        hint_penalty = max(0.0, min(1.0, hint_penalty))
        return cls(alpha=alpha, beta=beta, last_observation=last_observation, hint_penalty=hint_penalty)


@dataclass
class WorkingMemoryBuffer:
    active_question_id: str | None = None
    active_chapter: str | None = None
    socratic_state: str = "DIAGNOSE"
    context_chunks: list[str] = field(default_factory=list)
    struggle_flags: dict[str, bool] = field(
        default_factory=lambda: {
            "latency_spike": False,
            "error_streak": False,
            "hint_dependency": False,
        }
    )

    def push_context(self, text: str, max_chunks: int = 4) -> None:
        row = str(text or "").strip()
        if not row:
            return
        try:
            cap = max(1, min(12, int(max_chunks)))
        except Exception:
            cap = 4
        self.context_chunks.append(row)
        if len(self.context_chunks) > cap:
            self.context_chunks[:] = self.context_chunks[-cap:]

    @classmethod
    def from_payload(cls, payload: Any) -> "WorkingMemoryBuffer":
        buf = cls()
        if not isinstance(payload, dict):
            return buf
        for key in ("active_question_id", "active_chapter", "socratic_state"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                setattr(buf, key, value.strip())
        chunks = payload.get("context_chunks")
        if isinstance(chunks, list):
            buf.context_chunks = [str(v).strip() for v in chunks if str(v).strip()][:4]
        flags = payload.get("struggle_flags")
        if isinstance(flags, dict):
            for flag_key in list(buf.struggle_flags.keys()):
                if flag_key in flags:
                    buf.struggle_flags[flag_key] = bool(flags.get(flag_key))
        return buf


@dataclass
class CognitiveState:
    posteriors: dict[str, CompetencyPosterior] = field(default_factory=dict)
    structure_posteriors: dict[str, CompetencyPosterior] = field(default_factory=dict)
    working_memory: WorkingMemoryBuffer = field(default_factory=WorkingMemoryBuffer)
    confusion_links: dict[str, set[str]] = field(default_factory=dict)
    prerequisite_gaps: set[str] = field(default_factory=set)
    claim_confidence: dict[str, float] = field(default_factory=dict)
    structure_exposure_counts: dict[str, int] = field(default_factory=dict)
    transfer_attempt_ids: list[str] = field(default_factory=list)
    hint_fade_levels: dict[str, int] = field(default_factory=dict)
    misconception_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    remediation_by_chapter: dict[str, str] = field(default_factory=dict)
    reflection_queue: list[str] = field(default_factory=list)
    cognitive_load_score: float = 0.0
    cognitive_load_history: list[float] = field(default_factory=list)
    quiz_active: bool = False
    struggle_mode: bool = False
    last_persisted_at: str | None = None
    last_persist_ok: bool | None = None
    last_persist_error: str | None = None

    def to_json_snapshot(self) -> dict[str, Any]:
        payload = {
            "schema_version": int(COGNITIVE_STATE_SCHEMA_VERSION),
            "posteriors": {k: asdict(v) for k, v in self.posteriors.items()},
            "structure_posteriors": {k: asdict(v) for k, v in self.structure_posteriors.items()},
            "working_memory": asdict(self.working_memory),
            "confusion_links": {k: sorted(v) for k, v in self.confusion_links.items()},
            "prerequisite_gaps": sorted(self.prerequisite_gaps),
            "claim_confidence": {k: float(v) for k, v in self.claim_confidence.items()},
            "structure_exposure_counts": {k: int(v) for k, v in self.structure_exposure_counts.items()},
            "transfer_attempt_ids": [str(v) for v in self.transfer_attempt_ids if str(v or "").strip()],
            "hint_fade_levels": {k: int(v) for k, v in self.hint_fade_levels.items()},
            "misconception_counts": {
                k: {mk: int(mv) for mk, mv in v.items()}
                for k, v in self.misconception_counts.items()
                if isinstance(v, dict)
            },
            "remediation_by_chapter": {
                k: str(v)
                for k, v in self.remediation_by_chapter.items()
                if str(k or "").strip() and str(v or "").strip()
            },
            "reflection_queue": [str(v).strip() for v in self.reflection_queue if str(v).strip()][:8],
            "cognitive_load_score": max(0.0, min(1.0, float(self.cognitive_load_score or 0.0))),
            "cognitive_load_history": [
                max(0.0, min(1.0, float(v or 0.0)))
                for v in list(self.cognitive_load_history or [])[-24:]
            ],
            "quiz_active": bool(self.quiz_active),
            "struggle_mode": bool(self.struggle_mode),
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        return payload

    @classmethod
    def from_snapshot(cls, payload: Any) -> "CognitiveState":
        state = cls()
        if not isinstance(payload, dict):
            return state
        posteriors = payload.get("posteriors")
        if isinstance(posteriors, dict):
            for key, value in posteriors.items():
                name = str(key or "").strip()
                if not name:
                    continue
                state.posteriors[name] = CompetencyPosterior.from_payload(value)
        structure_posteriors = payload.get("structure_posteriors")
        if isinstance(structure_posteriors, dict):
            for key, value in structure_posteriors.items():
                name = str(key or "").strip()
                if not name:
                    continue
                state.structure_posteriors[name] = CompetencyPosterior.from_payload(value)
        state.working_memory = WorkingMemoryBuffer.from_payload(payload.get("working_memory"))
        confusion_links = payload.get("confusion_links")
        if isinstance(confusion_links, dict):
            for key, value in confusion_links.items():
                name = str(key or "").strip()
                if not name:
                    continue
                if isinstance(value, (list, set, tuple)):
                    state.confusion_links[name] = {
                        str(v).strip() for v in value if isinstance(v, str) and str(v).strip()
                    }
        prerequisite_gaps = payload.get("prerequisite_gaps")
        if isinstance(prerequisite_gaps, (list, set, tuple)):
            state.prerequisite_gaps = {
                str(v).strip() for v in prerequisite_gaps if isinstance(v, str) and str(v).strip()
            }
        claim_confidence = payload.get("claim_confidence")
        if isinstance(claim_confidence, dict):
            for key, value in claim_confidence.items():
                claim_key = str(key or "").strip()
                if not claim_key:
                    continue
                try:
                    score = float(value)
                except Exception:
                    continue
                if score < 0.0:
                    score = 0.0
                if score > 1.0:
                    score = 1.0
                state.claim_confidence[claim_key] = score
        structure_exposure_counts = payload.get("structure_exposure_counts")
        if isinstance(structure_exposure_counts, dict):
            for key, value in structure_exposure_counts.items():
                name = str(key or "").strip()
                if not name:
                    continue
                try:
                    count = int(value)
                except Exception:
                    continue
                state.structure_exposure_counts[name] = max(0, count)
        transfer_attempt_ids = payload.get("transfer_attempt_ids")
        if isinstance(transfer_attempt_ids, (list, tuple)):
            state.transfer_attempt_ids = [str(v).strip() for v in transfer_attempt_ids if str(v).strip()][:200]
        hint_fade_levels = payload.get("hint_fade_levels")
        if isinstance(hint_fade_levels, dict):
            for key, value in hint_fade_levels.items():
                name = str(key or "").strip()
                if not name:
                    continue
                try:
                    level = int(value)
                except Exception:
                    continue
                state.hint_fade_levels[name] = max(1, min(4, level))
        misconception_counts = payload.get("misconception_counts")
        if isinstance(misconception_counts, dict):
            for key, value in misconception_counts.items():
                chapter = str(key or "").strip()
                if not chapter or not isinstance(value, dict):
                    continue
                chapter_counts: dict[str, int] = {}
                for mk, mv in value.items():
                    mkey = str(mk or "").strip()
                    if not mkey:
                        continue
                    try:
                        mcount = int(mv)
                    except Exception:
                        continue
                    chapter_counts[mkey] = max(0, mcount)
                if chapter_counts:
                    state.misconception_counts[chapter] = chapter_counts
        remediation_by_chapter = payload.get("remediation_by_chapter")
        if isinstance(remediation_by_chapter, dict):
            for key, value in remediation_by_chapter.items():
                chapter = str(key or "").strip()
                remediation = str(value or "").strip()
                if chapter and remediation:
                    state.remediation_by_chapter[chapter] = remediation
        reflection_queue = payload.get("reflection_queue")
        if isinstance(reflection_queue, (list, tuple)):
            state.reflection_queue = [str(v).strip() for v in reflection_queue if str(v).strip()][:8]
        try:
            state.cognitive_load_score = max(
                0.0,
                min(1.0, float(payload.get("cognitive_load_score", 0.0) or 0.0)),
            )
        except Exception:
            state.cognitive_load_score = 0.0
        history = payload.get("cognitive_load_history")
        if isinstance(history, (list, tuple)):
            parsed: list[float] = []
            for row in history:
                try:
                    parsed.append(max(0.0, min(1.0, float(row or 0.0))))
                except Exception:
                    continue
            state.cognitive_load_history = parsed[-24:]
        state.quiz_active = bool(payload.get("quiz_active", False))
        state.struggle_mode = bool(payload.get("struggle_mode", False))
        return state

    @classmethod
    def from_legacy_data(
        cls,
        data: dict[str, Any] | None,
        module_config: dict[str, Any] | None = None,
    ) -> "CognitiveState":
        state = cls()
        payload = data if isinstance(data, dict) else {}
        module_cfg = module_config if isinstance(module_config, dict) else {}
        competence = payload.get("competence")
        difficulty_counts = payload.get("difficulty_counts")
        chapter_flow = module_cfg.get("chapter_flow")
        chapter_miss_streak = payload.get("chapter_miss_streak")
        study_days = payload.get("study_days")
        last_study = None
        if isinstance(study_days, list) and study_days:
            raw = study_days[-1]
            if isinstance(raw, str) and raw.strip():
                last_study = raw.strip()
        if isinstance(competence, dict):
            for chapter, score_raw in competence.items():
                chapter_name = str(chapter or "").strip()
                if not chapter_name:
                    continue
                try:
                    score = float(score_raw or 0.0)
                except Exception:
                    score = 0.0
                score = max(0.0, min(100.0, score))
                attempts = 0.0
                if isinstance(difficulty_counts, dict):
                    counts_val = difficulty_counts.get(chapter_name)
                    if isinstance(counts_val, dict):
                        attempts = float(sum(int(v or 0) for v in counts_val.values() if isinstance(v, (int, float))))
                    elif isinstance(counts_val, (int, float)):
                        attempts = float(counts_val)
                total = max(4.0, min(60.0, 4.0 + max(0.0, attempts)))
                mean = score / 100.0
                alpha = max(0.5, mean * total)
                beta = max(0.5, (1.0 - mean) * total)
                state.posteriors[chapter_name] = CompetencyPosterior(
                    alpha=alpha,
                    beta=beta,
                    last_observation=last_study,
                )
        if isinstance(chapter_miss_streak, dict):
            for chapter, streak_raw in chapter_miss_streak.items():
                chapter_name = str(chapter or "").strip()
                if not chapter_name:
                    continue
                try:
                    streak = int(streak_raw or 0)
                except Exception:
                    streak = 0
                if streak < 2:
                    continue
                prereqs: set[str] = set()
                if isinstance(chapter_flow, dict):
                    raw_prereqs = chapter_flow.get(chapter_name)
                    if isinstance(raw_prereqs, (list, tuple, set)):
                        prereqs = {str(v).strip() for v in raw_prereqs if str(v).strip()}
                if prereqs:
                    state.confusion_links[chapter_name] = prereqs
        return state

    def get_structure_posterior(self, structure_id: str) -> CompetencyPosterior:
        key = str(structure_id or "").strip()
        if not key:
            return CompetencyPosterior()
        if key not in self.structure_posteriors:
            self.structure_posteriors[key] = CompetencyPosterior()
        return self.structure_posteriors[key]

    def should_offer_transfer_test(
        self,
        *,
        structure_id: str,
        base_correct: bool,
        hint_penalty: float,
    ) -> bool:
        key = str(structure_id or "").strip()
        if not key:
            return False
        if not bool(base_correct):
            return False
        try:
            if float(hint_penalty or 0.0) < 0.5:
                return False
        except Exception:
            return False
        if bool(self.struggle_mode) or bool(self.quiz_active):
            return False
        posterior = self.get_structure_posterior(key)
        if float(posterior.mean) < 0.75 or float(posterior.variance) > 0.05:
            return False
        if int(self.structure_exposure_counts.get(key, 0) or 0) >= 3:
            return False
        return True

    def record_transfer_exposure(self, structure_id: str, attempt_id: str = "") -> None:
        key = str(structure_id or "").strip()
        if not key:
            return
        self.structure_exposure_counts[key] = int(self.structure_exposure_counts.get(key, 0) or 0) + 1
        attempt_key = str(attempt_id or "").strip()
        if attempt_key:
            self.transfer_attempt_ids.append(attempt_key)
            if len(self.transfer_attempt_ids) > 200:
                self.transfer_attempt_ids[:] = self.transfer_attempt_ids[-200:]

    def get_hint_fade_level(self, chapter: str, default: int = 2) -> int:
        key = str(chapter or "").strip()
        if not key:
            return max(1, min(4, int(default)))
        try:
            fallback = int(default)
        except Exception:
            fallback = 2
        value = int(self.hint_fade_levels.get(key, fallback) or fallback)
        return max(1, min(4, value))

    def adapt_hint_fade_level(self, chapter: str, *, correct: bool, hints_used: int) -> int:
        key = str(chapter or "").strip()
        if not key:
            return 2
        level = self.get_hint_fade_level(key, default=2)
        if not bool(correct) or int(hints_used or 0) >= 2:
            level = min(4, level + 1)
        elif bool(correct) and int(hints_used or 0) == 0:
            level = max(1, level - 1)
        self.hint_fade_levels[key] = level
        return level

    def queue_reflection_prompt(self, prompt: str, max_items: int = 8) -> None:
        text = str(prompt or "").strip()
        if not text:
            return
        self.reflection_queue.append(text)
        try:
            cap = max(1, min(16, int(max_items)))
        except Exception:
            cap = 8
        if len(self.reflection_queue) > cap:
            self.reflection_queue[:] = self.reflection_queue[-cap:]

    def peek_reflection_prompt(self) -> str | None:
        if not self.reflection_queue:
            return None
        return str(self.reflection_queue[-1] or "").strip() or None

    def pop_reflection_prompt(self) -> str | None:
        if not self.reflection_queue:
            return None
        value = str(self.reflection_queue.pop() or "").strip()
        return value or None

    def record_misconception(self, chapter: str, tag: str, remediation: str = "") -> None:
        chapter_key = str(chapter or "").strip()
        tag_key = str(tag or "").strip()
        if not chapter_key or not tag_key:
            return
        chapter_counts = self.misconception_counts.setdefault(chapter_key, {})
        chapter_counts[tag_key] = int(chapter_counts.get(tag_key, 0) or 0) + 1
        rem = str(remediation or "").strip()
        if rem:
            self.remediation_by_chapter[chapter_key] = rem

    def top_misconceptions(self, chapter: str, limit: int = 3) -> list[str]:
        chapter_key = str(chapter or "").strip()
        if not chapter_key:
            return []
        counts = self.misconception_counts.get(chapter_key, {})
        if not counts:
            return []
        try:
            cap = max(1, min(10, int(limit)))
        except Exception:
            cap = 3
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [name for name, _ in ranked[:cap]]

    def set_cognitive_load(self, score: float, max_items: int = 24) -> float:
        try:
            normalized = max(0.0, min(1.0, float(score or 0.0)))
        except Exception:
            normalized = 0.0
        self.cognitive_load_score = normalized
        self.cognitive_load_history.append(normalized)
        try:
            cap = max(4, min(64, int(max_items or 24)))
        except Exception:
            cap = 24
        if len(self.cognitive_load_history) > cap:
            self.cognitive_load_history[:] = self.cognitive_load_history[-cap:]
        return normalized

    def get_cognitive_load_band(self, score: float | None = None) -> str:
        try:
            value = float(self.cognitive_load_score if score is None else score)
        except Exception:
            value = 0.0
        if value >= 0.72:
            return "high"
        if value >= 0.42:
            return "moderate"
        return "low"
