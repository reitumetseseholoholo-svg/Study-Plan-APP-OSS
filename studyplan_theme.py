#!/usr/bin/env python3
import gi  # type: ignore[import-untyped]

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk  # type: ignore[reportAttributeAccessIssue,import-untyped]

SYSTEM_THEME_CSS = """
@define-color app_accent alpha(@theme_selected_bg_color, 0.98);
@define-color app_border alpha(@theme_fg_color, 0.30);
@define-color app_border_strong alpha(@theme_fg_color, 0.48);
@define-color app_surface alpha(@theme_bg_color, 0.93);
@define-color app_surface_alt alpha(@theme_bg_color, 0.90);
@define-color app_muted alpha(@theme_fg_color, 0.99);


@keyframes badge-unlock-pulse {
    0%   { box-shadow: 0 0 0 0 alpha(@theme_selected_bg_color, 0.8); transform: scale(1.0); }
    40%  { box-shadow: 0 0 0 8px alpha(@theme_selected_bg_color, 0.0); transform: scale(1.15); }
    70%  { transform: scale(0.96); }
    100% { transform: scale(1.0); }
}

window.app-dialog-window {
    border-radius: 12px;
}


window.app-dialog-window button {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 9px;
}

window.app-dialog-window button.dialog-action {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 9px;
}

window.app-dialog-window button.suggested-action {
    min-height: 30px;
}

window.app-dialog-window spinbutton button {
    min-height: 22px;
    min-width: 22px;
    padding: 1px 4px;
}

window.app-dialog-window spinbutton entry {
    min-height: 26px;
}

window.compact {
    font-size: 12px;
}

window.compact .card {
    padding: 6px;
}

window.compact .panel {
    padding: 8px;
}

window.compact .plan-meta {
    font-size: 10px;
}

window.compact .section-title {
    font-size: 11px;
    letter-spacing: 0.5px;
}

window.compact .study-summary {
    font-size: 11px;
}

window.compact .title {
    font-size: 17px;
}

window.compact button {
    padding: 4px 6px;
}

window.high-contrast .card {
    border-color: alpha(@theme_fg_color, 0.68);
}

window.high-contrast .coach-title {
    color: @theme_fg_color;
    border-color: alpha(@theme_fg_color, 0.72);
}

window.high-contrast .hint {
    color: alpha(@theme_fg_color, 0.82);
}

window.high-contrast .muted {
    color: alpha(@theme_fg_color, 0.90);
}

window.high-contrast .panel {
    border-color: alpha(@theme_fg_color, 0.58);
}

window.high-contrast .panel-left {
    border-color: alpha(@theme_fg_color, 0.58);
}

window.high-contrast .panel-right {
    border-color: alpha(@theme_fg_color, 0.58);
}

window.high-contrast .section-title {
    color: @theme_fg_color;
    border-color: alpha(@theme_fg_color, 0.72);
}

window.high-contrast label.coach-title {
    color: @theme_fg_color;
    border-color: alpha(@theme_fg_color, 0.72);
}

window.high-contrast label.section-title {
    color: @theme_fg_color;
    border-color: alpha(@theme_fg_color, 0.72);
}

window.pomodoro-active .badges-card {
    opacity: 0.45;
}

window.pomodoro-active .card:not(.hero-card):not(.study-room-card) {
    opacity: 0.55;
    transition: opacity 400ms ease;
}

window.pomodoro-active .hero-card {
    opacity: 1.0;
}

window.pomodoro-active .quest-card {
    opacity: 0.45;
}

window.pomodoro-active .study-room-card {
    opacity: 1.0;
}

window.pomodoro-active .tools-card {
    opacity: 0.45;
}

window.sidebar-collapsed .panel-right {
    margin-left: 0;
    border-left: 1px solid app_border;
    box-shadow: none;
}

window.tile .card {
    padding: 8px;
}

window.tile .coach-title {
    font-size: 11px;
}

window.tile .panel-left {
    margin-right: 10px;
    border-right: 2px solid app_border_strong;
}

window.tile .panel-right {
    margin-left: 10px;
    border-left: 2px solid app_border_strong;
}

window.tile .section-title {
    font-size: 11px;
}

.action-timer {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", "Symbols Nerd Font", sans-serif;
    font-weight: 780;
    font-size: 19px;
    letter-spacing: 0.35px;
}

.allow-wrap {
    -gtk-line-limit: 0;
}

.badge {
    background: alpha(@theme_fg_color, 0.1);
    border: 1px solid alpha(@theme_fg_color, 0.24);
    border-radius: 999px;
    padding: 2px 8px;
    transition: box-shadow 300ms ease, border-color 200ms ease;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.10),
        alpha(@theme_selected_bg_color, 0.0)
        );
}

.badge-highlight {
    box-shadow: 0 0 0 5px alpha(@theme_selected_bg_color, 0.55);
    transition: box-shadow 500ms ease-out;
}

.badge-locked {
    background: alpha(@theme_fg_color, 0.05);
    border: 1px dashed alpha(@theme_fg_color, 0.22);
    border-radius: 999px;
    padding: 2px 8px;
    color: alpha(@theme_fg_color, 0.6);
}

.badges-card {
    border-color: alpha(@theme_selected_bg_color, 0.38);
}

.banner-shell {
    border-color: alpha(@theme_selected_bg_color, 0.72);
    background-image:
        linear-gradient(
        to right,
        alpha(@theme_selected_bg_color, 0.16),
        alpha(@theme_selected_bg_color, 0.06)
        );
}

.banner-shell .banner-text {
    font-weight: 690;
    letter-spacing: 0.16px;
}

.card {
    background-color: alpha(@theme_bg_color, 0.88);
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.025),
        alpha(@theme_selected_bg_color, 0.0)
        );
    border: 2px solid alpha(@theme_fg_color, 0.46);
    border-radius: 12px;
    padding: 14px;
    box-shadow:
        0 1px 3px alpha(@theme_fg_color, 0.08),
        0 4px 12px alpha(@theme_fg_color, 0.06);
    margin-top: 6px;
    margin-bottom: 6px;
    transition: border-color 180ms ease, box-shadow 180ms ease, background-color 180ms ease;
    border-color: alpha(@theme_fg_color, 0.30);
}

.card-tight {
    padding: 7px;
}

.card:hover {
    border-color: alpha(@theme_selected_bg_color, 0.96);
    box-shadow:
        0 0 0 1px alpha(@theme_selected_bg_color, 0.48),
        0 6px 20px alpha(@theme_selected_bg_color, 0.18),
        0 2px 6px alpha(@theme_fg_color, 0.10);
}

.chart-card {
    padding-top: 8px;
    padding-bottom: 6px;
    padding-left: 4px;
    padding-right: 4px;
}

.chart-card:hover {
    border-color: #b2caff;
    background: #263653;
    box-shadow: 0 0 0 1px rgba(139, 175, 255, 0.40), 0 7px 22px rgba(139, 175, 255, 0.22);
}

.coach-card {
    border-left: 3px solid alpha(@theme_selected_bg_color, 0.72);
}

.coach-title {
    font-weight: 820;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.62px;
    color: alpha(@theme_fg_color, 1.0);
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.42),
        alpha(@theme_selected_bg_color, 0.24)
        );
    border: 1px solid alpha(@theme_selected_bg_color, 0.82);
    border-radius: 10px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
    -gtk-line-limit: 1;
}

.cockpit-live-card {
    border-left: 4px solid alpha(@theme_selected_bg_color, 0.85);
}

.concept-bar {
    background: alpha(@theme_selected_bg_color, 0.06);
    border-left: 3px solid alpha(@theme_selected_bg_color, 0.5);
    border-radius: 6px;
    padding: 5px 10px;
    margin-top: 4px;
}

.dashboard-block-body {
    color: alpha(@theme_fg_color, 1.0);
    font-size: 13px;
    line-height: 1.58;
}

.dashboard-stack > .card {
    margin-top: 4px;
    margin-bottom: 8px;
}

.error {
    background-color: @error_color;
}

.exam-urgent {
    color: #cc0000;
    font-weight: bold;
}

.exam-warning {
    color: #cc6600;
    font-weight: bold;
}

.feature-card {
    border-width: 2px;
}

.focus-list row {
    border: none;
    padding: 3px 4px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
    min-height: 28px;
}

.focus-list row:selected {
    background: alpha(@theme_selected_bg_color, 0.12);
}

.heatmap-active {
    background-color: mix(@theme_selected_bg_color, green, 0.6);
    border-radius: 2px;
    min-width: 10px;
    min-height: 10px;
}

.heatmap-future {
    background-color: alpha(@theme_fg_color, 0.04);
    border-radius: 2px;
    min-width: 10px;
    min-height: 10px;
}

.heatmap-inactive {
    background-color: alpha(@theme_fg_color, 0.10);
    border-radius: 2px;
    min-width: 10px;
    min-height: 10px;
}

.hero-card {
    border-color: alpha(@theme_selected_bg_color, 0.72);
    box-shadow:
        0 1px 0 alpha(@theme_selected_bg_color, 0.30),
        0 6px 20px alpha(@theme_selected_bg_color, 0.22),
        0 2px 6px alpha(@theme_fg_color, 0.10);
    transition: border-color 180ms ease, box-shadow 200ms ease;
}

.hero-card .coach-title {
    color: app_accent;
}

.hero-card .section-title {
    color: app_accent;
}

.hero-card.coach-card {
    border-left: 4px solid alpha(@theme_selected_bg_color, 0.78);
}

.hint {
    color: alpha(@theme_fg_color, 0.72);
    font-size: 11px;
    font-style: normal;
}

.hint-level-0 {
    border-left: 3px solid alpha(@theme_selected_bg_color, 0.25);
    padding-left: 8px;
}

.hint-level-1 {
    border-left: 3px solid alpha(@theme_selected_bg_color, 0.40);
    padding-left: 8px;
}

.hint-level-2 {
    border-left: 3px solid alpha(@theme_selected_bg_color, 0.55);
    padding-left: 8px;
}

.hint-level-3 {
    border-left: 3px solid alpha(@theme_selected_bg_color, 0.72);
    padding-left: 8px;
    background: alpha(@theme_selected_bg_color, 0.04);
}

.hint-level-4 {
    border-left: 3px solid alpha(@theme_selected_bg_color, 0.90);
    padding-left: 8px;
    background: alpha(@theme_selected_bg_color, 0.08);
}

.inline-toolbar {
    border-bottom: 1px solid alpha(@theme_fg_color, 0.11);
    padding-bottom: 3px;
    margin-bottom: 1px;
}

.inline-toolbar button.flat {
    min-height: 32px;
    padding: 4px 8px;
}

.insight-card {
    border-left: 4px solid alpha(@theme_selected_bg_color, 0.42);
    background-image:
        linear-gradient(
        to right,
        alpha(@theme_selected_bg_color, 0.07),
        alpha(@theme_bg_color, 0.0)
        );
    border-left-width: 5px;
}

.insight-card .section-title {
    margin-bottom: 8px;
}

.kpi-line {
    font-weight: 620;
    letter-spacing: 0.1px;
    font-size: 12px;
    line-height: 1.42;
}

.list-card {
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.08),
        alpha(@theme_bg_color, 0.0)
        );
}

.metric-card {
    border-color: alpha(@theme_selected_bg_color, 0.46);
}

.metric-card progressbar {
    min-height: 12px;
}

.muted {
    color: alpha(@theme_fg_color, 0.92);
    line-height: 1.56;
}

.nav-button {
    min-height: 36px;
    padding: 6px 12px;
    font-weight: 600;
    border-radius: 10px;
}

.nav-button:focus-visible {
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.4);
}

.nav-button:hover {
    background: alpha(@theme_fg_color, 0.08);
}

.navigation-bar {
    background: alpha(@theme_bg_color, 0.92);
    border-bottom: 1px solid app_border;
    padding: 6px 10px;
    min-height: 44px;
}

.nudge-good {
    color: @success_color;
    font-weight: 760;
    font-style: italic;
    background-color: alpha(@success_color, 0.16);
    border: 1px solid alpha(@success_color, 0.36);
    border-radius: 10px;
    padding: 2px 8px;
}

.nudge-info {
    color: app_accent;
    font-weight: 700;
    font-style: italic;
    background-color: alpha(@theme_selected_bg_color, 0.16);
    border: 1px solid alpha(@theme_selected_bg_color, 0.36);
    border-radius: 10px;
    padding: 2px 8px;
}

.nudge-warn {
    color: @warning_color;
    font-weight: 760;
    font-style: italic;
    line-height: 1.18;
    background-color: alpha(@warning_color, 0.12);
    border: 1px solid alpha(@warning_color, 0.30);
    border-radius: 10px;
    padding: 4px 10px;
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

.panel-left .card {
    padding: 10px;
    margin-top: 3px;
    margin-bottom: 3px;
}

.panel-left .hero-card {
    padding: 10px 12px;
}

.panel-left .muted {
    font-size: 12px;
    line-height: 1.42;
}

.panel-left .section-title {
    background: transparent;
    background-image: none;
    border: none;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 0;
    padding: 2px 0 4px 0;
    margin-top: 8px;
    margin-bottom: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: alpha(@theme_fg_color, 0.72);
}

.panel-left label {
    -gtk-line-limit: 4;
}

.panel-left label.allow-wrap {
    -gtk-line-limit: 0;
}

.panel-left label.single-line-lock {
    -gtk-line-limit: 1;
}

.panel-right {
    background-color: alpha(@theme_bg_color, 0.935);
    border-left: 2px solid app_border_strong;
    border-top-left-radius: 14px;
    border-bottom-left-radius: 14px;
    margin-left: 8px;
    box-shadow: -2px 0 0 alpha(@theme_fg_color, 0.16);
}

.panel-scroll {
    background: transparent;
}

.panel-stack {
    padding-top: 2px;
}

.plan-meta {
    font-size: 11px;
}

.plan-title {
    font-weight: 760;
    color: alpha(@theme_fg_color, 1.0);
    letter-spacing: 0.15px;
    -gtk-line-limit: 1;
}

.quest-card {
    border: 1px solid app_border;
    border-radius: 12px;
    padding: 10px;
}

.quiz-content {
    margin-top: 4px;
    margin-bottom: 4px;
}

.quiz-dialog {
    min-width: 640px;
}

.quiz-feedback {
    margin-top: 6px;
    border-radius: 8px;
    padding: 6px 8px;
    background: alpha(@theme_fg_color, 0.045);
    transition: background 200ms ease;
}

.quiz-header {
    margin-bottom: 4px;
}

.quiz-hint {
    margin-top: 3px;
}

.quiz-meta {
    font-size: 12px;
}

.quiz-mix-row {
    margin-top: 2px;
    margin-bottom: 2px;
}

.quiz-option {
    border-radius: 10px;
    border: 1px solid app_border;
    padding: 9px 12px;
    margin-top: 3px;
    margin-bottom: 3px;
    transition: border-color 140ms ease, box-shadow 140ms ease, background 140ms ease;
}

.quiz-option label {
    font-size: 13px;
    line-height: 1.40;
    -gtk-line-limit: 0;
}

.quiz-option.quiz-correct {
    border-color: @success_color;
    background: alpha(@success_color, 0.12);
    box-shadow: 0 0 0 1px alpha(@success_color, 0.30);
}

.quiz-option.quiz-selected {
    border-color: alpha(@theme_selected_bg_color, 0.80);
    background: alpha(@theme_selected_bg_color, 0.10);
    box-shadow: 0 0 0 1px alpha(@theme_selected_bg_color, 0.36);
}

.quiz-option.quiz-wrong {
    border-color: @error_color;
    background: alpha(@error_color, 0.10);
    box-shadow: 0 0 0 1px alpha(@error_color, 0.25);
}

.quiz-option:hover {
    border-color: app_border_strong;
    background: alpha(@theme_fg_color, 0.06);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.18);
}

.quiz-progress {
    min-height: 8px;
}

.quiz-progress trough {
    min-height: 8px;
}

.quiz-question {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-weight: 700;
    font-size: 15px;
    line-height: 1.35;
}

.quiz-reason {
    margin-top: 3px;
}




.rule {
    color: alpha(@theme_fg_color, 0.24);
}

.section-expander > title {
    background: alpha(@theme_fg_color, 0.05);
    border-radius: 9px;
    padding: 4px 6px;
}

.section-expander > title:hover {
    background: alpha(@theme_selected_bg_color, 0.10);
}

.section-title {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", "Symbols Nerd Font", sans-serif;
    font-weight: 820;
    font-size: 12px;
    letter-spacing: 0.55px;
    text-transform: uppercase;
    color: alpha(@theme_fg_color, 1.0);
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.40),
        alpha(@theme_selected_bg_color, 0.22)
        );
    border: 1px solid alpha(@theme_selected_bg_color, 0.78);
    border-radius: 10px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
    -gtk-line-limit: 1;
}

.section-title + .muted {
    margin-top: 1px;
}

.settings-grid {
    margin-top: 2px;
}

.settings-grid label {
    font-size: 12px;
}

.sidebar-toggle {
    min-height: 30px;
    padding: 4px 10px;
}

.single-line-lock {
    -gtk-line-limit: 1;
}

.status-bad {
    color: @error_color;
    font-weight: 600;
}
.status-info {
    color: @app_accent;
    font-weight: 600;
}

.status-line {
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.15px;
    padding: 2px 0;
}

.status-ok {
    color: @success_color;
    font-weight: 600;
}

.status-warn {
    color: @warning_color;
    font-weight: 600;
}

.study-room-actions button {
    min-height: 36px;
    font-weight: 650;
    padding: 6px 10px;
}

.study-summary {
    font-size: 12px;
    line-height: 1.4;
}

.study-window {
    letter-spacing: 0.1px;
}

.subtle-panel {
    background: alpha(@theme_fg_color, 0.02);
    border: 1px solid alpha(@theme_fg_color, 0.08);
    border-radius: 8px;
    padding: 8px 10px;
    margin-top: 4px;
    margin-bottom: 2px;
}

.success {
    background-color: @success_color;
}

.title {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", "Symbols Nerd Font", sans-serif;
    font-weight: 760;
    font-size: 22px;
    letter-spacing: 0.2px;
}

.tools-card button {
    min-height: 34px;
    font-weight: 640;
}

.top-menu {
    background: alpha(@theme_bg_color, 0.84);
    border-bottom: 1px solid alpha(@theme_fg_color, 0.16);
    padding-top: 3px;
    padding-bottom: 3px;
    padding-left: 6px;
    padding-right: 6px;
    min-height: 28px;
    padding: 2px 8px;
}

.top-menu button {
    min-height: 24px;
    padding: 2px 8px;
    font-size: 12px;
    border-radius: 6px;
}

.topic-selector > button {
    font-weight: 650;
}

.topic-selector > button > box > label {
    letter-spacing: 0.15px;
}

.tutor-prompt-hint {
    font-size: 11px;
    padding: 2px 6px 2px 0;
}

.tutor-prompt-scroll {
    border-radius: 8px;
    border: 1px solid alpha(@theme_fg_color, 0.12);
    background: alpha(@theme_bg_color, 0.60);
}

.tutor-prompt-view {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-size: 13px;
    line-height: 1.52;
    padding: 8px 10px;
}

.tutor-response-scroll {
    border-radius: 8px;
    border: 1px solid alpha(@theme_fg_color, 0.12);
    background: alpha(@theme_bg_color, 0.60);
}

.tutor-response-view {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-size: 13px;
    line-height: 1.52;
    padding: 8px 10px;
}

.tutor-stream-pulse {
    min-height: 4px;
    padding: 0;
    border: none;
    background: transparent;
}

.tutor-stream-pulse progress {
    min-height: 4px;
    border-radius: 2px;
    background: linear-gradient(to right, @theme_selected_bg_color, alpha(@theme_selected_bg_color, 0.5));
}

.tutor-stream-pulse trough {
    min-height: 4px;
    border-radius: 2px;
    background: alpha(@theme_fg_color, 0.08);
}

.tutor-thinking-row {
    padding: 4px 10px;
    min-height: 28px;
    background: alpha(@theme_fg_color, 0.03);
    border-radius: 8px;
}

.warning {
    background-color: @warning_color;
}

.workbench-header {
    padding: 4px 8px 4px 8px;
    min-height: 32px;
}

.workbench-header-primary {
    min-height: 28px;
}

.workbench-quick-actions {
    padding: 2px 0 4px 0;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
}

.workbench-quick-actions button {
    min-height: 26px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 600;
    border-radius: 6px;
}

.workbench-status {
    font-family: "IBM Plex Sans", "Cantarell", "Noto Sans", sans-serif;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.18px;
    padding: 3px 8px;
    min-height: 20px;
    border-radius: 0;
    border: none;
    border-top: 1px solid alpha(@theme_fg_color, 0.10);
    background: alpha(@theme_selected_bg_color, 0.055);
    color: alpha(@theme_fg_color, 0.78);
}

.workbench-title {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.15px;
    -gtk-line-limit: 1;
}

.workspace-root {
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 0.04),
        alpha(@theme_bg_color, 0.0)
        );
}

.workspace-split {
    margin-top: 2px;
}

.workspace-tabs button {
    min-height: 28px;
    padding: 4px 12px;
    border-radius: 0;
    border: none;
    border-bottom: 2px solid transparent;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
    color: alpha(@theme_fg_color, 0.62);
    box-shadow: none;
}

.workspace-tabs button:checked {
    color: @theme_fg_color;
    border-bottom-color: alpha(@theme_selected_bg_color, 0.90);
    background: transparent;
    box-shadow: none;
}

.workspace-tabs button:hover {
    color: alpha(@theme_fg_color, 0.88);
    background: alpha(@theme_fg_color, 0.04);
    border-bottom-color: alpha(@theme_fg_color, 0.20);
}

.xp-progress {
    min-height: 12px;
}

.xp-progress progress {
    box-shadow: 0 0 8px 2px alpha(@theme_selected_bg_color, 0.40);
}

button {
    border-radius: 10px;
    padding: 6px 10px;
    min-height: 32px;
    background: alpha(@theme_fg_color, 0.07);
    border: 1px solid alpha(@theme_fg_color, 0.26);
    color: @theme_fg_color;
    box-shadow: 0 1px 0 alpha(@theme_bg_color, 0.22);
    transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
}

button.coach-action {
    background: alpha(@theme_selected_bg_color, 0.15);
    border-color: alpha(@theme_selected_bg_color, 0.48);
}

button.coach-action:hover {
    background: alpha(@theme_selected_bg_color, 0.24);
}

button.flat {
    background: transparent;
    border-color: transparent;
    box-shadow: none;
}

button.flat:active {
    background: alpha(@theme_fg_color, 0.12);
    border-color: alpha(@theme_fg_color, 0.24);
}

button.flat:hover {
    background: alpha(@theme_fg_color, 0.08);
    border-color: alpha(@theme_fg_color, 0.2);
}

button.suggested-action {
    background: @theme_selected_bg_color;
    color: @theme_selected_fg_color;
    border-color: alpha(@theme_selected_fg_color, 0.4);
    box-shadow:
        0 1px 0 alpha(@theme_selected_fg_color, 0.22),
        0 3px 10px alpha(@theme_selected_bg_color, 0.42);
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_selected_bg_color, 1.0),
        mix(@theme_selected_bg_color, @theme_fg_color, 0.06)
        );
}

button.suggested-action:active {
    background: mix(@theme_selected_bg_color, @theme_fg_color, 0.24);
}

button.suggested-action:hover {
    background: mix(@theme_selected_bg_color, @theme_fg_color, 0.16);
    background-image:
        linear-gradient(
        to bottom,
        mix(@theme_selected_bg_color, @theme_fg_color, 0.10),
        mix(@theme_selected_bg_color, @theme_fg_color, 0.14)
        );
}

button:active {
    background: alpha(@theme_fg_color, 0.16);
    border-color: alpha(@theme_fg_color, 0.42);
    transition: background 60ms ease;
}

button:disabled {
    background: alpha(@theme_fg_color, 0.04);
    border-color: alpha(@theme_fg_color, 0.12);
    color: alpha(@theme_fg_color, 0.5);
    box-shadow: none;
}

button:focus-visible {
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.50);
}

button:hover {
    background: alpha(@theme_fg_color, 0.12);
    border-color: alpha(@theme_fg_color, 0.36);
}

dropdown > button {
    border-radius: 10px;
    min-height: 34px;
}

dropdown > button:focus-visible {
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.35);
}

entry {
    background: alpha(@theme_bg_color, 0.82);
    border: 1px solid alpha(@theme_fg_color, 0.22);
    border-radius: 10px;
}

entry:focus {
    border-color: alpha(@theme_selected_bg_color, 0.72);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.22);
}

entry:focus-visible {
    outline: none;
    border-color: alpha(@theme_selected_bg_color, 0.78);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.50);
}

expander.muted {
    margin-top: 4px;
    margin-bottom: 4px;
}

expander.muted label {
    font-size: 12px;
}

label.coach-title {
    color: alpha(@theme_fg_color, 1.0);
    font-weight: 820;
}

label.plan-title {
    color: alpha(@theme_fg_color, 1.0);
    font-weight: 760;
}

label.section-title {
    color: alpha(@theme_fg_color, 1.0);
    font-weight: 820;
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

paned.horizontal > separator {
    min-height: 4px;
    min-width: 4px;
    background: alpha(@theme_fg_color, 0.06);
    border: none;
    margin: 2px 0;
}

paned.vertical > separator {
    min-height: 4px;
    min-width: 4px;
    background: alpha(@theme_fg_color, 0.06);
    border: none;
    margin: 0 2px;
}

paned > separator:hover {
    background: alpha(@theme_selected_bg_color, 0.25);
}

progressbar {
    min-height: 11px;
}

progressbar progress {
    border-radius: 999px;
    background-color: app_accent;
    box-shadow: 0 0 6px 1px alpha(@theme_selected_bg_color, 0.35);
    transition: background-color 300ms ease;
    background-image: none;
}

progressbar trough {
    border-radius: 999px;
    background-color: alpha(@theme_fg_color, 0.2);
}

scrollbar {
    min-width: 8px;
    min-height: 8px;
}

scrollbar slider {
    background-color: alpha(@theme_fg_color, 0.25);
    border-radius: 999px;
}

scrollbar slider:active {
    background-color: alpha(@theme_fg_color, 0.5);
}

scrollbar slider:hover {
    background-color: alpha(@theme_fg_color, 0.38);
}

scrolledwindow {
    border-radius: 10px;
}

spinbutton button {
    min-height: 24px;
    min-width: 24px;
    padding: 1px 5px;
    border-radius: 8px;
}

spinbutton entry {
    min-height: 28px;
    background: alpha(@theme_bg_color, 0.82);
    border: 1px solid alpha(@theme_fg_color, 0.22);
    border-radius: 10px;
}

spinbutton entry:focus {
    border-color: alpha(@theme_selected_bg_color, 0.72);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.22);
}

spinbutton entry:focus-visible {
    outline: none;
    border-color: alpha(@theme_selected_bg_color, 0.78);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.35);
}

textview {
    background: alpha(@theme_bg_color, 0.82);
    border: 1px solid alpha(@theme_fg_color, 0.22);
    border-radius: 10px;
}

textview:focus {
    border-color: alpha(@theme_selected_bg_color, 0.72);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.22);
}

textview:focus-visible {
    outline: none;
    border-color: alpha(@theme_selected_bg_color, 0.78);
    box-shadow: 0 0 0 2px alpha(@theme_selected_bg_color, 0.50);
}

tooltip {
    padding: 6px 8px;
    border-radius: 8px;
    border: 1px solid app_border;
}

window {
    background-color: @theme_bg_color;
    background-image:
        linear-gradient(
        to bottom,
        alpha(@theme_bg_color, 1.0),
        alpha(@theme_bg_color, 0.96)
        );
    color: @theme_fg_color;
}

/* Exam countdown card */
.exam-countdown-card {
    border-left: 4px solid alpha(@theme_selected_bg_color, 0.50);
}

/* Chart color palette (used by dashboard Cairo charts) */
@define-color chart_fig_bg #1a2233;
@define-color chart_ax_bg #1a2233;
@define-color chart_text #dbe4f4;
@define-color chart_muted #b1bfd8;
@define-color chart_grid #465a7d;
@define-color chart_spine #5d739b;
@define-color chart_accent_a #6aa4ff;
@define-color chart_accent_b #4fd1c5;
@define-color chart_accent_c #f6c453;
@define-color chart_accent_d #a18bff;
@define-color chart_legend_bg #202b41;

"""

