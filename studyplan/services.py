from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Callable, Protocol, Sequence

logger = logging.getLogger(__name__)

from .ai.prompt_design import (
    ASSESSMENT_JUDGE_ROLE_BASE,
    ASSESSMENT_JUDGE_RULES,
    ASSESSMENT_JUDGE_SCHEMA_ONE_LINE,
    JUDGE_JSON_ONLY,
    build_judge_prompt_3es,
)
from .ai.llm_auth import discover_llm_auth_headers
from .ai.recovery import build_deterministic_fallback_response
from .config import Config
from .contracts import (
    AppStateSnapshot,
    AutopilotDecision,
    AutopilotExecutionResult,
    CompetencyEdge,
    CompetencyNode,
    JudgmentRubricTemplate,
    MisconceptionPattern,
    ModuleDescriptor,
    RagQueryRequest,
    RagSourceHint,
    RagQueryResult,
    ProblemStructure,
    StructureType,
    SurfaceVariant,
    TransferAttempt,
    TransferScore,
    TutorActionIntent,
    TutorAssessmentResult,
    TutorAssessmentSubmission,
    TutorLearnerProfileSnapshot,
    TutorLoopTurnRequest,
    TutorLoopTurnResult,
    TutorPracticeItem,
    TutorSessionState,
    TutorTurnRequest,
    TutorTurnResult,
)


class TutorService(Protocol):
    def generate(self, request: TutorTurnRequest) -> TutorTurnResult: ...


class CoachService(Protocol):
    def recommend(self, snapshot: dict[str, object]) -> dict[str, object]: ...


class RagService(Protocol):
    def retrieve(self, request: RagQueryRequest) -> RagQueryResult: ...


class AutopilotService(Protocol):
    def tick(self, snapshot: dict[str, object]) -> AutopilotDecision: ...

    def execute(self, decision: AutopilotDecision) -> AutopilotExecutionResult: ...


class ModelSelector(Protocol):
    def rank(self, models: list[str], purpose: str = "general") -> list[dict[str, object]]: ...


class TelemetryService(Protocol):
    def record(self, event: dict[str, object]) -> dict[str, object]: ...


class TutorLearningLoopService(Protocol):
    def run_turn(self, request: TutorLoopTurnRequest) -> TutorLoopTurnResult: ...


