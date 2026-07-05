from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime as _dt
from enum import Enum
import math
from typing import Any

from .logging_config import get_logger

logger = get_logger(__name__)


COGNITIVE_STATE_SCHEMA_VERSION = 2
INTERVENTION_LEVELS = ("none", "light", "strong")

# Concept cognition constants
CONCEPT_DECAY_HALF_LIFE_DAYS = 14.0
CONCEPT_TRANSFER_FRACTION = 0.1
CONCEPT_MIN_EVIDENCE_WEIGHT = 0.3
CONCEPT_COLD_START_ALPHA = 2.0
CONCEPT_COLD_START_BETA = 2.0


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
    tutor_chunks: list[str] = field(default_factory=list)
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

    def push_tutor_context(self, text: str, max_chunks: int = 4) -> None:
        row = str(text or "").strip()
        if not row:
            return
        try:
            cap = max(1, min(12, int(max_chunks)))
        except Exception:
            cap = 4
        self.tutor_chunks.append(row)
        if len(self.tutor_chunks) > cap:
            self.tutor_chunks[:] = self.tutor_chunks[-cap:]

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
        tutor_chunks = payload.get("tutor_chunks")
        if isinstance(tutor_chunks, list):
            buf.tutor_chunks = [str(v).strip() for v in tutor_chunks if str(v).strip()][:4]
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
    quiz_active: bool = False
    struggle_mode: bool = False
    last_persisted_at: str | None = None
    last_persist_ok: bool | None = None
    last_persist_error: str | None = None

    # concept-scoped cognitive state (schema v2)
    concept_posteriors: dict[str, CompetencyPosterior] = field(default_factory=dict)
    concept_exposure_counts: dict[str, int] = field(default_factory=dict)

    # recovery / degradation state
    class Mode(str, Enum):
        NORMAL = "normal"
        DEGRADED = "degraded"
        READONLY = "readonly"
        OFFLINE = "offline"

    mode: "CognitiveState.Mode" = Mode.NORMAL
    recovery_hints: dict[str, str] = field(default_factory=dict)

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
            "quiz_active": bool(self.quiz_active),
            "struggle_mode": bool(self.struggle_mode),
            "mode": str(getattr(self.mode, "value", self.mode) or self.Mode.NORMAL.value),
            "recovery_hints": {str(k): str(v) for k, v in dict(self.recovery_hints or {}).items() if str(k).strip()},
            "concept_posteriors": {k: asdict(v) for k, v in self.concept_posteriors.items()},
            "concept_exposure_counts": {k: int(v) for k, v in self.concept_exposure_counts.items()},
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        return payload

    def mark_corrupted(self, reason: str) -> None:
        logger.warning("marking cognitive state corrupted", extra={"reason": reason})
        self.mode = self.Mode.READONLY
        self.recovery_hints["last_error"] = reason

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
                score = max(0.0, min(1.0, score))
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
        state.quiz_active = bool(payload.get("quiz_active", False))
        state.struggle_mode = bool(payload.get("struggle_mode", False))
        raw_mode = str(payload.get("mode", cls.Mode.NORMAL.value) or cls.Mode.NORMAL.value).strip().lower()
        try:
            state.mode = cls.Mode(raw_mode)
        except Exception:
            state.mode = cls.Mode.NORMAL
        recovery_hints = payload.get("recovery_hints")
        if isinstance(recovery_hints, dict):
            state.recovery_hints = {str(k): str(v) for k, v in recovery_hints.items() if str(k).strip()}

        # concept-scoped posteriors (schema v2+)
        concept_posteriors = payload.get("concept_posteriors")
        if isinstance(concept_posteriors, dict):
            for key, value in concept_posteriors.items():
                name = str(key or "").strip()
                if not name:
                    continue
                state.concept_posteriors[name] = CompetencyPosterior.from_payload(value)
        concept_exposure_counts = payload.get("concept_exposure_counts")
        if isinstance(concept_exposure_counts, dict):
            for key, value in concept_exposure_counts.items():
                name = str(key or "").strip()
                if not name:
                    continue
                try:
                    count = int(value)
                except Exception:
                    continue
                state.concept_exposure_counts[name] = max(0, count)

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
            # Values below 0.5 indicate high hint dependency.
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

    def recommend_intervention_level(
        self,
        *,
        outcome: str,
        hints_used: int = 0,
        pattern_detected: bool = False,
        confidence_delta: float | None = None,
    ) -> str:
        """Classify intervention strength for next-step guidance.

        Returns one of: ``none``, ``light``, ``strong``.
        """
        normalized = str(outcome or "").strip().lower()
        if normalized not in {"correct", "partial", "incorrect", "unknown"}:
            normalized = "unknown"
        score = 0

        if normalized == "incorrect":
            score += 3
        elif normalized == "partial":
            score += 1

        try:
            hints = int(hints_used or 0)
        except Exception:
            hints = 0
        if hints >= 2:
            score += 1

        if bool(pattern_detected):
            score += 2

        if bool(self.struggle_mode):
            score += 1

        # Positive delta means "felt more confident than actual accuracy".
        if confidence_delta is not None and normalized != "correct":
            try:
                conf_delta = float(confidence_delta)
            except Exception:
                conf_delta = 0.0
            if math.isfinite(conf_delta) and conf_delta >= 0.25:
                score += 1

        if score >= 3:
            return INTERVENTION_LEVELS[2]
        if score >= 1:
            return INTERVENTION_LEVELS[1]
        return INTERVENTION_LEVELS[0]

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

    # ------------------------------------------------------------------
    # Concept-scoped cognitive state (schema v2+)
    # ------------------------------------------------------------------

    def get_concept_posterior(self, concept_id: str) -> CompetencyPosterior:
        key = str(concept_id or "").strip()
        if not key:
            return CompetencyPosterior(alpha=CONCEPT_COLD_START_ALPHA, beta=CONCEPT_COLD_START_BETA)
        if key not in self.concept_posteriors:
            self.concept_posteriors[key] = CompetencyPosterior(
                alpha=CONCEPT_COLD_START_ALPHA, beta=CONCEPT_COLD_START_BETA
            )
        return self.concept_posteriors[key]

    def _apply_concept_decay(self, concept_id: str, posterior: CompetencyPosterior) -> None:
        obs = posterior.last_observation
        if not obs:
            return
        try:
            last = _dt.datetime.fromisoformat(obs)
            if last.tzinfo is not None:
                now = _dt.datetime.now(_dt.timezone.utc)
            else:
                now = _dt.datetime.now()
            days = max(0.0, (now - last).total_seconds() / 86400.0)
        except Exception:
            return
        if days <= 0.5:
            return
        decay = 2.0 ** (-days / CONCEPT_DECAY_HALF_LIFE_DAYS)
        posterior.alpha = max(CONCEPT_COLD_START_ALPHA * 0.5, posterior.alpha * decay)
        posterior.beta = max(CONCEPT_COLD_START_BETA * 0.5, posterior.beta * decay)

    def update_concept_posteriors(
        self,
        concept_ids: list[str],
        correct: bool,
        hints_used: int = 0,
        score_ratio: float = 1.0,
        *,
        concept_dependents: dict[str, set[str]] | None = None,
    ) -> None:
        if not concept_ids:
            return
        try:
            hints = max(0, int(hints_used or 0))
        except Exception:
            hints = 0
        evidence_weight = max(CONCEPT_MIN_EVIDENCE_WEIGHT, 1.0 - hints * 0.3)

        now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

        for cid in concept_ids:
            cid = str(cid or "").strip()
            if not cid:
                continue
            posterior = self.get_concept_posterior(cid)

            self._apply_concept_decay(cid, posterior)

            if correct and score_ratio >= 0.9:
                posterior.alpha = float(posterior.alpha) + evidence_weight
            elif correct and score_ratio > 0.0:
                partial = evidence_weight * score_ratio
                posterior.alpha = float(posterior.alpha) + partial
                posterior.beta = float(posterior.beta) + max(0.1, evidence_weight - partial)
            elif correct:
                posterior.alpha = float(posterior.alpha) + evidence_weight * 0.5
                posterior.beta = float(posterior.beta) + evidence_weight * 0.5
            else:
                posterior.beta = float(posterior.beta) + evidence_weight

            posterior.last_observation = now_iso

            self.concept_exposure_counts[cid] = int(self.concept_exposure_counts.get(cid, 0) or 0) + 1

            self._transfer_concept_update(cid, correct, evidence_weight, concept_dependents, now_iso)

    def _transfer_concept_update(
        self,
        concept_id: str,
        correct: bool,
        evidence_weight: float,
        concept_dependents: dict[str, set[str]] | None,
        now_iso: str,
    ) -> None:
        if not concept_dependents:
            return
        dependents = concept_dependents.get(concept_id)
        if not dependents:
            return
        delta = evidence_weight if correct else -evidence_weight * 0.5
        if delta >= 0:
            alpha_nudge = delta * CONCEPT_TRANSFER_FRACTION
            beta_nudge = 0.0
        else:
            alpha_nudge = 0.0
            beta_nudge = -delta * CONCEPT_TRANSFER_FRACTION
        for dep_id in dependents:
            dep_id = str(dep_id or "").strip()
            if not dep_id:
                continue
            dep = self.get_concept_posterior(dep_id)
            if alpha_nudge > 0:
                dep.alpha = float(dep.alpha) + alpha_nudge
            if beta_nudge > 0:
                dep.beta = float(dep.beta) + beta_nudge
            dep.last_observation = now_iso

    def get_concept_derived_competence_for_chapter(
        self,
        chapter: str,
        *,
        chapter_concepts: dict[str, list[str]] | None = None,
    ) -> float:
        if not chapter_concepts:
            return 50.0
        cids = chapter_concepts.get(chapter)
        if not cids:
            return 50.0
        total_weight = 0.0
        weighted_sum = 0.0
        for cid in cids:
            posterior = self.concept_posteriors.get(cid)
            if posterior is None:
                continue
            exposure = float(self.concept_exposure_counts.get(cid, 0) or 0)
            weight = min(1.0, exposure / 3.0) + 0.5
            total_weight += weight
            weighted_sum += posterior.mean * weight
        if total_weight <= 0:
            return 50.0
        return max(0.0, min(100.0, (weighted_sum / total_weight) * 100.0))

    def get_concept_prerequisite_gaps(
        self,
        *,
        concept_dependencies: dict[str, tuple[str, ...]] | None = None,
    ) -> list[tuple[str, str, float]]:
        gaps: list[tuple[str, str, float]] = []
        if not concept_dependencies:
            return gaps
        for cid, deps in concept_dependencies.items():
            if not deps:
                continue
            posterior = self.concept_posteriors.get(cid)
            if posterior is None:
                continue
            dep_mean = posterior.mean
            for dep_cid in deps:
                dep_posterior = self.concept_posteriors.get(dep_cid)
                if dep_posterior is None:
                    continue
                if dep_posterior.mean < 0.5 and dep_mean < 0.6:
                    gaps.append((cid, dep_cid, round(dep_posterior.mean, 3)))
        return gaps

    def get_concept_blocked_set(
        self,
        *,
        concept_dependencies: dict[str, tuple[str, ...]] | None = None,
    ) -> set[str]:
        blocked: set[str] = set()
        if not concept_dependencies:
            return blocked
        for cid, deps in concept_dependencies.items():
            if not deps:
                continue
            posterior = self.concept_posteriors.get(cid)
            if posterior is None or posterior.mean >= 0.6:
                continue
            for dep_cid in deps:
                dep_posterior = self.concept_posteriors.get(dep_cid)
                if dep_posterior is None or dep_posterior.mean < 0.5:
                    blocked.add(cid)
                    break
        return blocked