COACH_THEME_CSS = """
@define-color coach_bg #121724;
@define-color coach_panel #1a2233;
@define-color coach_card #212d43;
@define-color coach_border #647fb3;
@define-color coach_border_strong #9bb8ef;
@define-color app_accent #8bafff;
@define-color coach_text #e8edf7;
@define-color coach_muted #e4edff;
@define-color coach_accent #4fd1c5;
@define-color coach_accent_alt #8bafff;


@keyframes badge-unlock-pulse {
    0%   { box-shadow: 0 0 0 0 alpha(@theme_selected_bg_color, 0.8); transform: scale(1.0); }
    40%  { box-shadow: 0 0 0 8px alpha(@theme_selected_bg_color, 0.0); transform: scale(1.15); }
    70%  { transform: scale(0.96); }
    100% { transform: scale(1.0); }
}

window.app-dialog-window {
    border-radius: 12px;
}


window.app-dialog-window button {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 9px;
}

window.app-dialog-window button.dialog-action {
    min-height: 30px;
    padding: 4px 10px;
    border-radius: 9px;
}

window.app-dialog-window button.suggested-action {
    min-height: 30px;
}

window.app-dialog-window spinbutton button {
    min-height: 22px;
    min-width: 22px;
    padding: 1px 4px;
}

window.app-dialog-window spinbutton entry {
    min-height: 26px;
}

window.compact {
    font-size: 12px;
}

window.compact .card {
    padding: 8px;
    border-radius: 10px;
}

window.compact .panel {
    padding: 8px;
}

window.compact .plan-meta {
    font-size: 10px;
}

window.compact .section-title {
    font-size: 11px;
    letter-spacing: 0.5px;
}

window.compact .study-summary {
    font-size: 11px;
}

window.compact .title {
    font-size: 17px;
}

window.compact button {
    padding: 4px 6px;
}

window.high-contrast .card {
    border-color: #b2caff;
}

window.high-contrast .coach-title {
    color: #f5f8ff;
    border-color: #b2caff;
}

window.high-contrast .hint {
    color: #c8d4eb;
}

window.high-contrast .muted {
    color: #d4dff5;
}

window.high-contrast .panel {
    border-color: #9bb8ef;
}

window.high-contrast .panel-left {
    border-color: #9bb8ef;
}

window.high-contrast .panel-right {
    border-color: #9bb8ef;
}

window.high-contrast .section-title {
    color: #f5f8ff;
    border-color: #b2caff;
}

window.high-contrast label.coach-title {
    color: #f5f8ff;
    border-color: #b2caff;
}

window.high-contrast label.section-title {
    color: #f5f8ff;
    border-color: #b2caff;
}

window.pomodoro-active .badges-card {
    opacity: 0.40;
}

window.pomodoro-active .card:not(.hero-card):not(.study-room-card) {
    opacity: 0.50;
    transition: opacity 400ms ease;
}

window.pomodoro-active .hero-card {
    opacity: 1.0;
}

window.pomodoro-active .quest-card {
    opacity: 0.40;
}

window.pomodoro-active .study-room-card {
    opacity: 1.0;
}

window.pomodoro-active .tools-card {
    opacity: 0.40;
}

window.sidebar-collapsed .panel-right {
    margin-left: 0;
    border-left: 1px solid coach_border;
    box-shadow: none;
}

window.tile .card {
    padding: 10px;
    border-radius: 11px;
}

window.tile .coach-title {
    font-size: 11px;
}

window.tile .panel-left {
    margin-right: 10px;
    border-right: 2px solid coach_border_strong;
}

window.tile .panel-right {
    margin-left: 10px;
    border-left: 2px solid coach_border_strong;
}

window.tile .section-title {
    font-size: 11px;
}

.action-timer {
    font-weight: 780;
    font-size: 19px;
    letter-spacing: 0.35px;
    color: coach_text;
}

.allow-wrap {
    -gtk-line-limit: 0;
}

.badge {
    background: #252f44;
    border: 1px solid #536684;
    border-radius: 999px;
    padding: 2px 8px;
    color: coach_text;
    transition: box-shadow 300ms ease, border-color 200ms ease;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
    background-image:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.14),
        rgba(139, 175, 255, 0.02)
        );
}

.badge-highlight {
    box-shadow: 0 0 0 5px rgba(79, 209, 197, 0.65);
    transition: box-shadow 500ms ease-out;
}

.badge-locked {
    background: #1d2534;
    border: 1px dashed #44536e;
    border-radius: 999px;
    padding: 2px 8px;
    color: #7f8792;
}

.badges-card {
    border-color: #6e8cc4;
}

.banner-shell {
    border-color: #8fb2ef;
    background-image:
        linear-gradient(
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

.card {
    background: #23314a;
    border: 2px solid #7590c5;
    border-radius: 13px;
    padding: 12px;
    box-shadow:
        0 1px 3px rgba(0, 0, 0, 0.24),
        0 4px 12px rgba(0, 0, 0, 0.18);
    margin-top: 6px;
    margin-bottom: 6px;
    border-color: #6986be;
    transition: border-color 180ms ease, box-shadow 180ms ease, background-color 180ms ease;
    background-image:
        linear-gradient(
        to bottom,
        rgba(255, 255, 255, 0.030),
        rgba(0, 0, 0, 0.0)
        );
}

.card-tight {
    padding: 7px;
}

.card:hover {
    border-color: #b2caff;
    background: #263653;
    box-shadow:
        0 0 0 1px rgba(139, 175, 255, 0.52),
        0 6px 20px rgba(139, 175, 255, 0.16),
        0 2px 6px rgba(0, 0, 0, 0.28);
    background-image:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.060),
        rgba(0, 0, 0, 0.0)
        );
}

.chart-card {
    padding-top: 8px;
    padding-bottom: 6px;
    padding-left: 4px;
    padding-right: 4px;
}

.chart-card:hover {
    border-color: #b2caff;
    background: #263653;
    box-shadow: 0 0 0 1px rgba(139, 175, 255, 0.40), 0 7px 22px rgba(139, 175, 255, 0.22);
}

.coach-card {
    border-left: 3px solid rgba(139, 175, 255, 0.78);
}

.coach-title {
    font-weight: 820;
    letter-spacing: 0.62px;
    color: #f5f8ff;
    text-transform: uppercase;
    font-size: 12px;
    background:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.48),
        rgba(139, 175, 255, 0.28)
        );
    border: 1px solid rgba(139, 175, 255, 0.92);
    border-radius: 10px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
}

.cockpit-live-card {
    border-left: 4px solid alpha(#4dabf7, 0.85);
}

.concept-bar {
    background: rgba(139, 175, 255, 0.06);
    border-left: 3px solid rgba(139, 175, 255, 0.5);
    border-radius: 6px;
    padding: 5px 10px;
    margin-top: 4px;
}

.dashboard-block-body {
    color: #f2f7ff;
    font-size: 13px;
    line-height: 1.58;
}

.dashboard-stack > .card {
    margin-top: 4px;
    margin-bottom: 8px;
}

.error {
    background-color: #6d2a2a;
}

.exam-urgent {
    color: #ff4444;
    font-weight: bold;
}

.exam-warning {
    color: #ff9900;
    font-weight: bold;
}

.feature-card {
    border-width: 2px;
}

.focus-list row {
    border: none;
    padding: 3px 4px;
    border-bottom: 1px solid rgba(101, 122, 158, 0.22);
    min-height: 28px;
}

.focus-list row:selected {
    background: rgba(79, 209, 197, 0.12);
}

.heatmap-active {
    background-color: #3dba73;
    border-radius: 2px;
    min-width: 10px;
    min-height: 10px;
}

.heatmap-future {
    background-color: rgba(255, 255, 255, 0.04);
    border-radius: 2px;
    min-width: 10px;
    min-height: 10px;
}

.heatmap-inactive {
    background-color: rgba(255, 255, 255, 0.10);
    border-radius: 2px;
    min-width: 10px;
    min-height: 10px;
}

.hero-card {
    border-color: #86a2db;
    box-shadow:
        0 1px 0 rgba(123, 149, 200, 0.32),
        0 8px 24px rgba(79, 209, 197, 0.22),
        0 2px 6px rgba(0, 0, 0, 0.32);
    transition: border-color 180ms ease, box-shadow 200ms ease;
    background-image:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.070),
        rgba(139, 175, 255, 0.018)
        );
}

.hero-card .coach-title {
    color: coach_accent;
}

.hero-card .section-title {
    color: coach_accent;
}

.hero-card.coach-card {
    border-left: 4px solid rgba(139, 175, 255, 0.82);
}

.hint {
    color: #a8b3ca;
    font-size: 11px;
    font-style: normal;
}

.hint-level-0 {
    border-left: 3px solid rgba(139, 175, 255, 0.25);
    padding-left: 8px;
}

.hint-level-1 {
    border-left: 3px solid rgba(139, 175, 255, 0.40);
    padding-left: 8px;
}

.hint-level-2 {
    border-left: 3px solid rgba(139, 175, 255, 0.55);
    padding-left: 8px;
}

.hint-level-3 {
    border-left: 3px solid rgba(139, 175, 255, 0.72);
    padding-left: 8px;
    background: rgba(139, 175, 255, 0.05);
}

.hint-level-4 {
    border-left: 3px solid rgba(139, 175, 255, 0.90);
    padding-left: 8px;
    background: rgba(139, 175, 255, 0.10);
}

.inline-toolbar {
    border-bottom: 1px solid rgba(141, 169, 218, 0.34);
    padding-bottom: 3px;
    margin-bottom: 1px;
}

.inline-toolbar button.flat {
    min-height: 32px;
    padding: 4px 8px;
}

.insight-card {
    border-left: 5px solid rgba(139, 175, 255, 0.65);
    background:
        linear-gradient(
        to right,
        rgba(139, 175, 255, 0.11),
        rgba(33, 45, 67, 0.0)
        );
}

.insight-card .section-title {
    margin-bottom: 8px;
}

.kpi-line {
    color: #eef4ff;
    font-weight: 620;
    letter-spacing: 0.1px;
    font-size: 12px;
    line-height: 1.42;
}

.list-card {
    background:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.12),
        rgba(0, 0, 0, 0.0)
        );
}

.metric-card {
    border-color: #7fa0db;
    background: #24344f;
}

.metric-card progressbar {
    min-height: 12px;
}

.muted {
    color: #eaf0ff;
    line-height: 1.56;
}

.nav-button {
    min-height: 36px;
    padding: 6px 12px;
    font-weight: 600;
    border-radius: 10px;
}

.nav-button:focus-visible {
    box-shadow: 0 0 0 2px rgba(79, 209, 197, 0.45);
}

.nav-button:hover {
    background: rgba(79, 209, 197, 0.12);
}

.navigation-bar {
    background: rgba(26, 34, 51, 0.95);
    border-bottom: 1px solid coach_border;
    padding: 6px 10px;
    min-height: 44px;
}

.nudge-good {
    color: #4fd1c5;
    font-weight: 760;
    font-style: italic;
    background: rgba(79, 209, 197, 0.16);
    border: 1px solid rgba(79, 209, 197, 0.42);
    border-radius: 10px;
    padding: 2px 8px;
}

.nudge-info {
    color: #8bafff;
    font-weight: 700;
    font-style: italic;
    background: rgba(139, 175, 255, 0.16);
    border: 1px solid rgba(139, 175, 255, 0.42);
    border-radius: 10px;
    padding: 2px 8px;
}

.nudge-warn {
    color: #f6c453;
    font-weight: 760;
    font-style: italic;
    line-height: 1.18;
    background: rgba(246, 196, 83, 0.12);
    border: 1px solid rgba(246, 196, 83, 0.30);
    border-radius: 10px;
    padding: 4px 10px;
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

.panel-left .card {
    padding: 10px;
    margin-top: 3px;
    margin-bottom: 3px;
}

.panel-left .hero-card {
    padding: 10px 12px;
}

.panel-left .muted {
    font-size: 12px;
    line-height: 1.42;
}

.panel-left .section-title {
    background: transparent;
    background-image: none;
    border: none;
    border-bottom: 1px solid rgba(139, 175, 255, 0.22);
    border-radius: 0;
    padding: 2px 0 4px 0;
    margin-top: 8px;
    margin-bottom: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
    color: #90a8cc;
}

.panel-left label {
    -gtk-line-limit: 4;
}

.panel-left label.allow-wrap {
    -gtk-line-limit: 0;
}

.panel-left label.single-line-lock {
    -gtk-line-limit: 1;
}

.panel-right {
    background: #182135;
    border-left: 2px solid coach_border_strong;
    border-top-left-radius: 14px;
    border-bottom-left-radius: 14px;
    margin-left: 8px;
    box-shadow: -2px 0 0 rgba(155, 184, 239, 0.24);
}

.panel-scroll {
    background: transparent;
}

.panel-stack {
    padding-top: 2px;
}

.plan-meta {
    font-size: 11px;
}

.plan-title {
    font-weight: 760;
    color: #f5f8ff;
    letter-spacing: 0.15px;
}

.quest-card {
    background: #212d43;
    border: 1px solid #526487;
    border-radius: 13px;
    padding: 11px;
}

.quiz-content {
    margin-top: 4px;
    margin-bottom: 4px;
}

.quiz-dialog {
    min-width: 640px;
}

.quiz-feedback {
    margin-top: 6px;
    border-radius: 8px;
    padding: 6px 8px;
    background: #243047;
    transition: background 200ms ease;
}

.quiz-header {
    margin-bottom: 4px;
}

.quiz-hint {
    margin-top: 3px;
}

.quiz-meta {
    font-size: 12px;
}

.quiz-mix-row {
    margin-top: 2px;
    margin-bottom: 2px;
}

.quiz-option {
    border-radius: 10px;
    border: 1px solid coach_border;
    padding: 9px 12px;
    margin-top: 3px;
    margin-bottom: 3px;
    transition: border-color 140ms ease, box-shadow 140ms ease, background 140ms ease;
}

.quiz-option label {
    font-size: 13px;
    line-height: 1.40;
    -gtk-line-limit: 0;
}

.quiz-option.quiz-correct {
    border-color: #2f8a5c;
    background: rgba(47, 138, 92, 0.14);
    box-shadow: 0 0 0 1px rgba(47, 138, 92, 0.32);
}

.quiz-option.quiz-selected {
    border-color: rgba(139, 175, 255, 0.82);
    background: rgba(139, 175, 255, 0.12);
    box-shadow: 0 0 0 1px rgba(139, 175, 255, 0.38);
}

.quiz-option.quiz-wrong {
    border-color: #c85450;
    background: rgba(200, 84, 80, 0.12);
    box-shadow: 0 0 0 1px rgba(200, 84, 80, 0.28);
}

.quiz-option:hover {
    border-color: rgba(139, 175, 255, 0.80);
    background:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.10),
        rgba(139, 175, 255, 0.04)
        );
    box-shadow: 0 0 0 1px rgba(139, 175, 255, 0.24);
}

.quiz-progress {
    min-height: 8px;
}

.quiz-progress trough {
    min-height: 8px;
}

.quiz-question {
    font-weight: 700;
    font-size: 15px;
    line-height: 1.35;
}

.quiz-reason {
    margin-top: 3px;
}




.rule {
    color: #4d5d79;
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

.section-title {
    font-weight: 820;
    font-size: 12px;
    letter-spacing: 0.58px;
    text-transform: uppercase;
    color: #f5f8ff;
    background:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.46),
        rgba(139, 175, 255, 0.26)
        );
    border: 1px solid rgba(139, 175, 255, 0.90);
    border-radius: 10px;
    padding: 4px 10px;
    margin-top: 3px;
    margin-bottom: 6px;
}

.section-title + .muted {
    margin-top: 1px;
}

.settings-grid {
    margin-top: 2px;
}

.settings-grid label {
    font-size: 12px;
}

.sidebar-toggle {
    min-height: 30px;
    padding: 4px 10px;
}

.single-line-lock {
    -gtk-line-limit: 1;
}

.status-bad {
    color: #f28b82;
    font-weight: 600;
}
.status-info {
    color: @coach_accent_alt;
    font-weight: 600;
}

.status-line {
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.15px;
    padding: 2px 0;
    color: #c5d4f0;
}

.status-ok {
    color: coach_accent;
    font-weight: 600;
}

.status-warn {
    color: #f6c453;
    font-weight: 600;
}

.study-room-actions button {
    min-height: 36px;
    font-weight: 650;
    padding: 6px 10px;
}

.study-summary {
    font-size: 12px;
    line-height: 1.4;
}

.study-window {
    letter-spacing: 0.1px;
}

.subtle-panel {
    background: rgba(139, 175, 255, 0.04);
    border: 1px solid rgba(139, 175, 255, 0.10);
    border-radius: 8px;
    padding: 8px 10px;
    margin-top: 4px;
    margin-bottom: 2px;
}

.success {
    background-color: #1f5c3a;
}

.title {
    font-weight: 760;
    font-size: 22px;
    letter-spacing: 0.2px;
    color: coach_text;
}

.tools-card button {
    min-height: 34px;
    font-weight: 640;
}

.top-menu {
    background: #1a263c;
    border-bottom: 1px solid #5d77aa;
    padding-top: 3px;
    padding-bottom: 3px;
    padding-left: 6px;
    padding-right: 6px;
    min-height: 28px;
    padding: 2px 8px;
}

.top-menu button {
    min-height: 24px;
    padding: 2px 8px;
    font-size: 12px;
    border-radius: 6px;
}

.topic-selector > button {
    background: #273855;
    border-color: #88a6de;
    font-weight: 650;
}

.topic-selector > button > box > label {
    letter-spacing: 0.15px;
}

.tutor-prompt-hint {
    font-size: 11px;
    padding: 2px 6px 2px 0;
    color: rgba(234, 240, 255, 0.45);
}

.tutor-prompt-scroll {
    border-radius: 8px;
    border: 1px solid rgba(90, 114, 161, 0.40);
    background: #1a2438;
}

.tutor-prompt-view {
    font-size: 13px;
    line-height: 1.52;
    padding: 8px 10px;
    color: #eaf0ff;
}

.tutor-response-scroll {
    border-radius: 8px;
    border: 1px solid rgba(90, 114, 161, 0.40);
    background: #1a2438;
}

.tutor-response-view {
    font-size: 13px;
    line-height: 1.52;
    padding: 8px 10px;
    color: #eaf0ff;
}

.tutor-stream-pulse {
    min-height: 4px;
    padding: 0;
    border: none;
    background: transparent;
}

.tutor-stream-pulse progress {
    min-height: 4px;
    border-radius: 2px;
    background: linear-gradient(to right, #6fa8ff, rgba(111, 168, 255, 0.35));
}

.tutor-stream-pulse trough {
    min-height: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.08);
}

.tutor-thinking-row {
    padding: 4px 10px;
    min-height: 28px;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
}

.warning {
    background-color: #6a4b1f;
}

.workbench-header {
    padding: 4px 8px;
    min-height: 32px;
}

.workbench-header-primary {
    min-height: 28px;
}

.workbench-quick-actions {
    padding: 2px 0 4px 0;
    border-bottom: 1px solid rgba(139, 175, 255, 0.12);
}

.workbench-quick-actions button {
    min-height: 26px;
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 600;
    border-radius: 6px;
}

.workbench-status {
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.18px;
    padding: 3px 8px;
    min-height: 20px;
    border-radius: 0;
    border: none;
    border-top: 1px solid rgba(93, 119, 170, 0.48);
    background: #131c2e;
    color: #b8cadf;
}

.workbench-title {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.15px;
    color: #eaf0ff;
}

.workspace-root {
    background:
        linear-gradient(
        to bottom,
        rgba(139, 175, 255, 0.06),
        rgba(18, 23, 36, 0.0)
        );
}

.workspace-split {
    margin-top: 2px;
}

.workspace-tabs button {
    min-height: 28px;
    padding: 4px 12px;
    border-radius: 0;
    border: none;
    border-bottom: 2px solid transparent;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
    color: #7a90b8;
    box-shadow: none;
}

.workspace-tabs button:checked {
    color: #eaf0ff;
    border-bottom-color: #8bafff;
    background: transparent;
    box-shadow: none;
}

.workspace-tabs button:hover {
    color: #c5d4f0;
    background: rgba(139, 175, 255, 0.06);
    border-bottom-color: rgba(139, 175, 255, 0.24);
}

.xp-progress {
    min-height: 12px;
}

.xp-progress progress {
    box-shadow: 0 0 10px 3px rgba(79, 209, 197, 0.46);
    background-image:
        linear-gradient(
        to right,
        #4fd1c5,
        #82e6df
        );
}

button {
    background: #2d3b56;
    border: 1px solid #5b6f95;
    border-radius: 10px;
    color: coach_text;
    padding: 6px 10px;
    min-height: 32px;
    box-shadow: 0 1px 0 rgba(169, 190, 227, 0.12);
    transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
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

button.flat {
    background: transparent;
    border-color: transparent;
    box-shadow: none;
}

button.flat:active {
    background: #3b4b6b;
    border-color: #7a95c3;
}

button.flat:hover {
    background: #324160;
    border-color: #6881ad;
}

button.suggested-action {
    background: coach_accent;
    border-color: #7fe0d8;
    color: #072326;
    box-shadow:
        0 1px 0 rgba(188, 246, 240, 0.52),
        0 3px 12px rgba(79, 209, 197, 0.48);
    background-image:
        linear-gradient(
        to bottom,
        rgba(255, 255, 255, 0.20),
        rgba(0, 0, 0, 0.06)
        );
}

button.suggested-action:active {
    background: #54cfc3;
}

button.suggested-action:hover {
    background: #66ddd2;
    background-image:
        linear-gradient(
        to bottom,
        rgba(255, 255, 255, 0.28),
        rgba(0, 0, 0, 0.04)
        );
}

button:active {
    background: #3f5376;
    border-color: #8da9da;
    transition: background 60ms ease;
}

button:disabled {
    background: #26334d;
    border-color: #425579;
    color: #95a2bc;
    box-shadow: none;
}

button:focus-visible {
    box-shadow: 0 0 0 2px rgba(79, 209, 197, 0.50);
}

button:hover {
    background: #354766;
    border-color: #7d98c8;
}

dropdown > button {
    border-radius: 10px;
    min-height: 34px;
}

dropdown > button:focus-visible {
    box-shadow: 0 0 0 2px rgba(79, 209, 197, 0.4);
}

entry {
    background: #1f2a41;
    border: 1px solid #5a72a1;
    border-radius: 10px;
    color: #eef4ff;
}

entry:focus {
    border-color: #8fb4ff;
    box-shadow: 0 0 0 2px rgba(139, 175, 255, 0.30);
}

entry:focus-visible {
    outline: none;
    border-color: #b8d0ff;
    box-shadow: 0 0 0 2px rgba(139, 175, 255, 0.48);
}

expander.muted {
    margin-top: 4px;
    margin-bottom: 4px;
}

expander.muted label {
    font-size: 12px;
}

label.coach-title {
    color: #f5f8ff;
    font-weight: 820;
}

label.plan-title {
    color: #f5f8ff;
    font-weight: 760;
}

label.section-title {
    color: #f5f8ff;
    font-weight: 820;
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

paned.horizontal > separator {
    min-height: 4px;
    min-width: 4px;
    background: rgba(139, 175, 255, 0.08);
    border: none;
    margin: 2px 0;
}

paned.vertical > separator {
    min-height: 4px;
    min-width: 4px;
    background: rgba(139, 175, 255, 0.08);
    border: none;
    margin: 0 2px;
}

paned > separator:hover {
    background: rgba(139, 175, 255, 0.28);
}

progressbar {
    min-height: 11px;
    padding: 2px 0;
}

progressbar progress {
    border-radius: 999px;
    background-color: coach_accent_alt;
    box-shadow: 0 0 8px 2px rgba(139, 175, 255, 0.36);
    transition: background-color 300ms ease;
    background-image:
        linear-gradient(
        to right,
        #7facff,
        #b4ccff
        );
}

progressbar trough {
    border-radius: 999px;
    background-color: #2d3b56;
}

scrollbar {
    min-width: 8px;
    min-height: 8px;
}

scrollbar slider {
    background-color: #4b5b79;
    border-radius: 999px;
}

scrollbar slider:active {
    background-color: #7189b5;
}

scrollbar slider:hover {
    background-color: #5e7195;
}

scrolledwindow {
    border-radius: 10px;
}

spinbutton button {
    min-height: 24px;
    min-width: 24px;
    padding: 1px 5px;
    border-radius: 8px;
}

spinbutton entry {
    min-height: 28px;
    background: #1f2a41;
    border: 1px solid #5a72a1;
    border-radius: 10px;
    color: #eef4ff;
}

spinbutton entry:focus {
    border-color: #8fb4ff;
    box-shadow: 0 0 0 2px rgba(139, 175, 255, 0.30);
}

spinbutton entry:focus-visible {
    outline: none;
    border-color: #b8d0ff;
    box-shadow: 0 0 0 2px rgba(139, 175, 255, 0.48);
}

textview {
    background: #1f2a41;
    border: 1px solid #5a72a1;
    border-radius: 10px;
    color: #eef4ff;
}

textview:focus {
    border-color: #8fb4ff;
    box-shadow: 0 0 0 2px rgba(139, 175, 255, 0.30);
}

textview:focus-visible {
    outline: none;
    border-color: #b8d0ff;
    box-shadow: 0 0 0 2px rgba(139, 175, 255, 0.48);
}

tooltip {
    padding: 6px 8px;
    border-radius: 8px;
    border: 1px solid #3f5270;
}

window {
    background: coach_bg;
    color: coach_text;
    font-family: "IBM Plex Sans", "JetBrains Mono NL", "Noto Sans", "Symbols Nerd Font", sans-serif;
    background-image:
        linear-gradient(
        155deg,
        rgba(26, 38, 62, 0.55),
        rgba(18, 23, 36, 0.0) 72%
        );
}

/* Exam countdown card */
.exam-countdown-card {
    border-left: 4px solid rgba(139, 175, 255, 0.55);
}

/* Chart color palette (used by dashboard Cairo charts) */
@define-color chart_fig_bg #1c2230;
@define-color chart_ax_bg #1c2230;
@define-color chart_text #e8edf7;
@define-color chart_muted #b1bcd3;
@define-color chart_grid #42526f;
@define-color chart_spine #4c5d82;
@define-color chart_accent_a #4fd1c5;
@define-color chart_accent_b #8bafff;
@define-color chart_accent_c #f6c453;
@define-color chart_accent_d #9b7cff;
@define-color chart_legend_bg #202633;

"""

