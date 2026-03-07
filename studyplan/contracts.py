from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal


@dataclass(frozen=True)
class AppStateSnapshot:
    module: str
    current_topic: str
    coach_pick: str
    days_to_exam: int | None
    must_review_due: int
    overdue_srs_count: int
    weak_topics_top3: tuple[str, ...] = ()
    risk_snapshot_top3: tuple[str, ...] = ()
    due_snapshot_top3: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TutorTurnRequest:
    model: str
    prompt: str
    history_fingerprint: str
    context_budget_chars: int
    rag_budget_chars: int


@dataclass(frozen=True)
class TutorTurnResult:
    text: str
    model: str
    latency_ms: int
    error_code: str = ""
    telemetry: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RagQueryRequest:
    query: str
    topic: str
    top_k: int
    char_budget: int
    semantic_enabled: bool


@dataclass(frozen=True)
class RagQueryResult:
    snippets: tuple[dict[str, Any], ...]
    method: str
    source_count: int
    candidate_count: int
    char_used: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AutopilotDecision:
    action: str
    topic: str
    duration_minutes: int
    reason: str
    confidence: float
    requires_confirmation: bool


@dataclass(frozen=True)
class AutopilotExecutionResult:
    executed: bool
    action: str
    reason: str
    blocked_reason: str = ""


@dataclass(frozen=True)
class ModelPerfStats:
    model: str
    samples: int
    success: int
    errors: int
    cancelled: int
    latency_ms_sum: float
    response_tokens_sum: float
    coverage_target_sum: int = 0
    coverage_hit_sum: int = 0


@dataclass(frozen=True)
class SloProfile:
    status: str
    samples: int
    p50_latency_ms: float
    p90_latency_ms: float
    p95_latency_ms: float
    latency_spread_ratio: float
    p50_target_ms: int
    p90_target_ms: int
    spread_target_ratio: float
    min_samples: int


TutorLoopMode = Literal[
    "auto",
    "teach",
    "guided_practice",
    "retrieval_drill",
    "error_clinic",
    "exam_technique",
    "section_c_coach",
    "revision_planner",
]

TutorLoopPhase = Literal[
    "observe",
    "diagnose",
    "teach",
    "practice",
    "assess",
    "reinforce",
    "switch",
    "recap",
]

TutorPracticeItemType = Literal[
    "mcq",
    "short_answer",
    "calculation_step",
    "teach_back",
    "error_spot",
    "section_c_part",
]

TutorAssessmentOutcome = Literal["correct", "partial", "incorrect"]


