"""Dashboard card builders extracted from the main app for UI refactoring."""

from __future__ import annotations

import datetime
from typing import Any, Callable

from gi.repository import Gtk, Pango  # type: ignore[reportMissingImports,reportAttributeAccessIssue,import-untyped]

from studyplan.ui_builder import UIBuilder


def build_exam_forecast_card(
    ui: UIBuilder,
    readiness_score: float,
    pace_status: str,
    days_remaining: int | None,
    trend_points: list[tuple[datetime.date, float]],
) -> Gtk.Widget:
    """Build the Exam Forecast dashboard card (presentation + deterministic projection)."""
    card = ui.vbox(spacing=6)
    card.add_css_class("card")
    card.add_css_class("card-tight")
    title = ui.section_title("Exam Forecast")
    card.append(title)

    daily_slope = 0.0
    trend_7d = 0.0
    points = list(trend_points or [])
    if len(points) >= 2:
        span_days = max(1, (points[-1][0] - points[0][0]).days)
        daily_slope = (points[-1][1] - points[0][1]) / float(span_days)
        cutoff_7d = datetime.date.today() - datetime.timedelta(days=6)
        recent = [p for p in points if p[0] >= cutoff_7d]
        if len(recent) >= 2:
            trend_7d = recent[-1][1] - recent[0][1]

    projected = float(readiness_score)
    if isinstance(days_remaining, int):
        projected += daily_slope * float(days_remaining) * 0.6
    if pace_status == "behind":
        projected -= 5.0
    elif pace_status == "ahead":
        projected += 3.0
    projected = max(0.0, min(100.0, projected))

    if projected >= 85:
        status = "On course"
    elif projected >= 70:
        status = "Watchlist"
    else:
        status = "At risk"

    bar = ui.progress_bar(show_text=True)
    bar.set_hexpand(True)
    bar.set_fraction(projected / 100.0)
    bar.set_text(f"Projected {projected:.0f}%")
    bar.set_tooltip_text(
        f"Projected readiness: {projected:.0f}% (current {float(readiness_score):.0f}%)"
    )

    stats_row = ui.hbox(spacing=8)
    stats_row.set_hexpand(True)
    current_label = ui.label(
        f"Current readiness: {float(readiness_score):.0f}%",
        css_classes=["status-line", "single-line-lock"],
        ellipsize=Pango.EllipsizeMode.END,
        max_width_chars=48,
    )
    stats_row.append(current_label)
    stats_spacer = Gtk.Box()
    stats_spacer.set_hexpand(True)
    stats_row.append(stats_spacer)
    projected_label = ui.label(
        f"Projected readiness {projected:.0f}%",
        halign=Gtk.Align.END,
        css_classes=["muted", "single-line-lock", "status-line"],
        ellipsize=Pango.EllipsizeMode.END,
        max_width_chars=40,
    )
    stats_row.append(projected_label)
    card.append(stats_row)

    card.append(bar)

    meta_grid = Gtk.Grid()
    meta_grid.set_column_spacing(12)
    meta_grid.set_row_spacing(4)

    trend_key = ui.muted_label("Trend (7d mastery):")
    trend_val = ui.label(f"{trend_7d:+.1f}%")
    if trend_7d > 0:
        trend_val.add_css_class("nudge-good")
    elif trend_7d < 0:
        trend_val.add_css_class("nudge-warn")
    else:
        trend_val.add_css_class("nudge-info")

    days_key = ui.muted_label("Days remaining:")
    days_text = str(days_remaining) if isinstance(days_remaining, int) else "Set exam date"
    days_val = ui.label(days_text)

    status_key = ui.muted_label("Status:")
    status_badge = ui.label(status)
    status_badge.add_css_class("badge")
    if status == "On course":
        status_badge.add_css_class("nudge-good")
    elif status == "Watchlist":
        status_badge.add_css_class("nudge-info")
    else:
        status_badge.add_css_class("nudge-warn")

    meta_grid.attach(trend_key, 0, 0, 1, 1)
    meta_grid.attach(trend_val, 1, 0, 1, 1)
    meta_grid.attach(days_key, 0, 1, 1, 1)
    meta_grid.attach(days_val, 1, 1, 1, 1)
    meta_grid.attach(status_key, 0, 2, 1, 1)
    meta_grid.attach(status_badge, 1, 2, 1, 1)
    card.append(meta_grid)

    return card


