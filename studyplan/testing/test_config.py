import importlib
import os
import tempfile

import studyplan.config as config_module


_ENV_KEYS = [
    "STUDYPLAN_ENV",
    "STUDYPLAN_LOG_LEVEL",
    "STUDYPLAN_LLAMA_CPP_ENABLED",
    "STUDYPLAN_LLAMA_CPP_ENDPOINT",
    "STUDYPLAN_LLAMA_CPP_MODEL",
    "STUDYPLAN_LLAMA_CPP_CONTEXT_WINDOW",
    "STUDYPLAN_LLAMA_CPP_TIMEOUT_SECONDS",
    "STUDYPLAN_LLAMA_CPP_MAX_RETRIES",
    "STUDYPLAN_LLAMA_CPP_TEMPERATURE",
    "STUDYPLAN_LLAMA_CPP_TOP_P",
    "STUDYPLAN_LLAMA_CPP_AUTO_MODEL_DISCOVERY",
    "STUDYPLAN_LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED",
    "STUDYPLAN_LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED",
    "STUDYPLAN_LLAMA_CPP_OLLAMA_HOST",
    "STUDYPLAN_LLAMA_CPP_GPT4ALL_MODELS_DIR",
    "STUDYPLAN_LLAMA_CPP_MODEL_PREFERENCE",
    "STUDYPLAN_LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS",
    "STUDYPLAN_OLLAMA_MODELS_DIR",
    "OLLAMA_MODELS",
    "STUDYPLAN_LLAMA_SERVER_THREADS",
    "STUDYPLAN_LLAMA_SERVER_CTX_SIZE",
    "STUDYPLAN_LLAMA_SERVER_BATCH_SIZE",
    "STUDYPLAN_LLAMA_SERVER_EXTRA_ARGS",
    "STUDYPLAN_LLAMA_AUTO_HW_EXTRAS",
]


def _reload_config(monkeypatch, **env):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(config_module)


def test_config_invalid_env_falls_back_to_dev(monkeypatch):
    mod = _reload_config(
        monkeypatch,
        STUDYPLAN_ENV="invalid-env",
    )
    assert mod.Config.ENV == mod.Environment.DEV
    assert mod.Config.LOG_LEVEL == "DEBUG"


def test_config_llama_cpp_parsing_and_clamps(monkeypatch):
    mod = _reload_config(
        monkeypatch,
        STUDYPLAN_ENV="prod",
        STUDYPLAN_LLAMA_CPP_ENABLED="false",
        STUDYPLAN_LLAMA_CPP_ENDPOINT="  http://localhost:9999/v1/chat/completions  ",
        STUDYPLAN_LLAMA_CPP_MODEL="  local-model  ",
        STUDYPLAN_LLAMA_CPP_CONTEXT_WINDOW="999999",
        STUDYPLAN_LLAMA_CPP_TIMEOUT_SECONDS="-5",
        STUDYPLAN_LLAMA_CPP_MAX_RETRIES="99",
        STUDYPLAN_LLAMA_CPP_TEMPERATURE="9.9",
        STUDYPLAN_LLAMA_CPP_TOP_P="-0.5",
        STUDYPLAN_LLAMA_CPP_AUTO_MODEL_DISCOVERY="off",
        STUDYPLAN_LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED="0",
        STUDYPLAN_LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED="no",
        STUDYPLAN_LLAMA_CPP_OLLAMA_HOST=" http://localhost:11434/ ",
        STUDYPLAN_LLAMA_CPP_GPT4ALL_MODELS_DIR=" /tmp/gpt4all ",
        STUDYPLAN_LLAMA_CPP_MODEL_PREFERENCE=" configured_first ",
        STUDYPLAN_LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS="999999",
    )
    assert mod.Config.ENV == mod.Environment.PROD
    assert mod.Config.LOG_LEVEL == "INFO"
    assert mod.Config.LLAMA_CPP_ENABLED is False
    assert mod.Config.LLAMA_CPP_ENDPOINT == "http://localhost:9999/v1/chat/completions"
    assert mod.Config.LLAMA_CPP_MODEL == "local-model"
    assert mod.Config.LLAMA_CPP_CONTEXT_WINDOW == 32768
    assert mod.Config.LLAMA_CPP_TIMEOUT_SECONDS == 1.0
    assert mod.Config.LLAMA_CPP_MAX_RETRIES == 5
    assert mod.Config.LLAMA_CPP_TEMPERATURE == 2.0
    assert mod.Config.LLAMA_CPP_TOP_P == 0.0
    assert mod.Config.LLAMA_CPP_AUTO_MODEL_DISCOVERY is False
    assert mod.Config.LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED is False
    assert mod.Config.LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED is False
    assert mod.Config.LLAMA_CPP_OLLAMA_HOST == "http://localhost:11434/"
    assert mod.Config.LLAMA_CPP_GPT4ALL_MODELS_DIR == "/tmp/gpt4all"
    assert mod.Config.LLAMA_CPP_MODEL_PREFERENCE == "configured_first"
    assert mod.Config.LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS == 3600.0


def test_config_llama_cpp_invalid_values_use_defaults(monkeypatch):
    mod = _reload_config(
        monkeypatch,
        STUDYPLAN_LLAMA_CPP_ENABLED="maybe",
        STUDYPLAN_LLAMA_CPP_CONTEXT_WINDOW="abc",
        STUDYPLAN_LLAMA_CPP_TIMEOUT_SECONDS="nanx",
        STUDYPLAN_LLAMA_CPP_MAX_RETRIES="nan",
        STUDYPLAN_LLAMA_CPP_TEMPERATURE="oops",
        STUDYPLAN_LLAMA_CPP_TOP_P="none",
        STUDYPLAN_LLAMA_CPP_AUTO_MODEL_DISCOVERY="???",
        STUDYPLAN_LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED="???",
        STUDYPLAN_LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED="???",
        STUDYPLAN_LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS="-1",
    )
    assert mod.Config.LLAMA_CPP_ENABLED is True
    assert mod.Config.LLAMA_CPP_CONTEXT_WINDOW == 8192
    assert mod.Config.LLAMA_CPP_TIMEOUT_SECONDS == 30.0
    assert mod.Config.LLAMA_CPP_MAX_RETRIES == 2
    assert mod.Config.LLAMA_CPP_TEMPERATURE == 0.2
    assert mod.Config.LLAMA_CPP_TOP_P == 0.95
    assert mod.Config.LLAMA_CPP_AUTO_MODEL_DISCOVERY is True
    assert mod.Config.LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED is True
    assert mod.Config.LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED is True
    assert mod.Config.LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS == 5.0


def test_config_ollama_models_dir_prefers_studyplan_over_ollama_models(monkeypatch):
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        mod = _reload_config(
            monkeypatch,
            STUDYPLAN_OLLAMA_MODELS_DIR=t1,
            OLLAMA_MODELS=t2,
        )
        assert os.path.samefile(mod.Config.OLLAMA_MODELS_DIR, t1)


def test_config_ollama_models_dir_falls_back_to_ollama_models_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        mod = _reload_config(monkeypatch, OLLAMA_MODELS=tmp)
        assert os.path.samefile(mod.Config.OLLAMA_MODELS_DIR, tmp)