provider = Gtk.CssProvider()

_THEME_RUNTIME_OPTIONS: dict[str, object] = {
    "modern_enabled": False,
    "density_mode": "progressive",
    "reduce_motion": False,
    "legacy_fallback_enabled": True,
}

_THEME_TOKEN_SYSTEM: dict[str, dict[str, str]] = {
    "color": {
        "accent": "alpha(@theme_selected_bg_color, 0.92)",
        "text": "@theme_fg_color",
        "muted": "alpha(@theme_fg_color, 0.84)",
        "bg": "@theme_bg_color",
    },
    "surface": {
        "panel": "alpha(@theme_bg_color, 0.94)",
        "card": "alpha(@theme_bg_color, 0.90)",
        "card_alt": "alpha(@theme_bg_color, 0.86)",
    },
    "border": {
        "soft": "alpha(@theme_fg_color, 0.22)",
        "strong": "alpha(@theme_fg_color, 0.34)",
    },
}

_THEME_TOKEN_COACH: dict[str, dict[str, str]] = {
    "color": {
        "accent": "#8fb4ff",
        "text": "#e8edf7",
        "muted": "#d5def1",
        "bg": "#121724",
    },
    "surface": {
        "panel": "#1a2233",
        "card": "#22324b",
        "card_alt": "#1f2c42",
    },
    "border": {
        "soft": "#5b74a3",
        "strong": "#7c9ed7",
    },
}


