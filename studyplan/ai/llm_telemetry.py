"""Unified LLM job / turn purpose labels for telemetry (Phase 0 roadmap).

Provides purpose label normalization and a shared telemetry field registry
that both telemetry paths (embedded + popup) and the sanitizer validate
against, preventing prompt/telemetry semantic drift.
"""

from __future__ import annotations

import re
from typing import Any, Final

# Stable purpose strings stored on each telemetry row (`purpose` field).
PURPOSE_TUTOR_EMBEDDED: Final[str] = "tutor_embedded"
PURPOSE_TUTOR_POPUP: Final[str] = "tutor_popup"
PURPOSE_COACH: Final[str] = "coach_turn"
PURPOSE_AUTOPILOT: Final[str] = "autopilot_decide"
PURPOSE_GAP_GEN: Final[str] = "gap_gen"
PURPOSE_SECTION_C: Final[str] = "section_c_gen"
PURPOSE_SYLLABUS: Final[str] = "syllabus_ai"
PURPOSE_UNKNOWN: Final[str] = "unknown"

_ALLOWED_PURPOSE_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

# ── Telemetry Field Registry ────────────────────────────────────────────────
# Single source of truth for all telemetry payload fields. Both payload
# builders (embedded in studyplan_app.py, popup in studyplan_ai_tutor.py)
# and the sanitizer validate against this registry. Adding a new field
# requires an entry here — otherwise it will be stripped by the sanitizer.

_T = type  # convenience alias

TELEMETRY_FIELD_DEFS: Final[dict[str, dict[str, Any]]] = {
    # ── Identity ───────────────────────────────────────────────────────────
    "model": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": True,
        "description": "Model identifier credited for the turn",
        "clamp_str": 120,
    },
    "actual_model": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "Actual model that produced the response after provider fallback; empty if same as 'model'",
        "clamp_str": 120,
    },
    "outcome": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": True,
        "description": "success / cancelled / error / parse_retry",
        "allowed": ("success", "cancelled", "error", "parse_retry"),
    },
    "error_class": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "Machine-readable error label (timeout, cancelled, busy, etc.)",
        "clamp_str": 40,
    },
    "purpose": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": True,
        "description": "tutor_embedded / tutor_popup / coach_turn / autopilot_decide / gap_gen / section_c_gen / syllabus_ai",
    },
    "effective_topic": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "Chapter context at decision time",
        "clamp_str": 200,
    },
    "module_id": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "ACCA module identifier (FM, AA, etc.)",
        "clamp_str": 80,
    },
    "pedagogical_mode": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "teach / practice / revision / exam_technique / freeform — from prompt assembly",
        "clamp_str": 32,
    },
    "prompt_contract_version": {
        "type": int,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "AI_TUTOR_PROMPT_CONTRACT_VERSION at turn time",
        "clamp": (0, 99999),
    },
    "learning_context_fp": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "SHA-1 fingerprint of learning context block",
        "clamp_str": 64,
    },
    "learning_context_omitted": {
        "type": int,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "1 if learning context was omitted",
        "clamp": (0, 1),
    },
    # ── Autopilot state ────────────────────────────────────────────────────
    "autopilot_mode": {
        "type": str,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "suggest / assist / cockpit",
    },
    "autopilot_decision_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100000)},
    "autopilot_action_executed_count": {
        "type": int,
        "paths": ("embedded", "popup"),
        "required": False,
        "clamp": (0, 100000),
    },
    "autopilot_action_blocked_count": {
        "type": int,
        "paths": ("embedded", "popup"),
        "required": False,
        "clamp": (0, 100000),
    },
    "autopilot_last_block_reason": {"type": str, "paths": ("embedded", "popup"), "required": False, "clamp_str": 200},
    "nudge_info_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100000)},
    "nudge_warning_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100000)},
    "nudge_intervention_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100000)},
    # ── Timing ─────────────────────────────────────────────────────────────
    "latency_ms": {
        "type": int,
        "paths": ("embedded", "popup"),
        "required": True,
        "description": "Wall-clock ms for the full turn",
        "clamp": (0, 3600000),
    },
    "queue_ms": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 3600000)},
    "prompt_build_ms": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 3600000)},
    "rag_ms": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 3600000)},
    "generation_ms": {
        "type": int,
        "paths": ("embedded", "popup"),
        "required": True,
        "description": "Wall-clock ms from LLM inference start to completion",
        "clamp": (0, 3600000),
    },
    "stream_ms": {
        "type": int,
        "paths": ("embedded", "popup"),
        "required": False,
        "description": "Wall-clock ms from first token arrival to stream completion; must be <= generation_ms",
        "clamp": (0, 3600000),
    },
    "model_first_token_ms": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 3600000)},
    "timeout_seconds": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (10, 600)},
    "timeout_hit": {"type": bool, "paths": ("embedded", "popup"), "required": False},
    "truncated": {"type": bool, "paths": ("embedded", "popup"), "required": False},
    # ── Latency profile (popup only) ───────────────────────────────────────
    "latency_p50_ms": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 3600000)},
    "latency_p90_ms": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 3600000)},
    "latency_spread_ratio": {"type": float, "paths": ("popup",), "required": False, "clamp": (1.0, 20.0)},
    "latency_load_level": {"type": str, "paths": ("popup",), "required": False, "clamp_str": 16},
    "latency_slo_status": {"type": str, "paths": ("popup",), "required": False, "clamp_str": 16},
    # ── Prompt / Response ──────────────────────────────────────────────────
    "prompt_chars": {"type": int, "paths": ("embedded", "popup"), "required": True, "clamp": (0, 500000)},
    "response_chars": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 500000)},
    "prompt_tokens_est": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 200000)},
    "response_tokens_est": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 200000)},
    # ── RAG ────────────────────────────────────────────────────────────────
    "rag_snippets": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100)},
    "rag_sources": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 50)},
    "rag_candidate_count": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 500)},
    "rag_selected_total_count": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 500)},
    "rag_char_used": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 10000)},
    "rag_char_budget": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 10000)},
    "rag_top_k_target": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 64)},
    "rag_neighbor_window": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 8)},
    "rag_doc_cache_hit": {"type": int, "paths": ("embedded",), "required": False, "clamp": (0, 1000)},
    "rag_query_cache_hit": {"type": int, "paths": ("embedded",), "required": False, "clamp": (0, 1000)},
    "rag_insufficient_flag": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 1)},
    "rag_source_mix": {"type": str, "paths": ("embedded", "popup"), "required": False, "clamp_str": 120},
    "rag_target_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 1000)},
    "rag_target_hit_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 1000)},
    # ── Embedding cache (embedded only) ────────────────────────────────────
    "embedding_cache_hits": {"type": int, "paths": ("embedded",), "required": False, "clamp": (0, 10000)},
    "embedding_cache_misses": {"type": int, "paths": ("embedded",), "required": False, "clamp": (0, 10000)},
    # ── Prompt/response cache (popup only) ─────────────────────────────────
    "prompt_cache_hit": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 10000)},
    "response_cache_hit": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 10000)},
    "token_est_cache_hit": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 10000)},
    "model_stats_persisted": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 10000)},
    # ── Context ────────────────────────────────────────────────────────────
    "ctx_chars": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 10000)},
    "ctx_budget_chars": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 10000)},
    "ctx_tokens_est": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 5000)},
    "ctx_dropped_sections_count": {
        "type": int,
        "paths": ("popup", "embedded"),
        "required": False,
        "clamp": (0, 50),
    },
    "ctx_horizon_days": {
        "type": int,
        "paths": ("popup", "embedded"),
        "required": False,
        "clamp": (1, 90),
    },
    "context_condensed_turns": {"type": int, "paths": ("popup",), "required": False, "clamp": (0, 200)},
    # ── Coverage ───────────────────────────────────────────────────────────
    "coverage_target_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 1000)},
    "coverage_hit_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 1000)},
    # ── Gap generation ─────────────────────────────────────────────────────
    "gap_q_generated_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100000)},
    "gap_q_saved_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100000)},
    "gap_q_quarantined_count": {"type": int, "paths": ("embedded", "popup"), "required": False, "clamp": (0, 100000)},
    # ── Prefilter (embedded only) ──────────────────────────────────────────
    "prefilter_kept": {"type": int, "paths": ("embedded",), "required": False, "clamp": (0, 20000)},
    # ── Autopilot skip reason counts ───────────────────────────────────────
    "autopilot_skip_reason_counts": {"type": dict, "paths": ("embedded", "popup"), "required": False},
}