def _tuple_str(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return tuple(out)


def _dict_str_any(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        out[str(key)] = item
    return out


def _clamp_int(value: Any, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        result = int(value)
    except Exception:
        result = int(default)
    if min_value is not None and result < min_value:
        result = min_value
    if max_value is not None and result > max_value:
        result = max_value
    return result


def _clamp_float(
    value: Any,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    try:
        result = float(value)
    except Exception:
        result = float(default)
    if min_value is not None and result < min_value:
        result = min_value
    if max_value is not None and result > max_value:
        result = max_value
    return result


@dataclass(frozen=True)
class TutorPracticeItem:
    item_id: str
    item_type: TutorPracticeItemType | str
    prompt: str
    topic: str
    expected_format: str = ""
    difficulty: str = "medium"
    source: str = "tutor_micro"
    capability_tags: tuple[str, ...] = ()
    rubric_hints: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id or ""),
            "item_type": str(self.item_type or ""),
            "prompt": str(self.prompt or ""),
            "topic": str(self.topic or ""),
            "expected_format": str(self.expected_format or ""),
            "difficulty": str(self.difficulty or "medium"),
            "source": str(self.source or "tutor_micro"),
            "capability_tags": list(self.capability_tags),
            "rubric_hints": list(self.rubric_hints),
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TutorPracticeItem":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            item_id=str(data.get("item_id", "") or ""),
            item_type=str(data.get("item_type", "short_answer") or "short_answer"),
            prompt=str(data.get("prompt", "") or ""),
            topic=str(data.get("topic", "") or ""),
            expected_format=str(data.get("expected_format", "") or ""),
            difficulty=str(data.get("difficulty", "medium") or "medium"),
            source=str(data.get("source", "tutor_micro") or "tutor_micro"),
            capability_tags=_tuple_str(data.get("capability_tags")),
            rubric_hints=_tuple_str(data.get("rubric_hints")),
            meta=_dict_str_any(data.get("meta")),
        )


@dataclass(frozen=True)
class TutorAssessmentSubmission:
    item_id: str
    answer_text: str
    confidence: int | None = None
    response_time_seconds: float | None = None
    attempt_index: int = 1
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id or ""),
            "answer_text": str(self.answer_text or ""),
            "confidence": self.confidence,
            "response_time_seconds": self.response_time_seconds,
            "attempt_index": int(self.attempt_index),
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TutorAssessmentSubmission":
        data = payload if isinstance(payload, dict) else {}
        conf_raw = data.get("confidence")
        conf = None
        if conf_raw is not None:
            conf = _clamp_int(conf_raw, 0, 1, 5)
        rt_raw = data.get("response_time_seconds")
        rt = None
        if rt_raw is not None:
            rt = _clamp_float(rt_raw, 0.0, 0.0)
        return cls(
            item_id=str(data.get("item_id", "") or ""),
            answer_text=str(data.get("answer_text", "") or ""),
            confidence=conf,
            response_time_seconds=rt,
            attempt_index=_clamp_int(data.get("attempt_index", 1), 1, 1, 20),
            meta=_dict_str_any(data.get("meta")),
        )


@dataclass(frozen=True)
class TutorAssessmentResult:
    item_id: str
    outcome: TutorAssessmentOutcome | str
    marks_awarded: float
    marks_max: float
    feedback: str
    error_tags: tuple[str, ...] = ()
    misconception_tags: tuple[str, ...] = ()
    retry_recommended: bool = False
    next_difficulty: str = "same"
    suggested_next_step: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id or ""),
            "outcome": str(self.outcome or "incorrect"),
            "marks_awarded": float(self.marks_awarded),
            "marks_max": float(self.marks_max),
            "feedback": str(self.feedback or ""),
            "error_tags": list(self.error_tags),
            "misconception_tags": list(self.misconception_tags),
            "retry_recommended": bool(self.retry_recommended),
            "next_difficulty": str(self.next_difficulty or "same"),
            "suggested_next_step": str(self.suggested_next_step or ""),
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TutorAssessmentResult":
        data = payload if isinstance(payload, dict) else {}
        marks_max = _clamp_float(data.get("marks_max", 1.0), 1.0, 0.0)
        marks_awarded = _clamp_float(data.get("marks_awarded", 0.0), 0.0, 0.0, marks_max)
        return cls(
            item_id=str(data.get("item_id", "") or ""),
            outcome=str(data.get("outcome", "incorrect") or "incorrect"),
            marks_awarded=marks_awarded,
            marks_max=marks_max,
            feedback=str(data.get("feedback", "") or ""),
            error_tags=_tuple_str(data.get("error_tags")),
            misconception_tags=_tuple_str(data.get("misconception_tags")),
            retry_recommended=bool(data.get("retry_recommended", False)),
            next_difficulty=str(data.get("next_difficulty", "same") or "same"),
            suggested_next_step=str(data.get("suggested_next_step", "") or ""),
            meta=_dict_str_any(data.get("meta")),
        )


