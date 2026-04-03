"""AI-based question generation service.

Provides an abstraction over whatever secondary backend (RAG, LLM, etc.)
is used to auto-produce practice questions from high-level prompts or source
material.

Two concrete implementations are provided:

* ``OllamaQGenService`` — calls the local Ollama ``/api/generate`` endpoint
  and parses numbered question text from the response.  Falls back to an
  empty list gracefully when Ollama is not reachable so the practice loop
  is never disrupted.

* ``DummyQGenService`` — template-based fallback used in tests or when you
  explicitly need deterministic output.

``get_qgen_service()`` returns an ``OllamaQGenService`` instance configured
from the app's ``Config``.  Inject a ``DummyQGenService`` (or any custom
``QGenService`` implementation) when you need deterministic output in tests.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol, List

from .logging_config import get_logger

logger = get_logger(__name__)


class QGenService(Protocol):
    """Protocol for question generation backends."""

    def generate_questions(
        self,
        *,
        topic: str,
        source_text: str | None = None,
        count: int = 5,
    ) -> List[str]:
        ...


class DummyQGenService:
    """Template-based fallback; deterministic output for tests.

    Use this when you need predictable question text without a running LLM.
    """

    def generate_questions(
        self,
        *,
        topic: str,
        source_text: str | None = None,
        count: int = 5,
    ) -> List[str]:
        questions: List[str] = []
        base = source_text or topic
        for i in range(count):
            questions.append(f"[{topic}] Auto-generated question {i+1} based on {base}.")
        logger.debug("dummy questions generated", extra={"topic": topic, "count": count})
        return questions


class OllamaQGenService:
    """QGenService backed by a local Ollama instance.

    Calls the Ollama native ``/api/generate`` endpoint with ``stream=false``
    to get a complete text response in one shot, then extracts numbered
    questions from it.

    If Ollama is not running or returns an unexpected payload the method
    returns an empty list so the practice loop degrades gracefully.
    """

    DEFAULT_HOST = "http://127.0.0.1:11434"
    DEFAULT_MODEL = "llama3.2"
    DEFAULT_TIMEOUT_SECONDS = 30.0
    MIN_TIMEOUT_SECONDS = 5.0
    MIN_QUESTION_LENGTH = 10

    def __init__(
        self,
        *,
        host: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        raw_host = str(host or os.getenv("OLLAMA_HOST", "") or self.DEFAULT_HOST).strip()
        self.host = raw_host.rstrip("/")
        self.model = str(model or self.DEFAULT_MODEL).strip() or self.DEFAULT_MODEL
        self.timeout_seconds = max(self.MIN_TIMEOUT_SECONDS, float(timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS))

    def _build_prompt(self, *, topic: str, source_text: str | None, count: int) -> str:
        context = str(source_text or "").strip() or topic
        return (
            f"Generate {count} concise study questions about the topic '{topic}'.\n"
            f"Context material: {context}\n"
            f"Output only the questions, each on its own line, numbered 1 to {count}. "
            f"Do not include answers, options, or explanations—only the question text."
        )

    def _parse_questions(self, text: str, count: int) -> List[str]:
        questions: List[str] = []
        for line in str(text or "").splitlines():
            stripped = re.sub(r"^\s*\d+[\.\)\-]\s*", "", line).strip()
            if len(stripped) >= self.MIN_QUESTION_LENGTH:
                questions.append(stripped)
            if len(questions) >= count:
                break
        return questions

    def generate_questions(
        self,
        *,
        topic: str,
        source_text: str | None = None,
        count: int = 5,
    ) -> List[str]:
        prompt = self._build_prompt(topic=topic, source_text=source_text, count=count)
        url = f"{self.host}/api/generate"
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning(
                "OllamaQGenService: request failed, returning empty list",
                extra={"url": url, "model": self.model, "error": str(exc)},
            )
            return []
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning(
                "OllamaQGenService: could not parse JSON response",
                extra={"url": url, "model": self.model},
            )
            return []
        response_text = str(data.get("response", "") or "").strip()
        if not response_text:
            logger.warning(
                "OllamaQGenService: empty response text from model",
                extra={"model": self.model},
            )
            return []
        questions = self._parse_questions(response_text, count)
        logger.debug(
            "OllamaQGenService: questions generated",
            extra={"model": self.model, "topic": topic, "count": len(questions)},
        )
        return questions


# helper factory

def get_qgen_service() -> QGenService:
    """Return the runtime QGenService instance.

    Returns an ``OllamaQGenService`` configured from ``Config``.  The service
    falls back gracefully to an empty list when Ollama is not reachable, so
    callers never need to handle connection errors.

    Inject ``DummyQGenService`` (or another implementation) explicitly when
    you need deterministic output in tests.
    """
    try:
        from .config import Config

        host = str(getattr(Config, "LLAMA_CPP_OLLAMA_HOST", "") or "").strip()
        if not host:
            host = os.getenv("OLLAMA_HOST", OllamaQGenService.DEFAULT_HOST)
        model = str(getattr(Config, "LLAMA_CPP_MODEL", "") or "").strip()
        if not model:
            model = OllamaQGenService.DEFAULT_MODEL
    except Exception:
        host = os.getenv("OLLAMA_HOST", OllamaQGenService.DEFAULT_HOST)
        model = OllamaQGenService.DEFAULT_MODEL
    return OllamaQGenService(host=host, model=model)
