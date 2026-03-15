"""
Tutor memory: hybrid context for personalized explanations.

- TutorContextPacket: lightweight data built from engine (topic, competence, weak areas,
  recent activity, outcomes, confidence drift). No new storage; uses existing engine data.
- format_tutor_context_line(): single-line [STUDENT CONTEXT] for prompt injection.
- Used so the tutor tailors explanations to the learner's level and gaps.
"""
from __future__ import annotations

import datetime
from typing import Any

EngineLike = Any


def build_tutor_context_packet(
    engine: EngineLike,
    chapter: str,
    topic: str | None = None,
    recent_activity: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Build a lightweight context packet from engine data for tutor prompt injection.

    Captures: topic/chapter, competence %, quiz performance, top 3 weak areas,
    recent study (last 3 days), syllabus outcomes for the topic, confidence drift.
    """
    chapter = str(chapter or "").strip()
    topic = str(topic or chapter or "").strip() or chapter
    comp_map = getattr(engine, "competence", {}) or {}
    if not isinstance(comp_map, dict):
        comp_map = {}
    competence_pct = max(0.0, min(100.0, float(comp_map.get(chapter, 0) or 0)))

    quiz_results = getattr(engine, "quiz_results", {}) or {}
    if not isinstance(quiz_results, dict):
        quiz_results = {}
    quiz_pct = max(0.0, min(100.0, float(quiz_results.get(chapter, 0) or 0)))

    chapters = list(getattr(engine, "CHAPTERS", []) or [])
    if not isinstance(chapters, list):
        chapters = []
    comp_rows = [(ch, float(comp_map.get(ch, 0) or 0)) for ch in chapters if ch]
    comp_rows.sort(key=lambda x: (x[1], x[0]))
    weak_areas_top3 = [ch for ch, _ in comp_rows[:3]]

    recent_study: list[str] = []
    activity = list(recent_activity or [])
    today = datetime.date.today()
    three_days_ago = today - datetime.timedelta(days=3)
    for entry in activity:
        if not isinstance(entry, dict):
            continue
        try:
            ts = entry.get("at") or entry.get("timestamp") or entry.get("date")
            if ts is None:
                continue
            if isinstance(ts, (int, float)):
                dt = datetime.datetime.fromtimestamp(float(ts)).date()
            else:
                s = str(ts).strip()
                if len(s) <= 10 and "-" in s:
                    dt = datetime.date.fromisoformat(s)
                else:
                    dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except Exception:
            continue
        if dt < three_days_ago:
            continue
        ch = str(entry.get("chapter") or entry.get("topic") or "").strip()
        action = str(entry.get("action") or entry.get("actions") or "study").strip()
        conf = entry.get("confidence_feedback") or entry.get("confidence") or ""
        if ch:
            part = f"{ch}"
            if action:
                part += f" ({action})"
            if conf:
                part += f" [{conf}]"
            recent_study.append(part)
    recent_study = recent_study[-5:]

    outcome_ids: list[str] = []
    try:
        intel = engine.get_syllabus_chapter_intelligence(chapter) if hasattr(engine, "get_syllabus_chapter_intelligence") else {}
        if isinstance(intel, dict):
            los = intel.get("learning_outcomes") or []
            if isinstance(los, list):
                for o in los:
                    if isinstance(o, dict) and o.get("id"):
                        outcome_ids.append(str(o.get("id", "")).strip())
                    elif isinstance(o, dict) and o.get("text"):
                        outcome_ids.append(str(o.get("text", ""))[:40].strip())
    except Exception:
        pass
    outcome_ids = outcome_ids[:6]

    confidence_drift_pct: float | None = None
    try:
        drift_getter = getattr(engine, "get_semantic_drift_kpi_by_chapter", None)
        if callable(drift_getter):
            by_ch = drift_getter(days=14) or {}
            row = by_ch.get(chapter) if isinstance(by_ch, dict) else None
            if isinstance(row, dict) and "gap_pct" in row:
                confidence_drift_pct = max(0.0, float(row.get("gap_pct", 0) or 0))
    except Exception:
        pass

    return {
        "topic": topic,
        "chapter": chapter,
        "competence_pct": round(competence_pct, 1),
        "quiz_pct": round(quiz_pct, 1),
        "weak_areas_top3": weak_areas_top3[:3],
        "recent_study_last_3_days": recent_study,
        "outcome_ids": outcome_ids,
        "confidence_drift_pct": confidence_drift_pct,
    }


def format_tutor_context_line(packet: dict[str, Any], max_chars: int = 480) -> str:
    """
    Format the context packet as a single line for [STUDENT CONTEXT] prompt injection.

    Example: [STUDENT CONTEXT] Topic: NPV | Chapter: F.2.1 | Competence: 40% | Weak areas: Ch1, Ch2 | Recent: 2d ago working capital (low) | Outcomes: F.2.1, F.2.2 | Confidence drift: 15%
    """
    if not isinstance(packet, dict):
        return ""
    topic = str(packet.get("topic") or "").strip()
    chapter = str(packet.get("chapter") or "").strip()
    comp = packet.get("competence_pct")
    comp_s = f"{float(comp):.0f}%" if comp is not None else "—"
    quiz = packet.get("quiz_pct")
    quiz_s = f"{float(quiz):.0f}%" if quiz is not None else "—"
    weak = packet.get("weak_areas_top3") or []
    weak_s = ", ".join(str(w)[:20] for w in weak[:3]) if weak else "—"
    recent = packet.get("recent_study_last_3_days") or []
    if recent:
        recent_s = "; ".join(str(r)[:50] for r in recent[-3:])
    else:
        recent_s = "—"
    outcomes = packet.get("outcome_ids") or []
    out_s = ", ".join(str(o)[:16] for o in outcomes[:4]) if outcomes else "—"
    drift = packet.get("confidence_drift_pct")
    drift_s = f"{float(drift):.0f}%" if drift is not None else "—"

    line = (
        f"[STUDENT CONTEXT] Topic: {topic or '—'} | Chapter: {chapter or '—'} | "
        f"Competence: {comp_s} | Quiz: {quiz_s} | Weak areas: {weak_s} | "
        f"Recent: {recent_s} | Outcomes: {out_s} | Confidence drift: {drift_s}"
    )
    line = line.replace("\n", " ").strip()
    if max_chars > 0 and len(line) > max_chars:
        line = line[: max_chars - 3].rstrip() + "..."
    return line


def confidence_guidance_line(competence_pct: float) -> str:
    """
    Return one-line guidance for explanation depth based on learner confidence/competence.

    Low competence -> simpler language, more examples. High -> go deeper, probe, test application.
    """
    try:
        pct = max(0.0, min(100.0, float(competence_pct)))
    except Exception:
        pct = 50.0
    if pct < 40:
        return (
            "Learner confidence for this topic: low. Use simpler language, more worked examples, "
            "and step-by-step reasoning. Avoid jargon until concepts are established."
        )
    if pct < 70:
        return (
            "Learner confidence for this topic: medium. Balance clarity with depth; "
            "include one short example and one quick check."
        )
    return (
        "Learner confidence for this topic: high. Go deeper, ask probing questions, "
        "and test application; challenge overconfidence with a harder follow-up where useful."
    )