@dataclass(frozen=True)
class TutorLearnerProfileSnapshot:
    learner_id: str
    module: str
    schema_version: int = 1
    misconception_tags_top: tuple[str, ...] = ()
    weak_capabilities_top: tuple[str, ...] = ()
    preferred_explanation_style: str = "worked_example"
    response_speed_tier: str = "unknown"
    confidence_calibration_bias: float = 0.0
    chat_to_quiz_transfer_score: float = 0.0
    last_practice_outcome: str = ""
    last_updated_ts: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_id": str(self.learner_id or ""),
            "module": str(self.module or ""),
            "schema_version": int(self.schema_version),
            "misconception_tags_top": list(self.misconception_tags_top),
            "weak_capabilities_top": list(self.weak_capabilities_top),
            "preferred_explanation_style": str(self.preferred_explanation_style or "worked_example"),
            "response_speed_tier": str(self.response_speed_tier or "unknown"),
            "confidence_calibration_bias": float(self.confidence_calibration_bias),
            "chat_to_quiz_transfer_score": float(self.chat_to_quiz_transfer_score),
            "last_practice_outcome": str(self.last_practice_outcome or ""),
            "last_updated_ts": str(self.last_updated_ts or ""),
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TutorLearnerProfileSnapshot":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            learner_id=str(data.get("learner_id", "") or ""),
            module=str(data.get("module", "") or ""),
            schema_version=_clamp_int(data.get("schema_version", 1), 1, 1, 999),
            misconception_tags_top=_tuple_str(data.get("misconception_tags_top")),
            weak_capabilities_top=_tuple_str(data.get("weak_capabilities_top")),
            preferred_explanation_style=str(data.get("preferred_explanation_style", "worked_example") or "worked_example"),
            response_speed_tier=str(data.get("response_speed_tier", "unknown") or "unknown"),
            confidence_calibration_bias=_clamp_float(data.get("confidence_calibration_bias", 0.0), 0.0, -5.0, 5.0),
            chat_to_quiz_transfer_score=_clamp_float(data.get("chat_to_quiz_transfer_score", 0.0), 0.0, -1.0, 1.0),
            last_practice_outcome=str(data.get("last_practice_outcome", "") or ""),
            last_updated_ts=str(data.get("last_updated_ts", "") or ""),
            meta=_dict_str_any(data.get("meta")),
        )


@dataclass(frozen=True)
class TutorActionIntent:
    action: str
    topic: str = ""
    duration_minutes: int = 0
    reason: str = ""
    confidence: float = 0.0
    requires_confirmation: bool = False
    priority: str = "normal"
    expected_outcome: str = ""
    evidence: tuple[str, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": str(self.action or ""),
            "topic": str(self.topic or ""),
            "duration_minutes": int(self.duration_minutes),
            "reason": str(self.reason or ""),
            "confidence": float(self.confidence),
            "requires_confirmation": bool(self.requires_confirmation),
            "priority": str(self.priority or "normal"),
            "expected_outcome": str(self.expected_outcome or ""),
            "evidence": list(self.evidence),
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TutorActionIntent":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            action=str(data.get("action", "") or ""),
            topic=str(data.get("topic", "") or ""),
            duration_minutes=_clamp_int(data.get("duration_minutes", 0), 0, 0, 360),
            reason=str(data.get("reason", "") or ""),
            confidence=_clamp_float(data.get("confidence", 0.0), 0.0, 0.0, 1.0),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            priority=str(data.get("priority", "normal") or "normal"),
            expected_outcome=str(data.get("expected_outcome", "") or ""),
            evidence=_tuple_str(data.get("evidence")),
            meta=_dict_str_any(data.get("meta")),
        )


