from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from .backends import InferenceResult, InferenceStreamCallback


def _normalize_host(raw: str) -> str:
    host = str(raw or "").strip()
    if not host:
        host = "http://127.0.0.1:8080"
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _load_model_map_env() -> dict[str, str]:
    raw = str(os.environ.get("STUDYPLAN_LLAMACPP_MODEL_MAP", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    mapped: dict[str, str] = {}
    for key, value in payload.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k and v:
            mapped[k] = v
    return mapped


class LlamaCppBackend:
    name = "llamacpp"

    def __init__(
        self,
        *,
        host: str | None = None,
        model_map: dict[str, str] | None = None,
        endpoint: str = "/v1/chat/completions",
    ) -> None:
        self.host = _normalize_host(host or os.environ.get("STUDYPLAN_LLAMACPP_HOST", ""))
        self.endpoint = str(endpoint or "/v1/chat/completions").strip() or "/v1/chat/completions"
        self.model_map = dict(model_map or _load_model_map_env())

    def _map_model(self, model: str) -> str:
        model_name = str(model or "").strip()
        return str(self.model_map.get(model_name, model_name))

    def health(self) -> tuple[bool, str | None]:
        url = f"{self.host}/health"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                code = int(getattr(resp, "status", 200) or 200)
            return (200 <= code < 300), (None if 200 <= code < 300 else f"HTTP {code}")
        except Exception as exc:
            return False, str(exc)

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: int,
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> InferenceResult:
        mapped_model = self._map_model(model)
        payload: dict[str, Any] = {
            "model": mapped_model,
            "messages": [{"role": "user", "content": str(prompt or "")}],
            "temperature": float(max(0.0, min(1.0, float(temperature)))),
            "stream": False,
        }
        if num_ctx is not None:
            try:
                payload["n_ctx"] = int(max(256, int(num_ctx)))
            except Exception:
                pass
        url = f"{self.host}{self.endpoint}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=float(max(5, int(timeout_seconds)))) as resp:
                raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return InferenceResult(backend=self.name, text="", error="invalid response", model_used=mapped_model)
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message", {})
                    if isinstance(message, dict):
                        text = str(message.get("content", "") or "")
                        if text.strip():
                            return InferenceResult(backend=self.name, text=text, error=None, model_used=mapped_model)
            text = str(data.get("content", "") or data.get("response", "") or "")
            if text.strip():
                return InferenceResult(backend=self.name, text=text, error=None, model_used=mapped_model)
            return InferenceResult(backend=self.name, text="", error="empty response", model_used=mapped_model)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace").strip()
            except Exception:
                detail = ""
            msg = f"HTTP {exc.code}"
            if detail:
                msg = f"{msg}: {detail}"
            return InferenceResult(backend=self.name, text="", error=msg, model_used=mapped_model)
        except Exception as exc:
            return InferenceResult(backend=self.name, text="", error=str(exc), model_used=mapped_model)

    def generate_stream(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: int,
        on_chunk: InferenceStreamCallback | None = None,
        cancel_check: Callable[[], bool] | None = None,
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> InferenceResult:
        mapped_model = self._map_model(model)
        payload: dict[str, Any] = {
            "model": mapped_model,
            "messages": [{"role": "user", "content": str(prompt or "")}],
            "temperature": float(max(0.0, min(1.0, float(temperature)))),
            "stream": True,
        }
        if num_ctx is not None:
            try:
                payload["n_ctx"] = int(max(256, int(num_ctx)))
            except Exception:
                pass
        url = f"{self.host}{self.endpoint}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream, application/json"},
            method="POST",
        )
        chunks: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=float(max(5, int(timeout_seconds)))) as resp:
                while True:
                    if callable(cancel_check) and bool(cancel_check()):
                        return InferenceResult(
                            backend=self.name,
                            text="".join(chunks),
                            error="cancelled",
                            model_used=mapped_model,
                        )
                    raw_line = resp.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue
                    choices = data.get("choices")
                    piece = ""
                    if isinstance(choices, list) and choices:
                        first = choices[0]
                        if isinstance(first, dict):
                            delta = first.get("delta", {})
                            if isinstance(delta, dict):
                                piece = str(delta.get("content", "") or "")
                            if not piece:
                                message = first.get("message", {})
                                if isinstance(message, dict):
                                    piece = str(message.get("content", "") or "")
                    if not piece:
                        piece = str(data.get("content", "") or data.get("response", "") or "")
                    if piece:
                        chunks.append(piece)
                        if callable(on_chunk):
                            try:
                                on_chunk(piece)
                            except Exception:
                                pass
            return InferenceResult(backend=self.name, text="".join(chunks), error=None, model_used=mapped_model)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace").strip()
            except Exception:
                detail = ""
            msg = f"HTTP {exc.code}"
            if detail:
                msg = f"{msg}: {detail}"
            return InferenceResult(backend=self.name, text="".join(chunks), error=msg, model_used=mapped_model)
        except Exception as exc:
            return InferenceResult(backend=self.name, text="".join(chunks), error=str(exc), model_used=mapped_model)

