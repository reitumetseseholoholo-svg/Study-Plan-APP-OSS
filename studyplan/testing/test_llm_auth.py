from studyplan.ai.llm_auth import discover_llm_auth_headers


_ENV_KEYS = [
    "STUDYPLAN_CLOUD_LLAMACPP_AUTH_BEARER",
    "STUDYPLAN_LLM_AUTH_BEARER",
    "STUDYPLAN_LLM_GATEWAY_API_KEY",
    "LLM_GATEWAY_API_KEY",
    "LLM_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "MISTRAL_API_KEY",
]


def _clear_env(monkeypatch, **env):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_discover_llm_auth_prefers_explicit_generic_override(monkeypatch, tmp_path):
    _clear_env(
        monkeypatch,
        STUDYPLAN_CLOUD_LLAMACPP_AUTH_BEARER="explicit-token",
        OPENROUTER_API_KEY="router-token",
    )
    auth = discover_llm_auth_headers(
        "https://openrouter.ai/api/v1/chat/completions",
        search_paths=[tmp_path],
    )
    assert auth is not None
    assert auth.source == "generic_override"
    assert auth.headers["Authorization"] == "Bearer explicit-token"


def test_discover_llm_auth_uses_provider_specific_headers_for_gemini(monkeypatch, tmp_path):
    _clear_env(monkeypatch, GOOGLE_API_KEY="gemini-token")
    auth = discover_llm_auth_headers(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        search_paths=[tmp_path],
    )
    assert auth is not None
    assert auth.provider == "gemini"
    assert auth.headers["Authorization"] == "Bearer gemini-token"
    assert auth.headers["x-goog-api-key"] == "gemini-token"


def test_discover_llm_auth_reads_env_file_for_custom_gateway(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    (tmp_path / "llm.env").write_text("LLM_GATEWAY_API_KEY=file-token\n", encoding="utf-8")

    auth = discover_llm_auth_headers(
        "https://gateway.example.com/v1/chat/completions",
        search_paths=[tmp_path],
    )
    assert auth is not None
    assert auth.source == "generic_override"
    assert auth.headers["Authorization"] == "Bearer file-token"


def test_discover_llm_auth_ignores_unrelated_cloud_keys_for_local_endpoints(monkeypatch, tmp_path):
    _clear_env(monkeypatch, OPENAI_API_KEY="openai-token")
    auth = discover_llm_auth_headers(
        "http://127.0.0.1:11434/v1/chat/completions",
        search_paths=[tmp_path],
    )
    assert auth is None
