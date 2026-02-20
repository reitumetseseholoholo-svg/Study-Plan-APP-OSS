from __future__ import annotations

from typing import Protocol

from .contracts import (
    AutopilotDecision,
    AutopilotExecutionResult,
    RagQueryRequest,
    RagQueryResult,
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
