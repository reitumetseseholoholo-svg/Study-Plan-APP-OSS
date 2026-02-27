"""AI-based question generation service.

Provides an abstraction over whatever secondary backend (RAG, LLM, etc.)
is used to auto-produce practice questions from high-level prompts or source
material.  The framework is lightweight and easy to replace with real AI
calls later.
"""

from __future__ import annotations

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


# helper factory

def get_qgen_service() -> QGenService:
    """Return an instance of QGenService to use at runtime.

    This could inspect config/env to pick real vs dummy implementation.
    """
    # for now return dummy; later switch via Config flag
    return DummyQGenService()
