from __future__ import annotations

import datetime

import pytest


gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # type: ignore[import-untyped]

from studyplan.ui import UIBuilder
from studyplan.ui.dashboard_cards import (
    build_data_health_content,
    build_daily_summary_card,
    build_exam_forecast_card,
    build_insight_lines_card,
    build_leech_alerts_card,
    build_multiline_text_card,
    build_mastery_snapshot_card,
    build_next_action_card,
    build_outcome_mastery_card,
    build_quiz_insights_card,
    build_reviews_due_today_card,
    build_reviews_pace_card,
    build_weak_vs_strong_card,
    build_study_hub_content,
)


def _walk_widgets(root: Gtk.Widget):
    stack = [root]
    while stack:
        widget = stack.pop()
        yield widget
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()


def _label_texts(root: Gtk.Widget) -> list[str]:
    texts: list[str] = []
    for w in _walk_widgets(root):
        if isinstance(w, Gtk.Label):
            txt = w.get_label()
            if isinstance(txt, str):
                texts.append(txt)
    return texts


def _button_labels(root: Gtk.Widget) -> list[str]:
    labels: list[str] = []
    for w in _walk_widgets(root):
        if isinstance(w, Gtk.Button):
            txt = w.get_label()
            if isinstance(txt, str):
                labels.append(txt)
    return labels


def _first_progress_bar(root: Gtk.Widget) -> Gtk.ProgressBar | None:
    for w in _walk_widgets(root):
        if isinstance(w, Gtk.ProgressBar):
            return w
    return None


class _FakeEngine:
    def __init__(self, payload):
        self._payload = payload

    def get_outcome_mastery_map(self):
        return self._payload


def test_build_exam_forecast_card_renders_expected_sections():
    ui = UIBuilder()
    today = datetime.date.today()
    points = [
        (today - datetime.timedelta(days=6), 40.0),
        (today, 49.0),
    ]
    card = build_exam_forecast_card(ui, 49.0, "behind", 8, points)

    assert isinstance(card, Gtk.Widget)
    texts = _label_texts(card)
    joined = "\n".join(texts)
    assert "Exam Forecast" in joined
    assert "Current readiness: 49%" in joined
    assert "Days remaining:" in joined
    assert "Status:" in joined
    assert any(t in joined for t in ("At risk", "Watchlist", "On course"))
    bar = _first_progress_bar(card)
    assert bar is not None
    assert str(bar.get_text() or "").startswith("Projected ")


def test_build_outcome_mastery_card_empty_state_message():
    ui = UIBuilder()
    engine = _FakeEngine({"total_outcomes": 0})
    card = build_outcome_mastery_card(ui, engine)
    texts = "\n".join(_label_texts(card))
    assert "Outcome Mastery" in texts
    assert "No syllabus outcomes loaded" in texts


def test_build_outcome_mastery_card_shows_coverage_and_capability_lines():
    ui = UIBuilder()
    engine = _FakeEngine(
        {
            "total_outcomes": 10,
            "covered_outcomes": 7,
            "uncovered_outcomes": 3,
            "coverage_pct": 70.0,
            "capabilities": {
                "analysis": {"total_outcomes": 4, "covered_outcomes": 2, "coverage_pct": 50.0},
                "evaluation": {"total_outcomes": 6, "covered_outcomes": 5, "coverage_pct": 83.0},
            },
        }
    )
    card = build_outcome_mastery_card(ui, engine)
    texts = "\n".join(_label_texts(card))
    assert "Outcome Mastery" in texts
    assert "Covered:" in texts
    assert "Uncovered:" in texts
    assert "analysis:" in texts or "evaluation:" in texts


def test_build_next_action_card_wires_button_labels_and_reason_rows():
    ui = UIBuilder()

    def _focus(*_args, **_kwargs):
        return None
    def _clear(*_args, **_kwargs):
        return None
    def _drill(*_args, **_kwargs):
        return None
    def _quiz(*_args, **_kwargs):
        return None

    card = build_next_action_card(
        ui,
        recommended_topic="Risk Management",
        weak_chapter="WACC",
        must_review_due=0,
        has_questions=True,
        pace_status="behind",
        on_focus_now=_focus,
        on_clear_must_review=_clear,
        on_drill_weak=_drill,
        on_quick_quiz=_quiz,
        format_ui_info_block_lines=lambda lines, **_kw: "\n".join(str(x) for x in lines),
        mark_wrapping_label=lambda *_a, **_k: None,
        enforce_label_single_line=lambda *_a, **_k: None,
        sync_single_line_label_tooltip=lambda *_a, **_k: None,
    )

    texts = "\n".join(_label_texts(card))
    buttons = _button_labels(card)
    assert "Next Best Action" in texts
    assert "Do:" in texts
    assert "Reason:" in texts
    assert "Pace:" in texts
    assert "Weak drill" in buttons
    assert "Quick quiz" in buttons


def test_build_weak_vs_strong_card_renders_both_groups():
    ui = UIBuilder()
    card = build_weak_vs_strong_card(
        ui,
        weak_lines=["- WACC: 42%", "- NPV: 50%"],
        strong_lines=["- Risk: 90%"],
        sync_single_line_label_tooltip=lambda *_a, **_k: None,
    )
    texts = "\n".join(_label_texts(card))
    assert "Weak vs Strong" in texts
    assert "Weakest" in texts
    assert "Strongest" in texts
    assert "- WACC: 42%" in texts
    assert "- Risk: 90%" in texts


