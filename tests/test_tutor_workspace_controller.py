"""Tests for TutorWorkspaceController.

Covers: start_turn, finish_turn, pause_turn, resume_turn,
commit_resumed_turn, discard_paused_turn with both object-style
and dict-style run_state arguments.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from studyplan.tutor_workspace_controller import TutorWorkspaceController


# ---------------------------------------------------------------------------
# Dict-style run_state
# ---------------------------------------------------------------------------


@pytest.fixture
def dict_state() -> dict[str, Any]:
    return {
        "job_id": 0,
        "cancel_event": None,
        "model": "",
        "draft_user": "",
        "draft_assistant": "",
        "follow_live": False,
        "follow_manual_override": False,
        "turn_started_at": 0.0,
        "turn_user_prompt": "",
        "turn_full_prompt": "",
        "turn_model_candidates": [],
        "turn_llm_purpose": "",
        "turn_backend": "",
    }


def test_start_turn_dict(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    running: list[bool] = []

    def set_running(v: bool) -> None:
        running.append(v)

    job_id = ctrl.start_turn(
        user_prompt="hello",
        model="test-model",
        cancel_event=cancel,
        set_running=set_running,
    )
    assert job_id == 1
    assert dict_state["draft_user"] == "hello"
    assert dict_state["model"] == "test-model"
    assert dict_state["cancel_event"] is cancel
    assert running == [True]


def test_start_turn_dict_increments_job_id(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    assert ctrl.start_turn(user_prompt="a", model="m", cancel_event=cancel) == 1
    assert ctrl.start_turn(user_prompt="b", model="m", cancel_event=threading.Event()) == 2


def test_start_turn_dict_stream_callable(dict_state: dict[str, Any]) -> None:
    """stream is not callable on a plain dict, so follow_live path sets state attrs."""
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    ctrl.start_turn(user_prompt="x", model="m", cancel_event=cancel)
    assert dict_state["follow_live"] is True


def test_start_turn_dict_render_transcript(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    rendered: list[bool] = []

    ctrl.start_turn(
        user_prompt="x",
        model="m",
        cancel_event=cancel,
        render_transcript=lambda force_scroll: rendered.append(force_scroll),
    )
    assert rendered == [True]


def test_finish_turn_dict(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    job_id = ctrl.start_turn(user_prompt="user msg", model="m", cancel_event=cancel)

    dict_state["draft_assistant"] = "assistant reply"
    drafts = ctrl.finish_turn(job_id=job_id)
    assert drafts == ("user msg", "assistant reply")


def test_finish_turn_dict_wrong_job(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    ctrl.start_turn(user_prompt="x", model="m", cancel_event=cancel)
    drafts = ctrl.finish_turn(job_id=999)
    assert drafts is None


def test_finish_turn_dict_clears_state(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    job_id = ctrl.start_turn(user_prompt="x", model="m", cancel_event=cancel)
    ctrl.finish_turn(job_id=job_id)
    assert dict_state["cancel_event"] is None
    assert dict_state["draft_user"] == ""
    assert dict_state["draft_assistant"] == ""


def test_finish_turn_sets_running_false(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    job_id = ctrl.start_turn(user_prompt="x", model="m", cancel_event=cancel)
    running: list[bool] = []
    ctrl.finish_turn(job_id=job_id, set_running=lambda v: running.append(v))
    assert running == [False]


def test_finish_turn_no_state(dict_state: dict[str, Any]) -> None:
    """When job_id doesn't match, finish returns None."""
    ctrl = TutorWorkspaceController(run_state=dict_state)
    assert ctrl.finish_turn(job_id=1) is None


# ---------------------------------------------------------------------------
# Object-style run_state (with begin_turn, stream, etc.)
# ---------------------------------------------------------------------------


class ObjectState:
    def __init__(self) -> None:
        self._job_id = 0
        self._stream_called = False
        self._reset_called = False

    def begin_turn(self, *, user_prompt: str, model: str, cancel_event: threading.Event) -> int:
        self._job_id += 1
        return self._job_id

    def reset_stream_runtime(self) -> None:
        self._reset_called = True

    def stream(self) -> Any:
        class FakeStream:
            follow_live = False
            follow_manual_override = False

        self._stream_called = True
        return FakeStream()

    def consume_turn_drafts_for_finish(self, *, job_id: int) -> tuple[str, str]:
        return ("user_draft", "assistant_draft")


def test_start_turn_object() -> None:
    state = ObjectState()
    ctrl = TutorWorkspaceController(run_state=state)
    cancel = threading.Event()
    job_id = ctrl.start_turn(user_prompt="hello", model="m", cancel_event=cancel)
    assert job_id == 1
    assert state._reset_called
    assert state._stream_called


def test_start_turn_object_stream_exception() -> None:
    class StateWithBadStream(dict):
        def begin_turn(self, **kw: Any) -> int:
            return 1

        def reset_stream_runtime(self) -> None:
            pass

        def stream(self) -> Any:
            raise RuntimeError("stream failed")

    state = StateWithBadStream()
    ctrl = TutorWorkspaceController(run_state=state)
    cancel = threading.Event()
    # Should not raise — stream exception is caught, dict fallback sets attrs
    job_id = ctrl.start_turn(user_prompt="x", model="m", cancel_event=cancel)
    assert job_id == 1


