"""Strip model \"thinking\" / chain-of-thought traces from visible LLM output."""
from __future__ import annotations

import os
import re
from typing import Any


def _paired_xmlish_tags(names: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    out: list[re.Pattern[str]] = []
    for name in names:
        o = re.escape("<" + name + ">")
        c = re.escape("</" + name + ">")
        out.append(re.compile(o + r".*?" + c, re.DOTALL | re.IGNORECASE))
    return tuple(out)


_THINK_PAIR_PATTERNS: tuple[re.Pattern[str], ...] = _paired_xmlish_tags(
    ("think", "reasoning", "analysis", "redacted_reasoning", "thought")
)


def ollama_think_request_value_for_section_c_judgment(model_name: str) -> Any | None:
    """Optional Ollama ``think`` override for Section C second-pass (borderline) grading.

    When ``STUDYPLAN_SECTION_C_JUDGMENT_THINKING`` is enabled, returns a value suitable for
    reasoning-oriented local models. Return ``None`` to keep the default
    :func:`ollama_think_request_value` behaviour for that model.
    """
    if str(os.environ.get("STUDYPLAN_SECTION_C_JUDGMENT_THINKING", "") or "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    m = str(model_name or "").strip().lower()
    if "gpt-oss" in m or "gpt_oss" in m:
        return "high"
    if "deepseek" in m and "r1" in m:
        return True
    if "qwen" in m and "think" in m:
        return True
    if "magistral" in m or "reasoning" in m:
        return True
    return True


def ollama_think_request_value(model_name: str) -> Any | None:
    """Top-level ``think`` for Ollama ``/api/generate``. ``None`` = omit field.

    Default disables thinking for faster UX and so traces never appear in the UI.
    Set ``STUDYPLAN_OLLAMA_ALLOW_THINKING=1`` to omit the field (server/model default).
    """
    if str(os.environ.get("STUDYPLAN_OLLAMA_ALLOW_THINKING", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    m = str(model_name or "").strip().lower()
    if "gpt-oss" in m or "gpt_oss" in m:
        return "low"
    return False


def strip_thinking_traces(text: str) -> str:
    """Remove common reasoning wrappers; safe to call on any string."""
    s = str(text or "")
    if not s:
        return ""
    prev = None
    while prev != s:
        prev = s
        for pat in _THINK_PAIR_PATTERNS:
            s = pat.sub("", s)
    lb, rb = chr(60), chr(62)
    for name in ("think", "reasoning", "redacted_reasoning"):
        s = re.sub(re.escape(lb + name + rb) + r"\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*" + re.escape(lb + "/" + name + rb), "", s, flags=re.IGNORECASE)
    return s.strip()


def _strip_leading_instructor_planner(text: str) -> str:
    """Remove a leading 'planning' paragraph some models emit before the real answer."""
    t = str(text or "")
    if len(t) < 100:
        return t
    head = t[:1400].lower()
    hints = (
        "learner is asking",
        "the user is asking",
        "you're asking",
        "the learner wants",
        "the answer should be",
        "i will structure",
        "here's how i'll",
        "the user is likely",
    )
    if not any(h in head for h in hints):
        return t
    for anchor in (
        "\n(1) Direct",
        "\n(1) ",
        "\n(1)",
        "\n# ",
        "\n## ",
        "\nAnswer:\n",
        "\nAnswer:",
        "\n**Answer",
    ):
        idx = t.find(anchor)
        if idx >= 20:
            return t[idx + 1 :].lstrip() if anchor.startswith("\n") else t[idx:].lstrip()
    return t


def strip_tutor_meta_tail(text: str) -> str:
    """Drop repetitive debrief / session-footer blocks local models often append."""
    s = str(text or "")
    if not s:
        return ""
    debrief_markers = (
        "\nWhy this works",
        "\nEnd of Session",
        "\n---\nNext:",
        "\nFinal Note:",
        "\nExam Focus:",
        "\nFinal Check:",
        "\n**Final Answer",
        "\n---\n**Final",
        "\nIf the learner answers",
        "\nNext: If the learner",
    )
    cut = len(s)
    for m in debrief_markers:
        i = s.find(m)
        if i != -1 and i > 40:
            cut = min(cut, i)
    s = s[:cut].rstrip() if cut < len(s) else s
    # Trailing horizontal-rule stacks
    s = re.sub(r"(?:\n\s*---\s*){2,}\s*\Z", "\n", s)
    return s.strip()


def polish_tutor_answer_prose(text: str) -> str:
    """Tutor-only: drop planning monologue + repetitive session footers (after thinking strips)."""
    s = _strip_leading_instructor_planner(str(text or ""))
    return strip_tutor_meta_tail(s)


def sanitize_visible_local_llm_answer(text: str) -> str:
    """Single entry for removing thinking/reasoning wrappers from local LLM text.

    Call this (or :func:`strip_thinking_traces`, which it wraps) before any
    user-visible formatting. Tutor surfaces should use
    ``studyplan_ai_tutor.clean_ai_tutor_text``, which applies this first, then
    :func:`polish_tutor_answer_prose`, then LaTeX/markdown/disclaimer cleanup.
    The Ollama non-streaming client applies this to raw ``response`` text before
    caching and downstream use (tutor polish is *not* applied there on purpose).
    """
    return strip_thinking_traces(text)
