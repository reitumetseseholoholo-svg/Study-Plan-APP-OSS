"""Tests for tutor memory: context packet and format line."""
from __future__ import annotations

import datetime
import types

import pytest

from studyplan.tutor_memory import (
    build_tutor_context_packet,
    confidence_guidance_line,
    format_tutor_context_line,
)


def test_build_tutor_context_packet_basic() -> None:
    engine = types.SimpleNamespace(
        CHAPTERS=["Ch1", "Ch2"],
        competence={"Ch1": 45.0, "Ch2": 80.0},
        quiz_results={"Ch1": 40.0, "Ch2": 75.0},
        get_syllabus_chapter_intelligence=lambda ch: (
            {"learning_outcomes": [{"id": "F.2.1", "text": "Explain NPV"}]}
            if ch == "Ch1"
            else {}
        ),
    )
    packet = build_tutor_context_packet(engine, "Ch1", topic="NPV", recent_activity=[])
    assert packet["topic"] == "NPV"
    assert packet["chapter"] == "Ch1"
    assert packet["competence_pct"] == 45.0
    assert packet["quiz_pct"] == 40.0
    assert "Ch1" in packet["weak_areas_top3"] or "Ch2" in packet["weak_areas_top3"]
    assert packet["outcome_ids"] == ["F.2.1"]


def test_format_tutor_context_line() -> None:
    packet = {
        "topic": "NPV",
        "chapter": "Ch1",
        "competence_pct": 40.0,
        "quiz_pct": 35.0,
        "weak_areas_top3": ["Ch1", "Ch2"],
        "recent_study_last_3_days": ["Ch1 (explain)"],
        "outcome_ids": ["F.2.1"],
        "confidence_drift_pct": 15.0,
    }
    line = format_tutor_context_line(packet)
    assert "[STUDENT CONTEXT]" in line
    assert "Topic: NPV" in line
    assert "Competence: 40%" in line
    assert "Ch1" in line
    line_short = format_tutor_context_line(packet, max_chars=100)
    assert len(line_short) <= 103


def test_confidence_guidance_line() -> None:
    low = confidence_guidance_line(30)
    assert "low" in low.lower()
    assert "simpler" in low.lower()
    mid = confidence_guidance_line(55)
    assert "medium" in mid.lower()
    high = confidence_guidance_line(85)
    assert "high" in high.lower()
    assert "deeper" in high.lower() or "probing" in high.lower()


def test_build_packet_with_recent_activity() -> None:
    today = datetime.date.today()
    engine = types.SimpleNamespace(
        CHAPTERS=["Ch1"],
        competence={"Ch1": 50.0},
        quiz_results={},
        get_syllabus_chapter_intelligence=lambda ch: {},
    )
    activity = [
        {"at": (today - datetime.timedelta(days=1)).isoformat(), "chapter": "Ch1", "topic": "NPV", "actions": "explain", "confidence_feedback": "ok", "summary": "Asked about timing"},
    ]
    packet = build_tutor_context_packet(engine, "Ch1", recent_activity=activity)
    assert len(packet["recent_study_last_3_days"]) >= 1
