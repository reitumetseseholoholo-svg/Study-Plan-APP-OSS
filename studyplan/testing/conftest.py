import pytest

from studyplan.persistence_layer import PersistenceLayer
from studyplan.cognitive_state import CognitiveState

@pytest.fixture
def persistence(tmp_path):
    # create a temp data directory
    base = tmp_path / "state"
    return PersistenceLayer(str(base))

@pytest.fixture
def sample_state():
    return CognitiveState()
