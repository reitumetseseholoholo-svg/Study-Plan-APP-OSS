"""
Heuristic outcome linking: assign outcome_ids to questions using lexical + structure only (no LLM).

Used by the "Refresh syllabus intelligence & link outcomes" pipeline to improve
outcome coverage without AI calls. Only updates questions that are persisted to
questions.json (added questions); built-in default questions are not modified.
"""

from __future__ import annotations

import re
from typing import Any

# Engine type: any object with CHAPTERS, QUESTIONS, QUESTIONS_DEFAULT, get_syllabus_chapter_intelligence, save_questions.
EngineLike = Any


def _tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, min length 2."""
    return {m.lower() for m in re.findall(r"[a-z0-9]{2,}", (text or "").lower()) if m}


def _lexical_score(question_text: str, outcome_text: str) -> float:
    """Simple overlap score 0..1 (precision-style: share of question tokens in outcome)."""
    q_tok = _tokens(question_text)
    o_tok = _tokens(outcome_text)
    if not q_tok:
        return 0.0
    overlap = len(q_tok & o_tok) / len(q_tok)
    if q_tok & o_tok and outcome_text.strip().lower() in (question_text or "").strip().lower():
        overlap = min(1.0, overlap + 0.2)
    return round(overlap, 4)


def link_questions_to_outcomes_heuristic(
    engine: EngineLike,
    *,
    top_k: int = 1,
    min_score: float = 0.08,
    skip_if_already_linked: bool = True,
) -> dict[str, Any]:
    """
    For each "added" question (in questions.json), assign up to top_k outcome_ids
    from the same chapter using lexical similarity. Only touches questions that
    are not in QUESTIONS_DEFAULT so that save_questions() persists them.

    Returns a summary: questions_linked, outcomes_covered, chapters_updated, errors.
    """
    summary: dict[str, Any] = {
        "questions_linked": 0,
        "questions_skipped_already_linked": 0,
        "questions_skipped_low_score": 0,
        "outcomes_covered": set(),
        "chapters_updated": set(),
        "errors": [],
    }
    chapters = getattr(engine, "CHAPTERS", None) or []
    if not isinstance(chapters, list) or not chapters:
        summary["errors"].append("no chapters")
        return _serialize_summary(summary)

    for chapter in chapters:
        info = None
        try:
            info = engine.get_syllabus_chapter_intelligence(chapter)
        except Exception as e:
            summary["errors"].append(f"{chapter}: {e!s}")
            continue
        if not isinstance(info, dict):
            continue
        outcomes = info.get("learning_outcomes") or info.get("outcomes") or []
        if not isinstance(outcomes, list) or not outcomes:
            continue

        questions = getattr(engine, "QUESTIONS", {}).get(chapter) or []
        default_questions = getattr(engine, "QUESTIONS_DEFAULT", {}).get(chapter) or []
        default_count = len(default_questions)
        if default_count >= len(questions):
            continue

        outcome_list = [
            (str(o.get("id", "")).strip(), str(o.get("text", "")).strip())
            for o in outcomes
            if isinstance(o, dict) and str(o.get("id", "")).strip() and str(o.get("text", "")).strip()
        ]
        if not outcome_list:
            continue

        for idx in range(default_count, len(questions)):
            q = questions[idx] if idx < len(questions) else None
            if not isinstance(q, dict):
                continue
            if skip_if_already_linked:
                existing = q.get("outcome_ids") or q.get("outcomes")
                if existing and (isinstance(existing, list) and len(existing) > 0 or isinstance(existing, dict)):
                    summary["questions_skipped_already_linked"] += 1
                    continue
            q_text = str(q.get("question", "") or q.get("text", "") or "").strip()
            if not q_text:
                continue
            scored: list[tuple[float, str]] = []
            for oid, o_text in outcome_list:
                score = _lexical_score(q_text, o_text)
                if score >= min_score:
                    scored.append((score, oid))
            if not scored:
                summary["questions_skipped_low_score"] += 1
                continue
            scored.sort(key=lambda x: (-x[0], x[1]))
            chosen = [oid for _, oid in scored[:top_k]]
            if not chosen:
                continue
            q["outcome_ids"] = chosen
            # Persist best lexical score as link confidence (0..1) for stable outcome ids + confidence
            best_score = scored[0][0]
            q["outcome_link_confidence"] = round(max(0.0, min(1.0, float(best_score))), 4)
            summary["questions_linked"] += 1
            summary["outcomes_covered"].update(chosen)
            summary["chapters_updated"].add(chapter)

    try:
        engine.save_questions()
    except Exception as e:
        summary["errors"].append(f"save_questions: {e!s}")

    return _serialize_summary(summary)


def _serialize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    out["outcomes_covered"] = len(out.get("outcomes_covered") or set())
    out["chapters_updated"] = list(out.get("chapters_updated") or set())
    return out


def auto_refresh_syllabus_and_link_outcomes(
    engine: EngineLike,
    *,
    rebuild_concept_graph: bool = True,
    link_top_k: int = 1,
    link_min_score: float = 0.08,
) -> dict[str, Any]:
    """
    One-shot pipeline: rebuild concept graph (so outcome/concept data is fresh),
    then run heuristic outcome linking. Does not run RAG reconfig (call that separately
    if syllabus_structure needs refreshing).

    Returns combined summary: concept_graph_built, linking summary, errors.
    """
    summary: dict[str, Any] = {
        "concept_graph_built": False,
        "linking": {},
        "errors": [],
    }
    if rebuild_concept_graph:
        try:
            engine.build_canonical_concept_graph(force=True)
            summary["concept_graph_built"] = True
        except Exception as e:
            summary["errors"].append(f"concept_graph: {e!s}")

    link_summary = link_questions_to_outcomes_heuristic(
        engine,
        top_k=link_top_k,
        min_score=link_min_score,
        skip_if_already_linked=True,
    )
    summary["linking"] = link_summary
    if link_summary.get("errors"):
        summary["errors"].extend(link_summary.get("errors") or [])
    return summary
