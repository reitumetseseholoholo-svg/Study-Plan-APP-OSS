#!/usr/bin/env python3
import gi  # type: ignore[import-untyped]
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk  # type: ignore[reportAttributeAccessIssue,import-untyped]

SYSTEM_THEME_CSS = b"""
@define-color app_accent alpha(@theme_selected_bg_color, 0.98);
@define-color app_border alpha(@theme_fg_color, 0.30);
@define-color app_border_strong alpha(@theme_fg_color, 0.48);
@define-color app_surface alpha(@theme_bg_color, 0.93);
@define-color app_surface_alt alpha(@theme_bg_color, 0.90);
@define-color app_muted alpha(@theme_fg_color, 0.99);
window {
    background-color: @theme_bg_color;
    background-image: linear-gradient(
        to bottom,
        alpha(@theme_bg_color, 1.0),
        alpha(@theme_bg_color, 0.96)
    );
    color: @theme_fg_color;
}
.panel {
    background-color: app_surface;
    border: 1px solid app_border;
    border-radius: 14px;
    padding: 12px;
    box-shadow: 0 3px 10px alpha(@theme_fg_color, 0.12);
}
.panel-left {
    background-color: alpha(@theme_bg_color, 0.965);
    border-right: 2px solid app_border_strong;
    border-top-right-radius: 14px;
    border-bottom-right-radius: 14px;
    margin-right: 8px;
    box-shadow: 2px 0 0 alpha(@theme_fg_color, 0.16);
}
.panel-right {
    background-color: alpha(@theme_bg_color, 0.935);
    border-left: 2px solid app_border_strong;
    border-top-left-radius: 14px;
    border-bottom-left-radius: 14px;
    margin-left: 8px;
    box-shadow: -2px 0 0 alpha(@theme_fg_color, 0.16);
}
.card {
    background-color: alpha(@theme_bg_color, 0.88);
    background-image: linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.04),
        alpha(@theme_bg_color, 0.0)
    );
    border: 2px solid alpha(@theme_fg_color, 0.46);
    border-radius: 13px;
    padding: 11px;
    box-shadow: 0 1px 0 alpha(@theme_fg_color, 0.10), 0 5px 16px alpha(@theme_fg_color, 0.16);
    margin-top: 6px;
    margin-bottom: 6px;
}
.card-tight {
    padding: 7px;
}
.chart-card {
    padding-top: 8px;
    padding-bottom: 6px;
}
.hero-card {
    border-color: alpha(@theme_selected_bg_color, 0.62);
    box-shadow: 0 1px 0 alpha(@theme_selected_bg_color, 0.28), 0 4px 14px alpha(@theme_selected_bg_color, 0.24);
}
.hero-card .coach-title,
.hero-card .section-title {
    color: app_accent;
}
.card:hover {
    border-color: alpha(@theme_selected_bg_color, 0.96);
    box-shadow: 0 0 0 1px alpha(@theme_selected_bg_color, 0.48), 0 7px 20px alpha(@theme_selected_bg_color, 0.28);
}
.title {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-weight: 760;
    font-size: 22px;
    letter-spacing: 0.2px;
}
.action-timer {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-weight: 780;
    font-size: 19px;
    letter-spacing: 0.35px;
}
.section-title {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-weight: 820;
    font-size: 12px;
    letter-spacing: 0.55px;
    text-transform: uppercase;
    color: alpha(@theme_fg_color, 1.0);
    background-image: linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.38),
        alpha(@theme_selected_bg_color, 0.24)
    );
    border: 1px solid alpha(@theme_selected_bg_color, 0.78);
    border-radius: 8px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
}
label.section-title {
    color: alpha(@theme_fg_color, 1.0);
    font-weight: 820;
}
.section-title + .muted {
    margin-top: 1px;
}
label.coach-title {
    color: alpha(@theme_fg_color, 1.0);
    font-weight: 820;
}
.muted {
    color: app_muted;
    line-height: 1.5;
}
.insight-card {
    border-left: 4px solid alpha(@theme_selected_bg_color, 0.42);
    background-image: linear-gradient(
        to right,
        alpha(@theme_selected_bg_color, 0.07),
        alpha(@theme_bg_color, 0.0)
    );
}
.insight-card .section-title {
    margin-bottom: 8px;
}
.dashboard-block-body {
    color: alpha(@theme_fg_color, 1.0);
    font-size: 13px;
    line-height: 1.58;
}
.quiz-dialog {
    min-width: 640px;
}
.quiz-header {
    margin-bottom: 4px;
}
.quiz-content {
    margin-top: 4px;
    margin-bottom: 4px;
}
.quiz-mix-row {
    margin-top: 2px;
    margin-bottom: 2px;
}
.quiz-meta {
    font-size: 12px;
}
.quiz-question {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-weight: 700;
    font-size: 15px;
    line-height: 1.35;
}
.quiz-option {
    border-radius: 10px;
    border: 1px solid app_border;
    padding: 7px 9px;
    margin-top: 3px;
    margin-bottom: 3px;
}
.quiz-option:hover {
    border-color: app_border_strong;
    background: alpha(@theme_fg_color, 0.06);
}
.quiz-feedback {
    margin-top: 6px;
    border-radius: 8px;
    padding: 6px 8px;
    background: alpha(@theme_fg_color, 0.045);
}
.quiz-hint {
    margin-top: 3px;
}
.quiz-reason {
    margin-top: 3px;
}
.hint {
    color: alpha(@theme_fg_color, 0.72);
    font-size: 11px;
    font-style: normal;
}
.plan-title {
    font-weight: 760;
    color: alpha(@theme_fg_color, 1.0);
    letter-spacing: 0.15px;
}
label.plan-title {
    color: alpha(@theme_fg_color, 1.0);
    font-weight: 760;
}
.plan-meta {
    font-size: 11px;
}
.study-summary {
    font-size: 12px;
    line-height: 1.4;
}
.rule {
    color: alpha(@theme_fg_color, 0.24);
}
.error { background-color: @error_color; }
.warning { background-color: @warning_color; }
.success { background-color: @success_color; }
window.compact {
    font-size: 12px;
}
window.compact .panel {
    padding: 8px;
}
window.compact .card {
    padding: 6px;
}
window.compact .title {
    font-size: 17px;
}
window.compact .section-title {
    font-size: 11px;
    letter-spacing: 0.5px;
}
window.compact .plan-meta {
    font-size: 10px;
}
window.compact .study-summary {
    font-size: 11px;
}
window.compact button {
    padding: 4px 6px;
}
window.tile .panel-left {
    margin-right: 10px;
    border-right: 2px solid app_border_strong;
}
window.tile .panel-right {
    margin-left: 10px;
    border-left: 2px solid app_border_strong;
}
window.tile .card {
    padding: 8px;
}
window.tile .section-title,
window.tile .coach-title {
    font-size: 11px;
}
.badge {
    background: alpha(@theme_fg_color, 0.1);
    border: 1px solid alpha(@theme_fg_color, 0.24);
    border-radius: 999px;
    padding: 2px 8px;
}
.badge-locked {
    background: alpha(@theme_fg_color, 0.05);
    border: 1px dashed alpha(@theme_fg_color, 0.22);
    border-radius: 999px;
    padding: 2px 8px;
    color: alpha(@theme_fg_color, 0.6);
}
.status-ok {
    color: @success_color;
    font-weight: 600;
}
.status-warn {
    color: @warning_color;
    font-weight: 600;
}
.status-bad {
    color: @error_color;
    font-weight: 600;
}
.nudge-warn {
    color: @warning_color;
    font-weight: 760;
    font-style: italic;
    line-height: 1.18;
    background-color: alpha(@warning_color, 0.12);
    border: 1px solid alpha(@warning_color, 0.30);
    border-radius: 9px;
    padding: 4px 10px;
}
.nudge-info {
    color: app_accent;
    font-weight: 700;
    font-style: italic;
    background-color: alpha(@theme_selected_bg_color, 0.16);
    border: 1px solid alpha(@theme_selected_bg_color, 0.36);
    border-radius: 8px;
    padding: 2px 8px;
}
.nudge-good {
    color: @success_color;
    font-weight: 760;
    font-style: italic;
    background-color: alpha(@success_color, 0.16);
    border: 1px solid alpha(@success_color, 0.36);
    border-radius: 8px;
    padding: 2px 8px;
}
.coach-title {
    font-weight: 820;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.62px;
    color: alpha(@theme_fg_color, 1.0);
    background-image: linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.40),
        alpha(@theme_selected_bg_color, 0.26)
    );
    border: 1px solid alpha(@theme_selected_bg_color, 0.82);
    border-radius: 8px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
}
label.today-focus-chip {
    font-size: 11px;
    letter-spacing: 0.48px;
    padding: 4px 12px;
    border-radius: 10px;
    line-height: 1.12;
    margin-top: 2px;
    margin-bottom: 4px;
}
.focus-list row {
    border: none;
    padding: 4px 2px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
}
.focus-list row:selected {
    background: alpha(@theme_selected_bg_color, 0.12);
}
.quest-card {
    border: 1px solid app_border;
    border-radius: 12px;
    padding: 10px;
}
.xp-progress {
    min-height: 12px;
}
progressbar {
    min-height: 11px;
}
button {
    border-radius: 10px;
    padding: 6px 10px;
    min-height: 32px;
    background: alpha(@theme_fg_color, 0.07);
    border: 1px solid alpha(@theme_fg_color, 0.26);
    color: @theme_fg_color;
    box-shadow: 0 1px 0 alpha(@theme_bg_color, 0.22);
}
window.app-dialog-window button,
window.app-dialog-window button.dialog-action {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 9px;
}
window.app-dialog-window spinbutton button {
    min-height: 22px;
    min-width: 22px;
    padding: 1px 4px;
}
window.app-dialog-window spinbutton entry {
    min-height: 26px;
}
window.app-dialog-window button.suggested-action {
    min-height: 30px;
}
button:hover {
    background: alpha(@theme_fg_color, 0.12);
    border-color: alpha(@theme_fg_color, 0.36);
}
button:active {
    background: alpha(@theme_fg_color, 0.16);
    border-color: alpha(@theme_fg_color, 0.42);
}
button:disabled {
    background: alpha(@theme_fg_color, 0.04);
    border-color: alpha(@theme_fg_color, 0.12);
    color: alpha(@theme_fg_color, 0.5);
    box-shadow: none;
}
button.suggested-action {
    background: @theme_selected_bg_color;
    color: @theme_selected_fg_color;
    border-color: alpha(@theme_selected_fg_color, 0.4);
    box-shadow: 0 1px 0 alpha(@theme_selected_fg_color, 0.2), 0 2px 6px alpha(@theme_selected_bg_color, 0.35);
}
button.suggested-action:hover {
    background: mix(@theme_selected_bg_color, @theme_fg_color, 0.16);
}
button.suggested-action:active {
    background: mix(@theme_selected_bg_color, @theme_fg_color, 0.24);
}
button.flat {
    background: transparent;
    border-color: transparent;
    box-shadow: none;
}
button.flat:hover {
    background: alpha(@theme_fg_color, 0.08);
    border-color: alpha(@theme_fg_color, 0.2);
}
button.flat:active {
    background: alpha(@theme_fg_color, 0.12);
    border-color: alpha(@theme_fg_color, 0.24);
}
button:focus-visible {
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.35);
}
spinbutton button {
    min-height: 24px;
    min-width: 24px;
    padding: 1px 5px;
    border-radius: 8px;
}
spinbutton entry {
    min-height: 28px;
}
progressbar trough {
    border-radius: 999px;
    background-color: alpha(@theme_fg_color, 0.2);
}
progressbar progress {
    border-radius: 999px;
    background-color: app_accent;
}
tooltip {
    padding: 6px 8px;
    border-radius: 8px;
    border: 1px solid app_border;
}
scrollbar {
    min-width: 8px;
    min-height: 8px;
}
scrollbar slider {
    background-color: alpha(@theme_fg_color, 0.25);
    border-radius: 999px;
}
scrollbar slider:hover {
    background-color: alpha(@theme_fg_color, 0.38);
}
scrollbar slider:active {
    background-color: alpha(@theme_fg_color, 0.5);
}
/* polish pass */
.card {
    border-color: alpha(@theme_fg_color, 0.30);
    padding: 14px;
    border-radius: 12px;
    box-shadow: 0 1px 0 alpha(@theme_fg_color, 0.10), 0 8px 22px alpha(@theme_fg_color, 0.14);
}
.hero-card {
    border-color: alpha(@theme_selected_bg_color, 0.72);
}
.muted {
    color: alpha(@theme_fg_color, 0.92);
    line-height: 1.56;
}
entry,
spinbutton entry,
textview {
    background: alpha(@theme_bg_color, 0.82);
    border: 1px solid alpha(@theme_fg_color, 0.22);
    border-radius: 10px;
}
entry:focus,
spinbutton entry:focus,
textview:focus {
    border-color: alpha(@theme_selected_bg_color, 0.72);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.22);
}
dropdown > button {
    border-radius: 10px;
    min-height: 34px;
}
.study-room-actions button {
    min-height: 36px;
    font-weight: 650;
    padding: 6px 10px;
}
button.coach-action {
    background: alpha(@theme_selected_bg_color, 0.15);
    border-color: alpha(@theme_selected_bg_color, 0.48);
}
button.coach-action:hover {
    background: alpha(@theme_selected_bg_color, 0.24);
}
scrolledwindow {
    border-radius: 10px;
}
/* deep gtk4 polish pass */
.study-window {
    letter-spacing: 0.1px;
}
.workspace-root {
    background-image: linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.04),
        alpha(@theme_bg_color, 0.0)
    );
}
.workspace-split {
    margin-top: 2px;
}
.top-menu {
    background: alpha(@theme_bg_color, 0.84);
    border-bottom: 1px solid alpha(@theme_fg_color, 0.16);
    padding-top: 3px;
    padding-bottom: 3px;
    padding-left: 6px;
    padding-right: 6px;
}
.banner-shell {
    border-color: alpha(@theme_selected_bg_color, 0.72);
    background-image: linear-gradient(
        to right,
        alpha(@theme_selected_bg_color, 0.16),
        alpha(@theme_selected_bg_color, 0.06)
    );
}
.banner-shell .banner-text {
    font-weight: 690;
    letter-spacing: 0.16px;
}
.panel-scroll {
    background: transparent;
}
.panel-stack {
    padding-top: 2px;
}
.section-expander > title {
    background: alpha(@theme_fg_color, 0.05);
    border-radius: 9px;
    padding: 4px 6px;
}
.section-expander > title:hover {
    background: alpha(@theme_selected_bg_color, 0.10);
}
.topic-selector > button {
    font-weight: 650;
}
.topic-selector > button > box > label {
    letter-spacing: 0.15px;
}
.inline-toolbar {
    border-bottom: 1px solid alpha(@theme_fg_color, 0.11);
    padding-bottom: 4px;
    margin-bottom: 2px;
}
.list-card {
    background-image: linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.08),
        alpha(@theme_bg_color, 0.0)
    );
}
.feature-card {
    border-width: 2px;
}
.tools-card button {
    min-height: 34px;
    font-weight: 640;
}
.metric-card {
    border-color: alpha(@theme_selected_bg_color, 0.46);
}
.metric-card progressbar {
    min-height: 12px;
}
.badges-card {
    border-color: alpha(@theme_selected_bg_color, 0.38);
}
.kpi-line {
    font-weight: 660;
    letter-spacing: 0.12px;
}
.dashboard-stack > .card {
    margin-top: 4px;
    margin-bottom: 8px;
}
"""