@dataclass(frozen=True)
class TutorSessionState:
    session_id: str
    module: str
    topic: str
    mode: TutorLoopMode | str = "auto"
    loop_phase: TutorLoopPhase | str = "observe"
    session_objective: str = ""
    success_criteria: str = ""
    target_concepts: tuple[str, ...] = ()
    active_practice_item_id: str = ""
    practice_streak: int = 0
    recent_failures: int = 0
    last_action: str = ""
    last_assessment_outcome: str = ""
    active: bool = False
    updated_at_ts: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id or ""),
            "module": str(self.module or ""),
            "topic": str(self.topic or ""),
            "mode": str(self.mode or "auto"),
            "loop_phase": str(self.loop_phase or "observe"),
            "session_objective": str(self.session_objective or ""),
            "success_criteria": str(self.success_criteria or ""),
            "target_concepts": list(self.target_concepts),
            "active_practice_item_id": str(self.active_practice_item_id or ""),
            "practice_streak": int(self.practice_streak),
            "recent_failures": int(self.recent_failures),
            "last_action": str(self.last_action or ""),
            "last_assessment_outcome": str(self.last_assessment_outcome or ""),
            "active": bool(self.active),
            "updated_at_ts": str(self.updated_at_ts or ""),
            "meta": dict(self.meta or {}),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TutorSessionState":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            session_id=str(data.get("session_id", "") or ""),
            module=str(data.get("module", "") or ""),
            topic=str(data.get("topic", "") or ""),
            mode=str(data.get("mode", "auto") or "auto"),
            loop_phase=str(data.get("loop_phase", "observe") or "observe"),
            session_objective=str(data.get("session_objective", "") or ""),
            success_criteria=str(data.get("success_criteria", "") or ""),
            target_concepts=_tuple_str(data.get("target_concepts")),
            active_practice_item_id=str(data.get("active_practice_item_id", "") or ""),
            practice_streak=_clamp_int(data.get("practice_streak", 0), 0, 0, 10_000),
            recent_failures=_clamp_int(data.get("recent_failures", 0), 0, 0, 10_000),
            last_action=str(data.get("last_action", "") or ""),
            last_assessment_outcome=str(data.get("last_assessment_outcome", "") or ""),
            active=bool(data.get("active", False)),
            updated_at_ts=str(data.get("updated_at_ts", "") or ""),
            meta=_dict_str_any(data.get("meta")),
        )


@dataclass(frozen=True)
class TutorLoopTurnRequest:
    user_message: str
    app_snapshot: AppStateSnapshot
    session_state: TutorSessionState
    learner_profile: TutorLearnerProfileSnapshot
    tutor_history_summary: str = ""
    rag_context_summary: str = ""
    mode_override: str = "auto"
    autonomy_mode: str = "assist"
    action_permissions: tuple[str, ...] = ()
    max_response_chars: int = 4000
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TutorLoopTurnResult:
    response_text: str
    mode_used: str
    phase_after_turn: str
    session_state: TutorSessionState
    learner_profile: TutorLearnerProfileSnapshot
    practice_items: tuple[TutorPracticeItem, ...] = ()
    action_intent: TutorActionIntent | None = None
    telemetry: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleDescriptor:
    module_code: str
    module_title: str
    domain_family: str = "generic"
    supports_section_c: bool = True
    supports_judgment_modes: bool = True


@dataclass(frozen=True)
class CompetencyNode:
    id: str
    topic_id: str
    label: str
    kind: str = "concept"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompetencyEdge:
    src_id: str
    dst_id: str
    edge_type: str
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MisconceptionPattern:
    id: str
    competency_ids: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    corrective_interventions: tuple[str, ...] = ()


@dataclass(frozen=True)
class JudgmentRubricTemplate:
    rubric_id: str
    label: str
    criteria: tuple[tuple[str, int], ...] = ()
    mode: str = "section_c"


@dataclass(frozen=True)
class RagSourceHint:
    source_key: str
    tier: str = "supplemental"
    priority: int = 100
    topic_tags: tuple[str, ...] = ()


class StructureType(Enum):
    """Deep problem structures used for zero-shot transfer checks."""

    NPV_ANNUITY_TIMING = "npv_annuity_timing"
    WACC_OPTIMIZATION = "wacc_optimization"
    FX_EXPOSURE_HEDGE = "fx_exposure_hedge"
    WORKING_CAPITAL_CYCLE = "working_capital_cycle"
    DIVIDEND_POLICY_TRADEOFF = "dividend_policy_tradeoff"
    CAPM_REQUIRED_RETURN = "capm_required_return"
    GEARING_FINANCIAL_RISK = "gearing_financial_risk"
    FOREIGN_INVESTMENT_APPRAISAL = "foreign_investment_appraisal"