def build_outcome_mastery_card(ui: UIBuilder, engine: Any) -> Gtk.Widget:
    """Build the Outcome Mastery dashboard card (presentation only)."""
    card = ui.vbox(spacing=6, css_classes=["card"])
    title = ui.section_title("Outcome Mastery")
    card.append(title)

    try:
        mastery = engine.get_outcome_mastery_map()
    except Exception:
        mastery = {}
    if not isinstance(mastery, dict):
        mastery = {}

    total = int(mastery.get("total_outcomes", 0) or 0)
    covered = int(mastery.get("covered_outcomes", 0) or 0)
    uncovered = int(mastery.get("uncovered_outcomes", 0) or 0)
    coverage_pct = float(mastery.get("coverage_pct", 0.0) or 0.0)

    if total <= 0:
        empty = ui.label(
            "No syllabus outcomes loaded for this module yet.",
            css_classes=["muted", "allow-wrap"],
            wrap=True,
        )
        card.append(empty)
        return card

    bar = ui.progress_bar(show_text=True)
    bar.set_fraction(max(0.0, min(1.0, coverage_pct / 100.0)))
    bar.set_text(f"Coverage {coverage_pct:.0f}%")
    card.append(bar)

    summary_grid = Gtk.Grid()
    summary_grid.set_column_spacing(10)
    summary_grid.set_row_spacing(4)
    summary_grid.attach(ui.muted_label("Covered:"), 0, 0, 1, 1)
    summary_grid.attach(ui.label(f"{covered}/{total}"), 1, 0, 1, 1)
    summary_grid.attach(ui.muted_label("Uncovered:"), 0, 1, 1, 1)
    uncovered_label = ui.label(str(uncovered))
    if uncovered > 0:
        uncovered_label.add_css_class("nudge-info")
    summary_grid.attach(uncovered_label, 1, 1, 1, 1)
    card.append(summary_grid)

    capabilities = mastery.get("capabilities", {})
    if isinstance(capabilities, dict) and capabilities:
        rows: list[tuple[str, float, int, int]] = []
        for cap, info in capabilities.items():
            if not isinstance(info, dict):
                continue
            cap_total = int(info.get("total_outcomes", 0) or 0)
            if cap_total <= 0:
                continue
            cap_covered = int(info.get("covered_outcomes", 0) or 0)
            cap_pct = float(info.get("coverage_pct", 0.0) or 0.0)
            rows.append((str(cap), cap_pct, cap_covered, cap_total))
        if rows:
            rows.sort(key=lambda x: (x[1], x[0]))
            lines = [f"{cap}: {cov}/{tot} ({pct:.0f}%)" for cap, pct, cov, tot in rows[:6]]
            detail = ui.label(
                "\n".join(lines),
                css_classes=["muted", "allow-wrap"],
                wrap=True,
            )
            card.append(detail)

    return card


