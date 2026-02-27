from enum import Enum
from dataclasses import dataclass
from typing import Any


KNOWN_ASSESSMENT_OUTCOMES = {"correct", "partial", "incorrect"}


class PracticeLoopEvent(str, Enum):
    """Explicit event enumeration for practice loop state machine."""
    QUIZ_START = "quiz_start"
    QUIZ_END = "quiz_end"
    ITEM_PRESENTED = "item_presented"
    SUBMISSION_RECEIVED = "submission_received"
    ASSESSMENT_CORRECT = "assessment_correct"
    ASSESSMENT_INCORRECT = "assessment_incorrect"
    ASSESSMENT_PARTIAL = "assessment_partial"
    HINT_REQUESTED = "hint_requested"
    REFLECTION_REQUESTED = "reflection_requested"
    TRANSFER_TEST_START = "transfer_test_start"
    TRANSFER_TEST_RESULT = "transfer_test_result"
    TOPIC_MASTERED = "topic_mastered"
    ERROR_DETECTED = "error_detected"
    TIMEOUT = "timeout"


class PracticeLoopState(str, Enum):
    """Explicit states for practice loop FSM."""
    IDLE = "idle"
    PRESENTING = "presenting"
    AWAITING_SUBMISSION = "awaiting_submission"
    ASSESSING = "assessing"
    SCORED = "scored"
    REFLECTING = "reflecting"
    TRANSFER_TESTING = "transfer_testing"
    MASTERED = "mastered"
    ERROR = "error"


@dataclass
class StateTransition:
    from_state: PracticeLoopState
    event: PracticeLoopEvent
    to_state: PracticeLoopState
    action: str = ""  # e.g., "update_posterior", "generate_hint"


@dataclass(frozen=True)
class NextActionDecision:
    """Pure action recommendation for learner-facing next-step guidance."""

    reason: str
    next_action: str
    urgent: bool = False


def _coerce_text(value: Any, default: str = "") -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        text = ""
    return text if text else str(default or "")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def normalize_assessment_outcome(outcome: Any) -> str:
    normalized = _coerce_text(outcome, "").lower()
    if normalized in KNOWN_ASSESSMENT_OUTCOMES:
        return normalized
    return "unknown"


def recommend_action_policy(
    *,
    outcome: Any,
    can_transfer: Any = False,
    pattern_detected: Any = False,
    pattern_description: Any = "",
    remediation: Any = "",
) -> NextActionDecision:
    """Return next-step decision with no side effects.

    Args:
        outcome: Assessment outcome ("correct", "partial", "incorrect").
        can_transfer: Whether transfer test should be offered for correct outcomes.
        pattern_detected: Whether recurring misconception pattern was detected.
        pattern_description: Optional recurring pattern summary.
        remediation: Optional remediation message when incorrect.
    """
    normalized = normalize_assessment_outcome(outcome)
    can_transfer_flag = _coerce_bool(can_transfer)
    pattern_detected_flag = _coerce_bool(pattern_detected)
    pattern_description_text = _coerce_text(pattern_description)
    remediation_text = _coerce_text(remediation)
    reason = "Continue building momentum."
    action = "Proceed to the next question."
    urgent = False

    if normalized == "incorrect":
        if pattern_detected_flag:
            reason = pattern_description_text or "Recurring misconception detected."
        else:
            reason = remediation_text or "Concept gap detected."
        action = "Review remediation, then retry a similar question."
        urgent = True
    elif normalized == "partial":
        reason = "Method is close, but one or more rubric steps are missing."
        action = "Tighten your method steps and resubmit."
        urgent = True
    elif normalized == "correct":
        if can_transfer_flag:
            reason = "Strong performance with low support; this is a good transfer check moment."
            action = "Attempt a transfer variant in a new context."
        else:
            reason = "Solid result recorded; reinforce with spaced retrieval."
            action = "Proceed and review this topic again on schedule."

    return NextActionDecision(reason=reason, next_action=action, urgent=urgent)


# Explicit transition table (deterministic, no hidden side-effects)
PRACTICE_LOOP_TRANSITIONS = [
    StateTransition(PracticeLoopState.IDLE, PracticeLoopEvent.QUIZ_START, PracticeLoopState.PRESENTING),
    StateTransition(PracticeLoopState.PRESENTING, PracticeLoopEvent.ITEM_PRESENTED, PracticeLoopState.AWAITING_SUBMISSION),
    StateTransition(PracticeLoopState.AWAITING_SUBMISSION, PracticeLoopEvent.SUBMISSION_RECEIVED, PracticeLoopState.ASSESSING),
    StateTransition(PracticeLoopState.ASSESSING, PracticeLoopEvent.ASSESSMENT_CORRECT, PracticeLoopState.SCORED, action="update_posterior_alpha"),
    StateTransition(PracticeLoopState.ASSESSING, PracticeLoopEvent.ASSESSMENT_INCORRECT, PracticeLoopState.SCORED, action="update_posterior_beta"),
    StateTransition(PracticeLoopState.ASSESSING, PracticeLoopEvent.ASSESSMENT_PARTIAL, PracticeLoopState.SCORED, action="update_posterior_partial"),
    StateTransition(PracticeLoopState.SCORED, PracticeLoopEvent.REFLECTION_REQUESTED, PracticeLoopState.REFLECTING),
    StateTransition(PracticeLoopState.SCORED, PracticeLoopEvent.TRANSFER_TEST_START, PracticeLoopState.TRANSFER_TESTING),
    StateTransition(PracticeLoopState.REFLECTING, PracticeLoopEvent.QUIZ_END, PracticeLoopState.IDLE),
    StateTransition(PracticeLoopState.TRANSFER_TESTING, PracticeLoopEvent.TRANSFER_TEST_RESULT, PracticeLoopState.SCORED),
    StateTransition(PracticeLoopState.SCORED, PracticeLoopEvent.TOPIC_MASTERED, PracticeLoopState.MASTERED),
    StateTransition(PracticeLoopState.AWAITING_SUBMISSION, PracticeLoopEvent.HINT_REQUESTED, PracticeLoopState.AWAITING_SUBMISSION, action="deliver_hint"),
    StateTransition(PracticeLoopState.AWAITING_SUBMISSION, PracticeLoopEvent.TIMEOUT, PracticeLoopState.ERROR),
    StateTransition(PracticeLoopState.ERROR, PracticeLoopEvent.QUIZ_START, PracticeLoopState.PRESENTING),
]


class PracticeLoopFSM:
    """Deterministic practice loop state machine: no hidden transitions."""

    def __init__(self):
        self._transition_map = {}
        for t in PRACTICE_LOOP_TRANSITIONS:
            key = (t.from_state, t.event)
            self._transition_map[key] = t
        self._current_state = PracticeLoopState.IDLE

    @property
    def current_state(self) -> PracticeLoopState:
        return self._current_state

    def can_transition(self, event: PracticeLoopEvent) -> bool:
        key = (self._current_state, event)
        return key in self._transition_map

    def transition(self, event: PracticeLoopEvent) -> tuple[PracticeLoopState, str]:
        """Transition and return next state + action."""
        key = (self._current_state, event)
        if key not in self._transition_map:
            raise ValueError(f"Invalid transition: {self._current_state} + {event}")
        trans = self._transition_map[key]
        self._current_state = trans.to_state
        return (trans.to_state, trans.action)

    def allowed_events(self) -> list[PracticeLoopEvent]:
        """Return list of events that can be triggered from current state."""
        return [event for (state, event) in self._transition_map.keys() if state == self._current_state]