def test_start_turn_object_set_running(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    called_with: list[bool] = []
    ctrl.start_turn(
        user_prompt="x",
        model="m",
        cancel_event=cancel,
        set_running=lambda v: called_with.append(v),
    )
    assert called_with == [True]


def test_finish_turn_object() -> None:
    state = ObjectState()
    ctrl = TutorWorkspaceController(run_state=state)
    cancel = threading.Event()
    job_id = ctrl.start_turn(user_prompt="hello", model="m", cancel_event=cancel)
    drafts = ctrl.finish_turn(job_id=job_id)
    assert drafts == ("user_draft", "assistant_draft")


def test_finish_turn_object_returns_none() -> None:
    class NoneState:
        def consume_turn_drafts_for_finish(self, *, job_id: int) -> None:
            return None

    ctrl = TutorWorkspaceController(run_state=NoneState())
    assert ctrl.finish_turn(job_id=999) is None


# ---------------------------------------------------------------------------
# pause_turn
# ---------------------------------------------------------------------------


def test_pause_turn() -> None:
    ctrl = TutorWorkspaceController(run_state={})

    def pause(reason: str) -> dict[str, Any] | None:
        return {"paused": True, "reason": reason}

    result = ctrl.pause_turn(reason="timeout", pause_fn=pause)
    assert result == {"paused": True, "reason": "timeout"}


def test_pause_turn_returns_none() -> None:
    ctrl = TutorWorkspaceController(run_state={})
    result = ctrl.pause_turn(reason="test", pause_fn=lambda reason: None)
    assert result is None


# ---------------------------------------------------------------------------
# resume_turn
# ---------------------------------------------------------------------------


def test_resume_turn_object() -> None:
    class StateWithPaused:
        def paused_tutor_turn(self) -> dict[str, Any] | None:
            return {"snapshot": True}

    ctrl = TutorWorkspaceController(run_state=StateWithPaused())
    result = ctrl.resume_turn()
    assert result == {"snapshot": True}


def test_resume_turn_no_getter() -> None:
    ctrl = TutorWorkspaceController(run_state={})
    assert ctrl.resume_turn() is None


def test_resume_turn_not_callable() -> None:
    ctrl = TutorWorkspaceController(run_state={"paused_tutor_turn": "not_callable"})
    assert ctrl.resume_turn() is None


def test_resume_turn_returns_non_dict() -> None:
    class StateWithBadPaused:
        def paused_tutor_turn(self) -> str:
            return "not a dict"

    ctrl = TutorWorkspaceController(run_state=StateWithBadPaused())
    assert ctrl.resume_turn() is None


# ---------------------------------------------------------------------------
# commit_resumed_turn
# ---------------------------------------------------------------------------


def test_commit_resumed_turn() -> None:
    class StateWithClearer:
        cleared = False

        def clear_paused_tutor_turn(self) -> None:
            self.cleared = True

    state = StateWithClearer()
    ctrl = TutorWorkspaceController(run_state=state)
    ctrl.commit_resumed_turn()
    assert state.cleared


def test_commit_resumed_turn_no_clearer() -> None:
    ctrl = TutorWorkspaceController(run_state={})
    ctrl.commit_resumed_turn()  # should not raise


# ---------------------------------------------------------------------------
# discard_paused_turn
# ---------------------------------------------------------------------------


def test_discard_paused_turn() -> None:
    class DiscardState:
        def paused_tutor_turn(self) -> dict[str, Any] | None:
            return {"snap": True}

        cleared = False

        def clear_paused_tutor_turn(self) -> None:
            self.cleared = True

    state = DiscardState()
    ctrl = TutorWorkspaceController(run_state=state)
    assert ctrl.discard_paused_turn() is True
    assert state.cleared


def test_discard_paused_turn_no_getter() -> None:
    ctrl = TutorWorkspaceController(run_state={})
    assert ctrl.discard_paused_turn() is False


def test_discard_paused_turn_no_snapshot() -> None:
    class NoSnapshot:
        def paused_tutor_turn(self) -> None:
            return None

    ctrl = TutorWorkspaceController(run_state=NoSnapshot())
    assert ctrl.discard_paused_turn() is False


def test_discard_paused_turn_no_clearer() -> None:
    class NoClearer:
        def paused_tutor_turn(self) -> dict[str, Any] | None:
            return {"snap": True}

    ctrl = TutorWorkspaceController(run_state=NoClearer())
    assert ctrl.discard_paused_turn() is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_start_turn_no_callbacks(dict_state: dict[str, Any]) -> None:
    ctrl = TutorWorkspaceController(run_state=dict_state)
    cancel = threading.Event()
    job_id = ctrl.start_turn(user_prompt="x", model="m", cancel_event=cancel)
    assert job_id >= 0
    assert dict_state["draft_user"] == "x"
