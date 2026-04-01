import json
import urllib.error

import studyplan.services as services_mod
from studyplan.ai.llm_gateway import ResolvedOpenAICompatibleEndpoint
from studyplan.contracts import TutorTurnRequest
from studyplan.services import LlamaCppTutorService


class _DummyResponse:
    def __init__(self, payload: str, status: int = 200):
        self._payload = payload.encode("utf-8")
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _req() -> TutorTurnRequest:
    return TutorTurnRequest(
        model="",
        prompt="Explain NPV in one line.",
        history_fingerprint="npv",
        context_budget_chars=4000,
        rag_budget_chars=1200,
    )


def _assert_llama_stability_telemetry(telemetry: dict):
    assert telemetry.get("provider") == "llama.cpp"
    assert isinstance(telemetry.get("latency_ms"), int)
    assert isinstance(telemetry.get("retry_count"), int)
    assert isinstance(telemetry.get("fallback_used"), bool)
    assert isinstance(telemetry.get("error_code"), str)


def test_llama_cpp_service_success(monkeypatch):
    payload = {"choices": [{"message": {"content": "NPV discounts cash flows to present value."}}]}

    def fake_urlopen(request, timeout):
        return _DummyResponse(json.dumps(payload), status=200)

    monkeypatch.setattr(services_mod.urllib.request, "urlopen", fake_urlopen)
    svc = LlamaCppTutorService(
        endpoint="http://localhost:8080/v1/chat/completions",
        model="llama-test",
        enabled=True,
        max_retries=0,
        auto_model_discovery=False,
    )
    result = svc.generate(_req())
    assert result.error_code == ""
    assert "discounts cash flows" in result.text
    assert result.telemetry.get("fallback_used") is False
    _assert_llama_stability_telemetry(result.telemetry)


def test_llama_cpp_service_retries_timeout_then_succeeds(monkeypatch):
    payload = {"choices": [{"message": {"content": "Retry success."}}]}
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("timed out")
        return _DummyResponse(json.dumps(payload), status=200)

    monkeypatch.setattr(services_mod.urllib.request, "urlopen", fake_urlopen)
    svc = LlamaCppTutorService(
        endpoint="http://localhost:8080/v1/chat/completions",
        model="llama-test",
        enabled=True,
        max_retries=1,
        auto_model_discovery=False,
    )
    result = svc.generate(_req())
    assert result.error_code == ""
    assert result.text == "Retry success."
    assert int(result.telemetry.get("retry_count", -1)) == 1
    assert calls["n"] == 2
    _assert_llama_stability_telemetry(result.telemetry)


def test_llama_cpp_service_invalid_json_fallback(monkeypatch):
    def fake_urlopen(request, timeout):
        return _DummyResponse("not-json", status=200)

    monkeypatch.setattr(services_mod.urllib.request, "urlopen", fake_urlopen)
    svc = LlamaCppTutorService(
        endpoint="http://localhost:8080/v1/chat/completions",
        model="llama-test",
        enabled=True,
        max_retries=0,
        auto_model_discovery=False,
    )
    result = svc.generate(_req())
    assert result.error_code == "invalid_json"
    assert result.telemetry.get("fallback_used") is True
    assert result.telemetry.get("fallback_code") == "fallback_invalid_output"
    assert "temporarily unavailable" in result.text.lower()
    _assert_llama_stability_telemetry(result.telemetry)


def test_llama_cpp_service_empty_output_fallback(monkeypatch):
    payload = {"choices": [{"message": {"content": "   "}}]}

    def fake_urlopen(request, timeout):
        return _DummyResponse(json.dumps(payload), status=200)

    monkeypatch.setattr(services_mod.urllib.request, "urlopen", fake_urlopen)
    svc = LlamaCppTutorService(
        endpoint="http://localhost:8080/v1/chat/completions",
        model="llama-test",
        enabled=True,
        max_retries=0,
        auto_model_discovery=False,
    )
    result = svc.generate(_req())
    assert result.error_code == "empty_output"
    assert result.telemetry.get("fallback_used") is True
    assert result.telemetry.get("fallback_code") == "fallback_unknown"
    _assert_llama_stability_telemetry(result.telemetry)


