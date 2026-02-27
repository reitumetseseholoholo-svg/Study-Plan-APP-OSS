from enum import Enum
from dataclasses import dataclass
from typing import Any


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
