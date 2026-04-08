"""AI-based question generation service.

Provides an abstraction over whatever secondary backend (RAG, LLM, etc.)
is used to auto-produce practice questions from high-level prompts or source
material.

Two concrete implementations are provided for the plain-string protocol:

* ``OllamaQGenService`` — calls the local Ollama ``/api/generate`` endpoint
  and parses numbered question text from the response.  Falls back to an
  empty list gracefully when Ollama is not reachable so the practice loop
  is never disrupted.

* ``DummyQGenService`` — template-based fallback used in tests or when you
  explicitly need deterministic output.

``get_qgen_service()`` returns an ``OllamaQGenService`` instance configured
from the app's ``Config``.  Inject a ``DummyQGenService`` (or any custom
``QGenService`` implementation) when you need deterministic output in tests.

Multi-agent workflow
--------------------
Use :class:`AgentOrchestrator` to run one :class:`QGenAgent` per chapter in
parallel and merge their outputs into the app-ready JSON import format::

    from studyplan.question_generator import AgentOrchestrator, DummyStructuredQGenService

    svc = DummyStructuredQGenService()
    orchestrator = AgentOrchestrator(service=svc, max_workers=4)
    merged = orchestrator.generate_for_chapters(
        chapters=["Chapter 1: IFRS", "Chapter 2: Conceptual Framework"],
        count_per_chapter=5,
    )
    # merged is a dict ready for studyplan_engine.import_questions_from_json()
    orchestrator.save_merged_output(merged, "/tmp/questions.json")
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import urllib.request
from typing import Protocol, List, TypedDict

from .logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Legacy plain-string protocol (kept for backward compatibility)
# ---------------------------------------------------------------------------

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
    """Fallback service that creates templated questions.

    Used for testing or when no real backend is available.
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


# ---------------------------------------------------------------------------
# Structured question format (matches app JSON import schema)
# ---------------------------------------------------------------------------

class StructuredQuestion(TypedDict):
    """A single question in the app-ready import format.

    Matches the JSON schema consumed by
    :meth:`studyplan_engine.StudyPlanEngine.import_questions_from_json`.
    """

    question: str
    options: List[str]
    correct: str
    explanation: str


# ---------------------------------------------------------------------------
# Structured question generation protocol
# ---------------------------------------------------------------------------

class StructuredQGenService(Protocol):
    """Protocol for backends that produce fully structured question objects."""

    def generate_structured_questions(
        self,
        *,
        topic: str,
        source_text: str | None = None,
        count: int = 5,
    ) -> List[StructuredQuestion]:
        ...


class DummyStructuredQGenService:
    """Fallback structured service for testing or when no real backend is available.

    Produces syntactically valid :class:`StructuredQuestion` objects that pass
    the engine's import validation checks.
    """

    def generate_structured_questions(
        self,
        *,
        topic: str,
        source_text: str | None = None,
        count: int = 5,
    ) -> List[StructuredQuestion]:
        questions: List[StructuredQuestion] = []
        base = source_text or topic
        for i in range(count):
            q_text = f"[{topic}] Auto-generated question {i + 1} based on: {base}."
            opts = [
                f"Option A for question {i + 1}",
                f"Option B for question {i + 1}",
                f"Option C for question {i + 1}",
                f"Option D for question {i + 1}",
            ]
            questions.append(
                StructuredQuestion(
                    question=q_text,
                    options=opts,
                    correct=opts[0],
                    explanation=(
                        f"Option A is correct for question {i + 1} on '{topic}'."
                    ),
                )
            )
        logger.debug(
            "dummy structured questions generated",
            extra={"topic": topic, "count": count},
        )
        return questions


def get_structured_qgen_service() -> StructuredQGenService:
    """Return a :class:`StructuredQGenService` instance for runtime use.

    Swap this out for a real LLM/RAG implementation via a Config flag.
    """
    return DummyStructuredQGenService()


# ---------------------------------------------------------------------------
# Single-chapter agent
# ---------------------------------------------------------------------------

