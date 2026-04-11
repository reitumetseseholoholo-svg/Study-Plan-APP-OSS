from __future__ import annotations

import datetime
import hashlib
import math
import os
import re
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, cast

from studyplan.ai.context_policy import adaptive_tutor_recent_cap, long_history_threshold_with_tier
from studyplan.ai.tutor_prompt_layers import (
    TUTOR_COACH_IDENTITY_LINES,
    TUTOR_STEP_BY_STEP_RESPONSE_CONTRACT,
    derive_pedagogical_mode,
)
from studyplan.ai.llm_output_sanitize import polish_tutor_answer_prose, sanitize_visible_local_llm_answer
from studyplan.ai.tutor_llm_purpose import infer_tutor_llm_purpose
from studyplan.ai.llm_telemetry import PURPOSE_TUTOR_POPUP
from studyplan.services import get_module_display_code, get_syllabus_scope_instruction

if TYPE_CHECKING:  # pragma: no cover - reserved for future editor hints
    pass


def _app_effective_tutor_topic(app: Any) -> str:
    """Prefer StudyPlanGUI._effective_tutor_topic (timer/quiz-aware); else UI current_topic."""
    fn = getattr(app, "_effective_tutor_topic", None)
    if callable(fn):
        try:
            return str(fn() or "").strip()
        except Exception:
            return ""
    return str(getattr(app, "current_topic", "") or "").strip()


# RAG chunking defaults (named constants for tuning and reuse)
RAG_CHUNK_CHARS_DEFAULT = 900
RAG_OVERLAP_CHARS_DEFAULT = 120
RAG_MAX_CHUNKS_DEFAULT = 1200


def _resolve_ai_tutor_max_response_chars() -> int:
    raw = str(os.environ.get("STUDYPLAN_AI_TUTOR_MAX_RESPONSE_CHARS", "") or "").strip()
    if raw:
        try:
            return max(2000, min(100_000, int(raw)))
        except Exception:
            pass
    try:
        from studyplan.ai.host_inference_profile import default_ai_tutor_max_response_chars

        return int(default_ai_tutor_max_response_chars())
    except Exception:
        return 12000


AI_TUTOR_MAX_RESPONSE_CHARS = _resolve_ai_tutor_max_response_chars()
AI_TUTOR_DEFAULT_TURN_TIMEOUT_SECONDS = 90
AI_TUTOR_MIN_TURN_TIMEOUT_SECONDS = 20
AI_TUTOR_MAX_TURN_TIMEOUT_SECONDS = 900
AI_TUTOR_PROMPT_CONTRACT_VERSION = 5
AI_TUTOR_STREAM_STALL_MS = 900
AI_TUTOR_STREAM_WATCHDOG_INTERVAL_MS = 240
AI_TUTOR_RAG_USAGE_HINT = (
    "RAG snippets come from two source types: [syllabus] snippets define exam scope and indicate which topics "
    "matter — use them to confirm relevance, not as your main explanation; [notes] and [supplemental] snippets "
    "contain detailed definitions, worked examples, and formulas — these are your primary knowledge source. "
    "When you use a fact, example, or formula from a snippet, cite the matching tag (e.g. [S2]). "
    "If the snippets do not cover the question, say so briefly, then answer from general knowledge and label "
    "any extra detail as unsupported by the provided excerpts."
)
# Single source for repeated tutor rules (economy + consistency).
AI_TUTOR_NEXT_STEP_RULE = (
    "End with one concrete next step (topic + mode + duration); suggest topic-based practice or in-app drill."
)
AI_TUTOR_NO_STUDY_GUIDE_QUESTION_RULE = (
    "Never suggest a specific study-guide question or textbook page number."
)
# When conversation length exceeds this, use adaptive recent_limit and a richer older summary.
AI_TUTOR_LONG_HISTORY_THRESHOLD = 24
AI_TUTOR_LONG_HISTORY_RECENT_LIMIT = 10
AI_TUTOR_LONG_HISTORY_SUMMARY_MAX_CHARS = 1100
AI_TUTOR_LONG_HISTORY_SUMMARY_MAX_ITEMS = 12


def _schedule_gui_background_thread(
    app: Any,
    GLib: Any,
    target: Callable[[], None],
    *,
    name: str,
    on_start_failed: Callable[[], bool] | None = None,
) -> bool:
    """Prefer ``app._start_managed_background_thread`` (shutdown-aware); else a daemon thread.

    When the managed starter refuses (e.g. shutdown in progress), ``on_start_failed`` is
    scheduled on the GTK main loop via ``idle_add`` and this returns False.
    """
    starter = getattr(app, "_start_managed_background_thread", None)
    if callable(starter):
        try:
            if starter(target, name=name):
                return True
        except Exception:
            pass
        if on_start_failed is not None:
            GLib.idle_add(on_start_failed)
        return False
    threading.Thread(target=target, daemon=True, name=name).start()
    return True


def infer_tutor_rag_preset(
    user_prompt: str,
    *,
    concise_mode: bool = False,
    exam_technique_only: bool = False,
) -> str:
    """Choose a RAG retrieval preset (roadmap Phase 2); env STUDYPLAN_AI_TUTOR_RAG_PRESET overrides."""
    from studyplan.ai.rag_presets import RAG_PRESET_NAMES

    env_raw = str(os.environ.get("STUDYPLAN_AI_TUTOR_RAG_PRESET", "") or "").strip().lower()
    if env_raw in RAG_PRESET_NAMES:
        return env_raw
    hint = infer_tutor_prompt_mode_hint(user_prompt)
    if exam_technique_only or hint == "exam_technique":
        return "tutor_explain"
    if hint in ("retrieval_drill", "guided_practice"):
        return "tutor_drill"
    if hint in ("revision_planner", "section_c_coach"):
        return "coach"
    if concise_mode:
        return "tutor_drill"
    return "tutor_explain"


def infer_tutor_prompt_mode_hint(user_prompt: str) -> str:
    text = str(user_prompt or "").strip().lower()
    if not text:
        return "teach"
    if any(token in text for token in ("section c", "constructed response", "case question", "case-based")):
        return "section_c_coach"
    if (
        any(token in text for token in ("exam technique", "command verb", "marks", "time allocation", "examiner"))
        and any(token in text for token in ("exam", "question", "answer", "approach", "technique", "section c"))
    ):
        return "exam_technique"
    if any(token in text for token in ("quiz me", "test me", "drill me", "rapid fire", "retrieval", "practice questions")):
        return "retrieval_drill"
    if any(token in text for token in ("step by step", "guide me", "work through", "don't give", "dont give", "hint first")):
        return "guided_practice"
    if any(token in text for token in ("revision plan", "revise", "study plan", "what should i study", "what next")):
        return "revision_planner"
    if any(token in text for token in ("why am i wrong", "mistake", "error", "keep getting", "where am i going wrong")):
        return "error_clinic"
    return "teach"


def _build_tutor_mode_guidance(mode_hint: str) -> list[str]:
    mode = str(mode_hint or "teach").strip().lower() or "teach"
    lines = [f"Mode hint (adapt response style): {mode}"]
    if mode == "guided_practice":
        lines.extend(
            [
                "- Use guided practice: ask for the learner's next step first, then reveal hints before full solutions.",
                "- Keep explanations short between attempts and focus on method correction.",
            ]
        )
    elif mode == "retrieval_drill":
        lines.extend(
            [
                "- Use retrieval mode: minimize explanation first, ask 1-3 quick checks, then give concise correction.",
                "- Prioritize recall/application prompts over long theory paragraphs.",
            ]
        )
    elif mode == "exam_technique":
        lines.extend(
            [
                "- Use exam-technique coaching: emphasize command verbs, mark allocation, and time management.",
                "- Show what earns marks and common presentation mistakes.",
            ]
        )
    elif mode == "section_c_coach":
        lines.extend(
            [
                "- Use Section C coaching: structure by requirement part/marks and apply points to case facts.",
                "- Prefer step-mark logic, assumptions, and recommendation quality over generic notes.",
            ]
        )
    elif mode == "revision_planner":
        lines.extend(
            [
                "- Use revision-planning mode: produce a practical sequence of study actions with timeboxes.",
                "- Tie the plan to weak areas, due reviews, and immediate practice checks.",
            ]
        )
    elif mode == "error_clinic":
        lines.extend(
            [
                "- Use error-clinic mode: diagnose why the learner is missing marks, then prescribe corrective drills.",
                "- Name the likely misconception and test the corrected understanding immediately.",
            ]
        )
    else:
        lines.extend(
            [
                "- Use teaching mode: explain intuition + method + exam relevance with a short worked example if applicable.",
            ]
        )
    return lines


def extract_tutor_coverage_targets(user_prompt: str, max_targets: int = 6) -> list[str]:
    raw = str(user_prompt or "").strip()
    if not raw:
        return []
    try:
        cap = max(1, min(12, int(max_targets)))
    except Exception:
        cap = 6
    text = re.sub(r"\s+", " ", raw)
    parts = re.split(r"\s*(?:,|;|\band\b|\bthen\b|\balso\b|\+|\/)\s*", text, flags=re.IGNORECASE)
    stop_words = {
        "explain",
        "compare",
        "and",
        "the",
        "a",
        "an",
        "for",
        "with",
        "about",
        "please",
        "show",
        "tell",
        "give",
        "help",
        "me",
    }
    cleaned: list[str] = []
    seen: set[str] = set()

    def _push_target(label: str) -> None:
        if len(cleaned) >= cap:
            return
        item = re.sub(r"[\(\)\[\]\{\}:]+", " ", str(label or "")).strip()
        item = re.sub(r"\s+", " ", item)
        if not item:
            return
        lowered = item.lower()
        if lowered in stop_words:
            return
        if len(lowered) < 2:
            return
        tokens = [tok for tok in re.findall(r"[a-z0-9]{2,}", lowered) if tok not in stop_words]
        if not tokens:
            return
        normalized = " ".join(tokens[:8]).strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        cleaned.append(item[:80])

    for part in parts:
        item = re.sub(r"[\(\)\[\]\{\}:]+", " ", str(part or "")).strip()
        item = re.sub(r"\s+", " ", item)
        if not item:
            continue
        lowered = item.lower()
        if lowered in stop_words:
            continue
        if len(lowered) < 4:
            continue
        tokens = [tok for tok in re.findall(r"[a-z0-9]{2,}", lowered) if tok not in stop_words]
        if not tokens:
            continue
        _push_target(item)
    # If the prompt is one long clause, keep high-signal acronyms as explicit targets.
    if len(cleaned) <= 1 and len(raw) >= 24:
        for token in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", raw):
            _push_target(token)
            if len(cleaned) >= cap:
                break
    if len(cleaned) <= 1:
        return cleaned
    # Filter broad fragments when more specific targets exist.
    dense: list[str] = []
    for target in cleaned:
        key = target.lower()
        if any(key != other.lower() and key in other.lower() for other in cleaned):
            continue
        dense.append(target)
    return dense[:cap] if dense else cleaned[:cap]