@dataclass(frozen=True)
class ProblemStructure:
    structure_id: str
    structure_type: StructureType
    required_operations: tuple[str, ...]
    misconception_exposure_class: str
    composition_of_ids: tuple[str, ...] = ()
    boundary_conditions: tuple[str, ...] = ()
    related_confusion_concept_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceVariant:
    variant_id: str
    base_structure_id: str
    domain: Literal["corporate", "project", "personal_finance", "public_sector"]
    numeric_range: tuple[Decimal, Decimal]
    entity_type: str
    context_seed: str
    is_isomorphic: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransferAttempt:
    attempt_id: str
    student_id: str
    base_question_id: str
    variant_question_id: str
    structure_id: str
    base_result: Literal["correct", "incorrect", "hint_used", "abandoned"]
    variant_result: Literal["correct", "incorrect", "hint_used", "abandoned"]
    base_latency_seconds: float
    variant_latency_seconds: float
    base_hint_penalty: float
    variant_hint_penalty: float
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def transferred(self) -> bool:
        return (
            self.base_result == "correct"
            and self.variant_result == "correct"
            and float(self.base_hint_penalty or 0.0) >= 0.5
            and float(self.variant_hint_penalty or 0.0) >= 0.5
        )

    @property
    def brittle(self) -> bool:
        return self.base_result == "correct" and self.variant_result != "correct"

    @property
    def recovered(self) -> bool:
        return self.base_result != "correct" and self.variant_result == "correct"


@dataclass
class TransferScore:
    student_id: str
    structure_id: str
    attempts: list[TransferAttempt] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def transfer_rate(self) -> float:
        if not self.attempts:
            return 0.0
        return float(sum(1 for a in self.attempts if a.transferred)) / float(len(self.attempts))

    @property
    def brittleness_index(self) -> float:
        correct_base = [a for a in self.attempts if a.base_result == "correct"]
        if not correct_base:
            return 0.0
        return float(sum(1 for a in correct_base if a.brittle)) / float(len(correct_base))

    @property
    def recovery_rate(self) -> float:
        if not self.attempts:
            return 0.0
        return float(sum(1 for a in self.attempts if a.recovered)) / float(len(self.attempts))

    def to_insight_summary(self) -> dict[str, Any]:
        brittleness = float(self.brittleness_index)
        return {
            "structure_id": str(self.structure_id or ""),
            "attempts": int(len(self.attempts)),
            "transfer_rate": round(float(self.transfer_rate), 2),
            "brittleness_index": round(brittleness, 2),
            "recovery_rate": round(float(self.recovery_rate), 2),
            "risk_level": "high" if brittleness > 0.3 else ("medium" if brittleness > 0.15 else "low"),
        }


@dataclass
class ExamOutcomeRecord:
    """Schema only in pass 1. Not wired to product flow yet."""

    record_id: str
    student_id: str
    exam_code: str
    outcome: Literal["pass", "fail", "no_show"]
    section_scores: dict[str, float] | None = None
    reported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    feature_snapshot_id: str | None = None


@dataclass
class FeatureSnapshotForCorrelation:
    """Schema only in pass 1. Not wired to product flow yet."""

    snapshot_id: str
    student_id: str
    exam_code: str
    created_at: datetime
    transfer_rates_by_structure: dict[str, float]
    mean_brittleness_index: float
    posterior_means: dict[str, float]
    struggle_mode_frequency: float
    total_practice_questions: int
    unique_structures_attempted: int
    mean_session_focus_minutes: float
    mean_rewrite_delta: float | None
    weak_criteria_frequency: dict[str, int]