COACH_THEME_CSS = b"""
@define-color coach_bg #121724;
@define-color coach_panel #1a2233;
@define-color coach_card #212d43;
@define-color coach_border #647fb3;
@define-color coach_border_strong #9bb8ef;
@define-color coach_text #e8edf7;
@define-color coach_muted #e4edff;
@define-color coach_accent #4fd1c5;
@define-color coach_accent_alt #8bafff;
window {
    background: coach_bg;
    color: coach_text;
    font-family: "IBM Plex Sans", "JetBrains Mono NL", "Noto Sans", sans-serif;
}
.panel {
    background: coach_panel;
    border: 1px solid coach_border;
    border-radius: 14px;
    padding: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.32);
}
.panel-left {
    background: #1a2233;
    border-right: 2px solid coach_border_strong;
    border-top-right-radius: 14px;
    border-bottom-right-radius: 14px;
    margin-right: 8px;
    box-shadow: 2px 0 0 rgba(155, 184, 239, 0.24);
}
.panel-right {
    background: #182135;
    border-left: 2px solid coach_border_strong;
    border-top-left-radius: 14px;
    border-bottom-left-radius: 14px;
    margin-left: 8px;
    box-shadow: -2px 0 0 rgba(155, 184, 239, 0.24);
}
.card {
    background: #23314a;
    border: 2px solid #7590c5;
    border-radius: 13px;
    padding: 11px;
    box-shadow: 0 1px 0 rgba(179, 198, 232, 0.08), 0 5px 16px rgba(0,0,0,0.36);
    margin-top: 6px;
    margin-bottom: 6px;
}
.card-tight {
    padding: 7px;
}
.chart-card {
    padding-top: 8px;
    padding-bottom: 6px;
}
.hero-card {
    border-color: #7b95c8;
    box-shadow: 0 1px 0 rgba(123, 149, 200, 0.28), 0 4px 14px rgba(79, 209, 197, 0.24);
}
.hero-card .coach-title,
.hero-card .section-title {
    color: coach_accent;
}
.card:hover {
    border-color: #b2caff;
    background: #263653;
    box-shadow: 0 0 0 1px rgba(139, 175, 255, 0.50), 0 7px 22px rgba(139, 175, 255, 0.28);
}
.title {
    font-weight: 760;
    font-size: 22px;
    letter-spacing: 0.2px;
    color: coach_text;
}
.action-timer {
    font-weight: 780;
    font-size: 19px;
    letter-spacing: 0.35px;
    color: coach_text;
}
.section-title {
    font-weight: 820;
    font-size: 12px;
    letter-spacing: 0.58px;
    text-transform: uppercase;
    color: #f5f8ff;
    background: linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.40),
        rgba(139, 175, 255, 0.24)
    );
    border: 1px solid rgba(139, 175, 255, 0.84);
    border-radius: 8px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
}
label.section-title {
    color: #f5f8ff;
    font-weight: 820;
}
.section-title + .muted {
    margin-top: 1px;
}
.coach-title {
    font-weight: 820;
    letter-spacing: 0.62px;
    color: #f5f8ff;
    text-transform: uppercase;
    font-size: 12px;
    background: linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.42),
        rgba(139, 175, 255, 0.26)
    );
    border: 1px solid rgba(139, 175, 255, 0.84);
    border-radius: 8px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
}
label.today-focus-chip {
    font-size: 11px;
    letter-spacing: 0.48px;
    padding: 4px 12px;
    border-radius: 10px;
    line-height: 1.12;
    margin-top: 2px;
    margin-bottom: 4px;
}
label.coach-title {
    color: #f5f8ff;
    font-weight: 820;
}
.muted {
    color: coach_muted;
    line-height: 1.5;
}
.insight-card {
    border-left: 4px solid rgba(139, 175, 255, 0.62);
    background: linear-gradient(
        to right,
        rgba(139, 175, 255, 0.11),
        rgba(33, 45, 67, 0.0)
    );
}
.insight-card .section-title {
    margin-bottom: 8px;
}
.dashboard-block-body {
    color: #f2f7ff;
    font-size: 13px;
    line-height: 1.58;
}
.quiz-dialog {
    min-width: 640px;
}
.quiz-header {
    margin-bottom: 4px;
}
.quiz-content {
    margin-top: 4px;
    margin-bottom: 4px;
}
.quiz-mix-row {
    margin-top: 2px;
    margin-bottom: 2px;
}
.quiz-meta {
    font-size: 12px;
}
.quiz-question {
    font-weight: 700;
    font-size: 15px;
    line-height: 1.35;
}
.quiz-option {
    border-radius: 10px;
    border: 1px solid coach_border;
    padding: 7px 9px;
    margin-top: 3px;
    margin-bottom: 3px;
}
.quiz-option:hover {
    border-color: coach_border_strong;
    background: #263043;
}
.quiz-feedback {
    margin-top: 6px;
    border-radius: 8px;
    padding: 6px 8px;
    background: #243047;
}
.quiz-hint {
    margin-top: 3px;
}
.quiz-reason {
    margin-top: 3px;
}
.hint {
    color: #a8b3ca;
    font-size: 11px;
    font-style: normal;
}
.plan-title {
    font-weight: 760;
    color: #f5f8ff;
    letter-spacing: 0.15px;
}
label.plan-title {
    color: #f5f8ff;
    font-weight: 760;
}
.plan-meta {
    font-size: 11px;
}
.study-summary {
    font-size: 12px;
    line-height: 1.4;
}
.rule {
    color: #4d5d79;
}
button {
    background: #2d3b56;
    border: 1px solid #5b6f95;
    border-radius: 10px;
    color: coach_text;
    padding: 6px 10px;
    min-height: 32px;
    box-shadow: 0 1px 0 rgba(169, 190, 227, 0.12);
}
window.app-dialog-window button,
window.app-dialog-window button.dialog-action {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 9px;
}
window.app-dialog-window spinbutton button {
    min-height: 22px;
    min-width: 22px;
    padding: 1px 4px;
}
window.app-dialog-window spinbutton entry {
    min-height: 26px;
}
window.app-dialog-window button.suggested-action {
    min-height: 30px;
}
button:hover {
    background: #354766;
    border-color: #7d98c8;
}
button:active {
    background: #3f5376;
    border-color: #8da9da;
}
button:disabled {
    background: #26334d;
    border-color: #425579;
    color: #95a2bc;
    box-shadow: none;
}
button.suggested-action {
    background: coach_accent;
    border-color: #7fe0d8;
    color: #072326;
    box-shadow: 0 1px 0 rgba(188, 246, 240, 0.42), 0 2px 7px rgba(79, 209, 197, 0.36);
}
button.suggested-action:hover {
    background: #66ddd2;
}
button.suggested-action:active {
    background: #54cfc3;
}
.error { background-color: #6d2a2a; }
.warning { background-color: #6a4b1f; }
.success { background-color: #1f5c3a; }
window.compact {
    font-size: 12px;
}
window.compact .panel {
    padding: 8px;
}
window.compact .card {
    padding: 8px;
    border-radius: 10px;
}
window.compact .title {
    font-size: 17px;
}
window.compact .section-title {
    font-size: 11px;
    letter-spacing: 0.5px;
}
window.compact .plan-meta {
    font-size: 10px;
}
window.compact .study-summary {
    font-size: 11px;
}
window.compact button {
    padding: 4px 6px;
}
window.tile .panel-left {
    margin-right: 10px;
    border-right: 2px solid coach_border_strong;
}
window.tile .panel-right {
    margin-left: 10px;
    border-left: 2px solid coach_border_strong;
}
window.tile .card {
    padding: 10px;
    border-radius: 11px;
}
window.tile .section-title,
window.tile .coach-title {
    font-size: 11px;
}
.badge {
    background: #252f44;
    border: 1px solid #44536e;
    border-radius: 999px;
    padding: 2px 8px;
    color: coach_text;
}
.badge-locked {
    background: #1d2534;
    border: 1px dashed #44536e;
    border-radius: 999px;
    padding: 2px 8px;
    color: #7f8792;
}
.badge-highlight {
    box-shadow: 0 0 0 5px rgba(79, 209, 197, 0.65);
    transition: box-shadow 0.5s ease-out;
}
.status-ok {
    color: coach_accent;
    font-weight: 600;
}
.status-warn {
    color: #f6c453;
    font-weight: 600;
}
.status-bad {
    color: #f28b82;
    font-weight: 600;
}
.nudge-warn {
    color: #f6c453;
    font-weight: 760;
    font-style: italic;
    line-height: 1.18;
    background: rgba(246, 196, 83, 0.12);
    border: 1px solid rgba(246, 196, 83, 0.30);
    border-radius: 9px;
    padding: 4px 10px;
}
.nudge-info {
    color: #8bafff;
    font-weight: 700;
    font-style: italic;
    background: rgba(139, 175, 255, 0.16);
    border: 1px solid rgba(139, 175, 255, 0.42);
    border-radius: 8px;
    padding: 2px 8px;
}
.nudge-good {
    color: #4fd1c5;
    font-weight: 760;
    font-style: italic;
    background: rgba(79, 209, 197, 0.16);
    border: 1px solid rgba(79, 209, 197, 0.42);
    border-radius: 8px;
    padding: 2px 8px;
}
.focus-list row {
    border: none;
    padding: 4px 2px;
    border-bottom: 1px solid rgba(101, 122, 158, 0.22);
}
.focus-list row:selected {
    background: rgba(79, 209, 197, 0.12);
}
.quest-card {
    background: #212d43;
    border: 1px solid #526487;
    border-radius: 13px;
    padding: 11px;
}
.xp-progress {
    min-height: 12px;
}
progressbar {
    min-height: 11px;
    padding: 2px 0;
}
button.flat {
    background: transparent;
    border-color: transparent;
    box-shadow: none;
}
button.flat:hover {
    background: #324160;
    border-color: #6881ad;
}
button.flat:active {
    background: #3b4b6b;
    border-color: #7a95c3;
}
button:focus-visible {
    box-shadow: 0 0 0 2px rgba(79, 209, 197, 0.42);
}
spinbutton button {
    min-height: 24px;
    min-width: 24px;
    padding: 1px 5px;
    border-radius: 8px;
}
spinbutton entry {
    min-height: 28px;
}
progressbar trough {
    border-radius: 999px;
    background-color: #2d3b56;
}
progressbar progress {
    border-radius: 999px;
    background-color: coach_accent_alt;
}
tooltip {
    padding: 6px 8px;
    border-radius: 8px;
    border: 1px solid #3f5270;
}
scrollbar {
    min-width: 8px;
    min-height: 8px;
}
scrollbar slider {
    background-color: #4b5b79;
    border-radius: 999px;
}
scrollbar slider:hover {
    background-color: #5e7195;
}
scrollbar slider:active {
    background-color: #7189b5;
}
/* polish pass */
.card {
    border-color: #6986be;
    padding: 12px;
    box-shadow: 0 1px 0 rgba(179, 198, 232, 0.09), 0 8px 22px rgba(0,0,0,0.36);
}
.hero-card {
    border-color: #86a2db;
    box-shadow: 0 1px 0 rgba(123, 149, 200, 0.30), 0 6px 18px rgba(79, 209, 197, 0.28);
}
.muted {
    color: #eaf0ff;
    line-height: 1.56;
}
entry,
spinbutton entry,
textview {
    background: #1f2a41;
    border: 1px solid #5a72a1;
    border-radius: 10px;
    color: #eef4ff;
}
entry:focus,
spinbutton entry:focus,
textview:focus {
    border-color: #8fb4ff;
    box-shadow: 0 0 0 2px rgba(139, 175, 255, 0.30);
}
dropdown > button {
    border-radius: 10px;
    min-height: 34px;
}
.study-room-actions button {
    min-height: 36px;
    font-weight: 650;
    padding: 6px 10px;
}
button.coach-action {
    background: #30435f;
    border-color: #7b96c7;
    color: #eaf0ff;
}
button.coach-action:hover {
    background: #3a5071;
    border-color: #95b2e8;
}
scrolledwindow {
    border-radius: 10px;
}
/* deep gtk4 polish pass */
.study-window {
    letter-spacing: 0.1px;
}
.workspace-root {
    background: linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.06),
        rgba(18, 23, 36, 0.0)
    );
}
.workspace-split {
    margin-top: 2px;
}
.top-menu {
    background: #1a263c;
    border-bottom: 1px solid #5d77aa;
    padding-top: 3px;
    padding-bottom: 3px;
    padding-left: 6px;
    padding-right: 6px;
}
.banner-shell {
    border-color: #8fb2ef;
    background-image: linear-gradient(
        to right,
        rgba(139, 175, 255, 0.24),
        rgba(139, 175, 255, 0.10)
    );
}
.banner-shell .banner-text {
    color: #f5f9ff;
    font-weight: 700;
    letter-spacing: 0.16px;
}
.panel-scroll {
    background: transparent;
}
.panel-stack {
    padding-top: 2px;
}
.section-expander > title {
    background: rgba(139, 175, 255, 0.14);
    border: 1px solid rgba(139, 175, 255, 0.28);
    border-radius: 9px;
    padding: 4px 6px;
}
.section-expander > title:hover {
    background: rgba(139, 175, 255, 0.22);
}
.topic-selector > button {
    background: #273855;
    border-color: #88a6de;
    font-weight: 650;
}
.topic-selector > button > box > label {
    letter-spacing: 0.15px;
}
.inline-toolbar {
    border-bottom: 1px solid rgba(141, 169, 218, 0.34);
    padding-bottom: 4px;
    margin-bottom: 2px;
}
.list-card {
    background: linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.12),
        rgba(0, 0, 0, 0.0)
    );
}
.feature-card {
    border-width: 2px;
}
.tools-card button {
    min-height: 34px;
    font-weight: 640;
}
.metric-card {
    border-color: #7fa0db;
    background: #24344f;
}
.metric-card progressbar {
    min-height: 12px;
}
.badges-card {
    border-color: #6e8cc4;
}
.kpi-line {
    color: #eef4ff;
    font-weight: 660;
    letter-spacing: 0.12px;
}
.dashboard-stack > .card {
    margin-top: 4px;
    margin-bottom: 8px;
}
"""

provider = Gtk.CssProvider()

def apply_theme(use_system: bool) -> None:
    css = SYSTEM_THEME_CSS if use_system else COACH_THEME_CSS
    try:
        # Gtk4 prefers load_from_string(str). Decode bytes constants explicitly.
        if hasattr(provider, "load_from_string"):
            css_text = css.decode("utf-8", errors="replace") if isinstance(css, (bytes, bytearray)) else str(css)
            provider.load_from_string(css_text)
        else:
            provider.load_from_data(css)
    except Exception:
        # Fallback path for bindings that may reject one API variant.
        try:
            provider.load_from_data(css)
        except Exception:
            return
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
