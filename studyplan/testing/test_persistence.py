from studyplan.cognitive_state import CognitiveState


def test_persistence_atomic_write(persistence, sample_state):
    learner = "learner123"
    success = persistence.save_state_atomic(learner, sample_state)
    assert success
    loaded = persistence.load_state(learner)
    assert isinstance(loaded, CognitiveState)
    assert loaded.to_json_snapshot() == sample_state.to_json_snapshot()


def test_load_nonexistent_returns_new(persistence):
    loaded = persistence.load_state("no-such")
    assert isinstance(loaded, CognitiveState)
    assert loaded.posteriors == {}