class TutorPracticeService(Protocol):
    def build_practice_items(
        self,
        *,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
        max_items: int = 3,
    ) -> tuple[TutorPracticeItem, ...]: ...

    def build_retest_variant(
        self,
        *,
        item: TutorPracticeItem,
        assessment_result: TutorAssessmentResult,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> TutorPracticeItem | None: ...


class TutorAssessmentService(Protocol):
    def assess(
        self,
        *,
        item: TutorPracticeItem,
        submission: TutorAssessmentSubmission,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> TutorAssessmentResult: ...


class TutorLearnerModelService(Protocol):
    def get_or_create_profile(self, learner_id: str, module: str) -> TutorLearnerProfileSnapshot: ...

    def save_profile(self, profile: TutorLearnerProfileSnapshot) -> TutorLearnerProfileSnapshot: ...

    def note_assessment(
        self,
        learner_id: str,
        module: str,
        assessment: TutorAssessmentResult,
        *,
        confidence: int | None = None,
    ) -> TutorLearnerProfileSnapshot: ...


class TutorInterventionPolicyService(Protocol):
    def choose_intervention(
        self,
        *,
        item: TutorPracticeItem,
        assessment_result: TutorAssessmentResult,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> dict[str, object]: ...


class TutorActionPolicyService(Protocol):
    def evaluate(
        self,
        intent: TutorActionIntent,
        *,
        app_snapshot: AppStateSnapshot,
        autonomy_mode: str,
    ) -> dict[str, object]: ...


class TutorSessionControllerService(Protocol):
    def get_or_create_session(
        self,
        *,
        session_id: str,
        module: str,
        topic: str,
    ) -> TutorSessionState: ...

    def save_session(self, state: TutorSessionState) -> TutorSessionState: ...

    def reset_session(self, session_id: str) -> None: ...

    def start_or_resume_session(
        self,
        *,
        session_id: str,
        module: str,
        topic: str,
        mode: str = "auto",
        session_objective: str = "",
        success_criteria: str = "",
        target_concepts: tuple[str, ...] = (),
    ) -> TutorSessionState: ...

    def advance_phase(self, session_id: str, phase: str) -> TutorSessionState: ...

    def record_assessment_outcome(
        self,
        session_id: str,
        *,
        outcome: str,
        practice_item_id: str = "",
        increment_streak: bool = False,
    ) -> TutorSessionState: ...


class TutorPromptOrchestrationService(Protocol):
    def build_turn_prompt(self, request: TutorLoopTurnRequest) -> dict[str, object]: ...


@dataclass
class LlamaCppTutorService:
    """TutorService implementation for llama.cpp OpenAI-compatible endpoints.

    When ``managed_runtime`` is set, the service delegates model discovery
    and server lifecycle to the llama.cpp-first runtime (direct GGUF
    loading via ``llama-server``).  The legacy Ollama-based discovery
    path is kept as a fallback.
    """

    endpoint: str = field(default_factory=lambda: str(getattr(Config, "LLAMA_CPP_ENDPOINT", "") or "").strip())
    model: str = field(default_factory=lambda: str(getattr(Config, "LLAMA_CPP_MODEL", "") or "").strip())
    enabled: bool = field(default_factory=lambda: bool(getattr(Config, "LLAMA_CPP_ENABLED", True)))
    timeout_seconds: float = field(
        default_factory=lambda: float(getattr(Config, "LLAMA_CPP_TIMEOUT_SECONDS", 30.0) or 30.0)
    )
    max_retries: int = field(default_factory=lambda: int(getattr(Config, "LLAMA_CPP_MAX_RETRIES", 2) or 2))
    temperature: float = field(default_factory=lambda: float(getattr(Config, "LLAMA_CPP_TEMPERATURE", 0.2) or 0.2))
    top_p: float = field(default_factory=lambda: float(getattr(Config, "LLAMA_CPP_TOP_P", 0.95) or 0.95))
    context_window: int = field(
        default_factory=lambda: int(getattr(Config, "LLAMA_CPP_CONTEXT_WINDOW", 8192) or 8192)
    )
    auto_model_discovery: bool = field(
        default_factory=lambda: bool(getattr(Config, "LLAMA_CPP_AUTO_MODEL_DISCOVERY", True))
    )
    ollama_discovery_enabled: bool = field(
        default_factory=lambda: bool(getattr(Config, "LLAMA_CPP_OLLAMA_DISCOVERY_ENABLED", True))
    )
    gpt4all_discovery_enabled: bool = field(
        default_factory=lambda: bool(getattr(Config, "LLAMA_CPP_GPT4ALL_DISCOVERY_ENABLED", True))
    )
    ollama_host: str = field(default_factory=lambda: str(getattr(Config, "LLAMA_CPP_OLLAMA_HOST", "") or "").strip())
    gpt4all_models_dir: str = field(
        default_factory=lambda: str(getattr(Config, "LLAMA_CPP_GPT4ALL_MODELS_DIR", "") or "").strip()
    )
    model_preference: str = field(
        default_factory=lambda: str(getattr(Config, "LLAMA_CPP_MODEL_PREFERENCE", "fast_cpp") or "fast_cpp").strip().lower()
    )
    model_discovery_ttl_seconds: float = field(
        default_factory=lambda: float(getattr(Config, "LLAMA_CPP_MODEL_DISCOVERY_TTL_SECONDS", 120.0) or 120.0)
    )
    _model_catalog_cached_at: float = field(default=0.0, init=False, repr=False)
    _model_catalog_cached: tuple[str, ...] = field(default_factory=tuple, init=False, repr=False)
    _model_catalog_sources: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    # llama.cpp-first managed runtime (None = use legacy Ollama discovery path)
    managed_runtime: Any = field(default=None)
    # Registry model name to try before automatic ranking (same semantics as app Preferences).
    preferred_managed_gguf: str = field(default_factory=lambda: "")
    _runtime_init_done: bool = field(default=False, init=False, repr=False)

    # Performance optimization fields
    performance_profiler: PerformanceProfiler | None = field(default=None)
    performance_cache: PerformanceCacheService | None = field(default=None)
    performance_middleware: PerformanceMiddleware | None = field(default=None)

    RETRYABLE_ERROR_CODES: tuple[str, ...] = (
        "timeout",
        "busy",
        "host_unreachable",
        "stream_stall",
        "invalid_output",
        "invalid_json",
        "empty_output",
        "http_error",
    )

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            out = int(value)
        except Exception:
            out = int(default)
        if out < minimum:
            out = minimum
        if out > maximum:
            out = maximum
        return out

    @staticmethod
    def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            out = float(value)
        except Exception:
            out = float(default)
        if out < minimum:
            out = minimum
        if out > maximum:
            out = maximum
        return out

    @staticmethod
    def _coerce_text(value: Any, default: str = "") -> str:
        text = str(value or "").strip()
        return text if text else str(default or "")

    @staticmethod
    def _normalize_ollama_host(host: str) -> str:
        raw = str(host or "").strip()
        if not raw:
            return ""
        if not re.match(r"^[a-z]+://", raw, flags=re.IGNORECASE):
            raw = f"http://{raw}"
        return raw.rstrip("/")

    @staticmethod
    def _normalize_gpt4all_filename_to_model(filename: str) -> str:
        stem = str(os.path.splitext(str(filename or ""))[0] or "").strip().lower()
        norm = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
        if not norm:
            return ""
        if not norm.startswith("gpt4all-"):
            norm = f"gpt4all-{norm}"
        return f"{norm}:latest"

    @staticmethod
    def _de_dupe(items: Sequence[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            name = str(item or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
        return out

    def _discover_ollama_models(self) -> list[str]:
        if not self.ollama_discovery_enabled:
            return []
        host = self._normalize_ollama_host(self.ollama_host)
        if not host:
            return []
        url = f"{host}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=self._clamp_float(self.timeout_seconds, 8.0, 2.0, 30.0)) as response:
                raw = response.read()
        except Exception:
            return []
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []
        models_node = payload.get("models")
        if not isinstance(models_node, list):
            return []
        out: list[str] = []
        for item in models_node:
            if not isinstance(item, dict):
                continue
            name = self._coerce_text(item.get("name"), "")
            if name:
                out.append(name)
        return self._de_dupe(out)

    def _discover_gpt4all_models(self) -> list[str]:
        if not self.gpt4all_discovery_enabled:
            return []
        models_dir = self._coerce_text(self.gpt4all_models_dir, "")
        if not models_dir:
            return []
        expanded = os.path.expanduser(models_dir)
        if not os.path.isdir(expanded):
            return []
        out: list[str] = []
        try:
            files = sorted(os.listdir(expanded))
        except Exception:
            return []
        for name in files:
            lower = str(name or "").lower()
            if not lower.endswith(".gguf"):
                continue
            model_name = self._normalize_gpt4all_filename_to_model(name)
            if model_name:
                out.append(model_name)
        return self._de_dupe(out)

    def _fast_cpp_rank_key(self, model_name: str) -> tuple[float, int, str]:
        name = str(model_name or "").strip().lower()
        if not name:
            return (9999.0, 9999, "")
        score = 0.0
        size_match = re.search(r"(\d+(?:\.\d+)?)b", name)
        if size_match:
            try:
                score += float(size_match.group(1))
            except Exception:
                score += 8.0
        else:
            score += 8.0
        if "q2" in name:
            score -= 2.0
        elif "q3" in name:
            score -= 1.5
        elif "q4" in name:
            score -= 1.0
        elif "q5" in name:
            score -= 0.4
        elif "q8" in name:
            score += 0.7
        if any(tok in name for tok in ("mini", "tiny", "small", "1b", "1.5b", "2b", "3b")):
            score -= 0.35
        if any(tok in name for tok in ("32b", "34b", "70b", "72b")):
            score += 10.0
        if name.startswith("gpt4all-"):
            score -= 0.15
        return (score, len(name), name)

    def _sort_model_candidates(self, models: Sequence[str]) -> list[str]:
        deduped = self._de_dupe(models)
        preference = self._coerce_text(self.model_preference, "fast_cpp").lower()
        if preference == "fast_cpp":
            return sorted(deduped, key=self._fast_cpp_rank_key)
        if preference == "alphabetical":
            return sorted(deduped)
        return deduped

    def _discover_model_catalog(self) -> tuple[list[str], dict[str, str], bool]:
        ttl = self._clamp_float(self.model_discovery_ttl_seconds, 120.0, 5.0, 3600.0)
        now = time.monotonic()
        if self._model_catalog_cached and (now - float(self._model_catalog_cached_at or 0.0)) <= ttl:
            return (
                list(self._model_catalog_cached),
                dict(self._model_catalog_sources),
                True,
            )
        source_map: dict[str, str] = {}
        for model_name in self._discover_ollama_models():
            source_map.setdefault(model_name, "ollama")
        for model_name in self._discover_gpt4all_models():
            source_map.setdefault(model_name, "gpt4all")
        models_sorted = self._sort_model_candidates(list(source_map.keys()))
        self._model_catalog_cached = tuple(models_sorted)
        self._model_catalog_sources = dict(source_map)
        self._model_catalog_cached_at = now
        return models_sorted, source_map, False

    def _resolve_model_candidates(self, request_model: str) -> tuple[list[str], dict[str, str], dict[str, Any]]:
        requested = self._coerce_text(request_model, "")
        configured = self._coerce_text(self.model, "")
        if requested:
            return [requested], {requested: "request"}, {"mode": "request_model", "cache_hit": False}

        if not self.auto_model_discovery:
            if configured:
                return [configured], {configured: "configured"}, {"mode": "configured_only", "cache_hit": False}
            return [], {}, {"mode": "configured_only", "cache_hit": False}

        discovered, source_map, cache_hit = self._discover_model_catalog()
        models = list(discovered)
        if configured and configured not in source_map:
            source_map[configured] = "configured"
            models.append(configured)
        models = self._sort_model_candidates(models)
        return (
            models,
            source_map,
            {
                "mode": "auto_discovery",
                "cache_hit": bool(cache_hit),
            },
        )

    def _normalize_request(self, request: TutorTurnRequest) -> dict[str, Any]:
        model_name = self._coerce_text(getattr(request, "model", ""), self.model)
        if not model_name:
            model_name = self._coerce_text(self.model, "")
        prompt = self._coerce_text(getattr(request, "prompt", ""))
        context_budget_chars = self._clamp_int(
            getattr(request, "context_budget_chars", 4000),
            default=4000,
            minimum=256,
            maximum=20000,
        )
        rag_budget_chars = self._clamp_int(
            getattr(request, "rag_budget_chars", 1500),
            default=1500,
            minimum=0,
            maximum=20000,
        )
        return {
            "model": model_name,
            "prompt": prompt,
            "history_fingerprint": self._coerce_text(getattr(request, "history_fingerprint", "")),
            "context_budget_chars": context_budget_chars,
            "rag_budget_chars": rag_budget_chars,
        }

    def _build_payload(self, normalized: dict[str, Any]) -> dict[str, Any]:
        prompt = self._coerce_text(normalized.get("prompt"), "")
        approx_prompt_tokens = max(1, len(prompt) // 4)
        max_completion_tokens = max(
            64,
            min(
                1024,
                int(self.context_window) - int(approx_prompt_tokens),
            ),
        )
        return {
            "model": self._coerce_text(normalized.get("model"), self.model),
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": self._clamp_float(self.temperature, 0.2, 0.0, 2.0),
            "top_p": self._clamp_float(self.top_p, 0.95, 0.0, 1.0),
            "max_tokens": max_completion_tokens,
            "stream": False,
        }

    @staticmethod
    def _map_http_error(status_code: int, body_text: str) -> str:
        lower = str(body_text or "").lower()
        if status_code == 404:
            if "model" in lower and ("not found" in lower or "missing" in lower):
                return "model_missing"
            return "endpoint_missing"
        if status_code in {408, 504}:
            return "timeout"
        if status_code in {429, 503}:
            return "busy"
        return "http_error"

    @staticmethod
    def _map_url_error(reason: Any, message: str) -> str:
        reason_text = str(reason or "").strip().lower()
        message_text = str(message or "").strip().lower()
        if "timed out" in reason_text or "timed out" in message_text or "timeout" in message_text:
            return "timeout"
        if any(token in reason_text for token in ("refused", "unreachable", "failed")):
            return "host_unreachable"
        return "host_unreachable"

    @staticmethod
    def _extract_assistant_text(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return ""

    def _invoke_once(self, normalized: dict[str, Any]) -> tuple[bool, str, str, dict[str, Any]]:
        payload = self._build_payload(normalized)
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        try:
            resolved_auth = discover_llm_auth_headers(
                self.endpoint,
                search_paths=[
                    str(getattr(Config, "CONFIG_HOME", "") or ""),
                    os.getcwd(),
                ],
            )
        except Exception:
            resolved_auth = None
        if resolved_auth is not None:
            headers.update(resolved_auth.headers)
        request = urllib.request.Request(
            url=self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._clamp_float(self.timeout_seconds, 30.0, 1.0, 300.0)) as response:
                status = int(getattr(response, "status", 200) or 200)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = b""
            try:
                raw = exc.read() or b""
            except Exception:
                raw = b""
            body_text = raw.decode("utf-8", errors="replace")
            error_code = self._map_http_error(int(getattr(exc, "code", 500) or 500), body_text)
            return (
                False,
                "",
                error_code,
                {"status_code": int(getattr(exc, "code", 500) or 500), "error_message": self._coerce_text(body_text)},
            )
        except urllib.error.URLError as exc:
            message = self._coerce_text(getattr(exc, "reason", ""), str(exc))
            return (
                False,
                "",
                self._map_url_error(getattr(exc, "reason", ""), message),
                {"status_code": 0, "error_message": message},
            )
        except TimeoutError as exc:
            return (False, "", "timeout", {"status_code": 0, "error_message": self._coerce_text(str(exc), "timeout")})
        except Exception as exc:
            return (
                False,
                "",
                "unknown_error",
                {"status_code": 0, "error_message": self._coerce_text(str(exc), "unknown error")},
            )

        text_payload = raw.decode("utf-8", errors="replace")
        if status >= 400:
            return (
                False,
                "",
                self._map_http_error(status, text_payload),
                {"status_code": status, "error_message": self._coerce_text(text_payload)},
            )
        try:
            decoded = json.loads(text_payload)
        except Exception:
            return (
                False,
                "",
                "invalid_json",
                {"status_code": status, "error_message": "json parse failed"},
            )
        if not isinstance(decoded, dict):
            return (
                False,
                "",
                "invalid_output",
                {"status_code": status, "error_message": "response payload is not an object"},
            )
        if isinstance(decoded.get("error"), dict):
            err = dict(decoded.get("error", {}))
            msg = self._coerce_text(err.get("message"), "model returned error")
            code = self._coerce_text(err.get("code"), "http_error").lower()
            mapped = code if code in {"model_missing", "endpoint_missing", "timeout", "busy"} else "http_error"
            return (
                False,
                "",
                mapped,
                {"status_code": status, "error_message": msg},
            )
        text = self._extract_assistant_text(decoded)
        if not text:
            return (
                False,
                "",
                "empty_output",
                {"status_code": status, "error_message": "empty model output"},
            )
        return (
            True,
            text,
            "",
            {"status_code": status, "response_chars": len(text)},
        )

    def _fallback_payload(
        self,
        normalized: dict[str, Any],
        *,
        error_code: str,
        message: str = "",
        model_name: str = "",
    ) -> dict[str, Any]:
        return build_deterministic_fallback_response(
            error_code=error_code,
            message=message,
            model=model_name,
            topic_hint=self._coerce_text(normalized.get("history_fingerprint"), "current topic"),
        )

    def generate(self, request: TutorTurnRequest) -> TutorTurnResult:
        started = time.perf_counter()
        
        # Profile the operation if profiler is available
        if self.performance_profiler:
            return self.performance_profiler.profile_operation(
                "llama_cpp_generate",
                self._generate_with_profiling,
                request,
                started
            )
        
        return self._generate_with_profiling(request, started)
    
    def _ensure_runtime(self, purpose: str = "general") -> None:
        """Lazily initialize managed runtime and update endpoint/model."""
        rt = self.managed_runtime
        if rt is None:
            return
        endpoint_ok = self._coerce_text(self.endpoint)
        if self._runtime_init_done and endpoint_ok:
            server = getattr(rt, "server", None)
            managed_ep = ""
            if server is not None:
                managed_ep = self._coerce_text(getattr(server, "endpoint", ""))
            if managed_ep and endpoint_ok.rstrip("/") == managed_ep.rstrip("/"):
                if not bool(getattr(server, "is_running", False)):
                    self._runtime_init_done = False
            else:
                return
        if self._runtime_init_done and endpoint_ok:
            return
        try:
            pref = str(getattr(self, "preferred_managed_gguf", "") or "").strip()
            status = rt.ensure_ready(purpose, preferred_gguf_name=pref)
        except TypeError:
            try:
                status = rt.ensure_ready(purpose)
            except Exception:
                return
        except Exception:
            return
        if status.healthy and status.endpoint:
            self.endpoint = status.endpoint
            if status.model_name:
                self.model = status.model_name
            self._runtime_init_done = True

    def _generate_with_profiling(self, request: TutorTurnRequest, started: float) -> TutorTurnResult:
        self._ensure_runtime()
        normalized = self._normalize_request(request)
        request_model = self._coerce_text(getattr(request, "model", ""), "")
        model_name = self._coerce_text(request_model, self._coerce_text(normalized.get("model"), self.model))
        model_candidates, candidate_sources, discovery_meta = self._resolve_model_candidates(request_model)
        if model_name and model_name not in model_candidates:
            model_candidates = self._sort_model_candidates([model_name, *model_candidates])
            candidate_sources.setdefault(model_name, "configured")
        primary_model = self._coerce_text(model_candidates[0] if model_candidates else model_name, "")

        runtime_backend = ""
        if self.managed_runtime is not None:
            try:
                runtime_backend = getattr(
                    getattr(self.managed_runtime, "server", None), "current_model", ""
                ) or ""
                if runtime_backend:
                    runtime_backend = "llama_server"
            except Exception:
                pass

        telemetry: dict[str, Any] = {
            "provider": "llama.cpp",
            "endpoint": self._coerce_text(self.endpoint),
            "model": primary_model,
            "model_candidates_count": len(model_candidates),
            "model_candidates_preview": list(model_candidates[:6]),
            "model_selection_mode": str(discovery_meta.get("mode", "configured_only") or "configured_only"),
            "model_catalog_cache_hit": bool(discovery_meta.get("cache_hit", False)),
            "model_preference": self._coerce_text(self.model_preference, "fast_cpp"),
            "runtime_backend": runtime_backend or "external",
            "retry_count": 0,
            "fallback_used": False,
            "error_code": "",
        }
        if not self.enabled:
            error_code = "provider_disabled"
            fallback = self._fallback_payload(
                normalized,
                error_code=error_code,
                message="llama.cpp provider disabled by configuration",
                model_name=model_name,
            )
            telemetry["fallback_used"] = True
            telemetry["error_code"] = str(fallback.get("error_code", error_code) or error_code)
            telemetry["fallback_code"] = str(fallback.get("fallback_code", "") or "")
            telemetry["recovery"] = fallback.get("recovery", {})
            latency_ms = int(max(0.0, (time.perf_counter() - started) * 1000.0))
            telemetry["latency_ms"] = latency_ms
            return TutorTurnResult(
                text=self._coerce_text(fallback.get("text"), ""),
                model=primary_model or "unknown",
                latency_ms=latency_ms,
                error_code=self._coerce_text(fallback.get("error_code"), error_code),
                telemetry=telemetry,
            )
        if not self._coerce_text(self.endpoint):
            error_code = "endpoint_missing"
            fallback = self._fallback_payload(
                normalized,
                error_code=error_code,
                message="llama.cpp endpoint missing",
                model_name=model_name,
            )
            telemetry["fallback_used"] = True
            telemetry["error_code"] = str(fallback.get("error_code", error_code) or error_code)
            telemetry["fallback_code"] = str(fallback.get("fallback_code", "") or "")
            telemetry["recovery"] = fallback.get("recovery", {})
            latency_ms = int(max(0.0, (time.perf_counter() - started) * 1000.0))
            telemetry["latency_ms"] = latency_ms
            return TutorTurnResult(
                text=self._coerce_text(fallback.get("text"), ""),
                model=primary_model or "unknown",
                latency_ms=latency_ms,
                error_code=self._coerce_text(fallback.get("error_code"), error_code),
                telemetry=telemetry,
            )
        if not model_candidates:
            error_code = "model_missing"
            fallback = self._fallback_payload(
                normalized,
                error_code=error_code,
                message="llama.cpp model missing",
                model_name="",
            )
            telemetry["fallback_used"] = True
            telemetry["error_code"] = str(fallback.get("error_code", error_code) or error_code)
            telemetry["fallback_code"] = str(fallback.get("fallback_code", "") or "")
            telemetry["recovery"] = fallback.get("recovery", {})
            latency_ms = int(max(0.0, (time.perf_counter() - started) * 1000.0))
            telemetry["latency_ms"] = latency_ms
            return TutorTurnResult(
                text=self._coerce_text(fallback.get("text"), ""),
                model="unknown",
                latency_ms=latency_ms,
                error_code=self._coerce_text(fallback.get("error_code"), error_code),
                telemetry=telemetry,
            )

        attempts = max(1, self._clamp_int(self.max_retries, 2, 0, 5) + 1)
        final_error = ""
        final_message = ""
        retries_used = 0
        for candidate in model_candidates:
            normalized["model"] = candidate
            telemetry["model"] = candidate
            telemetry["model_source"] = self._coerce_text(candidate_sources.get(candidate), "unknown")
            for attempt_idx in range(attempts):
                ok, text, error_code, meta = self._invoke_once(normalized)
                if self.managed_runtime is not None:
                    try:
                        self.managed_runtime.mark_server_used()
                    except Exception:
                        pass
                telemetry["retry_count"] = int(retries_used)
                if isinstance(meta, dict):
                    telemetry.update(meta)
                if ok:
                    latency_ms = int(max(0.0, (time.perf_counter() - started) * 1000.0))
                    telemetry["latency_ms"] = latency_ms
                    telemetry["fallback_used"] = False
                    telemetry["error_code"] = ""
                    return TutorTurnResult(
                        text=self._coerce_text(text),
                        model=candidate,
                        latency_ms=latency_ms,
                        error_code="",
                        telemetry=telemetry,
                    )
                final_error = self._coerce_text(error_code, "unknown_error")
                final_message = self._coerce_text(meta.get("error_message") if isinstance(meta, dict) else "", "request failed")
                retries_used += 1
                # Move to next discovered model quickly when provider reports missing model.
                if final_error == "model_missing":
                    break
                if final_error not in self.RETRYABLE_ERROR_CODES:
                    break
                if attempt_idx >= (attempts - 1):
                    break

        fallback = self._fallback_payload(
            normalized,
            error_code=final_error or "unknown_error",
            message=final_message,
            model_name=self._coerce_text(normalized.get("model"), primary_model),
        )
        latency_ms = int(max(0.0, (time.perf_counter() - started) * 1000.0))
        telemetry["latency_ms"] = latency_ms
        telemetry["fallback_used"] = True
        telemetry["error_code"] = str(fallback.get("error_code", final_error or "unknown_error") or "unknown_error")
        telemetry["fallback_code"] = str(fallback.get("fallback_code", "") or "")
        telemetry["recovery"] = fallback.get("recovery", {})
        return TutorTurnResult(
            text=self._coerce_text(fallback.get("text"), ""),
            model=self._coerce_text(normalized.get("model"), primary_model) or "unknown",
            latency_ms=latency_ms,
            error_code=self._coerce_text(fallback.get("error_code"), final_error or "unknown_error"),
            telemetry=telemetry,
        )


class ModuleAdapter(Protocol):
    def descriptor(self) -> ModuleDescriptor: ...

    def competency_nodes(self) -> Sequence[CompetencyNode]: ...

    def competency_edges(self) -> Sequence[CompetencyEdge]: ...

    def supported_tutor_modes(self) -> Sequence[str]: ...

    def default_tutor_mode_for_topic(self, topic_id: str) -> str: ...

    def misconception_patterns(self) -> Sequence[MisconceptionPattern]: ...

    def map_error_to_misconceptions(
        self,
        *,
        topic_id: str,
        error_tags: Sequence[str],
        user_answer: str = "",
        expected_answer: str = "",
    ) -> Sequence[str]: ...

    def section_c_rubric_templates(self, topic_id: str | None = None) -> Sequence[JudgmentRubricTemplate]: ...

    def rag_source_hints(self) -> Sequence[RagSourceHint]: ...

    def build_rag_query_variants(
        self,
        *,
        topic_id: str,
        user_prompt: str,
        mode: str,
        weak_competencies: Sequence[str] = (),
    ) -> Sequence[str]: ...

    def infer_transfer_structure(
        self,
        *,
        topic_id: str,
        question_type: str,
        tags: Sequence[str] = (),
        meta: dict[str, Any] | None = None,
    ) -> str | ProblemStructure | None: ...


@dataclass
class ModuleAdapterRegistry:
    _adapters: dict[str, ModuleAdapter] = field(default_factory=dict)

    def register(self, adapter: ModuleAdapter) -> None:
        try:
            code = str(adapter.descriptor().module_code or "").strip().upper()
        except Exception:
            code = ""
        if not code:
            return
        self._adapters[code] = adapter

    def get(self, module_code: str) -> ModuleAdapter | None:
        code = str(module_code or "").strip().upper()
        if not code:
            return None
        return self._adapters.get(code)


@dataclass(frozen=True)
class NullModuleAdapter:
    _descriptor: ModuleDescriptor = field(
        default_factory=lambda: ModuleDescriptor(
            module_code="GENERIC",
            module_title="Generic Module",
            domain_family="generic",
            supports_section_c=True,
            supports_judgment_modes=False,
        )
    )

    def descriptor(self) -> ModuleDescriptor:
        return self._descriptor

    def competency_nodes(self) -> Sequence[CompetencyNode]:
        return ()

    def competency_edges(self) -> Sequence[CompetencyEdge]:
        return ()

    def supported_tutor_modes(self) -> Sequence[str]:
        return (
            "teach",
            "guided_practice",
            "retrieval_drill",
            "error_clinic",
            "exam_technique",
            "section_c_coach",
            "revision_planner",
        )

    def default_tutor_mode_for_topic(self, topic_id: str) -> str:
        _ = topic_id
        return "teach"

    def misconception_patterns(self) -> Sequence[MisconceptionPattern]:
        return ()

    def map_error_to_misconceptions(
        self,
        *,
        topic_id: str,
        error_tags: Sequence[str],
        user_answer: str = "",
        expected_answer: str = "",
    ) -> Sequence[str]:
        _ = (topic_id, user_answer, expected_answer)
        seen: set[str] = set()
        mapped: list[str] = []
        for tag in error_tags:
            text = str(tag or "").strip().lower()
            if not text:
                continue
            if text.startswith("missing_"):
                candidate = f"{text}_concept"
                if candidate not in seen:
                    seen.add(candidate)
                    mapped.append(candidate)
            if len(mapped) >= 3:
                break
        return tuple(mapped)

    def section_c_rubric_templates(self, topic_id: str | None = None) -> Sequence[JudgmentRubricTemplate]:
        _ = topic_id
        return (
            JudgmentRubricTemplate(
                rubric_id="section_c_generic_20",
                label="Constructed response (generic 20 marks)",
                mode="section_c",
                criteria=(
                    ("Technical application", 8),
                    ("Method / workings", 4),
                    ("Evaluation / recommendation", 4),
                    ("Structure / communication", 4),
                ),
            ),
        )

    def rag_source_hints(self) -> Sequence[RagSourceHint]:
        return ()

    def build_rag_query_variants(
        self,
        *,
        topic_id: str,
        user_prompt: str,
        mode: str,
        weak_competencies: Sequence[str] = (),
    ) -> Sequence[str]:
        variants: list[str] = []
        for candidate in (
            str(user_prompt or "").strip(),
            f"{str(topic_id or '').strip()} {str(mode or '').strip()}".strip(),
            f"{str(topic_id or '').strip()} exam pitfalls".strip(),
            " ".join(str(x or "").strip() for x in weak_competencies if str(x or "").strip())[:160].strip(),
        ):
            text = str(candidate or "").strip()
            if text and text not in variants:
                variants.append(text)
        return tuple(variants)

    def infer_transfer_structure(
        self,
        *,
        topic_id: str,
        question_type: str,
        tags: Sequence[str] = (),
        meta: dict[str, Any] | None = None,
    ) -> str | ProblemStructure | None:
        _ = (topic_id, question_type, tags, meta)
        return None


@dataclass(frozen=True)
class FMModuleAdapter:
    _descriptor: ModuleDescriptor = field(
        default_factory=lambda: ModuleDescriptor(
            module_code="FM",
            module_title="Financial Management",
            domain_family="finance",
            supports_section_c=True,
            supports_judgment_modes=True,
        )
    )

    def descriptor(self) -> ModuleDescriptor:
        return self._descriptor

    def competency_nodes(self) -> Sequence[CompetencyNode]:
        return (
            CompetencyNode(id="fm.wacc", topic_id="Cost of Capital", label="WACC", kind="formula", tags=("discount_rate",)),
            CompetencyNode(id="fm.capm", topic_id="Risk Management", label="CAPM", kind="formula", tags=("cost_of_equity",)),
            CompetencyNode(id="fm.working_capital_policy", topic_id="Working Capital Management", label="Working capital policy"),
            CompetencyNode(id="fm.cash_cycle", topic_id="Working Capital Management", label="Cash operating cycle"),
        )

    def competency_edges(self) -> Sequence[CompetencyEdge]:
        return (
            CompetencyEdge("fm.capm", "fm.wacc", "shares_mechanism_with", 0.85),
            CompetencyEdge("fm.working_capital_policy", "fm.cash_cycle", "commonly_confused_with", 0.9),
            CompetencyEdge("fm.cash_cycle", "fm.working_capital_policy", "commonly_confused_with", 0.9),
        )

    def supported_tutor_modes(self) -> Sequence[str]:
        return (
            "teach",
            "guided_practice",
            "retrieval_drill",
            "error_clinic",
            "exam_technique",
            "section_c_coach",
            "revision_planner",
        )

    def default_tutor_mode_for_topic(self, topic_id: str) -> str:
        topic = str(topic_id or "").strip().lower()
        if any(token in topic for token in ("wacc", "capm", "working capital", "cash management", "investment appraisal")):
            return "guided_practice"
        if "risk" in topic:
            return "retrieval_drill"
        return "teach"

    def misconception_patterns(self) -> Sequence[MisconceptionPattern]:
        return (
            MisconceptionPattern(
                id="fm.wc_policy_risk_ignored",
                competency_ids=("fm.working_capital_policy",),
                triggers=("missing_risk", "risk_omitted"),
                corrective_interventions=("worked_example_then_retest", "keyword_recovery"),
            ),
            MisconceptionPattern(
                id="fm.capm_component_confusion",
                competency_ids=("fm.capm",),
                triggers=("formula_direction", "missing_rf", "beta_confusion"),
                corrective_interventions=("step_drill", "worked_example_then_retest"),
            ),
        )

    def map_error_to_misconceptions(
        self,
        *,
        topic_id: str,
        error_tags: Sequence[str],
        user_answer: str = "",
        expected_answer: str = "",
    ) -> Sequence[str]:
        _ = (user_answer, expected_answer)
        topic = str(topic_id or "").lower()
        tags = {str(t or "").strip().lower() for t in error_tags if str(t or "").strip()}
        out: list[str] = []
        if ("working capital" in topic or "cash" in topic) and any(t in tags for t in ("missing_risk", "risk_omitted")):
            out.append("wc_policy_risk_ignored")
        if ("capm" in topic or "risk" in topic) and any(t in tags for t in ("formula_direction", "missing_rf", "beta_confusion")):
            out.append("capm_component_confusion")
        return tuple(out[:3])

    def section_c_rubric_templates(self, topic_id: str | None = None) -> Sequence[JudgmentRubricTemplate]:
        topic = str(topic_id or "").strip()
        label = f"FM Section C ({topic})" if topic else "FM Section C"
        return (
            JudgmentRubricTemplate(
                rubric_id="fm_section_c_20",
                label=label,
                mode="section_c",
                criteria=(
                    ("Technical application to case", 8),
                    ("Method / workings / assumptions", 5),
                    ("Evaluation / recommendation", 4),
                    ("Structure / exam communication", 3),
                ),
            ),
        )

    def rag_source_hints(self) -> Sequence[RagSourceHint]:
        return (
            RagSourceHint(source_key="syllabus", tier="syllabus", priority=10, topic_tags=("all",)),
            RagSourceHint(source_key="course_notes", tier="notes", priority=30, topic_tags=("finance",)),
        )

    def build_rag_query_variants(
        self,
        *,
        topic_id: str,
        user_prompt: str,
        mode: str,
        weak_competencies: Sequence[str] = (),
    ) -> Sequence[str]:
        topic = str(topic_id or "").strip()
        prompt = str(user_prompt or "").strip()
        mode_text = str(mode or "").strip()
        variants: list[str] = []
        for candidate in (
            prompt,
            f"{topic} ACCA finance exam {mode_text}".strip(),
            f"{topic} formula pitfalls assumptions".strip(),
            f"{topic} worked example and common mistakes".strip(),
            (" ".join(str(x or "").strip() for x in weak_competencies if str(x or "").strip())[:180]).strip(),
        ):
            text = str(candidate or "").strip()
            if text and text not in variants:
                variants.append(text)
        return tuple(variants)

    def infer_transfer_structure(
        self,
        *,
        topic_id: str,
        question_type: str,
        tags: Sequence[str] = (),
        meta: dict[str, Any] | None = None,
    ) -> str | ProblemStructure | None:
        _ = (question_type, meta)
        topic = str(topic_id or "").strip().lower()
        tag_set = {str(t or "").strip().lower() for t in tags if str(t or "").strip()}
        if any(tok in tag_set for tok in ("npv", "annuity", "discount")) or any(
            tok in topic for tok in ("investment appraisal", "npv", "annuity")
        ):
            return "npv_annuity_timing_v1"
        if any(tok in tag_set for tok in ("wacc", "capm", "cost_of_capital")) or any(
            tok in topic for tok in ("wacc", "cost of capital", "capital structure")
        ):
            return "wacc_optimization_v1"
        if any(tok in tag_set for tok in ("working_capital", "cash_cycle", "cash_management")) or any(
            tok in topic for tok in ("working capital", "cash management", "cash cycle")
        ):
            return "working_capital_cycle_v1"
        return None


@dataclass(frozen=True)
class FRModuleAdapter:
    """Adapter for ACCA FR (F7) Financial Reporting: rubrics and RAG tuned for IFRS/consolidation."""

    _descriptor: ModuleDescriptor = field(
        default_factory=lambda: ModuleDescriptor(
            module_code="FR",
            module_title="Financial Reporting",
            domain_family="reporting",
            supports_section_c=True,
            supports_judgment_modes=True,
        )
    )

    def descriptor(self) -> ModuleDescriptor:
        return self._descriptor

    def competency_nodes(self) -> Sequence[CompetencyNode]:
        return ()

    def competency_edges(self) -> Sequence[CompetencyEdge]:
        return ()

    def supported_tutor_modes(self) -> Sequence[str]:
        return (
            "teach",
            "guided_practice",
            "retrieval_drill",
            "error_clinic",
            "exam_technique",
            "section_c_coach",
            "revision_planner",
        )

    def default_tutor_mode_for_topic(self, topic_id: str) -> str:
        topic = str(topic_id or "").strip().lower()
        if any(
            token in topic
            for token in ("consolidat", "ifrs", "ias ", "group", "associate", "goodwill", "cash flow")
        ):
            return "guided_practice"
        return "teach"

    def misconception_patterns(self) -> Sequence[MisconceptionPattern]:
        return ()

    def map_error_to_misconceptions(
        self,
        *,
        topic_id: str,
        error_tags: Sequence[str],
        user_answer: str = "",
        expected_answer: str = "",
    ) -> Sequence[str]:
        _ = (topic_id, user_answer, expected_answer)
        seen: set[str] = set()
        mapped: list[str] = []
        for tag in error_tags:
            text = str(tag or "").strip().lower()
            if not text:
                continue
            if text.startswith("missing_"):
                candidate = f"{text}_concept"
                if candidate not in seen:
                    seen.add(candidate)
                    mapped.append(candidate)
            if len(mapped) >= 3:
                break
        return tuple(mapped)

    def section_c_rubric_templates(self, topic_id: str | None = None) -> Sequence[JudgmentRubricTemplate]:
        topic = str(topic_id or "").strip()
        label = f"FR constructed response ({topic})" if topic else "FR constructed response"
        return (
            JudgmentRubricTemplate(
                rubric_id="fr_constructed_20",
                label=label,
                mode="section_c",
                criteria=(
                    ("Technical application (IFRS/standards)", 8),
                    ("Method / workings / disclosure", 5),
                    ("Evaluation / conclusion", 4),
                    ("Structure / exam communication", 3),
                ),
            ),
        )

    def rag_source_hints(self) -> Sequence[RagSourceHint]:
        return (
            RagSourceHint(source_key="syllabus", tier="syllabus", priority=10, topic_tags=("all",)),
            RagSourceHint(source_key="course_notes", tier="notes", priority=30, topic_tags=("reporting", "ifrs")),
        )

    def build_rag_query_variants(
        self,
        *,
        topic_id: str,
        user_prompt: str,
        mode: str,
        weak_competencies: Sequence[str] = (),
    ) -> Sequence[str]:
        topic = str(topic_id or "").strip()
        prompt = str(user_prompt or "").strip()
        mode_text = str(mode or "").strip()
        variants: list[str] = []
        for candidate in (
            prompt,
            f"{topic} ACCA FR Financial Reporting exam {mode_text}".strip(),
            f"{topic} IFRS IAS standards application pitfalls".strip(),
            f"{topic} consolidation group accounting worked example".strip(),
            (" ".join(str(x or "").strip() for x in weak_competencies if str(x or "").strip())[:180]).strip(),
        ):
            text = str(candidate or "").strip()
            if text and text not in variants:
                variants.append(text)
        return tuple(variants)

    def infer_transfer_structure(
        self,
        *,
        topic_id: str,
        question_type: str,
        tags: Sequence[str] = (),
        meta: dict[str, Any] | None = None,
    ) -> str | ProblemStructure | None:
        _ = (topic_id, question_type, tags, meta)
        return None


@dataclass(frozen=True)
class AAModuleAdapter:
    """Adapter for ACCA AA (F8) Audit and Assurance: rubrics and RAG tuned for audit/assurance."""

    _descriptor: ModuleDescriptor = field(
        default_factory=lambda: ModuleDescriptor(
            module_code="AA",
            module_title="Audit and Assurance",
            domain_family="assurance",
            supports_section_c=True,
            supports_judgment_modes=True,
        )
    )

    def descriptor(self) -> ModuleDescriptor:
        return self._descriptor

    def competency_nodes(self) -> Sequence[CompetencyNode]:
        return ()

    def competency_edges(self) -> Sequence[CompetencyEdge]:
        return ()

    def supported_tutor_modes(self) -> Sequence[str]:
        return (
            "teach",
            "guided_practice",
            "retrieval_drill",
            "error_clinic",
            "exam_technique",
            "section_c_coach",
            "revision_planner",
        )

    def default_tutor_mode_for_topic(self, topic_id: str) -> str:
        topic = str(topic_id or "").strip().lower()
        if any(
            token in topic
            for token in ("risk", "internal control", "evidence", "reporting", "materiality")
        ):
            return "guided_practice"
        return "teach"

    def misconception_patterns(self) -> Sequence[MisconceptionPattern]:
        return ()

    def map_error_to_misconceptions(
        self,
        *,
        topic_id: str,
        error_tags: Sequence[str],
        user_answer: str = "",
        expected_answer: str = "",
    ) -> Sequence[str]:
        _ = (topic_id, user_answer, expected_answer)
        seen: set[str] = set()
        mapped: list[str] = []
        for tag in error_tags:
            text = str(tag or "").strip().lower()
            if not text:
                continue
            if text.startswith("missing_"):
                candidate = f"{text}_concept"
                if candidate not in seen:
                    seen.add(candidate)
                    mapped.append(candidate)
            if len(mapped) >= 3:
                break
        return tuple(mapped)

    def section_c_rubric_templates(self, topic_id: str | None = None) -> Sequence[JudgmentRubricTemplate]:
        topic = str(topic_id or "").strip()
        label = f"AA constructed response ({topic})" if topic else "AA constructed response"
        return (
            JudgmentRubricTemplate(
                rubric_id="aa_constructed_20",
                label=label,
                mode="section_c",
                criteria=(
                    ("Audit/assurance application to scenario", 8),
                    ("Method / procedures / rationale", 5),
                    ("Evaluation / conclusion / reporting", 4),
                    ("Structure / exam communication", 3),
                ),
            ),
        )

    def rag_source_hints(self) -> Sequence[RagSourceHint]:
        return (
            RagSourceHint(source_key="syllabus", tier="syllabus", priority=10, topic_tags=("all",)),
            RagSourceHint(source_key="course_notes", tier="notes", priority=30, topic_tags=("audit", "assurance")),
        )

    def build_rag_query_variants(
        self,
        *,
        topic_id: str,
        user_prompt: str,
        mode: str,
        weak_competencies: Sequence[str] = (),
    ) -> Sequence[str]:
        topic = str(topic_id or "").strip()
        prompt = str(user_prompt or "").strip()
        mode_text = str(mode or "").strip()
        variants: list[str] = []
        for candidate in (
            prompt,
            f"{topic} ACCA AA Audit and Assurance exam {mode_text}".strip(),
            f"{topic} audit procedures evidence materiality".strip(),
            f"{topic} internal control risk assessment reporting".strip(),
            (" ".join(str(x or "").strip() for x in weak_competencies if str(x or "").strip())[:180]).strip(),
        ):
            text = str(candidate or "").strip()
            if text and text not in variants:
                variants.append(text)
        return tuple(variants)

    def infer_transfer_structure(
        self,
        *,
        topic_id: str,
        question_type: str,
        tags: Sequence[str] = (),
        meta: dict[str, Any] | None = None,
    ) -> str | ProblemStructure | None:
        _ = (topic_id, question_type, tags, meta)
        return None


@dataclass(frozen=True)
class TXModuleAdapter:
    """Adapter for ACCA TX (F6) Taxation: rubrics and RAG tuned for tax."""

    _descriptor: ModuleDescriptor = field(
        default_factory=lambda: ModuleDescriptor(
            module_code="TX",
            module_title="Taxation",
            domain_family="tax",
            supports_section_c=True,
            supports_judgment_modes=True,
        )
    )

    def descriptor(self) -> ModuleDescriptor:
        return self._descriptor

    def competency_nodes(self) -> Sequence[CompetencyNode]:
        return ()

    def competency_edges(self) -> Sequence[CompetencyEdge]:
        return ()

    def supported_tutor_modes(self) -> Sequence[str]:
        return (
            "teach",
            "guided_practice",
            "retrieval_drill",
            "error_clinic",
            "exam_technique",
            "section_c_coach",
            "revision_planner",
        )

    def default_tutor_mode_for_topic(self, topic_id: str) -> str:
        topic = str(topic_id or "").strip().lower()
        if any(
            token in topic
            for token in ("computation", "tax", "vat", "allowance", "relief", "corporation")
        ):
            return "guided_practice"
        return "teach"

    def misconception_patterns(self) -> Sequence[MisconceptionPattern]:
        return ()

    def map_error_to_misconceptions(
        self,
        *,
        topic_id: str,
        error_tags: Sequence[str],
        user_answer: str = "",
        expected_answer: str = "",
    ) -> Sequence[str]:
        _ = (topic_id, user_answer, expected_answer)
        seen: set[str] = set()
        mapped: list[str] = []
        for tag in error_tags:
            text = str(tag or "").strip().lower()
            if not text:
                continue
            if text.startswith("missing_"):
                candidate = f"{text}_concept"
                if candidate not in seen:
                    seen.add(candidate)
                    mapped.append(candidate)
            if len(mapped) >= 3:
                break
        return tuple(mapped)

    def section_c_rubric_templates(self, topic_id: str | None = None) -> Sequence[JudgmentRubricTemplate]:
        topic = str(topic_id or "").strip()
        label = f"TX constructed response ({topic})" if topic else "TX constructed response"
        return (
            JudgmentRubricTemplate(
                rubric_id="tx_constructed_20",
                label=label,
                mode="section_c",
                criteria=(
                    ("Tax technical application to scenario", 8),
                    ("Computation / workings / allowances", 5),
                    ("Evaluation / recommendation", 4),
                    ("Structure / exam communication", 3),
                ),
            ),
        )

    def rag_source_hints(self) -> Sequence[RagSourceHint]:
        return (
            RagSourceHint(source_key="syllabus", tier="syllabus", priority=10, topic_tags=("all",)),
            RagSourceHint(source_key="course_notes", tier="notes", priority=30, topic_tags=("tax", "taxation")),
        )

    def build_rag_query_variants(
        self,
        *,
        topic_id: str,
        user_prompt: str,
        mode: str,
        weak_competencies: Sequence[str] = (),
    ) -> Sequence[str]:
        topic = str(topic_id or "").strip()
        prompt = str(user_prompt or "").strip()
        mode_text = str(mode or "").strip()
        variants: list[str] = []
        for candidate in (
            prompt,
            f"{topic} ACCA TX Taxation exam {mode_text}".strip(),
            f"{topic} tax computation allowances relief pitfalls".strip(),
            f"{topic} income tax corporation tax VAT worked example".strip(),
            (" ".join(str(x or "").strip() for x in weak_competencies if str(x or "").strip())[:180]).strip(),
        ):
            text = str(candidate or "").strip()
            if text and text not in variants:
                variants.append(text)
        return tuple(variants)

    def infer_transfer_structure(
        self,
        *,
        topic_id: str,
        question_type: str,
        tags: Sequence[str] = (),
        meta: dict[str, Any] | None = None,
    ) -> str | ProblemStructure | None:
        _ = (topic_id, question_type, tags, meta)
        return None


def _normalize_module_code_for_adapter(module_code: str) -> str:
    """Map app module_id (e.g. acca_f7) to adapter registry code (e.g. FR)."""
    raw = str(module_code or "").strip().upper().replace("-", "_")
    if raw in ("ACCA_F9", "F9", "FM"):
        return "FM"
    if raw in ("ACCA_F7", "F7", "FR"):
        return "FR"
    if raw in ("ACCA_F8", "F8", "AA"):
        return "AA"
    if raw in ("ACCA_F6", "F6", "TX"):
        return "TX"
    return raw


# ACCA syllabus-aligned scope for each module: in-scope calculations/concepts and out-of-scope.
# Used to constrain AI-generated questions and tutor responses to examinable content only.
ACCA_SYLLABUS_SCOPE_INSTRUCTIONS: dict[str, str] = {
    "FM": (
        "ACCA FM (Financial Management) syllabus scope — use ONLY these examinable methods: "
        "Total Shareholder Return TSR = (P₁ - P₀ + D₁) / P₀; Cost of equity Ke (Dividend Growth Model: Ke = D₁/P₀ + g); "
        "Weighted Average Cost of Capital (WACC); NPV and IRR for investment appraisal; "
        "two-stage and variable growth models for share valuation when dividends grow non-constantly. "
        "Do NOT use: equity multiple, MOIC, cash-on-cash return, or other private-equity-style multiples — they are not in the FM syllabus."
    ),
    "FR": (
        "ACCA FR (Financial Reporting) syllabus scope — use only IFRS/IAS standards and examinable content: "
        "conceptual framework, presentation (IFRS 18), revenue (IFRS 15), consolidation, associates, "
        "leases (IFRS 16), provisions (IAS 37), impairment (IAS 36), income taxes (IAS 12), EPS (IAS 33), "
        "cash flows (IAS 7), financial instruments. Do not introduce non-syllabus or non-examinable treatments."
    ),
    "AA": (
        "ACCA AA (Audit and Assurance) syllabus scope — use only examinable content: audit framework and regulation, "
        "planning and risk assessment, internal control, audit evidence, review and reporting. "
        "Stick to ISA and exam guide terminology and procedures."
    ),
    "TX": (
        "ACCA TX (Taxation) syllabus scope — use only examinable content for the chosen variant (e.g. UK): "
        "income tax and NIC, chargeable gains, corporation tax, VAT. Use only syllabus tax rules and rates."
    ),
}


def get_syllabus_scope_instruction(module_id: str) -> str:
    """Return ACCA syllabus-scope instruction for the given module (e.g. acca_f9, acca_f7)."""
    code = _normalize_module_code_for_adapter(module_id or "")
    return ACCA_SYLLABUS_SCOPE_INSTRUCTIONS.get(code, "")


def get_module_display_code(module_id: str) -> str:
    """Return a short display label for the module for tutor/coach context (e.g. 'ACCA FM', 'ACCA FR')."""
    code = _normalize_module_code_for_adapter(module_id or "")
    if not code:
        return ""
    labels: dict[str, str] = {
        "FM": "ACCA FM",
        "FR": "ACCA FR",
        "AA": "ACCA AA",
        "TX": "ACCA TX",
    }
    return labels.get(code, f"ACCA {code}")


def build_default_module_adapter_registry() -> ModuleAdapterRegistry:
    registry = ModuleAdapterRegistry()
    registry.register(FMModuleAdapter())
    registry.register(FRModuleAdapter())
    registry.register(AAModuleAdapter())
    registry.register(TXModuleAdapter())
    return registry


def resolve_module_adapter(
    module_code: str,
    *,
    registry: ModuleAdapterRegistry | None = None,
) -> ModuleAdapter:
    reg = registry if isinstance(registry, ModuleAdapterRegistry) else build_default_module_adapter_registry()
    adapter_code = _normalize_module_code_for_adapter(module_code)
    adapter = reg.get(adapter_code)
    if adapter is not None:
        return adapter
    code = str(module_code or "").strip().upper()
    if code:
        return NullModuleAdapter(
            ModuleDescriptor(
                module_code=code,
                module_title=code,
                domain_family="generic",
                supports_section_c=True,
                supports_judgment_modes=False,
            )
        )
    return NullModuleAdapter()


@dataclass
class DeterministicTransferVariantGenerator:
    """Rule-based isomorphic variant generation (stable across runs)."""

    rng: random.Random = field(default_factory=random.Random)

    DOMAIN_TEMPLATES: dict[StructureType, dict[str, str]] = field(
        default_factory=lambda: {
            StructureType.NPV_ANNUITY_TIMING: {
                "corporate": "equipment_replacement",
                "project": "infrastructure_build",
                "personal_finance": "retirement_annuity",
                "public_sector": "municipal_facility",
            },
            StructureType.WORKING_CAPITAL_CYCLE: {
                "corporate": "seasonal_inventory",
                "project": "contract_payments",
                "personal_finance": "freelance_cash",
                "public_sector": "grant_gaps",
            },
            StructureType.WACC_OPTIMIZATION: {
                "corporate": "capital_restructure",
                "project": "project_finance_mix",
                "personal_finance": "mortgage_refi",
                "public_sector": "bond_issuance",
            },
        }
    )
    ENTITY_ADJECTIVES: tuple[str, ...] = (
        "rapidly growing",
        "established",
        "family-owned",
        "listed",
        "distressed",
        "venture-backed",
    )
    PRESSURE_FACTORS: tuple[str, ...] = (
        "tight credit",
        "currency volatility",
        "supplier consolidation",
        "regulatory change",
        "competitive pressure",
    )
    DOMAINS: tuple[str, ...] = ("corporate", "project", "personal_finance", "public_sector")

    def _stable_seed(self, structure_id: str, seed_offset: int) -> int:
        digest = hashlib.sha1(f"{str(structure_id or '')}:{int(seed_offset)}".encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _excluded_domains(self, exclude_variants: Sequence[SurfaceVariant]) -> set[str]:
        out: set[str] = set()
        for variant in exclude_variants:
            try:
                domain = str((variant.metadata or {}).get("domain", "") or "").strip()
            except Exception:
                domain = ""
            if domain:
                out.add(domain)
        return out

    def generate(
        self,
        structure: ProblemStructure,
        *,
        exclude_variants: Sequence[SurfaceVariant] = (),
        seed_offset: int = 0,
    ) -> SurfaceVariant:
        excluded = self._excluded_domains(exclude_variants)
        available = [d for d in self.DOMAINS if d not in excluded]
        domain = str(available[0] if available else self.DOMAINS[int(seed_offset) % len(self.DOMAINS)])
        self.rng.seed(self._stable_seed(str(structure.structure_id or ""), int(seed_offset)))
        ranges: dict[str, tuple[Decimal, Decimal]] = {
            "personal_finance": (Decimal("5000"), Decimal("200000")),
            "corporate": (Decimal("50000"), Decimal("2000000")),
            "project": (Decimal("100000"), Decimal("5000000")),
            "public_sector": (Decimal("200000"), Decimal("10000000")),
        }
        numeric_range = ranges.get(domain, ranges["corporate"])
        return SurfaceVariant(
            variant_id=f"{str(structure.structure_id or '')}__{domain}__{int(seed_offset)}",
            base_structure_id=str(structure.structure_id or ""),
            domain=domain,  # type: ignore[arg-type]
            numeric_range=numeric_range,
            entity_type=str(self.rng.choice(self.ENTITY_ADJECTIVES)),
            context_seed=str(self.rng.choice(self.PRESSURE_FACTORS)),
            is_isomorphic=True,
            metadata={"domain": domain, "seed_offset": int(seed_offset)},
        )

    def generate_question_text(self, variant: SurfaceVariant, structure: ProblemStructure) -> str:
        template_key = self.DOMAIN_TEMPLATES.get(structure.structure_type, {}).get(
            str(variant.domain or ""), "business_scenario"
        )
        templates: dict[str, str] = {
            "equipment_replacement": (
                "A {entity} manufacturing firm faces a machinery replacement decision. "
                "New equipment costs {max_val:,.0f} and reduces operating costs. "
                "Given current {pressure}, evaluate the investment decision using NPV analysis."
            ),
            "seasonal_inventory": (
                "A {entity} retail business faces {pressure} affecting inventory turnover. "
                "Analyse working capital implications and recommend financing to optimise the cash conversion cycle."
            ),
            "capital_restructure": (
                "A {entity} firm is considering a debt/equity rebalance to minimise WACC. "
                "Current market conditions include {pressure}. Evaluate the optimal capital structure."
            ),
            "business_scenario": (
                "A {entity} organisation is making a finance decision under {pressure}. "
                "Apply the required technique and justify the recommendation."
            ),
        }
        template = templates.get(template_key, templates["business_scenario"])
        return template.format(
            entity=str(variant.entity_type or "business"),
            max_val=float(variant.numeric_range[1]),
            pressure=str(variant.context_seed or "market pressure"),
        )


@dataclass
class TransferScoringService:
    _attempts: dict[tuple[str, str], list[TransferAttempt]] = field(default_factory=dict)

    def record_attempt(self, attempt: TransferAttempt) -> TransferScore:
        key = (str(attempt.student_id or ""), str(attempt.structure_id or ""))
        rows = self._attempts.setdefault(key, [])
        rows.append(attempt)
        return TransferScore(student_id=key[0], structure_id=key[1], attempts=list(rows))

    def get_score(self, student_id: str, structure_id: str) -> TransferScore | None:
        key = (str(student_id or ""), str(structure_id or ""))
        rows = self._attempts.get(key)
        if not rows:
            return None
        return TransferScore(student_id=key[0], structure_id=key[1], attempts=list(rows))

    def get_brittle_concepts(
        self,
        student_id: str,
        threshold: float = 0.3,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        sid = str(student_id or "")
        out: list[dict[str, Any]] = []
        for (row_sid, structure_id), rows in self._attempts.items():
            if row_sid != sid:
                continue
            score = TransferScore(student_id=sid, structure_id=structure_id, attempts=list(rows))
            if float(score.brittleness_index) > float(threshold):
                out.append(score.to_insight_summary())
        out.sort(key=lambda row: float(row.get("brittleness_index", 0.0) or 0.0), reverse=True)
        return out[: max(1, int(limit))]


@dataclass
class TransferAttemptLogService:
    """JSONL persistence helper for transfer attempts (UI-agnostic)."""

    def _attempt_to_payload(self, attempt: TransferAttempt) -> dict[str, Any]:
        created_at = getattr(attempt, "created_at", None)
        created_text = ""
        try:
            if isinstance(created_at, datetime.datetime):
                created_text = created_at.isoformat()
        except Exception:
            created_text = ""
        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "attempt_id": str(getattr(attempt, "attempt_id", "") or ""),
            "student_id": str(getattr(attempt, "student_id", "") or ""),
            "base_question_id": str(getattr(attempt, "base_question_id", "") or ""),
            "variant_question_id": str(getattr(attempt, "variant_question_id", "") or ""),
            "structure_id": str(getattr(attempt, "structure_id", "") or ""),
            "base_result": str(getattr(attempt, "base_result", "") or ""),
            "variant_result": str(getattr(attempt, "variant_result", "") or ""),
            "base_latency_seconds": float(getattr(attempt, "base_latency_seconds", 0.0) or 0.0),
            "variant_latency_seconds": float(getattr(attempt, "variant_latency_seconds", 0.0) or 0.0),
            "base_hint_penalty": float(getattr(attempt, "base_hint_penalty", 1.0) or 1.0),
            "variant_hint_penalty": float(getattr(attempt, "variant_hint_penalty", 1.0) or 1.0),
            "created_at": created_text,
        }

    def _attempt_from_payload(self, payload: dict[str, Any]) -> TransferAttempt | None:
        if not isinstance(payload, dict):
            return None
        created_at_raw = str(payload.get("created_at", "") or payload.get("timestamp", "") or "").strip()
        created_at_dt: datetime.datetime | None = None
        if created_at_raw:
            try:
                created_at_dt = datetime.datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            except Exception:
                created_at_dt = None
        try:
            return TransferAttempt(
                attempt_id=str(payload.get("attempt_id", "") or ""),
                student_id=str(payload.get("student_id", "") or "local-user"),
                base_question_id=str(payload.get("base_question_id", "") or ""),
                variant_question_id=str(payload.get("variant_question_id", "") or ""),
                structure_id=str(payload.get("structure_id", "") or ""),
                base_result=str(payload.get("base_result", "incorrect") or "incorrect"),  # type: ignore[arg-type]
                variant_result=str(payload.get("variant_result", "incorrect") or "incorrect"),  # type: ignore[arg-type]
                base_latency_seconds=float(payload.get("base_latency_seconds", 0.0) or 0.0),
                variant_latency_seconds=float(payload.get("variant_latency_seconds", 0.0) or 0.0),
                base_hint_penalty=float(payload.get("base_hint_penalty", 1.0) or 1.0),
                variant_hint_penalty=float(payload.get("variant_hint_penalty", 1.0) or 1.0),
                created_at=created_at_dt if isinstance(created_at_dt, datetime.datetime) else datetime.datetime.now(datetime.timezone.utc),
            )
        except Exception:
            return None

    def append_attempt(self, file_path: str, attempt: TransferAttempt) -> bool:
        path = os.path.abspath(os.path.expanduser(str(file_path or "").strip()))
        if not path:
            return False
        line = json.dumps(self._attempt_to_payload(attempt), ensure_ascii=True, separators=(",", ":")) + "\n"
        parent = os.path.dirname(path) or "."
        try:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        except Exception:
            pass
        try:
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(fd, line.encode("utf-8", "replace"))
                try:
                    os.fsync(fd)
                except Exception:
                    pass
            finally:
                os.close(fd)
            return True
        except Exception:
            try:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(line)
                return True
            except Exception:
                return False

    def load_recent_attempts(self, file_path: str, *, max_rows: int = 600) -> tuple[TransferAttempt, ...]:
        path = os.path.abspath(os.path.expanduser(str(file_path or "").strip()))
        if not path or not os.path.isfile(path):
            return ()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw_text = str(handle.read() or "")
        except Exception:
            return ()
        if not raw_text:
            return ()
        try:
            row_cap = max(1, min(5000, int(max_rows)))
        except Exception:
            row_cap = 600
        lines = [str(line or "").strip() for line in raw_text.splitlines() if str(line or "").strip()]
        out: list[TransferAttempt] = []
        for line in lines[-row_cap:]:
            try:
                payload = json.loads(line)
            except Exception:
                continue
            attempt = self._attempt_from_payload(payload)
            if attempt is not None:
                out.append(attempt)
        return tuple(out)


@dataclass
class StructureRegistry:
    _structures: dict[str, ProblemStructure] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self._structures:
            self._init_default_structures()

    def _init_default_structures(self) -> None:
        self._structures["npv_annuity_timing_v1"] = ProblemStructure(
            structure_id="npv_annuity_timing_v1",
            structure_type=StructureType.NPV_ANNUITY_TIMING,
            required_operations=("discount", "annuity_factor", "compare_alternatives"),
            misconception_exposure_class="time_value_timing",
            boundary_conditions=("inflation_adjustment", "tax_shield_timing"),
            related_confusion_concept_ids=("discount_rate", "annuity_factor"),
        )
        self._structures["wacc_optimization_v1"] = ProblemStructure(
            structure_id="wacc_optimization_v1",
            structure_type=StructureType.WACC_OPTIMIZATION,
            required_operations=("component_cost", "weighting", "minimize_wacc"),
            misconception_exposure_class="capital_structure_weights",
            related_confusion_concept_ids=("cost_of_debt", "cost_of_equity"),
        )
        self._structures["working_capital_cycle_v1"] = ProblemStructure(
            structure_id="working_capital_cycle_v1",
            structure_type=StructureType.WORKING_CAPITAL_CYCLE,
            required_operations=("cycle_calculation", "financing_gap", "recommend_policy"),
            misconception_exposure_class="working_capital_components",
        )

    def get(self, structure_id: str) -> ProblemStructure | None:
        return self._structures.get(str(structure_id or ""))

    def all_structure_ids(self) -> list[str]:
        return list(self._structures.keys())

    def infer_from_topic_and_item(
        self,
        *,
        topic_id: str,
        question_type: str = "",
        tags: Sequence[str] = (),
    ) -> ProblemStructure | None:
        topic = str(topic_id or "").strip().lower()
        _ = str(question_type or "").strip().lower()
        tag_set = {str(tag or "").strip().lower() for tag in tags if str(tag or "").strip()}
        if ("npv" in tag_set) or ("annuity" in tag_set) or ("investment appraisal" in topic):
            return self._structures.get("npv_annuity_timing_v1")
        if ("wacc" in tag_set) or ("cost_of_capital" in tag_set) or ("cost of capital" in topic):
            return self._structures.get("wacc_optimization_v1")
        if ("working_capital" in tag_set) or ("working capital" in topic) or ("cash management" in topic):
            return self._structures.get("working_capital_cycle_v1")
        return None


@dataclass
class RuleBasedRagEvidencePolicyService:
    """Deterministic prompt-policy classifier for current Tutor RAG evidence quality."""

    strong_threshold: float = 0.72
    mixed_threshold: float = 0.45

    def evaluate(
        self,
        *,
        rag_meta: dict[str, Any] | None,
        user_prompt: str = "",
        current_topic: str = "",
    ) -> dict[str, object]:
        meta = dict(rag_meta or {})
        method = str(meta.get("method", "disabled") or "disabled").strip().lower()
        raw_errors = meta.get("errors", [])
        errors = [str(item or "").strip() for item in list(raw_errors or []) if str(item or "").strip()]

        def _as_int(value: Any, default: int = 0) -> int:
            try:
                return int(value)
            except Exception:
                return int(default)

        snippet_count = max(0, _as_int(meta.get("snippet_count", 0)))
        source_count = max(0, _as_int(meta.get("source_count", 0)))
        target_query_count = max(0, _as_int(meta.get("target_query_count", 0)))
        target_hit_snippets = max(0, _as_int(meta.get("target_hit_snippets", 0)))
        source_mix = str(meta.get("rag_source_mix", "") or "").strip()
        if not source_mix:
            try:
                source_rows = [str(item or "").strip() for item in list(meta.get("sources", []) or []) if str(item or "").strip()]
            except Exception:
                source_rows = []
            source_mix = ", ".join(sorted(set(source_rows))) if source_rows else "none"

        base_by_method = {
            "disabled": 0.0,
            "empty": 0.08,
            "empty_query": 0.08,
            "error": 0.10,
            "lexical": 0.56,
            "semantic": 0.68,
            "hybrid": 0.72,
        }
        confidence = float(base_by_method.get(method, 0.50))
        confidence += min(0.20, float(snippet_count) * 0.03)
        confidence += min(0.08, float(source_count) * 0.02)
        if target_query_count > 0:
            target_ratio = min(1.0, float(target_hit_snippets) / float(max(1, target_query_count)))
            confidence += 0.14 * target_ratio
        elif snippet_count > 0:
            confidence += 0.05
        if errors:
            confidence -= min(0.25, 0.12 + (0.06 * float(len(errors))))
        if method in {"disabled", "error", "empty", "empty_query"} and snippet_count <= 0:
            confidence = min(confidence, 0.35)
        confidence = max(0.0, min(1.0, confidence))

        insufficient = bool(
            (method not in {"disabled"} and snippet_count <= 0)
            or (target_query_count > 0 and target_hit_snippets <= 0)
        )
        if method == "disabled":
            policy_mode = "disabled"
        elif insufficient or confidence < float(self.mixed_threshold):
            policy_mode = "weak_grounding"
        elif confidence >= float(self.strong_threshold):
            policy_mode = "strong_grounding"
        else:
            policy_mode = "mixed_grounding"

        prompt_text = str(user_prompt or "").strip().lower()
        topic_text = str(current_topic or "").strip()
        standard_sensitive = bool(
            topic_text
            and any(token in prompt_text for token in ("ifrs", "ias", "standard", "rule", "examiner", "syllabus"))
        )

        if policy_mode == "strong_grounding":
            planner_line = "- RAG evidence strong: use snippets for precise rules/formulas, then explain in exam-focused terms."
            certainty_style = "grounded"
        elif policy_mode == "mixed_grounding":
            planner_line = (
                "- RAG evidence mixed: anchor key claims to snippets when relevant; fill gaps with model knowledge and state assumptions."
            )
            certainty_style = "balanced"
        elif policy_mode == "disabled":
            planner_line = (
                "- RAG evidence unavailable: answer with model knowledge and clearly state assumptions for syllabus-specific claims."
            )
            certainty_style = "assumption_first"
        else:
            planner_line = (
                "- RAG evidence weak: avoid overclaiming; answer with model knowledge, flag assumptions, and prioritize robust principles."
            )
            certainty_style = "hedged"
        if standard_sensitive and policy_mode in {"weak_grounding", "disabled"}:
            planner_line += " Note uncertainty for standard-specific details."

        return {
            "policy_mode": policy_mode,
            "confidence_score": round(float(confidence), 4),
            "insufficient": bool(insufficient),
            "certainty_style": certainty_style,
            "planner_brief_line": planner_line,
            "method": method,
            "snippet_count": int(snippet_count),
            "target_query_count": int(target_query_count),
            "target_hit_snippets": int(target_hit_snippets),
            "source_mix": source_mix or "none",
            "error_count": int(len(errors)),
        }


@dataclass
class DeterministicTutorStrugglePolicyService:
    """Token-bucket hint policy for productive struggle in Tutor practice loops."""

    refill_seconds: float = 30.0
    min_spacing_seconds: float = 4.0
    pre_attempt_tokens_if_struggling: int = 1
    pre_attempt_capacity_if_struggling: int = 1
    post_attempt_capacity: int = 2

    def evaluate_hint_access(
        self,
        *,
        item_id: str,
        state: dict[str, Any] | None,
        has_assessment: bool,
        cognitive_runtime: dict[str, Any] | None = None,
        now_monotonic: float | None = None,
    ) -> tuple[dict[str, object], dict[str, Any]]:
        now = float(now_monotonic if isinstance(now_monotonic, (int, float)) else 0.0)
        if now <= 0.0:
            try:
                import time as _time

                now = float(_time.monotonic())
            except Exception:
                now = 0.0
        item_key = str(item_id or "").strip() or "practice-item"
        cog = dict(cognitive_runtime or {})
        struggle_mode = bool(cog.get("struggle_mode", False))
        quiz_active = bool(cog.get("quiz_active", False))

        normalized = self._normalize_state(
            state=state,
            item_id=item_key,
            has_assessment=bool(has_assessment),
            struggle_mode=struggle_mode,
            now_monotonic=now,
        )
        normalized = self._refill_tokens(normalized, now)
        normalized = self._upgrade_after_assessment(normalized, has_assessment=bool(has_assessment))

        last_hint_at = float(normalized.get("last_hint_at", 0.0) or 0.0)
        if last_hint_at > 0.0 and now > 0.0:
            remaining = float(self.min_spacing_seconds) - max(0.0, now - last_hint_at)
            if remaining > 0.0:
                return (
                    {
                        "allow": False,
                        "reason": "cooldown",
                        "status": f"Hint cooling down ({remaining:.0f}s).",
                        "tokens_remaining": int(normalized.get("tokens", 0) or 0),
                        "capacity": int(normalized.get("capacity", 0) or 0),
                    },
                    normalized,
                )

        if (not has_assessment) and (not struggle_mode):
            return (
                {
                    "allow": False,
                    "reason": "attempt_first",
                    "status": "Hint held briefly: take one attempt first so the tutor can tailor the hint to your exact mistake.",
                    "tokens_remaining": int(normalized.get("tokens", 0) or 0),
                    "capacity": int(normalized.get("capacity", 0) or 0),
                },
                normalized,
            )

        tokens = int(normalized.get("tokens", 0) or 0)
        if tokens <= 0:
            return (
                {
                    "allow": False,
                    "reason": "budget_exhausted",
                    "status": "Hint budget spent for this step. Try another attempt or wait for refill.",
                    "tokens_remaining": 0,
                    "capacity": int(normalized.get("capacity", 0) or 0),
                },
                normalized,
            )

        normalized["tokens"] = max(0, tokens - 1)
        normalized["last_hint_at"] = float(now)
        reason = "struggle_priority" if struggle_mode and not has_assessment else "allowed"
        if quiz_active and not has_assessment:
            reason = "quiz_active_safe_hint"
        return (
            {
                "allow": True,
                "reason": reason,
                "status": "Hint granted.",
                "tokens_remaining": int(normalized.get("tokens", 0) or 0),
                "capacity": int(normalized.get("capacity", 0) or 0),
            },
            normalized,
        )

    def _normalize_state(
        self,
        *,
        state: dict[str, Any] | None,
        item_id: str,
        has_assessment: bool,
        struggle_mode: bool,
        now_monotonic: float,
    ) -> dict[str, Any]:
        raw = dict(state or {})
        old_item = str(raw.get("item_id", "") or "").strip()
        item_changed = old_item != item_id
        if item_changed:
            raw = {}
        try:
            refill_anchor = float(raw.get("last_refill_at", now_monotonic) or now_monotonic)
        except Exception:
            refill_anchor = float(now_monotonic)
        try:
            last_hint_at = float(raw.get("last_hint_at", 0.0) or 0.0)
        except Exception:
            last_hint_at = 0.0
        try:
            tokens = int(raw.get("tokens", 0) or 0)
        except Exception:
            tokens = 0
        try:
            capacity = int(raw.get("capacity", 0) or 0)
        except Exception:
            capacity = 0
        post_bonus = bool(raw.get("post_assessment_bonus_granted", False))

        if item_changed:
            if struggle_mode:
                capacity = max(1, int(self.pre_attempt_capacity_if_struggling))
                tokens = max(0, min(capacity, int(self.pre_attempt_tokens_if_struggling)))
            elif has_assessment:
                capacity = max(1, int(self.post_attempt_capacity))
                tokens = 0
                post_bonus = False
            else:
                capacity = max(1, int(self.post_attempt_capacity))
                tokens = 0
                post_bonus = False
            last_hint_at = 0.0
            refill_anchor = float(now_monotonic)

        return {
            "item_id": item_id,
            "tokens": max(0, tokens),
            "capacity": max(1, capacity),
            "last_refill_at": float(refill_anchor),
            "last_hint_at": float(max(0.0, last_hint_at)),
            "post_assessment_bonus_granted": bool(post_bonus),
        }

    def _refill_tokens(self, state: dict[str, Any], now_monotonic: float) -> dict[str, Any]:
        out = dict(state)
        refill_seconds = max(5.0, float(self.refill_seconds))
        if now_monotonic <= 0.0:
            return out
        last_refill = float(out.get("last_refill_at", now_monotonic) or now_monotonic)
        elapsed = max(0.0, float(now_monotonic) - last_refill)
        if elapsed < refill_seconds:
            return out
        add_tokens = int(elapsed // refill_seconds)
        if add_tokens <= 0:
            return out
        capacity = max(1, int(out.get("capacity", 1) or 1))
        tokens = max(0, int(out.get("tokens", 0) or 0))
        out["tokens"] = min(capacity, tokens + add_tokens)
        out["last_refill_at"] = float(last_refill + (add_tokens * refill_seconds))
        return out

    def _upgrade_after_assessment(self, state: dict[str, Any], *, has_assessment: bool) -> dict[str, Any]:
        out = dict(state)
        if not bool(has_assessment):
            return out
        capacity = max(1, int(out.get("capacity", 1) or 1))
        target_capacity = max(capacity, int(self.post_attempt_capacity))
        out["capacity"] = target_capacity
        bonus_granted = bool(out.get("post_assessment_bonus_granted", False))
        if not bonus_granted:
            tokens = max(0, int(out.get("tokens", 0) or 0))
            out["tokens"] = max(tokens, target_capacity)
            out["post_assessment_bonus_granted"] = True
        return out


@dataclass(frozen=True)
class TutorLoopPolicyThresholds:
    min_assessments_for_metrics: int = 4
    error_incorrect_rate_threshold: float = 0.50
    retrieval_correct_rate_threshold: float = 0.72
    retrieval_min_streak: int = 2
    retrieval_score_ema_min: float = 0.55
    calibration_bias_guard: float = 1.40
    review_pressure_guard_total: int = 8

    def clamped(self) -> "TutorLoopPolicyThresholds":
        return TutorLoopPolicyThresholds(
            min_assessments_for_metrics=max(1, min(32, int(self.min_assessments_for_metrics))),
            error_incorrect_rate_threshold=max(0.20, min(0.90, float(self.error_incorrect_rate_threshold))),
            retrieval_correct_rate_threshold=max(0.40, min(0.95, float(self.retrieval_correct_rate_threshold))),
            retrieval_min_streak=max(1, min(8, int(self.retrieval_min_streak))),
            retrieval_score_ema_min=max(0.30, min(0.95, float(self.retrieval_score_ema_min))),
            calibration_bias_guard=max(0.40, min(3.50, float(self.calibration_bias_guard))),
            review_pressure_guard_total=max(2, min(40, int(self.review_pressure_guard_total))),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "min_assessments_for_metrics": int(self.min_assessments_for_metrics),
            "error_incorrect_rate_threshold": round(float(self.error_incorrect_rate_threshold), 4),
            "retrieval_correct_rate_threshold": round(float(self.retrieval_correct_rate_threshold), 4),
            "retrieval_min_streak": int(self.retrieval_min_streak),
            "retrieval_score_ema_min": round(float(self.retrieval_score_ema_min), 4),
            "calibration_bias_guard": round(float(self.calibration_bias_guard), 4),
            "review_pressure_guard_total": int(self.review_pressure_guard_total),
        }


@dataclass
class DeterministicTutorPolicyTuningService:
    """Deterministic threshold tuning from observed learning-loop outcomes."""

    def tune(
        self,
        *,
        base_thresholds: TutorLoopPolicyThresholds,
        loop_metrics: dict[str, Any],
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> tuple[TutorLoopPolicyThresholds, dict[str, object]]:
        base = base_thresholds.clamped()
        total = max(0, int(loop_metrics.get("assessments_total", 0) or 0))
        if total <= 0:
            return base, {"status": "insufficient_data", "reason": "no_assessments"}

        incorrect = max(0, int(loop_metrics.get("incorrect_count", 0) or 0))
        recurrence = max(0, int(loop_metrics.get("misconception_recurrence_count", 0) or 0))
        streak_ok = max(0, int(loop_metrics.get("consecutive_correct", 0) or 0))
        streak_bad = max(0, int(loop_metrics.get("consecutive_incorrect", 0) or 0))
        accuracy_like = max(0.0, min(1.0, float(loop_metrics.get("accuracy_like", 0.0) or 0.0)))
        score_ema = max(0.0, min(1.0, float(loop_metrics.get("avg_score_ratio_ema", 0.0) or 0.0)))
        bias_abs = max(0.0, min(5.0, float(loop_metrics.get("confidence_bias_abs_ema", 0.0) or 0.0)))
        incorrect_rate = float(incorrect) / float(max(1, total))
        review_pressure = max(0, int(getattr(app_snapshot, "must_review_due", 0) or 0)) + max(
            0,
            int(getattr(app_snapshot, "overdue_srs_count", 0) or 0),
        )
        transfer = float(getattr(learner_profile, "chat_to_quiz_transfer_score", 0.0) or 0.0)

        tuned = base
        reason = "stable"
        severity = "neutral"

        if total < int(base.min_assessments_for_metrics):
            # Require more observations before trusting automatic mode shifts.
            tuned = TutorLoopPolicyThresholds(
                **{
                    **base.to_dict(),
                    "min_assessments_for_metrics": min(12, max(int(base.min_assessments_for_metrics), total + 1)),
                }
            ).clamped()
            reason = "warmup_more_data"
            severity = "conservative"
        elif (
            recurrence >= 3
            or streak_bad >= 2
            or incorrect_rate >= max(0.45, float(base.error_incorrect_rate_threshold))
            or score_ema < 0.45
        ):
            tuned = TutorLoopPolicyThresholds(
                min_assessments_for_metrics=base.min_assessments_for_metrics,
                error_incorrect_rate_threshold=max(0.35, base.error_incorrect_rate_threshold - 0.08),
                retrieval_correct_rate_threshold=min(0.90, base.retrieval_correct_rate_threshold + 0.06),
                retrieval_min_streak=min(6, base.retrieval_min_streak + 1),
                retrieval_score_ema_min=min(0.85, base.retrieval_score_ema_min + 0.06),
                calibration_bias_guard=max(0.8, base.calibration_bias_guard - 0.15),
                review_pressure_guard_total=base.review_pressure_guard_total,
            ).clamped()
            reason = "error_pressure"
            severity = "conservative"
        elif (
            recurrence == 0
            and streak_ok >= max(2, base.retrieval_min_streak)
            and accuracy_like >= 0.82
            and score_ema >= 0.72
            and transfer >= -0.05
        ):
            tuned = TutorLoopPolicyThresholds(
                min_assessments_for_metrics=base.min_assessments_for_metrics,
                error_incorrect_rate_threshold=min(0.70, base.error_incorrect_rate_threshold + 0.03),
                retrieval_correct_rate_threshold=max(0.60, base.retrieval_correct_rate_threshold - 0.04),
                retrieval_min_streak=max(1, base.retrieval_min_streak),
                retrieval_score_ema_min=max(0.45, base.retrieval_score_ema_min - 0.03),
                calibration_bias_guard=min(2.2, base.calibration_bias_guard + 0.12),
                review_pressure_guard_total=base.review_pressure_guard_total,
            ).clamped()
            reason = "progress_ready"
            severity = "aggressive"
        elif bias_abs >= 1.6:
            tuned = TutorLoopPolicyThresholds(
                min_assessments_for_metrics=base.min_assessments_for_metrics,
                error_incorrect_rate_threshold=base.error_incorrect_rate_threshold,
                retrieval_correct_rate_threshold=min(0.88, base.retrieval_correct_rate_threshold + 0.03),
                retrieval_min_streak=base.retrieval_min_streak,
                retrieval_score_ema_min=base.retrieval_score_ema_min,
                calibration_bias_guard=max(0.8, base.calibration_bias_guard - 0.20),
                review_pressure_guard_total=base.review_pressure_guard_total,
            ).clamped()
            reason = "calibration_guard"
            severity = "conservative"

        if review_pressure >= int(base.review_pressure_guard_total):
            tuned = TutorLoopPolicyThresholds(
                **{
                    **tuned.to_dict(),
                    "review_pressure_guard_total": max(2, min(int(tuned.review_pressure_guard_total), review_pressure)),
                }
            ).clamped()
            if reason == "stable":
                reason = "review_pressure_guard"
            severity = "conservative"

        meta: dict[str, object] = {
            "status": "tuned" if tuned != base else "stable",
            "reason": reason,
            "severity": severity,
            "assessments_total": int(total),
            "incorrect_rate": round(max(0.0, min(1.0, incorrect_rate)), 4),
            "accuracy_like": round(accuracy_like, 4),
            "score_ema": round(score_ema, 4),
            "recurrence": int(recurrence),
            "streak_ok": int(streak_ok),
            "streak_bad": int(streak_bad),
            "confidence_bias_abs_ema": round(bias_abs, 4),
            "review_pressure_total": int(review_pressure),
            "transfer_score": round(max(-1.0, min(1.0, transfer)), 4),
        }
        return tuned, meta


@dataclass
class InMemoryTutorSessionController:
    """Phase 1 session-state store/controller used by the Tutor learning loop."""

    _sessions: dict[str, TutorSessionState] = field(default_factory=dict)

    def _now_ts(self) -> str:
        try:
            return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            return ""

    def get_or_create_session(
        self,
        *,
        session_id: str,
        module: str,
        topic: str,
    ) -> TutorSessionState:
        key = str(session_id or "").strip()
        if not key:
            key = "default"
        existing = self._sessions.get(key)
        if isinstance(existing, TutorSessionState):
            new_topic = str(topic or "").strip()
            new_module = str(module or "").strip()
            updated = existing
            changed = False
            if new_topic and new_topic != str(existing.topic or "").strip():
                updated = replace(updated, topic=new_topic, updated_at_ts=self._now_ts())
                changed = True
            if new_module and new_module != str(existing.module or "").strip():
                updated = replace(updated, module=new_module, updated_at_ts=self._now_ts())
                changed = True
            if changed:
                self._sessions[key] = updated
                return updated
            return existing
        state = TutorSessionState(
            session_id=key,
            module=str(module or "").strip(),
            topic=str(topic or "").strip(),
            mode="auto",
            loop_phase="observe",
            updated_at_ts=self._now_ts(),
        )
        self._sessions[key] = state
        return state

    def save_session(self, state: TutorSessionState) -> TutorSessionState:
        session_id = str(getattr(state, "session_id", "") or "").strip() or "default"
        updated = replace(state, session_id=session_id, updated_at_ts=self._now_ts())
        self._sessions[session_id] = updated
        return updated

    def reset_session(self, session_id: str) -> None:
        key = str(session_id or "").strip()
        if not key:
            key = "default"
        self._sessions.pop(key, None)

    def start_or_resume_session(
        self,
        *,
        session_id: str,
        module: str,
        topic: str,
        mode: str = "auto",
        session_objective: str = "",
        success_criteria: str = "",
        target_concepts: tuple[str, ...] = (),
    ) -> TutorSessionState:
        state = self.get_or_create_session(session_id=session_id, module=module, topic=topic)
        normalized_targets = tuple(str(x or "").strip() for x in target_concepts if str(x or "").strip())
        updated = replace(
            state,
            module=str(module or state.module or "").strip(),
            topic=str(topic or state.topic or "").strip(),
            mode=str(mode or state.mode or "auto"),
            loop_phase="observe" if not bool(state.active) else str(state.loop_phase or "observe"),
            session_objective=str(session_objective or state.session_objective or ""),
            success_criteria=str(success_criteria or state.success_criteria or ""),
            target_concepts=normalized_targets or state.target_concepts,
            active=True,
            updated_at_ts=self._now_ts(),
        )
        self._sessions[updated.session_id] = updated
        return updated

    def advance_phase(self, session_id: str, phase: str) -> TutorSessionState:
        state = self.get_or_create_session(session_id=session_id, module="", topic="")
        updated = replace(
            state,
            loop_phase=str(phase or state.loop_phase or "observe"),
            updated_at_ts=self._now_ts(),
        )
        self._sessions[updated.session_id] = updated
        return updated

    def record_assessment_outcome(
        self,
        session_id: str,
        *,
        outcome: str,
        practice_item_id: str = "",
        increment_streak: bool = False,
    ) -> TutorSessionState:
        state = self.get_or_create_session(session_id=session_id, module="", topic="")
        outcome_text = str(outcome or "").strip().lower()
        is_success = outcome_text in {"correct", "partial"} if increment_streak else False
        new_streak = int(state.practice_streak or 0)
        if increment_streak:
            new_streak = max(0, new_streak + 1) if is_success else 0
        recent_failures = int(state.recent_failures or 0)
        if outcome_text == "incorrect":
            recent_failures = min(10_000, recent_failures + 1)
        elif outcome_text in {"correct", "partial"}:
            recent_failures = max(0, recent_failures - 1)
        updated = replace(
            state,
            loop_phase="reinforce" if outcome_text in {"correct", "partial"} else "teach",
            active_practice_item_id=str(practice_item_id or state.active_practice_item_id or ""),
            practice_streak=new_streak,
            recent_failures=recent_failures,
            last_assessment_outcome=outcome_text,
            updated_at_ts=self._now_ts(),
        )
        self._sessions[updated.session_id] = updated
        return updated


@dataclass
class InMemoryTutorLearnerModelStore:
    """Phase 1 learner-profile store with simple deterministic updates from assessment results."""

    _profiles: dict[tuple[str, str], TutorLearnerProfileSnapshot] = field(default_factory=dict)
    max_tags: int = 8

    def _now_ts(self) -> str:
        try:
            return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            return ""

    def _key(self, learner_id: str, module: str) -> tuple[str, str]:
        return (str(learner_id or "").strip() or "default", str(module or "").strip())

    def get_or_create_profile(self, learner_id: str, module: str) -> TutorLearnerProfileSnapshot:
        key = self._key(learner_id, module)
        existing = self._profiles.get(key)
        if isinstance(existing, TutorLearnerProfileSnapshot):
            return existing
        profile = TutorLearnerProfileSnapshot(
            learner_id=key[0],
            module=key[1],
            last_updated_ts=self._now_ts(),
        )
        self._profiles[key] = profile
        return profile

    def save_profile(self, profile: TutorLearnerProfileSnapshot) -> TutorLearnerProfileSnapshot:
        key = self._key(profile.learner_id, profile.module)
        updated = replace(profile, learner_id=key[0], module=key[1], last_updated_ts=self._now_ts())
        self._profiles[key] = updated
        return updated

    def note_assessment(
        self,
        learner_id: str,
        module: str,
        assessment: TutorAssessmentResult,
        *,
        confidence: int | None = None,
    ) -> TutorLearnerProfileSnapshot:
        profile = self.get_or_create_profile(learner_id, module)
        prior_mis_tags = tuple(getattr(profile, "misconception_tags_top", ()) or ())
        misconception_tags = self._merge_tags(profile.misconception_tags_top, assessment.misconception_tags)
        weak_caps = self._merge_tags(profile.weak_capabilities_top, assessment.error_tags)
        outcome = str(getattr(assessment, "outcome", "") or "").strip().lower()
        marks_awarded = float(getattr(assessment, "marks_awarded", 0.0) or 0.0)
        marks_max = max(0.0, float(getattr(assessment, "marks_max", 0.0) or 0.0))
        score_ratio = (marks_awarded / marks_max) if marks_max > 0 else (1.0 if outcome == "correct" else 0.0)

        prior_transfer = float(getattr(profile, "chat_to_quiz_transfer_score", 0.0) or 0.0)
        blended_transfer = (0.8 * prior_transfer) + (0.2 * ((score_ratio * 2.0) - 1.0))
        blended_transfer = max(-1.0, min(1.0, blended_transfer))

        bias = float(getattr(profile, "confidence_calibration_bias", 0.0) or 0.0)
        if confidence is not None:
            conf_scaled = max(1, min(5, int(confidence))) / 5.0
            correctness_scaled = max(0.0, min(1.0, score_ratio))
            bias = max(-5.0, min(5.0, (0.8 * bias) + (0.2 * ((conf_scaled - correctness_scaled) * 5.0))))

        speed_tier = str(getattr(profile, "response_speed_tier", "unknown") or "unknown")
        loop_metrics = self._update_learning_loop_metrics(
            profile=profile,
            assessment=assessment,
            score_ratio=score_ratio,
            outcome=outcome,
            confidence=confidence,
            prior_misconception_tags=prior_mis_tags,
        )
        profile_meta = dict(getattr(profile, "meta", {}) or {})
        profile_meta["learning_loop_metrics"] = loop_metrics
        updated = replace(
            profile,
            misconception_tags_top=misconception_tags,
            weak_capabilities_top=weak_caps,
            confidence_calibration_bias=bias,
            chat_to_quiz_transfer_score=blended_transfer,
            last_practice_outcome=outcome,
            response_speed_tier=speed_tier,
            last_updated_ts=self._now_ts(),
            meta=profile_meta,
        )
        self._profiles[self._key(learner_id, module)] = updated
        return updated

    def _learning_loop_metrics_from_meta(self, meta: dict[str, Any]) -> dict[str, Any]:
        raw = meta.get("learning_loop_metrics", {}) if isinstance(meta, dict) else {}
        data = raw if isinstance(raw, dict) else {}

        def _intv(key: str, default: int = 0, maxv: int = 1_000_000) -> int:
            try:
                val = int(data.get(key, default) or default)
            except Exception:
                val = int(default)
            return max(0, min(int(maxv), val))

        def _floatv(key: str, default: float = 0.0, minv: float = -10.0, maxv: float = 10.0) -> float:
            try:
                val = float(data.get(key, default) or default)
            except Exception:
                val = float(default)
            return max(float(minv), min(float(maxv), val))

        recent_outcomes = tuple(
            str(x or "").strip().lower()
            for x in list(data.get("recent_outcomes", []) or [])
            if str(x or "").strip()
        )[:8]
        recent_mis = tuple(
            str(x or "").strip()
            for x in list(data.get("recent_misconceptions", []) or [])
            if str(x or "").strip()
        )[:8]
        return {
            "schema_version": 1,
            "assessments_total": _intv("assessments_total"),
            "correct_count": _intv("correct_count"),
            "partial_count": _intv("partial_count"),
            "incorrect_count": _intv("incorrect_count"),
            "consecutive_correct": _intv("consecutive_correct"),
            "consecutive_incorrect": _intv("consecutive_incorrect"),
            "misconception_recurrence_count": _intv("misconception_recurrence_count"),
            "avg_score_ratio_ema": _floatv("avg_score_ratio_ema", 0.0, 0.0, 1.0),
            "confidence_samples": _intv("confidence_samples"),
            "confidence_bias_abs_ema": _floatv("confidence_bias_abs_ema", 0.0, 0.0, 5.0),
            "recent_outcomes": list(recent_outcomes),
            "recent_misconceptions": list(recent_mis),
            "last_outcome": str(data.get("last_outcome", "") or "").strip().lower()[:24],
        }

    def _update_learning_loop_metrics(
        self,
        *,
        profile: TutorLearnerProfileSnapshot,
        assessment: TutorAssessmentResult,
        score_ratio: float,
        outcome: str,
        confidence: int | None,
        prior_misconception_tags: tuple[str, ...],
    ) -> dict[str, Any]:
        metrics = self._learning_loop_metrics_from_meta(dict(getattr(profile, "meta", {}) or {}))
        metrics["assessments_total"] = int(metrics.get("assessments_total", 0) or 0) + 1
        if outcome == "correct":
            metrics["correct_count"] = int(metrics.get("correct_count", 0) or 0) + 1
            metrics["consecutive_correct"] = int(metrics.get("consecutive_correct", 0) or 0) + 1
            metrics["consecutive_incorrect"] = 0
        elif outcome == "partial":
            metrics["partial_count"] = int(metrics.get("partial_count", 0) or 0) + 1
            metrics["consecutive_correct"] = int(metrics.get("consecutive_correct", 0) or 0) + 1
            metrics["consecutive_incorrect"] = 0
        else:
            metrics["incorrect_count"] = int(metrics.get("incorrect_count", 0) or 0) + 1
            metrics["consecutive_incorrect"] = int(metrics.get("consecutive_incorrect", 0) or 0) + 1
            metrics["consecutive_correct"] = 0

        prev_ema = float(metrics.get("avg_score_ratio_ema", 0.0) or 0.0)
        if int(metrics.get("assessments_total", 0) or 0) <= 1:
            score_ema = max(0.0, min(1.0, float(score_ratio)))
        else:
            score_ema = (0.8 * prev_ema) + (0.2 * max(0.0, min(1.0, float(score_ratio))))
        metrics["avg_score_ratio_ema"] = round(max(0.0, min(1.0, score_ema)), 4)

        current_mis = tuple(str(x or "").strip() for x in tuple(getattr(assessment, "misconception_tags", ()) or ()) if str(x or "").strip())
        prior_set = {str(x or "").strip().lower() for x in prior_misconception_tags if str(x or "").strip()}
        recent_mis = [
            str(x or "").strip()
            for x in list(metrics.get("recent_misconceptions", []) or [])
            if str(x or "").strip()
        ]
        recurrence_hit = False
        for tag in current_mis:
            key = tag.lower()
            if key in prior_set or any(key == str(item).lower() for item in recent_mis):
                recurrence_hit = True
            if not any(key == str(item).lower() for item in recent_mis):
                recent_mis.append(tag)
        if recurrence_hit:
            metrics["misconception_recurrence_count"] = int(metrics.get("misconception_recurrence_count", 0) or 0) + 1
        metrics["recent_misconceptions"] = recent_mis[-8:]

        recent_outcomes = [
            str(x or "").strip().lower()
            for x in list(metrics.get("recent_outcomes", []) or [])
            if str(x or "").strip()
        ]
        if outcome:
            recent_outcomes.append(outcome)
        metrics["recent_outcomes"] = recent_outcomes[-8:]
        metrics["last_outcome"] = str(outcome or "").strip().lower()[:24]

        if confidence is not None:
            try:
                conf = max(1, min(5, int(confidence)))
            except Exception:
                conf = 3
            correctness_scaled = max(0.0, min(1.0, float(score_ratio)))
            abs_delta = abs((float(conf) / 5.0) - correctness_scaled) * 5.0
            prev_bias_abs_ema = float(metrics.get("confidence_bias_abs_ema", 0.0) or 0.0)
            if int(metrics.get("confidence_samples", 0) or 0) <= 0:
                bias_abs_ema = abs_delta
            else:
                bias_abs_ema = (0.8 * prev_bias_abs_ema) + (0.2 * abs_delta)
            metrics["confidence_bias_abs_ema"] = round(max(0.0, min(5.0, bias_abs_ema)), 4)
            metrics["confidence_samples"] = int(metrics.get("confidence_samples", 0) or 0) + 1
        return metrics

    def _merge_tags(self, existing: tuple[str, ...], new_tags: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for seq in (existing, new_tags):
            for item in seq:
                text = str(item or "").strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(text)
                if len(out) >= int(max(1, self.max_tags)):
                    return tuple(out)
        return tuple(out)


from functools import lru_cache
from .components.performance.caching import PerformanceCacheService, create_performance_cache_service
from .components.performance.optimization import PerformanceMiddleware
from .components.performance.profiler import PerformanceProfiler


def _normalize_free_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


# caching normalization and tokenization to avoid repeat regex work
@lru_cache(maxsize=4096)
def _normalized_cached(value: str) -> str:
    # value expected to be str already
    return _normalize_free_text(value)

@lru_cache(maxsize=4096)
def _tokenize_words(value: Any) -> tuple[str, ...]:
    text = _normalized_cached(str(value or ""))
    if not text:
        return ()
    # simple regex; precompiled not necessary but could be
    tokens = tuple(tok for tok in re.findall(r"[a-z0-9]+", text) if tok)
    return tokens


def _extract_first_number(value: Any) -> float | None:
    text = str(value or "")
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", text)
    if not match:
        return None
    raw = match.group(0).replace(",", "")
    try:
        return float(raw)
    except Exception:
        return None


@dataclass
class DeterministicTutorPracticeService:
    """Phase 3 deterministic micro-practice generator (bank-free fallback skeleton)."""

    default_max_items: int = 3
    module_adapter: ModuleAdapter | None = None

    def build_practice_items(
        self,
        *,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
        max_items: int = 3,
    ) -> tuple[TutorPracticeItem, ...]:
        limit = max(0, int(max_items or self.default_max_items or 0))
        if limit <= 0:
            return ()

        mode = str(getattr(session_state, "mode", "auto") or "auto").strip().lower()
        topic = str(getattr(session_state, "topic", "") or getattr(app_snapshot, "current_topic", "") or "").strip() or "current topic"
        topic_tokens = [t for t in _tokenize_words(topic) if len(t) >= 3]
        core_keywords = tuple(topic_tokens[:3]) or ("concept", "application")
        misconceptions = tuple(getattr(learner_profile, "misconception_tags_top", ()) or ())
        weak_caps = tuple(getattr(learner_profile, "weak_capabilities_top", ()) or ())
        weak_topics = tuple(getattr(app_snapshot, "weak_topics_top3", ()) or ())
        session_meta = dict(getattr(session_state, "meta", {}) or {})
        difficulty_hint = str(session_meta.get("difficulty_hint", "") or "").strip().lower()

        def _difficulty(base: str) -> str:
            base_text = str(base or "medium").strip().lower() or "medium"
            if difficulty_hint == "easier":
                return "easy" if base_text in {"easy", "medium"} else "medium"
            if difficulty_hint == "harder":
                return "hard" if base_text in {"medium", "hard"} else "medium"
            return base_text

        items: list[TutorPracticeItem] = []

        def _mk_id(suffix: str, idx: int) -> str:
            base = re.sub(r"[^a-z0-9]+", "-", _normalize_free_text(topic)).strip("-") or "topic"
            return f"{base}-{suffix}-{idx}"

        # Universal quick teach-back item (good after explanation)
        items.append(
            TutorPracticeItem(
                item_id=_mk_id("teachback", 1),
                item_type="teach_back",
                topic=topic,
                prompt=f"Explain {topic} in 2-4 lines and include one practical use.",
                expected_format="2-4 short lines",
                difficulty=_difficulty("easy" if mode == "teach" else "medium"),
                source="tutor_micro",
                capability_tags=weak_caps[:2],
                rubric_hints=("definition", "application"),
                meta={
                    "keywords": list(core_keywords[:2]),
                    "marks_max": 2.0,
                    "misconception_tags_by_missing_keyword": {
                        str(core_keywords[0]): "concept_anchor_missing" if core_keywords else "concept_anchor_missing",
                    },
                },
            )
        )

        if mode in {"guided_practice", "retrieval_drill", "error_clinic", "revision_planner"} and len(items) < limit:
            weak_topic = str(weak_topics[0] if weak_topics else topic).strip() or topic
            weak_tokens = [t for t in _tokenize_words(weak_topic) if len(t) >= 3][:3]
            items.append(
                TutorPracticeItem(
                    item_id=_mk_id("short", 2),
                    item_type="short_answer",
                    topic=weak_topic,
                    prompt=f"Give a concise rule/definition for '{weak_topic}' and one exam pitfall to avoid.",
                    expected_format="1-3 lines",
                    difficulty=_difficulty("medium"),
                    source="tutor_micro",
                    capability_tags=weak_caps[:2],
                    rubric_hints=("rule", "pitfall"),
                    meta={
                        "keywords": list(tuple(weak_tokens) or core_keywords[:2]),
                        "optional_keywords": ["pitfall", "avoid"],
                        "marks_max": 3.0,
                        "misconception_tags": list(misconceptions[:2]),
                    },
                )
            )

        if mode in {"retrieval_drill", "guided_practice", "revision_planner"} and len(items) < limit:
            items.append(
                TutorPracticeItem(
                    item_id=_mk_id("mcq", 3),
                    item_type="mcq",
                    topic=topic,
                    prompt=(
                        f"Which tutor step best improves retention after explaining {topic}?\n"
                        "A. Re-read notes silently\n"
                        "B. Immediate retrieval practice\n"
                        "C. Skip to a new topic\n"
                        "D. Wait until tomorrow"
                    ),
                    expected_format="Answer with A, B, C, or D",
                    difficulty=_difficulty("easy"),
                    source="tutor_micro",
                    capability_tags=weak_caps[:1],
                    rubric_hints=("retrieval",),
                    meta={
                        "correct_option": "B",
                        "marks_max": 1.0,
                        "options": ["A", "B", "C", "D"],
                        "error_tags_by_option": {
                            "A": "passive_review_bias",
                            "C": "premature_topic_switch",
                            "D": "delay_retrieval",
                        },
                    },
                )
            )

        if mode in {"section_c_coach", "exam_technique"} and len(items) < limit:
            items.append(
                TutorPracticeItem(
                    item_id=_mk_id("examtech", 4),
                    item_type="short_answer",
                    topic=topic,
                    prompt="What should you do first when a question asks you to evaluate/recommend in an exam scenario?",
                    expected_format="1-3 lines",
                    difficulty=_difficulty("medium"),
                    source="tutor_micro",
                    rubric_hints=("identify requirement", "apply to case", "justify"),
                    meta={
                        "keywords": ["requirement", "case", "justify"],
                        "marks_max": 3.0,
                    },
                )
            )

        return tuple(items[:limit])

    def build_retest_variant(
        self,
        *,
        item: TutorPracticeItem,
        assessment_result: TutorAssessmentResult,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> TutorPracticeItem | None:
        item_type = str(getattr(item, "item_type", "") or "").strip().lower() or "short_answer"
        topic = (
            str(getattr(item, "topic", "") or "").strip()
            or str(getattr(session_state, "topic", "") or "").strip()
            or str(getattr(app_snapshot, "current_topic", "") or "").strip()
            or "current topic"
        )
        result_outcome = str(getattr(assessment_result, "outcome", "") or "").strip().lower()
        next_diff = str(getattr(assessment_result, "next_difficulty", "") or "same").strip().lower()
        source_meta = dict(getattr(item, "meta", {}) or {})
        source_item_id = str(getattr(item, "item_id", "") or "").strip() or "practice-item"
        variant_of = str(source_meta.get("variant_of", "") or source_item_id).strip() or source_item_id
        try:
            prior_round = int(source_meta.get("variant_round", 0) or 0)
        except Exception:
            prior_round = 0
        variant_round = max(1, prior_round + 1)
        difficulty_map = {"easier": "easy", "same": str(getattr(item, "difficulty", "medium") or "medium"), "harder": "hard"}
        difficulty = str(difficulty_map.get(next_diff, str(getattr(item, "difficulty", "medium") or "medium")) or "medium")

        base_meta: dict[str, Any] = dict(source_meta)
        base_meta["variant_of"] = variant_of
        base_meta["variant_round"] = int(variant_round)
        base_meta["variant_from_item_type"] = item_type
        base_meta["variant_trigger_outcome"] = result_outcome or "unknown"
        base_meta["variant_source_item_id"] = source_item_id

        def _variant_id() -> str:
            base = re.sub(r"[^a-z0-9]+", "-", _normalize_free_text(variant_of)).strip("-") or "variant"
            return f"{base}-v{variant_round}"

        # Prefer keyword-preserving short-answer/teach-back variants because they can be
        # scored deterministically with the existing assessment service.
        if item_type in {"teach_back", "short_answer", "error_spot", "section_c_part"}:
            keywords = list(source_meta.get("keywords") or [])
            if not keywords:
                keywords = [kw for kw in _tokenize_words(topic) if len(kw) >= 3][:3]
            if item_type == "teach_back":
                prompt = (
                    f"Variant re-test ({variant_round}): explain {topic} again in fresh wording, "
                    "then add one common mistake to avoid."
                )
                expected_format = "2-4 short lines"
                hints = tuple(dict.fromkeys(tuple(getattr(item, "rubric_hints", ()) or ()) + ("fresh wording", "common mistake")))
                variant_kind = "paraphrase_plus_pitfall"
                transfer_level = "near"
                optional_keywords = list(dict.fromkeys(list(source_meta.get("optional_keywords") or []) + ["mistake", "avoid"]))
            else:
                prompt = (
                    f"Variant re-test ({variant_round}): answer the same concept in a new scenario/example for {topic}. "
                    "Keep it concise and practical."
                )
                expected_format = str(getattr(item, "expected_format", "") or "1-3 lines")
                hints = tuple(dict.fromkeys(tuple(getattr(item, "rubric_hints", ()) or ()) + ("new scenario",)))
                variant_kind = "context_shift"
                transfer_level = "near"
                optional_keywords = list(source_meta.get("optional_keywords") or [])
            base_meta.update(
                {
                    "variant_kind": variant_kind,
                    "transfer_level": transfer_level,
                    "keywords": [str(x).strip() for x in keywords if str(x).strip()][:8],
                    "optional_keywords": [str(x).strip() for x in optional_keywords if str(x).strip()][:8],
                }
            )
            return TutorPracticeItem(
                item_id=_variant_id(),
                item_type="short_answer" if item_type != "section_c_part" else "section_c_part",
                topic=topic,
                prompt=prompt,
                expected_format=expected_format,
                difficulty=difficulty,
                source="tutor_micro_variant",
                capability_tags=tuple(getattr(item, "capability_tags", ()) or ()),
                rubric_hints=hints[:6],
                meta=base_meta,
            )

        if item_type == "mcq":
            correct_opt = str(source_meta.get("correct_option", "") or "B").strip().upper() or "B"
            variant_kind = "mcq_rephrase"
            prompt = (
                f"Variant re-test ({variant_round}): after learning {topic}, which step best confirms real understanding?\n"
                "A. Read the same explanation again\n"
                "B. Answer a new but related check question\n"
                "C. Move to a different topic immediately\n"
                "D. Memorize the exact wording of the last question"
            )
            if correct_opt not in {"A", "B", "C", "D"}:
                correct_opt = "B"
            base_meta.update(
                {
                    "variant_kind": variant_kind,
                    "transfer_level": "near",
                    "correct_option": "B",
                    "options": ["A", "B", "C", "D"],
                    "error_tags_by_option": {
                        "A": "passive_review_bias",
                        "C": "premature_topic_switch",
                        "D": "rote_memorization_bias",
                    },
                    "marks_max": float(source_meta.get("marks_max", 1.0) or 1.0),
                }
            )
            return TutorPracticeItem(
                item_id=_variant_id(),
                item_type="mcq",
                topic=topic,
                prompt=prompt,
                expected_format="Answer with A, B, C, or D",
                difficulty=difficulty,
                source="tutor_micro_variant",
                capability_tags=tuple(getattr(item, "capability_tags", ()) or ()),
                rubric_hints=tuple(dict.fromkeys(tuple(getattr(item, "rubric_hints", ()) or ()) + ("new variant",))),
                meta=base_meta,
            )

        # Fallback for unsupported/strict numeric items: preserve concept coverage with a
        # deterministic explain-and-apply check rather than fabricating numeric parameters.
        keywords = list(source_meta.get("keywords") or [])
        if not keywords:
            keywords = [kw for kw in _tokenize_words(topic) if len(kw) >= 3][:3]
        base_meta.update(
            {
                "variant_kind": "fallback_explain_apply",
                "transfer_level": "near",
                "keywords": [str(x).strip() for x in keywords if str(x).strip()][:8],
                "optional_keywords": ["apply", "example"],
                "marks_max": float(source_meta.get("marks_max", 2.0) or 2.0),
            }
        )
        return TutorPracticeItem(
            item_id=_variant_id(),
            item_type="short_answer",
            topic=topic,
            prompt=(
                f"Variant re-test ({variant_round}): explain the method for {topic} and show how you would apply it "
                "to a slightly different case (no full calculation needed)."
            ),
            expected_format="2-4 short lines",
            difficulty=difficulty,
            source="tutor_micro_variant",
            capability_tags=tuple(getattr(item, "capability_tags", ()) or ()),
            rubric_hints=tuple(dict.fromkeys(tuple(getattr(item, "rubric_hints", ()) or ()) + ("method", "application"))),
            meta=base_meta,
        )


@dataclass
class DeterministicTutorAssessmentService:
    """Phase 3 deterministic micro-assessment scoring for short Tutor practice items."""

    partial_threshold: float = 0.4
    correct_threshold: float = 0.75

    def assess(
        self,
        *,
        item: TutorPracticeItem,
        submission: TutorAssessmentSubmission,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> TutorAssessmentResult:
        item_type = str(getattr(item, "item_type", "") or "").strip().lower()
        meta = dict(getattr(item, "meta", {}) or {})
        answer_text = str(getattr(submission, "answer_text", "") or "")
        if item_type == "mcq":
            return self._assess_mcq(item, answer_text)
        if item_type == "calculation_step":
            return self._assess_numeric(item, answer_text)
        # Open-ended items: no keyword matching; use AI judge (see AITutorAssessmentService).
        marks_max = float(meta.get("marks_max", 2.0) or 2.0)
        return TutorAssessmentResult(
            item_id=item.item_id,
            outcome="partial",
            marks_awarded=round(marks_max * 0.5, 2),
            marks_max=marks_max,
            feedback="Open-ended assessment requires AI judge. Enable a local model for expert grading.",
            error_tags=("ai_judge_required",),
            retry_recommended=True,
            next_difficulty="same",
        )

    def _assess_mcq(self, item: TutorPracticeItem, answer_text: str) -> TutorAssessmentResult:
        meta = dict(item.meta or {})
        expected = str(meta.get("correct_option", "") or meta.get("answer_key", "") or "").strip().upper()
        picked_match = re.search(r"[A-Da-d]", str(answer_text or ""))
        picked = picked_match.group(0).upper() if picked_match else _normalize_free_text(answer_text).upper()
        marks_max = float(meta.get("marks_max", 1.0) or 1.0)
        error_tags_by_option = meta.get("error_tags_by_option", {}) if isinstance(meta.get("error_tags_by_option"), dict) else {}
        if expected and picked == expected:
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="correct",
                marks_awarded=marks_max,
                marks_max=marks_max,
                feedback=f"Correct. {expected} is the best answer.",
            )
        error_tags: tuple[str, ...] = ()
        wrong_tag = str(error_tags_by_option.get(picked, "") or "").strip()
        if wrong_tag:
            error_tags = (wrong_tag,)
        return TutorAssessmentResult(
            item_id=item.item_id,
            outcome="incorrect",
            marks_awarded=0.0,
            marks_max=marks_max,
            feedback=f"Incorrect. Expected {expected or 'the keyed option'}.",
            error_tags=error_tags,
            retry_recommended=True,
            next_difficulty="same",
        )

    def _assess_numeric(self, item: TutorPracticeItem, answer_text: str) -> TutorAssessmentResult:
        meta = dict(item.meta or {})
        expected_raw = meta.get("numeric_answer", meta.get("answer_value"))
        expected: float | None
        if expected_raw is None:
            expected = None
        else:
            try:
                expected = float(expected_raw)
            except Exception:
                expected = None
        marks_max = float(meta.get("marks_max", 1.0) or 1.0)
        if expected is None:
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="incorrect",
                marks_awarded=0.0,
                marks_max=marks_max,
                feedback="No numeric answer key configured for this practice item.",
                error_tags=("missing_answer_key",),
            )
        actual = _extract_first_number(answer_text)
        if actual is None:
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="incorrect",
                marks_awarded=0.0,
                marks_max=marks_max,
                feedback="I could not find a numeric answer. Enter a number (you can include workings).",
                error_tags=("no_numeric_answer",),
                retry_recommended=True,
            )
        tolerance = float(meta.get("tolerance", 0.01) or 0.01)
        tolerance_pct = meta.get("tolerance_pct")
        allowed = abs(tolerance)
        if tolerance_pct is not None:
            try:
                pct = abs(float(tolerance_pct))
                allowed = max(allowed, abs(expected) * pct)
            except Exception:
                pass
        delta = abs(actual - expected)
        if delta <= allowed:
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="correct",
                marks_awarded=marks_max,
                marks_max=marks_max,
                feedback=f"Correct. Your answer {actual:g} is within tolerance.",
            )
        if delta <= (allowed * 5.0):
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="partial",
                marks_awarded=round(marks_max * 0.5, 2),
                marks_max=marks_max,
                feedback=f"Close, but outside tolerance. Expected about {expected:g}; you gave {actual:g}.",
                error_tags=("numeric_precision",),
                retry_recommended=True,
                next_difficulty="same",
            )
        return TutorAssessmentResult(
            item_id=item.item_id,
            outcome="incorrect",
            marks_awarded=0.0,
            marks_max=marks_max,
            feedback=f"Incorrect numeric result. Expected about {expected:g}; you gave {actual:g}.",
            error_tags=("numeric_mismatch",),
            retry_recommended=True,
            next_difficulty="easier",
        )

    def _assess_keyword_based(
        self,
        *,
        item: TutorPracticeItem,
        answer_text: str,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> TutorAssessmentResult:
        meta = dict(item.meta or {})
        marks_max = float(meta.get("marks_max", 2.0) or 2.0)
        text_norm = _normalize_free_text(answer_text)
        answer_tokens = set(_tokenize_words(answer_text))
        required_keywords = self._collect_keywords(item, meta)
        optional_keywords = tuple(str(x).strip().lower() for x in (meta.get("optional_keywords") or []) if str(x).strip())
        if not text_norm:
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="incorrect",
                marks_awarded=0.0,
                marks_max=marks_max,
                feedback="No answer provided yet.",
                error_tags=("empty_answer",),
                retry_recommended=True,
                next_difficulty="same",
            )

        hits: list[str] = []
        missing: list[str] = []
        for kw in required_keywords:
            if self._keyword_hit(kw, text_norm, answer_tokens):
                hits.append(kw)
            else:
                missing.append(kw)

        optional_hits = [kw for kw in optional_keywords if self._keyword_hit(kw, text_norm, answer_tokens)]
        required_count = max(1, len(required_keywords))
        ratio = len(hits) / float(required_count)
        bonus = 0.0
        if optional_keywords:
            bonus = min(0.15, len(optional_hits) / max(1.0, len(optional_keywords)) * 0.15)
        score_ratio = max(0.0, min(1.0, ratio + bonus))

        if score_ratio >= float(self.correct_threshold):
            outcome = "correct"
            next_diff = "harder"
            retry = False
        elif score_ratio >= float(self.partial_threshold):
            outcome = "partial"
            next_diff = "same"
            retry = True
        else:
            outcome = "incorrect"
            next_diff = "easier"
            retry = True

        marks_awarded = round(marks_max * score_ratio, 2)
        if outcome == "correct" and marks_awarded < marks_max:
            marks_awarded = marks_max
        elif outcome == "incorrect":
            marks_awarded = 0.0

        misconception_tags = self._misconception_tags_from_missing(meta, missing, learner_profile)
        error_tags = self._error_tags_from_missing(meta, missing)
        if not error_tags and outcome != "correct":
            error_tags = ("missing_key_points",)

        feedback_parts = []
        if outcome == "correct":
            feedback_parts.append("Good answer. You covered the key points.")
        elif outcome == "partial":
            feedback_parts.append("Partly correct. You have the right direction but missed some key points.")
        else:
            feedback_parts.append("Not enough key points yet. Let's tighten the answer.")
        if hits:
            feedback_parts.append("Hit: " + ", ".join(hits[:3]))
        if missing:
            feedback_parts.append("Missing: " + ", ".join(missing[:3]))
        if optional_hits:
            feedback_parts.append("Strong extras: " + ", ".join(optional_hits[:2]))

        return TutorAssessmentResult(
            item_id=item.item_id,
            outcome=outcome,
            marks_awarded=max(0.0, min(marks_max, marks_awarded)),
            marks_max=marks_max,
            feedback=" ".join(feedback_parts).strip(),
            error_tags=error_tags,
            misconception_tags=misconception_tags,
            retry_recommended=retry,
            next_difficulty=next_diff,
            meta={
                "keyword_hits": hits,
                "keyword_missing": missing,
                "score_ratio": round(score_ratio, 3),
                "session_phase": str(getattr(session_state, "loop_phase", "") or ""),
            },
        )

    def _collect_keywords(self, item: TutorPracticeItem, meta: dict[str, Any]) -> tuple[str, ...]:
        raw = meta.get("keywords")
        words: list[str] = []
        if isinstance(raw, (list, tuple)):
            for item_kw in raw:
                text = str(item_kw or "").strip().lower()
                if text:
                    words.append(text)
        if not words:
            for kw in tuple(getattr(item, "rubric_hints", ()) or ()):
                text = str(kw or "").strip().lower()
                if text:
                    words.append(text)
        if not words:
            topic_tokens = [t for t in _tokenize_words(getattr(item, "topic", "")) if len(t) >= 3]
            words.extend(topic_tokens[:2])
        dedup: list[str] = []
        seen: set[str] = set()
        for text in words:
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            dedup.append(text)
        return tuple(dedup[:8]) or ("concept",)

    def _keyword_hit(self, keyword: str, text_norm: str, answer_tokens: set[str]) -> bool:
        key = str(keyword or "").strip().lower()
        if not key:
            return False
        if " " in key:
            return key in text_norm
        return key in answer_tokens or key in text_norm

    def _misconception_tags_from_missing(
        self,
        meta: dict[str, Any],
        missing_keywords: list[str],
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> tuple[str, ...]:
        tags: list[str] = []
        mapping = meta.get("misconception_tags_by_missing_keyword")
        if isinstance(mapping, dict):
            for key in missing_keywords:
                mapped = str(mapping.get(key, "") or "").strip()
                if mapped:
                    tags.append(mapped)
        explicit = meta.get("misconception_tags")
        if isinstance(explicit, (list, tuple)) and missing_keywords:
            for raw in explicit:
                text = str(raw or "").strip()
                if text:
                    tags.append(text)
        # retain one recent known misconception to keep continuity in the loop
        profile_tags = tuple(getattr(learner_profile, "misconception_tags_top", ()) or ())
        if profile_tags and missing_keywords:
            tags.append(str(profile_tags[0]))
        seen: set[str] = set()
        out: list[str] = []
        for tag in tags:
            key = tag.lower()
            if not tag or key in seen:
                continue
            seen.add(key)
            out.append(tag)
            if len(out) >= 4:
                break
        return tuple(out)

    def _error_tags_from_missing(self, meta: dict[str, Any], missing_keywords: list[str]) -> tuple[str, ...]:
        tags: list[str] = []
        for kw in missing_keywords[:3]:
            tags.append(f"missing_{re.sub(r'[^a-z0-9]+', '_', kw.lower()).strip('_') or 'keyword'}")
        explicit = meta.get("error_tags")
        if isinstance(explicit, (list, tuple)) and missing_keywords:
            for raw in explicit:
                text = str(raw or "").strip()
                if text:
                    tags.append(text)
        seen: set[str] = set()
        out: list[str] = []
        for tag in tags:
            key = tag.lower()
            if key in seen or not tag:
                continue
            seen.add(key)
            out.append(tag)
            if len(out) >= 4:
                break
        return tuple(out)


def _extract_first_json_object(text: str) -> str | None:
    """Extract first {...} or [...] from text. Returns None if not found."""
    if not text or not isinstance(text, str):
        return None
    start = text.find("{")
    if start < 0:
        start = text.find("[")
    if start < 0:
        return None
    depth = 0
    open_ch, close_ch = ("{", "}") if text[start] == "{" else ("[", "]")
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


@dataclass
class AITutorAssessmentService:
    """Practice loop assessment using AI judge only. No keyword matching."""

    generate_fn: Callable[[str], tuple[str, str | None]]
    deterministic_fallback: DeterministicTutorAssessmentService = field(
        default_factory=DeterministicTutorAssessmentService
    )
    get_suggested_tags: Callable[[str, str], Sequence[str]] | None = None

    def assess(
        self,
        *,
        item: TutorPracticeItem,
        submission: TutorAssessmentSubmission,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> TutorAssessmentResult:
        item_type = str(getattr(item, "item_type", "") or "").strip().lower()
        answer_text = str(getattr(submission, "answer_text", "") or "")
        # MCQ and numeric: use deterministic (no keywords).
        if item_type == "mcq" or item_type == "calculation_step":
            return self.deterministic_fallback.assess(
                item=item,
                submission=submission,
                session_state=session_state,
                learner_profile=learner_profile,
            )
        # Open-ended: AI judge only (expertise-based, no keyword matching).
        return self._assess_with_ai(
            item=item,
            submission=submission,
            answer_text=answer_text,
            session_state=session_state,
            learner_profile=learner_profile,
        )

    def _assess_with_ai(
        self,
        *,
        item: TutorPracticeItem,
        submission: TutorAssessmentSubmission,
        answer_text: str,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> TutorAssessmentResult:
        meta = dict(getattr(item, "meta", {}) or {})
        marks_max = float(meta.get("marks_max", 2.0) or 2.0)
        if not str(answer_text or "").strip():
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="incorrect",
                marks_awarded=0.0,
                marks_max=marks_max,
                feedback="No answer provided yet.",
                error_tags=("empty_answer",),
                retry_recommended=True,
                next_difficulty="same",
            )
        prompt = self._build_judge_prompt(
            item=item,
            submission=submission,
            answer_text=answer_text,
            session_state=session_state,
            learner_profile=learner_profile,
        )
        text, err = self.generate_fn(prompt)
        if err or not (text or "").strip():
            return TutorAssessmentResult(
                item_id=item.item_id,
                outcome="partial",
                marks_awarded=round(marks_max * 0.5, 2),
                marks_max=marks_max,
                feedback="Assessment unavailable; try again or enable local model.",
                error_tags=("ai_judge_unavailable",),
                retry_recommended=True,
                next_difficulty="same",
            )
        payload = self._parse_judge_response(text, item.item_id, marks_max)
        if payload is not None:
            logger.info(
                "assessment_audit",
                extra={
                    "item_id": item.item_id,
                    "outcome": payload.outcome,
                    "marks_awarded": payload.marks_awarded,
                    "marks_max": payload.marks_max,
                    "source": "ai_judge",
                },
            )
            return payload
        # Stricter fallback: retry with JSON-only instruction and shorter prompt.
        retry_prompt = self._build_judge_prompt_json_only(
            item=item, answer_text=answer_text, session_state=session_state, learner_profile=learner_profile
        )
        text2, err2 = self.generate_fn(retry_prompt)
        if not err2 and (text2 or "").strip():
            payload = self._parse_judge_response(text2, item.item_id, marks_max)
            if payload is not None:
                logger.info(
                    "assessment_audit",
                    extra={
                        "item_id": item.item_id,
                        "outcome": payload.outcome,
                        "marks_awarded": payload.marks_awarded,
                        "marks_max": payload.marks_max,
                        "source": "ai_judge_retry",
                    },
                )
                return payload
        return TutorAssessmentResult(
            item_id=item.item_id,
            outcome="partial",
            marks_awarded=round(marks_max * 0.5, 2),
            marks_max=marks_max,
            feedback="Could not parse AI judgement; answer recorded.",
            retry_recommended=True,
            next_difficulty="same",
        )

    def _build_judge_prompt(
        self,
        *,
        item: TutorPracticeItem,
        submission: TutorAssessmentSubmission | None,
        answer_text: str,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> str:
        module = str(getattr(learner_profile, "module", "") or getattr(session_state, "module", "") or "").strip()
        topic = str(getattr(item, "topic", "") or "").strip()
        prompt = str(getattr(item, "prompt", "") or "").strip()
        rubric_hints = tuple(getattr(item, "rubric_hints", ()) or ())
        payload_blocks: list[tuple[str, str]] = [
            ("Module", module or "ACCA"),
            ("Topic", topic or "n/a"),
        ]
        if submission is not None:
            conf = getattr(submission, "confidence", None)
            if conf is not None and isinstance(conf, (int, float)):
                try:
                    c = max(1, min(5, int(conf)))
                    payload_blocks.append(("Learner confidence (1–5)", str(c)))
                except Exception:
                    pass
        get_tags = self.get_suggested_tags
        if get_tags is not None and module and topic:
            try:
                suggested = list(get_tags(module, topic))[:12]
                if suggested:
                    payload_blocks.append(
                        ("Suggested tags for this topic (choose or align with)", ", ".join(str(t) for t in suggested))
                    )
            except Exception:
                pass
        payload_blocks.append(("Question", prompt[:2000] or "n/a"))
        if rubric_hints:
            focus_parts = [str(h) for h in list(rubric_hints)[:5]]
            payload_blocks.append(("Marking focus", ", ".join(focus_parts)))
        payload_blocks.append(("Learner answer", (answer_text or "")[:3000].strip() or "n/a"))
        return build_judge_prompt_3es(
            role_base=ASSESSMENT_JUDGE_ROLE_BASE,
            schema_one_line=ASSESSMENT_JUDGE_SCHEMA_ONE_LINE,
            rules=list(ASSESSMENT_JUDGE_RULES or []),
            payload_blocks=payload_blocks,
        )

    def _build_judge_prompt_json_only(
        self,
        *,
        item: TutorPracticeItem,
        answer_text: str,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
    ) -> str:
        """Shorter prompt for parse retry: insist on JSON only (3Es order, minimal payload)."""
        module = str(getattr(learner_profile, "module", "") or getattr(session_state, "module", "") or "").strip()
        topic = str(getattr(item, "topic", "") or "").strip()
        prompt = str(getattr(item, "prompt", "") or "").strip()
        payload_blocks = [
            ("Module", f"{module or 'ACCA'} Topic: {topic or 'n/a'}"),
            ("Question", (prompt or "")[:800] or "n/a"),
            ("Learner answer", (str(answer_text or "").strip())[:1500] or "n/a"),
        ]
        return build_judge_prompt_3es(
            role_base=JUDGE_JSON_ONLY,
            schema_one_line=ASSESSMENT_JUDGE_SCHEMA_ONE_LINE,
            rules=[],
            payload_blocks=payload_blocks,
        )

    def _parse_judge_response(self, text: str, item_id: str, marks_max: float) -> TutorAssessmentResult | None:
        raw = _extract_first_json_object(text)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        outcome = str(data.get("outcome", "") or "incorrect").strip().lower()
        if outcome not in ("correct", "partial", "incorrect"):
            outcome = "incorrect"
        try:
            marks_awarded = float(data.get("marks_awarded", 0.0) or 0.0)
        except Exception:
            marks_awarded = 0.0
        marks_awarded = max(0.0, min(marks_max, round(marks_awarded, 2)))
        feedback = str(data.get("feedback", "") or "").strip() or "Assessed."
        error_tags_raw = data.get("error_tags")
        if isinstance(error_tags_raw, list):
            error_tags = tuple(str(x).strip() for x in error_tags_raw if str(x).strip())[:6]
        else:
            error_tags = ()
        misconception_tags: tuple[str, ...] = ()
        mis_raw = data.get("misconception_tags")
        if isinstance(mis_raw, list):
            misconception_tags = tuple(str(x).strip() for x in mis_raw if str(x).strip())[:6]
        else:
            main_mis = data.get("main_misconception")
            if isinstance(main_mis, str) and main_mis.strip():
                misconception_tags = (main_mis.strip(),)
        suggested_next_step = str(data.get("suggested_next_step", "") or "").strip()[:300] or ""
        return TutorAssessmentResult(
            item_id=item_id,
            outcome=outcome,
            marks_awarded=marks_awarded,
            marks_max=marks_max,
            feedback=feedback[:500],
            error_tags=error_tags,
            misconception_tags=misconception_tags,
            suggested_next_step=suggested_next_step,
            retry_recommended=outcome != "correct",
            next_difficulty="harder" if outcome == "correct" else ("easier" if outcome == "incorrect" else "same"),
        )


@dataclass
class DeterministicTutorInterventionPolicyService:
    """Phase 3 starter: deterministic corrective intervention mapping.

    Chooses a correction style using outcome/error/misconception signals. This remains
    advisory and explainable (no direct state mutation).
    """
    module_adapter: ModuleAdapter | None = None

    def choose_intervention(
        self,
        *,
        item: TutorPracticeItem,
        assessment_result: TutorAssessmentResult,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> dict[str, object]:
        outcome = str(getattr(assessment_result, "outcome", "") or "").strip().lower() or "incorrect"
        error_tags = tuple(
            str(x).strip().lower()
            for x in tuple(getattr(assessment_result, "error_tags", ()) or ())
            if str(x).strip()
        )
        mis_tags = tuple(
            str(x).strip().lower()
            for x in tuple(getattr(assessment_result, "misconception_tags", ()) or ())
            if str(x).strip()
        )
        item_type = str(getattr(item, "item_type", "") or "").strip().lower() or "short_answer"
        topic = (
            str(getattr(item, "topic", "") or "").strip()
            or str(getattr(session_state, "topic", "") or "").strip()
            or str(getattr(app_snapshot, "current_topic", "") or "").strip()
            or "current topic"
        )
        retry_recommended = bool(getattr(assessment_result, "retry_recommended", False))
        loop_metrics = {}
        try:
            profile_meta = dict(getattr(learner_profile, "meta", {}) or {})
            raw_metrics = profile_meta.get("learning_loop_metrics", {})
            loop_metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
        except Exception:
            loop_metrics = {}
        try:
            recurrence_count = max(0, int(loop_metrics.get("misconception_recurrence_count", 0) or 0))
        except Exception:
            recurrence_count = 0
        try:
            streak_incorrect = max(0, int(loop_metrics.get("consecutive_incorrect", 0) or 0))
        except Exception:
            streak_incorrect = 0

        intervention_type = "reinforce_recall"
        rationale = "Stabilize recall with a short follow-up check."
        hint_strategy = "minimal_prompt"
        recommended_variant = bool(retry_recommended)
        severity = "info"

        if any(tag in error_tags for tag in ("no_numeric_answer", "numeric_mismatch", "numeric_precision")) or item_type == "calculation_step":
            intervention_type = "step_drill"
            rationale = "Numeric/procedural error detected. Rebuild the method step-by-step before checking the final value."
            hint_strategy = "show_method_steps"
            severity = "warning" if outcome != "correct" else "info"
        elif mis_tags or recurrence_count >= 2:
            intervention_type = "worked_example_then_retest"
            rationale = "Recurring misconception signal detected. Correct with a worked example, then re-test on a new variant."
            hint_strategy = "worked_example"
            recommended_variant = True
            severity = "intervention" if recurrence_count >= 2 or streak_incorrect >= 2 else "warning"
        elif any("missing_" in tag for tag in error_tags):
            intervention_type = "keyword_recovery"
            rationale = "Key-point omission detected. Prompt missing points explicitly, then re-test with a near-transfer wording."
            hint_strategy = "keyword_hint"
            recommended_variant = True
            severity = "warning" if outcome != "correct" else "info"
        elif outcome == "partial":
            intervention_type = "near_transfer_retest"
            rationale = "Partly correct answer: confirm understanding with a same-concept, new-surface-form variant."
            hint_strategy = "nudge_then_retry"
            recommended_variant = True
            severity = "info"
        elif outcome == "incorrect":
            intervention_type = "guided_reteach"
            rationale = "Incorrect answer without a strong error signature. Use a short re-teach and immediate re-test."
            hint_strategy = "scaffolded_reteach"
            recommended_variant = True
            severity = "warning"
        elif outcome == "correct":
            intervention_type = "desirable_difficulty_ladder"
            rationale = "Correct answer: increase difficulty slightly to test durable understanding and transfer."
            hint_strategy = "increase_difficulty"
            recommended_variant = False
            severity = "info"

        rationale_short = rationale
        if len(rationale_short) > 96:
            rationale_short = rationale_short[:93].rstrip() + "..."
        evidence: list[str] = [f"outcome={outcome}", f"item_type={item_type}"]
        if error_tags:
            evidence.append(f"errors={','.join(error_tags[:2])}")
        if mis_tags:
            evidence.append(f"mis={','.join(mis_tags[:2])}")
        if recurrence_count > 0:
            evidence.append(f"recur={recurrence_count}")
        if streak_incorrect > 0:
            evidence.append(f"streak_bad={streak_incorrect}")

        return {
            "intervention_type": intervention_type,
            "rationale": rationale,
            "rationale_short": rationale_short,
            "hint_strategy": hint_strategy,
            "recommended_variant": bool(recommended_variant),
            "severity": severity,
            "topic": topic,
            "evidence": tuple(evidence[:4]),
        }


@dataclass
class RuleBasedTutorLearningLoopService:
    """Phase 2 deterministic learning-loop controller.

    This service does not generate teaching text with an LLM. It selects a tutor mode,
    loop phase, and (optionally) a safe next action intent based on current app state,
    learner profile, and session state. It is intended to be used as a planning layer
    ahead of prompt generation.
    """

    session_controller: TutorSessionControllerService
    learner_model_store: TutorLearnerModelService
    practice_service: TutorPracticeService | None = None
    module_adapter: ModuleAdapter | None = None
    max_practice_items: int = 2
    policy_thresholds: TutorLoopPolicyThresholds = field(default_factory=TutorLoopPolicyThresholds)
    policy_tuning_service: DeterministicTutorPolicyTuningService | None = field(
        default_factory=DeterministicTutorPolicyTuningService
    )
    _last_tuned_thresholds: TutorLoopPolicyThresholds | None = None
    _last_tuning_meta: dict[str, object] = field(default_factory=dict)

    def run_turn(self, request: TutorLoopTurnRequest) -> TutorLoopTurnResult:
        app_snapshot = request.app_snapshot
        current_session = self._start_or_sync_session(request)
        learner_profile = self._sync_profile(request)
        self._refresh_tuned_thresholds(learner_profile=learner_profile, app_snapshot=app_snapshot)
        cognitive_meta = self._cognitive_runtime_meta(request)

        mode_used, mode_reason = self._choose_mode(
            request=request,
            session_state=current_session,
            learner_profile=learner_profile,
            app_snapshot=app_snapshot,
        )
        phase_after_turn = self._choose_phase(
            mode=mode_used,
            session_state=current_session,
            learner_profile=learner_profile,
            app_snapshot=app_snapshot,
        )
        session_meta = dict(getattr(current_session, "meta", {}) or {})
        difficulty_hint = self._difficulty_hint_from_cognitive(cognitive_meta, mode_used=mode_used)
        if difficulty_hint:
            session_meta["difficulty_hint"] = str(difficulty_hint)
        elif "difficulty_hint" in session_meta:
            session_meta.pop("difficulty_hint", None)
        if cognitive_meta:
            session_meta["cognitive_runtime_active"] = bool(cognitive_meta.get("enabled", False))
            if "posterior_mean" in cognitive_meta:
                session_meta["cognitive_posterior_mean"] = float(cognitive_meta.get("posterior_mean", 0.0) or 0.0)
            if "posterior_variance" in cognitive_meta:
                session_meta["cognitive_posterior_variance"] = float(cognitive_meta.get("posterior_variance", 0.0) or 0.0)
            session_meta["cognitive_struggle_mode"] = bool(cognitive_meta.get("struggle_mode", False))

        session_state = self.session_controller.save_session(
            replace(
                current_session,
                mode=mode_used,
                loop_phase=phase_after_turn,
                updated_at_ts=getattr(current_session, "updated_at_ts", ""),
                active=True,
                meta=session_meta,
            )
        )

        practice_items: tuple[TutorPracticeItem, ...] = ()
        if self.practice_service is not None and phase_after_turn in {"practice", "assess", "reinforce"}:
            try:
                practice_items = tuple(
                    self.practice_service.build_practice_items(
                        session_state=session_state,
                        learner_profile=learner_profile,
                        app_snapshot=app_snapshot,
                        max_items=max(0, int(self.max_practice_items)),
                    )
                    or ()
                )
            except Exception:
                practice_items = ()

        session_state = self.session_controller.save_session(
            replace(
                session_state,
                active_practice_item_id=(
                    str(practice_items[0].item_id)
                    if practice_items and str(practice_items[0].item_id or "").strip()
                    else str(session_state.active_practice_item_id or "")
                ),
            )
        )

        action_intent = self._build_next_action_intent(
            request=request,
            session_state=session_state,
            learner_profile=learner_profile,
            app_snapshot=app_snapshot,
            mode_used=mode_used,
            phase_after_turn=phase_after_turn,
        )

        response_text = self._build_response_plan_text(
            request=request,
            session_state=session_state,
            learner_profile=learner_profile,
            mode_used=mode_used,
            phase_after_turn=phase_after_turn,
            mode_reason=mode_reason,
            practice_items=practice_items,
            action_intent=action_intent,
        )
        telemetry = {
            "planner": "rule_based_phase2",
            "mode_used": mode_used,
            "mode_reason": mode_reason,
            "phase_after_turn": phase_after_turn,
            "practice_item_count": len(practice_items),
            "must_review_due": int(getattr(app_snapshot, "must_review_due", 0) or 0),
            "overdue_srs_count": int(getattr(app_snapshot, "overdue_srs_count", 0) or 0),
            "recent_failures": int(getattr(session_state, "recent_failures", 0) or 0),
            "misconception_count": len(tuple(getattr(learner_profile, "misconception_tags_top", ()) or ())),
        }
        if cognitive_meta:
            telemetry.update(
                {
                    "cognitive_runtime_active": 1 if bool(cognitive_meta.get("enabled", False)) else 0,
                    "cognitive_struggle_mode": 1 if bool(cognitive_meta.get("struggle_mode", False)) else 0,
                    "cognitive_quiz_active": 1 if bool(cognitive_meta.get("quiz_active", False)) else 0,
                    "cognitive_posterior_mean": float(cognitive_meta.get("posterior_mean", 0.0) or 0.0),
                    "cognitive_posterior_variance": float(cognitive_meta.get("posterior_variance", 0.0) or 0.0),
                    "cognitive_difficulty_hint": str(difficulty_hint or ""),
                }
            )
        loop_metrics = self._learner_loop_metrics(learner_profile)
        if loop_metrics:
            telemetry.update(
                {
                    "loop_assessments_total": int(loop_metrics.get("assessments_total", 0) or 0),
                    "loop_correct_count": int(loop_metrics.get("correct_count", 0) or 0),
                    "loop_partial_count": int(loop_metrics.get("partial_count", 0) or 0),
                    "loop_incorrect_count": int(loop_metrics.get("incorrect_count", 0) or 0),
                    "loop_mis_recurrence_count": int(loop_metrics.get("misconception_recurrence_count", 0) or 0),
                    "loop_consecutive_correct": int(loop_metrics.get("consecutive_correct", 0) or 0),
                    "loop_consecutive_incorrect": int(loop_metrics.get("consecutive_incorrect", 0) or 0),
                    "loop_score_ratio_ema": float(loop_metrics.get("avg_score_ratio_ema", 0.0) or 0.0),
                }
            )
        active_thresholds = self.get_active_policy_thresholds()
        tuning_meta = self.get_policy_tuning_meta()
        telemetry.update(
            {
                "loop_thresholds": active_thresholds,
                "loop_tuning_status": str(tuning_meta.get("status", "stable") or "stable"),
                "loop_tuning_reason": str(tuning_meta.get("reason", "stable") or "stable"),
            }
        )
        return TutorLoopTurnResult(
            response_text=response_text,
            mode_used=mode_used,
            phase_after_turn=phase_after_turn,
            session_state=session_state,
            learner_profile=learner_profile,
            practice_items=practice_items,
            action_intent=action_intent,
            telemetry=telemetry,
        )

    def _start_or_sync_session(self, request: TutorLoopTurnRequest) -> TutorSessionState:
        session = request.session_state
        session_id = str(getattr(session, "session_id", "") or "").strip() or "default"
        module = str(getattr(request.app_snapshot, "module", "") or getattr(session, "module", "") or "").strip()
        topic = str(getattr(request.app_snapshot, "current_topic", "") or getattr(session, "topic", "") or "").strip()
        mode_hint = str(getattr(request, "mode_override", "auto") or "auto")
        if mode_hint == "auto":
            mode_hint = str(getattr(session, "mode", "auto") or "auto")
        objective = str(getattr(session, "session_objective", "") or "").strip()
        if not objective and topic:
            objective = f"Learn and apply {topic}"
        success = str(getattr(session, "success_criteria", "") or "").strip()
        if not success and topic:
            success = f"Explain and answer practice checks on {topic}"
        return self.session_controller.start_or_resume_session(
            session_id=session_id,
            module=module,
            topic=topic,
            mode=mode_hint,
            session_objective=objective,
            success_criteria=success,
            target_concepts=tuple(getattr(session, "target_concepts", ()) or ()),
        )

    def _sync_profile(self, request: TutorLoopTurnRequest) -> TutorLearnerProfileSnapshot:
        profile = request.learner_profile
        learner_id = str(getattr(profile, "learner_id", "") or "").strip() or "default"
        module = str(getattr(request.app_snapshot, "module", "") or getattr(profile, "module", "") or "").strip()
        stored = self.learner_model_store.get_or_create_profile(learner_id, module)
        # Prefer the richer incoming snapshot if it already contains tutor-local signals.
        if (
            tuple(getattr(profile, "misconception_tags_top", ()) or ())
            or tuple(getattr(profile, "weak_capabilities_top", ()) or ())
            or str(getattr(profile, "last_practice_outcome", "") or "").strip()
            or bool((getattr(profile, "meta", {}) or {}).get("learning_loop_metrics"))
            or abs(float(getattr(profile, "chat_to_quiz_transfer_score", 0.0) or 0.0)) > 0.0
            or abs(float(getattr(profile, "confidence_calibration_bias", 0.0) or 0.0)) > 0.0
        ):
            return self.learner_model_store.save_profile(
                replace(
                    profile,
                    learner_id=learner_id,
                    module=module,
                )
            )
        return stored

    def _choose_mode(
        self,
        *,
        request: TutorLoopTurnRequest,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> tuple[str, str]:
        override = str(getattr(request, "mode_override", "auto") or "auto").strip().lower()
        if override and override != "auto":
            return override, "mode_override"

        user_text = str(getattr(request, "user_message", "") or "").strip().lower()
        current_mode = str(getattr(session_state, "mode", "auto") or "auto").strip().lower()
        if current_mode and current_mode != "auto" and bool(getattr(session_state, "active", False)):
            return current_mode, "active_session_mode"

        if "section c" in user_text or "constructed response" in user_text:
            return "section_c_coach", "section_c_request"
        if any(token in user_text for token in ("exam technique", "time management", "how to answer", "marking")):
            return "exam_technique", "exam_technique_request"
        if any(token in user_text for token in ("quiz", "drill", "test me", "practice me", "question me")):
            return "retrieval_drill", "practice_request"
        if any(token in user_text for token in ("explain", "what is", "why does", "how does", "teach me")):
            return "teach", "explanation_request"

        cognitive_mode = self._choose_mode_from_cognitive(request=request, app_snapshot=app_snapshot)
        if cognitive_mode is not None:
            return cognitive_mode

        metrics = self._learner_loop_metrics(learner_profile)
        tuned_mode = self._choose_mode_from_metrics(metrics, learner_profile, app_snapshot)
        if tuned_mode is not None:
            return tuned_mode

        recent_failures = int(getattr(session_state, "recent_failures", 0) or 0)
        misconceptions = tuple(getattr(learner_profile, "misconception_tags_top", ()) or ())
        if recent_failures >= 2 or len(misconceptions) >= 2:
            return "error_clinic", "recent_failures_or_misconceptions"

        must_review_due = int(getattr(app_snapshot, "must_review_due", 0) or 0)
        overdue = int(getattr(app_snapshot, "overdue_srs_count", 0) or 0)
        if must_review_due > 0 or overdue > 0:
            return "revision_planner", "review_pressure"

        weak_topics_raw = tuple(getattr(app_snapshot, "weak_topics_top3", ()) or ())
        weak_topics = tuple(str(t or "").strip() for t in weak_topics_raw if str(t or "").strip())
        current_topic = str(getattr(app_snapshot, "current_topic", "") or "").strip()
        if weak_topics and current_topic and any(current_topic.lower() == t.lower() for t in weak_topics):
            return "guided_practice", "weak_topic_focus"

        adapter_mode = self._choose_mode_from_adapter(app_snapshot)
        if adapter_mode is not None:
            return adapter_mode

        return "teach", "default_teach"

    def _cognitive_runtime_meta(self, request: TutorLoopTurnRequest) -> dict[str, Any]:
        raw = getattr(request, "meta", {}) or {}
        if not isinstance(raw, dict):
            return {}
        cog = raw.get("cognitive_runtime")
        if isinstance(cog, dict):
            return dict(cog)
        return {}

    def _choose_mode_from_cognitive(
        self,
        *,
        request: TutorLoopTurnRequest,
        app_snapshot: AppStateSnapshot,
    ) -> tuple[str, str] | None:
        cog = self._cognitive_runtime_meta(request)
        if not bool(cog.get("enabled", False)):
            return None
        if bool(cog.get("quiz_active", False)):
            return "guided_practice", "cognitive_quiz_active_guard"
        if bool(cog.get("struggle_mode", False)):
            return "guided_practice", "cognitive_struggle_mode"
        try:
            mean = float(cog.get("posterior_mean", 0.0) or 0.0)
        except Exception:
            mean = 0.0
        try:
            variance = float(cog.get("posterior_variance", 0.0) or 0.0)
        except Exception:
            variance = 0.0
        mean = max(0.0, min(1.0, mean))
        variance = max(0.0, min(1.0, variance))
        must_review_due = int(getattr(app_snapshot, "must_review_due", 0) or 0)
        overdue = int(getattr(app_snapshot, "overdue_srs_count", 0) or 0)
        if mean >= 0.82 and variance <= 0.035 and must_review_due <= 0 and overdue <= 0:
            return "retrieval_drill", "cognitive_high_mastery_low_variance"
        if mean <= 0.40 or variance >= 0.08:
            return "teach", "cognitive_low_mastery_or_high_variance"
        return None

    def _difficulty_hint_from_cognitive(self, cog: dict[str, Any], *, mode_used: str) -> str:
        if not bool(cog.get("enabled", False)):
            return ""
        if bool(cog.get("quiz_active", False)) or bool(cog.get("struggle_mode", False)):
            return "easier"
        try:
            mean = float(cog.get("posterior_mean", 0.0) or 0.0)
        except Exception:
            mean = 0.0
        try:
            variance = float(cog.get("posterior_variance", 0.0) or 0.0)
        except Exception:
            variance = 0.0
        mean = max(0.0, min(1.0, mean))
        variance = max(0.0, min(1.0, variance))
        if mode_used in {"retrieval_drill", "guided_practice"} and mean >= 0.80 and variance <= 0.04:
            return "harder"
        if mean <= 0.45 or variance >= 0.08:
            return "easier"
        return ""

    def _choose_mode_from_adapter(self, app_snapshot: AppStateSnapshot) -> tuple[str, str] | None:
        adapter = self.module_adapter
        if adapter is None:
            return None
        topic = str(getattr(app_snapshot, "current_topic", "") or "").strip()
        if not topic:
            return None
        try:
            mode = str(adapter.default_tutor_mode_for_topic(topic) or "").strip().lower()
        except Exception:
            return None
        if not mode or mode == "auto":
            return None
        try:
            supported = {str(x or "").strip().lower() for x in (adapter.supported_tutor_modes() or ()) if str(x or "").strip()}
        except Exception:
            supported = set()
        if supported and mode not in supported:
            return None
        return mode, "module_adapter_topic_default"

    def _choose_phase(
        self,
        *,
        mode: str,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> str:
        current_phase = str(getattr(session_state, "loop_phase", "observe") or "observe").strip().lower()
        if mode in {"teach", "exam_technique"}:
            if current_phase in {"teach", "practice"}:
                return "practice"
            return "teach"
        if mode in {"guided_practice", "retrieval_drill"}:
            return "practice"
        if mode == "section_c_coach":
            return "teach" if current_phase in {"observe", "diagnose"} else "practice"
        if mode == "error_clinic":
            metrics = self._learner_loop_metrics(learner_profile)
            thresholds = self._active_thresholds()
            if int(metrics.get("consecutive_correct", 0) or 0) >= max(1, int(thresholds.retrieval_min_streak)):
                return "practice"
            if tuple(getattr(learner_profile, "misconception_tags_top", ()) or ()):
                return "reinforce"
            return "teach"
        if mode == "revision_planner":
            if int(getattr(app_snapshot, "must_review_due", 0) or 0) > 0:
                return "switch"
            return "practice"
        return "diagnose"

    def _build_next_action_intent(
        self,
        *,
        request: TutorLoopTurnRequest,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
        mode_used: str,
        phase_after_turn: str,
    ) -> TutorActionIntent | None:
        autonomy_mode = str(getattr(request, "autonomy_mode", "assist") or "assist").strip().lower()
        current_topic = str(getattr(app_snapshot, "current_topic", "") or getattr(session_state, "topic", "") or "").strip()
        weak_topics = tuple(getattr(app_snapshot, "weak_topics_top3", ()) or ())
        must_review_due = int(getattr(app_snapshot, "must_review_due", 0) or 0)
        overdue = int(getattr(app_snapshot, "overdue_srs_count", 0) or 0)

        if mode_used == "revision_planner" and (must_review_due > 0 or overdue > 0):
            return TutorActionIntent(
                action="review_start",
                topic=current_topic,
                reason=f"Due review pressure detected ({must_review_due} must-review, {overdue} overdue).",
                confidence=0.86,
                requires_confirmation=(autonomy_mode == "assist"),
                priority="high",
                expected_outcome="Reduce due-review backlog before deeper teaching.",
                evidence=(
                    f"must_review_due={must_review_due}",
                    f"overdue_srs_count={overdue}",
                    f"phase={phase_after_turn}",
                ),
            )

        if mode_used in {"error_clinic", "guided_practice"} and weak_topics:
            weak_topic = str(weak_topics[0] or "").strip()
            if weak_topic:
                return TutorActionIntent(
                    action="drill_start",
                    topic=weak_topic,
                    duration_minutes=15,
                    reason="Targeted practice on the highest-priority weak topic.",
                    confidence=0.74,
                    requires_confirmation=(autonomy_mode != "cockpit"),
                    priority="normal",
                    expected_outcome="Generate corrective repetitions on current weakness.",
                    evidence=(
                        f"weak_topic_top={weak_topic}",
                        f"misconceptions={len(tuple(getattr(learner_profile, 'misconception_tags_top', ()) or ()))}",
                    ),
                )

        if mode_used == "retrieval_drill":
            return TutorActionIntent(
                action="quick_quiz_start",
                topic=current_topic,
                reason="User request and mode selection indicate retrieval practice.",
                confidence=0.7,
                requires_confirmation=(autonomy_mode != "cockpit"),
                priority="normal",
                expected_outcome="Fast retrieval check after explanation.",
                evidence=(f"mode={mode_used}", f"phase={phase_after_turn}"),
            )

        return None

    def _learner_loop_metrics(self, learner_profile: TutorLearnerProfileSnapshot) -> dict[str, Any]:
        meta = getattr(learner_profile, "meta", {}) or {}
        raw = meta.get("learning_loop_metrics", {}) if isinstance(meta, dict) else {}
        data = raw if isinstance(raw, dict) else {}
        try:
            assessments_total = max(0, int(data.get("assessments_total", 0) or 0))
        except Exception:
            assessments_total = 0
        try:
            correct_count = max(0, int(data.get("correct_count", 0) or 0))
        except Exception:
            correct_count = 0
        try:
            partial_count = max(0, int(data.get("partial_count", 0) or 0))
        except Exception:
            partial_count = 0
        try:
            incorrect_count = max(0, int(data.get("incorrect_count", 0) or 0))
        except Exception:
            incorrect_count = 0
        try:
            recurrence = max(0, int(data.get("misconception_recurrence_count", 0) or 0))
        except Exception:
            recurrence = 0
        try:
            streak_correct = max(0, int(data.get("consecutive_correct", 0) or 0))
        except Exception:
            streak_correct = 0
        try:
            streak_incorrect = max(0, int(data.get("consecutive_incorrect", 0) or 0))
        except Exception:
            streak_incorrect = 0
        try:
            score_ratio_ema = float(data.get("avg_score_ratio_ema", 0.0) or 0.0)
        except Exception:
            score_ratio_ema = 0.0
        try:
            confidence_bias_abs_ema = float(data.get("confidence_bias_abs_ema", 0.0) or 0.0)
        except Exception:
            confidence_bias_abs_ema = 0.0
        effective_correct = int(correct_count + partial_count)
        accuracy_like = (float(effective_correct) / float(assessments_total)) if assessments_total > 0 else 0.0
        return {
            "assessments_total": int(assessments_total),
            "correct_count": int(correct_count),
            "partial_count": int(partial_count),
            "incorrect_count": int(incorrect_count),
            "misconception_recurrence_count": int(recurrence),
            "consecutive_correct": int(streak_correct),
            "consecutive_incorrect": int(streak_incorrect),
            "avg_score_ratio_ema": max(0.0, min(1.0, float(score_ratio_ema))),
            "confidence_bias_abs_ema": max(0.0, min(5.0, float(confidence_bias_abs_ema))),
            "accuracy_like": max(0.0, min(1.0, float(accuracy_like))),
        }

    def _choose_mode_from_metrics(
        self,
        metrics: dict[str, Any],
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> tuple[str, str] | None:
        try:
            total = max(0, int(metrics.get("assessments_total", 0) or 0))
        except Exception:
            total = 0
        thresholds = self._active_thresholds()
        if total < max(1, int(thresholds.min_assessments_for_metrics)):
            return None

        must_review_due = int(getattr(app_snapshot, "must_review_due", 0) or 0)
        overdue = int(getattr(app_snapshot, "overdue_srs_count", 0) or 0)
        if (must_review_due + overdue) >= int(thresholds.review_pressure_guard_total):
            return None

        try:
            incorrect_count = max(0, int(metrics.get("incorrect_count", 0) or 0))
        except Exception:
            incorrect_count = 0
        try:
            recurrence = max(0, int(metrics.get("misconception_recurrence_count", 0) or 0))
        except Exception:
            recurrence = 0
        try:
            streak_incorrect = max(0, int(metrics.get("consecutive_incorrect", 0) or 0))
        except Exception:
            streak_incorrect = 0
        try:
            streak_correct = max(0, int(metrics.get("consecutive_correct", 0) or 0))
        except Exception:
            streak_correct = 0
        try:
            accuracy_like = max(0.0, min(1.0, float(metrics.get("accuracy_like", 0.0) or 0.0)))
        except Exception:
            accuracy_like = 0.0
        try:
            score_ema = max(0.0, min(1.0, float(metrics.get("avg_score_ratio_ema", 0.0) or 0.0)))
        except Exception:
            score_ema = 0.0
        try:
            confidence_bias_abs_ema = max(0.0, min(5.0, float(metrics.get("confidence_bias_abs_ema", 0.0) or 0.0)))
        except Exception:
            confidence_bias_abs_ema = 0.0

        incorrect_rate = (float(incorrect_count) / float(total)) if total > 0 else 0.0
        if (
            recurrence >= 2
            or streak_incorrect >= 2
            or incorrect_rate >= float(thresholds.error_incorrect_rate_threshold)
        ):
            return "error_clinic", "loop_metrics_recurrence_or_error_rate"

        transfer = float(getattr(learner_profile, "chat_to_quiz_transfer_score", 0.0) or 0.0)
        if (
            streak_correct >= max(1, int(thresholds.retrieval_min_streak))
            and accuracy_like >= float(thresholds.retrieval_correct_rate_threshold)
            and score_ema >= float(thresholds.retrieval_score_ema_min)
            and transfer >= -0.1
        ):
            if confidence_bias_abs_ema > float(thresholds.calibration_bias_guard):
                return "guided_practice", "loop_metrics_progress_but_calibration_off"
            return "retrieval_drill", "loop_metrics_progress_ready_for_retrieval"
        return None

    def _active_thresholds(self) -> TutorLoopPolicyThresholds:
        cached = self._last_tuned_thresholds
        if isinstance(cached, TutorLoopPolicyThresholds):
            return cached.clamped()
        base = self.policy_thresholds if isinstance(self.policy_thresholds, TutorLoopPolicyThresholds) else TutorLoopPolicyThresholds()
        return base.clamped()

    def _refresh_tuned_thresholds(
        self,
        *,
        learner_profile: TutorLearnerProfileSnapshot,
        app_snapshot: AppStateSnapshot,
    ) -> TutorLoopPolicyThresholds:
        base = self.policy_thresholds if isinstance(self.policy_thresholds, TutorLoopPolicyThresholds) else TutorLoopPolicyThresholds()
        base = base.clamped()
        metrics = self._learner_loop_metrics(learner_profile)
        tuner = self.policy_tuning_service
        if tuner is None:
            self._last_tuned_thresholds = base
            self._last_tuning_meta = {"status": "disabled", "reason": "no_tuner"}
            return base
        try:
            tuned, meta = tuner.tune(
                base_thresholds=base,
                loop_metrics=metrics,
                learner_profile=learner_profile,
                app_snapshot=app_snapshot,
            )
        except Exception:
            tuned, meta = base, {"status": "error", "reason": "tuner_exception"}
        self._last_tuned_thresholds = tuned.clamped()
        self._last_tuning_meta = dict(meta or {})
        return self._last_tuned_thresholds

    def get_active_policy_thresholds(self) -> dict[str, float | int]:
        return self._active_thresholds().to_dict()

    def get_policy_tuning_meta(self) -> dict[str, object]:
        return dict(self._last_tuning_meta or {})

    def _build_response_plan_text(
        self,
        *,
        request: TutorLoopTurnRequest,
        session_state: TutorSessionState,
        learner_profile: TutorLearnerProfileSnapshot,
        mode_used: str,
        phase_after_turn: str,
        mode_reason: str,
        practice_items: tuple[TutorPracticeItem, ...],
        action_intent: TutorActionIntent | None,
    ) -> str:
        topic = str(getattr(session_state, "topic", "") or getattr(request.app_snapshot, "current_topic", "") or "current topic")
        lines = [
            f"Planner mode: {mode_used}",
            f"Loop phase: {phase_after_turn}",
            f"Topic: {topic}",
            f"Reason: {mode_reason}",
        ]
        misconceptions = tuple(getattr(learner_profile, "misconception_tags_top", ()) or ())
        if misconceptions:
            lines.append("Misconceptions: " + ", ".join(misconceptions[:3]))
        if practice_items:
            labels = [f"{item.item_type}:{item.item_id}" for item in practice_items[:3]]
            lines.append("Practice queued: " + ", ".join(labels))
        if action_intent is not None:
            action_topic = str(getattr(action_intent, "topic", "") or "").strip()
            action_display = str(action_intent.action or "")
            if action_topic:
                action_display += f" ({action_topic})"
            lines.append(f"Suggested action: {action_display}")
        return "\n".join(lines)