def test_build_reviews_pace_card_renders_summary_lines():
    ui = UIBuilder()
    card = build_reviews_pace_card(
        ui,
        review_lines=[
            "Daily plan: 2/3 (67%)",
            "Overdue cards: 12",
            "Review load: 48h 5 • 7d 18",
            "Next due: 2026-02-27",
        ],
        format_ui_info_block_lines=lambda lines, **_kw: "\n".join(lines),
    )
    texts = "\n".join(_label_texts(card))
    assert "Reviews & Pace" in texts
    assert "Daily plan: 2/3 (67%)" in texts
    assert "Overdue cards: 12" in texts


def test_build_reviews_due_today_card_renders_lines():
    ui = UIBuilder()
    card = build_reviews_due_today_card(
        ui,
        lines=["Total due: 22", "1. Risk — 8", "2. WACC — 5"],
        format_ui_info_block_lines=lambda lines, **_kw: "\n".join(lines),
    )
    texts = "\n".join(_label_texts(card))
    assert "Reviews Due Today" in texts
    assert "Total due: 22" in texts
    assert "1. Risk — 8" in texts


def test_build_leech_alerts_card_renders_lines():
    ui = UIBuilder()
    card = build_leech_alerts_card(
        ui,
        lines=["Total flagged: 4", "1. NPV — 2"],
        format_ui_info_block_lines=lambda lines, **_kw: "\n".join(lines),
    )
    texts = "\n".join(_label_texts(card))
    assert "Leech Alerts" in texts
    assert "Total flagged: 4" in texts
    assert "1. NPV — 2" in texts


def test_build_mastery_snapshot_card_renders_lines():
    ui = UIBuilder()
    card = build_mastery_snapshot_card(
        ui,
        mastery_lines=[
            "Overall mastery: 68.2%",
            "Questions: 420",
            "Mastered/Learning/New: 120 / 210 / 90",
            "Avg interval: 4.2 days",
            "Avg ease: 2.31",
        ],
        format_ui_info_block_lines=lambda lines, **_kw: "\n".join(lines),
    )
    texts = "\n".join(_label_texts(card))
    assert "Mastery Snapshot" in texts
    assert "Overall mastery: 68.2%" in texts
    assert "Avg interval: 4.2 days" in texts


def test_build_study_hub_content_renders_optional_sections():
    ui = UIBuilder()
    content = build_study_hub_content(
        ui,
        summary_lines=[
            "Questions answered: 120/300 (40%)",
            "Estimated remaining: 900 min",
            "Questions/day target: 15.0",
        ],
        age_line="Data age: 2 days",
        category_lines_text="- Finance: 30%\n- Risk: 45%",
        chapter_lines_text="- WACC: 35%\n- NPV: 48%",
        format_ui_info_block_lines=lambda lines, **_kw: "\n".join(lines),
    )
    texts = "\n".join(_label_texts(content))
    assert "Questions answered: 120/300 (40%)" in texts
    assert "Data age: 2 days" in texts
    assert "Categories (weakest):" in texts
    assert "By Chapter (weakest):" in texts


def test_build_data_health_content_renders_lines():
    ui = UIBuilder()
    content = build_data_health_content(
        ui,
        health_lines=[
            "Data Health",
            "- Competence fixed: 2",
            "- SRS fixed: 0",
        ],
        format_ui_info_block_lines=lambda lines, **_kw: "\n".join(lines),
    )
    texts = "\n".join(_label_texts(content))
    assert "Data Health" in texts
    assert "- Competence fixed: 2" in texts


def test_build_insight_lines_card_renders_title_and_lines():
    ui = UIBuilder()
    card = build_insight_lines_card(
        ui,
        title_text="Focus Topics (7 days)",
        lines=["1. Risk — 45m", "2. WACC — 30m"],
    )
    texts = "\n".join(_label_texts(card))
    assert "Focus Topics (7 days)" in texts
    assert "1. Risk — 45m" in texts
    assert "2. WACC — 30m" in texts


def test_build_daily_summary_card_renders_capped_single_line_entries():
    ui = UIBuilder()
    card = build_daily_summary_card(
        ui,
        summary_lines=["A", "B", "C", "D"],
        sync_single_line_label_tooltip=lambda *_a, **_k: None,
    )
    texts = _label_texts(card)
    assert "Daily Summary" in texts
    assert "A" in texts and "B" in texts and "C" in texts
    assert "D" not in texts


def test_build_multiline_text_card_renders_and_applies_flags():
    ui = UIBuilder()
    card = build_multiline_text_card(
        ui,
        title_text="Coach Recap (7 days)",
        lines=["Total focus time: 120 min", "Mastery change: +2.1%"],
        insight_card=True,
        add_dashboard_body_class=False,
    )
    assert "insight-card" in list(card.get_css_classes())
    texts = "\n".join(_label_texts(card))
    assert "Coach Recap (7 days)" in texts
    assert "Total focus time: 120 min" in texts


def test_build_quiz_insights_card_renders_risk_and_detail_rows():
    ui = UIBuilder()
    card = build_quiz_insights_card(
        ui,
        risk_lines=["1. WACC — miss-risk 72% • 18 Qs"],
        detail_rows=[
            {"text": "Recall model: sklearn • Difficulty model: heuristic"},
            {"text": "ML confidence: low • samples 12", "warn": True},
            {"text": "Top-risk chapter ML (WACC): fallback • 42% • 12/45 Qs", "single_line": True},
        ],
    )
    texts = "\n".join(_label_texts(card))
    assert "Quiz Insights" in texts
    assert "miss-risk 72%" in texts
    assert "ML confidence: low" in texts
