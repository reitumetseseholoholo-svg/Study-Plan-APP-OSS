from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


InferenceStreamCallback = Callable[[str], None]


@dataclass(frozen=True)
class InferenceResult:
    backend: str
    text: str
    error: str | None = None
    model_used: str = ""


class InferenceBackend(Protocol):
    name: str

    def health(self) -> tuple[bool, str | None]:
        ...

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: int,
        temperature: float = 0.2,
        num_ctx: int | None = None,
    ) -> InferenceResult:
        ...

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
        ...

