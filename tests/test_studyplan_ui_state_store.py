from __future__ import annotations

from studyplan.cognitive_state import CognitiveState, CompetencyPosterior
from studyplan.contracts import TutorLearnerProfileSnapshot, TutorSessionState
from studyplan_ui_state_store import (
    GTK4WindowStateSnapshot,
    default_gtk4_window_state_path,
    load_gtk4_window_state,
    save_gtk4_window_state,
)


def test_save_and_load_gtk4_window_state_roundtrip(tmp_path):
    state = CognitiveState()
    state.posteriors["npv"] = CompetencyPosterior(alpha=6.0, beta=2.0)
    state.working_memory.active_question_id = "q:1"
    state.quiz_active = True
    snapshot = GTK4WindowStateSnapshot(
        cognitive_state=state,
        session_state=TutorSessionState(session_id="main", module="ACCA", topic="NPV", active=True),
        learner_profile=TutorLearnerProfileSnapshot(learner_id="user", module="ACCA"),
        visible_page="dashboard",
    )

    path = tmp_path / "gtk4" / "window_state.json"
    save_gtk4_window_state(snapshot, str(path))
    restored = load_gtk4_window_state(str(path))

    assert restored.visible_page == "dashboard"
    assert restored.session_state is not None
    assert restored.session_state.topic == "NPV"
    assert restored.learner_profile is not None
    assert restored.learner_profile.learner_id == "user"
    assert restored.cognitive_state.quiz_active is True
    assert restored.cognitive_state.posteriors["npv"].alpha == 6.0


def test_load_gtk4_window_state_returns_default_on_missing_or_invalid_file(tmp_path):
    missing = load_gtk4_window_state(str(tmp_path / "missing.json"))
    assert missing.visible_page == ""
    assert missing.session_state is None
    assert missing.learner_profile is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not-json", encoding="utf-8")
    restored = load_gtk4_window_state(str(broken))
    assert restored.visible_page == ""
    assert restored.cognitive_state.posteriors == {}


def test_default_gtk4_window_state_path_uses_config_home(tmp_path):
    path = default_gtk4_window_state_path(str(tmp_path))
    assert path.startswith(str(tmp_path))
    assert path.endswith("gtk4_shell/window_state.json")
