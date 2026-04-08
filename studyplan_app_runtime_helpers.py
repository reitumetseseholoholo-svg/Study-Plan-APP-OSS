from __future__ import annotations

from typing import Any

from studyplan.ai.model_routing import routed_primary_for_purpose
from studyplan.question_quality import assess_question_quality_extended


def build_question_stats_export_rows(engine: Any) -> list[list[Any]]:
    """Build rows for question stats export (CSV) without importing GTK."""
    stats = getattr(engine, "question_stats", {}) or {}
    questions = getattr(engine, "QUESTIONS", {}) or {}

    rows: list[list[Any]] = [
        [
            "Chapter",
            "Question Index",
            "Question",
            "Attempts",
            "Correct",
            "Miss Rate",
            "Streak",
            "Avg Time (sec)",
            "Last Time (sec)",
            "Last Seen",
            "Outcome IDs (direct)",
            "Outcome IDs (manual linked)",
            "Manual Link Source",
            "Manual Link At",
            "Outcome IDs (resolved)",
            "Quality Score",
            "Quality Issues",
            "Difficulty Guess",
            "Max Distractor Similarity",
        ]
    ]

    qid_fn = getattr(engine, "_question_qid", None)
    resolve_fn = getattr(engine, "resolve_question_outcomes", None)
    for chapter, chapter_stats in stats.items():
        if not isinstance(chapter_stats, dict):
            continue
        q_list = questions.get(chapter, []) if isinstance(questions, dict) else []
        qid_to_idx: dict[str, int] = {}
        if isinstance(q_list, list):
            for idx in range(len(q_list)):
                qid = ""
                if callable(qid_fn):
                    try:
                        qid = str(qid_fn(chapter, idx) or "").strip()
                    except Exception:
                        qid = ""
                if not qid:
                    qid = str(idx)
                qid_to_idx[qid] = idx

        for key, entry in chapter_stats.items():
            if not isinstance(entry, dict):
                continue
            idx: int | None = None
            try:
                idx_int = int(str(key))
                idx = idx_int
            except Exception:
                idx = qid_to_idx.get(str(key))
            q_text = ""
            direct_outcome_ids_str = ""
            quality: dict[str, Any] = {}
            if idx is not None and isinstance(q_list, list) and 0 <= idx < len(q_list):
                try:
                    q_obj = q_list[idx]
                    if isinstance(q_obj, dict):
                        q_text = str(q_obj.get("question", "") or "")
                        direct = q_obj.get("outcome_ids")
                        if isinstance(direct, list) and direct:
                            direct_outcome_ids_str = "|".join(str(x) for x in direct if str(x).strip())
                        quality = assess_question_quality_extended(q_obj)
                except Exception:
                    q_text = ""
                    quality = {}

            linked = entry.get("linked_outcome_ids")
            manual_outcome_ids_str = ""
            if isinstance(linked, list) and linked:
                manual_outcome_ids_str = "|".join(str(x).strip() for x in linked if str(x).strip())
            manual_source = str(entry.get("linked_outcome_source", "") or "")
            manual_at = str(entry.get("linked_outcome_at", "") or "")

            resolved_outcome_ids_str = ""
            if idx is not None and callable(resolve_fn):
                try:
                    route = resolve_fn(chapter, idx)
                except Exception:
                    route = None
                if isinstance(route, dict):
                    oids = route.get("outcome_ids")
                    if isinstance(oids, list) and oids:
                        resolved_outcome_ids_str = "|".join(str(x).strip() for x in oids if str(x).strip())

            try:
                attempts = int(entry.get("attempts", 0) or 0)
            except Exception:
                attempts = 0
            try:
                correct = int(entry.get("correct", 0) or 0)
            except Exception:
                correct = 0
            miss_rate = 0.0 if attempts <= 0 else 1.0 - (correct / max(1, attempts))
            try:
                streak = int(entry.get("streak", 0) or 0)
            except Exception:
                streak = 0
            try:
                avg_time = float(entry.get("avg_time_sec", 0) or 0.0)
            except Exception:
                avg_time = 0.0
            try:
                last_time = float(entry.get("last_time_sec", 0) or 0.0)
            except Exception:
                last_time = 0.0
            last_seen = entry.get("last_seen") or ""

            rows.append(
                [
                    chapter,
                    (idx if idx is not None else str(key)),
                    q_text,
                    attempts,
                    correct,
                    f"{miss_rate:.2f}",
                    streak,
                    f"{avg_time:.1f}",
                    f"{last_time:.1f}",
                    last_seen,
                    direct_outcome_ids_str,
                    manual_outcome_ids_str,
                    manual_source,
                    manual_at,
                    resolved_outcome_ids_str,
                    f"{float(quality.get('score', 0.0) or 0.0):.2f}",
                    "|".join(str(x) for x in (quality.get("issues") or [])),
                    str(quality.get("difficulty_guess", "") or ""),
                    f"{float(quality.get('max_distractor_similarity', 0.0) or 0.0):.2f}",
                ]
            )
    return rows