def build_next_action_card(
    ui: UIBuilder,
    *,
    recommended_topic: str,
    weak_chapter: str | None,
    must_review_due: int,
    has_questions: bool,
    pace_status: str,
    on_focus_now: Callable[..., Any],
    on_clear_must_review: Callable[..., Any],
    on_drill_weak: Callable[..., Any],
    on_quick_quiz: Callable[..., Any],
    format_ui_info_block_lines: Callable[..., str],
    mark_wrapping_label: Callable[..., Any],
    enforce_label_single_line: Callable[..., Any],
    sync_single_line_label_tooltip: Callable[..., Any],
) -> Gtk.Widget:
    """Build the Next Best Action dashboard card (presentation + action wiring)."""
    card = ui.vbox(spacing=6)
    card.add_css_class("card")
    title = ui.section_title("Next Best Action")
    card.append(title)

    action_text = f"Do: Focus 25m — {recommended_topic}"
    primary_label = "Start focus"
    primary_cb = on_focus_now
    reason_lines: list[str] = []

    if must_review_due > 0 and has_questions:
        action_text = f"Do: Clear {must_review_due} must-review cards"
        primary_label = "Clear reviews"
        primary_cb = on_clear_must_review
        reason_lines.append("Reason: reviews are due today")
    elif weak_chapter and has_questions:
        action_text = f"Do: Weak drill — {weak_chapter}"
        primary_label = "Weak drill"
        primary_cb = on_drill_weak
        reason_lines.append("Reason: weakest chapter needs lift")
    else:
        reason_lines.append("Reason: best momentum topic")

    if pace_status == "behind":
        reason_lines.append("Pace: behind — small push today")

    pace_line = ""
    why_lines: list[str] = []
    for raw_line in reason_lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        if line.lower().startswith("pace:"):
            pace_line = line
        else:
            why_lines.append(line)

    def _build_value_label(
        raw_text: str,
        *,
        split_threshold: int,
        max_chars: int,
        muted: bool = False,
    ) -> Gtk.Label:
        line = str(raw_text or "").strip()
        display_line = line
        if len(line) > split_threshold:
            display_line = format_ui_info_block_lines([line], split_threshold=split_threshold)
        label = ui.label(display_line)
        label.set_xalign(0.0)
        if muted:
            label.add_css_class("muted")
        if "\n" in display_line:
            mark_wrapping_label(label, max_width_chars=max_chars)
        else:
            if not muted:
                label.add_css_class("status-line")
            enforce_label_single_line(label, max_chars=max_chars)
            sync_single_line_label_tooltip(label, line)
        if display_line != line:
            try:
                label.set_tooltip_text(line)
            except Exception:
                pass
        return label

    action_grid = Gtk.Grid()
    action_grid.set_column_spacing(10)
    action_grid.set_row_spacing(4)
    do_key = ui.muted_label("Do:")
    do_val = _build_value_label(action_text, split_threshold=54, max_chars=96, muted=False)
    action_grid.attach(do_key, 0, 0, 1, 1)
    action_grid.attach(do_val, 1, 0, 1, 1)

    row_index = 1
    if why_lines:
        reason_key = ui.muted_label("Reason:")
        reason_val = _build_value_label(
            "\n".join(why_lines),
            split_threshold=58,
            max_chars=92,
            muted=True,
        )
        action_grid.attach(reason_key, 0, row_index, 1, 1)
        action_grid.attach(reason_val, 1, row_index, 1, 1)
        row_index += 1
    if pace_line:
        pace_key = ui.muted_label("Pace:")
        pace_val = _build_value_label(
            pace_line.removeprefix("Pace:").strip(),
            split_threshold=54,
            max_chars=90,
            muted=True,
        )
        if pace_status == "behind":
            pace_val.add_css_class("nudge-warn")
        elif pace_status == "ahead":
            pace_val.add_css_class("nudge-good")
        else:
            pace_val.add_css_class("nudge-info")
        action_grid.attach(pace_key, 0, row_index, 1, 1)
        action_grid.attach(pace_val, 1, row_index, 1, 1)
    card.append(action_grid)

    actions = ui.hbox(spacing=6)
    actions.add_css_class("inline-toolbar")
    primary_btn = ui.button(primary_label, on_click=primary_cb)
    actions.append(primary_btn)
    if has_questions:
        secondary_label = "Quick quiz" if primary_cb != on_quick_quiz else "Focus now"
        secondary_cb = on_quick_quiz if secondary_label == "Quick quiz" else on_focus_now
        secondary_btn = ui.button(secondary_label, on_click=secondary_cb)
        actions.append(secondary_btn)
    card.append(actions)
    return card