def set_theme_runtime_options(
    *,
    modern_enabled: bool,
    density_mode: str = "progressive",
    reduce_motion: bool = False,
    legacy_fallback_enabled: bool = True,
) -> None:
    mode = str(density_mode or "progressive").strip().lower()
    if mode != "progressive":
        mode = "progressive"
    _THEME_RUNTIME_OPTIONS["modern_enabled"] = bool(modern_enabled)
    _THEME_RUNTIME_OPTIONS["density_mode"] = mode
    _THEME_RUNTIME_OPTIONS["reduce_motion"] = bool(reduce_motion)
    _THEME_RUNTIME_OPTIONS["legacy_fallback_enabled"] = bool(legacy_fallback_enabled)


def _theme_tokens(use_system: bool) -> dict[str, dict[str, str]]:
    return _THEME_TOKEN_SYSTEM if use_system else _THEME_TOKEN_COACH


def _build_modern_overlay_css(use_system: bool) -> str:
    tokens = _theme_tokens(use_system)
    color = tokens["color"]
    surface = tokens["surface"]
    border = tokens["border"]
    reduce_motion = bool(_THEME_RUNTIME_OPTIONS.get("reduce_motion", False))

    motion_css = ""
    if reduce_motion:
        motion_css = """
* {
    transition: none;
    animation: none;
}
"""

    return f"""
/* modern token overlay */
window.study-window {{
    color: {color["text"]};
}}
window.study-window .panel {{
    background: {surface["panel"]};
    border: 1px solid {border["soft"]};
    box-shadow: 0 1px 8px alpha({color["text"]}, 0.09);
}}
window.study-window .card {{
    background-color: {surface["card"]};
    background-image: linear-gradient(
        to bottom,
        alpha({color["accent"]}, 0.028),
        alpha({color["accent"]}, 0.0)
    );
    border: 1px solid {border["soft"]};
    border-radius: 12px;
    padding: 12px;
    box-shadow: 0 1px 0 alpha({color["text"]}, 0.06),
                0 4px 14px alpha({color["text"]}, 0.10);
}}
window.study-window .card:hover {{
    box-shadow: 0 0 0 1px alpha({color["accent"]}, 0.40),
                0 8px 22px alpha({color["accent"]}, 0.14),
                0 2px 6px alpha({color["text"]}, 0.10);
}}
window.study-window .hero-card {{
    border-color: {border["strong"]};
    background-color: {surface["card_alt"]};
    background-image: linear-gradient(
        to bottom,
        alpha({color["accent"]}, 0.055),
        alpha({color["accent"]}, 0.0)
    );
    box-shadow: 0 2px 14px alpha({color["accent"]}, 0.14),
                0 1px 4px alpha({color["text"]}, 0.10);
}}
window.study-window .section-title {{
    background: transparent;
    border: 0;
    color: {color["text"]};
    font-weight: 740;
    font-size: 12px;
    letter-spacing: 0.44px;
    padding: 0;
    margin-top: 2px;
    margin-bottom: 4px;
}}
window.study-window .muted {{
    color: {color["muted"]};
    line-height: 1.46;
}}
window.study-window .inline-toolbar {{
    border-bottom: 1px solid {border["soft"]};
    padding-bottom: 3px;
    margin-bottom: 2px;
}}
window.study-window .workbench-shell {{
    padding: 10px;
    border-radius: 14px;
}}
window.study-window.stack-layout .workbench-shell {{
    padding: 8px;
    border-radius: 11px;
}}
window.study-window.sidebar-collapsed .workbench-shell {{
    margin-left: 0;
    border-left: 1px solid {border["soft"]};
}}
window.study-window .workbench-header {{
    border-bottom: 1px solid {border["soft"]};
    padding-bottom: 6px;
    margin-bottom: 2px;
}}
window.study-window .workbench-header-primary {{
    min-height: 30px;
}}
window.study-window .workspace-tabs-scroll {{
    background: transparent;
    border: none;
    margin-top: 1px;
}}
window.study-window .workbench-quick-scroll {{
    background: transparent;
    margin-top: 1px;
}}
window.study-window .workbench-quick-actions {{
    border-bottom: 1px solid alpha({color["text"]}, 0.08);
    padding-bottom: 3px;
    margin-bottom: 0;
}}
window.study-window .workbench-quick-actions button {{
    min-height: 30px;
    padding: 4px 12px;
    border-radius: 8px;
}}
window.study-window .workbench-title {{
    margin-right: 6px;
    font-weight: 780;
    letter-spacing: 0.18px;
}}
window.study-window .workspace-tabs {{
    margin-left: 0;
    margin-right: 2px;
}}
window.study-window .workspace-tabs button {{
    min-height: 30px;
    padding: 4px 14px;
    border-radius: 8px;
    border: 1px solid alpha({color["text"]}, 0.13);
    background: alpha({color["text"]}, 0.04);
    transition: background 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
}}
window.study-window .workspace-tabs button:checked {{
    background-image: linear-gradient(
        to bottom,
        alpha({color["accent"]}, 0.28),
        alpha({color["accent"]}, 0.18)
    );
    border-color: alpha({color["accent"]}, 0.58);
    color: {color["text"]};
    box-shadow: 0 1px 0 alpha({color["accent"]}, 0.28),
                0 2px 6px alpha({color["accent"]}, 0.16);
    font-weight: 660;
}}
window.study-window .workspace-tabs button:hover {{
    background: alpha({color["text"]}, 0.09);
    border-color: alpha({color["text"]}, 0.22);
}}
window.study-window .workbench-stack {{
    border-radius: 10px;
}}
window.study-window.stack-layout .workbench-header {{
    padding-bottom: 4px;
    margin-bottom: 1px;
}}
window.study-window.stack-layout .workbench-header-primary {{
    min-height: 28px;
}}
window.study-window.stack-layout .workspace-tabs-scroll {{
    margin-top: 0;
}}
window.study-window.stack-layout .workspace-tabs button {{
    min-height: 28px;
    padding: 3px 9px;
}}
window.study-window.stack-layout .workbench-quick-actions {{
    padding-bottom: 1px;
    margin-bottom: 0;
}}
window.study-window.stack-layout .workbench-quick-actions button {{
    min-height: 28px;
    padding: 3px 9px;
}}
window.study-window.stack-layout .workbench-status {{
    padding: 4px 7px;
    margin-top: 0;
    margin-bottom: 1px;
}}
window.study-window.stack-layout .sidebar-toggle {{
    min-height: 28px;
    padding: 3px 9px;
}}
window.study-window .workbench-page {{
    background: transparent;
}}
window.study-window .workbench-page-card {{
    border-radius: 12px;
    border: 1px solid {border["soft"]};
    background: {surface["card"]};
}}
window.study-window .dashboard-workbench-page {{
    border-radius: 12px;
}}
window.study-window .dashboard-workbench-panel {{
    padding-right: 2px;
}}
window.study-window .dashboard-workbench-panel > .card {{
    border-radius: 13px;
    border: 1px solid alpha({color["text"]}, 0.11);
    background: linear-gradient(180deg, alpha({color["text"]}, 0.018), alpha({color["text"]}, 0.005));
    box-shadow: 0 1px 10px alpha({color["text"]}, 0.07);
}}
window.study-window .dashboard-workbench-panel > .hero-card {{
    border-color: alpha({color["accent"]}, 0.44);
    background-image: linear-gradient(
        to bottom,
        alpha({color["accent"]}, 0.060),
        alpha({color["bg"]}, 0.0)
    );
    box-shadow: 0 2px 14px alpha({color["accent"]}, 0.14),
                0 1px 4px alpha({color["text"]}, 0.08);
}}
window.study-window .dashboard-workbench-panel .section-title {{
    letter-spacing: 0.50px;
    font-weight: 760;
}}
window.study-window .coach-diagnostics-expander {{
    margin-top: 2px;
}}
window.study-window .coach-diagnostics-box {{
    border-top: 1px solid alpha({color["text"]}, 0.10);
    margin-top: 4px;
    padding-top: 4px;
}}
window.study-window .tutor-workbench {{
    padding-top: 6px;
}}
window.study-window .tutor-workbench .tutor-prompt-scroll,
window.study-window .tutor-workbench .tutor-response-scroll {{
    border-radius: 10px;
    border: 1px solid alpha({color["text"]}, 0.14);
    background: alpha({color["text"]}, 0.025);
}}
window.study-window .tutor-workbench .tutor-prompt-view {{
    font-size: 13px;
    line-height: 1.46;
}}
window.study-window .tutor-workbench .tutor-response-view {{
    font-size: 13px;
    line-height: 1.52;
}}
window.study-window .tutor-workbench .inline-toolbar {{
    border-bottom: 1px solid alpha({color["text"]}, 0.09);
    padding-bottom: 4px;
    margin-bottom: 4px;
}}
window.study-window .tutor-workbench .inline-toolbar button {{
    min-height: 32px;
    border-radius: 8px;
}}
window.study-window .tutor-workbench .single-line-lock {{
    border: 1px solid alpha({color["text"]}, 0.10);
    border-radius: 8px;
    background: alpha({color["text"]}, 0.03);
    padding: 4px 8px;
    font-size: 12px;
}}
window.study-window .workbench-status {{
    border: 1px solid alpha({color["text"]}, 0.10);
    border-radius: 8px;
    background: alpha({color["text"]}, 0.035);
    padding: 5px 8px;
    margin-top: 1px;
    margin-bottom: 2px;
    letter-spacing: 0.16px;
}}
window.study-window .workbench-heading {{
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.36px;
}}
window.study-window .workbench-text {{
    font-family: "Iosevka Aile", "JetBrains Mono NL", "Noto Sans Mono", monospace;
    font-size: 12px;
}}
window.study-window button.coach-action {{
    background-color: alpha({color["accent"]}, 0.14);
    background-image: linear-gradient(
        to bottom,
        alpha({color["accent"]}, 0.08),
        alpha({color["accent"]}, 0.0)
    );
    border: 1px solid alpha({color["accent"]}, 0.44);
}}
window.study-window button.coach-action:hover {{
    background-color: alpha({color["accent"]}, 0.22);
}}
window.study-window .study-room-actions button {{
    min-height: 34px;
}}
window.study-window button.suggested-action {{
    background-image: linear-gradient(
        to bottom,
        alpha({color["accent"]}, 1.0),
        alpha({color["accent"]}, 0.92)
    );
    box-shadow: 0 1px 0 alpha({color["text"]}, 0.18),
                0 3px 10px alpha({color["accent"]}, 0.38);
}}
window.study-window.compact .card {{
    padding: 8px;
}}
window.study-window.compact .section-title {{
    font-size: 11px;
}}

/* ── Hyprland / compositor-friendly glass surface ── */
window.study-window {{
    background: alpha({color["bg"]}, 0.82);
    -gtk-backdrop-filter: blur(6px);
}}
window.study-window .panel,
window.study-window .card {{
    -gtk-backdrop-filter: blur(12px);
}}

/* ── Thin rounded scrollbars ── */
window.study-window scrollbar {{
    -gtk-fixed-height: 8px;
    -gtk-fixed-width: 8px;
}}
window.study-window scrollbar slider {{
    min-height: 8px;
    min-width: 8px;
    border-radius: 4px;
    background: alpha({color["text"]}, 0.20);
    border: none;
    transition: background 150ms ease;
}}
window.study-window scrollbar slider:hover {{
    background: alpha({color["text"]}, 0.35);
}}
window.study-window scrollbar slider:active {{
    background: alpha({color["accent"]}, 0.50);
}}
window.study-window scrollbar trough {{
    background: transparent;
    border: none;
}}

/* ── Global buttons ── */
window.study-window button {{
    border-radius: 8px;
    min-height: 30px;
    padding: 4px 14px;
    transition: all 150ms ease;
    border: 1px solid alpha({color["text"]}, 0.12);
    background: alpha({color["text"]}, 0.04);
}}
window.study-window button:hover {{
    background: alpha({color["text"]}, 0.10);
    border-color: alpha({color["text"]}, 0.22);
}}
window.study-window button:active {{
    background: alpha({color["accent"]}, 0.16);
    border-color: alpha({color["accent"]}, 0.36);
}}
window.study-window button:checked {{
    background: linear-gradient(180deg, alpha({color["accent"]}, 0.24), alpha({color["accent"]}, 0.14));
    border-color: alpha({color["accent"]}, 0.52);
    color: {color["text"]};
}}
window.study-window button.suggested-action {{
    background: linear-gradient(180deg, alpha({color["accent"]}, 1.0), alpha({color["accent"]}, 0.92));
    border-color: alpha({color["accent"]}, 0.8);
    color: {color["bg"]};
    font-weight: 660;
    box-shadow: 0 1px 0 alpha({color["text"]}, 0.18),
                0 3px 10px alpha({color["accent"]}, 0.38);
}}
window.study-window button.suggested-action:hover {{
    box-shadow: 0 1px 0 alpha({color["text"]}, 0.22),
                0 5px 16px alpha({color["accent"]}, 0.46);
}}
window.study-window button.flat {{
    background: transparent;
    border-color: transparent;
}}
window.study-window button.flat:hover {{
    background: alpha({color["text"]}, 0.08);
    border-color: transparent;
}}

/* ── Entries (text fields) ── */
window.study-window entry {{
    border-radius: 8px;
    border: 1px solid alpha({color["text"]}, 0.14);
    background: alpha({color["text"]}, 0.03);
    min-height: 30px;
    padding: 4px 10px;
    caret-color: {color["accent"]};
    transition: border-color 150ms ease, box-shadow 150ms ease;
}}
window.study-window entry:focus {{
    border-color: alpha({color["accent"]}, 0.60);
    box-shadow: 0 0 0 2px alpha({color["accent"]}, 0.18);
    background: alpha({color["text"]}, 0.06);
}}
window.study-window entry:disabled {{
    opacity: 0.45;
}}

/* ── Combo boxes ── */
window.study-window combox {{
    border-radius: 8px;
    min-height: 30px;
}}
window.study-window combox button {{
    border-radius: 8px;
    min-height: 30px;
}}
window.study-window combox arrow {{
    -gtk-icon-size: 10px;
}}
window.study-window combox dropdown {{
    border-radius: 10px;
    border: 1px solid alpha({color["text"]}, 0.14);
    background: alpha({color["bg"]}, 0.96);
    -gtk-backdrop-filter: blur(12px);
    padding: 4px;
}}
window.study-window combox dropdown button {{
    border-radius: 6px;
    border: none;
    background: transparent;
    padding: 6px 10px;
    transition: background 100ms ease;
}}
window.study-window combox dropdown button:hover {{
    background: alpha({color["accent"]}, 0.14);
}}

/* ── Spin buttons ── */
window.study-window spinbutton {{
    border-radius: 8px;
    border: 1px solid alpha({color["text"]}, 0.14);
}}
window.study-window spinbutton button {{
    min-height: 24px;
    min-width: 24px;
    padding: 2px;
    border-radius: 6px;
}}

/* ── Check / Radio buttons ── */
window.study-window checkbutton, window.study-window radiobutton {{
    transition: all 120ms ease;
}}
window.study-window checkbutton check {{
    border-radius: 4px;
    min-width: 16px;
    min-height: 16px;
    border: 2px solid alpha({color["text"]}, 0.30);
    background: transparent;
    transition: all 120ms ease;
}}
window.study-window checkbutton check:checked {{
    background: {color["accent"]};
    border-color: {color["accent"]};
    -gtk-icon-source: -gtk-scaled(url("resource:///org/gtk/libgtk/icons/16x16/legacy/object-select-symbolic.symbolic.png"));
}}
window.study-window checkbutton check:hover {{
    border-color: alpha({color["accent"]}, 0.60);
}}
window.study-window radiobutton radio {{
    border-radius: 50%;
    min-width: 16px;
    min-height: 16px;
    border: 2px solid alpha({color["text"]}, 0.30);
    background: transparent;
    transition: all 120ms ease;
}}
window.study-window radiobutton radio:checked {{
    background: {color["accent"]};
    border-color: {color["accent"]};
    box-shadow: inset 0 0 0 3px alpha({color["bg"]}, 0.85);
}}
window.study-window radiobutton radio:hover {{
    border-color: alpha({color["accent"]}, 0.60);
}}

/* ── Selection highlight ── */
window.study-window selection {{
    background-color: alpha({color["accent"]}, 0.34);
    color: {color["text"]};
}}

/* ── Separators / rules ── */
window.study-window separator.rule {{
    margin-top: 4px;
    margin-bottom: 4px;
    background: alpha({color["text"]}, 0.08);
    min-height: 1px;
}}

/* ── Notifications / toasts ── */
window.study-window .toast,
window.study-window .banner-shell {{
    border-radius: 10px;
    background: alpha({color["bg"]}, 0.92);
    border: 1px solid alpha({color["text"]}, 0.12);
    -gtk-backdrop-filter: blur(14px);
    padding: 8px 14px;
    margin: 4px;
}}

/* ── Tooltips ── */
window.study-window tooltip {{
    border-radius: 8px;
    border: 1px solid alpha({color["text"]}, 0.12);
    background: alpha({color["bg"]}, 0.94);
    -gtk-backdrop-filter: blur(10px);
    padding: 6px 10px;
}}

/* ── ScrolledWindow ── */
window.study-window scrolledwindow {{
    border-radius: 8px;
}}
window.study-window scrolledwindow.frame {{
    border: 1px solid alpha({color["text"]}, 0.08);
    border-radius: 8px;
}}

/* ── Progress bar ── */
window.study-window progressbar {{
    border-radius: 4px;
    min-height: 6px;
}}
window.study-window progressbar trough {{
    border-radius: 4px;
    background: alpha({color["text"]}, 0.08);
    min-height: 6px;
}}
window.study-window progressbar progress {{
    border-radius: 4px;
    background: linear-gradient(90deg, alpha({color["accent"]}, 0.8), {color["accent"]});
    min-height: 6px;
}}

/* ── Level bar ── */
window.study-window levelbar {{
    border-radius: 4px;
}}
window.study-window levelbar trough {{
    border-radius: 4px;
    background: alpha({color["text"]}, 0.08);
}}
window.study-window levelbar block {{
    border-radius: 3px;
}}

/* ── Window handle / resize grip ── */
window.study-window .titlebar,
window.study-window windowhandle {{
    background: transparent;
    border: none;
}}

/* ── Nerd Font / icon font support ── */
window.study-window .nerd-font,
window.study-window .workbench-text {{
    font-family: "Iosevka Aile", "JetBrains Mono NL", "Noto Sans Mono", "Symbols Nerd Font Mono", monospace;
}}

/* ── About dialog ── */
window.aboutdialog {{
    background: {surface["card"]};
    border-radius: 14px;
}}
window.aboutdialog .dialog-vbox {{
    padding: 6px;
}}

/* ── Section titles with accent underline ── */
window.study-window .section-title {{
    padding-bottom: 2px;
}}
window.study-window .section-title::after {{
    content: "";
    display: block;
    width: 28px;
    height: 2px;
    background: alpha({color["accent"]}, 0.50);
    border-radius: 1px;
    margin-top: 3px;
}}

/* ── Card entrance subtle animation ── */
window.study-window .card {{
    transition: all 180ms ease-out, box-shadow 200ms ease, background 150ms ease;
}}

/* ── Enhanced badge pulse ── */
window.study-window .badge {{
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 660;
    letter-spacing: 0.2px;
    background: alpha({color["accent"]}, 0.14);
    border: 1px solid alpha({color["accent"]}, 0.30);
}}
window.study-window .badge.status-warn {{
    background: alpha(#f5a623, 0.15);
    border-color: alpha(#f5a623, 0.35);
    color: #f5a623;
}}

/* ── Coach card polish ── */
window.study-window .coach-card {{
    border-left: 3px solid alpha({color["accent"]}, 0.50);
}}

/* ── Metric / KPI lines ── */
window.study-window .kpi-line {{
    font-weight: 660;
    letter-spacing: 0.1px;
}}

/* ── Tooltip subtle enhancement ── */
window.study-window tooltip {{
    font-size: 12px;
    box-shadow: 0 2px 8px alpha({color["text"]}, 0.12);
}}

{motion_css}
"""


def _compose_theme_css(use_system: bool) -> str:
    base_css = SYSTEM_THEME_CSS if use_system else COACH_THEME_CSS
    base_text = (
        base_css.decode("utf-8", errors="replace") if isinstance(base_css, (bytes, bytearray)) else str(base_css)
    )
    if not bool(_THEME_RUNTIME_OPTIONS.get("modern_enabled", False)):
        return base_text
    return base_text + "\n" + _build_modern_overlay_css(use_system)


def apply_theme(use_system: bool) -> None:
    css_text = _compose_theme_css(bool(use_system))
    css_data = css_text.encode("utf-8", errors="replace")
    try:
        # Gtk4 prefers load_from_string(str). Decode bytes constants explicitly.
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(css_text)
        else:
            provider.load_from_data(css_data)
    except Exception:
        # Fallback path for bindings that may reject one API variant.
        try:
            provider.load_from_data(css_data)
        except Exception:
            return
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
