"""
Map a learner message to an LLM routing purpose for model selection.

``deep_reason`` prefers larger / higher-quality models when the prompt looks like
deep reasoning, proofs, code, or very long analysis. Falls back to ``tutor`` otherwise.

Disable with ``STUDYPLAN_TUTOR_DYNAMIC_MODEL_PURPOSE=0`` to always use ``tutor``.
"""
from __future__ import annotations

import os


def infer_tutor_llm_purpose(user_prompt: str) -> str:
    """Return ``deep_reason`` or ``tutor`` for ``_select_local_llm_model`` / failover."""
    raw = str(os.environ.get("STUDYPLAN_TUTOR_DYNAMIC_MODEL_PURPOSE", "") or "").strip().lower()
    if raw in {"0", "false", "no", "off", "disable", "disabled"}:
        return "tutor"
    text = str(user_prompt or "").strip()
    if len(text) >= 1100:
        return "deep_reason"
    lower = text.lower()
    # Deliberately conservative: avoid routing every short "why" question to a huge model.
    needles = (
        "prove ",
        "proof ",
        "theorem",
        "lemma",
        "formal proof",
        "by contradiction",
        "derive ",
        "derivation",
        "rigorous",
        "exhaustive",
        "in-depth",
        "in depth",
        "debug this",
        "stack trace",
        "recursion",
        "algorithm",
        "time complexity",
        "space complexity",
        "big-o",
        "big o",
        "induction",
        "contrapositive",
        "counterexample",
        "verify my working",
        "check my proof",
        "step-by-step derivation",
        "line by line",
    )
    if any(n in lower for n in needles):
        return "deep_reason"
    return "tutor"