def build_study_snapshot_card(
    ui: UIBuilder,
    *,
    stats_lines: list[str],
    format_ui_info_block_lines: Callable[..., str],
) -> Gtk.Widget:
    """Build the Study Snapshot dashboard card from precomputed lines."""
    stats_card = ui.card(spacing=4)
    stats_title = ui.section_title("Study Snapshot")
    stats_card.append(stats_title)
    stats_label = ui.label(
        format_ui_info_block_lines(stats_lines, split_threshold=72),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    stats_card.append(stats_label)
    return stats_card


def build_mastery_snapshot_card(
    ui: UIBuilder,
    *,
    mastery_lines: list[str],
    format_ui_info_block_lines: Callable[..., str],
) -> Gtk.Widget:
    """Build the Mastery Snapshot dashboard card from precomputed lines."""
    mastery_card = ui.card(spacing=4)
    mastery_title = ui.section_title("Mastery Snapshot")
    mastery_card.append(mastery_title)
    mastery_label = ui.label(
        format_ui_info_block_lines(mastery_lines, split_threshold=72),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    mastery_card.append(mastery_label)
    return mastery_card


def build_weak_vs_strong_card(
    ui: UIBuilder,
    *,
    weak_lines: list[str],
    strong_lines: list[str],
    sync_single_line_label_tooltip: Callable[..., Any],
) -> Gtk.Widget:
    """Build the Weak vs Strong dashboard card from precomputed line lists."""
    ws_card = ui.card(spacing=4)
    ws_title = ui.section_title("Weak vs Strong")
    ws_card.append(ws_title)

    weak_box = ui.vbox(spacing=2)
    weak_title = ui.muted_label("Weakest")
    weak_title.add_css_class("nudge-warn")
    weak_box.append(weak_title)
    for line in weak_lines:
        lbl = ui.label(
            line,
            css_classes=["muted"],
            wrap=False,
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=64,
        )
        sync_single_line_label_tooltip(lbl, line)
        weak_box.append(lbl)
    ws_card.append(weak_box)

    if strong_lines:
        strong_box = ui.vbox(spacing=2)
        strong_title = ui.muted_label("Strongest")
        strong_title.add_css_class("nudge-good")
        strong_box.append(strong_title)
        for line in strong_lines:
            lbl = ui.label(
                line,
                css_classes=["muted"],
                wrap=False,
                ellipsize=Pango.EllipsizeMode.END,
                max_width_chars=64,
            )
            sync_single_line_label_tooltip(lbl, line)
            strong_box.append(lbl)
        ws_card.append(strong_box)

    return ws_card


def build_reviews_pace_card(
    ui: UIBuilder,
    *,
    review_lines: list[str],
    format_ui_info_block_lines: Callable[..., str],
) -> Gtk.Widget:
    """Build the Reviews & Pace dashboard card from precomputed lines."""
    reviews_card = ui.card(spacing=4)
    reviews_title = ui.section_title("Reviews & Pace")
    reviews_card.append(reviews_title)
    review_label = ui.label(
        format_ui_info_block_lines(review_lines, split_threshold=72),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    reviews_card.append(review_label)
    return reviews_card


def build_reviews_due_today_card(
    ui: UIBuilder,
    *,
    lines: list[str],
    format_ui_info_block_lines: Callable[..., str],
) -> Gtk.Widget:
    """Build the Reviews Due Today dashboard card from precomputed lines."""
    due_card = ui.card(spacing=4)
    due_title = ui.section_title("Reviews Due Today")
    due_card.append(due_title)
    due_label = ui.label(
        format_ui_info_block_lines(lines, split_threshold=72),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    due_card.append(due_label)
    return due_card


def build_leech_alerts_card(
    ui: UIBuilder,
    *,
    lines: list[str],
    format_ui_info_block_lines: Callable[..., str],
) -> Gtk.Widget:
    """Build the Leech Alerts dashboard card from precomputed lines."""
    leech_card = ui.card(spacing=4)
    leech_title = ui.section_title("Leech Alerts")
    leech_card.append(leech_title)
    leech_label = ui.label(
        format_ui_info_block_lines(lines, split_threshold=72),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    leech_card.append(leech_label)
    return leech_card


def build_study_hub_content(
    ui: UIBuilder,
    *,
    summary_lines: list[str],
    age_line: str | None,
    category_lines_text: str | None,
    chapter_lines_text: str | None,
    format_ui_info_block_lines: Callable[..., str],
) -> Gtk.Widget:
    """Build Study Hub expander content (not the expander shell)."""
    hub_box = ui.vbox(spacing=6)
    hub_label = ui.label(
        format_ui_info_block_lines(summary_lines, split_threshold=72),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    hub_box.append(hub_label)

    if isinstance(age_line, str) and age_line.strip():
        age_label = ui.muted_label(age_line.strip())
        hub_box.append(age_label)

    if isinstance(category_lines_text, str) and category_lines_text.strip():
        cat_label = ui.label(
            f"Categories (weakest):\n{category_lines_text}",
            css_classes=["muted", "allow-wrap"],
            wrap=True,
        )
        hub_box.append(cat_label)

    if isinstance(chapter_lines_text, str) and chapter_lines_text.strip():
        ch_label = ui.label(
            f"By Chapter (weakest):\n{chapter_lines_text}",
            css_classes=["muted", "allow-wrap"],
            wrap=True,
        )
        hub_box.append(ch_label)

    return hub_box


def build_data_health_content(
    ui: UIBuilder,
    *,
    health_lines: list[str],
    format_ui_info_block_lines: Callable[..., str],
) -> Gtk.Widget:
    """Build Data Health Checks expander content (not the expander shell)."""
    health_box = ui.vbox(spacing=6)
    health_label = ui.label(
        format_ui_info_block_lines(health_lines, split_threshold=72),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    health_box.append(health_label)
    return health_box


def build_insight_lines_card(
    ui: UIBuilder,
    *,
    title_text: str,
    lines: list[str],
) -> Gtk.Widget:
    """Build a simple dashboard insight card with a title and multiline body."""
    card = ui.vbox(spacing=4)
    card.add_css_class("card")
    card.add_css_class("insight-card")
    title = ui.label(title_text)
    title.set_halign(Gtk.Align.START)
    title.add_css_class("section-title")
    card.append(title)
    body = ui.label("\n".join(lines))
    body.set_halign(Gtk.Align.START)
    body.set_wrap(True)
    body.add_css_class("muted")
    body.add_css_class("dashboard-block-body")
    card.append(body)
    return card


def build_daily_summary_card(
    ui: UIBuilder,
    *,
    summary_lines: list[str],
    sync_single_line_label_tooltip: Callable[..., Any],
) -> Gtk.Widget:
    """Build the Daily Summary dashboard card with single-line entries."""
    card = ui.vbox(spacing=4)
    card.add_css_class("card")
    card.add_css_class("insight-card")
    title = ui.label("Daily Summary")
    title.set_halign(Gtk.Align.START)
    title.add_css_class("section-title")
    card.append(title)
    for line in summary_lines[:3]:
        lbl = ui.label(
            line,
            css_classes=["muted", "dashboard-block-body"],
            wrap=False,
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=96,
        )
        lbl.set_halign(Gtk.Align.START)
        sync_single_line_label_tooltip(lbl, line)
        card.append(lbl)
    return card


def build_multiline_text_card(
    ui: UIBuilder,
    *,
    title_text: str,
    lines: list[str],
    insight_card: bool = False,
    add_dashboard_body_class: bool = True,
) -> Gtk.Widget:
    """Build a simple title + multiline body dashboard card."""
    card = ui.vbox(spacing=4)
    card.add_css_class("card")
    if insight_card:
        card.add_css_class("insight-card")
    title = ui.section_title(title_text)
    card.append(title)
    body = ui.label(
        "\n".join(str(line) for line in lines),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    if add_dashboard_body_class:
        body.add_css_class("dashboard-block-body")
    card.append(body)
    return card


def build_quiz_insights_card(
    ui: UIBuilder,
    *,
    risk_lines: list[str],
    detail_rows: list[dict[str, Any]] | None = None,
) -> Gtk.Widget:
    """Build the Quiz Insights dashboard card from precomputed text rows."""
    card = ui.vbox(spacing=4)
    card.add_css_class("card")
    title = ui.section_title("Quiz Insights")
    card.append(title)

    risk_label = ui.label(
        "\n".join(str(line) for line in risk_lines),
        css_classes=["muted", "allow-wrap"],
        wrap=True,
    )
    card.append(risk_label)

    for row in list(detail_rows or []):
        text = str(row.get("text", "") or "").strip()
        if not text:
            continue
        single_line = bool(row.get("single_line", False))
        label = ui.label(
            text,
            css_classes=["muted"],
            wrap=not single_line,
            ellipsize=Pango.EllipsizeMode.END if single_line else None,
            max_width_chars=int(row.get("max_width_chars", 120) or 120),
        )
        if single_line:
            label.add_css_class("single-line-lock")
        if bool(row.get("warn", False)):
            label.add_css_class("status-warn")
            label.add_css_class("nudge-warn")
        card.append(label)

    return card
