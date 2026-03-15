"""
Complete truncated syllabus learning outcomes using AI.

Used during the scheduled syllabus refresh (PDF re-parse or RAG reconfig): after
outcomes are extracted, any outcome text that looks truncated (e.g. ends with "...",
or is very short, or ends mid-sentence) is sent to the LLM to produce a complete
sentence. The updated config is then saved so the syllabus has full outcome text.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

# Config is a module config dict with syllabus_structure: { chapter: { learning_outcomes: [ {id, text, level}, ... ] } }.
# llm_generate: (prompt: str, max_tokens: int) -> str


def is_truncated_outcome_text(text: str) -> bool:
    """
    Return True if the outcome text looks truncated and should be completed by AI.

    Truncation signals: ends with "..." or "…"; very short (< 25 chars) with no
    sentence-ending punctuation; ends with a comma or "and" or "or" (mid-sentence).
    """
    if not text or not isinstance(text, str):
        return False
    t = text.strip()
    if len(t) < 12:
        return False
    # Explicit ellipsis
    if t.endswith("...") or t.endswith("…") or re.search(r"\.\.\.\s*$", t) or re.search(r"…\s*$", t):
        return True
    # Very short and no final punctuation
    if len(t) < 25 and t[-1] not in ".!?":
        return True
    # Ends mid-sentence (comma, or trailing "and"/"or" without period)
    if t[-1] in ",;" or re.search(r"\b(and|or|the|a|to)\s*$", t, re.IGNORECASE):
        return True
    # No sentence-ending punctuation for longer text (likely cut off)
    if len(t) >= 40 and t[-1] not in ".!?":
        return True
    return False


def _prompt_for_completion(chapter: str, truncated_text: str, outcome_id: str = "") -> str:
    """Build a single prompt asking the model to complete the outcome sentence."""
    id_hint = f" (outcome id: {outcome_id})" if outcome_id else ""
    return (
        "Complete this ACCA syllabus learning outcome so it is one full, grammatically correct sentence. "
        "Return only the completed sentence, no explanation, no quotes, no prefix.\n\n"
        f"Chapter: {chapter}{id_hint}\n"
        f"Truncated text: {truncated_text}\n\n"
        "Completed outcome:"
    )


def complete_truncated_syllabus_outcomes(
    config: dict[str, Any],
    llm_generate: Callable[[str, int], str],
    *,
    max_tokens: int = 256,
    max_to_complete: int = 50,
) -> tuple[dict[str, Any], int]:
    """
    Find learning outcomes with truncated text, call the LLM to complete each,
    and return an updated config and the number of outcomes completed.

    llm_generate(prompt, max_tokens) -> str. If it returns empty or invalid,
    the original outcome text is left unchanged.
    """
    if not isinstance(config, dict):
        return config, 0
    structure = config.get("syllabus_structure")
    if not isinstance(structure, dict):
        return config, 0

    config = copy.deepcopy(config)
    structure = config.setdefault("syllabus_structure", {})
    completed = 0
    to_process: list[tuple[str, int, dict[str, Any]]] = []  # (chapter, outcome_index, outcome)

    for chapter, info in structure.items():
        if not isinstance(info, dict):
            continue
        los = info.get("learning_outcomes")
        if not isinstance(los, list):
            continue
        for idx, outcome in enumerate(los):
            if not isinstance(outcome, dict):
                continue
            text = str(outcome.get("text") or "").strip()
            if not text or not is_truncated_outcome_text(text):
                continue
            to_process.append((chapter, idx, outcome))

    if not to_process:
        return config, 0
    if len(to_process) > max_to_complete:
        to_process = to_process[:max_to_complete]

    for chapter, idx, outcome in to_process:
        text = str(outcome.get("text") or "").strip()
        oid = str(outcome.get("id") or "").strip()
        prompt = _prompt_for_completion(chapter, text, oid)
        try:
            raw = llm_generate(prompt, max_tokens)
        except Exception:
            continue
        raw = (raw or "").strip()
        # Strip surrounding quotes and common prefixes
        raw = re.sub(r"^[\"']+|[\"']\s*$", "", raw)
        raw = re.sub(r"^Completed outcome:\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^Completed:\s*", "", raw, flags=re.IGNORECASE)
        raw = raw.strip()
        if len(raw) > len(text) and len(raw) <= 500:
            structure[chapter]["learning_outcomes"][idx]["text"] = raw
            completed += 1

    return config, completed