def test_llama_cpp_service_auto_discovers_ollama_models_prefers_fast_cpp(monkeypatch):
    tags_payload = {
        "models": [
            {"name": "gpt4all-llama-3-2-3b-instruct-q4-0:latest"},
            {"name": "llama3.1:8b-instruct-q8_0"},
        ]
    }

    def fake_urlopen(request, timeout):
        url = str(getattr(request, "full_url", request))
        if url.endswith("/api/tags"):
            return _DummyResponse(json.dumps(tags_payload), status=200)
        body = b""
        if hasattr(request, "data"):
            body = bytes(getattr(request, "data") or b"")
        parsed = json.loads(body.decode("utf-8"))
        model_name = str(parsed.get("model", "") or "")
        if model_name == "gpt4all-llama-3-2-3b-instruct-q4-0:latest":
            return _DummyResponse(json.dumps({"choices": [{"message": {"content": "Fast model selected."}}]}), status=200)
        return _DummyResponse(json.dumps({"choices": [{"message": {"content": "Other model."}}]}), status=200)

    monkeypatch.setattr(services_mod.urllib.request, "urlopen", fake_urlopen)
    svc = LlamaCppTutorService(
        endpoint="http://localhost:8080/v1/chat/completions",
        model="",
        enabled=True,
        max_retries=0,
        auto_model_discovery=True,
        ollama_discovery_enabled=True,
        gpt4all_discovery_enabled=False,
        ollama_host="http://127.0.0.1:11434",
    )
    result = svc.generate(_req())
    assert result.error_code == ""
    assert result.model == "gpt4all-llama-3-2-3b-instruct-q4-0:latest"
    assert "Fast model selected" in result.text
    assert int(result.telemetry.get("model_candidates_count", 0)) >= 2
    assert result.telemetry.get("model_source") == "ollama"
    _assert_llama_stability_telemetry(result.telemetry)


def test_llama_cpp_service_fails_over_to_gpt4all_discovered_model(monkeypatch):
    first_model = "gpt4all-aaa-missing:latest"
    expected_model = "gpt4all-zzz-recovered:latest"

    def fake_isdir(path: str) -> bool:
        return True

    def fake_listdir(path: str):
        return ["aaa-missing.gguf", "zzz-recovered.gguf"]

    def fake_urlopen(request, timeout):
        url = str(getattr(request, "full_url", request))
        if url.endswith("/api/tags"):
            return _DummyResponse(json.dumps({"models": []}), status=200)
        body = b""
        if hasattr(request, "data"):
            body = bytes(getattr(request, "data") or b"")
        parsed = json.loads(body.decode("utf-8"))
        model_name = str(parsed.get("model", "") or "")
        if model_name == first_model:
            return _DummyResponse('{"error":{"message":"model missing"}}', status=404)
        if model_name == expected_model:
            return _DummyResponse(json.dumps({"choices": [{"message": {"content": "Recovered model."}}]}), status=200)
        raise AssertionError(f"unexpected model: {model_name}")

    monkeypatch.setattr(services_mod.os.path, "isdir", fake_isdir)
    monkeypatch.setattr(services_mod.os, "listdir", fake_listdir)
    monkeypatch.setattr(services_mod.urllib.request, "urlopen", fake_urlopen)
    svc = LlamaCppTutorService(
        endpoint="http://localhost:8080/v1/chat/completions",
        model="",
        enabled=True,
        max_retries=0,
        auto_model_discovery=True,
        ollama_discovery_enabled=False,
        gpt4all_discovery_enabled=True,
        gpt4all_models_dir="/tmp/gpt4all-models",
    )
    result = svc.generate(_req())
    assert result.error_code == ""
    assert result.model == expected_model
    assert result.text == "Recovered model."
    assert int(result.telemetry.get("retry_count", 0)) >= 1
    assert result.telemetry.get("model_source") == "gpt4all"
    _assert_llama_stability_telemetry(result.telemetry)


def test_llama_cpp_service_gateway_backend_skips_local_discovery(monkeypatch):
    calls = {"tags": 0, "chat": 0}

    def fake_urlopen(request, timeout):
        url = str(getattr(request, "full_url", request))
        if url.endswith("/api/tags"):
            calls["tags"] += 1
            return _DummyResponse(json.dumps({"models": []}), status=200)
        calls["chat"] += 1
        body = b""
        if hasattr(request, "data"):
            body = bytes(getattr(request, "data") or b"")
        parsed = json.loads(body.decode("utf-8"))
        assert str(parsed.get("model", "") or "") == "gateway-primary"
        return _DummyResponse(json.dumps({"choices": [{"message": {"content": "Gateway route."}}]}), status=200)

    monkeypatch.setattr(services_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(services_mod.Config, "LLM_GATEWAY_MODEL", "gateway-primary", raising=False)
    monkeypatch.setattr(services_mod.Config, "LLM_GATEWAY_MODEL_FALLBACKS", "gateway-backup", raising=False)
    svc = LlamaCppTutorService(
        endpoint="http://localhost:8080/v1/chat/completions",
        model="local-should-not-be-discovered",
        resolved_backend=ResolvedOpenAICompatibleEndpoint(
            endpoint="https://api.example.com/v1/chat/completions",
            source="gateway",
        ),
        enabled=True,
        max_retries=0,
        auto_model_discovery=True,
        ollama_discovery_enabled=True,
        gpt4all_discovery_enabled=True,
        ollama_host="http://127.0.0.1:11434",
        gpt4all_models_dir="/tmp/gpt4all-models",
    )
    result = svc.generate(_req())
    assert result.error_code == ""
    assert result.model == "gateway-primary"
    assert result.telemetry.get("model_selection_mode") == "gateway_configured"
    assert result.telemetry.get("model_source") == "gateway"
    assert calls["tags"] == 0
    assert calls["chat"] >= 1