# Fields that must satisfy numeric relationships (post-sanitization assertions).
NUMERIC_INVARIANTS: Final[list[dict[str, Any]]] = [
    {
        "gte": ("generation_ms", "stream_ms"),
        "description": "generation must be >= streaming time (streaming starts after first token)",
    },
    {
        "lte": ("stream_ms", "generation_ms"),
        "description": "streaming time must be <= generation time",
    },
    {
        "gte": ("latency_ms", "generation_ms"),
        "description": "total latency must be >= generation time (latency includes prompt build + RAG)",
    },
]


def validate_telemetry_payload(
    payload: dict[str, Any],
    path: str = "embedded",
    *,
    strict: bool = False,
) -> list[str]:
    """Validate a telemetry payload against the shared field registry.

    Returns a list of validation messages (empty = valid).
    In non-strict mode, unknown fields are allowed (not an error).
    In strict mode, unknown fields produce a warning message.

    Checks performed:
    - Required fields present
    - Field types match registry
    - Numeric invariants hold (generation_ms >= stream_ms, etc.)
    """
    messages: list[str] = []
    known_keys = set(TELEMETRY_FIELD_DEFS)

    # Check required fields
    for key, spec in TELEMETRY_FIELD_DEFS.items():
        if spec.get("required") and path in spec.get("paths", ()):
            if key not in payload:
                messages.append(f"required field '{key}' missing for path '{path}'")

    # Type-check present fields
    for key, value in payload.items():
        if key in TELEMETRY_FIELD_DEFS:
            spec = TELEMETRY_FIELD_DEFS[key]
            expected = spec.get("type")
            if expected and value is not None:
                if expected is str and not isinstance(value, str):
                    messages.append(f"field '{key}' expected str, got {type(value).__name__}")
                elif expected is int and not isinstance(value, (int, float)):
                    messages.append(f"field '{key}' expected int, got {type(value).__name__}")
                elif expected is bool and not isinstance(value, bool):
                    messages.append(f"field '{key}' expected bool, got {type(value).__name__}")
                elif expected is float and not isinstance(value, (int, float)):
                    messages.append(f"field '{key}' expected float, got {type(value).__name__}")
        elif strict:
            messages.append(f"unknown field '{key}' not in registry")

    # Check numeric invariants
    for inv in NUMERIC_INVARIANTS:
        if "gte" in inv:
            a_key, b_key = inv["gte"]
            a_val = payload.get(a_key)
            b_val = payload.get(b_key)
            if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
                if a_val < b_val:
                    messages.append(f"invariant violated: {a_key} ({a_val}) < {b_key} ({b_val}) — {inv['description']}")

    return messages


def normalize_purpose(raw: str, *, default: str = PURPOSE_UNKNOWN) -> str:
    s = str(raw or "").strip().lower()
    if not s or not _ALLOWED_PURPOSE_RE.match(s):
        return str(default)
    return s