def build_targeted_rag_queries(user_prompt: str, max_targets: int = 4) -> list[str]:
    targets = extract_tutor_coverage_targets(user_prompt, max_targets=max_targets)
    if not targets:
        return []
    try:
        query_cap = max(2, min(12, int(max_targets) * 2))
    except Exception:
        query_cap = 8
    queries: list[str] = []
    seen: set[str] = set()
    for target in targets:
        text = str(target or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        queries.append(text)
        seen.add(key)
        if len(queries) >= query_cap:
            return queries[:query_cap]
    # Add relation-focused blends so retrieval catches cross-topic prompts.
    head = [str(t or "").strip() for t in targets[:4] if str(t or "").strip()]
    for i, left in enumerate(head):
        for right in head[i + 1:]:
            blend = f"{left} {right} relationship".strip()
            key = blend.lower()
            if key in seen:
                continue
            queries.append(blend)
            seen.add(key)
            if len(queries) >= query_cap:
                return queries[:query_cap]
    return queries[:query_cap]


def assess_tutor_coverage(response_text: str, targets: list[str]) -> dict[str, Any]:
    response = str(response_text or "").lower()
    target_rows = [str(target or "").strip() for target in list(targets or []) if str(target or "").strip()]
    if not target_rows:
        return {
            "target_count": 0,
            "hit_count": 0,
            "missed_targets": [],
            "coverage_ratio": 1.0,
        }
    hit_count = 0
    missed: list[str] = []
    for target in target_rows:
        tokens = [tok for tok in re.findall(r"[a-z0-9]{2,}", target.lower()) if tok]
        if not tokens:
            continue
        if " ".join(tokens) in response:
            hit_count += 1
            continue
        matched = sum(1 for tok in tokens if tok in response)
        threshold = max(1, int(math.ceil(float(len(tokens)) * 0.6)))
        if matched >= threshold:
            hit_count += 1
        else:
            missed.append(target)
    total = max(1, len(target_rows))
    return {
        "target_count": int(len(target_rows)),
        "hit_count": int(hit_count),
        "missed_targets": missed[:8],
        "coverage_ratio": float(hit_count / float(total)),
    }


def build_tutor_coverage_checklist_note(
    response_text: str,
    targets: list[str],
    max_items: int = 6,
) -> str:
    target_rows = [str(target or "").strip() for target in list(targets or []) if str(target or "").strip()]
    if len(target_rows) < 2:
        return ""
    try:
        item_cap = max(2, min(10, int(max_items)))
    except Exception:
        item_cap = 6
    summary = assess_tutor_coverage(response_text, target_rows)
    missed_set = {
        str(item or "").strip().lower()
        for item in list(summary.get("missed_targets", []) or [])
        if str(item or "").strip()
    }
    lower = str(response_text or "").lower()
    has_checklist = ("coverage checklist" in lower) or bool(re.search(r"\bt\d+\b", lower))
    # Add a deterministic checklist when the model skipped it or missed targets.
    if has_checklist and not missed_set:
        return ""
    lines = ["Coverage checklist:"]
    for idx, target in enumerate(target_rows[:item_cap], start=1):
        state = "follow-up needed" if str(target).strip().lower() in missed_set else "covered"
        lines.append(f"- T{idx}: {target} ({state})")
    return "\n".join(lines).strip()


def normalize_tutor_timeout_seconds(
    value: Any,
    default: int = AI_TUTOR_DEFAULT_TURN_TIMEOUT_SECONDS,
    minimum: int = AI_TUTOR_MIN_TURN_TIMEOUT_SECONDS,
    maximum: int = AI_TUTOR_MAX_TURN_TIMEOUT_SECONDS,
) -> int:
    try:
        timeout = int(value)
    except Exception:
        timeout = int(default)
    timeout = max(int(minimum), min(int(maximum), int(timeout)))
    return int(timeout)


def classify_ollama_error(err: str, host: str = "") -> tuple[str, str]:
    raw = str(err or "").strip()
    if not raw:
        return "unknown", "Ollama request failed. Try again."
    lower = raw.lower()
    host_hint = str(host or "").strip()
    if (
        "connection refused" in lower
        or "failed to establish" in lower
        or "name or service not known" in lower
        or "nodename nor servname" in lower
        or "no route to host" in lower
        or "network is unreachable" in lower
    ):
        suffix = f" ({host_hint})" if host_hint else ""
        return "host_unreachable", f"Cannot reach Ollama{suffix}. Start `ollama serve` and retry."
    if "timed out" in lower or "timeout" in lower:
        return "timeout", "Ollama request timed out. Try a shorter prompt or faster model."
    if (
        "model" in lower
        and ("not found" in lower or "missing" in lower or "no such model" in lower)
    ):
        return "model_missing", "Selected model is missing. Pull it first with `ollama pull <model>`."
    if (
        "busy" in lower
        or "try again" in lower
        or "rate limit" in lower
        or "too many requests" in lower
        or "http 429" in lower
    ):
        return "busy", "Ollama is busy. Wait for active jobs to finish, then retry."
    if "http 404" in lower:
        return "endpoint_missing", "Ollama endpoint unavailable. Verify host/version and retry."
    clean = raw.replace("\n", " ").strip()
    if len(clean) > 180:
        clean = f"{clean[:177].rstrip()}..."
    return "unknown", f"Ollama error: {clean}"


def chunk_text_for_rag(
    text: str,
    chunk_chars: int = RAG_CHUNK_CHARS_DEFAULT,
    overlap_chars: int = RAG_OVERLAP_CHARS_DEFAULT,
    max_chunks: int = RAG_MAX_CHUNKS_DEFAULT,
    boundary: str = "paragraph",
) -> list[str]:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", raw) if p and p.strip()]
    if not paragraphs:
        flat = re.sub(r"\s+", " ", raw).strip()
        if not flat:
            return []
        paragraphs = [flat]
    boundary_mode = str(boundary or "paragraph").strip().lower()
    if boundary_mode == "sentence":
        sentences: list[str] = []
        for para in paragraphs:
            for sent in re.split(r"(?<=[.!?])\s+", str(para or "").strip()):
                sent_clean = sent.strip()
                if sent_clean:
                    sentences.append(sent_clean)
        if sentences:
            paragraphs = sentences
    try:
        chunk_cap = max(240, min(2400, int(chunk_chars)))
    except Exception:
        chunk_cap = RAG_CHUNK_CHARS_DEFAULT
    try:
        overlap_cap = max(0, min(chunk_cap // 2, int(overlap_chars)))
    except Exception:
        overlap_cap = RAG_OVERLAP_CHARS_DEFAULT
    try:
        max_chunk_count = max(1, min(5000, int(max_chunks)))
    except Exception:
        max_chunk_count = RAG_MAX_CHUNKS_DEFAULT

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        paragraph = re.sub(r"\s+", " ", para).strip()
        if not paragraph:
            continue
        if len(paragraph) > chunk_cap:
            if current:
                chunks.append(current.strip())
                if len(chunks) >= max_chunk_count:
                    return chunks[:max_chunk_count]
                current = ""
            step = max(80, chunk_cap - overlap_cap)
            start = 0
            while start < len(paragraph):
                piece = paragraph[start:start + chunk_cap].strip()
                if piece:
                    chunks.append(piece)
                    if len(chunks) >= max_chunk_count:
                        return chunks[:max_chunk_count]
                if start + chunk_cap >= len(paragraph):
                    break
                start += step
            continue

        if not current:
            current = paragraph
            continue
        candidate = f"{current}\n{paragraph}"
        if len(candidate) <= chunk_cap:
            current = candidate
            continue
        chunks.append(current.strip())
        if len(chunks) >= max_chunk_count:
            return chunks[:max_chunk_count]
        if overlap_cap > 0:
            overlap_text = current[-overlap_cap:].strip()
            current = f"{overlap_text} {paragraph}".strip() if overlap_text else paragraph
        else:
            current = paragraph
    if current.strip() and len(chunks) < max_chunk_count:
        chunks.append(current.strip())
    return chunks[:max_chunk_count]


def _rag_tokens(text: str) -> list[str]:
    return [tok for tok in re.findall(r"[a-z0-9]{2,}", str(text or "").lower()) if tok]


# Phrases that suggest tutor is asking about presentation / statements (boost matching PDF chunks for FR).
_FR_PRESENTATION_RAG_PHRASES: tuple[str, ...] = (
    "ias 1",
    "ias 7",
    "ifrs 18",
    "statement of financial position",
    "statement of cash flows",
    "statement of profit or loss",
    "statement of profit",
    "other comprehensive income",
    "presentation of financial",
    "notes to the financial",
    "disclosure",
    "operating activities",
    "investing activities",
    "financing activities",
    "current assets",
    "non-current liabilities",
)


def tutor_query_suggests_format_rag_focus(query: str) -> bool:
    """Heuristic: learner question is about format, layout, or where items appear in financial statements."""
    q = str(query or "").strip().lower()
    if not q:
        return False
    needles = (
        "format",
        "layout",
        "present ",
        "presentation",
        "ias 1",
        "ias 7",
        "ifrs 18",
        "statement of financial",
        "statement of cash",
        "sof p",
        "sofp",
        "socf",
        "cash flow",
        "disclosure",
        "where does",
        "where should",
        "which statement",
        "which line",
        "line item",
        "operating activities",
        "investing activities",
        "financing activities",
        "minimum line",
    )
    return any(n in q for n in needles)


def lexical_rank_rag_chunks(
    query: str,
    chunks: list[str],
    top_n: int = 40,
    *,
    fr_presentation_rag_boost: bool = False,
) -> list[tuple[int, float]]:
    if not chunks:
        return []
    q_tokens = _rag_tokens(query)
    q_set = set(q_tokens)
    q_text = str(query or "").strip().lower()
    scored: list[tuple[int, float]] = []
    for idx, chunk in enumerate(chunks):
        text = str(chunk or "")
        if not text:
            continue
        c_tokens = _rag_tokens(text)
        if not c_tokens:
            continue
        c_set = set(c_tokens)
        overlap = len(q_set & c_set)
        precision = float(overlap) / float(max(1, len(q_set)))
        recall = float(overlap) / float(max(1, len(c_set)))
        score = (0.78 * precision) + (0.22 * recall)
        lower = text.lower()
        if q_text and q_text in lower:
            score += 0.20
        elif q_tokens:
            phrase_hits = 0
            for i in range(0, max(0, len(q_tokens) - 1)):
                pair = f"{q_tokens[i]} {q_tokens[i + 1]}"
                if pair in lower:
                    phrase_hits += 1
            if phrase_hits:
                score += min(0.18, 0.03 * float(phrase_hits))
        if fr_presentation_rag_boost:
            low = text.lower()
            hits = sum(1 for phrase in _FR_PRESENTATION_RAG_PHRASES if phrase in low)
            if hits:
                score += min(0.14, 0.022 * float(hits))
        if score <= 0:
            continue
        scored.append((idx, float(score)))
    scored.sort(key=lambda item: (-float(item[1]), int(item[0])))
    try:
        cap = max(1, min(200, int(top_n)))
    except Exception:
        cap = 40
    return scored[:cap]


def build_rag_context_block(snippets: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for row in list(snippets or []):
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id", "") or "").strip()
        source = str(row.get("source", "") or "").strip()
        text = str(row.get("text", "") or "").strip()
        if not sid or not text:
            continue
        if len(text) > 420:
            text = f"{text[:417].rstrip()}..."
        source_label = source if source else "PDF source"
        tier = str(row.get("tier", "") or "").strip()
        tier_tag = f"[{tier}] " if tier else ""
        rows.append(f"[{sid}] {tier_tag}{source_label}: {text}")
    if not rows:
        return ""
    return "\n".join(
        [
            "Reference snippets (use only when relevant; cite snippet IDs like [S1] in your answer):",
            *rows,
        ]
    ).strip()


def build_rag_concept_graph(
    snippets: list[dict[str, Any]],
    *,
    max_terms: int = 256,
    min_term_freq: int = 2,
) -> dict[str, Any]:
    """Build a lightweight lexical concept graph directly from RAG snippets.

    This is an additive, RAG-derived structure that complements (but does not
    modify) the canonical concept graph built from syllabus_structure.

    Nodes:
      - term nodes: id="term:<token>"
      - snippet nodes: id="snip:<snippet_id>"

    Edges:
      - term -> snippet with "weight" = term frequency within that snippet.
    """
    # Defensive defaults
    try:
        max_terms = max(1, min(2048, int(max_terms)))
    except Exception:
        max_terms = 256
    try:
        min_term_freq = max(1, min(50, int(min_term_freq)))
    except Exception:
        min_term_freq = 2

    # Tokenize all snippets and collect global frequencies.
    term_global_freq: dict[str, int] = {}
    snippet_terms: list[tuple[str, dict[str, int]]] = []

    for raw in list(snippets or []):
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("id", "") or "").strip()
        text = str(raw.get("text", "") or "").strip()
        if not sid or not text:
            continue
        tokens = _rag_tokens(text)
        if not tokens:
            continue
        local_counts: dict[str, int] = {}
        for tok in tokens:
            if len(tok) <= 2:
                continue
            local_counts[tok] = local_counts.get(tok, 0) + 1
        if not local_counts:
            continue
        snippet_terms.append((sid, local_counts))
        for tok, cnt in local_counts.items():
            term_global_freq[tok] = term_global_freq.get(tok, 0) + cnt

    if not term_global_freq or not snippet_terms:
        return {
            "meta": {
                "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "term_count": 0,
                "snippet_count": 0,
                "edge_count": 0,
                "method": "lexical",
            },
            "terms": [],
            "snippets": [],
            "edges": [],
        }

    # Select top terms by global frequency.
    sorted_terms = sorted(
        term_global_freq.items(),
        key=lambda item: (-int(item[1]), str(item[0])),
    )
    filtered_terms: list[str] = []
    for tok, freq in sorted_terms:
        if freq < min_term_freq:
            break
        filtered_terms.append(tok)
        if len(filtered_terms) >= max_terms:
            break

    if not filtered_terms:
        filtered_terms = [sorted_terms[0][0]] if sorted_terms else []

    term_index = {tok: idx for idx, tok in enumerate(filtered_terms)}

    term_nodes: list[dict[str, Any]] = []
    snippet_nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for tok in filtered_terms:
        term_nodes.append(
            {
                "id": f"term:{tok}",
                "token": tok,
                "frequency": int(term_global_freq.get(tok, 0)),
                "kind": "term",
            }
        )

    for sid, local_counts in snippet_terms:
        snippet_nodes.append(
            {
                "id": f"snip:{sid}",
                "snippet_id": sid,
                "kind": "snippet",
            }
        )
        for tok, cnt in local_counts.items():
            if tok not in term_index:
                continue
            edges.append(
                {
                    "term_id": f"term:{tok}",
                    "snippet_id": f"snip:{sid}",
                    "weight": float(cnt),
                }
            )

    return {
        "meta": {
            "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "term_count": len(term_nodes),
            "snippet_count": len(snippet_nodes),
            "edge_count": len(edges),
            "method": "lexical",
        },
        "terms": term_nodes,
        "snippets": snippet_nodes,
        "edges": edges,
    }


def assemble_ai_tutor_turn_prompt(
    base_prompt: str,
    learning_context: str = "",
    rag_context: str = "",
    planner_brief: str = "",
    *,
    learning_context_unchanged_sha256: str = "",
) -> str:
    parts: list[str] = [str(base_prompt or "").strip()]
    fp = str(learning_context_unchanged_sha256 or "").strip()
    context_text = str(learning_context or "").strip()
    if context_text:
        parts.append("\n".join(["Learning context (aggregated app state):", context_text]).strip())
    elif fp:
        parts.append(
            "Learning context (aggregated app state): Unchanged since the prior turn "
            f"(fingerprint sha256:{fp})."
        )
    planner_text = str(planner_brief or "").strip()
    if planner_text:
        parts.append("\n".join(["Planner brief (deterministic guidance):", planner_text]).strip())
    rag_text = str(rag_context or "").strip()
    if rag_text:
        parts.append(rag_text)
        parts.append(AI_TUTOR_RAG_USAGE_HINT)
    return "\n\n".join([part for part in parts if part]).strip()


def should_keep_response_bottom(
    auto_scroll_enabled: bool,
    force_scroll: bool,
    near_bottom: bool,
) -> bool:
    return bool(auto_scroll_enabled) and (bool(force_scroll) or bool(near_bottom))


def should_force_stream_flush(
    *,
    last_chunk_monotonic: float,
    last_render_monotonic: float,
    now_monotonic: float,
    stall_ms: int = AI_TUTOR_STREAM_STALL_MS,
) -> bool:
    try:
        chunk_at = float(last_chunk_monotonic)
    except Exception:
        chunk_at = 0.0
    if chunk_at <= 0.0:
        return False
    try:
        render_at = float(last_render_monotonic)
    except Exception:
        render_at = 0.0
    # Flush only when render progress is behind latest chunk.
    if render_at >= chunk_at:
        return False
    try:
        now_at = float(now_monotonic)
    except Exception:
        now_at = 0.0
    if now_at <= 0.0 or now_at < chunk_at:
        return False
    try:
        stall_limit_ms = max(150, min(5000, int(stall_ms)))
    except Exception:
        stall_limit_ms = AI_TUTOR_STREAM_STALL_MS
    return ((now_at - chunk_at) * 1000.0) >= float(stall_limit_ms)


def compute_tutor_control_state(
    *,
    running: bool,
    paused_turn: bool = False,
    model_ready: bool,
    llm_ready: bool,
    prompt_ready: bool,
    has_history: bool,
    has_latest_answer: bool,
    has_active_or_history: bool,
) -> dict[str, bool]:
    is_running = bool(running)
    is_paused = bool(paused_turn)
    ready_to_send = bool(model_ready) and bool(llm_ready) and bool(prompt_ready)
    return {
        "send_enabled": (not is_running) and ready_to_send,
        "stop_enabled": is_running or is_paused,
        "new_chat_enabled": not is_running,
        "refresh_models_enabled": not is_running,
        "model_dropdown_enabled": not is_running,
        "prompt_editable": not is_running,
        "quick_prompts_enabled": not is_running,
        "copy_transcript_enabled": (not is_running) and bool(has_history),
        "copy_last_enabled": (not is_running) and bool(has_latest_answer),
        "jump_latest_enabled": bool(has_active_or_history),
    }


def build_ai_tutor_seed_prompt(
    topic: str,
    module_title: str = "selected module",
    chapter: str | None = None,
) -> str:
    topic_val = str(topic or "").strip()
    module_val = str(module_title or "selected module").strip() or "selected module"
    chapter_val = str(chapter or "").strip()
    scope = f" for {module_val}"
    if chapter_val:
        scope = f" for {module_val} (chapter: {chapter_val})"
    if topic_val:
        return (
            f"As my ACCA coach: explain '{topic_val}'{scope} in exam-focused terms. "
            "Include: key rules/formulas, common mistakes, and 2–3 short practice checks with brief answers. "
            f"{AI_TUTOR_NEXT_STEP_RULE} {AI_TUTOR_NO_STUDY_GUIDE_QUESTION_RULE}"
        )
    return (
        f"As my ACCA coach: help me revise{scope} efficiently. "
        "Give a concise explanation, key formulas, and a short practice drill. "
        f"{AI_TUTOR_NEXT_STEP_RULE} {AI_TUTOR_NO_STUDY_GUIDE_QUESTION_RULE}"
    )


def _summarize_older_tutor_messages(
    messages: list[dict[str, str]],
    max_items: int = 6,
    max_chars: int = 520,
) -> str:
    """Summarize older conversation turns into a compact block so context stays within limits."""
    rows: list[str] = []
    try:
        item_cap = max(1, min(20, int(max_items)))
    except Exception:
        item_cap = 6
    try:
        char_cap = max(160, min(2400, int(max_chars)))
    except Exception:
        char_cap = 520
    used_chars = 0
    for msg in list(messages or [])[-item_cap:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "").strip().lower()
        if role not in ("user", "assistant"):
            continue
        raw_content = str(msg.get("content", "") or "").strip()
        if not raw_content:
            continue
        content = clean_ai_tutor_text(raw_content)
        content = re.sub(r"\s+", " ", content).strip()
        if not content:
            continue
        if len(content) > 120:
            content = f"{content[:117].rstrip()}..."
        prefix = "You" if role == "user" else "Tutor"
        row = f"- {prefix}: {content}"
        projected = used_chars + len(row) + (1 if rows else 0)
        if rows and projected > char_cap:
            break
        rows.append(row)
        used_chars = projected
    return "\n".join(rows).strip()


def build_ai_tutor_context_prompt_details(
    history: list[dict[str, str]],
    user_prompt: str,
    module_title: str,
    chapter: str,
    recent_limit: int = 10,
    syllabus_scope_instruction: str | None = None,
    module_id: str | None = None,
    concise_mode: bool = False,
    exam_technique_only: bool = False,
    student_context_line: str | None = None,
    confidence_guidance_line: str | None = None,
) -> tuple[str, dict[str, Any]]:
    cleaned_history: list[dict[str, str]] = []
    for msg in list(history or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "").strip().lower()
        content = str(msg.get("content", "") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        cleaned_history.append({"role": role, "content": content})
    try:
        recent_cap = max(2, min(20, int(recent_limit)))
    except Exception:
        recent_cap = 10
    recent_cap = adaptive_tutor_recent_cap(recent_cap)
    summary_max_chars = 520
    summary_max_items = 6
    long_threshold = long_history_threshold_with_tier(AI_TUTOR_LONG_HISTORY_THRESHOLD)
    if len(cleaned_history) > long_threshold:
        recent_cap = min(recent_cap, AI_TUTOR_LONG_HISTORY_RECENT_LIMIT)
        summary_max_chars = AI_TUTOR_LONG_HISTORY_SUMMARY_MAX_CHARS
        summary_max_items = AI_TUTOR_LONG_HISTORY_SUMMARY_MAX_ITEMS
    older_messages = cleaned_history[:-recent_cap] if len(cleaned_history) > recent_cap else []
    recent_messages = cleaned_history[-recent_cap:]
    older_summary = _summarize_older_tutor_messages(
        older_messages,
        max_items=summary_max_items,
        max_chars=summary_max_chars,
    )
    coverage_targets = extract_tutor_coverage_targets(user_prompt, max_targets=6)
    mode_hint = infer_tutor_prompt_mode_hint(user_prompt)
    pedagogical_mode = derive_pedagogical_mode(
        concise_mode=bool(concise_mode),
        exam_technique_only=bool(exam_technique_only),
        mode_hint=str(mode_hint),
    )
    display_code = get_module_display_code(str(module_id or "").strip()) if module_id else ""
    module_label = f"{display_code} — {module_title}" if display_code and (module_title or "").strip() else (module_title or "selected module")
    lines = [
        "You are the in-app ACCA professional coach (first-class local ACCA tutor) for this learner. Speak in one coherent, syllabus-bound voice.",
        f"Module: {module_label}",
        f"Current chapter: {chapter or 'not selected'}",
        f"Pedagogical mode: {pedagogical_mode}",
        "",
    ]
    if student_context_line and student_context_line.strip():
        lines.append(student_context_line.strip())
        lines.append("")
    if confidence_guidance_line and confidence_guidance_line.strip():
        lines.append(confidence_guidance_line.strip())
        lines.append("")
    lines.extend(TUTOR_COACH_IDENTITY_LINES)
    if concise_mode:
        lines.append("Concise mode: keep responses short (under 6–8 sentences) unless the user explicitly asks for more depth.")
        lines.append("")
    if exam_technique_only:
        lines.extend([
            "Exam technique only: do not add micro-checks, practice questions, or retrieval drills. "
            "Focus only on command verbs, mark allocation, time management, and what earns marks.",
            "",
        ])
    if syllabus_scope_instruction and syllabus_scope_instruction.strip():
        lines.append("Syllabus scope (strict — do not use non-examinable content):")
        lines.append(syllabus_scope_instruction.strip())
        lines.append("")
    lines.append(
        "Syllabus-derived context (outcomes, scope, importance) is for guiding what to teach and priority only; "
        "do not quote or cite the syllabus document. Use snippets when relevant from reference materials for explanations and citations."
    )
    lines.append("")
    if not exam_technique_only and not concise_mode:
        lines.extend(TUTOR_STEP_BY_STEP_RESPONSE_CONTRACT)
    if exam_technique_only:
        lines.extend([
            "Response contract (exam technique only — no practice checks):",
            "- Direct answer on exam technique: command verbs, mark allocation, time management",
            "- What earns marks and common presentation mistakes",
            f"- {AI_TUTOR_NEXT_STEP_RULE} {AI_TUTOR_NO_STUDY_GUIDE_QUESTION_RULE}",
            "",
            *_build_tutor_mode_guidance("exam_technique"),
            "",
        ])
    else:
        lines.extend([
            "Default learning-loop response contract (practice-first unless the user opts out):",
            "- Direct answer / teach the concept briefly",
            "- Method or worked example (when calculations/procedures apply)",
            "- Micro-check (1-3 practical checks or prompts)",
            "- What to look for / common pitfall",
            f"- {AI_TUTOR_NEXT_STEP_RULE} {AI_TUTOR_NO_STUDY_GUIDE_QUESTION_RULE}",
            "- When the learner answers a check, mark it as correct/partial/incorrect and correct the specific gap",
            "",
            *_build_tutor_mode_guidance(mode_hint),
            "",
        ])
    if len(coverage_targets) >= 2:
        lines.append("Multi-concept coverage targets:")
        for idx, target in enumerate(coverage_targets, start=1):
            lines.append(f"- T{idx}: {target}")
        lines.extend(
            [
                "Response contract for multi-concept prompts:",
                "- Direct answer",
                "- Coverage checklist (T1..Tn)",
                "- Key formulas/rules",
                "- Pitfalls to avoid",
                "- Quick drill (2-3 checks)",
                "",
            ]
        )
    if older_messages:
        lines.append("Earlier context summary (older turns condensed):")
        if older_summary:
            lines.append(older_summary)
        lines.append("")
    lines.append("Conversation context (recent turns):")
    for msg in recent_messages:
        role = str(msg.get("role", "") or "").strip().lower()
        content = str(msg.get("content", "") or "").strip()
        prefix = "USER" if role == "user" else "ASSISTANT"
        lines.append(f"{prefix}: {content}")
    lines.append(f"USER: {str(user_prompt or '').strip()}")
    lines.append("ASSISTANT:")
    prompt = "\n".join(lines).strip()
    meta: dict[str, Any] = {
        "history_total": int(len(cleaned_history)),
        "recent_used": int(len(recent_messages)),
        "older_condensed": int(len(older_messages)),
        "context_condensed": bool(older_messages),
        "summary_included": bool(older_summary),
        "coverage_targets": coverage_targets,
        "coverage_target_count": int(len(coverage_targets)),
        "mode_hint": str(mode_hint),
        "pedagogical_mode": str(pedagogical_mode),
        "practice_first_contract": not exam_technique_only,
        "concise_mode": bool(concise_mode),
        "exam_technique_only": bool(exam_technique_only),
    }
    return prompt, meta


def build_ai_tutor_context_prompt(
    history: list[dict[str, str]],
    user_prompt: str,
    module_title: str,
    chapter: str,
    syllabus_scope_instruction: str | None = None,
    module_id: str | None = None,
) -> str:
    prompt, _meta = build_ai_tutor_context_prompt_details(
        history=history,
        user_prompt=user_prompt,
        module_title=module_title,
        chapter=chapter,
        syllabus_scope_instruction=syllabus_scope_instruction,
        module_id=module_id,
    )
    return prompt


def strip_study_guide_question_refs(text: str) -> str:
    """Remove or neutralize phrases that ask the learner to do a specific study-guide question or page."""
    raw = str(text or "").strip()
    if not raw:
        return raw
    # Patterns that suggest "do question N" or "see page N" (often wrong references).
    # Match full sentences or bullet lines containing these, then remove or shorten.
    patterns = [
        # "Try/Do/Attempt question 3" or "see page 42"
        re.compile(
            r"\b(?:try|do|attempt|refer to|see|check)\s+"
            r"(?:question\s*#?\s*\d+|page\s*(?:#?\s*)?\d+)[^.!?\n]*(?:[.!?\n]|$)",
            re.IGNORECASE,
        ),
        # "Question 3 on page 42" or "question 5 from the study guide"
        re.compile(
            r"\bquestion\s*#?\s*\d+\s*(?:on|from)\s*(?:page\s*(?:#?\s*)?\d+|the\s+study\s+guide)[^.!?\n]*(?:[.!?\n]|$)",
            re.IGNORECASE,
        ),
        # "Refer to page 42" / "See page 12" (instructional reference; skip explanatory "on page X, ...")
        re.compile(
            r"\b(?:refer to|see|check|look at)\s+page\s*(?:#?\s*)?\d+[^.!?\n]*(?:[.!?\n]|$)",
            re.IGNORECASE,
        ),
        # "study guide question 3"
        re.compile(
            r"\bstudy\s+guide\s+(?:question|q\.?)\s*#?\s*\d+[^.!?\n]*(?:[.!?\n]|$)",
            re.IGNORECASE,
        ),
    ]
    result = raw
    for pat in patterns:
        result = pat.sub(" ", result)
    # Collapse repeated spaces and clean empty lines
    result = re.sub(r"[ \t]+", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _strip_ai_disclaimers(text: str) -> str:
    """Remove common AI assistant disclaimers so output reads as direct, human advice."""
    if not text or not isinstance(text, str):
        return text
    # Sentences or blocks to remove (case-insensitive start).
    disclaimer_starts = (
        "As an AI ",
        "As a language model",
        "I'm an AI ",
        "I am an AI ",
        "I cannot provide ",
        "I'm not able to ",
        "I am not able to ",
        "Note: As an AI",
        "Note: I am an AI",
        "Disclaimer: ",
        "I don't have the ability to ",
        "I do not have the ability to ",
    )
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        low = stripped.lower()
        skip = False
        for start in disclaimer_starts:
            if low.startswith(start.lower()):
                skip = True
                break
        if skip:
            continue
        # Trim leading "However, " / "That said, " after removing disclaimer above.
        if out and re.match(r"^(However|That said|Still),?\s+", stripped, re.IGNORECASE):
            stripped = re.sub(r"^(However|That said|Still),?\s+", "", stripped, flags=re.IGNORECASE)
        out.append(line)
    return "\n".join(out)


def _latex_to_human_readable(text: str) -> str:
    """Convert LaTeX and code-style math to human-readable form (how we write formulas)."""
    if not text or not isinstance(text, str):
        return text
    t = text
    # Unescape braces first so \frac\{a\}\{b\} is matchable.
    t = t.replace(r"\{", "{").replace(r"\}", "}")

    # \frac{a}{b} -> (a/b) human style
    frac = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
    for _ in range(10):
        nxt = frac.sub(r"(\1/\2)", t)
        if nxt == t:
            break
        t = nxt

    # \sqrt{x} -> sqrt(x)
    t = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"sqrt(\1)", t)
    # \sum -> sum of, \prod -> product of
    t = re.sub(r"\\sum\b", "sum of ", t)
    t = re.sub(r"\\prod\b", "product of ", t)
    # \int -> integral of
    t = re.sub(r"\\int\b", "integral of ", t)

    # Subscripts: x_1 -> x₁ or x_1 (keep underscore for readability), x_{12} -> x_12
    t = re.sub(r"\_\{([^{}]*)\}", r"_\1", t)
    # Superscripts for powers: x^2 -> x², x^3 -> x³, x^{10} -> x^10 (keep caret for big numbers)
    def _sup(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if inner == "2":
            return "²"
        if inner == "3":
            return "³"
        if inner == "1":
            return "¹"
        return f"^{inner}"
    t = re.sub(r"\^\{([^{}]*)\}", _sup, t)
    t = re.sub(r"\^2\b", "²", t)
    t = re.sub(r"\^3\b", "³", t)
    t = re.sub(r"\^1\b", "¹", t)

    # Greek letters: \alpha -> alpha, \beta -> beta, etc.
    greek = {
        r"\alpha": "alpha", r"\beta": "beta", r"\gamma": "gamma", r"\delta": "delta",
        r"\epsilon": "epsilon", r"\theta": "theta", r"\lambda": "lambda", r"\mu": "mu",
        r"\sigma": "sigma", r"\rho": "rho", r"\omega": "omega", r"\pi": "pi",
        r"\infty": "infinity", r"\partial": "d",
    }
    for src, dst in greek.items():
        t = t.replace(src, dst)

    # Operators (human style: as we write them)
    t = re.sub(r"\\times", " x ", t)
    t = re.sub(r"\\cdot", " · ", t)
    t = re.sub(r"\\approx", " ≈ ", t)
    t = re.sub(r"\\leq", " ≤ ", t)
    t = re.sub(r"\\geq", " ≥ ", t)
    t = re.sub(r"\\neq", " ≠ ", t)
    t = re.sub(r"\\pm", " ± ", t)
    t = re.sub(r"\\div", " ÷ ", t)
    t = re.sub(r"\\%", "%", t)  # literal backslash-percent -> percent
    t = re.sub(r"\\left\s*\(?", "(", t)
    t = re.sub(r"\\right\s*\)?", ")", t)
    t = re.sub(r"\\text\s*\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\quad", " ", t)
    t = re.sub(r"\\,", " ", t)
    t = re.sub(r"\\;", " ", t)
    t = re.sub(r"\\:", " ", t)
    # Strip remaining backslash-math like \( \) \[ \]
    t = re.sub(r"\\\(", "(", t).replace(r"\)", ")")
    t = re.sub(r"\\\[", "", t).replace(r"\]", "")
    return t


def _normalise_math_spacing(cleaned: str) -> str:
    """Shared numeric / operator spacing fix used by both clean_ai_tutor_text variants."""
    cleaned = re.sub(r"(\d)\s*([=+\-])\s*(\d)", r"\1 \2 \3", cleaned)
    cleaned = re.sub(r"([a-zA-Z0-9_)])\s*=\s*", r"\1 = ", cleaned)
    # Fix missing spaces between words and numbers (e.g., "is30,000" -> "is 30,000").
    cleaned = re.sub(r"([a-z])(\d)", r"\1 \2", cleaned)
    cleaned = re.sub(r"([A-Z]{2,})(\d)", r"\1 \2", cleaned)
    cleaned = re.sub(r"(\d)([a-z])", r"\1 \2", cleaned)
    return cleaned


def clean_ai_tutor_text(text: str) -> str:
    """Clean AI output to human-readable text: formulas as humans write them, no LaTeX/code noise."""
    cleaned = str(text or "")
    if not cleaned:
        return ""
    cleaned = sanitize_visible_local_llm_answer(cleaned)
    cleaned = polish_tutor_answer_prose(cleaned)
    cleaned = strip_study_guide_question_refs(cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

    # Remove AI disclaimers so it reads as direct advice.
    cleaned = _strip_ai_disclaimers(cleaned)

    # Remove fenced code wrappers but keep inner content (often formulas).
    cleaned = re.sub(r"```[A-Za-z0-9_-]*\n?", "", cleaned)
    cleaned = cleaned.replace("```", "")

    # Common markdown cleanup.
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)

    # Convert LaTeX and math to human-readable form.
    cleaned = re.sub(r"\\{2,}", r"\\", cleaned)
    cleaned = _latex_to_human_readable(cleaned)

    # Inline math $...$: convert contents then strip delimiters.
    def _replace_inline_math(m: re.Match[str]) -> str:
        inner = _latex_to_human_readable(m.group(1) or "")
        return inner.strip()
    cleaned = re.sub(r"\$\$?([^$]+)\$\$?", _replace_inline_math, cleaned)

    # Remove remaining $ and normalize spacing around = + - for readability.
    cleaned = cleaned.replace("$", "")
    cleaned = _normalise_math_spacing(cleaned)

    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def clean_ai_tutor_text_for_rich_display(text: str) -> str:
    """Like :func:`clean_ai_tutor_text` but preserves Markdown structure for rich rendering.

    Strips thinking traces, AI disclaimers, LaTeX, and study-guide question refs
    just like :func:`clean_ai_tutor_text` does, but keeps:
    - ``**bold**`` / ``*italic*`` inline spans
    - ``# Heading`` / ``## Heading`` ATX headings
    - Pipe-table rows (``| col | col |``)
    - Fenced code blocks (`` ``` ``)
    - Bullet list markers (``-`` / ``*``)

    These are then rendered visually by :func:`studyplan.ui.markdown_renderer.render_markdown_to_buffer`.
    """
    cleaned = str(text or "")
    if not cleaned:
        return ""
    cleaned = sanitize_visible_local_llm_answer(cleaned)
    cleaned = polish_tutor_answer_prose(cleaned)
    cleaned = strip_study_guide_question_refs(cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

    # Remove AI disclaimers.
    cleaned = _strip_ai_disclaimers(cleaned)

    # Remove fenced code language hints (``` python → ```) but keep the fence.
    cleaned = re.sub(r"```([A-Za-z0-9_-]+)\n", "```\n", cleaned)

    # Convert LaTeX and math to human-readable form (keep markdown intact).
    cleaned = re.sub(r"\\{2,}", r"\\", cleaned)
    cleaned = _latex_to_human_readable(cleaned)

    # Inline math $...$: convert contents then strip delimiters.
    def _replace_inline_math(m: re.Match[str]) -> str:
        inner = _latex_to_human_readable(m.group(1) or "")
        return inner.strip()
    cleaned = re.sub(r"\$\$?([^$]+)\$\$?", _replace_inline_math, cleaned)

    # Remove remaining $ and normalise spacing around operators.
    cleaned = cleaned.replace("$", "")
    cleaned = _normalise_math_spacing(cleaned)

    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def format_llm_output_attribution(model_id: str, backend: str = "") -> str:
    """Single-line credit for locally generated assistant text (Ollama vs llama.cpp)."""
    mid = str(model_id or "").strip()
    if not mid:
        return ""
    be = str(backend or "").strip().lower()
    if be in ("llama.cpp", "llama", "llama_cpp"):
        label = "llama.cpp"
    elif be == "ollama":
        label = "Ollama"
    elif be:
        label = be
    else:
        label = "Local LLM"
    return f"— {label} · {mid}"


def build_ai_tutor_assistant_history_row(
    app: Any,
    content: str,
    requested_model: str,
    *,
    inference_snapshot: tuple[str, str] | None = None,
) -> dict[str, str]:
    """Assistant turn dict with model + backend credited for this turn.

    When ``inference_snapshot`` is ``(backend, model_id)`` from the worker thread immediately
    after generation stops, it is authoritative (avoids races with other local LLM calls).

    Otherwise: prefer ``requested_model`` for Ollama failover correctness; use
    ``_last_llm_inference_*`` when the managed llama.cpp server handled the request.
    """
    snap_back = ""
    snap_model = ""
    if inference_snapshot is not None and len(inference_snapshot) >= 2:
        snap_back = str(inference_snapshot[0] or "").strip()
        snap_model = str(inference_snapshot[1] or "").strip()
    if snap_model:
        row: dict[str, str] = {"role": "assistant", "content": str(content or "")}
        row["model"] = snap_model[:200]
        if snap_back:
            row["llm_backend"] = snap_back[:32]
        return row

    back_raw = str(getattr(app, "_last_llm_inference_backend", "") or "").strip()
    back_norm = back_raw.lower()
    last_mid = str(getattr(app, "_last_llm_inference_model", "") or "").strip()
    req = str(requested_model or "").strip()
    if back_norm in ("llama.cpp", "llama", "llama_cpp") and last_mid:
        mid = last_mid
    elif req:
        mid = req
    else:
        mid = last_mid
    row = {"role": "assistant", "content": str(content or "")}
    if mid:
        row["model"] = mid[:200]
    if back_raw:
        row["llm_backend"] = back_raw[:32]
    return row


def normalize_ai_tutor_history_entry(item: Any, *, max_content: int = 8000) -> dict[str, str] | None:
    """Load one stored tutor turn; preserves model credit fields for assistant messages."""
    if not isinstance(item, dict):
        return None
    role = str(item.get("role", "") or "").strip().lower()
    text = str(item.get("content", "") or "").strip()
    if role not in ("user", "assistant") or not text:
        return None
    cap = max(256, min(32000, int(max_content)))
    row: dict[str, str] = {"role": role, "content": text[:cap]}
    if role == "assistant":
        m = str(item.get("model", "") or "").strip()[:200]
        b = str(item.get("llm_backend", "") or "").strip()[:32]
        if m:
            row["model"] = m
        if b:
            row["llm_backend"] = b
    return row


def compact_ai_tutor_history_for_prefs(history: list[Any], *, tail: int, max_content: int = 8000) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    n = max(1, min(64, int(tail)))
    for item in list(history or [])[-n:]:
        norm = normalize_ai_tutor_history_entry(item, max_content=max_content)
        if norm:
            out.append(norm)
    return out


def format_ai_tutor_transcript(history: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    show_attr = str(os.environ.get("STUDYPLAN_AI_TUTOR_SHOW_LLM_ATTRIBUTION", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    for msg in list(history or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "").strip().lower()
        content = str(msg.get("content", "") or "").strip()
        if role == "assistant":
            content = clean_ai_tutor_text(content)
            model_id = str(msg.get("model", "") or "").strip()
            backend = str(msg.get("llm_backend", "") or "").strip()
            attr = format_llm_output_attribution(model_id, backend) if show_attr else ""
            if attr and content:
                content = f"{content}\n\n{attr}"
            elif attr:
                content = attr
        if not content:
            continue
        label = "You" if role == "user" else "Tutor"
        blocks.append(f"{label}:\n{content}")
    return "\n\n".join(blocks).strip()


class AITutorDialogController:
    def __init__(self, app: Any, Gtk: Any, GLib: Any, Gdk: Any) -> None:
        self.app = app
        self.Gtk = Gtk
        self.GLib = GLib
        self.Gdk = Gdk

    def open(self) -> None:
        app = self.app
        Gtk = self.Gtk
        GLib = self.GLib
        Gdk = self.Gdk
        try:
            app._ai_tutor_dialog_open = True
        except Exception:
            pass
        dialog = app._new_dialog(title="AI Tutor (Ollama)", transient_for=app, modal=True)
        dialog.set_default_size(760, 620)
        dialog.add_buttons("_Close", Gtk.ResponseType.CLOSE)
        content = dialog.get_content_area()
        content.set_spacing(8)
        try:
            content.set_margin_top(10)
            content.set_margin_bottom(10)
            content.set_margin_start(10)
            content.set_margin_end(10)
        except Exception:
            pass

        intro = Gtk.Label(
            label="Use local Ollama models for topic explanations, drills, and revision support."
        )
        intro.set_halign(Gtk.Align.START)
        intro.set_wrap(True)
        intro.add_css_class("muted")
        content.append(intro)

        host_label = Gtk.Label(label=f"Host: {app._normalize_ollama_host()}")
        host_label.set_halign(Gtk.Align.START)
        host_label.add_css_class("muted")
        content.append(host_label)

        topic = _app_effective_tutor_topic(app)
        coach_pick = ""
        try:
            if hasattr(app, "_get_coach_pick_snapshot"):
                coach_pick, _ = app._get_coach_pick_snapshot(force=True)
                coach_pick = str(coach_pick or "").strip()
        except Exception:
            pass
        topic_line = f"Topic: {topic or '—'}"
        if topic and coach_pick and coach_pick == topic:
            topic_line += " (from Coach)"
        topic_label = Gtk.Label(label=topic_line)
        topic_label.set_halign(Gtk.Align.START)
        topic_label.add_css_class("muted")
        content.append(topic_label)

        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        model_label = Gtk.Label(label="Model")
        model_label.set_halign(Gtk.Align.START)
        model_label.set_size_request(70, -1)
        model_dropdown = Gtk.DropDown.new(Gtk.StringList.new(["Loading models…"]), None)
        model_dropdown.set_hexpand(True)
        refresh_btn = Gtk.Button(label="Refresh models")
        model_row.append(model_label)
        model_row.append(model_dropdown)
        model_row.append(refresh_btn)
        content.append(model_row)

        prompt_label = Gtk.Label(label="Prompt")
        prompt_label.set_halign(Gtk.Align.START)
        prompt_label.add_css_class("section-title")
        content.append(prompt_label)
        prompt_meta_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prompt_meta_row.add_css_class("inline-toolbar")
        prompt_hint = Gtk.Label(label="Ctrl+Enter to send.")
        prompt_hint.set_halign(Gtk.Align.START)
        prompt_hint.add_css_class("muted")
        prompt_hint.set_hexpand(True)
        prompt_count_label = Gtk.Label(label="0 chars")
        prompt_count_label.set_halign(Gtk.Align.END)
        prompt_count_label.add_css_class("muted")
        prompt_meta_row.append(prompt_hint)
        prompt_meta_row.append(prompt_count_label)
        content.append(prompt_meta_row)
        quick_prompts_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        quick_prompts_box.add_css_class("inline-toolbar")
        quick_prompts_box.set_hexpand(True)
        quick_prompts_label = Gtk.Label(label="Quick prompts")
        quick_prompts_label.set_halign(Gtk.Align.START)
        quick_prompts_label.add_css_class("muted")
        quick_prompts_box.append(quick_prompts_label)
        quick_prompt_templates: list[tuple[str, str]] = [
            ("Explain topic", "Explain '{topic}' for {module} in exam-focused terms."),
            ("Drill 5", "Write a 5-question drill on '{topic}' with short answers."),
            ("Formula sheet", "List the must-know formulas for '{topic}' and when to use each."),
            ("Exam pitfalls", "Give common exam pitfalls for '{topic}' and how to avoid them."),
        ]
        quick_prompt_buttons: list[tuple[Any, str]] = []
        for label, template in quick_prompt_templates:
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.set_tooltip_text(template.replace("{topic}", "current topic").replace("{module}", "module"))
            quick_prompts_box.append(btn)
            quick_prompt_buttons.append((btn, template))
        quick_prompts_scroller = Gtk.ScrolledWindow()
        quick_prompts_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        quick_prompts_scroller.set_min_content_height(44)
        quick_prompts_scroller.set_child(quick_prompts_box)
        content.append(quick_prompts_scroller)
        outcome_suggestions: list[dict[str, str]] = []
        try:
            eng = getattr(app, "engine", None)
            if eng and topic and hasattr(eng, "get_outcome_tutor_prompt_suggestions"):
                outcome_suggestions = list(eng.get_outcome_tutor_prompt_suggestions(topic) or [])[:15]
        except Exception:
            outcome_suggestions = []
        if outcome_suggestions:
            outcome_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            outcome_row.add_css_class("inline-toolbar")
            outcome_lbl = Gtk.Label(label="Outcome prompts")
            outcome_lbl.set_halign(Gtk.Align.START)
            outcome_lbl.add_css_class("muted")
            outcome_row.append(outcome_lbl)
            for sug in outcome_suggestions:
                lab = str(sug.get("label", "") or "").strip() or "Outcome"
                prompt_text = str(sug.get("prompt", "") or "").strip()
                btn = Gtk.Button(label=lab[:18] + ("…" if len(lab) > 18 else ""))
                btn.add_css_class("flat")
                btn.set_tooltip_text(prompt_text[:180] + ("…" if len(prompt_text) > 180 else ""))
                btn.connect("clicked", lambda _b, t=prompt_text: prompt_buf.set_text(t))
                outcome_row.append(btn)
            outcome_scroll = Gtk.ScrolledWindow()
            outcome_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            outcome_scroll.set_min_content_height(36)
            outcome_scroll.set_child(outcome_row)
            content.append(outcome_scroll)
        prompt_scroller = Gtk.ScrolledWindow()
        prompt_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        prompt_scroller.set_min_content_height(120)
        prompt_view = Gtk.TextView()
        prompt_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_buf = prompt_view.get_buffer()
        eff_topic = _app_effective_tutor_topic(app)
        prompt_buf.set_text(
            build_ai_tutor_seed_prompt(
                topic=eff_topic,
                module_title=str(getattr(app, "module_title", "") or "").strip() or "selected module",
                chapter=eff_topic or None,
            )
        )
        prompt_scroller.set_child(prompt_view)
        content.append(prompt_scroller)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_row.add_css_class("inline-toolbar")
        generate_btn = Gtk.Button(label="Send")
        generate_btn.add_css_class("suggested-action")
        stop_btn = Gtk.Button(label="Stop")
        stop_btn.set_sensitive(False)
        new_chat_btn = Gtk.Button(label="New chat")
        clear_prompt_btn = Gtk.Button(label="Clear prompt")
        copy_btn = Gtk.Button(label="Copy transcript")
        copy_btn.set_sensitive(False)
        action_row.append(generate_btn)
        action_row.append(stop_btn)
        action_row.append(new_chat_btn)
        action_row.append(clear_prompt_btn)
        action_row.append(copy_btn)
        action_scroller = Gtk.ScrolledWindow()
        action_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        action_scroller.set_min_content_height(42)
        action_scroller.set_child(action_row)
        content.append(action_scroller)

        status_label = Gtk.Label(label="")
        status_label.set_halign(Gtk.Align.START)
        status_label.set_wrap(True)
        status_label.add_css_class("muted")
        content.append(status_label)

        cockpit_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cockpit_row.add_css_class("inline-toolbar")
        cockpit_status_label = Gtk.Label(label="Tutor autopilot: app-wide")
        cockpit_status_label.set_halign(Gtk.Align.START)
        cockpit_status_label.set_hexpand(True)
        cockpit_status_label.add_css_class("muted")
        cockpit_pause_btn = Gtk.Button(label="Pause Autopilot")
        cockpit_pause_btn.add_css_class("flat")
        cockpit_row.append(cockpit_status_label)
        cockpit_row.append(cockpit_pause_btn)
        content.append(cockpit_row)

        response_label = Gtk.Label(label="Response")
        response_label.set_halign(Gtk.Align.START)
        response_label.add_css_class("section-title")
        content.append(response_label)
        response_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        response_toolbar.add_css_class("inline-toolbar")
        auto_scroll_toggle = Gtk.CheckButton(label="Auto-scroll")
        auto_scroll_toggle.set_active(True)
        jump_latest_btn = Gtk.Button(label="Jump to latest")
        copy_last_btn = Gtk.Button(label="Copy last answer")
        copy_last_btn.set_sensitive(False)
        response_toolbar.append(auto_scroll_toggle)
        response_toolbar.append(jump_latest_btn)
        response_toolbar.append(copy_last_btn)
        content.append(response_toolbar)
        response_scroller = Gtk.ScrolledWindow()
        response_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        response_scroller.set_min_content_height(260)
        response_scroller.set_vexpand(True)
        try:
            response_scroller.set_kinetic_scrolling(False)
        except Exception:
            pass
        response_view = Gtk.TextView()
        response_view.set_editable(False)
        response_view.set_cursor_visible(False)
        response_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        response_buf = response_view.get_buffer()
        response_scroller.set_child(response_view)
        content.append(response_scroller)

        history: list[dict[str, str]] = []
        for item in list(getattr(app, "_ai_tutor_history", []) or [])[-32:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "") or "").strip().lower()
            text = str(item.get("content", "") or "").strip()
            if role in ("user", "assistant") and text:
                history.append({"role": role, "content": text[:8000]})
        run_state: dict[str, Any] = {
            "active": False,
            "job_id": 0,
            "cancel_event": None,
            "model": "",
            "draft_user": "",
            "draft_assistant": "",
            "scroll_pending": False,
            "stream_render_pending": False,
            "stream_render_force": False,
            "stream_last_clean_text": "",
            "stream_label_inserted": False,
            "stream_last_chunk_at": 0.0,
            "stream_last_render_at": 0.0,
            "stream_watchdog_last_force_at": 0.0,
            "stream_watchdog_forced_flushes": 0,
            "stream_watchdog_id": 0,
        }

        if not bool(app.local_llm_enabled):
            status_label.set_text("Local AI tutor is disabled in Preferences.")
            generate_btn.set_sensitive(False)
        else:
            status_label.set_text("Ready. Press Ctrl+Enter to send.")

        refresh_btn.set_tooltip_text("Reload local models from Ollama.")
        generate_btn.set_tooltip_text("Send prompt to the selected model (Ctrl+Enter).")
        stop_btn.set_tooltip_text("Stop the current generation.")
        new_chat_btn.set_tooltip_text("Clear this tutor conversation.")
        clear_prompt_btn.set_tooltip_text("Clear the current prompt.")
        copy_btn.set_tooltip_text("Copy full tutor transcript.")
        copy_last_btn.set_tooltip_text("Copy only the latest tutor answer.")
        jump_latest_btn.set_tooltip_text("Jump to the newest response line.")
        auto_scroll_toggle.set_tooltip_text("Keep response view pinned to newest text.")
        cockpit_pause_btn.set_tooltip_text(
            "Pause or resume app-wide tutor autopilot (runs from the main window on a timer, even when this dialog is closed)."
        )

        def _persist_history() -> None:
            compact: list[dict[str, str]] = []
            for item in list(history)[-20:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "") or "").strip().lower()
                text = str(item.get("content", "") or "").strip()
                if role not in ("user", "assistant") or not text:
                    continue
                compact.append({"role": role, "content": text[:8000]})
            app._ai_tutor_history = compact
            app.save_preferences()

        def _turn_count() -> int:
            return sum(1 for msg in history if isinstance(msg, dict) and str(msg.get("role", "")).strip().lower() == "assistant")

        def _current_prompt_text(strip: bool = False) -> str:
            try:
                start, end = prompt_buf.get_bounds()
                text = prompt_buf.get_text(start, end, True)
            except Exception:
                text = ""
            text = str(text or "")
            return text.strip() if strip else text

        def _latest_assistant_answer() -> str:
            if bool(run_state.get("active", False)):
                draft_live = str(run_state.get("draft_assistant", "") or "").strip()
                if draft_live:
                    return clean_ai_tutor_text(draft_live)
            for item in reversed(list(history)):
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role", "") or "").strip().lower()
                if role != "assistant":
                    continue
                text = str(item.get("content", "") or "").strip()
                if not text:
                    continue
                return clean_ai_tutor_text(text)
            draft_assistant = str(run_state.get("draft_assistant", "") or "").strip()
            if draft_assistant:
                return clean_ai_tutor_text(draft_assistant)
            return ""

        def _update_prompt_meta() -> None:
            prompt_text = _current_prompt_text(strip=False)
            char_count = len(prompt_text)
            word_count = len([tok for tok in prompt_text.split() if tok.strip()])
            try:
                size_fn = getattr(app, "_apply_tutor_prompt_window_size", None)
                if callable(size_fn):
                    size_fn(
                        prompt_scroller,
                        model_name=_selected_model_name() or str(getattr(app, "local_llm_model", "") or ""),
                        base_min_height=120,
                    )
            except Exception:
                pass
            prompt_count_label.set_text(f"{char_count} chars · {word_count} words")
            if char_count > 2200:
                prompt_count_label.add_css_class("status-warn")
            else:
                prompt_count_label.remove_css_class("status-warn")

        def _response_is_near_bottom(padding: float = 36.0) -> bool:
            try:
                adj = response_scroller.get_vadjustment()
                if adj is None:
                    return True
                value = float(adj.get_value() or 0.0)
                upper = float(adj.get_upper() or 0.0)
                page = float(adj.get_page_size() or 0.0)
                tail_gap = max(0.0, upper - page - value)
                return tail_gap <= max(0.0, float(padding))
            except Exception:
                return True

        def _scroll_response_end_deferred() -> None:
            if bool(run_state.get("scroll_pending", False)):
                return
            run_state["scroll_pending"] = True

            def _apply_scroll() -> bool:
                run_state["scroll_pending"] = False
                try:
                    adj = response_scroller.get_vadjustment()
                    if adj is None:
                        return False
                    upper = float(adj.get_upper() or 0.0)
                    page = float(adj.get_page_size() or 0.0)
                    adj.set_value(max(0.0, upper - page))
                except Exception:
                    pass
                return False

            GLib.idle_add(_apply_scroll, priority=GLib.PRIORITY_LOW)

        def _response_buffer_text() -> str:
            try:
                start, end = response_buf.get_bounds()
                return str(response_buf.get_text(start, end, True) or "")
            except Exception:
                return ""

        def _append_response_text(text: str) -> None:
            piece = str(text or "")
            if not piece:
                return
            try:
                end_iter = response_buf.get_end_iter()
                response_buf.insert(end_iter, piece)
            except Exception:
                _render_transcript(force_scroll=False)

        def _sync_stream_tracking_from_draft() -> None:
            if not bool(run_state.get("active", False)):
                run_state["stream_last_clean_text"] = ""
                run_state["stream_label_inserted"] = False
                return
            draft_assistant = str(run_state.get("draft_assistant", "") or "")
            cleaned_draft = clean_ai_tutor_text(draft_assistant)
            run_state["stream_last_clean_text"] = cleaned_draft
            run_state["stream_label_inserted"] = bool(cleaned_draft)

        def _transcript_text_for_clipboard() -> str:
            entries: list[dict[str, Any]] = list(history)
            if bool(run_state.get("active", False)):
                draft_user = str(run_state.get("draft_user", "") or "").strip()
                draft_assistant = str(run_state.get("draft_assistant", "") or "")
                if draft_user:
                    entries.append({"role": "user", "content": draft_user})
                if draft_assistant.strip():
                    entries.append(
                        build_ai_tutor_assistant_history_row(
                            app,
                            draft_assistant,
                            str(run_state.get("model", "") or "").strip(),
                        )
                    )
            return format_ai_tutor_transcript(entries)

        def _render_transcript(force_scroll: bool = False) -> None:
            auto_scroll_enabled = bool(auto_scroll_toggle.get_active())
            should_keep_bottom = should_keep_response_bottom(
                auto_scroll_enabled=auto_scroll_enabled,
                force_scroll=bool(force_scroll),
                near_bottom=_response_is_near_bottom(56.0 if bool(run_state.get("active", False)) else 28.0),
            )
            text = _transcript_text_for_clipboard()
            response_buf.set_text(text if text else "No conversation yet.")
            _sync_stream_tracking_from_draft()
            run_state["stream_last_render_at"] = float(time.monotonic())
            if should_keep_bottom and text:
                _scroll_response_end_deferred()

        def _append_stream_delta(force_scroll: bool = False) -> None:
            if not bool(run_state.get("active", False)):
                _render_transcript(force_scroll=force_scroll)
                return
            auto_scroll_enabled = bool(auto_scroll_toggle.get_active())
            should_keep_bottom = should_keep_response_bottom(
                auto_scroll_enabled=auto_scroll_enabled,
                force_scroll=bool(force_scroll),
                near_bottom=_response_is_near_bottom(56.0),
            )
            draft_assistant = str(run_state.get("draft_assistant", "") or "")
            cleaned_full = clean_ai_tutor_text(draft_assistant)
            prev_clean = str(run_state.get("stream_last_clean_text", "") or "")
            if not cleaned_full:
                run_state["stream_last_clean_text"] = ""
                run_state["stream_label_inserted"] = False
                if should_keep_bottom:
                    _scroll_response_end_deferred()
                return
            if not bool(run_state.get("stream_label_inserted", False)):
                existing_text = _response_buffer_text()
                if not existing_text or existing_text.strip() == "No conversation yet.":
                    response_buf.set_text("Tutor:\n")
                else:
                    _append_response_text("\n\nTutor:\n")
                run_state["stream_label_inserted"] = True
                prev_clean = ""
            if cleaned_full.startswith(prev_clean):
                delta = cleaned_full[len(prev_clean):]
                if delta:
                    _append_response_text(delta)
            else:
                _render_transcript(force_scroll=False)
            run_state["stream_last_clean_text"] = cleaned_full
            run_state["stream_last_render_at"] = float(time.monotonic())
            if should_keep_bottom:
                _scroll_response_end_deferred()

        def _schedule_stream_render(force_scroll: bool = False) -> None:
            run_state["stream_render_force"] = bool(run_state.get("stream_render_force", False)) or bool(force_scroll)
            if bool(run_state.get("stream_render_pending", False)):
                return
            run_state["stream_render_pending"] = True

            def _apply_stream_render() -> bool:
                run_state["stream_render_pending"] = False
                force_flag = bool(run_state.get("stream_render_force", False))
                run_state["stream_render_force"] = False
                if bool(run_state.get("active", False)):
                    _append_stream_delta(force_scroll=force_flag)
                else:
                    _render_transcript(force_scroll=force_flag)
                return False

            GLib.idle_add(_apply_stream_render, priority=GLib.PRIORITY_DEFAULT_IDLE)

        def _ensure_stream_watchdog() -> None:
            existing_id = int(run_state.get("stream_watchdog_id", 0) or 0)
            if existing_id > 0:
                return

            def _watch_stream() -> bool:
                if not bool(run_state.get("active", False)):
                    run_state["stream_watchdog_id"] = 0
                    return False
                now_ts = float(time.monotonic())
                if should_force_stream_flush(
                    last_chunk_monotonic=float(run_state.get("stream_last_chunk_at", 0.0) or 0.0),
                    last_render_monotonic=float(run_state.get("stream_last_render_at", 0.0) or 0.0),
                    now_monotonic=now_ts,
                    stall_ms=AI_TUTOR_STREAM_STALL_MS,
                ):
                    last_force = float(run_state.get("stream_watchdog_last_force_at", 0.0) or 0.0)
                    if (now_ts - last_force) >= 0.25:
                        run_state["stream_watchdog_last_force_at"] = now_ts
                        run_state["stream_watchdog_forced_flushes"] = int(
                            run_state.get("stream_watchdog_forced_flushes", 0) or 0
                        ) + 1
                        run_state["stream_render_pending"] = False
                        run_state["stream_render_force"] = False
                        try:
                            _append_stream_delta(force_scroll=False)
                        except Exception:
                            _render_transcript(force_scroll=False)
                        run_state["stream_last_render_at"] = float(time.monotonic())
                return True

            try:
                watchdog_ms = max(120, min(2000, int(AI_TUTOR_STREAM_WATCHDOG_INTERVAL_MS)))
            except Exception:
                watchdog_ms = 240
            run_state["stream_watchdog_id"] = int(GLib.timeout_add(watchdog_ms, _watch_stream) or 0)

        def _sync_cockpit_controls() -> None:
            autopilot_enabled = bool(getattr(app, "ai_tutor_autopilot_enabled", True))
            paused = bool(getattr(app, "ai_tutor_autopilot_paused", False))
            if not autopilot_enabled:
                cockpit_pause_btn.set_label("Pause Autopilot")
                cockpit_pause_btn.set_sensitive(False)
                return
            cockpit_pause_btn.set_sensitive(True)
            cockpit_pause_btn.set_label("Resume Autopilot" if paused else "Pause Autopilot")

        def _jump_latest(*_args) -> None:
            _scroll_response_end_deferred()

        def _on_auto_scroll_toggled(*_args) -> None:
            if bool(auto_scroll_toggle.get_active()):
                _jump_latest()

        def _on_prompt_changed(*_args) -> None:
            _update_prompt_meta()
            _set_running(bool(run_state.get("active", False)))

        def _set_running(running: bool) -> None:
            run_state["active"] = bool(running)
            try:
                app._ai_tutor_popup_stream_active = bool(running)
            except Exception:
                pass
            if not running:
                run_state["stream_render_force"] = False
                run_state["stream_render_pending"] = False
                run_state["stream_last_clean_text"] = ""
                run_state["stream_label_inserted"] = False
                run_state["stream_last_chunk_at"] = 0.0
                run_state["stream_last_render_at"] = 0.0
                run_state["stream_watchdog_last_force_at"] = 0.0
                stream_watchdog_id = int(run_state.get("stream_watchdog_id", 0) or 0)
                if stream_watchdog_id > 0:
                    try:
                        GLib.source_remove(stream_watchdog_id)
                    except Exception:
                        pass
                run_state["stream_watchdog_id"] = 0
            else:
                _ensure_stream_watchdog()
            controls = compute_tutor_control_state(
                running=bool(running),
                paused_turn=bool(run_state.get("paused_tutor_turn") is not None),
                model_ready=bool(_selected_model_name()),
                llm_ready=bool(app.local_llm_enabled),
                prompt_ready=bool(_current_prompt_text(strip=True)),
                has_history=bool(history),
                has_latest_answer=bool(_latest_assistant_answer()),
                has_active_or_history=bool(history) or bool(run_state.get("active", False)),
            )
            generate_btn.set_sensitive(bool(controls.get("send_enabled", False)))
            stop_btn.set_sensitive(bool(controls.get("stop_enabled", False)))
            new_chat_btn.set_sensitive(bool(controls.get("new_chat_enabled", False)))
            refresh_btn.set_sensitive(bool(controls.get("refresh_models_enabled", False)))
            model_dropdown.set_sensitive(bool(controls.get("model_dropdown_enabled", False)))
            prompt_view.set_editable(bool(controls.get("prompt_editable", False)))
            quick_prompts_enabled = bool(controls.get("quick_prompts_enabled", False))
            for btn, _template in quick_prompt_buttons:
                btn.set_sensitive(quick_prompts_enabled)
            copy_btn.set_sensitive(bool(controls.get("copy_transcript_enabled", False)))
            copy_last_btn.set_sensitive(bool(controls.get("copy_last_enabled", False)))
            jump_latest_btn.set_sensitive(bool(controls.get("jump_latest_enabled", False)))
            _sync_cockpit_controls()

        def _autopilot_mode() -> str:
            try:
                resolver = getattr(app, "_effective_ai_tutor_autonomy_mode", None)
                if callable(resolver):
                    return str(resolver() or "assist")
                return str(app._coerce_ai_tutor_autonomy_mode(getattr(app, "ai_tutor_autonomy_mode", "assist")) or "assist")
            except Exception:
                return str(getattr(app, "ai_tutor_autonomy_mode", "assist") or "assist").strip().lower() or "assist"

        def _set_cockpit_status(message: str) -> None:
            mode = _autopilot_mode()
            base = f"Tutor autopilot [{mode}]"
            detail = str(message or "").strip()
            stats = getattr(app, "_ai_tutor_autopilot_stats", {})
            executed = int(stats.get("autopilot_action_executed_count", 0))
            dismissed = int(stats.get("autopilot_suggestion_dismissed_count", 0))
            pending = getattr(app, "_ai_tutor_pending_suggestion", None)
            pending_text = ""
            if isinstance(pending, dict):
                try:
                    describe_action = getattr(app, "_describe_ai_tutor_action", None)
                    if callable(describe_action):
                        pending_text = str(describe_action(pending) or "").strip()
                except Exception:
                    pending_text = ""
            parts = [detail] if detail else []
            parts.append(f"exec {executed}")
            parts.append(f"dismissed {dismissed}")
            if pending_text:
                parts.append(f"pending {pending_text}")
            cockpit_status_label.set_text(f"{base}: {' • '.join(parts)}" if parts else base)

        def _toggle_autopilot_pause(*_args) -> None:
            if not bool(getattr(app, "ai_tutor_autopilot_enabled", True)):
                _set_cockpit_status("disabled in Preferences")
                return
            app.ai_tutor_autopilot_paused = not bool(getattr(app, "ai_tutor_autopilot_paused", False))
            try:
                app.save_preferences()
            except Exception:
                pass
            _sync_cockpit_controls()
            if bool(getattr(app, "ai_tutor_autopilot_paused", False)):
                _set_cockpit_status("paused (app-wide)")
            else:
                _set_cockpit_status("resumed (app-wide)")

        def _selected_model_name() -> str:
            try:
                item = model_dropdown.get_selected_item()
            except Exception:
                item = None
            if item is None:
                return ""
            text_val = ""
            if hasattr(item, "get_string"):
                try:
                    text_val = str(item.get_string() or "")
                except Exception:
                    text_val = ""
            if not text_val:
                try:
                    text_val = str(item)
                except Exception:
                    text_val = ""
            text_val = text_val.strip()
            if text_val.startswith("("):
                return ""
            return text_val

        current_models: list[str] = []
        model_poll_id: int | None = None
        model_poll_errors = 0

        def _set_dropdown_models(model_names: list[str]) -> None:
            nonlocal current_models
            cleaned = [str(m).strip() for m in model_names if str(m).strip()]
            if not cleaned:
                cleaned = ["(no local models found)"]
            model_dropdown.set_model(Gtk.StringList.new(cleaned))
            preferred = str(app.local_llm_model or "").strip()
            if preferred and preferred in cleaned:
                model_dropdown.set_selected(cleaned.index(preferred))
            else:
                model_dropdown.set_selected(0)
            _set_running(bool(run_state.get("active", False)))
            current_models = cleaned

        def _refresh_models(*_args):
            if bool(run_state.get("active", False)):
                return
            nonlocal model_poll_errors
            status_label.set_text("Loading models from Ollama…")
            refresh_btn.set_sensitive(False)
            generate_btn.set_sensitive(False)

            def _worker():
                models, err = app._ollama_list_models()

                def _finish():
                    nonlocal model_poll_errors
                    refresh_btn.set_sensitive(True)
                    if err:
                        _code, friendly = classify_ollama_error(err, host=app._normalize_ollama_host())
                        _set_dropdown_models([])
                        status_label.set_text(friendly)
                        return False
                    model_poll_errors = 0
                    _set_dropdown_models(models)
                    if models:
                        status_label.set_text(f"Loaded {len(models)} model(s).")
                    else:
                        status_label.set_text("No local models found in Ollama.")
                    return False

                GLib.idle_add(_finish)

            def _refresh_models_start_failed() -> bool:
                refresh_btn.set_sensitive(True)
                generate_btn.set_sensitive(True)
                status_label.set_text("Could not refresh models (app may be shutting down).")
                return False

            _schedule_gui_background_thread(
                app, GLib, _worker, name="ai-tutor-ollama-models-refresh", on_start_failed=_refresh_models_start_failed
            )

        def _auto_poll_models() -> bool:
            if bool(run_state.get("active", False)):
                return True

            def _worker():
                models, err = app._ollama_list_models()

                def _finish():
                    nonlocal model_poll_errors
                    if err:
                        model_poll_errors += 1
                        _code, friendly = classify_ollama_error(err, host=app._normalize_ollama_host())
                        if model_poll_errors >= 3:
                            status_label.set_text("Model refresh paused after repeated errors; use Refresh.")
                            return False
                        status_label.set_text(friendly)
                        return True
                    model_poll_errors = 0
                    cleaned = [str(m).strip() for m in models if str(m).strip()]
                    if cleaned and cleaned != current_models:
                        _set_dropdown_models(cleaned)
                        status_label.set_text(f"Models updated ({len(cleaned)}).")
                    return True

                GLib.idle_add(_finish)

            _schedule_gui_background_thread(app, GLib, _worker, name="ai-tutor-ollama-models-poll")
            return True

        def _on_model_change(*_args):
            if bool(run_state.get("active", False)):
                return
            model_name = _selected_model_name()
            if model_name:
                app.local_llm_model = model_name
                app.save_preferences()
            _set_running(False)

        def _new_chat(*_args):
            if bool(run_state.get("active", False)):
                return
            history.clear()
            _persist_history()
            run_state.pop("learning_context_sha256", None)
            run_state.pop("telemetry_learning_context_fp", None)
            run_state.pop("telemetry_learning_context_omitted", None)
            status_label.set_text("New chat started.")
            _render_transcript(force_scroll=True)
            _set_running(False)

        def _clear_prompt(*_args):
            if bool(run_state.get("active", False)):
                return
            prompt_buf.set_text("")
            _update_prompt_meta()
            _set_running(False)

        def _insert_quick_prompt(template: str) -> None:
            if bool(run_state.get("active", False)):
                return
            topic = _app_effective_tutor_topic(app) or "the current topic"
            module = str(getattr(app, "module_title", "") or "").strip() or "selected module"
            try:
                resolved = str(template or "").format(topic=topic, module=module)
            except Exception:
                resolved = str(template or "")
            prompt_buf.set_text(resolved.strip())
            _update_prompt_meta()
            _set_running(False)
            status_label.set_text("Quick prompt inserted.")
            try:
                end_iter = prompt_buf.get_end_iter()
                prompt_buf.place_cursor(end_iter)
                prompt_view.grab_focus()
            except Exception:
                pass

        def _copy_chat(*_args):
            text = _transcript_text_for_clipboard()
            if not text:
                status_label.set_text("Nothing to copy.")
                return
            try:
                display = Gdk.Display.get_default()
                clipboard = display.get_clipboard() if display is not None else None
                if clipboard is not None:
                    clipboard.set_text(text)
                    status_label.set_text("Chat copied to clipboard.")
                else:
                    status_label.set_text("Clipboard unavailable.")
            except Exception:
                status_label.set_text("Clipboard unavailable.")

        def _copy_last_answer(*_args):
            text = _latest_assistant_answer().strip()
            if not text:
                status_label.set_text("No tutor answer to copy yet.")
                return
            try:
                display = Gdk.Display.get_default()
                clipboard = display.get_clipboard() if display is not None else None
                if clipboard is None:
                    status_label.set_text("Clipboard unavailable.")
                    return
                clipboard.set_text(text)
                status_label.set_text("Last tutor answer copied.")
            except Exception:
                status_label.set_text("Clipboard unavailable.")

        def _generate(*_args):
            if not bool(app.local_llm_enabled):
                status_label.set_text("Local AI tutor is disabled in Preferences.")
                return
            if bool(run_state.get("active", False)):
                status_label.set_text("Generation already running.")
                return
            user_prompt = _current_prompt_text(strip=True)
            if not user_prompt:
                status_label.set_text("Enter a prompt first.")
                return
            tutor_llm_purpose = infer_tutor_llm_purpose(user_prompt)
            new_req_id = getattr(app, "_new_llm_routing_request_id", None)
            routing_request_id = str(new_req_id() if callable(new_req_id) else "").strip()
            model_name = _selected_model_name() or str(app.local_llm_model or "").strip()
            auto_model_note = ""
            failover_note = ""
            available_models = [
                str(item).strip()
                for item in list(current_models or [])
                if str(item or "").strip() and not str(item or "").strip().startswith("(")
            ]
            selector = getattr(app, "_select_local_llm_model", None)
            if callable(selector):
                try:
                    selected_name, selected_err = cast(
                        Any,
                        selector(
                            model_override=None,
                            purpose=tutor_llm_purpose,
                            available_models=available_models or None,
                            persist=True,
                            routing_request_id=routing_request_id,
                            prompt_chars=len(user_prompt),
                        ),
                    )
                except Exception:
                    selected_name, selected_err = "", None
                selected_text = str(selected_name or "").strip()
                if selected_text:
                    if model_name and model_name != selected_text:
                        auto_model_note = f"Auto model: {selected_text}"
                    model_name = selected_text
                elif not model_name and selected_err:
                    status_label.set_text(str(selected_err))
                    return
            if not model_name:
                status_label.set_text("Select an Ollama model first.")
                return
            model_candidates: list[str] = [str(model_name or "").strip()]
            failover_builder = getattr(app, "_build_local_llm_model_failover_sequence", None)
            if callable(failover_builder):
                try:
                    failover_models, _failover_err = cast(
                        Any,
                        failover_builder(
                            purpose=tutor_llm_purpose,
                            model_override=None,
                            available_models=available_models or None,
                            persist=True,
                            routing_request_id=routing_request_id,
                            prompt_chars=len(user_prompt),
                        ),
                    )
                except Exception:
                    failover_models = []
                normalized_failover = [
                    str(item).strip()
                    for item in list(failover_models or [])
                    if str(item or "").strip() and not str(item or "").strip().startswith("(")
                ]
                if normalized_failover:
                    model_candidates = [str(model_name or "").strip()]
                    for candidate in normalized_failover:
                        if candidate not in model_candidates:
                            model_candidates.append(candidate)
            model_candidates = [name for name in model_candidates if name]
            if not model_candidates:
                model_candidates = [str(model_name or "").strip()]
            if len(model_candidates) > 1:
                failover_note = f"Failover armed: {len(model_candidates)} models"
            cognitive_runtime_brief = ""
            cognitive_guard: dict[str, Any] = {}
            try:
                builder = getattr(app, "_build_cognitive_tutor_runtime_brief", None)
                if callable(builder):
                    cognitive_runtime_brief, cognitive_guard = cast(
                        Any,
                        builder(user_prompt=user_prompt, chapter=_app_effective_tutor_topic(app)),
                    )
            except Exception:
                cognitive_runtime_brief = ""
                cognitive_guard = {}
            blocked_response = str(cognitive_guard.get("blocked_response", "") or "").strip()
            if blocked_response:
                history.append({"role": "user", "content": user_prompt})
                history.append({"role": "assistant", "content": blocked_response})
                try:
                    note_exchange = getattr(app, "_cognitive_tutor_note_exchange", None)
                    if callable(note_exchange):
                        cast(Any, note_exchange)("user", user_prompt)
                        cast(Any, note_exchange)("assistant", blocked_response)
                except Exception:
                    pass
                _persist_history()
                status_label.set_text("Quiz active: Socratic guard enforced.")
                _render_transcript(force_scroll=True)
                return
            turn_requested_at = float(time.monotonic())
            prompt_stage_started_at = float(time.monotonic())
            module_title = str(getattr(app, "module_title", "") or "").strip() or "selected module"
            chapter = _app_effective_tutor_topic(app)
            syllabus_scope = get_syllabus_scope_instruction(str(getattr(app, "module_id", "") or ""))
            effective_concise = bool(getattr(app, "ai_tutor_concise_mode", False))
            concise_reader = getattr(app, "_ai_tutor_effective_concise_for_turn", None)
            if callable(concise_reader):
                try:
                    effective_concise = bool(
                        concise_reader(
                            exam_technique_only=bool(getattr(app, "ai_tutor_exam_technique_only", False)),
                        )
                    )
                except Exception:
                    effective_concise = bool(getattr(app, "ai_tutor_concise_mode", False))
            full_prompt, prompt_meta = build_ai_tutor_context_prompt_details(
                history=history,
                user_prompt=user_prompt,
                module_title=module_title,
                chapter=chapter,
                syllabus_scope_instruction=syllabus_scope or None,
                module_id=str(getattr(app, "module_id", "") or "").strip() or None,
                concise_mode=effective_concise,
                exam_technique_only=bool(getattr(app, "ai_tutor_exam_technique_only", False)),
            )
            coverage_targets = [
                str(item or "").strip()
                for item in list(prompt_meta.get("coverage_targets", []) or [])
                if str(item or "").strip()
            ]
            coverage_target_count = int(prompt_meta.get("coverage_target_count", len(coverage_targets)) or len(coverage_targets))
            rag_top_k = max(4, min(12, int(4 + max(0, coverage_target_count))))
            rag_char_budget_override = 1800
            latency_profile: dict[str, Any] = {
                "p50_latency_ms": 0.0,
                "p90_latency_ms": 0.0,
                "latency_spread_ratio": 1.0,
            }
            latency_load_level = "normal"
            latency_slo_status = "insufficient"
            latency_hardening_applied = False
            adaptive_limits: dict[str, Any] = {}
            adaptive_reader = getattr(app, "_compute_ai_tutor_adaptive_limits", None)
            if callable(adaptive_reader):
                try:
                    adaptive_limits = cast(
                        Any,
                        adaptive_reader(
                            coverage_target_count=int(max(0, coverage_target_count)),
                            context_max_chars=900,
                            context_max_tokens=280,
                            rag_top_k=int(rag_top_k),
                            rag_char_budget=1800,
                        ),
                    )
                except Exception:
                    adaptive_limits = {}
                if isinstance(adaptive_limits, dict):
                    try:
                        rag_top_k = max(4, min(12, int(adaptive_limits.get("rag_top_k", rag_top_k) or rag_top_k)))
                    except Exception:
                        rag_top_k = max(4, min(12, int(rag_top_k)))
                    try:
                        rag_char_budget_override = max(
                            800,
                            min(3600, int(adaptive_limits.get("rag_char_budget", rag_char_budget_override) or rag_char_budget_override)),
                        )
                    except Exception:
                        rag_char_budget_override = 1800
                    profile_candidate = adaptive_limits.get("profile", {})
                    if isinstance(profile_candidate, dict):
                        latency_profile = profile_candidate
                    latency_load_level = str(adaptive_limits.get("load_level", "normal") or "normal").strip().lower() or "normal"
                    latency_slo_status = str(adaptive_limits.get("slo_status", "insufficient") or "insufficient").strip().lower() or "insufficient"
                    latency_hardening_applied = bool(adaptive_limits.get("hardening_applied", False))
            context_block = ""
            context_chars = 0
            context_budget_chars = 0
            context_tokens_est = 0
            context_dropped_sections = 0
            context_horizon_days = 14
            try:
                packet_builder = getattr(app, "_build_local_ai_context_packet", None)
                formatter = getattr(app, "_format_local_ai_context_block", None)
                budget_reader = getattr(app, "_context_budget_limits", None)
                token_estimator = getattr(app, "_estimate_context_tokens", None)
                if callable(packet_builder) and callable(formatter):
                    packet = packet_builder(kind="tutor", horizon_days=14)
                    if isinstance(packet, dict):
                        try:
                            context_horizon_days = int(packet.get("horizon_days", 14) or 14)
                        except Exception:
                            context_horizon_days = 14
                    max_chars = 900
                    max_tokens = 280
                    if callable(budget_reader):
                        try:
                            raw_limits = budget_reader("tutor")
                        except Exception:
                            raw_limits = None
                        if isinstance(raw_limits, tuple) and len(raw_limits) >= 2:
                            try:
                                max_chars = int(raw_limits[0] or max_chars)
                            except Exception:
                                max_chars = 900
                            try:
                                max_tokens = int(raw_limits[1] or max_tokens)
                            except Exception:
                                max_tokens = 280
                    if isinstance(adaptive_limits, dict) and adaptive_limits:
                        try:
                            max_chars = min(max_chars, int(adaptive_limits.get("context_max_chars", max_chars) or max_chars))
                        except Exception:
                            pass
                        try:
                            max_tokens = min(max_tokens, int(adaptive_limits.get("context_max_tokens", max_tokens) or max_tokens))
                        except Exception:
                            pass
                    max_chars = max(120, max_chars)
                    max_tokens = max(80, max_tokens)
                    context_budget_chars = int(min(max_chars, max_tokens * 4))
                    context_block = str(formatter(packet, max_chars=context_budget_chars) or "").strip()
                    if callable(token_estimator):
                        try:
                            context_tokens_est = int(cast(Any, token_estimator(context_block)))
                        except Exception:
                            context_tokens_est = max(0, int(round(float(len(context_block)) / 4.0)))
                    else:
                        context_tokens_est = max(0, int(round(float(len(context_block)) / 4.0)))
                    if context_tokens_est > max_tokens:
                        resized_budget = max(120, int(max_tokens * 4))
                        if resized_budget < context_budget_chars:
                            context_budget_chars = int(resized_budget)
                            context_block = str(formatter(packet, max_chars=context_budget_chars) or "").strip()
                            if callable(token_estimator):
                                try:
                                    context_tokens_est = int(cast(Any, token_estimator(context_block)))
                                except Exception:
                                    context_tokens_est = max(0, int(round(float(len(context_block)) / 4.0)))
                            else:
                                context_tokens_est = max(0, int(round(float(len(context_block)) / 4.0)))
                    context_chars = int(len(context_block))
                    format_meta = {}
                    if isinstance(packet, dict):
                        maybe_meta = packet.get("_format_meta")
                        if isinstance(maybe_meta, dict):
                            format_meta = maybe_meta
                    context_dropped_sections = int(format_meta.get("dropped_sections_count", 0) or 0)
            except Exception:
                context_block = ""
                context_chars = 0
                context_tokens_est = 0
                context_dropped_sections = 0
            prompt_build_ms = int(max(0.0, (float(time.monotonic()) - float(prompt_stage_started_at)) * 1000.0))
            try:
                cache_debug = getattr(app, "_ai_cache_debug_last", {})
                if isinstance(cache_debug, dict):
                    for key in (
                        "rag_doc_cache_hit",
                        "rag_query_cache_hit",
                        "embedding_cache_hits",
                        "embedding_cache_misses",
                        "prompt_cache_hit",
                        "response_cache_hit",
                        "token_est_cache_hit",
                        "model_stats_persisted",
                    ):
                        cache_debug[key] = 0
            except Exception:
                pass
            rag_context = ""
            rag_meta: dict[str, Any] = {"snippet_count": 0, "source_count": 0, "method": "disabled", "errors": []}
            rag_stage_started_at = float(time.monotonic())
            try:
                rag_preset = infer_tutor_rag_preset(
                    user_prompt,
                    concise_mode=bool(effective_concise),
                    exam_technique_only=bool(getattr(app, "ai_tutor_exam_technique_only", False)),
                )
                rag_context, rag_meta = app._build_ai_tutor_rag_prompt_context(
                    user_prompt=user_prompt,
                    history=history,
                    top_k=rag_top_k,
                    char_budget_override=rag_char_budget_override,
                    rag_preset=rag_preset,
                )
            except Exception as exc:
                rag_context = ""
                rag_meta = {
                    "snippet_count": 0,
                    "source_count": 0,
                    "method": "error",
                    "errors": [str(exc)],
                }
            rag_ms = int(max(0.0, (float(time.monotonic()) - float(rag_stage_started_at)) * 1000.0))
            planner_brief = ""
            planner_builder = getattr(app, "_build_ai_tutor_planner_brief", None)
            if callable(planner_builder):
                try:
                    planner_brief = str(
                        cast(
                            Any,
                            planner_builder(
                                user_prompt=user_prompt,
                                coverage_targets=coverage_targets,
                                context_block=context_block,
                            ),
                        )
                        or ""
                    ).strip()
                except Exception:
                    planner_brief = ""
            learner_profile_brief = ""
            learner_profile_builder = getattr(app, "_build_ai_tutor_learner_profile_brief", None)
            if callable(learner_profile_builder):
                try:
                    learner_profile_brief = str(
                        cast(
                            Any,
                            learner_profile_builder(
                                current_topic=chapter,
                                user_prompt=user_prompt,
                                max_chars=260,
                            ),
                        )
                        or ""
                    ).strip()
                except Exception:
                    learner_profile_brief = ""
            if learner_profile_brief:
                planner_brief = (
                    f"{planner_brief}\n{learner_profile_brief}".strip()
                    if planner_brief
                    else learner_profile_brief
                )
            if cognitive_runtime_brief:
                planner_brief = (
                    f"{planner_brief}\n{cognitive_runtime_brief}".strip()
                    if planner_brief
                    else cognitive_runtime_brief
                )
            rag_evidence_policy: dict[str, Any] = {}
            rag_evidence_policy_builder = getattr(app, "_evaluate_ai_tutor_rag_evidence_policy", None)
            if callable(rag_evidence_policy_builder):
                try:
                    rag_evidence_policy = dict(
                        cast(
                            Any,
                            rag_evidence_policy_builder(
                                user_prompt=user_prompt,
                                chapter=chapter,
                                rag_meta=rag_meta,
                            ),
                        )
                        or {}
                    )
                except Exception:
                    rag_evidence_policy = {}
            rag_evidence_line = str(rag_evidence_policy.get("planner_brief_line", "") or "").strip()
            if rag_evidence_line:
                planner_brief = (
                    f"{planner_brief}\n{rag_evidence_line}".strip()
                    if planner_brief
                    else rag_evidence_line
                )
            rag_claim_recorder = getattr(app, "_record_cognitive_rag_claim_confidence", None)
            if callable(rag_claim_recorder):
                try:
                    cast(
                        Any,
                        rag_claim_recorder(
                            user_prompt=user_prompt,
                            decision=rag_evidence_policy,
                        ),
                    )
                except Exception:
                    pass
            ctx_for_assemble = context_block
            ctx_fp_full = ""
            learning_ctx_omitted = 0
            unchanged_fp = ""
            dedup_raw = str(os.environ.get("STUDYPLAN_TUTOR_CONTEXT_DEDUP", "1") or "1").strip().lower()
            dedup_on = dedup_raw not in {"0", "false", "no", "off"}
            if context_block.strip():
                ctx_fp_full = hashlib.sha256(context_block.encode("utf-8")).hexdigest()
                prev_fp = str(run_state.get("learning_context_sha256") or "")
                if dedup_on and prev_fp and prev_fp == ctx_fp_full:
                    ctx_for_assemble = ""
                    unchanged_fp = ctx_fp_full[:24]
                    learning_ctx_omitted = 1
                run_state["learning_context_sha256"] = ctx_fp_full
            else:
                run_state.pop("learning_context_sha256", None)
            run_state["telemetry_learning_context_fp"] = ctx_fp_full
            run_state["telemetry_learning_context_omitted"] = int(learning_ctx_omitted)
            full_prompt = assemble_ai_tutor_turn_prompt(
                full_prompt,
                learning_context=ctx_for_assemble,
                rag_context=rag_context,
                planner_brief=planner_brief,
                learning_context_unchanged_sha256=unchanged_fp,
            )
            turn_timeout_seconds = normalize_tutor_timeout_seconds(
                getattr(app, "local_llm_timeout_seconds", AI_TUTOR_DEFAULT_TURN_TIMEOUT_SECONDS),
                default=AI_TUTOR_DEFAULT_TURN_TIMEOUT_SECONDS,
            )
            cancel_event = threading.Event()
            guard_state: dict[str, Any] = {
                "timeout_hit": False,
                "truncated": False,
                "stop_issued": False,
                "first_token_ms": 0,
                "generation_started_at": 0.0,
                "stream_started_at": 0.0,
                "failover_count": 0,
            }
            turn_started_at = float(turn_requested_at)
            prompt_chars = len(str(full_prompt or ""))
            try:
                prompt_tokens_est = int(app._estimate_ai_tutor_token_count(str(full_prompt or "")))
            except Exception:
                prompt_tokens_est = max(0, int(round(float(prompt_chars) / 4.0)))
            coverage_state: dict[str, Any] = {
                "target_count": int(max(0, coverage_target_count)),
                "hit_count": 0,
            }

            def _request_stream_stop_once() -> None:
                if bool(guard_state.get("stop_issued", False)):
                    return
                guard_state["stop_issued"] = True
                try:
                    app._ollama_stop_model(str(model_name or ""))
                except Exception:
                    pass

            def _cancel_check() -> bool:
                if cancel_event.is_set():
                    return True
                elapsed = float(time.monotonic() - turn_started_at)
                if elapsed >= float(turn_timeout_seconds):
                    guard_state["timeout_hit"] = True
                    cancel_event.set()
                    _request_stream_stop_once()
                    return True
                return False

            def _record_turn_telemetry(
                outcome: str,
                error_class: str,
                response_text: str,
                *,
                credited_model: str = "",
            ) -> None:
                if not hasattr(app, "_record_ai_tutor_telemetry"):
                    return
                clean_response = clean_ai_tutor_text(str(response_text or ""))
                response_chars = len(clean_response)
                try:
                    response_tokens_est = int(app._estimate_ai_tutor_token_count(clean_response))
                except Exception:
                    response_tokens_est = max(0, int(round(float(response_chars) / 4.0)))
                try:
                    latency_ms = int(max(0.0, (float(time.monotonic()) - float(turn_started_at)) * 1000.0))
                except Exception:
                    latency_ms = 0
                queue_ms_reader = getattr(app, "_consume_last_ollama_queue_ms", None)
                if callable(queue_ms_reader):
                    try:
                        queue_raw = cast(Any, queue_ms_reader)()
                        queue_ms = int(max(0, int(queue_raw or 0)))
                    except Exception:
                        queue_ms = 0
                else:
                    queue_ms = 0
                try:
                    generation_started_at = float(guard_state.get("generation_started_at", 0.0) or 0.0)
                except Exception:
                    generation_started_at = 0.0
                if generation_started_at > 0.0:
                    generation_ms = int(max(0.0, (float(time.monotonic()) - generation_started_at) * 1000.0))
                else:
                    generation_ms = 0
                try:
                    stream_started_at = float(guard_state.get("stream_started_at", 0.0) or 0.0)
                except Exception:
                    stream_started_at = 0.0
                if stream_started_at > 0.0:
                    stream_ms = int(max(0.0, (float(time.monotonic()) - stream_started_at) * 1000.0))
                else:
                    stream_ms = 0
                first_token_ms = int(max(0, int(guard_state.get("first_token_ms", 0) or 0)))
                autopilot_stats = dict(getattr(app, "_ai_tutor_autopilot_stats", {}) or {})
                eff_topic = _app_effective_tutor_topic(app)
                credited = str(credited_model or "").strip() or str(model_name or "").strip()
                payload = {
                    "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "model": credited,
                    "outcome": str(outcome or "").strip().lower(),
                    "error_class": str(error_class or "").strip().lower(),
                    "purpose": PURPOSE_TUTOR_POPUP,
                    "effective_topic": str(eff_topic or "").strip()[:200],
                    "module_id": str(getattr(app, "module_id", "") or "").strip()[:80],
                    "prompt_contract_version": int(AI_TUTOR_PROMPT_CONTRACT_VERSION),
                    "learning_context_fp": str(run_state.get("telemetry_learning_context_fp") or "")[:64],
                    "learning_context_omitted": int(run_state.get("telemetry_learning_context_omitted", 0) or 0),
                    "autopilot_mode": str(autopilot_stats.get("autopilot_mode", getattr(app, "ai_tutor_autonomy_mode", "assist")) or "assist"),
                    "autopilot_decision_count": int(autopilot_stats.get("autopilot_decision_count", 0) or 0),
                    "autopilot_action_executed_count": int(autopilot_stats.get("autopilot_action_executed_count", 0) or 0),
                    "autopilot_action_blocked_count": int(autopilot_stats.get("autopilot_action_blocked_count", 0) or 0),
                    "autopilot_last_block_reason": str(autopilot_stats.get("autopilot_last_block_reason", "") or ""),
                    "nudge_info_count": int(autopilot_stats.get("nudge_info_count", 0) or 0),
                    "nudge_warning_count": int(autopilot_stats.get("nudge_warning_count", 0) or 0),
                    "nudge_intervention_count": int(autopilot_stats.get("nudge_intervention_count", 0) or 0),
                    "latency_ms": int(latency_ms),
                    "queue_ms": int(queue_ms),
                    "prompt_build_ms": int(max(0, prompt_build_ms)),
                    "rag_ms": int(max(0, rag_ms)),
                    "generation_ms": int(max(0, generation_ms)),
                    "stream_ms": int(max(0, stream_ms)),
                    "model_first_token_ms": int(max(0, first_token_ms)),
                    "latency_p50_ms": int(max(0.0, float(latency_profile.get("p50_latency_ms", 0.0) or 0.0))),
                    "latency_p90_ms": int(max(0.0, float(latency_profile.get("p90_latency_ms", 0.0) or 0.0))),
                    "latency_spread_ratio": float(max(1.0, float(latency_profile.get("latency_spread_ratio", 1.0) or 1.0))),
                    "latency_load_level": str(latency_load_level or "normal"),
                    "latency_slo_status": str(latency_slo_status or "insufficient"),
                    "prompt_chars": int(prompt_chars),
                    "response_chars": int(response_chars),
                    "prompt_tokens_est": int(max(0, prompt_tokens_est)),
                    "response_tokens_est": int(max(0, response_tokens_est)),
                    "timeout_seconds": int(turn_timeout_seconds),
                    "timeout_hit": bool(guard_state.get("timeout_hit", False)),
                    "truncated": bool(guard_state.get("truncated", False)),
                    "rag_snippets": int(rag_count),
                    "rag_sources": int(rag_sources),
                    "rag_candidate_count": int(rag_candidate_count),
                    "rag_selected_total_count": int(rag_selected_total_count),
                    "rag_char_used": int(rag_char_used),
                    "rag_char_budget": int(rag_char_budget),
                    "rag_top_k_target": int(rag_top_k_target),
                    "rag_neighbor_window": int(rag_neighbor_window),
                    "rag_doc_cache_hit": int(rag_doc_cache_hit),
                    "rag_query_cache_hit": int(rag_query_cache_hit),
                    "embedding_cache_hits": int(embedding_cache_hits),
                    "embedding_cache_misses": int(embedding_cache_misses),
                    "prefilter_kept": int(prefilter_kept),
                    "prompt_cache_hit": int(getattr(app, "_ai_cache_debug_last", {}).get("prompt_cache_hit", 0) or 0),
                    "response_cache_hit": int(getattr(app, "_ai_cache_debug_last", {}).get("response_cache_hit", 0) or 0),
                    "token_est_cache_hit": int(getattr(app, "_ai_cache_debug_last", {}).get("token_est_cache_hit", 0) or 0),
                    "model_stats_persisted": int(getattr(app, "_ai_cache_debug_last", {}).get("model_stats_persisted", 0) or 0),
                    "coverage_target_count": int(max(0, coverage_state.get("target_count", 0) or 0)),
                    "coverage_hit_count": int(max(0, coverage_state.get("hit_count", 0) or 0)),
                    "gap_q_generated_count": int(autopilot_stats.get("gap_q_generated_count", 0) or 0),
                    "gap_q_saved_count": int(autopilot_stats.get("gap_q_saved_count", 0) or 0),
                    "gap_q_quarantined_count": int(autopilot_stats.get("gap_q_quarantined_count", 0) or 0),
                    "ctx_chars": int(context_chars),
                    "ctx_budget_chars": int(context_budget_chars),
                    "ctx_tokens_est": int(max(0, context_tokens_est)),
                    "ctx_dropped_sections_count": int(max(0, context_dropped_sections)),
                    "ctx_horizon_days": int(max(1, context_horizon_days)),
                    "context_condensed_turns": int(condensed_count),
                }
                try:
                    app._record_ai_tutor_telemetry(payload, persist=True)
                except Exception:
                    pass

            run_state["job_id"] = int(run_state.get("job_id", 0) or 0) + 1
            job_id = int(run_state.get("job_id", 0) or 0)
            run_state["cancel_event"] = cancel_event
            run_state["model"] = model_name
            run_state["draft_user"] = user_prompt
            run_state["draft_assistant"] = ""
            run_state["stream_last_clean_text"] = ""
            run_state["stream_label_inserted"] = False
            run_state["stream_last_chunk_at"] = 0.0
            run_state["stream_last_render_at"] = 0.0
            run_state["stream_watchdog_last_force_at"] = 0.0
            run_state["stream_watchdog_forced_flushes"] = 0
            app.local_llm_model = model_name
            app.save_preferences()
            condensed_count = int(prompt_meta.get("older_condensed", 0) or 0)
            rag_count = int(rag_meta.get("snippet_count", 0) or 0)
            rag_sources = int(rag_meta.get("source_count", 0) or 0)
            rag_method = str(rag_meta.get("method", "disabled") or "disabled").strip()
            rag_candidate_count = int(rag_meta.get("candidate_count", 0) or 0)
            rag_selected_total_count = int(rag_meta.get("selected_total_count", 0) or 0)
            rag_char_used = int(rag_meta.get("char_used", 0) or 0)
            rag_char_budget = int(rag_meta.get("char_budget", 0) or 0)
            rag_top_k_target = int(rag_meta.get("top_k_target", 0) or 0)
            rag_neighbor_window = int(rag_meta.get("neighbor_window", 0) or 0)
            rag_target_query_count = int(rag_meta.get("target_query_count", 0) or 0)
            rag_target_hit_snippets = int(rag_meta.get("target_hit_snippets", 0) or 0)
            rag_doc_cache_hit = int(rag_meta.get("rag_doc_cache_hit", 0) or 0)
            rag_query_cache_hit = int(rag_meta.get("rag_query_cache_hit", 0) or 0)
            embedding_cache_hits = int(rag_meta.get("embedding_cache_hits", 0) or 0)
            embedding_cache_misses = int(rag_meta.get("embedding_cache_misses", 0) or 0)
            prefilter_kept = int(rag_meta.get("prefilter_kept", 0) or 0)
            rag_evidence_mode = str(rag_evidence_policy.get("policy_mode", "") or "").strip()
            status_parts = ["Generating…"]
            if condensed_count > 0:
                status_parts.append(f"context condensed: {condensed_count} older turn(s)")
            if context_budget_chars > 0:
                status_parts.append(f"CTX: {context_chars}/{context_budget_chars} chars")
            if coverage_target_count > 1:
                status_parts.append(f"Coverage targets: {coverage_target_count}")
            fsm_state = str(cognitive_guard.get("fsm_state", "") or "").strip()
            if fsm_state:
                status_parts.append(f"FSM: {fsm_state}")
            if latency_load_level in {"warn", "critical"}:
                status_parts.append(f"Adaptive mode: {latency_load_level}")
            if latency_hardening_applied or latency_slo_status == "fail":
                status_parts.append("SLO hardening: on")
            if rag_count > 0:
                budget_text = ""
                if rag_char_budget > 0:
                    budget_text = f", {rag_char_used}/{rag_char_budget} chars"
                target_text = ""
                if rag_top_k_target > 0:
                    target_text = f", target {rag_top_k_target}"
                neighbor_text = ""
                if rag_neighbor_window > 0:
                    neighbor_text = f", +/-{rag_neighbor_window} neighbors"
                candidate_text = ""
                if rag_candidate_count > 0 or rag_selected_total_count > 0:
                    candidate_text = f", {rag_selected_total_count}/{rag_candidate_count} kept"
                target_query_text = ""
                if rag_target_query_count > 0:
                    target_query_text = f", tq {rag_target_query_count}"
                target_hit_text = ""
                if rag_target_hit_snippets > 0:
                    target_hit_text = f", target-hit {rag_target_hit_snippets}"
                cache_text = ""
                cache_parts: list[str] = []
                if rag_doc_cache_hit > 0:
                    cache_parts.append(f"doc-hit {rag_doc_cache_hit}")
                if rag_query_cache_hit > 0:
                    cache_parts.append("query-hit")
                if embedding_cache_hits > 0 or embedding_cache_misses > 0:
                    cache_parts.append(f"emb {embedding_cache_hits}/{embedding_cache_misses}")
                if prefilter_kept > 0:
                    cache_parts.append(f"pref {prefilter_kept}")
                if cache_parts:
                    cache_text = ", " + " ".join(cache_parts)
                status_parts.append(
                    f"RAG: {rag_count} snippet(s) from {rag_sources} PDF(s) "
                    f"[{rag_method}{budget_text}{target_text}{neighbor_text}{candidate_text}{target_query_text}{target_hit_text}{cache_text}]"
                )
            elif rag_sources > 0:
                status_parts.append("RAG: no relevant snippets")
            elif rag_method == "disabled":
                status_parts.append("RAG disabled (toggle in Preferences or set STUDYPLAN_AI_TUTOR_RAG_PDFS)")
            if rag_evidence_mode in {"weak_grounding", "disabled"} and rag_method != "disabled":
                status_parts.append("RAG evidence: weak")
            rag_errors = [err for err in rag_meta.get("errors", []) if err]
            if rag_errors:
                status_parts.append(f"RAG errors: {rag_errors[0][:72]}")
            if auto_model_note:
                status_parts.append(auto_model_note)
            if failover_note:
                status_parts.append(failover_note)
            notice_fn = getattr(app, "_ai_tutor_maybe_append_load_notice", None)
            if callable(notice_fn):
                try:
                    notice_fn(status_parts, adaptive_limits)
                except Exception:
                    pass
            status_label.set_text(" • ".join(status_parts))
            _set_running(True)
            _render_transcript(force_scroll=True)

            def _worker():
                nonlocal model_name

                def _on_chunk(piece: str) -> None:
                    def _apply_chunk():
                        if int(run_state.get("job_id", 0) or 0) != job_id:
                            return False
                        if not bool(run_state.get("active", False)):
                            return False
                        if int(guard_state.get("first_token_ms", 0) or 0) <= 0:
                            try:
                                started = float(guard_state.get("generation_started_at", 0.0) or 0.0)
                            except Exception:
                                started = 0.0
                            if started > 0.0:
                                guard_state["first_token_ms"] = int(
                                    max(0.0, (float(time.monotonic()) - started) * 1000.0)
                                )
                                guard_state["stream_started_at"] = float(time.monotonic())
                        draft = str(run_state.get("draft_assistant", "") or "") + str(piece or "")
                        if len(draft) > int(AI_TUTOR_MAX_RESPONSE_CHARS):
                            draft = draft[: int(AI_TUTOR_MAX_RESPONSE_CHARS)]
                            guard_state["truncated"] = True
                            cancel_event.set()
                            _request_stream_stop_once()
                        run_state["draft_assistant"] = draft
                        run_state["stream_last_chunk_at"] = float(time.monotonic())
                        _schedule_stream_render(force_scroll=False)
                        return False

                    GLib.idle_add(_apply_chunk)

                text = ""
                err: str | None = None
                failover_count = 0
                for idx, candidate_model in enumerate(model_candidates):
                    candidate_name = str(candidate_model or "").strip()
                    if not candidate_name:
                        continue
                    model_name = candidate_name
                    run_state["model"] = candidate_name
                    guard_state["generation_started_at"] = float(time.monotonic())
                    guard_state["stream_started_at"] = 0.0
                    guard_state["first_token_ms"] = 0
                    text, err = app._ollama_generate_text_stream(
                        candidate_name,
                        full_prompt,
                        on_chunk=_on_chunk,
                        cancel_check=_cancel_check,
                        inference_purpose=tutor_llm_purpose,
                    )
                    if not err or err == "cancelled":
                        break
                    partial_text = str(text or "").strip()
                    draft_text = str(run_state.get("draft_assistant", "") or "").strip()
                    if partial_text or draft_text:
                        break
                    if idx >= (len(model_candidates) - 1):
                        break
                    next_model = str(model_candidates[idx + 1] or "").strip()
                    if not next_model:
                        continue
                    failover_count += 1

                    def _notify_failover(failed_model: str, retry_model: str) -> bool:
                        if int(run_state.get("job_id", 0) or 0) != job_id:
                            return False
                        if not bool(run_state.get("active", False)):
                            return False
                        status_label.set_text(
                            f"Model {failed_model} failed, retrying with {retry_model}..."
                        )
                        return False

                    GLib.idle_add(_notify_failover, candidate_name, next_model)
                guard_state["failover_count"] = int(failover_count)

                inf_snap = (
                    str(getattr(app, "_last_llm_inference_backend", "") or "").strip(),
                    str(getattr(app, "_last_llm_inference_model", "") or "").strip(),
                )

                def _finish(inf_snap: tuple[str, str]) -> bool:
                    if int(run_state.get("job_id", 0) or 0) != job_id:
                        return False
                    draft_user = str(run_state.get("draft_user", "") or "").strip()
                    draft_assistant = str(run_state.get("draft_assistant", "") or "").strip()
                    run_state["cancel_event"] = None
                    run_state["draft_user"] = ""
                    run_state["draft_assistant"] = ""
                    _set_running(False)
                    final_text = str(text or "").strip() or draft_assistant
                    try:
                        postfilter = getattr(app, "_cognitive_tutor_postfilter_response", None)
                        if callable(postfilter):
                            final_text = str(
                                cast(
                                    Any,
                                    postfilter(
                                        final_text,
                                        permission=str(cognitive_guard.get("permission", "hint_ok") or "hint_ok"),
                                    ),
                                )
                                or ""
                            ).strip()
                    except Exception:
                        pass
                    action_plan: dict[str, Any] | None = None
                    try:
                        action_parser = getattr(app, "_extract_ai_tutor_inline_action", None)
                        if callable(action_parser):
                            parsed_result = action_parser(final_text)
                            if isinstance(parsed_result, tuple) and len(parsed_result) == 2:
                                cleaned_text, parsed_action = parsed_result
                                final_text = str(cleaned_text or "").strip()
                                if isinstance(parsed_action, dict):
                                    action_plan = parsed_action
                    except Exception:
                        action_plan = None

                    coverage_eval = assess_tutor_coverage(final_text, coverage_targets)
                    coverage_state["target_count"] = int(coverage_eval.get("target_count", coverage_target_count) or coverage_target_count)
                    coverage_state["hit_count"] = int(coverage_eval.get("hit_count", 0) or 0)
                    if not err:
                        coverage_note = build_tutor_coverage_checklist_note(
                            final_text,
                            coverage_targets,
                            max_items=6,
                        )
                        if coverage_note:
                            merged = f"{str(final_text or '').rstrip()}\n\n{coverage_note}".strip()
                            if len(merged) > int(AI_TUTOR_MAX_RESPONSE_CHARS):
                                merged = merged[: int(AI_TUTOR_MAX_RESPONSE_CHARS)].rstrip()
                            final_text = merged
                    try:
                        app_stats = dict(getattr(app, "_ai_tutor_autopilot_stats", {}) or {})
                        app._record_ai_tutor_autopilot_metrics(
                            {
                                "coverage_target_count": max(
                                    int(app_stats.get("coverage_target_count", 0) or 0),
                                    int(coverage_state["target_count"]),
                                ),
                                "coverage_hit_count": max(
                                    int(app_stats.get("coverage_hit_count", 0) or 0),
                                    int(coverage_state["hit_count"]),
                                ),
                            },
                            persist=False,
                        )
                    except Exception:
                        pass
                    credited_model = str(inf_snap[1] or "").strip() or str(model_name or "").strip()
                    if err == "cancelled":
                        if bool(guard_state.get("timeout_hit", False)):
                            telemetry_error = "timeout"
                        elif bool(guard_state.get("truncated", False)):
                            telemetry_error = "truncated"
                        else:
                            telemetry_error = "cancelled"
                        _record_turn_telemetry(
                            outcome="cancelled",
                            error_class=telemetry_error,
                            response_text=final_text,
                            credited_model=credited_model,
                        )
                        suffix = "[Stopped]"
                        if bool(guard_state.get("timeout_hit", False)):
                            suffix = f"[Timed out after {int(turn_timeout_seconds)}s]"
                        elif bool(guard_state.get("truncated", False)):
                            suffix = f"[Truncated at {int(AI_TUTOR_MAX_RESPONSE_CHARS)} chars]"
                        if draft_user and final_text:
                            final_text = clean_ai_tutor_text(final_text) or final_text
                            history.append({"role": "user", "content": draft_user})
                            history.append(
                                build_ai_tutor_assistant_history_row(
                                    app,
                                    f"{final_text}\n\n{suffix}",
                                    str(model_name or ""),
                                    inference_snapshot=inf_snap,
                                )
                            )
                            try:
                                note_exchange = getattr(app, "_cognitive_tutor_note_exchange", None)
                                if callable(note_exchange):
                                    cast(Any, note_exchange)("user", draft_user)
                                    cast(Any, note_exchange)("assistant", f"{final_text}\n\n{suffix}")
                            except Exception:
                                pass
                            _persist_history()
                            if bool(guard_state.get("timeout_hit", False)):
                                status_label.set_text(f"Turn timed out after {int(turn_timeout_seconds)}s ({credited_model}).")
                            elif bool(guard_state.get("truncated", False)):
                                status_label.set_text(
                                    f"Stopped at max length ({int(AI_TUTOR_MAX_RESPONSE_CHARS)} chars) • turns: {_turn_count()}"
                                )
                            else:
                                status_label.set_text(f"Stopped ({credited_model}) • turns: {_turn_count()}")
                        else:
                            if bool(guard_state.get("timeout_hit", False)):
                                status_label.set_text(f"Turn timed out after {int(turn_timeout_seconds)}s ({credited_model}).")
                            elif bool(guard_state.get("truncated", False)):
                                status_label.set_text(
                                    f"Stopped at max length ({int(AI_TUTOR_MAX_RESPONSE_CHARS)} chars)."
                                )
                            else:
                                status_label.set_text(f"Stopped ({credited_model}).")
                        _render_transcript(force_scroll=True)
                        return False
                    if err:
                        _code, friendly = classify_ollama_error(err, host=app._normalize_ollama_host())
                        recovery_status = ""
                        recovery_builder = getattr(app, "_compose_ollama_recovery_status", None)
                        if callable(recovery_builder):
                            try:
                                recovery_status = str(
                                    recovery_builder(
                                        err,
                                        model=str(model_name or ""),
                                        attempted_models=[str(item or "") for item in list(model_candidates or []) if str(item or "").strip()],
                                    )
                                ).strip()
                            except Exception:
                                recovery_status = ""
                        _record_turn_telemetry(
                            outcome="error",
                            error_class=_code,
                            response_text=final_text,
                            credited_model=credited_model,
                        )
                        status_label.set_text(recovery_status or friendly)
                        _render_transcript()
                        return False
                    if draft_user and final_text:
                        final_text = clean_ai_tutor_text(final_text) or final_text
                        updater = getattr(app, "_update_ai_tutor_working_memory", None)
                        if callable(updater):
                            try:
                                cast(
                                    Any,
                                    updater(
                                        user_prompt=draft_user,
                                        tutor_response=final_text,
                                        current_topic=chapter,
                                        coverage_targets=coverage_targets,
                                        persist=False,
                                    ),
                                )
                            except Exception:
                                pass
                        history.append({"role": "user", "content": draft_user})
                        history.append(
                            build_ai_tutor_assistant_history_row(
                                app,
                                final_text,
                                str(model_name or ""),
                                inference_snapshot=inf_snap,
                            )
                        )
                        try:
                            note_exchange = getattr(app, "_cognitive_tutor_note_exchange", None)
                            if callable(note_exchange):
                                cast(Any, note_exchange)("user", draft_user)
                                cast(Any, note_exchange)("assistant", final_text)
                        except Exception:
                            pass
                        _persist_history()
                    if isinstance(action_plan, dict):
                        try:
                            action_plan["source"] = "tutor_dialog"
                            setter = getattr(app, "_set_ai_tutor_pending_suggestion", None)
                            if callable(setter):
                                setter(action_plan, source="tutor_dialog")
                        except Exception:
                            pass
                    _record_turn_telemetry(
                        outcome="success",
                        error_class="",
                        response_text=final_text,
                        credited_model=credited_model,
                    )
                    _render_transcript(force_scroll=True)
                    if int(coverage_state.get("target_count", 0) or 0) > 1:
                        status_label.set_text(
                            f"Done ({credited_model}) • turns: {_turn_count()} • coverage {int(coverage_state.get('hit_count', 0) or 0)}/{int(coverage_state.get('target_count', 0) or 0)}"
                        )
                    else:
                        status_label.set_text(f"Done ({credited_model}) • turns: {_turn_count()}")
                    return False

                GLib.idle_add(_finish, inf_snap)

            def _generate_start_failed() -> bool:
                _set_running(False)
                run_state["cancel_event"] = None
                run_state["draft_user"] = ""
                run_state["draft_assistant"] = ""
                status_label.set_text("Could not start generation (app may be shutting down).")
                return False

            _schedule_gui_background_thread(
                app, GLib, _worker, name="ai-tutor-generate", on_start_failed=_generate_start_failed
            )

        def _stop_generation(*_args):
            if not bool(run_state.get("active", False)):
                return
            cancel_event = run_state.get("cancel_event")
            if isinstance(cancel_event, threading.Event):
                cancel_event.set()
            app._ollama_stop_model(str(run_state.get("model", "") or ""))
            status_label.set_text("Stopping…")

        def _on_close(d, _r):
            if bool(run_state.get("active", False)):
                cancel_event = run_state.get("cancel_event")
                if isinstance(cancel_event, threading.Event):
                    cancel_event.set()
                app._ollama_stop_model(str(run_state.get("model", "") or ""))
            if model_poll_id:
                try:
                    GLib.source_remove(model_poll_id)
                except Exception:
                    pass
            try:
                app._ai_tutor_popup_stream_active = False
            except Exception:
                pass
            stream_watchdog_id = int(run_state.get("stream_watchdog_id", 0) or 0)
            if stream_watchdog_id:
                try:
                    GLib.source_remove(stream_watchdog_id)
                except Exception:
                    pass
            run_state["stream_watchdog_id"] = 0
            try:
                app._ai_tutor_dialog_open = False
            except Exception:
                pass
            for refresh_name in ("_refresh_tutor_workspace_page", "update_dashboard", "update_study_room_card"):
                try:
                    refresh_fn = getattr(app, refresh_name, None)
                    if callable(refresh_fn):
                        refresh_fn()
                except Exception:
                    pass
            _persist_history()
            d.destroy()

        def _on_prompt_key(_controller, keyval, _keycode, state):
            ctrl_mask = int(getattr(Gdk.ModifierType, "CONTROL_MASK", 0))
            return_key = int(getattr(Gdk, "KEY_Return", 65293))
            kp_enter = int(getattr(Gdk, "KEY_KP_Enter", 65421))
            key_l = int(getattr(Gdk, "KEY_l", 108))
            key_L = int(getattr(Gdk, "KEY_L", 76))
            if (int(state) & ctrl_mask) and int(keyval) in (return_key, kp_enter):
                _generate()
                return True
            if (int(state) & ctrl_mask) and int(keyval) in (key_l, key_L):
                _clear_prompt()
                return True
            return False

        def _on_dialog_key(_controller, keyval, _keycode, _state):
            esc_key = int(getattr(Gdk, "KEY_Escape", 65307))
            if int(keyval) == esc_key and not bool(run_state.get("active", False)):
                dialog.response(Gtk.ResponseType.CLOSE)
                return True
            return False

        model_dropdown.connect("notify::selected", _on_model_change)
        refresh_btn.connect("clicked", _refresh_models)
        clear_prompt_btn.connect("clicked", _clear_prompt)
        new_chat_btn.connect("clicked", _new_chat)
        copy_btn.connect("clicked", _copy_chat)
        copy_last_btn.connect("clicked", _copy_last_answer)
        auto_scroll_toggle.connect("toggled", _on_auto_scroll_toggled)
        jump_latest_btn.connect("clicked", _jump_latest)
        stop_btn.connect("clicked", _stop_generation)
        cockpit_pause_btn.connect("clicked", _toggle_autopilot_pause)
        generate_btn.connect("clicked", _generate)
        prompt_buf.connect("changed", _on_prompt_changed)
        for btn, template in quick_prompt_buttons:
            btn.connect("clicked", lambda _b, t=template: _insert_quick_prompt(t))
        prompt_key = Gtk.EventControllerKey()
        prompt_key.connect("key-pressed", _on_prompt_key)
        prompt_view.add_controller(prompt_key)
        dialog_key = Gtk.EventControllerKey()
        dialog_key.connect("key-pressed", _on_dialog_key)
        dialog.add_controller(dialog_key)
        dialog.connect("response", _on_close)
        dialog.present()
        _update_prompt_meta()
        _render_transcript(force_scroll=True)
        _refresh_models()
        model_poll_id = GLib.timeout_add_seconds(45, _auto_poll_models)
        _sync_cockpit_controls()
        if not bool(getattr(app, "ai_tutor_autopilot_enabled", True)):
            _set_cockpit_status("disabled in Preferences")
        elif bool(getattr(app, "ai_tutor_autopilot_paused", False)):
            _set_cockpit_status("paused (app-wide)")
        else:
            _set_cockpit_status("running app-wide")
