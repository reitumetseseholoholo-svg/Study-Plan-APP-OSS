#!/usr/bin/env python3
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class UISectionState:
    section_id: str
    visible: bool = True
    enabled: bool = True
    compact: bool = False
    tile: bool = False
    mode: str = "default"


@dataclass(frozen=True)
class UIRenderContext:
    reason: str
    timestamp_iso: str
    width: int
    height: int
    compact: bool
    tile: bool
    density_mode: str = "progressive"
    reduce_motion: bool = False


@dataclass(frozen=True)
class UIActionIntent:
    action_id: str
    source: str = "ui"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UIFaultReport:
    section_id: str
    error: str
    details: str = ""
    recoverable: bool = True
    timestamp_iso: str = ""

    @staticmethod
    def build(section_id: str, error: str, details: str = "", recoverable: bool = True) -> "UIFaultReport":
        return UIFaultReport(
            section_id=str(section_id or "unknown"),
            error=str(error or "unknown_error"),
            details=str(details or ""),
            recoverable=bool(recoverable),
            timestamp_iso=datetime.datetime.now().isoformat(timespec="seconds"),
        )


@dataclass(frozen=True)
class CoachPanelVM:
    topic: str = ""
    reason: str = ""
    status: str = ""


@dataclass(frozen=True)
class StudyRoomVM:
    topic: str = ""
    action_label: str = ""
    mission_summary: str = ""


@dataclass(frozen=True)
class DashboardVM:
    title: str = ""
    status: str = ""
    cards: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreferencesVM:
    modern_enabled: bool = False
    density_mode: str = "progressive"
    reduce_motion: bool = False
    legacy_fallback_enabled: bool = True


class UIRefreshScheduler:
    """Centralized refresh scheduler with keyed coalescing.

    `schedule_timeout_fn` and `schedule_idle_fn` should return source ids (0 on failure).
    `cancel_fn` should remove source ids safely.
    """

    def __init__(
        self,
        schedule_timeout_fn: Callable[[int, Callable[[], bool]], int],
        schedule_idle_fn: Callable[[Callable[[], bool]], int],
        cancel_fn: Callable[[int], Any],
    ) -> None:
        self._schedule_timeout_fn = schedule_timeout_fn
        self._schedule_idle_fn = schedule_idle_fn
        self._cancel_fn = cancel_fn
        self._sources: dict[str, int] = {}

    def is_scheduled(self, key: str) -> bool:
        return int(self._sources.get(str(key or ""), 0) or 0) > 0

    def clear_key(self, key: str) -> None:
        k = str(key or "")
        source_id = int(self._sources.pop(k, 0) or 0)
        if source_id <= 0:
            return
        try:
            self._cancel_fn(source_id)
        except Exception:
            pass

    def cancel_all(self) -> None:
        keys = list(self._sources.keys())
        for key in keys:
            self.clear_key(key)

    def schedule(
        self,
        key: str,
        callback: Callable[[], bool],
        *,
        delay_ms: int = 120,
        idle: bool = False,
    ) -> bool:
        k = str(key or "")
        if not k:
            return False
        if self.is_scheduled(k):
            return False

        def _wrapped() -> bool:
            self._sources.pop(k, None)
            try:
                return bool(callback())
            except Exception:
                return False

        try:
            if idle:
                source_id = int(self._schedule_idle_fn(_wrapped) or 0)
            else:
                source_id = int(self._schedule_timeout_fn(max(1, int(delay_ms)), _wrapped) or 0)
        except Exception:
            source_id = 0
        if source_id <= 0:
            self._sources.pop(k, None)
            return False
        self._sources[k] = source_id
        return True


class UIDialogLifecycle:
    """Tracks transient dialogs and supports deterministic teardown."""

    def __init__(self) -> None:
        self._dialogs: dict[int, Any] = {}

    def register(self, dialog: Any) -> None:
        if dialog is None:
            return
        self._dialogs[id(dialog)] = dialog

    def unregister(self, dialog: Any) -> None:
        if dialog is None:
            return
        self._dialogs.pop(id(dialog), None)

    def count(self) -> int:
        return len(self._dialogs)

    def close_all(self) -> None:
        dialogs = list(self._dialogs.values())
        self._dialogs = {}
        for dialog in dialogs:
            try:
                destroy = getattr(dialog, "destroy", None)
                if callable(destroy):
                    destroy()
                    continue
                close = getattr(dialog, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass


class UIController:
    """Controller interface shim for staged UI decomposition."""

    controller_id = "ui_controller"

    def bind(self, actions: dict[str, Callable[..., Any]]) -> None:
        _ = actions

    def render(self, vm: Any, context: UIRenderContext) -> Any:
        _ = (vm, context)
        return None

    def refresh(self, reason: str) -> UIActionIntent:
        return UIActionIntent(action_id=f"{self.controller_id}.refresh", payload={"reason": str(reason or "")})


class CoachPanelController(UIController):
    controller_id = "coach_panel"


class StudyRoomController(UIController):
    controller_id = "study_room"


class PomodoroPanelController(UIController):
    controller_id = "pomodoro_panel"


class DashboardController(UIController):
    controller_id = "dashboard"


class PreferencesController(UIController):
    controller_id = "preferences"
