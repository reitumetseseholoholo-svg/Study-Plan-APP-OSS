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
    out = f"{prefix}: {detail}".strip()
    if str(kind or "").strip().lower() in {"conn_refused", "host_unreachable"}:
        out += " Start Ollama with: ollama serve"
    return out


def summarize_recovery(error_code: str, message: str, model: str = "") -> dict[str, Any]:
    kind = classify_failure_kind(error_code, message)
    sequence = build_recovery_sequence(kind)
    return {
        "failure_kind": kind,
        "recovery_sequence": sequence,
        "hint": recovery_hint_text(kind, sequence, model=model),
    }


def build_deterministic_fallback_response(
    *,
    error_code: str,
    message: str = "",
    model: str = "",
    topic_hint: str = "",
) -> dict[str, Any]:
    """Build a stable tutor fallback payload with machine-readable metadata."""
    normalized_code = str(error_code or "unknown_error").strip().lower() or "unknown_error"
    safe_topic = str(topic_hint or "").strip() or "current topic"
    recovery = summarize_recovery(normalized_code, message, model=model)
    failure_kind = str(recovery.get("failure_kind", "unknown") or "unknown")
    fallback_code = f"fallback_{failure_kind}"
    lead_by_kind = {
        "timeout": "Tutor response is temporarily unavailable.",
        "conn_refused": "Tutor response is temporarily unavailable.",
        "stream_stall": "Tutor response is temporarily unavailable.",
        "model_unavailable": "Tutor model is temporarily unavailable.",
        "invalid_output": "Tutor response is temporarily unavailable.",
        "context_overflow": "Tutor response is temporarily unavailable.",
    }
    lead = str(lead_by_kind.get(failure_kind, "Tutor response is temporarily unavailable."))
    text = (
        f"{lead} "
        f"Here is a quick practice step while I reconnect on {safe_topic}: "
        "write one key idea, one formula or rule, and one short exam-style application."
    )
    return {
        "text": text,
        "error_code": normalized_code,
        "fallback_code": fallback_code,
        "failure_kind": failure_kind,
        "recovery_sequence": list(recovery.get("recovery_sequence", []) or []),
        "hint": str(recovery.get("hint", "") or ""),
        "recovery": recovery,
    }