def resolve_local_llm_default_for_purpose(
    purpose: str,
    candidates: list[str],
    *,
    default_ollama_model: str = "",
    default_ollama_model_coach: str = "",
    default_ollama_model_tutor: str = "",
    default_ollama_model_fallback: str = "",
) -> str:
    """Resolve a default local model without importing the GTK app module."""
    purpose_key = str(purpose or "").strip().lower()
    ordered_candidates = [str(item or "").strip() for item in list(candidates or []) if str(item or "").strip()]
    if not ordered_candidates:
        return ""

    def _match_kimi_candidate() -> str:
        best_cloud = ""
        best_any = ""
        for item in ordered_candidates:
            lower = item.lower()
            compact = lower.replace("_", "").replace("-", "").replace(" ", "")
            if "incomplete" in lower:
                continue
            if "kimi" not in compact:
                continue
            if "k2.5" not in compact and "k25" not in compact:
                continue
            if compact == "kimik2.5:cloud" or lower.strip() == "kimi-k2.5:cloud":
                return item
            if lower.endswith(":cloud") and not best_cloud:
                best_cloud = item
            if not best_any:
                best_any = item
        return best_cloud or best_any

    def _match_qwen35_4b_candidate() -> str:
        best = ""
        for item in ordered_candidates:
            lower = item.lower()
            compact = lower.replace("_", "").replace("-", "").replace(" ", "")
            if "incomplete" in lower:
                continue
            if ("qwen3.5" in compact or "qwen35" in compact) and "4b" in compact:
                if "gpt4allqwen354b" in compact:
                    return item
                if not best:
                    best = item
        return best

    if purpose_key in {
        "coach",
        "autopilot",
        "tutor",
        "deep_reason",
        "section_c_generation",
        "gap_generation",
    }:
        kimi = _match_kimi_candidate()
        if kimi:
            return kimi

    if purpose_key in {
        "coach",
        "autopilot",
        "tutor",
        "section_c_evaluation",
        "section_c_loop_diff",
    }:
        qwen35_4b = _match_qwen35_4b_candidate()
        if qwen35_4b:
            return qwen35_4b

    routed = routed_primary_for_purpose(purpose_key, ordered_candidates)
    if routed:
        return routed

    if purpose_key in {
        "coach",
        "autopilot",
        "section_c_evaluation",
        "section_c_loop_diff",
    }:
        preferred = [
            str(default_ollama_model_coach or "").strip(),
            str(default_ollama_model_fallback or "").strip(),
            str(default_ollama_model or "").strip(),
        ]
    elif purpose_key in {"section_c_judgment"}:
        preferred = [
            str(default_ollama_model_tutor or "").strip(),
            str(default_ollama_model_coach or "").strip(),
            str(default_ollama_model or "").strip(),
            str(default_ollama_model_fallback or "").strip(),
        ]
    elif purpose_key in {
        "tutor",
        "deep_reason",
        "section_c_generation",
        "gap_generation",
    }:
        preferred = [
            str(default_ollama_model_tutor or "").strip(),
            str(default_ollama_model or "").strip(),
            str(default_ollama_model_fallback or "").strip(),
        ]
    else:
        preferred = [
            str(default_ollama_model or "").strip(),
            str(default_ollama_model_coach or "").strip(),
            str(default_ollama_model_tutor or "").strip(),
            str(default_ollama_model_fallback or "").strip(),
        ]
    preferred = [item for item in preferred if item]
    if not preferred:
        return ""

    for pref in preferred:
        if pref in ordered_candidates:
            return pref

    normalized: list[tuple[str, str]] = []
    for item in ordered_candidates:
        base = str(item.split(":", 1)[0] or "").strip()
        normalized.append((item, base))

    for pref in preferred:
        pref_base = str(pref.split(":", 1)[0] or "").strip()
        if not pref_base:
            continue
        for full_name, base in normalized:
            if base == pref_base:
                return full_name
        for full_name, base in normalized:
            if pref_base in base or base in pref_base:
                return full_name
    return ""