class CognitiveStateValidator:
    @staticmethod
    def validate(state: CognitiveState) -> tuple[bool, list[str]]:
        errors: list[str] = []
        # posterior mean in 0..1
        for topic, posterior in state.posteriors.items():
            m = posterior.mean
            if not (0.0 <= m <= 1.0):
                errors.append(f"Topic '{topic}' mean={m} outside [0,1]")
        # concept posterior means in 0..1
        for cid, posterior in state.concept_posteriors.items():
            m = posterior.mean
            if not (0.0 <= m <= 1.0):
                errors.append(f"Concept '{cid}' mean={m} outside [0,1]")
        # struggle flags bool
        for flag_name, flag_val in state.working_memory.struggle_flags.items():
            if not isinstance(flag_val, bool):
                errors.append(f"Struggle flag '{flag_name}' not bool: {flag_val}")
        # quiz_active invariants
        if state.quiz_active and not state.working_memory.active_question_id:
            errors.append("quiz_active=True but no active_question_id")
        # mode validity
        if state.mode not in CognitiveState.Mode:
            errors.append(f"Unknown mode {state.mode}")
        # concept exposure counts non-negative
        for cid, cnt in state.concept_exposure_counts.items():
            if not isinstance(cnt, int) or cnt < 0:
                errors.append(f"Concept '{cid}' exposure count {cnt} invalid")
        return (len(errors) == 0, errors)

    @classmethod
    def from_snapshot(cls, payload: Any) -> "CognitiveState":
        return CognitiveState.from_snapshot(payload)

    @classmethod
    def from_legacy_data(
        cls,
        data: dict[str, Any] | None,
        module_config: dict[str, Any] | None = None,
    ) -> "CognitiveState":
        return CognitiveState.from_legacy_data(data, module_config)
