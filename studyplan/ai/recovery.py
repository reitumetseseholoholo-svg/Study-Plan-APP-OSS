from __future__ import annotations

from typing import Any


def classify_failure_kind(error_code: str, message: str) -> str:
    code = str(error_code or "").strip().lower()
    lower = str(message or "").strip().lower()
    if code in {"host_unreachable"}:
        return "conn_refused"
    if code in {"model_missing", "endpoint_missing"}:
        return "model_unavailable"
    if code in {"timeout", "busy"}:
        return "timeout"
    if "cooldown active" in lower or "runtime busy" in lower or "queue wait exceeded" in lower:
        return "timeout"
    if "json parse failed" in lower or "guardrail validation failed" in lower or "valid json" in lower:
        return "invalid_output"
    if "context" in lower and ("overflow" in lower or "length" in lower or "token" in lower):
        return "context_overflow"
    if "stall" in lower:
        return "stream_stall"
    return "unknown"


def build_recovery_sequence(kind: str) -> list[str]:
    failure = str(kind or "unknown").strip().lower()
    steps = ["retry_same_model"]
    if failure == "invalid_output":
        steps.append("retry_strict_json")
    if failure in {"timeout", "stream_stall", "context_overflow"}:
        steps.append("reduce_context")
    if failure in {"timeout", "context_overflow"}:
        steps.append("disable_semantic")
    steps.append("switch_model")
    steps.append("concise_fallback")
    return steps


def recovery_hint_text(kind: str, sequence: list[str], model: str = "") -> str:
    action_lines: dict[str, str] = {
        "retry_same_model": "Retrying once on the same model.",
        "retry_strict_json": "Retrying with stricter JSON guardrails.",
        "reduce_context": "Reducing context budget for this turn.",
        "disable_semantic": "Temporarily disabling semantic retrieval for this turn.",
        "switch_model": "Switching to the next ranked local model.",
        "concise_fallback": "Falling back to concise mode if all retries fail.",
    }
    cleaned = [str(step).strip().lower() for step in list(sequence or []) if str(step).strip()]
    detail = " ".join(action_lines.get(step, step) for step in cleaned)
    prefix = f"Recovery ({kind})"
    if str(model or "").strip():
        prefix = f"Recovery ({kind}, model={model})"
    return f"{prefix}: {detail}".strip()


def summarize_recovery(error_code: str, message: str, model: str = "") -> dict[str, Any]:
    kind = classify_failure_kind(error_code, message)
    sequence = build_recovery_sequence(kind)
    return {
        "failure_kind": kind,
        "recovery_sequence": sequence,
        "hint": recovery_hint_text(kind, sequence, model=model),
    }
