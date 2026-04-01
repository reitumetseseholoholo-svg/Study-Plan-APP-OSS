import os
import tempfile


def _ensure_test_config_home() -> str:
    existing = os.environ.get("STUDYPLAN_CONFIG_HOME", "")
    if existing and os.path.isabs(existing):
        return existing
    path = tempfile.mkdtemp(prefix="studyplan_test_config_")
    os.environ["STUDYPLAN_CONFIG_HOME"] = path
    return path


_CONFIG_HOME = _ensure_test_config_home()
os.environ.setdefault("STUDYPLAN_OLLAMA_MODELS_DIR", os.path.join(_CONFIG_HOME, "ollama_models"))

try:
    from studyplan.config import Config

    Config.CONFIG_HOME = _CONFIG_HOME
    Config.OLLAMA_MODELS_DIR = os.environ["STUDYPLAN_OLLAMA_MODELS_DIR"]
except Exception:
    pass
