from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from studyplan.cognitive_state import CognitiveState
from studyplan.config import Config
from studyplan.contracts import TutorLearnerProfileSnapshot, TutorSessionState
from studyplan_app_path_utils import atomic_write_text_file

GTK4_WINDOW_STATE_SCHEMA_VERSION = 1


@dataclass
class GTK4WindowStateSnapshot:
    cognitive_state: CognitiveState = field(default_factory=CognitiveState)
    session_state: TutorSessionState | None = None
    learner_profile: TutorLearnerProfileSnapshot | None = None
    visible_page: str = ""
    source_path: str = ""


def default_gtk4_window_state_path(config_home: str | None = None) -> str:
    root = os.path.expanduser(str(config_home or Config.CONFIG_HOME or "~/.config/studyplan"))
    return os.path.join(root, "gtk4_shell", "window_state.json")


def build_gtk4_window_state_payload(snapshot: GTK4WindowStateSnapshot) -> dict[str, object]:
    return {
        "schema_version": GTK4_WINDOW_STATE_SCHEMA_VERSION,
        "ui": {
            "visible_page": str(snapshot.visible_page or "").strip(),
        },
        "cognitive_state": snapshot.cognitive_state.to_json_snapshot(),
        "session_state": snapshot.session_state.to_dict() if snapshot.session_state is not None else {},
        "learner_profile": snapshot.learner_profile.to_dict() if snapshot.learner_profile is not None else {},
    }


def save_gtk4_window_state(
    snapshot: GTK4WindowStateSnapshot,
    file_path: str | None = None,
) -> str:
    path = str(file_path or default_gtk4_window_state_path()).strip()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = build_gtk4_window_state_payload(snapshot)
    atomic_write_text_file(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return path


def load_gtk4_window_state(file_path: str | None = None) -> GTK4WindowStateSnapshot:
    path = str(file_path or default_gtk4_window_state_path()).strip()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return GTK4WindowStateSnapshot(source_path=path)
    if not isinstance(payload, dict):
        return GTK4WindowStateSnapshot(source_path=path)
    ui_payload = payload.get("ui")
    visible_page = ""
    if isinstance(ui_payload, dict):
        visible_page = str(ui_payload.get("visible_page", "") or "").strip()
    return GTK4WindowStateSnapshot(
        cognitive_state=CognitiveState.from_snapshot(payload.get("cognitive_state")),
        session_state=TutorSessionState.from_dict(payload.get("session_state"))
        if isinstance(payload.get("session_state"), dict) and payload.get("session_state")
        else None,
        learner_profile=TutorLearnerProfileSnapshot.from_dict(payload.get("learner_profile"))
        if isinstance(payload.get("learner_profile"), dict) and payload.get("learner_profile")
        else None,
        visible_page=visible_page,
        source_path=path,
    )
