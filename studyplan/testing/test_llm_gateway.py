from __future__ import annotations

import json
from types import SimpleNamespace

from studyplan.ai.llm_gateway import (
    resolve_openai_compatible_endpoint,
    resolve_openai_compatible_model_candidates,
)


def test_resolve_openai_compatible_endpoint_prefers_gateway_endpoint() -> None:
    config = SimpleNamespace(
        LLM_GATEWAY_ENABLED=True,
        LLM_GATEWAY_ENDPOINT="https://gateway.example.com/v1/chat/completions",
        LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS=11.0,
        LLAMA_CPP_ENDPOINT="https://legacy.example.com/v1/chat/completions",
        CLOUD_LLAMACPP_PREFER_EXTERNAL=True,
    )

    resolved = resolve_openai_compatible_endpoint(config)

    assert resolved is not None
    assert resolved.endpoint == "https://gateway.example.com/v1/chat/completions"
    assert resolved.source == "gateway"
    assert resolved.request_timeout_seconds == 11.0
    assert resolved.auth_mode == "discovery"


def test_resolve_openai_compatible_endpoint_falls_back_to_external_llama_cpp() -> None:
    config = SimpleNamespace(
        LLM_GATEWAY_ENABLED=False,
        LLM_GATEWAY_ENDPOINT="",
        LLAMA_CPP_ENDPOINT="https://api.example.com/v1/chat/completions",
        CLOUD_LLAMACPP_PREFER_EXTERNAL=True,
        CLOUD_LLAMACPP_REQUEST_TIMEOUT_SECONDS=9.0,
    )

    resolved = resolve_openai_compatible_endpoint(config)

    assert resolved is not None
    assert resolved.endpoint == "https://api.example.com/v1/chat/completions"
    assert resolved.source == "llama_cpp_cloud"
    assert resolved.request_timeout_seconds == 9.0
    assert resolved.auth_mode == "cloud_llamacpp"


def test_resolve_openai_compatible_endpoint_ignores_gateway_when_disabled() -> None:
    config = SimpleNamespace(
        LLM_GATEWAY_ENABLED=False,
        LLM_GATEWAY_ENDPOINT="https://gateway.example.com/v1/chat/completions",
        LLAMA_CPP_ENDPOINT="https://api.example.com/v1/chat/completions",
        CLOUD_LLAMACPP_PREFER_EXTERNAL=True,
        CLOUD_LLAMACPP_REQUEST_TIMEOUT_SECONDS=8.0,
    )
    resolved = resolve_openai_compatible_endpoint(config)
    assert resolved is not None
    assert resolved.source == "llama_cpp_cloud"


def test_resolve_openai_compatible_model_candidates_prefers_routed_gateway_models(
    monkeypatch,
    tmp_path,
) -> None:
    routing_path = tmp_path / "llm_model_routing.json"
    routing_path.write_text(
        json.dumps(
            {
                "purposes": {
                    "tutor": {
                        "primary": "openrouter/google/gemini-2.5-flash",
                        "failover_chain": [
                            "openrouter/openai/gpt-4o-mini",
                            "openrouter/anthropic/claude-3.5-sonnet",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDYPLAN_LLM_MODEL_ROUTING_PATH", str(routing_path))

    candidates = resolve_openai_compatible_model_candidates(
        purpose="tutor",
        requested_model="",
        configured_model="openrouter/google/gemini-2.5-flash",
        fallback_models="openrouter/openai/gpt-4o-mini, openrouter/anthropic/claude-3.5-sonnet",
    )

    assert candidates == [
        "openrouter/google/gemini-2.5-flash",
        "openrouter/openai/gpt-4o-mini",
        "openrouter/anthropic/claude-3.5-sonnet",
    ]


