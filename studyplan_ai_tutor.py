from __future__ import annotations

import re
import math
import threading
import time
from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:  # pragma: no cover - reserved for future editor hints
    pass


AI_TUTOR_MAX_RESPONSE_CHARS = 12000
AI_TUTOR_DEFAULT_TURN_TIMEOUT_SECONDS = 90
AI_TUTOR_MIN_TURN_TIMEOUT_SECONDS = 20
AI_TUTOR_MAX_TURN_TIMEOUT_SECONDS = 900
AI_TUTOR_PROMPT_CONTRACT_VERSION = 3
AI_TUTOR_STREAM_STALL_MS = 900
AI_TUTOR_STREAM_WATCHDOG_INTERVAL_MS = 240
AI_TUTOR_RAG_USAGE_HINT = (
    "Use snippets when relevant and cite IDs like [S1] for snippet-backed facts. "
    "If snippets are insufficient, answer with model knowledge and state assumptions clearly."
)


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
    chunk_chars: int = 900,
    overlap_chars: int = 120,
    max_chunks: int = 1200,
) -> list[str]:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", raw) if p and p.strip()]
    if not paragraphs:
        flat = re.sub(r"\s+", " ", raw).strip()
        if not flat:
            return []
        paragraphs = [flat]
    try:
        chunk_cap = max(240, min(2400, int(chunk_chars)))
    except Exception:
        chunk_cap = 900
    try:
        overlap_cap = max(0, min(chunk_cap // 2, int(overlap_chars)))
    except Exception:
        overlap_cap = 120
    try:
        max_chunk_count = max(1, min(5000, int(max_chunks)))
    except Exception:
        max_chunk_count = 1200

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


def lexical_rank_rag_chunks(
    query: str,
    chunks: list[str],
    top_n: int = 40,
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
        rows.append(f"[{sid}] {source_label}: {text}")
    if not rows:
        return ""
    return "\n".join(
        [
            "Reference snippets (use only when relevant; cite snippet IDs like [S1] in your answer):",
            *rows,
        ]
    ).strip()


def assemble_ai_tutor_turn_prompt(
    base_prompt: str,
    learning_context: str = "",
    rag_context: str = "",
) -> str:
    parts: list[str] = [str(base_prompt or "").strip()]
    context_text = str(learning_context or "").strip()
    if context_text:
        parts.append("\n".join(["Learning context (aggregated app state):", context_text]).strip())
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
    model_ready: bool,
    llm_ready: bool,
    prompt_ready: bool,
    has_history: bool,
    has_latest_answer: bool,
    has_active_or_history: bool,
) -> dict[str, bool]:
    is_running = bool(running)
    ready_to_send = bool(model_ready) and bool(llm_ready) and bool(prompt_ready)
    return {
        "send_enabled": (not is_running) and ready_to_send,
        "stop_enabled": is_running,
        "new_chat_enabled": not is_running,
        "refresh_models_enabled": not is_running,
        "model_dropdown_enabled": not is_running,
        "prompt_editable": not is_running,
        "quick_prompts_enabled": not is_running,
        "copy_transcript_enabled": (not is_running) and bool(has_history),
        "copy_last_enabled": (not is_running) and bool(has_latest_answer),
        "jump_latest_enabled": bool(has_active_or_history),
    }


def build_ai_tutor_seed_prompt(topic: str, module_title: str = "ACCA") -> str:
    topic_val = str(topic or "").strip()
    module_val = str(module_title or "ACCA").strip() or "ACCA"
    if topic_val:
        return (
            f"Explain '{topic_val}' for {module_val} in exam-focused terms. "
            "Include: key rules/formulas, common mistakes, and 3 practice questions with short answers."
        )
    return (
        "Help me revise ACCA efficiently. Give a concise explanation, key formulas, "
        "and a short practice drill."
    )


def _summarize_older_tutor_messages(
    messages: list[dict[str, str]],
    max_items: int = 6,
    max_chars: int = 520,
) -> str:
    rows: list[str] = []
    try:
        item_cap = max(1, min(12, int(max_items)))
    except Exception:
        item_cap = 6
    try:
        char_cap = max(160, min(2000, int(max_chars)))
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
    older_messages = cleaned_history[:-recent_cap] if len(cleaned_history) > recent_cap else []
    recent_messages = cleaned_history[-recent_cap:]
    older_summary = _summarize_older_tutor_messages(older_messages)
    coverage_targets = extract_tutor_coverage_targets(user_prompt, max_targets=6)
    lines = [
        "You are a first-class local ACCA tutor embedded inside the StudyPlan app.",
        f"Module: {module_title or 'ACCA'}",
        f"Current chapter: {chapter or 'not selected'}",
        "Mission: maximize exam readiness per minute using the learner state and current syllabus context.",
        "Priority order: must-review pressure -> weak-topic repair -> retrieval practice -> formula accuracy -> exam-style clarity.",
        "Operate as the session pilot: diagnose gaps, prescribe actions, drill, and finish with a concrete next move.",
        "Use short sections, bullets, formulas when relevant, and exam-focused tips.",
        "Avoid generic motivation; be operational and exam-hard.",
        "When useful, end with one concrete next step (topic + mode + duration).",
        "If assumptions are required, state them explicitly.",
        "",
    ]
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
    }
    return prompt, meta


def build_ai_tutor_context_prompt(
    history: list[dict[str, str]],
    user_prompt: str,
    module_title: str,
    chapter: str,
) -> str:
    prompt, _meta = build_ai_tutor_context_prompt_details(
        history=history,
        user_prompt=user_prompt,
        module_title=module_title,
        chapter=chapter,
    )
    return prompt


def clean_ai_tutor_text(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return ""
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

    # Remove fenced code wrappers while preserving inner content.
    cleaned = re.sub(r"```[A-Za-z0-9_-]*\n?", "", cleaned)
    cleaned = cleaned.replace("```", "")

    # Common markdown cleanup.
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)

    # Convert common LaTeX fragments into readable plain text.
    cleaned = re.sub(r"\\{2,}", r"\\", cleaned)
    cleaned = cleaned.replace(r"\{", "{").replace(r"\}", "}")
    frac_pattern = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    for _ in range(8):
        nxt = frac_pattern.sub(lambda m: f"({m.group(1).strip()}/{m.group(2).strip()})", cleaned)
        if nxt == cleaned:
            break
        cleaned = nxt
    latex_literals = {
        r"\times": " x ",
        r"\cdot": " * ",
        r"\approx": "~",
        r"\leq": "<=",
        r"\geq": ">=",
        r"\neq": "!=",
        r"\%": "%",
        r"\$": "$",
        r"\_": "_",
        r"\#": "#",
        r"\&": "&",
        r"\{": "{",
        r"\}": "}",
        r"\(": "",
        r"\)": "",
        r"\[": "",
        r"\]": "",
    }
    for src, dst in latex_literals.items():
        cleaned = cleaned.replace(src, dst)

    # Remove lightweight math delimiters and normalize spacing.
    cleaned = cleaned.replace("$", "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def format_ai_tutor_transcript(history: list[dict[str, str]]) -> str:
    blocks: list[str] = []
    for msg in list(history or []):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "").strip().lower()
        content = str(msg.get("content", "") or "").strip()
        if role == "assistant":
            content = clean_ai_tutor_text(content)
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
        prompt_scroller = Gtk.ScrolledWindow()
        prompt_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        prompt_scroller.set_min_content_height(120)
        prompt_view = Gtk.TextView()
        prompt_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_buf = prompt_view.get_buffer()
        prompt_buf.set_text(
            build_ai_tutor_seed_prompt(
                topic=str(getattr(app, "current_topic", "") or "").strip(),
                module_title=str(getattr(app, "module_title", "ACCA") or "ACCA").strip(),
            )
        )
        prompt_scroller.set_child(prompt_view)
        content.append(quick_prompts_scroller)
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
        cockpit_status_label = Gtk.Label(label="Tutor cockpit: idle")
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
        for item in list(getattr(app, "_ai_tutor_history", []) or [])[-20:]:
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
            "autopilot_paused": False,
            "autopilot_busy": False,
            "autopilot_loop_id": 0,
            "autopilot_last_action_at": 0.0,
            "autopilot_action_window": [],
            "autopilot_last_nudge_at": 0.0,
            "autopilot_last_nudge_key": "",
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
        cockpit_pause_btn.set_tooltip_text("Pause or resume Tutor cockpit automation for this dialog.")

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

        def _render_transcript(force_scroll: bool = False) -> None:
            auto_scroll_enabled = bool(auto_scroll_toggle.get_active())
            should_keep_bottom = should_keep_response_bottom(
                auto_scroll_enabled=auto_scroll_enabled,
                force_scroll=bool(force_scroll),
                near_bottom=_response_is_near_bottom(56.0 if bool(run_state.get("active", False)) else 28.0),
            )
            entries: list[dict[str, str]] = list(history)
            if bool(run_state.get("active", False)):
                draft_user = str(run_state.get("draft_user", "") or "").strip()
                draft_assistant = str(run_state.get("draft_assistant", "") or "")
                if draft_user:
                    entries.append({"role": "user", "content": draft_user})
                if draft_assistant.strip():
                    entries.append({"role": "assistant", "content": draft_assistant})
            text = format_ai_tutor_transcript(entries)
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
            paused = bool(run_state.get("autopilot_paused", False))
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
            base = f"Tutor cockpit [{mode}]"
            detail = str(message or "").strip()
            cockpit_status_label.set_text(f"{base}: {detail}" if detail else base)

        def _consume_action_budget(now_ts: float) -> bool:
            window = []
            for ts in list(run_state.get("autopilot_action_window", []) or []):
                try:
                    value = float(ts)
                except Exception:
                    continue
                if (now_ts - value) <= float(getattr(app, "AI_TUTOR_AUTOPILOT_ACTION_WINDOW_SECONDS", 600) if hasattr(app, "AI_TUTOR_AUTOPILOT_ACTION_WINDOW_SECONDS") else 600):
                    window.append(value)
            limit = int(getattr(app, "AI_TUTOR_AUTOPILOT_MAX_ACTIONS_PER_WINDOW", 6) if hasattr(app, "AI_TUTOR_AUTOPILOT_MAX_ACTIONS_PER_WINDOW") else 6)
            if len(window) >= max(1, limit):
                run_state["autopilot_action_window"] = window
                return False
            window.append(float(now_ts))
            run_state["autopilot_action_window"] = window
            return True

        def _emit_nudge(severity: str, message: str) -> None:
            if not bool(getattr(app, "ai_tutor_nudges_enabled", True)):
                return
            now_ts = float(time.monotonic())
            policy = str(getattr(app, "ai_tutor_nudge_policy", "moderate") or "moderate").strip().lower()
            cooldown_map = {"minimal": 240, "moderate": 120, "aggressive": 60}
            cooldown = int(cooldown_map.get(policy, 120))
            last_at = float(run_state.get("autopilot_last_nudge_at", 0.0) or 0.0)
            key = f"{severity}:{str(message or '').strip()[:80]}"
            if key == str(run_state.get("autopilot_last_nudge_key", "") or "") and (now_ts - last_at) < float(cooldown):
                return
            run_state["autopilot_last_nudge_at"] = now_ts
            run_state["autopilot_last_nudge_key"] = key
            metric_key = "nudge_info_count"
            title = "Tutor Nudge"
            if severity == "warning":
                metric_key = "nudge_warning_count"
                title = "Tutor Warning"
            elif severity == "intervention":
                metric_key = "nudge_intervention_count"
                title = "Tutor Intervention"
            try:
                stats = dict(getattr(app, "_ai_tutor_autopilot_stats", {}) or {})
                app._record_ai_tutor_autopilot_metrics(
                    {metric_key: int(stats.get(metric_key, 0) or 0) + 1},
                    persist=False,
                )
            except Exception:
                pass
            try:
                app.send_notification(title, str(message or "").strip()[:220])
            except Exception:
                pass

        def _autopilot_tick() -> bool:
            if not bool(dialog.get_visible()):
                return False
            if not bool(getattr(app, "ai_tutor_autopilot_enabled", True)):
                _set_cockpit_status("disabled in Preferences")
                return True
            if bool(run_state.get("autopilot_paused", False)):
                _set_cockpit_status("paused")
                return True
            if bool(run_state.get("autopilot_busy", False)) or bool(run_state.get("active", False)):
                return True
            run_state["autopilot_busy"] = True

            def _worker() -> None:
                decision: dict[str, Any] | None = None
                decision_err: str | None = None
                action_message = ""
                executed = False
                blocked_reason = ""
                try:
                    snapshot = app._build_ai_tutor_autopilot_snapshot()
                    mode = _autopilot_mode()
                    try:
                        stats = dict(getattr(app, "_ai_tutor_autopilot_stats", {}) or {})
                        app._record_ai_tutor_autopilot_metrics(
                            {
                                "autopilot_mode": mode,
                                "autopilot_decision_count": int(stats.get("autopilot_decision_count", 0) or 0) + 1,
                            },
                            persist=False,
                        )
                    except Exception:
                        pass
                    must_due = int(snapshot.get("must_review_due", 0) or 0)
                    focus_info = snapshot.get("focus_trend_14d", {}) if isinstance(snapshot.get("focus_trend_14d", {}), dict) else {}
                    integrity = focus_info.get("integrity_pct")
                    if isinstance(integrity, (int, float)) and float(integrity) < 60.0:
                        _emit_nudge("warning", "Focus integrity is slipping. Stay in allowlisted apps for this block.")
                    if must_due >= 5:
                        _emit_nudge("intervention", f"{must_due} must-review items are due. Consider a short review burst now.")

                    decision, decision_err = app._request_ai_tutor_action_plan(snapshot)
                    if not isinstance(decision, dict):
                        decision = None
                        blocked_reason = "invalid_decision"
                    else:
                        action = str(decision.get("action", "") or "").strip().lower()
                        requires_confirmation = bool(decision.get("requires_confirmation", False))
                        if not bool(app._can_auto_execute_ai_tutor_action(action, mode, requires_confirmation)):
                            blocked_reason = "needs_confirmation_or_mode_block"
                            reason = str(decision.get("reason", "") or "").strip()
                            if reason:
                                _emit_nudge("info", f"Suggested: {action} — {reason}")
                        else:
                            now_ts = float(time.monotonic())
                            cooldown = 20.0
                            try:
                                last_action = float(run_state.get("autopilot_last_action_at", 0.0) or 0.0)
                            except Exception:
                                last_action = 0.0
                            if (now_ts - last_action) < cooldown:
                                blocked_reason = "action_cooldown"
                            elif not _consume_action_budget(now_ts):
                                blocked_reason = "action_rate_limit"
                            else:
                                ok, msg = app._execute_ai_tutor_action(decision)
                                action_message = str(msg or "").strip()
                                executed = bool(ok)
                                if ok:
                                    run_state["autopilot_last_action_at"] = now_ts
                                else:
                                    blocked_reason = action_message or "action_failed"
                except Exception as exc:
                    blocked_reason = str(exc)

                def _finish() -> bool:
                    run_state["autopilot_busy"] = False
                    stats = dict(getattr(app, "_ai_tutor_autopilot_stats", {}) or {})
                    updates: dict[str, Any] = {"autopilot_mode": _autopilot_mode()}
                    if executed:
                        updates["autopilot_action_executed_count"] = int(stats.get("autopilot_action_executed_count", 0) or 0) + 1
                        _set_cockpit_status(action_message or "action executed")
                        try:
                            app.send_notification("Tutor Cockpit", action_message or "Action executed.")
                        except Exception:
                            pass
                    else:
                        if blocked_reason:
                            updates["autopilot_action_blocked_count"] = int(stats.get("autopilot_action_blocked_count", 0) or 0) + 1
                            updates["autopilot_last_block_reason"] = blocked_reason
                        if decision_err:
                            _set_cockpit_status(f"fallback: {decision_err[:80]}")
                        elif blocked_reason:
                            _set_cockpit_status(f"blocked: {blocked_reason[:80]}")
                        else:
                            _set_cockpit_status("monitoring")
                    try:
                        app._record_ai_tutor_autopilot_metrics(updates, persist=False)
                    except Exception:
                        pass
                    return False

                GLib.idle_add(_finish, priority=GLib.PRIORITY_LOW)

            threading.Thread(target=_worker, daemon=True).start()
            return True

        def _toggle_autopilot_pause(*_args) -> None:
            if not bool(getattr(app, "ai_tutor_autopilot_enabled", True)):
                _set_cockpit_status("disabled in Preferences")
                return
            paused = not bool(run_state.get("autopilot_paused", False))
            run_state["autopilot_paused"] = paused
            cockpit_pause_btn.set_label("Resume Autopilot" if paused else "Pause Autopilot")
            if paused:
                _set_cockpit_status("paused")
            else:
                _set_cockpit_status("resumed")

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
        autopilot_tick_id: int | None = None
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

            threading.Thread(target=_worker, daemon=True).start()

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

            threading.Thread(target=_worker, daemon=True).start()
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
            topic = str(getattr(app, "current_topic", "") or "").strip() or "the current topic"
            module = str(getattr(app, "module_title", "ACCA") or "ACCA").strip()
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
            text = format_ai_tutor_transcript(history)
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
                            purpose="tutor",
                            available_models=available_models or None,
                            persist=True,
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
                            purpose="tutor",
                            model_override=None,
                            available_models=available_models or None,
                            persist=True,
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
            user_prompt = _current_prompt_text(strip=True)
            if not user_prompt:
                status_label.set_text("Enter a prompt first.")
                return
            turn_requested_at = float(time.monotonic())
            prompt_stage_started_at = float(time.monotonic())
            module_title = str(getattr(app, "module_title", "ACCA") or "ACCA").strip()
            chapter = str(getattr(app, "current_topic", "") or "").strip()
            full_prompt, prompt_meta = build_ai_tutor_context_prompt_details(
                history=history,
                user_prompt=user_prompt,
                module_title=module_title,
                chapter=chapter,
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
                rag_context, rag_meta = app._build_ai_tutor_rag_prompt_context(
                    user_prompt=user_prompt,
                    history=history,
                    top_k=rag_top_k,
                    char_budget_override=rag_char_budget_override,
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
            full_prompt = assemble_ai_tutor_turn_prompt(
                full_prompt,
                learning_context=context_block,
                rag_context=rag_context,
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
            prompt_chars = len(str(user_prompt or ""))
            try:
                prompt_tokens_est = int(app._estimate_ai_tutor_token_count(str(user_prompt or "")))
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
                payload = {
                    "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "model": str(model_name or "").strip(),
                    "outcome": str(outcome or "").strip().lower(),
                    "error_class": str(error_class or "").strip().lower(),
                    "autopilot_mode": str(autopilot_stats.get("autopilot_mode", getattr(app, "ai_tutor_autonomy_mode", "assist")) or "assist"),
                    "autopilot_decision_count": int(autopilot_stats.get("autopilot_decision_count", 0) or 0),
                    "autopilot_action_executed_count": int(autopilot_stats.get("autopilot_action_executed_count", 0) or 0),
                    "autopilot_action_blocked_count": int(autopilot_stats.get("autopilot_action_blocked_count", 0) or 0),
                    "autopilot_last_block_reason": str(autopilot_stats.get("autopilot_last_block_reason", "") or ""),
                    "nudge_info_count": int(autopilot_stats.get("nudge_info_count", 0) or 0),
                    "nudge_warning_count": int(autopilot_stats.get("nudge_warning_count", 0) or 0),
                    "nudge_intervention_count": int(autopilot_stats.get("nudge_intervention_count", 0) or 0),
                    "latency_ms": int(latency_ms),
                    "queue_ms": 0,
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
            status_parts = ["Generating…"]
            if condensed_count > 0:
                status_parts.append(f"context condensed: {condensed_count} older turn(s)")
            if context_budget_chars > 0:
                status_parts.append(f"CTX: {context_chars}/{context_budget_chars} chars")
            if coverage_target_count > 1:
                status_parts.append(f"Coverage targets: {coverage_target_count}")
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
            rag_errors = [err for err in rag_meta.get("errors", []) if err]
            if rag_errors:
                status_parts.append(f"RAG errors: {rag_errors[0][:72]}")
            if auto_model_note:
                status_parts.append(auto_model_note)
            if failover_note:
                status_parts.append(failover_note)
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

                def _finish():
                    if int(run_state.get("job_id", 0) or 0) != job_id:
                        return False
                    draft_user = str(run_state.get("draft_user", "") or "").strip()
                    draft_assistant = str(run_state.get("draft_assistant", "") or "").strip()
                    run_state["cancel_event"] = None
                    run_state["draft_user"] = ""
                    run_state["draft_assistant"] = ""
                    _set_running(False)
                    final_text = str(text or "").strip() or draft_assistant

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
                        )
                        suffix = "[Stopped]"
                        if bool(guard_state.get("timeout_hit", False)):
                            suffix = f"[Timed out after {int(turn_timeout_seconds)}s]"
                        elif bool(guard_state.get("truncated", False)):
                            suffix = f"[Truncated at {int(AI_TUTOR_MAX_RESPONSE_CHARS)} chars]"
                        if draft_user and final_text:
                            final_text = clean_ai_tutor_text(final_text) or final_text
                            history.append({"role": "user", "content": draft_user})
                            history.append({"role": "assistant", "content": f"{final_text}\n\n{suffix}"})
                            _persist_history()
                            if bool(guard_state.get("timeout_hit", False)):
                                status_label.set_text(f"Turn timed out after {int(turn_timeout_seconds)}s ({model_name}).")
                            elif bool(guard_state.get("truncated", False)):
                                status_label.set_text(
                                    f"Stopped at max length ({int(AI_TUTOR_MAX_RESPONSE_CHARS)} chars) • turns: {_turn_count()}"
                                )
                            else:
                                status_label.set_text(f"Stopped ({model_name}) • turns: {_turn_count()}")
                        else:
                            if bool(guard_state.get("timeout_hit", False)):
                                status_label.set_text(f"Turn timed out after {int(turn_timeout_seconds)}s ({model_name}).")
                            elif bool(guard_state.get("truncated", False)):
                                status_label.set_text(
                                    f"Stopped at max length ({int(AI_TUTOR_MAX_RESPONSE_CHARS)} chars)."
                                )
                            else:
                                status_label.set_text(f"Stopped ({model_name}).")
                        _render_transcript(force_scroll=True)
                        return False
                    if err:
                        _code, friendly = classify_ollama_error(err, host=app._normalize_ollama_host())
                        _record_turn_telemetry(
                            outcome="error",
                            error_class=_code,
                            response_text=final_text,
                        )
                        status_label.set_text(friendly)
                        _render_transcript()
                        return False
                    if draft_user and final_text:
                        final_text = clean_ai_tutor_text(final_text) or final_text
                        history.append({"role": "user", "content": draft_user})
                        history.append({"role": "assistant", "content": final_text})
                        _persist_history()
                    _record_turn_telemetry(
                        outcome="success",
                        error_class="",
                        response_text=final_text,
                    )
                    _render_transcript(force_scroll=True)
                    if int(coverage_state.get("target_count", 0) or 0) > 1:
                        status_label.set_text(
                            f"Done ({model_name}) • turns: {_turn_count()} • coverage {int(coverage_state.get('hit_count', 0) or 0)}/{int(coverage_state.get('target_count', 0) or 0)}"
                        )
                    else:
                        status_label.set_text(f"Done ({model_name}) • turns: {_turn_count()}")
                    return False

                GLib.idle_add(_finish)

            threading.Thread(target=_worker, daemon=True).start()

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
            if autopilot_tick_id:
                try:
                    GLib.source_remove(autopilot_tick_id)
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
        try:
            tick_reader = getattr(app, "_coerce_ai_tutor_autopilot_tick_seconds", None)
            tick_value = int(getattr(app, "ai_tutor_autopilot_tick_seconds", 45) or 45)
            if callable(tick_reader):
                tick_value = int(cast(Any, tick_reader(tick_value)))
            tick_value = max(15, min(180, int(tick_value)))
            autopilot_tick_id = GLib.timeout_add_seconds(tick_value, _autopilot_tick)
            _set_cockpit_status("active")
        except Exception:
            autopilot_tick_id = None
            _set_cockpit_status("unavailable")