class QGenAgent:
    """Generates structured questions for a single chapter or topic.

    Each agent is independent and safe to run in a thread.  Call
    :meth:`run` to produce a ``{chapter: [questions]}`` dict fragment.
    """

    def __init__(
        self,
        chapter: str,
        service: StructuredQGenService,
        count: int = 5,
        source_text: str | None = None,
    ) -> None:
        self.chapter = chapter
        self.service = service
        self.count = count
        self.source_text = source_text

    def run(self) -> dict[str, List[StructuredQuestion]]:
        """Run question generation and return a single-chapter result dict."""
        logger.info(
            "agent starting question generation",
            extra={"chapter": self.chapter, "count": self.count},
        )
        questions = self.service.generate_structured_questions(
            topic=self.chapter,
            source_text=self.source_text,
            count=self.count,
        )
        logger.info(
            "agent finished question generation",
            extra={"chapter": self.chapter, "generated": len(questions)},
        )
        return {self.chapter: questions}


# ---------------------------------------------------------------------------
# Orchestrator – runs agents in parallel and merges output
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """Runs one :class:`QGenAgent` per chapter in parallel and merges results.

    The merged output is a ``dict[chapter_name, list[StructuredQuestion]]``
    which is directly importable via
    :meth:`studyplan_engine.StudyPlanEngine.import_questions_from_json`.

    Example::

        orchestrator = AgentOrchestrator(service=DummyStructuredQGenService())
        merged = orchestrator.generate_for_chapters(
            ["Chapter 1: IFRS", "Chapter 2: Conceptual Framework"],
            count_per_chapter=5,
        )
        orchestrator.save_merged_output(merged, "/tmp/out.json")
    """

    def __init__(
        self,
        service: StructuredQGenService,
        max_workers: int = 4,
    ) -> None:
        self.service = service
        self.max_workers = max_workers

    def generate_for_chapters(
        self,
        chapters: List[str],
        count_per_chapter: int = 5,
        source_texts: dict[str, str] | None = None,
    ) -> dict[str, List[StructuredQuestion]]:
        """Generate questions for every chapter, running agents in parallel.

        Args:
            chapters: Ordered list of chapter names.
            count_per_chapter: How many questions each agent should produce.
            source_texts: Optional mapping of chapter → source material string
                passed through to the underlying service.

        Returns:
            Merged ``{chapter_name: [StructuredQuestion, ...]}`` dict ready
            for JSON serialisation and engine import.
        """
        if not chapters:
            return {}

        agents = [
            QGenAgent(
                chapter=ch,
                service=self.service,
                count=count_per_chapter,
                source_text=(source_texts or {}).get(ch),
            )
            for ch in chapters
        ]

        merged: dict[str, List[StructuredQuestion]] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            future_to_chapter = {
                executor.submit(agent.run): agent.chapter for agent in agents
            }
            for future in concurrent.futures.as_completed(future_to_chapter):
                chapter = future_to_chapter[future]
                try:
                    result = future.result()
                    merged.update(result)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "agent failed, skipping chapter",
                        extra={"chapter": chapter, "error": str(exc)},
                    )

        # Restore insertion order so the output matches the input chapter list.
        ordered: dict[str, List[StructuredQuestion]] = {
            ch: merged[ch] for ch in chapters if ch in merged
        }
        logger.info(
            "orchestrator merged agent outputs",
            extra={
                "chapters_requested": len(chapters),
                "chapters_completed": len(ordered),
                "total_questions": sum(len(v) for v in ordered.values()),
            },
        )
        return ordered

    @staticmethod
    def save_merged_output(
        merged: dict[str, List[StructuredQuestion]],
        path: str,
    ) -> None:
        """Serialise *merged* to *path* as a pretty-printed JSON file.

        The resulting file is immediately importable by the engine via
        ``import_questions_from_json(path)``.
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2, ensure_ascii=False)
        logger.info("merged question output saved", extra={"path": path})

