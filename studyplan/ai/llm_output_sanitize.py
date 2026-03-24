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
