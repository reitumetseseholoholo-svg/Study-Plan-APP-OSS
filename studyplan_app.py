#!/usr/bin/env python3
import gi  # type: ignore[import-untyped]
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, GLib, Gdk, Gio  # type: ignore[reportAttributeAccessIssue,import-untyped]
from studyplan_engine import StudyPlanEngine


import datetime
import json
import os
import sys
import random
import csv
import subprocess
import shutil
import math
import time
import wave
import struct
from typing import Optional, Any

# Suppress known noisy GTK/GLib warnings without hiding real errors.
def _install_log_filters() -> None:
    noisy_substrings = (
        "Unknown key gtk-toolbar-style",
        "Unknown key gtk-toolbar-icon-size",
        "Unknown key gtk-button-images",
        "Unknown key gtk-menu-images",
        "Unknown key gtk-modules",
        "g_main_context_pop_thread_default: assertion 'stack != NULL' failed",
    )

    class _FilteredStderr:
        def __init__(self, stream):
            self._stream = stream
            self._buffer = ""

        def write(self, data):
            if not isinstance(data, str):
                try:
                    data = data.decode("utf-8", "ignore")
                except Exception:
                    data = str(data)
            self._buffer += data
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if any(needle in line for needle in noisy_substrings):
                    continue
                self._stream.write(line + "\n")

        def flush(self):
            if self._buffer:
                line = self._buffer
                self._buffer = ""
                if not any(needle in line for needle in noisy_substrings):
                    self._stream.write(line)
            try:
                self._stream.flush()
            except Exception:
                pass

        def isatty(self):
            return getattr(self._stream, "isatty", lambda: False)()

        def fileno(self):
            return getattr(self._stream, "fileno", lambda: -1)()

        @property
        def encoding(self):
            return getattr(self._stream, "encoding", "utf-8")

    def _handler(domain, level, message, _user_data):
        msg = message or ""
        for needle in noisy_substrings:
            if needle in msg:
                return
        try:
            sys.stderr.write(f"{domain}: {msg}\n" if domain else f"{msg}\n")
        except Exception:
            pass

    def _writer(log_level, fields, n_fields, _user_data):
        msg = ""
        try:
            if isinstance(fields, dict):
                msg = str(fields.get("MESSAGE", "") or "")
            else:
                for idx in range(int(n_fields or 0)):
                    field = fields[idx]
                    if getattr(field, "key", "") == "MESSAGE":
                        try:
                            msg = field.value.decode("utf-8", "ignore")
                        except Exception:
                            msg = str(field.value)
                        break
        except Exception:
            msg = ""
        for needle in noisy_substrings:
            if needle in msg:
                return GLib.LogWriterOutput.HANDLED
        return GLib.LogWriterOutput.UNHANDLED

    try:
        if hasattr(GLib, "log_set_writer_func"):
            GLib.log_set_writer_func(_writer, None)
        else:
            GLib.log_set_default_handler(_handler, None)
    except Exception:
        pass

    try:
        if not isinstance(sys.stderr, _FilteredStderr):
            sys.stderr = _FilteredStderr(sys.stderr)
    except Exception:
        pass

_install_log_filters()

SHORTCUTS_TEXT = (
    "Keyboard Shortcuts\n"
    "\n"
    "F1       Show shortcuts\n"
    "Ctrl+M   Toggle menu bar\n"
    "Ctrl+Q   Quit\n"
    "Ctrl+,   Preferences\n"
    "Ctrl+E   Set exam date\n"
    "\n"
    "F5       Start Pomodoro\n"
    "F6       Pause/Resume Pomodoro\n"
    "F7       Stop Pomodoro\n"
    "F8       Quick Quiz\n"
    "F9       Toggle Focus Mode\n"
)

APP_ID = "com.studyplan.assistant"
DEFAULT_MODULE_ID = os.environ.get("STUDYPLAN_MODULE_ID", "acca_f9")
DEFAULT_MODULE_TITLE = os.environ.get("STUDYPLAN_MODULE_TITLE", "ACCA F9")
MIN_POMODORO_CREDIT_MINUTES = 10
MAX_SHORT_POMODOROS_PER_DAY = 2
SHORT_POMODORO_XP = 2
FOCUS_IDLE_THRESHOLD_SECONDS = 120
HYPRIDLE_STATE_PATH = os.path.expanduser("~/.config/studyplan/hypridle_state")
POMODORO_ACTIVE_STATE_PATH = os.path.expanduser("~/.config/studyplan/pomodoro_active")
DEFAULT_SHORT_BREAK_MINUTES = 5
DEFAULT_LONG_BREAK_MINUTES = 15
DEFAULT_LONG_BREAK_EVERY = 4
DEFAULT_MAX_BREAK_SKIPS = 1

DEFAULT_FOCUS_ALLOWLIST = [
    "com.studyplan.assistant",
    "studyassistant",
    "studyplan",
    "studyplan_app",
    "studyplan_app.py",
    "firefox",
    "brave",
    "brave-browser",
    "Brave",
    "Brave-browser",
    "abiword",
    "gnumeric",
    "Abiword",
    "Gnumeric",
    "chromium",
    "google-chrome",
    "code",
    "code-oss",
    "cursor",
    "zed",
    "obsidian",
    "org.gnome.Evince",
    "evince",
    "zathura",
    "okular",
    "libreoffice",
    "soffice",
    "kitty",
    "alacritty",
    "foot",
    "wezterm",
    "gnome-terminal",
    "org.gnome.Terminal",
    "konsole",
]

ALL_BADGES = [
    ("pomodoro_first", "First Pomodoro", "Complete 1 Pomodoro"),
    ("pomodoro_4", "Focus Marathon", "4 Pomodoros in a day"),
    ("pomodoro_8", "Deep Work", "8 Pomodoros in a day"),
    ("quiz_first", "Quiz Starter", "Complete 1 quiz"),
    ("quiz_10", "Quiz Runner", "Complete 10 quizzes"),
    ("quiz_50", "Quiz Master", "Complete 50 quizzes"),
    ("quiz_perfect", "Perfect Quiz", "Score 100% in a quiz"),
    ("quiz_sharpshooter", "Quiz Sharpshooter", "Best streak 8+ in a quiz"),
    ("perfect_10", "Perfect 10", "10 correct answers in a row"),
    ("risk_manager", "Risk Manager", "Improve a weak chapter by +15% in 7 days"),
    ("daily_quests", "Daily Hero", "Complete all daily quests"),
    ("streak_3", "Streak Starter", "3-day streak"),
    ("streak_7", "One Week", "7-day streak"),
    ("streak_14", "Two Weeks", "14-day streak"),
    ("streak_30", "30-Day Streak", "30-day streak"),
]
try:
    import fitz  # type: ignore[import-untyped]  # PyMuPDF
    HAVE_FITZ = True
except Exception:
    fitz = None
    HAVE_FITZ = False

plt: Any | None = None
FigureCanvas: type[Any] | None = None
try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_gtk4agg import FigureCanvasGTK4Agg as _FigureCanvasGTK4Agg

    class _StudyPlanFigureCanvas(_FigureCanvasGTK4Agg):
        def _update_device_pixel_ratio(self, *args, **kwargs):
            native = self.get_native()
            if not native:
                return
            surface = native.get_surface()
            if not surface:
                return
            return super()._update_device_pixel_ratio(*args, **kwargs)

        # Allow zoom on Ctrl+scroll; otherwise let parent scroll.
        def scroll_event(self, controller, dx, dy):  # pyright: ignore[reportIncompatibleMethodOverride]
            try:
                mods = self._mpl_modifiers(controller)
            except Exception:
                mods = []
            if "ctrl" in mods:
                return super().scroll_event(controller, dx, dy)
            return False

    FigureCanvas = _StudyPlanFigureCanvas
except Exception:
    plt = None
    FigureCanvas = None
# from matplotlib.backends.backend_gtk4 import NavigationToolbar2GTK3 as NavigationToolbar

def configure_font_rendering() -> None:
    settings = Gtk.Settings.get_default()
    if not settings:
        return
    # Light hinting + antialiasing improves legibility on smaller displays.
    if hasattr(settings.props, "gtk_xft_antialias"):
        settings.props.gtk_xft_antialias = 1
    if hasattr(settings.props, "gtk_xft_hinting"):
        settings.props.gtk_xft_hinting = 1
    if hasattr(settings.props, "gtk_xft_hintstyle"):
        settings.props.gtk_xft_hintstyle = "hintslight"


class AppDialog(Gtk.Window):
    def __init__(self, title: str | None = None, transient_for=None, modal: bool = False):
        super().__init__(transient_for=transient_for)
        if title:
            self.set_title(title)
        self.set_modal(bool(modal))
        self._response_handlers: list[tuple] = []
        self._default_response = None

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._content_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._content_area.set_margin_top(12)
        self._content_area.set_margin_bottom(12)
        self._content_area.set_margin_start(12)
        self._content_area.set_margin_end(12)
        self._action_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._action_area.set_halign(Gtk.Align.END)
        main.append(self._content_area)
        main.append(self._action_area)
        self.set_child(main)

    def get_content_area(self):
        return self._content_area

    def add_button(self, label, response_id):
        if isinstance(label, str) and "_" in label:
            btn = Gtk.Button.new_with_mnemonic(label)
        else:
            btn = Gtk.Button(label=label)
        btn.connect("clicked", lambda _b, resp=response_id: self.response(resp))
        self._action_area.append(btn)
        if self._default_response == response_id:
            try:
                self.set_default_widget(btn)
            except Exception:
                pass
        return btn

    def add_buttons(self, *args):
        for i in range(0, len(args), 2):
            if i + 1 >= len(args):
                break
            self.add_button(args[i], args[i + 1])

    def set_default_response(self, response_id):
        self._default_response = response_id

    def response(self, response_id):
        for handler, user_data in list(self._response_handlers):
            try:
                if user_data:
                    handler(self, response_id, *user_data)
                else:
                    handler(self, response_id)
            except Exception:
                pass

    def connect(self, detailed_signal, handler, *user_data):
        if detailed_signal == "response":
            self._response_handlers.append((handler, user_data))
            return len(self._response_handlers)
        return super().connect(detailed_signal, handler, *user_data)


class AppMessageDialog:
    def __init__(
        self,
        text: str | None = None,
        transient_for=None,
        modal: bool = True,
        message_type=None,
        buttons=None,
        secondary_text: str | None = None,
        force_fallback: bool = False,
    ):
        self._parent = transient_for
        self._message = text or ""
        self._detail = secondary_text or ""
        self._buttons: list[tuple[str, int]] = []
        self._response_handlers: list[tuple] = []
        self._default_response = None
        self._cancel_response = None
        self._modal = bool(modal)
        self._use_alert = (not force_fallback) and hasattr(Gtk, "AlertDialog")
        self._dialog = None

        if not self._use_alert:
            # Fallback to custom window if AlertDialog is unavailable.
            self._dialog = AppDialog(transient_for=transient_for, modal=modal)
            content = self._dialog.get_content_area()
            label = Gtk.Label(label=self._message)
            label.set_wrap(True)
            label.set_halign(Gtk.Align.START)
            content.append(label)
            if self._detail:
                detail = Gtk.Label(label=self._detail)
                detail.set_wrap(True)
                detail.set_halign(Gtk.Align.START)
                detail.add_css_class("muted")
                content.append(detail)

        # Preload buttons if provided.
        if buttons is None:
            buttons = Gtk.ButtonsType.OK
        self._apply_buttons_type(buttons)

    def _apply_buttons_type(self, buttons) -> None:
        mapping = {
            Gtk.ButtonsType.NONE: [],
            Gtk.ButtonsType.OK: [("OK", Gtk.ResponseType.OK)],
            Gtk.ButtonsType.CLOSE: [("Close", Gtk.ResponseType.CLOSE)],
            Gtk.ButtonsType.CANCEL: [("Cancel", Gtk.ResponseType.CANCEL)],
            Gtk.ButtonsType.YES_NO: [("No", Gtk.ResponseType.NO), ("Yes", Gtk.ResponseType.YES)],
            Gtk.ButtonsType.OK_CANCEL: [("Cancel", Gtk.ResponseType.CANCEL), ("OK", Gtk.ResponseType.OK)],
        }
        for label, resp in mapping.get(buttons, []):
            self.add_button(label, resp)

    def add_button(self, label, response_id):
        self._buttons.append((label, response_id))
        if self._dialog is not None:
            self._dialog.add_button(label, response_id)
        return None

    def add_buttons(self, *args):
        for i in range(0, len(args), 2):
            if i + 1 >= len(args):
                break
            self.add_button(args[i], args[i + 1])

    def set_default_response(self, response_id):
        self._default_response = response_id

    def set_cancel_response(self, response_id):
        self._cancel_response = response_id

    def set_title(self, title: str) -> None:
        # GTK4 AlertDialog has no title; use heading when available.
        if self._dialog is not None:
            try:
                self._dialog.set_title(title)
            except Exception:
                pass
            return
        self._heading = title

    def connect(self, detailed_signal, handler, *user_data):
        if detailed_signal == "response":
            self._response_handlers.append((handler, user_data))
            if self._dialog is not None:
                self._dialog.connect("response", handler, *user_data)
            return len(self._response_handlers)
        if self._dialog is not None:
            return self._dialog.connect(detailed_signal, handler, *user_data)
        return 0

    def _emit_response(self, response_id):
        for handler, user_data in list(self._response_handlers):
            try:
                if user_data:
                    handler(self, response_id, *user_data)
                else:
                    handler(self, response_id)
            except Exception:
                pass

    def present(self):
        if self._dialog is not None:
            self._dialog.present()
            return
        dialog = Gtk.AlertDialog()
        try:
            dialog.set_message(self._message)
        except Exception:
            pass
        try:
            heading = getattr(self, "_heading", None)
            if heading:
                dialog.set_heading(heading)
        except Exception:
            pass
        if self._detail:
            try:
                dialog.set_detail(self._detail)
            except Exception:
                pass
        if not self._buttons:
            self._buttons = [("OK", Gtk.ResponseType.OK)]
        labels = [label for label, _ in self._buttons]
        try:
            dialog.set_buttons(labels)
        except Exception:
            pass
        if self._default_response is not None:
            try:
                idx = [resp for _, resp in self._buttons].index(self._default_response)
                dialog.set_default_button(idx)
            except Exception:
                pass
        if self._cancel_response is not None:
            try:
                idx = [resp for _, resp in self._buttons].index(self._cancel_response)
                dialog.set_cancel_button(idx)
            except Exception:
                pass

        def _on_choose(_dialog, res):
            idx = -1
            try:
                idx = _dialog.choose_finish(res)
            except Exception:
                idx = -1
            if 0 <= idx < len(self._buttons):
                response_id = self._buttons[idx][1]
            else:
                response_id = Gtk.ResponseType.CANCEL
            self._emit_response(response_id)

        try:
            dialog.choose(self._parent, None, _on_choose)
        except Exception:
            # Fallback to non-blocking show if choose isn't available.
            try:
                dialog.show(self._parent)
            except Exception:
                pass

    def destroy(self):
        if self._dialog is not None:
            try:
                self._dialog.destroy()
            except Exception:
                pass

SYSTEM_THEME_CSS = b"""
window {
    background: @theme_bg_color;
    color: @theme_fg_color;
}
.panel {
    background-color: alpha(@theme_bg_color, 0.8);
    border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 12px;
    padding: 12px;
    box-shadow: 0 1px 6px alpha(@theme_fg_color, 0.08);
}
.card {
    background-color: alpha(@theme_bg_color, 0.7);
    border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 12px;
    padding: 10px;
    box-shadow: 0 1px 4px alpha(@theme_fg_color, 0.06);
}
.title {
    font-weight: 700;
    font-size: 20px;
}
.action-timer {
    font-weight: 700;
    font-size: 18px;
    letter-spacing: 0.5px;
}
.section-title {
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: alpha(@theme_fg_color, 0.8);
    margin-top: 8px;
    margin-bottom: 6px;
}
.muted {
    color: alpha(@theme_fg_color, 0.7);
}
.hint {
    color: alpha(@theme_fg_color, 0.6);
    font-size: 11px;
    font-style: italic;
}
.plan-title {
    font-weight: 600;
}
.plan-meta {
    font-size: 11px;
}
.study-summary {
    font-size: 12px;
}
.rule {
    color: alpha(@theme_fg_color, 0.15);
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
.badge {
    background: alpha(@theme_fg_color, 0.06);
    border: 1px solid alpha(@theme_fg_color, 0.18);
    border-radius: 999px;
    padding: 2px 8px;
}
.badge-locked {
    background: alpha(@theme_fg_color, 0.03);
    border: 1px dashed alpha(@theme_fg_color, 0.18);
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
.coach-title {
    font-weight: 700;
}
.focus-list row {
    border: none;
    padding: 3px 2px;
}
.focus-list row:selected {
    background: transparent;
}
.quest-card {
    border: 1px solid alpha(@theme_fg_color, 0.12);
    border-radius: 12px;
    padding: 10px;
}
.xp-progress {
    min-height: 10px;
}
progressbar {
    min-height: 12px;
}
progressbar trough {
    border-radius: 999px;
    background-color: alpha(@theme_fg_color, 0.12);
}
progressbar progress {
    border-radius: 999px;
    background-color: @theme_selected_bg_color;
}
"""

COACH_THEME_CSS = b"""
window {
    background: #1e1f22;
    color: #e6e6e6;
    font-family: "Libertinus Serif", "Times New Roman", "Georgia", serif;
}
.panel {
    background: #2a2b2f;
    border: 1px solid #3a3c43;
    border-radius: 12px;
    padding: 12px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.35);
}
.card {
    background: #232428;
    border: 1px solid #3a3c43;
    border-radius: 12px;
    padding: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.35);
}
.title {
    font-weight: 700;
    font-size: 19px;
    color: #e6e6e6;
}
.action-timer {
    font-weight: 700;
    font-size: 18px;
    letter-spacing: 0.5px;
    color: #e6e6e6;
}
.section-title {
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: #c9cdd4;
    margin-top: 8px;
    margin-bottom: 6px;
}
.muted {
    color: #aab0bb;
}
.hint {
    color: #8f95a1;
    font-size: 11px;
    font-style: italic;
}
.plan-title {
    font-weight: 600;
}
.plan-meta {
    font-size: 11px;
}
.study-summary {
    font-size: 12px;
}
.rule {
    color: #3a3c43;
}
button {
    background: #2f3035;
    border: 1px solid #3f424a;
    border-radius: 8px;
    color: #e6e6e6;
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
.badge {
    background: #2f3035;
    border: 1px solid #3f424a;
    border-radius: 999px;
    padding: 2px 8px;
    color: #e6e6e6;
}
.badge-locked {
    background: #1f2126;
    border: 1px dashed #3f424a;
    border-radius: 999px;
    padding: 2px 8px;
    color: #7f8792;
}
.badge-highlight {
    box-shadow: 0 0 0 5px rgba(79, 209, 197, 0.65);
    transition: box-shadow 0.5s ease-out;
}
.status-ok {
    color: #4fd1c5;
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
.coach-title {
    font-weight: 700;
}
.focus-list row {
    border: none;
    padding: 3px 2px;
}
.focus-list row:selected {
    background: transparent;
}
.quest-card {
    background: #232428;
    border: 1px solid #3a3c43;
    border-radius: 12px;
    padding: 10px;
}
.xp-progress {
    min-height: 10px;
}
progressbar {
    min-height: 12px;
}
progressbar trough {
    border-radius: 999px;
    background-color: #2f3035;
}
progressbar progress {
    border-radius: 999px;
    background-color: #4fd1c5;
}
"""

provider = Gtk.CssProvider()

def apply_theme(use_system: bool) -> None:
    css = SYSTEM_THEME_CSS if use_system else COACH_THEME_CSS
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

apply_theme(True)


class StudyPlanGUI(Gtk.ApplicationWindow):
    def __init__(self, app, exam_date=None):
        super().__init__(application=app)
        configure_font_rendering()
        # Slightly smaller default size helps on 1280x1024 while staying roomy.
        self.set_default_size(960, 700)
        self.module_id = DEFAULT_MODULE_ID
        self.module_title = DEFAULT_MODULE_TITLE
        self.set_title(f"{self.module_title} Study Assistant")

        self.allow_lower_scores = False
        self.menu_bar_visible = True
        self.notifications_enabled = True
        self.xp_total = 0
        self.level = 1
        self.achievements = set()
        self.use_system_theme = True
        self.coach_only_view = False
        self.sticky_coach_pick = True
        self.last_coach_pick = None
        self.last_coach_pick_date = None
        self.onboarding_dismissed = False
        self.first_run_completed = False
        self._last_session_recap = None
        self._last_pomodoro_counted = False
        self.short_pomodoro_today_count = 0
        self.quiz_sessions_completed = 0
        self.pomodoro_today_count = 0
        self.last_pomodoro_date = None
        self.daily_pomodoros_by_chapter = {}
        self.daily_recall_by_chapter = {}
        self.recall_counts_for_release = True
        self.contract_log = []
        self.action_time_log = {}
        self.action_time_sessions = []
        self.session_quality_log = []
        self.micro_streak_recall = 0
        self.coach_reason_history = []
        self.last_break_adjust_note = None
        self._action_timer_kind = None
        self._action_timer_topic = None
        self._action_timer_started_at = None
        self._action_timer_elapsed = 0.0
        self._action_timer_id = None
        self._pomodoro_target_minutes = 25
        self._pomodoro_kind = "pomodoro_focus"
        self._recall_prompted_date = None
        self._recall_prompted_topic = None
        self.focus_integrity_log = []
        self.last_hindsight_week: str | None = None
        self._rescue_hits = 0
        self._rescue_prompted = False
        self._current_coach_pick_at_start = None
        self._last_momentum_date = None
        self.pomodoro_minutes_today_raw = 0.0
        self.pomodoro_minutes_today_verified = 0.0
        self.quiz_questions_today = 0
        self.quiz_sessions_today = 0
        self.last_quiz_date = None
        self.last_quest_date = None
        self.last_reflection_date = None
        self.last_hub_import_date = None
        self._last_daily_plan = []
        self._last_daily_plan_date = None
        self._plan_refresh_override = False
        self.last_weekly_review_date = None
        self.last_weekly_summary_week = None
        self.focus_tracking_enabled = True
        self.focus_allowlist = list(DEFAULT_FOCUS_ALLOWLIST)
        self._focus_tracking_available = bool(shutil.which("hyprctl"))
        self._focus_timer_id = None
        self._focus_active_seconds = 0
        self._focus_distract_seconds = 0
        self._last_focus_report = None
        self._last_focus_info = None
        self.focus_auto_pause_enabled = True
        self.focus_idle_threshold = FOCUS_IDLE_THRESHOLD_SECONDS
        self._focus_distraction_seconds = 0
        self._focus_recover_seconds = 0
        self._auto_paused = False
        self._focus_tracking_warning_shown = False
        self._last_idle_seconds = None
        self._last_idle_source = None
        self._hypridle_state_path = HYPRIDLE_STATE_PATH
        self._hypridle_supported = bool(shutil.which("hypridle"))
        self._pomodoro_active_state_path = POMODORO_ACTIVE_STATE_PATH
        self.break_remaining = 0
        self.break_timer_id = None
        self.on_break = False
        self.on_long_break = False
        self.short_break_minutes = DEFAULT_SHORT_BREAK_MINUTES
        self.long_break_minutes = DEFAULT_LONG_BREAK_MINUTES
        self.long_break_every = DEFAULT_LONG_BREAK_EVERY
        self.max_break_skips = DEFAULT_MAX_BREAK_SKIPS
        self.breaks_skipped_in_row = 0
        self.pomodoro_banner_enabled = True
        self.pomodoro_title_flash_enabled = True
        self.pomodoro_sound_enabled = True
        self._banner_hide_id = None
        self._title_flash_id = None
        self.last_coach_date = None
        self.weak_cleared_notified = set()
        self._closing_from_recap = False
        self._first_run_assistant = None
        self._first_run_auto = False
        self._force_message_dialog_fallback = False
        self._active_native_dialog = None
        self._dialog_smoke_mode = False
        self.risk_baselines = {}
        self.load_preferences()
        apply_theme(bool(self.use_system_theme))

        self.exam_date = exam_date
        self.last_study_date = None
        self.study_streak = 0   # Fixed typo: was study_steak
        self.load_streak_data()
        self.engine = StudyPlanEngine(
            self.exam_date,
            default_exam_date_to_today=False,
            module_id=self.module_id,
            module_title=self.module_title,
        )
        if self.exam_date is not None:
            self.engine.exam_date = self.exam_date
            try:
                self.engine.save_data()
            except Exception:
                pass
        else:
            if not os.path.exists(self.engine.DATA_FILE):
                self.engine.exam_date = None
        self.exam_date = self.engine.exam_date
        try:
            self.module_title = getattr(self.engine, "module_title", self.module_title)
            self.set_title(f"{self.module_title} Study Assistant")
        except Exception:
            pass

        # Days to exam label
        self.days_label = Gtk.Label()
        self.days_label.set_halign(Gtk.Align.START)
        self.days_label.add_css_class("title")

        self._create_actions()
        self.menu_bar = self._build_menu_bar()

        # Main layout
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        hbox.set_margin_top(16)
        hbox.set_margin_bottom(16)
        hbox.set_margin_start(16)
        hbox.set_margin_end(16)
        self.main_box = hbox

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(self.menu_bar)
        self.banner_revealer = Gtk.Revealer()
        self.banner_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.banner_revealer.set_reveal_child(False)
        banner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        banner_box.add_css_class("card")
        banner_box.add_css_class("banner")
        banner_box.set_margin_start(16)
        banner_box.set_margin_end(16)
        banner_box.set_margin_top(6)
        banner_box.set_margin_bottom(0)
        self.banner_label = Gtk.Label(label="Pomodoro complete.")
        self.banner_label.set_halign(Gtk.Align.START)
        self.banner_label.set_wrap(True)
        self.banner_action_btn = Gtk.Button(label="Skip break")
        self.banner_action_btn.connect("clicked", lambda _b: self._skip_break_action())
        dismiss_btn = Gtk.Button(label="Dismiss")
        dismiss_btn.connect("clicked", lambda _b: self._hide_pomodoro_banner())
        banner_box.append(self.banner_label)
        banner_box.append(self.banner_action_btn)
        banner_box.append(dismiss_btn)
        self.banner_revealer.set_child(banner_box)
        root.append(self.banner_revealer)
        root.append(hbox)
        self.root_box = root
        self.set_child(root)

        # Left panel
        left_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left_panel.set_halign(Gtk.Align.START)
        left_panel.set_size_request(340, -1)
        left_panel.add_css_class("panel")

        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left_scroll.set_hexpand(False)
        left_scroll.set_vexpand(True)
        left_scroll.set_propagate_natural_width(True)
        left_scroll.set_propagate_natural_height(False)
        left_scroll.set_child(left_panel)
        hbox.append(left_scroll)

        self.left_panel = left_panel
        self.left_scroll = left_scroll

        left_panel.append(self.days_label)

        # Exam date warning banner
        self.exam_warning_label = Gtk.Label(label="Set an exam date to unlock accurate planning.")
        self.exam_warning_label.set_halign(Gtk.Align.START)
        self.exam_warning_label.set_wrap(True)
        self.exam_warning_label.add_css_class("warning")
        left_panel.append(self.exam_warning_label)

        # Exam date picker button
        self.exam_date_btn = Gtk.Button(label="Set exam date…")
        self.exam_date_btn.connect("clicked", self.on_set_exam_date)
        left_panel.append(self.exam_date_btn)

        # Availability section (expander for compact mode)
        avail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.availability_warning_label = Gtk.Label(label="Set weekday/weekend minutes to personalize your plan.")
        self.availability_warning_label.set_halign(Gtk.Align.START)
        self.availability_warning_label.set_wrap(True)
        self.availability_warning_label.add_css_class("warning")
        avail_box.append(self.availability_warning_label)

        avail_grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        weekday_label = Gtk.Label(label="Weekday")
        weekday_label.set_halign(Gtk.Align.START)
        weekend_label = Gtk.Label(label="Weekend")
        weekend_label.set_halign(Gtk.Align.START)

        self.availability_weekday_spin = Gtk.SpinButton()
        self.availability_weekday_spin.set_adjustment(Gtk.Adjustment(lower=0, upper=600, step_increment=15, page_increment=30))
        self.availability_weekday_spin.set_digits(0)
        self.availability_weekday_spin.set_numeric(True)

        self.availability_weekend_spin = Gtk.SpinButton()
        self.availability_weekend_spin.set_adjustment(Gtk.Adjustment(lower=0, upper=600, step_increment=15, page_increment=30))
        self.availability_weekend_spin.set_digits(0)
        self.availability_weekend_spin.set_numeric(True)

        avail_grid.attach(weekday_label, 0, 0, 1, 1)
        avail_grid.attach(self.availability_weekday_spin, 1, 0, 1, 1)
        avail_grid.attach(weekend_label, 0, 1, 1, 1)
        avail_grid.attach(self.availability_weekend_spin, 1, 1, 1, 1)
        avail_box.append(avail_grid)

        self.availability_save_btn = Gtk.Button(label="Save Availability")
        self.availability_save_btn.connect("clicked", self.on_save_availability)
        avail_box.append(self.availability_save_btn)

        avail_label = Gtk.Label(label="Study Availability (minutes/day)")
        avail_label.set_halign(Gtk.Align.START)
        avail_label.add_css_class("section-title")
        self.availability_expander = Gtk.Expander()
        self.availability_expander.set_label_widget(avail_label)
        self.availability_expander.set_child(avail_box)
        self.availability_expander.set_expanded(True)
        left_panel.append(self.availability_expander)

        # Topic dropdown (GTK4 DropDown)
        chapters = []
        try:
            if isinstance(self.engine.CHAPTERS, list):
                chapters = [str(ch) for ch in self.engine.CHAPTERS if str(ch).strip()]
        except Exception:
            chapters = []
        self._chapters_available = bool(chapters)
        if not chapters:
            chapters = ["(No chapters loaded)"]
        self.topic_list = Gtk.StringList.new(chapters)
        self.topic_combo = Gtk.DropDown.new(self.topic_list, None)
        self.topic_combo.set_halign(Gtk.Align.FILL)
        self.topic_combo.set_hexpand(True)
        self.topic_combo.set_selected(0)
        if self._chapters_available:
            self.current_topic = chapters[0]
        else:
            self.current_topic = ""
            self.topic_combo.set_sensitive(False)
        self.topic_combo.connect("notify::selected", self.on_topic_changed)
        left_panel.append(self.topic_combo)
        if not self._chapters_available:
            note = Gtk.Label(
                label="No chapters loaded. Add a module JSON (Module → Manage Modules) to begin."
            )
            note.set_halign(Gtk.Align.START)
            note.set_wrap(True)
            note.add_css_class("warning")
            left_panel.append(note)

        # Coach pick summary
        coach_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        coach_card.add_css_class("card")
        coach_title = Gtk.Label(label="Coach Pick")
        coach_title.set_halign(Gtk.Align.START)
        coach_title.add_css_class("section-title")
        coach_card.append(coach_title)
        self.coach_pick_label = Gtk.Label(label="Coach pick: —")
        self.coach_pick_label.set_halign(Gtk.Align.START)
        self.coach_pick_label.set_wrap(True)
        self.coach_pick_label.add_css_class("muted")
        coach_btn = Gtk.Button()
        coach_btn.add_css_class("flat")
        coach_btn.set_child(self.coach_pick_label)
        coach_btn.connect("clicked", self.on_focus_coach_pick)
        coach_card.append(coach_btn)
        self.coach_pick_why_label = Gtk.Label(label="Why: —")
        self.coach_pick_why_label.set_halign(Gtk.Align.START)
        self.coach_pick_why_label.set_wrap(True)
        self.coach_pick_why_label.add_css_class("muted")
        self.coach_pick_why_label.set_visible(False)
        coach_card.append(self.coach_pick_why_label)
        self.coach_pick_why_history = Gtk.Label(label="Recent reasons:")
        self.coach_pick_why_history.set_halign(Gtk.Align.START)
        self.coach_pick_why_history.set_wrap(True)
        self.coach_pick_why_history.add_css_class("muted")
        self.coach_pick_why_history.set_visible(False)
        coach_card.append(self.coach_pick_why_history)
        self.coach_pick_why_btn = Gtk.Button(label="Why this topic?")
        self.coach_pick_why_btn.add_css_class("flat")
        self.coach_pick_why_btn.set_halign(Gtk.Align.START)
        def _toggle_why(_btn):
            now_visible = not self.coach_pick_why_label.get_visible()
            self.coach_pick_why_label.set_visible(now_visible)
            self.coach_pick_why_history.set_visible(now_visible)
        self.coach_pick_why_btn.connect("clicked", _toggle_why)
        coach_card.append(self.coach_pick_why_btn)
        self.verified_minutes_badge = Gtk.Label(label="Verified today: 0m")
        self.verified_minutes_badge.add_css_class("badge")
        self.verified_minutes_badge.set_halign(Gtk.Align.START)
        self.verified_minutes_badge.set_tooltip_text("Verified focus time in allowed apps today.")
        coach_card.append(self.verified_minutes_badge)
        left_panel.append(coach_card)

        # Daily Plan box
        self.plan_label = Gtk.Label(label="📚 Daily Focus Topics")
        self.plan_label.set_halign(Gtk.Align.START)
        self.plan_label.add_css_class("section-title")
        self.plan_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.plan_header_box.append(self.plan_label)
        self.plan_header_spacer = Gtk.Box()
        self.plan_header_spacer.set_hexpand(True)
        self.plan_header_box.append(self.plan_header_spacer)
        self.coach_only_toggle = Gtk.ToggleButton(label="Coach-only")
        self.coach_only_toggle.set_active(bool(self.coach_only_view))
        self.coach_only_toggle.connect("toggled", self.on_toggle_coach_only)
        self.coach_only_toggle.set_visible(not self.coach_only_view)
        self.coach_only_toggle.set_tooltip_text("Hide the daily plan list (coach-only view).")
        self.plan_header_box.append(self.coach_only_toggle)
        self.coach_only_badge = Gtk.Label(label="Coach-only")
        self.coach_only_badge.add_css_class("badge")
        self.coach_only_badge.set_visible(bool(self.coach_only_view))
        self.coach_only_badge.set_tooltip_text("Coach-only view is active; plan list hidden. Click to reset.")
        badge_gesture = Gtk.GestureClick()
        badge_gesture.connect("pressed", lambda *_: self._exit_coach_only_from_badge())
        self.coach_only_badge.add_controller(badge_gesture)
        self.plan_header_box.append(self.coach_only_badge)
        self.plan_hint = Gtk.Label(
            label="Coach-only view hides the daily plan. Click the badge to return."
        )
        self.plan_hint.set_halign(Gtk.Align.START)
        self.plan_hint.set_wrap(True)
        self.plan_hint.add_css_class("muted")
        self.plan_hint.set_margin_bottom(4)
        self.plan_hint.set_visible(bool(self.coach_only_view))
        plan_scroll = Gtk.ScrolledWindow()
        plan_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        plan_scroll.set_min_content_height(90)
        plan_scroll.add_css_class("card")
        self.plan_box = Gtk.ListBox()
        self.plan_box.set_selection_mode(Gtk.SelectionMode.NONE)
        if hasattr(self.plan_box, "set_show_separators"):
            self.plan_box.set_show_separators(False)
        self.plan_box.add_css_class("focus-list")
        plan_scroll.set_child(self.plan_box)
        self.plan_scroll = plan_scroll
        left_panel.append(self.plan_header_box)
        left_panel.append(self.plan_hint)
        self.plan_scroll.set_visible(not self.coach_only_view)
        left_panel.append(self.plan_scroll)
        self.update_daily_plan()
        self._update_coach_pick_card()

        # Top 5 recommendations box
        self.rec_label = Gtk.Label(label="⭐ Recommendations")
        self.rec_label.set_halign(Gtk.Align.START)
        self.rec_label.add_css_class("section-title")
        rec_scroll = Gtk.ScrolledWindow()
        rec_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        rec_scroll.set_min_content_height(120)
        rec_scroll.add_css_class("card")
        self.rec_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        rec_scroll.set_child(self.rec_box)
        self.rec_scroll = rec_scroll
        self.rec_expander = Gtk.Expander()
        self.rec_expander.set_label_widget(self.rec_label)
        self.rec_expander.set_child(rec_scroll)
        self.rec_expander.set_expanded(True)
        left_panel.append(self.rec_expander)

        # Study Room quick actions
        study_room_label = Gtk.Label(label="🧠 Study Room (Now)")
        study_room_label.set_halign(Gtk.Align.START)
        study_room_label.add_css_class("section-title")
        left_panel.append(study_room_label)

        study_room_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        study_room_card.add_css_class("card")
        self.study_room_summary = Gtk.Label()
        self.study_room_summary.set_halign(Gtk.Align.START)
        self.study_room_summary.set_wrap(True)
        self.study_room_summary.add_css_class("muted")
        self.study_room_summary.add_css_class("study-summary")
        self.study_room_details_label = Gtk.Label()
        self.study_room_details_label.set_halign(Gtk.Align.START)
        self.study_room_details_label.set_wrap(True)
        self.study_room_details_label.add_css_class("muted")
        self.study_room_details_label.add_css_class("study-summary")
        self.study_room_details_expander = Gtk.Expander()
        self.study_room_details_expander.set_label("Details")
        self.study_room_details_expander.set_expanded(False)
        self.study_room_details_expander.set_child(self.study_room_details_label)
        self.action_timer_label = Gtk.Label(label="Session: —")
        self.action_timer_label.set_halign(Gtk.Align.START)
        self.action_timer_label.add_css_class("action-timer")
        study_room_card.append(self.action_timer_label)
        study_room_card.append(self.study_room_summary)
        study_room_card.append(self.study_room_details_expander)

        self.study_room_next_due_label = Gtk.Label()
        self.study_room_next_due_label.set_halign(Gtk.Align.START)
        self.study_room_next_due_label.set_wrap(True)
        self.study_room_next_due_label.add_css_class("muted")
        study_room_card.append(self.study_room_next_due_label)

        self.study_room_mission_label = Gtk.Label()
        self.study_room_mission_label.set_halign(Gtk.Align.START)
        self.study_room_mission_label.set_wrap(True)
        self.study_room_mission_label.add_css_class("muted")
        study_room_card.append(self.study_room_mission_label)

        self.study_room_mission_bar = Gtk.ProgressBar()
        self.study_room_mission_bar.set_show_text(True)
        study_room_card.append(self.study_room_mission_bar)

        study_room_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        study_room_actions.set_homogeneous(True)
        self.study_room_focus_btn = Gtk.Button(label="Focus 25m")
        self.study_room_focus_btn.add_css_class("suggested-action")
        self.study_room_focus_btn.connect("clicked", self.on_focus_now)
        self.study_room_quiz_btn = Gtk.Button(label="Quiz")
        self.study_room_quiz_btn.connect("clicked", self.on_quick_quiz)
        self.study_room_drill_btn = Gtk.Button(label="Drill weak")
        self.study_room_drill_btn.connect("clicked", self.on_drill_weak)
        study_room_actions.append(self.study_room_focus_btn)
        study_room_actions.append(self.study_room_quiz_btn)
        study_room_actions.append(self.study_room_drill_btn)
        study_room_card.append(study_room_actions)
        left_panel.append(study_room_card)
        self.study_room_card = study_room_card
        self._badge_highlight_id = None

        # Pomodoro controls
        pomodoro_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.pomodoro_btn_start = Gtk.Button(label="Start pomodoro")
        self.pomodoro_btn_start.connect("clicked", self.on_pomodoro_start)
        pomodoro_hbox.append(self.pomodoro_btn_start)
        self.pomodoro_btn_pause = Gtk.Button(label="Pause")
        self.pomodoro_btn_pause.connect("clicked", self.on_pomodoro_pause)
        self.pomodoro_btn_pause.set_sensitive(False)
        pomodoro_hbox.append(self.pomodoro_btn_pause)
        self.pomodoro_btn_stop = Gtk.Button(label="Stop")
        self.pomodoro_btn_stop.connect("clicked", self.on_pomodoro_stop)
        self.pomodoro_btn_stop.set_sensitive(False)
        pomodoro_hbox.append(self.pomodoro_btn_stop)
        left_panel.append(pomodoro_hbox)

        # Pomodoro timer label
        self.pomodoro_timer_label = Gtk.Label(label="00:00")
        self.pomodoro_timer_label.set_halign(Gtk.Align.CENTER)
        self.pomodoro_timer_label.add_css_class("title")
        left_panel.append(self.pomodoro_timer_label)
        self.break_eta_label = Gtk.Label(label="")
        self.break_eta_label.set_halign(Gtk.Align.CENTER)
        self.break_eta_label.add_css_class("muted")
        left_panel.append(self.break_eta_label)

        self.focus_status_label = Gtk.Label()
        self.focus_status_label.set_halign(Gtk.Align.CENTER)
        self.focus_status_label.add_css_class("muted")
        self.focus_status_label.set_tooltip_text("Verified focus = time in allowed apps with recent activity.")
        left_panel.append(self.focus_status_label)

        self.pomodoro_remaining = 0
        self.pomodoro_timer_id = None
        self.pomodoro_paused = False

        # Take Quiz button
        self.quiz_btn = Gtk.Button(label="Take quiz")
        self.quiz_btn.connect("clicked", self.on_take_quiz)
        left_panel.append(self.quiz_btn)

        # Tools & data actions
        tools_label = Gtk.Label(label="🛠 Tools & Data")
        tools_label.set_halign(Gtk.Align.START)
        tools_label.add_css_class("section-title")
        left_panel.append(tools_label)
        tools_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tools_box.add_css_class("card")

        # Import PDF button
        self.import_btn = Gtk.Button(label="Import PDF scores")
        self.import_btn.connect("clicked", self.on_import_pdf)
        tools_box.append(self.import_btn)

        # Import AI Questions (JSON) button
        self.ai_questions_import_btn = Gtk.Button(label="Import AI questions (JSON)")
        self.ai_questions_import_btn.connect("clicked", self.on_import_ai_questions)
        tools_box.append(self.ai_questions_import_btn)

        # Export Data button
        self.export_btn = Gtk.Button(label="Export data (CSV)")
        self.export_btn.connect("clicked", self.on_export_data)
        tools_box.append(self.export_btn)

        # Export Import Template button
        self.template_btn = Gtk.Button(label="Export import template")
        self.template_btn.connect("clicked", self.on_export_template)
        tools_box.append(self.template_btn)

        # Reset Data button
        self.reset_btn = Gtk.Button(label="Reset Data")
        self.reset_btn.connect("clicked", self.on_reset_data)
        tools_box.append(self.reset_btn)

        # View Health Log button
        self.health_log_btn = Gtk.Button(label="View Health Log")
        self.health_log_btn.connect("clicked", self.on_view_health_log)
        tools_box.append(self.health_log_btn)

        left_panel.append(tools_box)
        self.tools_box = tools_box
        self.tools_label = tools_label

        # Streak label — created once here
        self.streak_label = Gtk.Label()
        self.update_streak_display()
        left_panel.append(self.streak_label)

        self.xp_label = Gtk.Label()
        self.update_xp_display()
        left_panel.append(self.xp_label)

        self.xp_progress = Gtk.ProgressBar()
        self.xp_progress.set_show_text(True)
        self.xp_progress.add_css_class("xp-progress")
        left_panel.append(self.xp_progress)

        self.xp_remaining_label = Gtk.Label()
        self.xp_remaining_label.set_halign(Gtk.Align.START)
        self.xp_remaining_label.add_css_class("muted")
        left_panel.append(self.xp_remaining_label)

        self.xp_multiplier_label = Gtk.Label()
        self.xp_multiplier_label.set_halign(Gtk.Align.START)
        self.xp_multiplier_label.add_css_class("muted")
        left_panel.append(self.xp_multiplier_label)

        quest_label = Gtk.Label(label="🎯 Daily Quests")
        quest_label.set_halign(Gtk.Align.START)
        quest_label.add_css_class("section-title")
        left_panel.append(quest_label)

        quest_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        quest_card.add_css_class("quest-card")
        self.quest_rows = {}
        for key, title, target in (
            ("pomodoro", "Pomodoros", 2),
            ("quiz_questions", "Quiz Questions", 10),
            ("quiz_sessions", "Quizzes Completed", 1),
        ):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            label = Gtk.Label(label=title)
            label.set_halign(Gtk.Align.START)
            progress = Gtk.ProgressBar()
            progress.set_show_text(True)
            row.append(label)
            row.append(progress)
            quest_card.append(row)
            self.quest_rows[key] = {"label": label, "progress": progress, "target": target}
        self.quest_reward_label = Gtk.Label(label="Complete all daily quests for +15 XP.")
        self.quest_reward_label.set_halign(Gtk.Align.START)
        self.quest_reward_label.add_css_class("muted")
        quest_card.append(self.quest_reward_label)
        left_panel.append(quest_card)
        self.quest_card = quest_card
        self.update_daily_quests_display()

        # Badges
        badge_label = Gtk.Label(label="🏅 Badges")
        badge_label.set_halign(Gtk.Align.START)
        badge_label.add_css_class("section-title")
        left_panel.append(badge_label)

        badge_scroll = Gtk.ScrolledWindow()
        badge_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        badge_scroll.set_min_content_height(70)
        badge_scroll.add_css_class("card")
        self.badge_flow = Gtk.FlowBox()
        self.badge_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.badge_flow.set_valign(Gtk.Align.START)
        self.badge_flow.set_max_children_per_line(3)
        badge_scroll.set_child(self.badge_flow)
        left_panel.append(badge_scroll)
        self.badge_scroll = badge_scroll
        self.update_badges_display()

        # Save status + backup warning
        self.last_saved_label = Gtk.Label()
        self.last_saved_label.set_halign(Gtk.Align.START)
        self.last_saved_label.set_wrap(True)
        self.last_saved_label.add_css_class("muted")
        left_panel.append(self.last_saved_label)

        self.backup_warning_label = Gtk.Label(label="Backup warning: last save could not create a .bak file.")
        self.backup_warning_label.set_halign(Gtk.Align.START)
        self.backup_warning_label.set_wrap(True)
        self.backup_warning_label.add_css_class("warning")
        left_panel.append(self.backup_warning_label)

        # Focus mode toggle
        self.focus_mode = False
        self.focus_mode_btn = Gtk.ToggleButton(label="Focus Mode")
        self.focus_mode_btn.connect("toggled", self.on_focus_mode_toggled)
        left_panel.append(self.focus_mode_btn)
        self._label_variants = {
            self.exam_date_btn: ("Set exam date…", "Exam Date"),
            self.availability_save_btn: ("Save Availability", "Save Avail"),
            self.study_room_focus_btn: ("Focus now (25m)", "Focus"),
            self.study_room_quiz_btn: ("Quick quiz", "Quiz"),
            self.study_room_drill_btn: ("Weak drill", "Drill"),
            self.pomodoro_btn_start: ("Start pomodoro", "Start"),
            self.pomodoro_btn_pause: ("Pause", "Pause"),
            self.pomodoro_btn_stop: ("Stop", "Stop"),
            self.quiz_btn: ("Take quiz", "Quiz"),
            self.import_btn: ("Import PDF scores", "Import PDF"),
            self.ai_questions_import_btn: ("Import AI questions (JSON)", "Import AI"),
            self.export_btn: ("Export data (CSV)", "Export CSV"),
            self.template_btn: ("Export import template", "Export Template"),
            self.reset_btn: ("Reset Data", "Reset"),
            self.health_log_btn: ("View Health Log", "Health Log"),
            self.focus_mode_btn: ("Focus Mode", "Focus"),
        }
        self._compact_mode = False

        # Right panel - dashboard
        dash_scroll = Gtk.ScrolledWindow()
        dash_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        dash_scroll.set_hexpand(True)
        dash_scroll.set_vexpand(True)
        dash_scroll.set_propagate_natural_height(False)
        dash_scroll.set_propagate_natural_width(False)
        dash_scroll.add_css_class("panel")
        self.dashboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.dashboard.set_halign(Gtk.Align.FILL)
        self.dashboard.set_valign(Gtk.Align.FILL)
        self.dashboard.set_hexpand(True)
        self.dashboard.set_vexpand(True)
        dash_scroll.set_child(self.dashboard)
        hbox.append(dash_scroll)
        self.dash_scroll = dash_scroll

        self.update_exam_date_display()
        self.update_availability_display()
        self.update_dashboard()
        self.update_recommendations()
        self.update_study_room_card()
        GLib.idle_add(self._maybe_show_first_run)

        # Autosave on close
        self.connect("close-request", self.on_close_request)
        self._last_window_size = (0, 0)
        GLib.timeout_add(300, self._poll_window_size)
        shortcut_controller = Gtk.ShortcutController()
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<Control>m"),
                Gtk.CallbackAction.new(self.on_toggle_menu_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<Control>q"),
                Gtk.CallbackAction.new(self.on_quit_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("F1"),
                Gtk.CallbackAction.new(self.on_show_shortcuts_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("F5"),
                Gtk.CallbackAction.new(self.on_pomodoro_start_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("F6"),
                Gtk.CallbackAction.new(self.on_pomodoro_pause_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("F7"),
                Gtk.CallbackAction.new(self.on_pomodoro_stop_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("F8"),
                Gtk.CallbackAction.new(self.on_quick_quiz_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("F9"),
                Gtk.CallbackAction.new(self.on_focus_mode_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<Control>e"),
                Gtk.CallbackAction.new(self.on_set_exam_date_shortcut),
            )
        )
        shortcut_controller.add_shortcut(
            Gtk.Shortcut.new(
                Gtk.ShortcutTrigger.parse_string("<Control>comma"),
                Gtk.CallbackAction.new(self.on_open_preferences_shortcut),
            )
        )
        self.add_controller(shortcut_controller)

    def _create_actions(self) -> None:
        self._add_action("import_pdf", self.on_menu_import_pdf)
        self._add_action("import_ai", self.on_menu_import_ai)
        self._add_action("export_csv", self.on_menu_export_csv)
        self._add_action("export_template", self.on_menu_export_template)
        self._add_action("weekly_report", self.on_view_weekly_report)
        self._add_action("reset_data", self.on_menu_reset_data)
        self._add_action("preferences", self.on_open_preferences)
        self._add_action("debug_info", self.on_debug_info)
        self._add_action("view_logs", self.on_view_logs)
        self._add_action("view_reflections", self.on_view_reflections)
        self._add_action("toggle_menu", self.on_toggle_menu_action)
        self._add_action("edit_focus_allowlist", self.on_edit_focus_allowlist)
        self._add_action("set_confidence_note", self.on_set_confidence_note)
        self._add_action("competence_table", self.on_show_competence_table)
        self._add_action("reset_competence", self.on_reset_chapter_competence)
        self._add_action("reset_all_competence", self.on_reset_all_competence)
        self._add_action("about", self.on_about)
        self._add_action("quit_app", self.on_quit_app)
        self._add_action("shortcuts", self.on_show_shortcuts)
        self._add_action("switch_module", self.on_switch_module)
        self._add_action("first_run_tour", self.on_first_run_tour)
        self._add_action("manage_modules", self.on_manage_modules)
        self._add_action("edit_module", self.on_edit_module)

    def _add_action(self, name: str, handler) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", handler)
        self.add_action(action)

    def _build_menu_bar(self) -> Gtk.Widget:
        file_menu = Gio.Menu()
        file_menu.append("Import PDF scores…", "win.import_pdf")
        file_menu.append("Import AI questions…", "win.import_ai")
        file_menu.append("Export data (CSV)…", "win.export_csv")
        file_menu.append("Export import template…", "win.export_template")
        file_menu.append("Weekly Report…", "win.weekly_report")
        file_menu.append("Reset Data…", "win.reset_data")
        file_menu.append("Quit", "win.quit_app")

        edit_menu = Gio.Menu()
        edit_menu.append("Focus Allowlist…", "win.edit_focus_allowlist")
        edit_menu.append("Set Confidence Note…", "win.set_confidence_note")
        edit_menu.append("Competence Table…", "win.competence_table")
        edit_menu.append("Reset Chapter Competence…", "win.reset_competence")
        edit_menu.append("Reset All Competence…", "win.reset_all_competence")

        module_menu = Gio.Menu()
        module_menu.append("Switch Module…", "win.switch_module")
        module_menu.append("Manage Modules…", "win.manage_modules")
        module_menu.append("Edit Module…", "win.edit_module")

        app_menu = Gio.Menu()
        app_menu.append("Preferences…", "win.preferences")
        app_menu.append("Debug Info…", "win.debug_info")
        app_menu.append("View Logs…", "win.view_logs")
        app_menu.append("Review Reflections…", "win.view_reflections")
        app_menu.append("Toggle Menu Bar", "win.toggle_menu")

        help_menu = Gio.Menu()
        help_menu.append("Keyboard Shortcuts…", "win.shortcuts")
        help_menu.append("First-Run Tour…", "win.first_run_tour")
        help_menu.append("About…", "win.about")

        top_menu = Gio.Menu()
        top_menu.append_submenu("File", file_menu)
        top_menu.append_submenu("Edit", edit_menu)
        top_menu.append_submenu("Module", module_menu)
        top_menu.append_submenu("Application", app_menu)
        top_menu.append_submenu("Help", help_menu)

        if hasattr(Gtk, "PopoverMenuBar"):
            menubar = Gtk.PopoverMenuBar.new_from_model(top_menu)
        else:
            menubar = Gtk.MenuBar.new_from_model(top_menu)
        menubar.set_visible(self.menu_bar_visible)
        return menubar

    def on_toggle_menu_shortcut(self, *_args):
        self.toggle_menu_bar()
        return True

    def on_toggle_menu_action(self, _action, _param):
        self.toggle_menu_bar()

    def toggle_menu_bar(self) -> None:
        self.menu_bar_visible = not self.menu_bar_visible
        self.menu_bar.set_visible(self.menu_bar_visible)
        self.save_preferences()

    def on_menu_import_pdf(self, _action, _param):
        self.on_import_pdf(None)

    def on_menu_import_ai(self, _action, _param):
        self.on_import_ai_questions(None)

    def on_menu_export_csv(self, _action, _param):
        self.on_export_data(None)

    def on_menu_export_template(self, _action, _param):
        self.on_export_template(None)

    def on_view_weekly_report(self, _action, _param):
        report_path = os.path.expanduser("~/.config/studyplan/weekly_report.txt")
        if not os.path.exists(report_path):
            self._show_text_dialog("Weekly Report", "No weekly report found yet.", Gtk.MessageType.INFO)
            return
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            self._show_text_dialog("Weekly Report", f"Failed to read report: {e}", Gtk.MessageType.ERROR)
            return
        self._show_scrolling_text("Weekly Report", content if content else "(report is empty)")

    def on_menu_reset_data(self, _action, _param):
        self.on_reset_data(None)

    def on_switch_module(self, _action, _param):
        dialog = self._new_dialog(title="Switch Module", transient_for=self, modal=True)
        dialog.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_Apply", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(8)

        note = Gtk.Label(
            label="Switching modules requires restarting the app to load new data."
        )
        note.set_halign(Gtk.Align.START)
        note.set_wrap(True)
        note.add_css_class("muted")
        content.append(note)

        modules = self._get_available_modules()
        labels = [f"{mod['title']} ({mod['id']})" for mod in modules]
        combo = Gtk.DropDown.new(Gtk.StringList.new(labels), None)
        combo._module_ids = [mod["id"] for mod in modules]
        if self.module_id and self.module_id in combo._module_ids:
            combo.set_selected(combo._module_ids.index(self.module_id))
        elif modules:
            combo.set_selected(0)

        combo_label = Gtk.Label(label="Available modules")
        combo_label.set_halign(Gtk.Align.START)
        content.append(combo_label)
        content.append(combo)

        id_label = Gtk.Label(label="Module ID")
        id_label.set_halign(Gtk.Align.START)
        id_entry = Gtk.Entry()
        id_entry.set_text(self.module_id)
        title_label = Gtk.Label(label="Module Title")
        title_label.set_halign(Gtk.Align.START)
        title_entry = Gtk.Entry()
        title_entry.set_text(self.module_title)

        content.append(id_label)
        content.append(id_entry)
        content.append(title_label)
        content.append(title_entry)

        def _on_combo_changed(_combo, _pspec=None):
            idx = combo.get_selected()
            if idx is None or idx < 0:
                return
            mid = combo._module_ids[idx] if idx < len(combo._module_ids) else None
            if not mid:
                return
            match = next((m for m in modules if m["id"] == mid), None)
            if not match:
                return
            id_entry.set_text(match["id"])
            title_entry.set_text(match["title"])

        combo.connect("notify::selected", _on_combo_changed)

        def _on_response(_d, response):
            if response == Gtk.ResponseType.OK:
                new_id = id_entry.get_text().strip()
                new_title = title_entry.get_text().strip() or new_id
                if new_id:
                    self.module_id = new_id
                    self.module_title = new_title
                    self.save_preferences()
                dialog.destroy()
                msg = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.NONE,
                    text="Restart required to apply the new module.",
                )
                msg.add_buttons("_Restart Later", Gtk.ResponseType.CLOSE, "_Restart Now", Gtk.ResponseType.OK)
                def _on_msg_close(_m, resp):
                    _m.destroy()
                    if resp == Gtk.ResponseType.OK:
                        self._restart_app()
                msg.connect("response", _on_msg_close)
                msg.present()
                return
            dialog.destroy()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_first_run_tour(self, _action, _param):
        self._first_run_auto = _action is None
        if self._first_run_assistant is not None:
            try:
                if self._first_run_assistant.get_visible():
                    self._first_run_assistant.present()
                    return
            except Exception:
                pass
            try:
                self._first_run_assistant.destroy()
            except Exception:
                pass
            self._first_run_assistant = None
        self._first_run_assistant = self._build_first_run_assistant()
        self._first_run_assistant.present()

    def on_manage_modules(self, _action, _param):
        dialog = self._new_dialog(title="Manage Modules", transient_for=self, modal=True)
        dialog.add_buttons("_Close", Gtk.ResponseType.CLOSE)
        content = dialog.get_content_area()
        content.set_spacing(8)

        note = Gtk.Label(
            label=(
                "Modules are JSON files defining chapters, weights, and optional questions.\n"
                "You can add or edit module configs in the folders below."
            )
        )
        note.set_halign(Gtk.Align.START)
        note.set_wrap(True)
        note.add_css_class("muted")
        content.append(note)

        folders = []
        try:
            folders.append(getattr(self.engine, "MODULES_DIR", ""))
        except Exception:
            pass
        folders.append(os.path.join(os.path.dirname(__file__), "modules"))
        folders = [f for f in folders if f]

        for folder in folders:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            label = Gtk.Label(label=folder)
            label.set_halign(Gtk.Align.START)
            label.add_css_class("muted")
            row.append(label)
            open_btn = Gtk.Button(label="Open Folder")
            def _open(_btn, path=folder):
                if not path:
                    return
                try:
                    subprocess.Popen(["xdg-open", path])
                except Exception:
                    pass
            open_btn.connect("clicked", _open)
            row.append(open_btn)
            content.append(row)

        modules = self._get_available_modules()
        rows = []
        for mod in modules:
            rows.append((mod["title"], mod["id"], mod.get("source", "")))
        table = self._build_import_table("Installed Modules", ["Title", "ID", "Source"], rows, min_height=140)
        content.append(table)

        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def on_edit_module(self, _action, _param):
        dialog = self._new_dialog(title="Module Editor", transient_for=self, modal=True)
        dialog.add_buttons("_Close", Gtk.ResponseType.CLOSE, "_Save", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(8)

        modules = self._get_available_modules()
        labels = [f"{mod['title']} ({mod['id']})" for mod in modules]
        combo = Gtk.DropDown.new(Gtk.StringList.new(labels), None)
        combo._module_ids = [mod["id"] for mod in modules]
        if self.module_id and self.module_id in combo._module_ids:
            combo.set_selected(combo._module_ids.index(self.module_id))
        elif modules:
            combo.set_selected(0)

        combo_label = Gtk.Label(label="Load module")
        combo_label.set_halign(Gtk.Align.START)
        content.append(combo_label)
        content.append(combo)

        id_label = Gtk.Label(label="Module ID (filename)")
        id_label.set_halign(Gtk.Align.START)
        id_entry = Gtk.Entry()
        id_entry.set_text(self.module_id)
        title_label = Gtk.Label(label="Module Title")
        title_label.set_halign(Gtk.Align.START)
        title_entry = Gtk.Entry()
        title_entry.set_text(self.module_title)

        content.append(id_label)
        content.append(id_entry)
        content.append(title_label)
        content.append(title_entry)

        chapters_label = Gtk.Label(label="Chapters (one per line)")
        chapters_label.set_halign(Gtk.Align.START)
        chapters_view = Gtk.TextView()
        chapters_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        chapters_scroll = Gtk.ScrolledWindow()
        chapters_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        chapters_scroll.set_min_content_height(140)
        chapters_scroll.add_css_class("card")
        chapters_scroll.set_child(chapters_view)
        content.append(chapters_label)
        content.append(chapters_scroll)

        weights_label = Gtk.Label(label="Importance weights (Chapter = weight)")
        weights_label.set_halign(Gtk.Align.START)
        weights_view = Gtk.TextView()
        weights_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        weights_scroll = Gtk.ScrolledWindow()
        weights_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        weights_scroll.set_min_content_height(100)
        weights_scroll.add_css_class("card")
        weights_scroll.set_child(weights_view)
        content.append(weights_label)
        content.append(weights_scroll)

        flow_label = Gtk.Label(label="Chapter flow (Chapter -> Next1, Next2)")
        flow_label.set_halign(Gtk.Align.START)
        flow_view = Gtk.TextView()
        flow_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        flow_scroll = Gtk.ScrolledWindow()
        flow_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        flow_scroll.set_min_content_height(100)
        flow_scroll.add_css_class("card")
        flow_scroll.set_child(flow_view)
        content.append(flow_label)
        content.append(flow_scroll)

        json_label = Gtk.Label(label="Raw JSON (optional)")
        json_label.set_halign(Gtk.Align.START)
        json_view = Gtk.TextView()
        json_view.set_wrap_mode(Gtk.WrapMode.NONE)
        json_scroll = Gtk.ScrolledWindow()
        json_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        json_scroll.set_min_content_height(180)
        json_scroll.add_css_class("card")
        json_scroll.set_child(json_view)
        content.append(json_label)
        content.append(json_scroll)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        to_json_btn = Gtk.Button(label="Update JSON from Form")
        from_json_btn = Gtk.Button(label="Update Form from JSON")
        open_folder_btn = Gtk.Button(label="Open Modules Folder")
        btn_row.append(to_json_btn)
        btn_row.append(from_json_btn)
        btn_row.append(open_folder_btn)
        content.append(btn_row)

        def _get_text(view: Gtk.TextView) -> str:
            buf = view.get_buffer()
            return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

        def _set_text(view: Gtk.TextView, text: str) -> None:
            view.get_buffer().set_text(text or "")

        def _load_config_for(mid: str) -> dict:
            try:
                config = self.engine._load_module_config(mid)
                return config if isinstance(config, dict) else {}
            except Exception:
                return {}

        def _populate_from_config(config: dict) -> None:
            _set_text(chapters_view, "")
            _set_text(weights_view, "")
            _set_text(flow_view, "")
            chapters = config.get("chapters") if isinstance(config, dict) else None
            if isinstance(chapters, list):
                _set_text(chapters_view, "\n".join(str(ch) for ch in chapters))
            weights = config.get("importance_weights") if isinstance(config, dict) else None
            if isinstance(weights, dict):
                lines = [f"{k} = {v}" for k, v in weights.items()]
                _set_text(weights_view, "\n".join(lines))
            flow = config.get("chapter_flow") if isinstance(config, dict) else None
            if isinstance(flow, dict):
                lines = []
                for k, v in flow.items():
                    if isinstance(v, list):
                        lines.append(f"{k} -> {', '.join(str(x) for x in v)}")
                _set_text(flow_view, "\n".join(lines))
            if isinstance(config, dict):
                _set_text(json_view, json.dumps(config, indent=2, ensure_ascii=True))

        def _build_config_from_form() -> dict:
            config = {}
            title = title_entry.get_text().strip()
            if title:
                config["title"] = title
            chapters = [line.strip() for line in _get_text(chapters_view).splitlines() if line.strip()]
            if chapters:
                config["chapters"] = chapters
            weights = {}
            for line in _get_text(weights_view).splitlines():
                if "=" in line:
                    left, right = line.split("=", 1)
                elif ":" in line:
                    left, right = line.split(":", 1)
                else:
                    continue
                key = left.strip()
                if not key:
                    continue
                try:
                    weights[key] = int(float(right.strip()))
                except Exception:
                    continue
            if weights:
                config["importance_weights"] = weights
            flow = {}
            for line in _get_text(flow_view).splitlines():
                if "->" not in line:
                    continue
                left, right = line.split("->", 1)
                key = left.strip()
                if not key:
                    continue
                targets = [t.strip() for t in right.split(",") if t.strip()]
                if targets:
                    flow[key] = targets
            if flow:
                config["chapter_flow"] = flow
            # Preserve questions if present in JSON
            try:
                existing = json.loads(_get_text(json_view))
                if isinstance(existing, dict) and existing.get("questions"):
                    config["questions"] = existing.get("questions")
            except Exception:
                pass
            return config

        def _from_json(_btn):
            try:
                data = json.loads(_get_text(json_view))
                if not isinstance(data, dict):
                    raise ValueError("JSON root must be an object")
            except Exception as exc:
                self.send_notification("Module Editor", f"Invalid JSON: {exc}")
                return
            title_entry.set_text(str(data.get("title", "") or ""))
            _populate_from_config(data)

        def _to_json(_btn):
            config = _build_config_from_form()
            _set_text(json_view, json.dumps(config, indent=2, ensure_ascii=True))

        def _open_folder(_btn):
            folder = getattr(self.engine, "MODULES_DIR", "")
            if not folder:
                return
            try:
                os.makedirs(folder, exist_ok=True)
                subprocess.Popen(["xdg-open", folder])
            except Exception:
                pass

        def _on_combo_changed(_combo, _pspec=None):
            idx = combo.get_selected()
            if idx is None or idx < 0:
                return
            mid = combo._module_ids[idx] if idx < len(combo._module_ids) else None
            if not mid:
                return
            id_entry.set_text(mid)
            config = _load_config_for(mid)
            title_entry.set_text(str(config.get("title", "") or mid))
            _populate_from_config(config)

        combo.connect("notify::selected", _on_combo_changed)
        to_json_btn.connect("clicked", _to_json)
        from_json_btn.connect("clicked", _from_json)
        open_folder_btn.connect("clicked", _open_folder)

        if combo.get_selected() is not None and combo.get_selected() >= 0:
            _on_combo_changed(combo)
        else:
            _to_json(None)

        def _on_response(_d, response):
            if response == Gtk.ResponseType.OK:
                module_id = id_entry.get_text().strip()
                if not module_id:
                    self.send_notification("Module Editor", "Module ID is required.")
                    return
                try:
                    config = json.loads(_get_text(json_view))
                    if not isinstance(config, dict):
                        raise ValueError("JSON root must be an object")
                except Exception as exc:
                    self.send_notification("Module Editor", f"Invalid JSON: {exc}")
                    return
                folder = getattr(self.engine, "MODULES_DIR", "")
                if not folder:
                    folder = os.path.join(os.path.expanduser("~/.config/studyplan"), "modules")
                try:
                    os.makedirs(folder, exist_ok=True)
                    path = os.path.join(folder, f"{module_id}.json")
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(config, f, ensure_ascii=True, indent=2)
                except Exception as exc:
                    self.send_notification("Module Editor", f"Save failed: {exc}")
                    return
                self.send_notification("Module Editor", f"Saved {module_id}.json")
            dialog.destroy()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_quit_shortcut(self, *_args):
        self.close()
        return True

    def on_quit_app(self, _action, _param):
        self.close()

    def on_show_shortcuts_shortcut(self, *_args):
        self.on_show_shortcuts(None, None)
        return True

    def on_pomodoro_start_shortcut(self, *_args):
        if self.pomodoro_remaining > 0:
            if self.pomodoro_paused:
                self.on_pomodoro_start(self.pomodoro_btn_start)
            return
        if self.pomodoro_btn_start.get_sensitive():
            self.on_pomodoro_start(self.pomodoro_btn_start)
        return True

    def on_pomodoro_pause_shortcut(self, *_args):
        if self.pomodoro_remaining > 0:
            self.on_pomodoro_pause(self.pomodoro_btn_pause)
        return True

    def on_pomodoro_stop_shortcut(self, *_args):
        if self.pomodoro_remaining > 0:
            self.on_pomodoro_stop(self.pomodoro_btn_stop)
        return True

    def on_quick_quiz_shortcut(self, *_args):
        self.on_quick_quiz(None)
        return True

    def on_focus_mode_shortcut(self, *_args):
        if getattr(self, "focus_mode_btn", None):
            try:
                self.focus_mode_btn.set_active(not self.focus_mode_btn.get_active())
            except Exception:
                pass
        return True

    def on_set_exam_date_shortcut(self, *_args):
        self.on_set_exam_date(self.exam_date_btn)
        return True

    def on_open_preferences_shortcut(self, *_args):
        self.on_open_preferences(None, None)
        return True

    def _restart_app(self) -> None:
        try:
            cmd = [sys.executable, os.path.abspath(__file__)]
            os.execv(sys.executable, cmd)
        except Exception:
            self.close()

    def on_about(self, _action, _param):
        about = self._new_about_dialog(transient_for=self, modal=True)
        about.set_program_name(f"{self.module_title} Study Assistant")
        about.set_version(getattr(StudyPlanEngine, "VERSION", "1.0.0"))
        about.set_comments(
            "A focused ACCA study coach with mission-driven Pomodoros, spaced repetition, "
            "and performance analytics."
        )
        about.set_authors(
            [
                "ACCA Study Coach (Lereko Ernest Seholoholo)",
                "Coach + UX enhancements: OpenAI Codex (assistant)",
            ]
        )
        about.present()

    def on_show_shortcuts(self, _action, _param):
        self._show_shortcuts_text_fallback()
        return

    def _show_shortcuts_text_fallback(self) -> None:
        dialog = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=SHORTCUTS_TEXT,
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _build_first_run_assistant(self) -> Gtk.Window:
        dialog = self._harden_window(Gtk.Window(transient_for=self))
        dialog.set_title("Welcome Tour")
        dialog.set_modal(True)
        dialog.set_default_size(620, 520)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        dialog.set_child(content)
        content.set_spacing(12)

        header = Gtk.Label()
        header.set_halign(Gtk.Align.START)
        header.add_css_class("section-title")
        content.append(header)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        stack.set_transition_duration(180)
        stack.set_vexpand(True)
        content.append(stack)

        page_titles = {}

        def _add_page(name: str, title: str, widget: Gtk.Widget) -> None:
            page_titles[name] = title
            stack.add_named(widget, name)

        # Page 1: Welcome
        welcome = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        welcome.add_css_class("card")
        welcome_label = Gtk.Label(
            label=(
                f"Welcome to {self.module_title} Study Assistant.\n"
                "We’ll set your essentials in 3 quick steps."
            )
        )
        welcome_label.set_halign(Gtk.Align.START)
        welcome_label.set_wrap(True)
        welcome.append(welcome_label)
        _add_page("welcome", "Welcome", welcome)

        # Page 2: Module selection
        module_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        module_page.add_css_class("card")
        module_label = Gtk.Label(label="Choose your ACCA module")
        module_label.set_halign(Gtk.Align.START)
        module_label.add_css_class("section-title")
        module_page.append(module_label)

        modules = self._get_available_modules()
        module_labels = [f"{mod['title']} ({mod['id']})" for mod in modules]
        module_combo = Gtk.DropDown.new(Gtk.StringList.new(module_labels), None)
        module_combo._module_ids = [mod["id"] for mod in modules]
        if self.module_id and self.module_id in module_combo._module_ids:
            module_combo.set_selected(module_combo._module_ids.index(self.module_id))
        elif modules:
            module_combo.set_selected(0)
        module_page.append(module_combo)

        module_id_entry = Gtk.Entry()
        module_id_entry.set_text(self.module_id)
        module_title_entry = Gtk.Entry()
        module_title_entry.set_text(self.module_title)
        module_page.append(Gtk.Label(label="Module ID"))
        module_page.append(module_id_entry)
        module_page.append(Gtk.Label(label="Module Title"))
        module_page.append(module_title_entry)

        def _sync_module_entries(_combo, _pspec=None):
            idx = module_combo.get_selected()
            if idx is None or idx < 0:
                return
            mid = module_combo._module_ids[idx] if idx < len(module_combo._module_ids) else None
            if not mid:
                return
            match = next((m for m in modules if m["id"] == mid), None)
            if match:
                module_id_entry.set_text(match["id"])
                module_title_entry.set_text(match["title"])

        module_combo.connect("notify::selected", _sync_module_entries)
        _add_page("module", "Module", module_page)

        # Page 3: Exam date + availability
        exam_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        exam_page.add_css_class("card")
        exam_title = Gtk.Label(label="Exam date & availability")
        exam_title.set_halign(Gtk.Align.START)
        exam_title.add_css_class("section-title")
        exam_page.append(exam_title)

        calendar = Gtk.Calendar()
        exam_page.append(calendar)

        avail_grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        weekday_label = Gtk.Label(label="Weekday minutes")
        weekday_label.set_halign(Gtk.Align.START)
        weekend_label = Gtk.Label(label="Weekend minutes")
        weekend_label.set_halign(Gtk.Align.START)
        weekday_spin = Gtk.SpinButton.new_with_range(0, 480, 15)
        weekend_spin = Gtk.SpinButton.new_with_range(0, 480, 15)
        try:
            avail = getattr(self.engine, "availability", {}) or {}
            weekday_spin.set_value(int(avail.get("weekday") or 0))
            weekend_spin.set_value(int(avail.get("weekend") or 0))
        except Exception:
            pass
        avail_grid.attach(weekday_label, 0, 0, 1, 1)
        avail_grid.attach(weekday_spin, 1, 0, 1, 1)
        avail_grid.attach(weekend_label, 0, 1, 1, 1)
        avail_grid.attach(weekend_spin, 1, 1, 1, 1)
        exam_page.append(avail_grid)

        skip_exam = Gtk.CheckButton(label="Set exam date later")
        exam_page.append(skip_exam)
        _add_page("exam", "Essentials", exam_page)

        # Page 4: Import data
        import_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        import_page.add_css_class("card")
        import_title = Gtk.Label(label="Import data (optional)")
        import_title.set_halign(Gtk.Align.START)
        import_title.add_css_class("section-title")
        import_page.append(import_title)
        import_note = Gtk.Label(label="Bring in Study Hub scores and questions to personalize the plan.")
        import_note.set_halign(Gtk.Align.START)
        import_note.set_wrap(True)
        import_note.add_css_class("muted")
        import_page.append(import_note)
        import_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        import_pdf = Gtk.Button(label="Import PDF scores")
        import_pdf.connect("clicked", self.on_import_pdf)
        import_ai = Gtk.Button(label="Import Questions")
        import_ai.connect("clicked", self.on_import_ai_questions)
        import_row.append(import_pdf)
        import_row.append(import_ai)
        import_page.append(import_row)
        _add_page("import", "Imports", import_page)

        # Page 5: Finish
        finish_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        finish_page.add_css_class("card")
        finish_label = Gtk.Label(label="You’re ready to study. Let’s lock in today’s mission.")
        finish_label.set_halign(Gtk.Align.START)
        finish_label.set_wrap(True)
        finish_page.append(finish_label)
        _add_page("finish", "Finish", finish_page)

        page_order = ["welcome", "module", "exam", "import", "finish"]

        nav_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        nav_row.set_halign(Gtk.Align.END)
        back_btn = Gtk.Button(label="Back")
        next_btn = Gtk.Button(label="Next")
        finish_btn = Gtk.Button(label="Finish")
        close_btn = Gtk.Button(label="Close")
        nav_row.append(close_btn)
        nav_row.append(back_btn)
        nav_row.append(next_btn)
        nav_row.append(finish_btn)
        content.append(nav_row)

        def _set_page(name: str) -> None:
            if name not in page_titles:
                return
            stack.set_visible_child_name(name)

        def _get_current_index() -> int:
            name = stack.get_visible_child_name() or page_order[0]
            try:
                return page_order.index(name)
            except ValueError:
                return 0

        def _update_nav() -> None:
            idx = _get_current_index()
            name = page_order[idx]
            header.set_text(page_titles.get(name, ""))
            back_btn.set_sensitive(idx > 0)
            next_btn.set_visible(idx < len(page_order) - 1)
            finish_btn.set_visible(idx == len(page_order) - 1)
            try:
                dialog.set_default_widget(finish_btn if idx == len(page_order) - 1 else next_btn)
            except Exception:
                pass

        def _on_next(_btn):
            idx = min(len(page_order) - 1, _get_current_index() + 1)
            _set_page(page_order[idx])

        def _on_back(_btn):
            idx = max(0, _get_current_index() - 1)
            _set_page(page_order[idx])

        def _on_close(_btn):
            dialog.destroy()

        def _on_apply(_btn=None):
            new_id = module_id_entry.get_text().strip()
            new_title = module_title_entry.get_text().strip() or new_id
            if not new_id:
                idx = module_combo.get_selected()
                if idx is not None and idx >= 0 and idx < len(module_combo._module_ids):
                    new_id = module_combo._module_ids[idx]
                    match = next((m for m in modules if m["id"] == new_id), None)
                    new_title = (match.get("title") if match else "") or new_id
            if new_id:
                if new_id != self.module_id or new_title != self.module_title:
                    self.module_id = new_id
                    self.module_title = new_title
                    self.save_preferences()
            if not skip_exam.get_active():
                dt = calendar.get_date()
                try:
                    new_date = datetime.date(dt.get_year(), dt.get_month(), dt.get_day_of_month())
                    self.engine.exam_date = new_date
                    self.exam_date = new_date
                except Exception:
                    pass
            try:
                self.engine.availability["weekday"] = int(weekday_spin.get_value())
                self.engine.availability["weekend"] = int(weekend_spin.get_value())
            except Exception:
                pass
            try:
                self.engine.save_data()
            except Exception:
                pass
            self.first_run_completed = True
            self.save_preferences()
            self.update_exam_date_display()
            self.update_availability_display()
            self.update_dashboard()
            self.update_recommendations()
            self.update_study_room_card()
            dialog.destroy()

            if new_id and new_id != getattr(self.engine, "module_id", self.module_id):
                msg = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.NONE,
                    text="Restart required to apply the new module.",
                )
                msg.add_buttons("_Restart Later", Gtk.ResponseType.CLOSE, "_Restart Now", Gtk.ResponseType.OK)
                def _on_msg(_m, resp):
                    _m.destroy()
                    if resp == Gtk.ResponseType.OK:
                        self._restart_app()
                msg.connect("response", _on_msg)
                msg.present()

        back_btn.connect("clicked", _on_back)
        next_btn.connect("clicked", _on_next)
        finish_btn.connect("clicked", _on_apply)
        close_btn.connect("clicked", _on_close)
        stack.connect("notify::visible-child-name", lambda *_args: _update_nav())

        _set_page(page_order[0])
        _update_nav()
        _sync_module_entries(module_combo)
        def _on_destroy(_d):
            if self._first_run_auto and not self.first_run_completed:
                self.first_run_completed = True
                self.save_preferences()
            self._first_run_auto = False
            self._first_run_assistant = None
        dialog.connect("destroy", _on_destroy)
        return dialog

    def on_edit_focus_allowlist(self, _action, _param):
        dialog = self._new_dialog(title="Focus Allowlist (Hyprland)", transient_for=self, modal=True)
        dialog.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_Save", Gtk.ResponseType.OK, "_Defaults", Gtk.ResponseType.APPLY)
        content = dialog.get_content_area()
        content.set_spacing(8)

        info = Gtk.Label(
            label=(
                "Add one Hyprland window class per line (class matching only).\n"
                "Examples: brave-browser, Abiword, Gnumeric, code, org.gnome.Evince"
            )
        )
        info.set_halign(Gtk.Align.START)
        info.set_wrap(True)
        info.add_css_class("muted")
        content.append(info)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(160)
        scroller.add_css_class("card")
        textview = Gtk.TextView()
        buffer = textview.get_buffer()
        current = "\n".join(self.focus_allowlist or [])
        buffer.set_text(current)
        scroller.set_child(textview)
        content.append(scroller)

        add_active_btn = Gtk.Button(label="Add Active Window Class")
        content.append(add_active_btn)

        def _add_active(_btn):
            info = self._get_active_window_info()
            if not info or not info.get("app"):
                return
            token = str(info.get("app")).strip()
            if not token:
                return
            start, end = buffer.get_bounds()
            text = buffer.get_text(start, end, True)
            existing = [t.strip() for t in text.replace(",", "\n").splitlines() if t.strip()]
            if token in existing:
                return
            existing.append(token)
            buffer.set_text("\n".join(existing))

        add_active_btn.connect("clicked", _add_active)

        def _on_response(_d, response):
            if response == Gtk.ResponseType.APPLY:
                buffer.set_text("\n".join(DEFAULT_FOCUS_ALLOWLIST))
                return
            if response == Gtk.ResponseType.OK:
                start, end = buffer.get_bounds()
                raw = buffer.get_text(start, end, True)
                tokens = []
                seen = set()
                for part in raw.replace(",", "\n").splitlines():
                    token = part.strip()
                    if not token:
                        continue
                    key = token.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    tokens.append(token)
                self.focus_allowlist = tokens or list(DEFAULT_FOCUS_ALLOWLIST)
                self.save_preferences()
            dialog.destroy()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_set_confidence_note(self, _action, _param):
        if not self._has_chapters():
            self.send_notification("Confidence Note", "No chapters loaded.")
            return
        self._ensure_valid_topic()
        topic = self.current_topic
        if not topic:
            return
        existing = ""
        try:
            notes = getattr(self.engine, "chapter_notes", {}) or {}
            entry = notes.get(topic, {})
            if isinstance(entry, dict):
                existing = entry.get("note", "") or ""
        except Exception:
            existing = ""
        dialog = self._new_dialog(title=f"Confidence Note — {topic}", transient_for=self, modal=True)
        dialog.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_Clear", Gtk.ResponseType.APPLY, "_Save", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(8)
        info = Gtk.Label(label="Add a short note about your confidence in this chapter.")
        info.set_halign(Gtk.Align.START)
        info.set_wrap(True)
        info.add_css_class("muted")
        content.append(info)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(90)
        textview = Gtk.TextView()
        buffer = textview.get_buffer()
        buffer.set_text(existing)
        scroller.set_child(textview)
        content.append(scroller)

        def _on_resp(_d, resp):
            _d.destroy()
            if resp == Gtk.ResponseType.CANCEL:
                return
            try:
                notes = getattr(self.engine, "chapter_notes", {}) or {}
                if not isinstance(notes, dict):
                    notes = {}
                if resp == Gtk.ResponseType.APPLY:
                    notes.pop(topic, None)
                else:
                    start, end = buffer.get_bounds()
                    text = buffer.get_text(start, end, True).strip()
                    if text:
                        notes.setdefault(topic, {})["note"] = text
                        notes[topic]["updated"] = datetime.date.today().isoformat()
                        try:
                            quiz_results = getattr(self.engine, "quiz_results", {}) or {}
                            baseline = float(quiz_results.get(topic, 0) or 0) if isinstance(quiz_results, dict) else 0.0
                            notes[topic]["note_quiz_score"] = baseline
                            notes[topic].pop("note_quiz_improved", None)
                        except Exception:
                            pass
                    else:
                        notes.pop(topic, None)
                self.engine.chapter_notes = notes
                self.engine.save_data()
            except Exception:
                pass
            self.update_dashboard()
            self.update_study_room_card()

        dialog.connect("response", _on_resp)
        dialog.present()

    def on_open_preferences(self, _action, _param):
        dialog = self._new_dialog(title="Preferences", transient_for=self, modal=True)
        dialog.add_buttons("_Close", Gtk.ResponseType.CLOSE)
        content = dialog.get_content_area()
        content.set_spacing(8)

        general_title = Gtk.Label(label="General")
        general_title.set_halign(Gtk.Align.START)
        general_title.add_css_class("section-title")
        content.append(general_title)
        general_note = Gtk.Label(
            label="Core behavior and appearance. Changes apply immediately when you close this dialog."
        )
        general_note.set_halign(Gtk.Align.START)
        general_note.set_wrap(True)
        general_note.add_css_class("muted")
        content.append(general_note)

        allow_lower = Gtk.CheckButton(
            label="Apply scores even if lower (overwrite competence)"
        )
        allow_lower.set_active(bool(self.allow_lower_scores))
        show_menu = Gtk.CheckButton(label="Show menu bar (Ctrl+M)")
        show_menu.set_active(bool(self.menu_bar_visible))
        notifications = Gtk.CheckButton(label="Enable desktop notifications")
        notifications.set_active(bool(self.notifications_enabled))
        system_theme = Gtk.CheckButton(label="Use system theme (nwg-look)")
        system_theme.set_active(bool(self.use_system_theme))
        coach_only = Gtk.CheckButton(label="Coach-only view (hide plan list)")
        coach_only.set_active(bool(self.coach_only_view))
        sticky_pick = Gtk.CheckButton(label="Sticky coach pick (keep today’s focus on restart)")
        sticky_pick.set_active(bool(self.sticky_coach_pick))
        recall_release = Gtk.CheckButton(
            label="Recall counts for coach release (2 focus + recall)"
        )
        recall_release.set_active(bool(self.recall_counts_for_release))

        content.append(allow_lower)
        content.append(show_menu)
        content.append(notifications)
        content.append(system_theme)
        content.append(coach_only)
        content.append(sticky_pick)
        content.append(recall_release)

        pomodoro_title = Gtk.Label(label="Pomodoro")
        pomodoro_title.set_halign(Gtk.Align.START)
        pomodoro_title.add_css_class("section-title")
        content.append(pomodoro_title)
        pomodoro_note = Gtk.Label(label="Timers, breaks, and completion feedback.")
        pomodoro_note.set_halign(Gtk.Align.START)
        pomodoro_note.set_wrap(True)
        pomodoro_note.add_css_class("muted")
        content.append(pomodoro_note)

        pomodoro_banner = Gtk.CheckButton(label="Pomodoro banner on completion")
        pomodoro_banner.set_active(bool(self.pomodoro_banner_enabled))
        pomodoro_title_flash = Gtk.CheckButton(label="Flash window title on completion")
        pomodoro_title_flash.set_active(bool(self.pomodoro_title_flash_enabled))
        pomodoro_sound = Gtk.CheckButton(label="Play sound on completion/break over")
        pomodoro_sound.set_active(bool(self.pomodoro_sound_enabled))
        short_break_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        short_break_label = Gtk.Label(label="Short break (min)")
        short_break_label.set_halign(Gtk.Align.START)
        short_break_spin = Gtk.SpinButton.new_with_range(1, 20, 1)
        short_break_spin.set_value(int(self.short_break_minutes))
        short_break_spin.set_numeric(True)
        short_break_row.append(short_break_label)
        short_break_row.append(short_break_spin)
        long_break_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        long_break_label = Gtk.Label(label="Long break (min)")
        long_break_label.set_halign(Gtk.Align.START)
        long_break_spin = Gtk.SpinButton.new_with_range(5, 30, 1)
        long_break_spin.set_value(int(self.long_break_minutes))
        long_break_spin.set_numeric(True)
        long_break_row.append(long_break_label)
        long_break_row.append(long_break_spin)
        long_every_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        long_every_label = Gtk.Label(label="Long break every (Pomodoros)")
        long_every_label.set_halign(Gtk.Align.START)
        long_every_spin = Gtk.SpinButton.new_with_range(2, 6, 1)
        long_every_spin.set_value(int(self.long_break_every))
        long_every_spin.set_numeric(True)
        long_every_row.append(long_every_label)
        long_every_row.append(long_every_spin)
        skip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        skip_label = Gtk.Label(label="Max break skips in a row")
        skip_label.set_halign(Gtk.Align.START)
        skip_spin = Gtk.SpinButton.new_with_range(0, 3, 1)
        skip_spin.set_value(int(self.max_break_skips))
        skip_spin.set_numeric(True)
        skip_row.append(skip_label)
        skip_row.append(skip_spin)

        content.append(pomodoro_banner)
        content.append(pomodoro_title_flash)
        content.append(pomodoro_sound)
        content.append(short_break_row)
        content.append(long_break_row)
        content.append(long_every_row)
        content.append(skip_row)
        reset_pomodoro_btn = Gtk.Button(label="Reset Pomodoro Defaults")
        content.append(reset_pomodoro_btn)

        focus_title = Gtk.Label(label="Focus Tracking (Hyprland)")
        focus_title.set_halign(Gtk.Align.START)
        focus_title.add_css_class("section-title")
        content.append(focus_title)
        focus_note_primary = Gtk.Label(
            label="Auto-pause is based on your allowlist and idle time. Requires Hyprland."
        )
        focus_note_primary.set_halign(Gtk.Align.START)
        focus_note_primary.set_wrap(True)
        focus_note_primary.add_css_class("muted")
        content.append(focus_note_primary)

        focus_tracking = Gtk.CheckButton(label="Enable focus tracking (Hyprland active window)")
        focus_tracking.set_active(bool(self.focus_tracking_enabled))
        if not self._focus_tracking_available:
            focus_tracking.set_sensitive(False)
        focus_note = None
        if not self._focus_tracking_available:
            focus_note = Gtk.Label(
                label="Focus tracking is unavailable (requires Hyprland + hyprctl)."
            )
            focus_note.set_halign(Gtk.Align.START)
            focus_note.set_wrap(True)
            focus_note.add_css_class("muted")
        focus_autopause = Gtk.CheckButton(label="Auto-pause Pomodoro when leaving allowed apps")
        focus_autopause.set_active(bool(self.focus_auto_pause_enabled))
        if not self._focus_tracking_available:
            focus_autopause.set_sensitive(False)
        focus_autopause.set_tooltip_text(
            f"Pauses after {int(self.focus_idle_threshold)}s off-task, resumes when you return."
        )
        idle_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        idle_label = Gtk.Label(label="Idle threshold (sec)")
        idle_label.set_halign(Gtk.Align.START)
        idle_spin = Gtk.SpinButton.new_with_range(30, 600, 10)
        idle_spin.set_value(int(self.focus_idle_threshold))
        idle_spin.set_numeric(True)
        if not self._focus_tracking_available:
            idle_spin.set_sensitive(False)
        idle_row.append(idle_label)
        idle_row.append(idle_spin)
        add_active_class_btn = Gtk.Button(label="Add Active Window Class to Allowlist")
        add_active_class_btn.set_sensitive(bool(self._focus_tracking_available))
        allowlist_note = Gtk.Label(label="Allowlist size: %d" % len(self.focus_allowlist))
        allowlist_note.set_halign(Gtk.Align.START)
        allowlist_note.add_css_class("muted")
        hypridle_note = None
        if self._hypridle_supported:
            hook_path = self._hypridle_state_path
            active_path = self._pomodoro_active_state_path
            hypridle_text = (
                "Hypridle idle hook (optional, Pomodoro-only):\n"
                f'on-timeout = sh -c "pgrep -f studyplan_app.py >/dev/null && '
                f'[ -f {active_path} ] && echo idle > {hook_path}"\n'
                f'on-resume = sh -c "pgrep -f studyplan_app.py >/dev/null && '
                f'[ -f {active_path} ] && echo active > {hook_path}"'
            )
            hypridle_note = Gtk.Label(label=hypridle_text)
            hypridle_note.set_halign(Gtk.Align.START)
            hypridle_note.set_wrap(True)
            hypridle_note.set_selectable(True)
            hypridle_note.add_css_class("muted")

        content.append(focus_tracking)
        content.append(focus_autopause)
        content.append(idle_row)
        content.append(add_active_class_btn)
        content.append(allowlist_note)
        reset_focus_btn = Gtk.Button(label="Reset Focus Defaults")
        content.append(reset_focus_btn)
        if focus_note is not None:
            content.append(focus_note)
        if hypridle_note is not None:
            content.append(hypridle_note)
        diagnostics = Gtk.Expander()
        diagnostics.set_label("Diagnostics")
        diagnostics_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        test_banner_btn = Gtk.Button(label="Test Pomodoro Banner")
        test_flash_btn = Gtk.Button(label="Test Title Flash")
        test_sound_btn = Gtk.Button(label="Test Sound")
        test_idle_btn = Gtk.Button(label="Test Idle Detection")
        test_idle_hook_btn = Gtk.Button(label="Test Hypridle Hook")
        diagnostics_box.append(test_banner_btn)
        diagnostics_box.append(test_flash_btn)
        diagnostics_box.append(test_sound_btn)
        diagnostics_box.append(test_idle_btn)
        diagnostics_box.append(test_idle_hook_btn)
        diagnostics.set_child(diagnostics_box)
        diagnostics.set_expanded(False)
        content.append(diagnostics)

        def _test_banner(_btn):
            self._show_pomodoro_banner("Test banner — Pomodoro complete.")

        def _test_flash(_btn):
            self._flash_window_title()

        def _test_sound(_btn):
            path = self._ensure_pomodoro_sound_file()
            if path:
                self._play_sound_file(path)
            else:
                self.send_notification("Sound Test", "Sound file unavailable.")

        def _test_idle(_btn):
            idle_seconds = self._get_idle_seconds()
            source = self._last_idle_source or "unavailable"
            if idle_seconds is None:
                msg = f"Idle detection unavailable ({source})."
            else:
                msg = f"Idle: {idle_seconds:.1f}s ({source})."
            dialog = self._new_message_dialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=msg,
            )
            dialog.connect("response", lambda d, r: d.destroy())
            dialog.present()

        def _test_idle_hook(_btn):
            path = self._hypridle_state_path
            if not path:
                self._show_text_dialog("Hypridle Hook", "No hook path configured.", Gtk.MessageType.INFO)
                return
            if not os.path.exists(path):
                self._show_text_dialog("Hypridle Hook", "State file not found yet.", Gtk.MessageType.INFO)
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    state = (f.read() or "").strip()
                mtime = os.path.getmtime(path)
                age = max(0.0, time.time() - float(mtime))
                msg = f"State: {state or '(empty)'}\nUpdated: {age:.1f}s ago"
            except Exception as exc:
                msg = f"Failed to read state file: {exc}"
            self._show_text_dialog("Hypridle Hook", msg, Gtk.MessageType.INFO)

        test_banner_btn.connect("clicked", _test_banner)
        test_flash_btn.connect("clicked", _test_flash)
        test_sound_btn.connect("clicked", _test_sound)
        test_idle_btn.connect("clicked", _test_idle)
        test_idle_hook_btn.connect("clicked", _test_idle_hook)
        def _reset_pomodoro_defaults(_btn):
            pomodoro_banner.set_active(True)
            pomodoro_title_flash.set_active(True)
            pomodoro_sound.set_active(True)
            short_break_spin.set_value(DEFAULT_SHORT_BREAK_MINUTES)
            long_break_spin.set_value(DEFAULT_LONG_BREAK_MINUTES)
            long_every_spin.set_value(DEFAULT_LONG_BREAK_EVERY)
            skip_spin.set_value(DEFAULT_MAX_BREAK_SKIPS)

        def _reset_focus_defaults(_btn):
            focus_tracking.set_active(True)
            focus_autopause.set_active(True)
            idle_spin.set_value(FOCUS_IDLE_THRESHOLD_SECONDS)

        reset_pomodoro_btn.connect("clicked", _reset_pomodoro_defaults)
        reset_focus_btn.connect("clicked", _reset_focus_defaults)

        def _add_active_class(_btn):
            info = self._get_active_window_info()
            if not info or not info.get("app"):
                self.send_notification("Focus Allowlist", "No active window class detected.")
                return
            token = str(info.get("app")).strip()
            if not token:
                return
            if token not in self.focus_allowlist:
                self.focus_allowlist.append(token)
                allowlist_note.set_text("Allowlist size: %d (added %s)" % (len(self.focus_allowlist), token))
                self.save_preferences()
            else:
                allowlist_note.set_text("Allowlist size: %d (already has %s)" % (len(self.focus_allowlist), token))

        add_active_class_btn.connect("clicked", _add_active_class)

        def _on_close(_d, _r):
            self.allow_lower_scores = bool(allow_lower.get_active())
            self.menu_bar_visible = bool(show_menu.get_active())
            self.notifications_enabled = bool(notifications.get_active())
            self.pomodoro_banner_enabled = bool(pomodoro_banner.get_active())
            self.pomodoro_title_flash_enabled = bool(pomodoro_title_flash.get_active())
            self.pomodoro_sound_enabled = bool(pomodoro_sound.get_active())
            try:
                self.short_break_minutes = int(short_break_spin.get_value())
            except Exception:
                self.short_break_minutes = DEFAULT_SHORT_BREAK_MINUTES
            try:
                self.long_break_minutes = int(long_break_spin.get_value())
            except Exception:
                self.long_break_minutes = DEFAULT_LONG_BREAK_MINUTES
            try:
                self.long_break_every = int(long_every_spin.get_value())
            except Exception:
                self.long_break_every = DEFAULT_LONG_BREAK_EVERY
            try:
                self.max_break_skips = int(skip_spin.get_value())
            except Exception:
                self.max_break_skips = DEFAULT_MAX_BREAK_SKIPS
            self.use_system_theme = bool(system_theme.get_active())
            self.coach_only_view = bool(coach_only.get_active())
            self.sticky_coach_pick = bool(sticky_pick.get_active())
            self.recall_counts_for_release = bool(recall_release.get_active())
            self.focus_tracking_enabled = bool(focus_tracking.get_active())
            self.focus_auto_pause_enabled = bool(focus_autopause.get_active())
            try:
                self.focus_idle_threshold = int(idle_spin.get_value())
            except Exception:
                self.focus_idle_threshold = FOCUS_IDLE_THRESHOLD_SECONDS
            self.menu_bar.set_visible(self.menu_bar_visible)
            if getattr(self, "plan_scroll", None):
                self.plan_scroll.set_visible(not self.coach_only_view)
            if getattr(self, "plan_hint", None):
                self.plan_hint.set_visible(bool(self.coach_only_view))
            if getattr(self, "coach_only_badge", None):
                self.coach_only_badge.set_visible(bool(self.coach_only_view))
            if getattr(self, "coach_only_toggle", None):
                self.coach_only_toggle.set_active(bool(self.coach_only_view))
                self.coach_only_toggle.set_visible(not self.coach_only_view)
            apply_theme(bool(self.use_system_theme))
            self.save_preferences()
            dialog.destroy()

        dialog.connect("response", _on_close)
        dialog.present()

    def on_debug_info(self, _action, _param):
        hub = getattr(self.engine, "study_hub_stats", {}) or {}
        msg = (
            f"Exam date: {self.exam_date}\n"
            f"Chapters: {len(self.engine.CHAPTERS)}\n"
            f"Competence entries: {len(self.engine.competence)}\n"
            f"Quiz scores parsed: {len(hub.get('quiz_scores', {}))}\n"
            f"Practice scores parsed: {len(hub.get('practice_scores', {}))}\n"
            f"Detail scores parsed: {len(hub.get('detail_scores', {}))}\n"
            f"Categories parsed: {len(hub.get('category_totals', {}))}"
        )
        self._show_text_dialog("Debug Info", msg, Gtk.MessageType.INFO)

    def on_view_logs(self, _action, _param):
        log_path = os.path.expanduser("~/.config/studyplan/app.log")
        if not os.path.exists(log_path):
            self._show_text_dialog("App Log", "No app log found yet.", Gtk.MessageType.INFO)
            return

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except OSError as e:
            self._show_text_dialog("App Log", f"Failed to read app log: {e}", Gtk.MessageType.ERROR)
            return

        self._show_scrolling_text("App Log", content if content else "(log is empty)")

    def on_view_reflections(self, _action, _param):
        notes = getattr(self.engine, "chapter_notes", {}) or {}
        if not isinstance(notes, dict) or not notes:
            self._show_text_dialog("Reflections", "No reflections yet.", Gtk.MessageType.INFO)
            return
        entries = []
        for chapter, entry in notes.items():
            if not isinstance(entry, dict):
                continue
            note = (entry.get("note") or "").strip()
            reflection = (entry.get("reflection") or "").strip()
            updated = entry.get("updated") or ""
            if not (note or reflection):
                continue
            try:
                updated_date = datetime.date.fromisoformat(updated) if updated else None
            except Exception:
                updated_date = None
            entries.append((updated_date, chapter, note, reflection, updated))
        if not entries:
            self._show_text_dialog("Reflections", "No reflections yet.", Gtk.MessageType.INFO)
            return
        entries.sort(key=lambda x: (x[0] is None, x[0]), reverse=True)
        lines = []
        for updated_date, chapter, note, reflection, updated in entries:
            lines.append(str(chapter))
            if note:
                lines.append(f"Confidence note: {note}")
            if reflection:
                lines.append(f"Reflection: {reflection}")
            if updated:
                lines.append(f"Updated: {updated}")
            lines.append("")
        self._show_scrolling_text("Reflections", "\n".join(lines).strip())

    def on_show_competence_table(self, _action, _param):
        comp = getattr(self.engine, "competence", {}) or {}
        rows = []
        for chapter in self.engine.CHAPTERS:
            try:
                score = float(comp.get(chapter, 0) or 0)
            except Exception:
                score = 0.0
            rows.append((chapter, f"{score:.0f}%"))
        rows.sort(key=lambda x: float(x[1].replace("%", "")))
        dialog = self._new_dialog(title="Competence by Chapter", transient_for=self, modal=True)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.set_default_size(520, 520)
        content = dialog.get_content_area()
        content.set_spacing(8)
        content.append(
            self._build_import_table(
                "Competence Snapshot",
                ["Chapter", "Competence"],
                rows,
                min_height=240,
            )
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def on_reset_chapter_competence(self, _action, _param):
        if not self.engine.CHAPTERS:
            self.send_notification("Competence Reset", "No chapters available.")
            return
        dialog = self._new_dialog(title="Reset Chapter Competence", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Reset", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(8)
        helper = Gtk.Label(label="Select a chapter to reset its competence to 0%.")
        helper.set_halign(Gtk.Align.START)
        helper.set_wrap(True)
        content.append(helper)
        dropdown = Gtk.DropDown.new_from_strings(self.engine.CHAPTERS)
        content.append(dropdown)
        value_label = Gtk.Label()
        value_label.set_halign(Gtk.Align.START)
        value_label.add_css_class("muted")
        content.append(value_label)

        def _get_selected_chapter() -> str | None:
            item = dropdown.get_selected_item()
            if item is None:
                return None
            if hasattr(item, "get_string"):
                return item.get_string()
            try:
                return str(item)
            except Exception:
                return None

        def _refresh_label(*_args):
            chapter = _get_selected_chapter()
            if not chapter:
                value_label.set_text("Competence: —")
                return
            try:
                score = float(getattr(self.engine, "competence", {}).get(chapter, 0) or 0)
            except Exception:
                score = 0.0
            value_label.set_text(f"Current competence: {score:.0f}%")

        dropdown.connect("notify::selected", _refresh_label)
        _refresh_label()

        def _on_response(d, response):
            if response != Gtk.ResponseType.OK:
                d.destroy()
                return
            chapter = _get_selected_chapter()
            if not chapter:
                d.destroy()
                return
            confirm = self._new_message_dialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text=f"Reset competence for “{chapter}” to 0%?",
            )

            def _on_confirm(_c, resp):
                _c.destroy()
                if resp != Gtk.ResponseType.OK:
                    return
                try:
                    self.engine.competence[chapter] = 0
                    self.engine.save_data()
                except Exception:
                    pass
                self.update_daily_plan()
                self.update_dashboard()
                self.update_recommendations()
                self.update_study_room_card()
                self.send_notification("Competence Reset", f"{chapter} reset to 0%.")
                d.destroy()

            confirm.connect("response", _on_confirm)
            confirm.present()

        dialog.connect("response", _on_response)
        dialog.present()

    def on_reset_all_competence(self, _action, _param):
        if not self.engine.CHAPTERS:
            self.send_notification("Competence Reset", "No chapters available.")
            return
        confirm = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Reset competence for all chapters to 0%?",
        )

        def _on_confirm(_c, resp):
            _c.destroy()
            if resp != Gtk.ResponseType.OK:
                return
            try:
                for ch in self.engine.CHAPTERS:
                    self.engine.competence[ch] = 0
                self.engine.save_data()
            except Exception:
                pass
            self.update_daily_plan()
            self.update_dashboard()
            self.update_recommendations()
            self.update_study_room_card()
            self.send_notification("Competence Reset", "All chapters reset to 0%.")

        confirm.connect("response", _on_confirm)
        confirm.present()

    def load_preferences(self) -> None:
        try:
            prefs_path = os.path.expanduser("~/.config/studyplan/preferences.json")
            if os.path.exists(prefs_path):
                with open(prefs_path, "r") as f:
                    data = json.load(f)
                    self.allow_lower_scores = bool(data.get("allow_lower_scores", False))
                    self.menu_bar_visible = bool(data.get("menu_bar_visible", True))
                    self.notifications_enabled = bool(data.get("notifications_enabled", True))
                    self.xp_total = int(data.get("xp_total", 0) or 0)
                    self.level = int(data.get("level", 1) or 1)
                    self.achievements = set(data.get("achievements", []) or [])
                    self.use_system_theme = bool(data.get("use_system_theme", True))
                    self.coach_only_view = bool(data.get("coach_only_view", False))
                    self.sticky_coach_pick = bool(data.get("sticky_coach_pick", True))
                    self.last_coach_pick = data.get("last_coach_pick")
                    self.last_coach_pick_date = data.get("last_coach_pick_date")
                    self.onboarding_dismissed = bool(data.get("onboarding_dismissed", False))
                    self.first_run_completed = bool(data.get("first_run_completed", False))
                    mod_id = data.get("module_id")
                    mod_title = data.get("module_title")
                    if isinstance(mod_id, str) and mod_id.strip():
                        self.module_id = mod_id.strip()
                    if isinstance(mod_title, str) and mod_title.strip():
                        self.module_title = mod_title.strip()
                    self.short_pomodoro_today_count = int(data.get("short_pomodoro_today_count", 0) or 0)
                    self.quiz_sessions_completed = int(data.get("quiz_sessions_completed", 0) or 0)
                    self.pomodoro_today_count = int(data.get("pomodoro_today_count", 0) or 0)
                    self.last_pomodoro_date = data.get("last_pomodoro_date")
                    dpbc = data.get("daily_pomodoros_by_chapter", {}) or {}
                    self.daily_pomodoros_by_chapter = dpbc if isinstance(dpbc, dict) else {}
                    drbc = data.get("daily_recall_by_chapter", {}) or {}
                    self.daily_recall_by_chapter = drbc if isinstance(drbc, dict) else {}
                    self.recall_counts_for_release = bool(data.get("recall_counts_for_release", True))
                    atl = data.get("action_time_log", {}) or {}
                    self.action_time_log = atl if isinstance(atl, dict) else {}
                    sessions = data.get("action_time_sessions", []) or []
                    self.action_time_sessions = sessions if isinstance(sessions, list) else []
                    qual = data.get("session_quality_log", []) or []
                    self.session_quality_log = qual if isinstance(qual, list) else []
                    fil = data.get("focus_integrity_log", []) or []
                    self.focus_integrity_log = fil if isinstance(fil, list) else []
                    self.contract_log = data.get("contract_log", []) or []
                    self.last_hindsight_week = data.get("last_hindsight_week")
                    self._last_momentum_date = data.get("last_momentum_date")
                    try:
                        self.pomodoro_minutes_today_raw = float(data.get("pomodoro_minutes_today_raw", 0) or 0)
                    except Exception:
                        self.pomodoro_minutes_today_raw = 0.0
                    try:
                        self.pomodoro_minutes_today_verified = float(data.get("pomodoro_minutes_today_verified", 0) or 0)
                    except Exception:
                        self.pomodoro_minutes_today_verified = 0.0
                    self.quiz_questions_today = int(data.get("quiz_questions_today", 0) or 0)
                    self.quiz_sessions_today = int(data.get("quiz_sessions_today", 0) or 0)
                    self.last_quiz_date = data.get("last_quiz_date")
                    self.last_quest_date = data.get("last_quest_date")
                    self.last_reflection_date = data.get("last_reflection_date")
                    self.last_hub_import_date = data.get("last_hub_import_date")
                    self.last_weekly_review_date = data.get("last_weekly_review_date")
                    self.micro_streak_recall = int(data.get("micro_streak_recall", 0) or 0)
                    history = data.get("coach_reason_history", []) or []
                    self.coach_reason_history = history if isinstance(history, list) else []
                    self.last_break_adjust_note = data.get("last_break_adjust_note")
                    self.last_weekly_summary_week = data.get("last_weekly_summary_week")
                    baselines = data.get("risk_baselines", {}) or {}
                    self.risk_baselines = baselines if isinstance(baselines, dict) else {}
                    self.focus_tracking_enabled = bool(data.get("focus_tracking_enabled", True))
                    self.focus_auto_pause_enabled = bool(data.get("focus_auto_pause_enabled", True))
                    idle_threshold = data.get("focus_idle_threshold", FOCUS_IDLE_THRESHOLD_SECONDS)
                    try:
                        self.focus_idle_threshold = int(idle_threshold)
                    except Exception:
                        self.focus_idle_threshold = FOCUS_IDLE_THRESHOLD_SECONDS
                    self.pomodoro_banner_enabled = bool(data.get("pomodoro_banner_enabled", True))
                    self.pomodoro_title_flash_enabled = bool(data.get("pomodoro_title_flash_enabled", True))
                    self.pomodoro_sound_enabled = bool(data.get("pomodoro_sound_enabled", True))
                    short_break = data.get("short_break_minutes", DEFAULT_SHORT_BREAK_MINUTES)
                    long_break = data.get("long_break_minutes", DEFAULT_LONG_BREAK_MINUTES)
                    long_every = data.get("long_break_every", DEFAULT_LONG_BREAK_EVERY)
                    max_skips = data.get("max_break_skips", DEFAULT_MAX_BREAK_SKIPS)
                    if isinstance(short_break, (int, float)):
                        self.short_break_minutes = max(1, int(short_break))
                    if isinstance(long_break, (int, float)):
                        self.long_break_minutes = max(5, int(long_break))
                    if isinstance(long_every, (int, float)):
                        self.long_break_every = max(2, int(long_every))
                    if isinstance(max_skips, (int, float)):
                        self.max_break_skips = max(0, int(max_skips))
                    self.last_coach_date = data.get("last_coach_date")
                    cleared = data.get("weak_cleared_notified", []) or []
                    if isinstance(cleared, list):
                        self.weak_cleared_notified = set(str(x) for x in cleared if str(x))
                    allowlist = data.get("focus_allowlist")
                    if isinstance(allowlist, list) and allowlist:
                        cleaned = [str(x) for x in allowlist if str(x).strip()]
                        for token in ("studyassistant", "studyplan", "studyplan_app", "brave", "brave-browser", "abiword", "gnumeric"):
                            if token not in cleaned:
                                cleaned.append(token)
                        self.focus_allowlist = cleaned
        except Exception:
            pass

    def save_preferences(self) -> None:
        try:
            prefs_path = os.path.expanduser("~/.config/studyplan/preferences.json")
            os.makedirs(os.path.dirname(prefs_path), exist_ok=True)
            data = {
                "allow_lower_scores": bool(self.allow_lower_scores),
                "menu_bar_visible": bool(self.menu_bar_visible),
                "notifications_enabled": bool(self.notifications_enabled),
                "xp_total": int(self.xp_total),
                "level": int(self.level),
                "achievements": sorted(self.achievements),
                "use_system_theme": bool(self.use_system_theme),
                "coach_only_view": bool(self.coach_only_view),
                "sticky_coach_pick": bool(self.sticky_coach_pick),
                "last_coach_pick": self.last_coach_pick,
                "last_coach_pick_date": self.last_coach_pick_date,
                "onboarding_dismissed": bool(self.onboarding_dismissed),
                "first_run_completed": bool(self.first_run_completed),
                "module_id": str(self.module_id),
                "module_title": str(self.module_title),
                "short_pomodoro_today_count": int(self.short_pomodoro_today_count),
                "quiz_sessions_completed": int(self.quiz_sessions_completed),
                "pomodoro_today_count": int(self.pomodoro_today_count),
                "last_pomodoro_date": self.last_pomodoro_date,
                "daily_pomodoros_by_chapter": self.daily_pomodoros_by_chapter,
                "daily_recall_by_chapter": self.daily_recall_by_chapter,
                "recall_counts_for_release": bool(self.recall_counts_for_release),
                "action_time_log": self.action_time_log,
                "action_time_sessions": self.action_time_sessions[-200:],
                "session_quality_log": self.session_quality_log[-200:],
                "focus_integrity_log": self.focus_integrity_log[-200:],
                "contract_log": self.contract_log,
                "last_hindsight_week": self.last_hindsight_week,
                "last_momentum_date": self._last_momentum_date,
                "pomodoro_minutes_today_raw": float(self.pomodoro_minutes_today_raw or 0.0),
                "pomodoro_minutes_today_verified": float(self.pomodoro_minutes_today_verified or 0.0),
                "quiz_questions_today": int(self.quiz_questions_today),
                "quiz_sessions_today": int(self.quiz_sessions_today),
                "last_quiz_date": self.last_quiz_date,
                "last_quest_date": self.last_quest_date,
                "last_reflection_date": self.last_reflection_date,
                "last_hub_import_date": self.last_hub_import_date,
                "last_weekly_review_date": self.last_weekly_review_date,
                "micro_streak_recall": int(self.micro_streak_recall),
                "coach_reason_history": list(self.coach_reason_history[-3:]),
                "last_break_adjust_note": self.last_break_adjust_note,
                "last_weekly_summary_week": self.last_weekly_summary_week,
                "risk_baselines": self.risk_baselines,
                "focus_tracking_enabled": bool(self.focus_tracking_enabled),
                "focus_auto_pause_enabled": bool(self.focus_auto_pause_enabled),
                "focus_idle_threshold": int(self.focus_idle_threshold),
                "pomodoro_banner_enabled": bool(self.pomodoro_banner_enabled),
                "pomodoro_title_flash_enabled": bool(self.pomodoro_title_flash_enabled),
                "pomodoro_sound_enabled": bool(self.pomodoro_sound_enabled),
                "short_break_minutes": int(self.short_break_minutes),
                "long_break_minutes": int(self.long_break_minutes),
                "long_break_every": int(self.long_break_every),
                "max_break_skips": int(self.max_break_skips),
                "last_coach_date": self.last_coach_date,
                "weak_cleared_notified": sorted(self.weak_cleared_notified),
                "focus_allowlist": list(self.focus_allowlist),
            }
            with open(prefs_path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _log_error(self, context: str, exc: Exception) -> None:
        try:
            log_path = os.path.expanduser("~/.config/studyplan/app.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            timestamp = datetime.datetime.now().isoformat(timespec="seconds")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {context}: {exc}\n")
        except Exception:
            pass

    def _log_import_history(self, entry: dict) -> None:
        try:
            log_path = os.path.expanduser("~/.config/studyplan/import_history.jsonl")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except Exception:
            pass

    def _build_import_table(
        self,
        title: str,
        headers: list[str],
        rows: list[tuple],
        min_height: int = 140,
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.add_css_class("section-title")
        box.append(title_label)
        if not rows:
            empty = Gtk.Label(label="No entries.")
            empty.set_halign(Gtk.Align.START)
            empty.add_css_class("muted")
            box.append(empty)
            return box
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        for col, header in enumerate(headers):
            h = Gtk.Label()
            h.set_markup(f"<b>{header}</b>")
            h.set_halign(Gtk.Align.START if col == 0 else Gtk.Align.END)
            h.set_xalign(0.0 if col == 0 else 1.0)
            grid.attach(h, col, 0, 1, 1)
        for row_idx, row in enumerate(rows, start=1):
            for col, cell in enumerate(row):
                label = Gtk.Label(label=str(cell))
                label.set_halign(Gtk.Align.START if col == 0 else Gtk.Align.END)
                label.set_xalign(0.0 if col == 0 else 1.0)
                grid.attach(label, col, row_idx, 1, 1)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(min_height)
        scroller.set_child(grid)
        box.append(scroller)
        return box

    def _show_text_dialog(self, title: str, text: str, message_type=Gtk.MessageType.INFO) -> None:
        dialog = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        try:
            dialog.set_title(title)
        except Exception:
            pass
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _show_scrolling_text(self, title: str, content: str) -> None:
        dialog = self._new_dialog(title=title, transient_for=self, modal=True)
        dialog.set_default_size(620, 420)
        content_area = dialog.get_content_area()

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        content_area.append(scroller)

        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_cursor_visible(False)
        buffer = textview.get_buffer()
        buffer.set_text(content if content else "(log is empty)")
        scroller.set_child(textview)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda _b: dialog.destroy())
        content_area.append(close_btn)

        dialog.present()

    def send_notification(self, title: str, message: str, priority=None) -> None:
        if not self.notifications_enabled:
            return
        high_priority = False
        try:
            high_priority = priority == getattr(getattr(Gio, "NotificationPriority", None), "HIGH", None)
        except Exception:
            high_priority = False
        if not high_priority:
            now = datetime.datetime.now().timestamp()
            last = getattr(self, "_last_notif_ts", 0.0)
            if now - last < 1.0:
                return
            self._last_notif_ts = now
        try:
            app = self.get_application()
            if app and hasattr(app, "send_notification"):
                notif = Gio.Notification.new(title)
                notif.set_body(message)
                if priority is not None and hasattr(notif, "set_priority"):
                    try:
                        notif.set_priority(priority)
                    except Exception:
                        pass
                app.send_notification(None, notif)
                return
        except Exception:
            pass
        # Fallback to in-app dialog if desktop notifications aren't available
        self.show_notification(title, message)

    def _get_file_path(self, chooser) -> Optional[str]:
        if chooser is None:
            return None
        try:
            if hasattr(chooser, "get_files"):
                files = chooser.get_files()
                if files is not None and files.get_n_items() > 0:
                    gfile = files.get_item(0)
                    if gfile is not None:
                        return gfile.get_path()
        except Exception:
            pass
        return None

    def update_xp_display(self) -> None:
        try:
            multiplier = self._get_xp_multiplier()
            mult_text = f" • x{multiplier:.1f}" if multiplier > 1.0 else ""
            if self.xp_label:
                self.xp_label.set_markup(f"XP: {self.xp_total} • Level {self.level}{mult_text}")
            if getattr(self, "xp_progress", None):
                progress = (self.xp_total % 100) / 100.0
                self.xp_progress.set_fraction(max(0.0, min(1.0, progress)))
                xp_to_next = 100 - int(self.xp_total % 100)
                self.xp_progress.set_text(f"{xp_to_next} XP to Level {self.level + 1}")
            if getattr(self, "xp_remaining_label", None):
                xp_to_next = 100 - int(self.xp_total % 100)
                self.xp_remaining_label.set_text(f"Next level in {xp_to_next} XP")
            if getattr(self, "xp_multiplier_label", None):
                if multiplier > 1.0:
                    bonus_pct = int(round((multiplier - 1.0) * 100))
                    self.xp_multiplier_label.set_text(f"Streak bonus: +{bonus_pct}% XP")
                else:
                    self.xp_multiplier_label.set_text("Streak bonus: none")
            self.update_study_room_card()
        except Exception:
            pass

    def _get_xp_multiplier(self) -> float:
        streak = int(self.study_streak or 0)
        if streak >= 14:
            return 1.3
        if streak >= 7:
            return 1.2
        if streak >= 3:
            return 1.1
        return 1.0

    def _get_verified_pomodoro_minutes(self, minutes_spent: float) -> float:
        if self.focus_tracking_enabled and self._focus_tracking_available:
            verified = self._focus_active_seconds / 60.0
            return max(0.0, min(float(minutes_spent), float(verified)))
        return max(0.0, float(minutes_spent))

    def _log_coach_contract(self, topic: str, minutes: int = 25) -> None:
        try:
            ts = datetime.datetime.now().isoformat(timespec="seconds")
        except Exception:
            ts = ""
        entry = {"timestamp": ts, "topic": str(topic), "minutes": int(minutes)}
        if not isinstance(self.contract_log, list):
            self.contract_log = []
        self.contract_log.append(entry)
        if len(self.contract_log) > 30:
            self.contract_log = self.contract_log[-30:]
        self.save_preferences()

    def _maybe_show_rescue_prompt(self) -> None:
        if self._rescue_prompted:
            return
        if self._rescue_hits < 2:
            return
        self._rescue_prompted = True
        self.send_notification(
            "Rescue Prompt",
            "Reset: 5-minute break, water, and one paragraph only. Then restart.",
        )

    def _ensure_daily_counters(self) -> None:
        today = datetime.date.today().isoformat()
        if self.last_quiz_date != today:
            self.quiz_questions_today = 0
            self.quiz_sessions_today = 0
            self.last_quiz_date = today
        if self.last_pomodoro_date != today and self.last_pomodoro_date is not None:
            self.pomodoro_today_count = 0
            self.short_pomodoro_today_count = 0
            self.pomodoro_minutes_today_raw = 0.0
            self.pomodoro_minutes_today_verified = 0.0
            self.daily_pomodoros_by_chapter = {}
            self.daily_recall_by_chapter = {}
            self.last_pomodoro_date = today

    def _window_allowed(self, info: dict) -> bool:
        return self._match_allowlist_token(info) is not None

    def _match_allowlist_token(self, info: dict) -> str | None:
        if not info:
            return None
        hay = str(info.get("app", "") or "").lower()
        if not hay:
            hay = str(info.get("title", "") or "").lower()
        for token in self.focus_allowlist or []:
            if token and token.lower() in hay:
                return token
        return None

    def _get_active_window_info(self) -> dict | None:
        if not self._focus_tracking_available:
            return None
        try:
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True,
                text=True,
                timeout=0.8,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout or "{}")
            app = data.get("class") or data.get("initialClass") or data.get("app") or ""
            title = data.get("title") or ""
            return {"app": str(app), "title": str(title)}
        except Exception:
            return None

    def _get_idle_seconds_hypridle(self) -> float | None:
        path = self._hypridle_state_path
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        except Exception:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = (f.read() or "").strip().lower()
        except Exception:
            return None
        if not raw:
            return None
        token = raw.split()[0]
        if token == "idle":
            return max(0.0, time.time() - float(st.st_mtime))
        if token in ("active", "resume", "awake"):
            return 0.0
        return None

    def _set_pomodoro_active_state(self, active: bool) -> None:
        path = self._pomodoro_active_state_path
        if not path:
            return
        if active:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("active\n")
                if self._hypridle_state_path:
                    try:
                        os.makedirs(os.path.dirname(self._hypridle_state_path), exist_ok=True)
                        with open(self._hypridle_state_path, "w", encoding="utf-8") as f:
                            f.write("active\n")
                    except Exception:
                        pass
            except Exception:
                pass
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        try:
            if self._hypridle_state_path:
                os.remove(self._hypridle_state_path)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _get_idle_seconds_logind(self) -> float | None:
        def _parse_idle(output: str) -> tuple[bool | None, int | None, int | None]:
            idle_hint = None
            idle_since = None
            idle_since_hint = None
            for line in (output or "").splitlines():
                if line.startswith("IdleHint="):
                    idle_hint = line.split("=", 1)[1].strip().lower() == "yes"
                elif line.startswith("IdleSinceHint="):
                    try:
                        idle_since_hint = int(line.split("=", 1)[1].strip())
                    except Exception:
                        idle_since_hint = None
                elif line.startswith("IdleSinceHintMonotonic="):
                    try:
                        idle_since = int(line.split("=", 1)[1].strip())
                    except Exception:
                        idle_since = None
            return idle_hint, idle_since, idle_since_hint

        def _compute_idle(idle_hint, idle_since, idle_since_hint) -> float | None:
            if idle_hint is False:
                return 0.0
            if idle_since in (None, 0) and idle_since_hint in (None, 0):
                return None
            try:
                with open("/proc/uptime", "r", encoding="utf-8") as f:
                    uptime_seconds = float(f.read().split()[0])
            except Exception:
                return None
            idle_since_value = idle_since if idle_since not in (None, 0) else idle_since_hint
            if idle_since_value in (None, 0):
                return None
            return max(0.0, (uptime_seconds * 1_000_000 - float(idle_since_value)) / 1_000_000)

        session_id = os.environ.get("XDG_SESSION_ID")
        if session_id:
            try:
                result = subprocess.run(
                    [
                        "loginctl",
                        "show-session",
                        session_id,
                        "-p",
                        "IdleHint",
                        "-p",
                        "IdleSinceHint",
                        "-p",
                        "IdleSinceHintMonotonic",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=0.6,
                )
                if result.returncode == 0:
                    idle_hint, idle_since, idle_since_hint = _parse_idle(result.stdout or "")
                    idle = _compute_idle(idle_hint, idle_since, idle_since_hint)
                    if idle is not None:
                        self._last_idle_source = "logind-session"
                        return idle
            except Exception:
                pass

        try:
            result = subprocess.run(
                [
                    "loginctl",
                    "show-user",
                    os.environ.get("USER", ""),
                    "-p",
                    "IdleHint",
                    "-p",
                    "IdleSinceHint",
                    "-p",
                    "IdleSinceHintMonotonic",
                ],
                capture_output=True,
                text=True,
                timeout=0.6,
            )
            if result.returncode == 0:
                idle_hint, idle_since, idle_since_hint = _parse_idle(result.stdout or "")
                idle = _compute_idle(idle_hint, idle_since, idle_since_hint)
                if idle is not None:
                    self._last_idle_source = "logind-user"
                    return idle
        except Exception:
            pass
        return None

    def _get_idle_seconds(self) -> float | None:
        idle_seconds = self._get_idle_seconds_hypridle()
        if idle_seconds is not None:
            self._last_idle_source = "hypridle"
            return idle_seconds
        idle_seconds = self._get_idle_seconds_logind()
        if idle_seconds is not None:
            return idle_seconds
        self._last_idle_source = "unavailable"
        return None

    def _poll_focus_activity(self) -> bool:
        if self.pomodoro_remaining <= 0:
            return False
        if self.pomodoro_paused and not self._auto_paused:
            return True
        interval = 5
        info = self._get_active_window_info()
        if info:
            self._last_focus_info = info
        idle_seconds = self._get_idle_seconds()
        self._last_idle_seconds = idle_seconds
        threshold = int(self.focus_idle_threshold or FOCUS_IDLE_THRESHOLD_SECONDS)
        idle_violation = idle_seconds is not None and idle_seconds >= threshold
        info_for_check = info or self._last_focus_info
        window_unknown = info_for_check is None
        window_ok = False if window_unknown else self._window_allowed(info_for_check)

        if window_ok and not idle_violation:
            self._focus_active_seconds += interval
            self._focus_distraction_seconds = 0
            if self._auto_paused:
                self._focus_recover_seconds += interval
            else:
                self._focus_recover_seconds = 0
        elif window_unknown and not idle_violation:
            # Avoid false pauses if window info is temporarily unavailable.
            self._focus_recover_seconds = 0
        else:
            self._focus_distract_seconds += interval
            self._focus_distraction_seconds += interval
            if idle_violation and idle_seconds is not None:
                try:
                    self._focus_distraction_seconds = max(self._focus_distraction_seconds, int(idle_seconds))
                except Exception:
                    pass
            self._focus_recover_seconds = 0

        if (
            self.focus_auto_pause_enabled
            and not self.pomodoro_paused
            and self._focus_distraction_seconds >= threshold
        ):
            self._auto_paused = True
            self._rescue_hits += 1
            self.on_pomodoro_pause(self.pomodoro_btn_pause)
            if idle_violation:
                message = f"No activity detected for {threshold} seconds."
            elif not window_ok:
                message = f"Focus window not detected for {threshold} seconds."
            else:
                message = f"Focus verification failed for {threshold} seconds."
            self.send_notification(
                "Pomodoro Auto-Paused",
                message,
            )
            self._maybe_show_rescue_prompt()
            return True

        if (
            self._auto_paused
            and self._focus_recover_seconds >= 20
            and self.pomodoro_paused
            and idle_seconds is not None
            and idle_seconds < 10
        ):
            self._auto_paused = False
            self.on_pomodoro_pause(self.pomodoro_btn_pause)
            self.send_notification(
                "Pomodoro Resumed",
                "Focus window detected again.",
            )
        self._update_focus_status_label()
        return True

    def _start_focus_tracking(self) -> None:
        self._focus_active_seconds = 0
        self._focus_distract_seconds = 0
        self._last_focus_report = None
        self._last_focus_info = None
        self._focus_distraction_seconds = 0
        self._focus_recover_seconds = 0
        self._auto_paused = False
        self._last_idle_seconds = None
        self._rescue_hits = 0
        self._rescue_prompted = False
        self._update_focus_status_label()
        if not (self.focus_tracking_enabled and self._focus_tracking_available):
            if self.focus_tracking_enabled and not self._focus_tracking_warning_shown:
                self._focus_tracking_warning_shown = True
                self.send_notification(
                    "Focus Tracking Unavailable",
                    "hyprctl not found. Install Hyprland tools to enable focus verification.",
                )
            return
        if self._focus_timer_id:
            try:
                GLib.source_remove(self._focus_timer_id)
            except Exception:
                pass
            self._focus_timer_id = None
        self._focus_timer_id = GLib.timeout_add_seconds(5, self._poll_focus_activity)

    def _format_focus_report(self) -> str | None:
        total = self._focus_active_seconds + self._focus_distract_seconds
        if total <= 0:
            return None
        active_min = self._focus_active_seconds / 60.0
        total_min = total / 60.0
        pct = (self._focus_active_seconds / total) * 100.0 if total > 0 else 0.0
        return f"Focus verified: {active_min:.1f}m / {total_min:.1f}m ({pct:.0f}%)"

    def _format_elapsed(self, seconds: float) -> str:
        total = max(0, int(seconds))
        mins, secs = divmod(total, 60)
        hrs, mins = divmod(mins, 60)
        if hrs > 0:
            return f"{hrs:d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _update_action_timer_label(self) -> None:
        label = getattr(self, "action_timer_label", None)
        if not label:
            return
        if not self._action_timer_kind:
            label.set_text("Session: —")
            return
        elapsed = float(self._action_timer_elapsed or 0.0)
        if self._action_timer_started_at is not None:
            elapsed += max(0.0, time.monotonic() - float(self._action_timer_started_at))
        kind = str(self._action_timer_kind).replace("_", " ").title()
        label.set_text(f"Session: {kind} {self._format_elapsed(elapsed)}")

    def _action_timer_tick(self) -> bool:
        if not self._action_timer_kind:
            return False
        self._update_action_timer_label()
        return True

    def _start_action_timer(self, kind: str, topic: str | None = None) -> None:
        self._stop_action_timer(finalize=True)
        self._action_timer_kind = str(kind)
        self._action_timer_topic = topic or ""
        self._action_timer_elapsed = 0.0
        self._action_timer_started_at = time.monotonic()
        self._update_action_timer_label()
        if self._action_timer_id:
            try:
                GLib.source_remove(self._action_timer_id)
            except Exception:
                pass
        self._action_timer_id = GLib.timeout_add_seconds(1, self._action_timer_tick)

    def _pause_action_timer(self) -> None:
        if not self._action_timer_kind:
            return
        if self._action_timer_started_at is None:
            return
        self._action_timer_elapsed += max(0.0, time.monotonic() - float(self._action_timer_started_at))
        self._action_timer_started_at = None
        self._update_action_timer_label()

    def _resume_action_timer(self) -> None:
        if not self._action_timer_kind:
            return
        if self._action_timer_started_at is not None:
            return
        self._action_timer_started_at = time.monotonic()
        self._update_action_timer_label()
        if not self._action_timer_id:
            self._action_timer_id = GLib.timeout_add_seconds(1, self._action_timer_tick)

    def _stop_action_timer(self, finalize: bool = True) -> None:
        if not self._action_timer_kind:
            return
        total = float(self._action_timer_elapsed or 0.0)
        if self._action_timer_started_at is not None:
            total += max(0.0, time.monotonic() - float(self._action_timer_started_at))
        if finalize:
            stats = self.action_time_log.get(self._action_timer_kind) or {"seconds": 0.0, "sessions": 0}
            stats["seconds"] = float(stats.get("seconds", 0.0) or 0.0) + total
            stats["sessions"] = int(stats.get("sessions", 0) or 0) + 1
            self.action_time_log[self._action_timer_kind] = stats
            try:
                entry = {
                    "kind": self._action_timer_kind,
                    "topic": self._action_timer_topic or "",
                    "seconds": total,
                    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                }
                self.action_time_sessions.append(entry)
                if len(self.action_time_sessions) > 200:
                    self.action_time_sessions = self.action_time_sessions[-200:]
            except Exception:
                pass
            self.save_preferences()
        self._action_timer_kind = None
        self._action_timer_topic = None
        self._action_timer_started_at = None
        self._action_timer_elapsed = 0.0
        if self._action_timer_id:
            try:
                GLib.source_remove(self._action_timer_id)
            except Exception:
                pass
            self._action_timer_id = None
        self._update_action_timer_label()

    def _update_focus_status_label(self) -> None:
        if not getattr(self, "focus_status_label", None):
            return
        report = self._format_focus_report()
        if self.pomodoro_remaining > 0:
            lines = [report or "Focus verified: 0.0m"]
            info = self._last_focus_info or {}
            app = str(info.get("app") or info.get("title") or "").strip()
            if app:
                match = self._match_allowlist_token(info)
                allowed = match is not None
                status = "allowed" if allowed else "blocked"
                lines.append(f"Active app: {app} ({status})")
                if match:
                    lines.append(f"Allowlist match: {match}")
            elif self.focus_tracking_enabled:
                lines.append("Active app: unavailable")
            if self._last_idle_seconds is None:
                if self._last_idle_source == "unavailable":
                    if self._hypridle_supported:
                        lines.append("Idle: unavailable (configure hypridle hook)")
                    else:
                        lines.append("Idle: unavailable")
            elif self._last_idle_seconds >= 5:
                idle_sec = int(self._last_idle_seconds)
                source = self._last_idle_source or "idle"
                lines.append(
                    f"Idle: {idle_sec}s (pause at {int(self.focus_idle_threshold)}s, {source})"
                )
            if self._hypridle_state_path:
                try:
                    st = os.stat(self._hypridle_state_path)
                    age = max(0, int(time.time() - st.st_mtime))
                    with open(self._hypridle_state_path, "r", encoding="utf-8") as f:
                        token = (f.read() or "").strip().lower() or "unknown"
                    lines.append(f"Hypridle: {token} (updated {age}s ago)")
                except FileNotFoundError:
                    lines.append("Hypridle: state file not found")
                except Exception:
                    lines.append("Hypridle: unavailable")
            self.focus_status_label.set_text("\n".join(lines))
        else:
            self.focus_status_label.set_text(report or "")

    # --- Action tracking helpers ---
    def _get_action_minutes_today(self) -> dict:
        action_minutes: dict[str, float] = {}
        sessions = getattr(self, "action_time_sessions", []) or []
        if not isinstance(sessions, list) or not sessions:
            return action_minutes
        today = datetime.date.today()
        for entry in sessions:
            if not isinstance(entry, dict):
                continue
            ts = entry.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(ts) if ts else None
            except Exception:
                dt = None
            if not dt or dt.date() != today:
                continue
            kind = str(entry.get("kind") or "").strip()
            if not kind:
                continue
            try:
                secs = float(entry.get("seconds", 0) or 0)
            except Exception:
                secs = 0.0
            if secs <= 0:
                continue
            action_minutes[kind] = action_minutes.get(kind, 0.0) + secs
        return action_minutes

    def _get_action_avg_minutes(self, kind: str) -> float | None:
        if not isinstance(self.action_time_log, dict):
            return None
        stats = self.action_time_log.get(kind)
        if not isinstance(stats, dict):
            return None
        try:
            secs = float(stats.get("seconds", 0) or 0)
            sessions = int(stats.get("sessions", 0) or 0)
        except Exception:
            return None
        if secs <= 0 or sessions <= 0:
            return None
        return (secs / 60.0) / sessions

    def _get_focus_integrity_weekly(self) -> float | None:
        entries = getattr(self, "focus_integrity_log", []) or []
        if not isinstance(entries, list) or not entries:
            return None
        today = datetime.date.today()
        start = today - datetime.timedelta(days=6)
        raw_total = 0.0
        verified_total = 0.0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            date_str = entry.get("date")
            try:
                date_val = datetime.date.fromisoformat(date_str) if date_str else None
            except Exception:
                date_val = None
            if not date_val or date_val < start:
                continue
            try:
                raw = float(entry.get("raw", 0) or 0)
                verified = float(entry.get("verified", 0) or 0)
            except Exception:
                continue
            if raw <= 0:
                continue
            raw_total += raw
            verified_total += min(raw, verified)
        if raw_total <= 0:
            return None
        return max(0.0, min(100.0, (verified_total / raw_total) * 100.0))

    # --- Coach signals + analytics helpers ---
    def _get_topic_time_window(
        self, days: int = 7, kinds: set[str] | None = None
    ) -> list[tuple[str, float]]:
        sessions = getattr(self, "action_time_sessions", []) or []
        if not isinstance(sessions, list):
            return []
        today = datetime.date.today()
        start = today - datetime.timedelta(days=max(1, days) - 1)
        kind_filter = set(kinds) if kinds else None
        totals: dict[str, float] = {}
        for entry in sessions:
            if not isinstance(entry, dict):
                continue
            if kind_filter:
                kind = str(entry.get("kind") or "")
                if kind not in kind_filter:
                    continue
            topic = str(entry.get("topic") or "").strip()
            if not topic:
                continue
            ts = entry.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(ts) if ts else None
            except Exception:
                dt = None
            if not dt or dt.date() < start:
                continue
            try:
                secs = float(entry.get("seconds", 0) or 0)
            except Exception:
                secs = 0.0
            if secs <= 0:
                continue
            totals[topic] = totals.get(topic, 0.0) + secs
        return sorted(totals.items(), key=lambda x: x[1], reverse=True)

    def _get_topic_saturation_today(self) -> tuple[str, float, float] | None:
        focus_kinds = {"pomodoro_focus", "pomodoro_recall"}
        totals = self._get_topic_time_window(1, kinds=focus_kinds)
        if not totals:
            return None
        total_focus_secs = sum(secs for _, secs in totals)
        thresholds = self._get_auto_thresholds()
        min_minutes = float(thresholds.get("saturation_minutes", 45.0))
        if total_focus_secs < min_minutes * 60:
            return None
        topic, top_secs = totals[0]
        if top_secs <= 0:
            return None
        saturation_pct = (top_secs / total_focus_secs) * 100.0
        min_pct = float(thresholds.get("saturation_pct", 65.0))
        if saturation_pct < min_pct:
            return None
        return topic, saturation_pct, total_focus_secs / 60.0

    def _get_topic_mastery_pct(self, topic: str | None, min_total: int = 0) -> float | None:
        if not topic:
            return None
        try:
            stats = self.engine.get_mastery_stats(topic)
        except Exception:
            return None
        if not isinstance(stats, dict):
            return None
        total = stats.get("total")
        if total is None:
            total = stats.get("total_cards", 0)
        try:
            total = int(total or 0)
        except Exception:
            total = 0
        if total <= 0 or total < max(0, int(min_total or 0)):
            return None
        try:
            mastered = int(stats.get("mastered", 0) or 0)
        except Exception:
            mastered = 0
        return max(0.0, min(100.0, (mastered / total) * 100.0))

    def _get_confidence_drift_note(self, topic: str | None) -> str | None:
        if not topic:
            return None
        try:
            competence_pct = float(self.engine.competence.get(topic, 0) or 0)
        except Exception:
            competence_pct = 0.0
        mastery_pct = self._get_topic_mastery_pct(topic, min_total=20)
        if mastery_pct is not None and competence_pct >= 80 and mastery_pct <= 20:
            return (
                f"Retention gap: {topic} competence {competence_pct:.0f}% vs mastery {mastery_pct:.0f}%."
            )
        try:
            last_import = getattr(self, "last_hub_import_date", None)
            if not last_import:
                return None
            try:
                last_date = datetime.date.fromisoformat(str(last_import))
            except Exception:
                return None
            thresholds = self._get_auto_thresholds()
            lag_days = float(thresholds.get("quiz_lag_days", 14.0))
            if (datetime.date.today() - last_date).days > lag_days:
                return None
            hub = getattr(self.engine, "study_hub_stats", {}) or {}
            quiz_scores = hub.get("quiz_scores", {}) if isinstance(hub, dict) else {}
            if isinstance(quiz_scores, dict) and topic in quiz_scores:
                quiz_score = float(quiz_scores.get(topic) or 0)
                if competence_pct - quiz_score >= 20:
                    return (
                        f"Quiz lag: {topic} quiz {quiz_score:.0f}% vs competence {competence_pct:.0f}%."
                    )
        except Exception:
            pass
        return None

    def _get_daily_summary_lines(
        self, recommended_topic: str | None, weak_chapter: str | None
    ) -> list[str]:
        lines: list[str] = []
        today_topics = self._get_topic_time_window(1)
        if today_topics:
            topic, seconds_spent = today_topics[0]
            minutes_spent = seconds_spent / 60.0
            lines.append(f"Most time on: {topic} ({minutes_spent:.0f}m)")
        else:
            lines.append("Most time on: —")

        gap_note = self._get_confidence_drift_note(recommended_topic)
        if gap_note:
            lines.append(f"Biggest gap: {gap_note}")
            return lines

        if weak_chapter:
            try:
                comp = float(self.engine.competence.get(weak_chapter, 0) or 0)
            except Exception:
                comp = 0.0
            lines.append(f"Biggest gap: {weak_chapter} ({comp:.0f}% competence)")
        else:
            lines.append("Biggest gap: —")
        return lines

    # --- Retrieval gating ---
    def _get_daily_minutes_window(self, days: int = 7) -> list[float]:
        sessions = getattr(self, "action_time_sessions", []) or []
        if not isinstance(sessions, list):
            return []
        today = datetime.date.today()
        start = today - datetime.timedelta(days=max(1, days) - 1)
        totals: dict[datetime.date, float] = {}
        for entry in sessions:
            if not isinstance(entry, dict):
                continue
            ts = entry.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(ts) if ts else None
            except Exception:
                dt = None
            if not dt:
                continue
            day = dt.date()
            if day < start:
                continue
            try:
                secs = float(entry.get("seconds", 0) or 0)
            except Exception:
                secs = 0.0
            if secs <= 0:
                continue
            totals[day] = totals.get(day, 0.0) + secs
        return [totals[d] / 60.0 for d in sorted(totals.keys())]

    def _get_smart_review_day(self, days: int = 21) -> int | None:
        sessions = getattr(self, "action_time_sessions", []) or []
        if not isinstance(sessions, list) or not sessions:
            return None
        today = datetime.date.today()
        start = today - datetime.timedelta(days=max(1, days) - 1)
        totals_by_day = {i: 0.0 for i in range(7)}
        days_with_data: dict[int, set[datetime.date]] = {i: set() for i in range(7)}
        for entry in sessions:
            if not isinstance(entry, dict):
                continue
            ts = entry.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(ts) if ts else None
            except Exception:
                dt = None
            if not dt:
                continue
            day = dt.date()
            if day < start:
                continue
            try:
                secs = float(entry.get("seconds", 0) or 0)
            except Exception:
                secs = 0.0
            if secs <= 0:
                continue
            dow = day.weekday()
            totals_by_day[dow] += secs
            days_with_data[dow].add(day)

        scored = []
        for dow in range(7):
            count_days = len(days_with_data[dow])
            if count_days == 0:
                continue
            avg_minutes = (totals_by_day[dow] / 60.0) / max(1, count_days)
            scored.append((avg_minutes, count_days, dow))
        if not scored:
            return None
        # Prefer the lowest average with at least 2 data points if possible.
        scored.sort(key=lambda x: (x[0], -x[1]))
        best = next((d for d in scored if d[1] >= 2), scored[0])
        return best[2]

    def _get_recent_session_quality_stats(self, days: int = 7) -> dict[str, int]:
        stats = {"good": 0, "okay": 0, "low": 0, "total": 0}
        entries = getattr(self, "session_quality_log", []) or []
        if not isinstance(entries, list):
            return stats
        today = datetime.date.today()
        start = today - datetime.timedelta(days=max(1, days) - 1)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            date_str = entry.get("date")
            try:
                date_val = datetime.date.fromisoformat(date_str) if date_str else None
            except Exception:
                date_val = None
            if not date_val or date_val < start:
                continue
            quality = str(entry.get("quality") or "").lower()
            if quality in ("good", "okay", "low"):
                stats[quality] += 1
                stats["total"] += 1
        return stats

    def _get_auto_thresholds(self) -> dict[str, float]:
        retrieval_min = 25.0
        quiz_lag_days = 14.0
        saturation_pct = 65.0
        saturation_minutes = 45.0

        try:
            days = self.engine.get_days_remaining()
        except Exception:
            days = None
        if isinstance(days, int):
            if days <= 14:
                retrieval_min = 35.0
                quiz_lag_days = 7.0
                saturation_pct = 60.0
                saturation_minutes = 30.0
            elif days <= 30:
                retrieval_min = 30.0
                quiz_lag_days = 10.0

        try:
            pace_info = self.engine.get_pace_status()
        except Exception:
            pace_info = {}
        try:
            pace_status = pace_info.get("status", "unknown")
            pace_delta = float(pace_info.get("delta", 0) or 0)
        except Exception:
            pace_status = "unknown"
            pace_delta = 0.0
        if pace_status == "behind" or pace_delta > 5:
            retrieval_min += 5.0
            saturation_pct = max(50.0, saturation_pct - 5.0)
            saturation_minutes = max(30.0, saturation_minutes - 10.0)
        elif pace_status == "ahead":
            retrieval_min = max(20.0, retrieval_min - 5.0)
            saturation_pct = min(75.0, saturation_pct + 5.0)
            saturation_minutes = min(75.0, saturation_minutes + 10.0)

        weekly_integrity = self._get_focus_integrity_weekly()
        quality = self._get_recent_session_quality_stats()
        low_ratio = (quality["low"] / quality["total"]) if quality["total"] else 0.0
        if (weekly_integrity is not None and weekly_integrity < 70) or low_ratio >= 0.4:
            retrieval_min = max(20.0, retrieval_min - 5.0)
            saturation_pct = min(75.0, saturation_pct + 5.0)
            saturation_minutes = min(90.0, saturation_minutes + 15.0)

        minutes_window = self._get_daily_minutes_window(7)
        if len(minutes_window) >= 3:
            avg = sum(minutes_window) / len(minutes_window)
            if avg > 0:
                var = sum((m - avg) ** 2 for m in minutes_window) / len(minutes_window)
                cv = (var ** 0.5) / avg if avg else 0.0
                if cv > 0.6:
                    saturation_minutes = min(90.0, saturation_minutes + 10.0)

        return {
            "retrieval_min_pct": max(20.0, min(45.0, retrieval_min)),
            "quiz_lag_days": max(5.0, min(21.0, quiz_lag_days)),
            "saturation_pct": max(50.0, min(80.0, saturation_pct)),
            "saturation_minutes": max(20.0, min(90.0, saturation_minutes)),
        }

    def _get_retrieval_min_pct(self) -> float:
        return float(self._get_auto_thresholds().get("retrieval_min_pct", 25.0))

    def _get_retrieval_ratio_today(self) -> float | None:
        action_minutes = self._get_action_minutes_today()
        if not action_minutes:
            return None
        focus_minutes = action_minutes.get("pomodoro_focus", 0.0)
        retrieval_minutes = (
            action_minutes.get("pomodoro_recall", 0.0)
            + action_minutes.get("quiz", 0.0)
            + action_minutes.get("drill", 0.0)
            + action_minutes.get("review", 0.0)
        )
        total_minutes = focus_minutes + retrieval_minutes
        if total_minutes < 900:  # require at least 15m tracked
            return None
        return (retrieval_minutes / total_minutes) * 100.0

    def _should_force_retrieval(self) -> bool:
        try:
            if not self._has_chapters():
                return False
            questions = self.engine.get_questions(self.current_topic or self._get_recommended_topic())
            if not questions:
                return False
        except Exception:
            return False
        try:
            now = datetime.datetime.now()
            if now.hour < 12:
                return False
        except Exception:
            return False
        retrieval_pct = self._get_retrieval_ratio_today()
        if retrieval_pct is None:
            return False
        return retrieval_pct < self._get_retrieval_min_pct()

    def _enforce_retrieval_gate(self) -> bool:
        if not self._should_force_retrieval():
            return True
        try:
            retrieval_pct = self._get_retrieval_ratio_today()
            target_pct = self._get_retrieval_min_pct()
        except Exception:
            retrieval_pct = None
            target_pct = None
        msg = "Retrieval block required to stay exam-ready."
        if retrieval_pct is not None and target_pct is not None:
            msg = f"Retrieval at {retrieval_pct:.0f}% (target {target_pct:.0f}%). Do a quiz block now."
        dialog = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Retrieval Required",
            secondary_text=msg,
        )
        dialog.add_button("Start Quiz", Gtk.ResponseType.OK)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        def _on_resp(d, r):
            d.destroy()
            if r == Gtk.ResponseType.OK:
                self.on_quick_quiz(self.quiz_btn)
        dialog.connect("response", _on_resp)
        dialog.present()
        return False

    def _get_next_block_kind(self) -> str:
        try:
            days_remaining = self.engine.get_days_remaining()
            weak = self._get_weak_chapter(60.0)
            if isinstance(days_remaining, int) and days_remaining <= 14 and not weak:
                return "Recall"
        except Exception:
            pass
        try:
            if isinstance(self.engine.exam_date, datetime.date) and self.engine.has_availability():
                schedule = self.engine.generate_study_schedule(days=1)
                if schedule:
                    blocks = schedule[0].get("blocks", []) or []
                    if blocks:
                        return str(blocks[0].get("kind", "Focus"))
        except Exception:
            pass
        return "Focus"

    def _count_action_sessions_today(self, kind: str, topic: str | None = None) -> int:
        sessions = getattr(self, "action_time_sessions", []) or []
        if not isinstance(sessions, list):
            return 0
        today = datetime.date.today()
        count = 0
        for entry in sessions:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("kind", "")) != kind:
                continue
            if topic and str(entry.get("topic", "")) != topic:
                continue
            ts = entry.get("timestamp")
            try:
                dt = datetime.datetime.fromisoformat(ts) if ts else None
            except Exception:
                dt = None
            if not dt or dt.date() != today:
                continue
            count += 1
        return count

    def _maybe_prompt_recall_block(self, topic: str | None) -> None:
        if not topic:
            return
        today_iso = datetime.date.today().isoformat()
        if self._recall_prompted_date == today_iso and self._recall_prompted_topic == topic:
            return
        focus_poms = self._count_action_sessions_today("pomodoro_focus", topic=topic)
        recall_poms = self._count_action_sessions_today("pomodoro_recall", topic=topic)
        if focus_poms < 2 or recall_poms >= 1:
            return
        self._recall_prompted_date = today_iso
        self._recall_prompted_topic = topic
        dialog = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Recall Block Due",
            secondary_text=f"Two focus blocks completed on {topic}. Start a 10‑minute recall block?",
        )
        dialog.add_button("Start Recall", Gtk.ResponseType.OK)
        dialog.add_button("Later", Gtk.ResponseType.CANCEL)
        def _on_resp(d, r):
            d.destroy()
            if r == Gtk.ResponseType.OK:
                self._stop_break_timer()
                self._begin_pomodoro(10, "pomodoro_recall")
        dialog.connect("response", _on_resp)
        dialog.present()

    def _begin_pomodoro(self, minutes: int, kind: str) -> None:
        self._pomodoro_target_minutes = max(1, int(minutes))
        self._pomodoro_kind = kind
        self._current_coach_pick_at_start = self._get_recommended_topic()
        self._log_coach_contract(self.current_topic or self._current_coach_pick_at_start or "Unknown", minutes)
        self.send_notification(
            "Coach Contract",
            f"I will finish {minutes} minutes on {self.current_topic or self._current_coach_pick_at_start}.",
        )
        self.pomodoro_remaining = self._pomodoro_target_minutes * 60
        self._pomodoro_notified: set[int] = set()
        self.update_pomodoro_timer_label()
        self.pomodoro_timer_id = GLib.timeout_add_seconds(1, self.pomodoro_tick)
        self._set_pomodoro_active_state(True)
        self._start_focus_tracking()
        self._start_action_timer(kind, topic=self.current_topic)
        self.pomodoro_btn_pause.set_sensitive(True)
        self.pomodoro_btn_stop.set_sensitive(True)
        self.pomodoro_btn_start.set_sensitive(False)
        self.send_notification("Pomodoro Started", "Focus on your study!")

    def _set_session_recap(self, title: str, lines: list[str]) -> None:
        if not lines:
            return
        try:
            when = datetime.datetime.now().strftime("%H:%M")
        except Exception:
            when = ""
        self._last_session_recap = {
            "title": str(title),
            "lines": list(lines),
            "when": when,
        }

    def _is_completed_today(self, chapter: str) -> bool:
        try:
            if hasattr(self.engine, "is_completed_today"):
                return bool(self.engine.is_completed_today(chapter))
            return bool(self.engine.is_completed(chapter))
        except Exception:
            return False

    def _auto_advance_daily_focus(self, completed_topic: str | None) -> None:
        if not completed_topic:
            return
        daily_plan = getattr(self, "_last_daily_plan", None) or []
        if not daily_plan:
            try:
                daily_plan = self.engine.get_daily_plan(num_topics=3, current_topic=self.current_topic) or []
            except Exception:
                daily_plan = []
        if not daily_plan or completed_topic not in daily_plan:
            return
        try:
            idx = daily_plan.index(completed_topic)
        except ValueError:
            return
        for next_ch in daily_plan[idx + 1:]:
            if not self._is_completed_today(next_ch):
                try:
                    self._set_current_topic(next_ch)
                except Exception:
                    pass
                return

    def _update_coach_pick_card(self) -> None:
        if not getattr(self, "coach_pick_label", None):
            return
        if not self._has_chapters():
            self.coach_pick_label.set_text("Coach pick: N/A")
            return
        topic = self._get_recommended_topic()
        if not topic:
            self.coach_pick_label.set_text("Coach pick: —")
            return
        today = datetime.date.today()
        reasons = []
        try:
            weak = self._get_weak_chapter(60.0)
            if weak and weak == topic:
                reasons.append("weak area <60%")
        except Exception:
            pass
        try:
            must_due = self._get_must_review_due_count(today)
            if must_due:
                reasons.append(f"{must_due} must-review due")
        except Exception:
            pass
        try:
            due_count = self._get_topic_due_count(topic, today)
            if due_count:
                reasons.append(f"{due_count} reviews due")
        except Exception:
            pass
        try:
            comp = getattr(self.engine, "competence", {}) or {}
            if isinstance(comp, dict):
                val = float(comp.get(topic, 0) or 0)
                if val < 70:
                    reasons.append(f"competence {val:.0f}%")
        except Exception:
            pass
        try:
            pace = self._get_pace_info().get("status")
            if pace == "behind":
                reasons.append("pace behind")
        except Exception:
            pass
        if not reasons:
            reasons.append("highest urgency overall")
        reason_text = ", ".join(reasons[:3])
        self.coach_pick_label.set_text(f"Coach pick: {topic}\nFocus reason: {reason_text}")
        try:
            if getattr(self, "coach_pick_why_label", None):
                self.coach_pick_why_label.set_text(f"Reason: {reason_text}")
        except Exception:
            pass
        try:
            history = getattr(self, "coach_reason_history", []) or []
            history.append(f"{datetime.date.today().isoformat()}: {reason_text}")
            self.coach_reason_history = history[-3:]
            self.save_preferences()
            if getattr(self, "coach_pick_why_history", None):
                self.coach_pick_why_history.set_text("Recent reasons:\n" + "\n".join(self.coach_reason_history))
        except Exception:
            pass
        try:
            today_iso = datetime.date.today().isoformat()
            if self.last_coach_pick != topic or self.last_coach_pick_date != today_iso:
                self.last_coach_pick = topic
                self.last_coach_pick_date = today_iso
                self.save_preferences()
        except Exception:
            pass
        try:
            comp = getattr(self.engine, "competence", {}) or {}
            comp_val = float(comp.get(topic, 0) or 0)
        except Exception:
            comp_val = 0.0
        try:
            due = self._get_topic_due_count(topic, today)
        except Exception:
            due = 0
        try:
            pace_info = self._get_pace_info()
            pace_status = pace_info.get("status", "unknown")
            pace_delta = float(pace_info.get("delta", 0) or 0)
        except Exception:
            pace_status = "unknown"
            pace_delta = 0.0
        tooltip_parts = [
            f"Competence: {comp_val:.0f}%",
            f"Reviews due: {int(due)}",
            f"Pace: {pace_status}",
        ]
        if pace_status == "behind":
            tooltip_parts.append(f"Delta: +{pace_delta:.0f} min/day")
            tip = self._format_pace_micro_target(pace_delta)
            if tip:
                tooltip_parts.append(f"Coach tip: {tip}")
        self.coach_pick_label.set_tooltip_text("\n".join(tooltip_parts))
        self._coach_pick_topic = topic
        try:
            verified = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
        except Exception:
            verified = 0.0
        if getattr(self, "verified_minutes_badge", None):
            self.verified_minutes_badge.set_text(f"Verified today: {verified:.0f}m")
            try:
                self.verified_minutes_badge.remove_css_class("badge-locked")
            except Exception:
                pass
            if verified <= 0:
                self.verified_minutes_badge.add_css_class("badge-locked")
        if self.coach_only_view:
            self._apply_coach_only_mode()

    def on_focus_coach_pick(self, _btn):
        topic = getattr(self, "_coach_pick_topic", "") or self._get_recommended_topic()
        if topic:
            try:
                self._set_current_topic(topic)
            except Exception:
                pass

    def on_do_coach_next(self, _btn):
        self._ensure_coach_selection()
        if not self._ensure_chapters_ready("Coach Next"):
            return
        topic = getattr(self, "_coach_pick_topic", "") or self._get_recommended_topic()
        if topic:
            try:
                self._set_current_topic(topic)
            except Exception:
                pass
        questions = []
        try:
            questions = self.engine.get_questions(self.current_topic)
        except Exception:
            questions = []
        if self._should_force_retrieval() and questions:
            self.start_quiz_session(topic=self.current_topic, kind="quiz")
            return
        self.on_pomodoro_start(None)

    def on_toggle_coach_only(self, btn):
        try:
            self.coach_only_view = bool(btn.get_active())
        except Exception:
            self.coach_only_view = not self.coach_only_view
        if getattr(self, "plan_scroll", None):
            self.plan_scroll.set_visible(not self.coach_only_view)
        if getattr(self, "plan_hint", None):
            self.plan_hint.set_visible(bool(self.coach_only_view))
        if getattr(self, "coach_only_badge", None):
            self.coach_only_badge.set_visible(bool(self.coach_only_view))
        if getattr(self, "coach_only_toggle", None):
            self.coach_only_toggle.set_visible(not self.coach_only_view)
            if self.coach_only_view:
                self.coach_only_toggle.set_active(True)
            else:
                self.coach_only_toggle.set_active(False)
        self._apply_coach_only_mode()
        self.save_preferences()

    def _exit_coach_only_from_badge(self):
        self.coach_only_view = False
        if getattr(self, "plan_scroll", None):
            self.plan_scroll.set_visible(True)
        if getattr(self, "plan_hint", None):
            self.plan_hint.set_visible(False)
        if getattr(self, "coach_only_badge", None):
            self.coach_only_badge.set_visible(False)
        if getattr(self, "coach_only_toggle", None):
            self.coach_only_toggle.set_visible(True)
            self.coach_only_toggle.set_active(False)
        self.save_preferences()
        self._animate_coach_badge()
        self._apply_coach_only_mode()

    def _apply_coach_only_mode(self):
        combo = getattr(self, "topic_combo", None)
        if combo:
            combo.set_sensitive(not self.coach_only_view)
        if not self.coach_only_view:
            return
        topic = getattr(self, "_coach_pick_topic", "") or self._get_recommended_topic()
        if topic and topic != self.current_topic:
            self._set_current_topic(topic)

    def _ensure_coach_selection(self):
        if not self.coach_only_view:
            return
        topic = getattr(self, "_coach_pick_topic", "") or self._get_recommended_topic()
        if topic and topic != self.current_topic:
            self._set_current_topic(topic)

    def _focus_coach_pick_if_needed(self):
        if not getattr(self, "coach_only_view", False):
            return
        topic = getattr(self, "_coach_pick_topic", "") or self._get_recommended_topic()
        if not topic or topic == self.current_topic:
            return
        try:
            self._set_current_topic(topic)
        except Exception:
            pass

    def _animate_coach_badge(self):
        badge = getattr(self, "coach_only_badge", None)
        if not badge:
            return
        badge.add_css_class("badge-highlight")
        if self._badge_highlight_id:
            try:
                GLib.source_remove(self._badge_highlight_id)
            except Exception:
                pass
        def _clear(_source=None):
            if badge:
                badge.remove_css_class("badge-highlight")
            self._badge_highlight_id = None
            return False
        self._badge_highlight_id = GLib.timeout_add_seconds(1, _clear)

    def _maybe_prompt_reflection(self, topic: str | None, context: str = "") -> None:
        if not topic:
            return
        today_iso = datetime.date.today().isoformat()
        if self.last_reflection_date == today_iso:
            return
        if not isinstance(getattr(self.engine, "chapter_notes", None), dict):
            self.engine.chapter_notes = {}
        dialog = self._new_dialog(title="Quick Reflection", transient_for=self, modal=True)
        dialog.add_buttons("_Skip", Gtk.ResponseType.CANCEL, "_Save", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_spacing(8)
        subtitle = f"Topic: {topic}"
        if context:
            subtitle = f"{subtitle} • {context}"
        info = Gtk.Label(
            label=f"{subtitle}\nWhat was clear, what was confusing, and what is your next step?"
        )
        info.set_halign(Gtk.Align.START)
        info.set_wrap(True)
        info.add_css_class("muted")
        content.append(info)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(120)
        textview = Gtk.TextView()
        buffer = textview.get_buffer()
        scroller.set_child(textview)
        content.append(scroller)

        def _on_resp(_d, resp):
            _d.destroy()
            if resp != Gtk.ResponseType.OK:
                self.last_reflection_date = today_iso
                self.save_preferences()
                return
            start, end = buffer.get_bounds()
            text = buffer.get_text(start, end, True).strip()
            if not text:
                self.last_reflection_date = today_iso
                self.save_preferences()
                return
            try:
                notes = getattr(self.engine, "chapter_notes", {}) or {}
                if not isinstance(notes, dict):
                    notes = {}
                entry = notes.get(topic, {}) if isinstance(notes.get(topic), dict) else {}
                entry["reflection"] = text
                entry["updated"] = today_iso
                notes[topic] = entry
                self.engine.chapter_notes = notes
                self.engine.save_data()
            except Exception:
                pass
            self.last_reflection_date = today_iso
            self.save_preferences()
            self.update_dashboard()
            self.update_study_room_card()

        dialog.connect("response", _on_resp)
        dialog.present()

    def _prompt_session_quality(self, topic: str | None, minutes: float, kind: str = "pomodoro") -> None:
        if not topic or minutes <= 0:
            return
        dialog = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Session quality?",
            secondary_text="One quick tap helps calibrate your plan.",
        )
        dialog.add_button("Good", Gtk.ResponseType.OK)
        dialog.add_button("Okay", Gtk.ResponseType.APPLY)
        dialog.add_button("Low", Gtk.ResponseType.REJECT)
        dialog.add_button("Skip", Gtk.ResponseType.CANCEL)
        def _on_resp(d, r):
            d.destroy()
            if r == Gtk.ResponseType.CANCEL:
                return
            label = None
            if r == Gtk.ResponseType.OK:
                label = "good"
            elif r == Gtk.ResponseType.APPLY:
                label = "okay"
            elif r == Gtk.ResponseType.REJECT:
                label = "low"
            if not label:
                return
            try:
                entry = {
                    "date": datetime.date.today().isoformat(),
                    "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                    "topic": topic,
                    "minutes": float(minutes),
                    "kind": kind,
                    "quality": label,
                }
                self.session_quality_log.append(entry)
                if len(self.session_quality_log) > 200:
                    self.session_quality_log = self.session_quality_log[-200:]
                self.save_preferences()
            except Exception:
                pass
        dialog.connect("response", _on_resp)
        dialog.present()

    def _get_confidence_note(self, topic: str | None) -> str:
        if not topic:
            return ""
        try:
            notes = getattr(self.engine, "chapter_notes", {}) or {}
            entry = notes.get(topic)
            if isinstance(entry, dict):
                note = entry.get("note", "") or ""
                return note.strip()
        except Exception:
            pass
        return ""

    def _maybe_notify_confidence_delta(self, topic: str | None, new_score: float) -> None:
        if not topic:
            return
        try:
            notes = getattr(self.engine, "chapter_notes", {}) or {}
            if not isinstance(notes, dict):
                return
            entry = notes.get(topic)
            if not isinstance(entry, dict):
                return
            if entry.get("note_quiz_improved"):
                return
            baseline = entry.get("note_quiz_score")
            if baseline is None:
                return
            try:
                baseline = float(baseline)
            except Exception:
                return
            diff = float(new_score) - baseline
            if diff < 10:
                return
            entry["note_quiz_improved"] = True
            notes[topic] = entry
            self.engine.chapter_notes = notes
            self.engine.save_data()
            self.send_notification(
                "Confidence Delta",
                f"{topic}: +{diff:.0f}% since your confidence note.",
            )
        except Exception:
            pass

    def _stop_focus_tracking(self) -> str | None:
        if self._focus_timer_id:
            try:
                GLib.source_remove(self._focus_timer_id)
            except Exception:
                pass
            self._focus_timer_id = None
        report = self._format_focus_report()
        if report:
            self._last_focus_report = report
        self._update_focus_status_label()
        return report

    def update_daily_quests_display(self) -> None:
        if not getattr(self, "quest_rows", None):
            return
        try:
            pace_info = self._get_pace_info()
            pace_status = pace_info.get("status", "unknown") if isinstance(pace_info, dict) else "unknown"
        except Exception:
            pace_status = "unknown"
        def _scaled_target(key: str, base: int) -> int:
            target = int(base)
            if pace_status == "behind":
                if key == "pomodoro":
                    target += 1
                elif key == "quiz_questions":
                    target += 4
            elif pace_status == "ahead":
                if key == "pomodoro":
                    target = max(1, target - 1)
                elif key == "quiz_questions":
                    target = max(6, target - 2)
            return max(1, target)
        self._ensure_daily_counters()
        today = datetime.date.today().isoformat()
        completed = True
        quest_values = {
            "pomodoro": int(self.pomodoro_today_count),
            "quiz_questions": int(self.quiz_questions_today),
            "quiz_sessions": int(self.quiz_sessions_today),
        }
        for key, row in self.quest_rows.items():
            target = _scaled_target(key, int(row.get("target", 1)))
            value = int(quest_values.get(key, 0))
            progress = min(1.0, value / max(1, target))
            label = row.get("label")
            bar = row.get("progress")
            if label:
                label.set_text(f"{label.get_text().split(' (')[0]} ({value}/{target})")
            if bar:
                bar.set_fraction(progress)
                bar.set_text(f"{int(progress * 100)}%")
            if value < target:
                completed = False
        if completed and self.last_quest_date != today:
            self.last_quest_date = today
            self._unlock_achievement("daily_quests", "Daily Hero", "Completed all daily quests today!")
            self.award_xp(15, "daily_quests")
        if getattr(self, "quest_reward_label", None):
            if completed:
                self.quest_reward_label.set_text("Daily quests completed — reward claimed.")
            else:
                self.quest_reward_label.set_text("Complete all daily quests for +15 XP.")
        self.save_preferences()

    def _update_risk_manager_progress(self) -> None:
        """Track rapid improvements on weak chapters for Risk Manager badge."""
        if not isinstance(getattr(self, "risk_baselines", None), dict):
            self.risk_baselines = {}
        comp = getattr(self.engine, "competence", {})
        if not isinstance(comp, dict):
            return
        today = datetime.date.today()
        threshold = 60.0
        changed = False
        to_remove = []
        for chapter, raw_score in comp.items():
            try:
                score = float(raw_score or 0)
            except Exception:
                continue
            baseline = self.risk_baselines.get(chapter)
            if score < threshold:
                if not isinstance(baseline, dict):
                    self.risk_baselines[chapter] = {"date": today.isoformat(), "score": score}
                    changed = True
                    continue
                date_str = baseline.get("date")
                base_score = baseline.get("score", score)
                try:
                    base_score = float(base_score)
                except Exception:
                    base_score = score
                try:
                    base_date = datetime.date.fromisoformat(date_str) if date_str else None
                except Exception:
                    base_date = None
                if base_date is None:
                    self.risk_baselines[chapter] = {"date": today.isoformat(), "score": score}
                    changed = True
                    continue
                days = (today - base_date).days
                if days > 7:
                    self.risk_baselines[chapter] = {"date": today.isoformat(), "score": score}
                    changed = True
                    continue
                if score >= base_score + 15:
                    self._unlock_achievement("risk_manager", "Risk Manager", f"Improved {chapter} by 15% in a week.")
                    self.award_xp(25, "risk_manager")
                    to_remove.append(chapter)
                    changed = True
            else:
                if chapter in self.risk_baselines:
                    to_remove.append(chapter)
                    changed = True
        for ch in to_remove:
            self.risk_baselines.pop(ch, None)
        if changed:
            self.save_preferences()

    def _increment_quiz_questions_today(self, count: int = 1) -> None:
        if count <= 0:
            return
        self._ensure_daily_counters()
        self.quiz_questions_today += int(count)
        self.update_daily_quests_display()

    def _increment_quiz_sessions_today(self, count: int = 1) -> None:
        if count <= 0:
            return
        self._ensure_daily_counters()
        self.quiz_sessions_today += int(count)
        self.update_daily_quests_display()

    def _badge_title_for(self, key: str) -> str:
        badges = {
            "pomodoro_first": "First Pomodoro",
            "pomodoro_4": "Focus Marathon",
            "pomodoro_8": "Deep Work",
            "quiz_first": "Quiz Starter",
            "quiz_10": "Quiz Runner",
            "quiz_50": "Quiz Master",
            "quiz_perfect": "Perfect Quiz",
            "quiz_sharpshooter": "Quiz Sharpshooter",
            "perfect_10": "Perfect 10",
            "risk_manager": "Risk Manager",
            "daily_quests": "Daily Hero",
            "streak_3": "Streak Starter",
            "streak_7": "One Week",
            "streak_14": "Two Weeks",
            "streak_30": "30-Day Streak",
        }
        if key.startswith("level_"):
            return f"Level {key.split('_', 1)[1]}"
        return badges.get(key, key.replace("_", " ").title())

    def update_badges_display(self) -> None:
        if not getattr(self, "badge_flow", None):
            return
        child = self.badge_flow.get_first_child()
        while child:
            self.badge_flow.remove(child)
            child = self.badge_flow.get_first_child()

        has_any = False
        achievements = set(self.achievements or [])
        for key, title, requirement in ALL_BADGES:
            unlocked = key in achievements
            label_text = title if unlocked else f"🔒 {title}"
            label = Gtk.Label(label=label_text)
            label.set_tooltip_text(requirement)
            label.add_css_class("badge" if unlocked else "badge-locked")
            self.badge_flow.append(label)
            has_any = True

        # Also show level badges
        for key in sorted(achievements):
            if key.startswith("level_"):
                label = Gtk.Label(label=self._badge_title_for(key))
                label.add_css_class("badge")
                self.badge_flow.append(label)
                has_any = True

        if not has_any:
            empty = Gtk.Label(label="No badges yet — keep going!")
            empty.set_halign(Gtk.Align.START)
            empty.add_css_class("muted")
            self.badge_flow.append(empty)

    def award_xp(self, points: int, reason: str = "") -> None:
        if points <= 0:
            return
        multiplier = self._get_xp_multiplier()
        adjusted = int(round(points * multiplier))
        if adjusted <= 0:
            adjusted = points
        self.xp_total = max(0, int(self.xp_total) + int(adjusted))
        new_level = 1 + (self.xp_total // 100)
        if new_level > self.level:
            self.level = new_level
            self.send_notification("Level Up!", f"You reached Level {self.level}. Keep it up!")
            self._unlock_achievement(f"level_{self.level}", "Level Up!", f"Level {self.level} achieved.")
        self.update_xp_display()
        self.save_preferences()

    def _unlock_achievement(self, key: str, title: str, message: str) -> None:
        if key in self.achievements:
            return
        self.achievements.add(key)
        self.send_notification(title, message)
        self.update_badges_display()
        self.save_preferences()

    def _award_pomodoro_xp(self, credited_minutes: float) -> dict:
        today = datetime.date.today().isoformat()
        if self.last_pomodoro_date != today:
            self.last_pomodoro_date = today
            self.pomodoro_today_count = 0
            self.short_pomodoro_today_count = 0

        if credited_minutes < MIN_POMODORO_CREDIT_MINUTES:
            result = {"counted": False, "short_counted": False, "xp": 0}
            if credited_minutes > 0 and self.short_pomodoro_today_count < MAX_SHORT_POMODOROS_PER_DAY:
                self.short_pomodoro_today_count += 1
                self.award_xp(SHORT_POMODORO_XP, "pomodoro_short")
                result["short_counted"] = True
                result["xp"] = SHORT_POMODORO_XP
            self.save_preferences()
            return result

        self.pomodoro_today_count += 1
        self.save_preferences()

        points = 10 if credited_minutes >= 25 else max(2, int(credited_minutes // 5) * 2)
        self.award_xp(points, "pomodoro")

        if self.pomodoro_today_count == 1:
            self._unlock_achievement("pomodoro_first", "First Pomodoro", "Great start! First focus session done.")
        if self.pomodoro_today_count == 4:
            self._unlock_achievement("pomodoro_4", "Focus Marathon", "4 Pomodoros in a day!")
        if self.pomodoro_today_count == 8:
            self._unlock_achievement("pomodoro_8", "Deep Work", "8 Pomodoros in a day. Impressive!")
        self.update_daily_quests_display()
        return {"counted": True, "short_counted": False, "xp": points}

    def _check_streak_milestones(self, previous: int) -> None:
        milestones = {3: "Streak Starter", 7: "One Week Streak", 14: "Two Week Streak", 30: "30-Day Streak"}
        title = milestones.get(self.study_streak)
        if title and self.study_streak > previous:
            self._unlock_achievement(f"streak_{self.study_streak}", title, f"{self.study_streak} days in a row!")

    def _poll_window_size(self):
        """Poll window size to adapt layout; avoids Gtk4 size-allocate signal issues."""
        try:
            width = self.get_width()
            height = self.get_height()
        except Exception:
            return True
        if width <= 0 or height <= 0:
            return True
        if (width, height) != self._last_window_size:
            self._last_window_size = (width, height)
            self._handle_window_size(width, height)
        return True

    def _handle_window_size(self, width: int, height: int) -> None:
        """Adapt layout for smaller screens (e.g., 1280x1024 and below)."""
        compact = width <= 1280 or height <= 900
        if width < 980:
            if self.main_box.get_orientation() != Gtk.Orientation.VERTICAL:
                self.main_box.set_orientation(Gtk.Orientation.VERTICAL)
            # Let left panel stretch full width in vertical mode.
            self.left_panel.set_size_request(-1, -1)
            if getattr(self, "left_scroll", None):
                self.left_scroll.set_size_request(-1, -1)
                self.left_scroll.set_hexpand(True)
                self.left_scroll.set_halign(Gtk.Align.FILL)
                self.left_scroll.set_propagate_natural_width(False)
                try:
                    self.left_scroll.set_min_content_height(max(260, int(height * 0.45)))
                except Exception:
                    pass
            self.left_panel.set_hexpand(True)
            self.left_panel.set_halign(Gtk.Align.FILL)
            self.left_panel.set_vexpand(True)
        else:
            if self.main_box.get_orientation() != Gtk.Orientation.HORIZONTAL:
                self.main_box.set_orientation(Gtk.Orientation.HORIZONTAL)
            self.left_panel.set_size_request(340, -1)
            if getattr(self, "left_scroll", None):
                self.left_scroll.set_size_request(340, -1)
                self.left_scroll.set_hexpand(False)
                self.left_scroll.set_halign(Gtk.Align.START)
                self.left_scroll.set_propagate_natural_width(True)
                try:
                    self.left_scroll.set_min_content_height(0)
                except Exception:
                    pass
            self.left_panel.set_hexpand(False)
            self.left_panel.set_halign(Gtk.Align.START)
            self.left_panel.set_vexpand(False)
        self.apply_compact_mode(compact)

    def apply_compact_mode(self, compact: bool) -> None:
        if compact == self._compact_mode:
            return
        self._compact_mode = compact
        if compact:
            self.add_css_class("compact")
            self.main_box.set_margin_top(10)
            self.main_box.set_margin_bottom(10)
            self.main_box.set_margin_start(10)
            self.main_box.set_margin_end(10)
            self.left_panel.set_spacing(6)
            self.dashboard.set_spacing(8)
            self.plan_scroll.set_min_content_height(70)
            self.rec_scroll.set_min_content_height(90)
            if getattr(self, "badge_scroll", None):
                self.badge_scroll.set_min_content_height(60)
            self.availability_expander.set_expanded(False)
            self.rec_expander.set_expanded(False)
        else:
            self.remove_css_class("compact")
            self.main_box.set_margin_top(16)
            self.main_box.set_margin_bottom(16)
            self.main_box.set_margin_start(16)
            self.main_box.set_margin_end(16)
            self.left_panel.set_spacing(12)
            self.dashboard.set_spacing(12)
            self.plan_scroll.set_min_content_height(90)
            self.rec_scroll.set_min_content_height(120)
            if getattr(self, "badge_scroll", None):
                self.badge_scroll.set_min_content_height(70)
            self.availability_expander.set_expanded(True)
            self.rec_expander.set_expanded(True)

        for button, labels in self._label_variants.items():
            button.set_label(labels[1] if compact else labels[0])

    def on_topic_changed(self, combo, _pspec=None):
        try:
            idx = combo.get_selected()
        except Exception:
            return
        if idx is None or idx < 0:
            return
        try:
            item = combo.get_selected_item()
            topic = item.get_string() if item else None
        except Exception:
            topic = None
        if not topic:
            try:
                topic = self.engine.CHAPTERS[idx]
            except Exception:
                return
        self.current_topic = topic
        self.update_study_room_card()

    def _set_current_topic(self, topic: str) -> None:
        if topic not in self.engine.CHAPTERS:
            return
        self.current_topic = topic
        try:
            idx = self.engine.CHAPTERS.index(topic)
            self.topic_combo.set_selected(idx)
        except Exception:
            pass
        self.update_study_room_card()

    def _should_override_sticky_coach_pick(self, topic: str) -> bool:
        try:
            daily_poms = int(self.daily_pomodoros_by_chapter.get(topic, 0) or 0)
        except Exception:
            daily_poms = 0
        recall_credit = 0
        if getattr(self, "recall_counts_for_release", False):
            try:
                recall_credit = 1 if int(self.daily_recall_by_chapter.get(topic, 0) or 0) >= 1 else 0
            except Exception:
                recall_credit = 0
        try:
            quiz_results = getattr(self.engine, "quiz_results", {}) or {}
            last_quiz = float(quiz_results.get(topic, 0) or 0) if isinstance(quiz_results, dict) else 0.0
        except Exception:
            last_quiz = 0.0
        effective_poms = daily_poms + recall_credit
        if effective_poms >= 3 and last_quiz >= 80:
            return True
        try:
            today = datetime.date.today()
            must_due = self._get_must_review_due_count(today)
            if must_due > 0:
                return True
        except Exception:
            pass
        try:
            weak = self._get_weak_chapter(60.0)
            if weak and weak != topic:
                return True
        except Exception:
            pass
        return False

    def _get_recommended_topic(self) -> str:
        if not self._has_chapters():
            return ""
        plan = []
        try:
            plan = list(getattr(self, "_last_daily_plan", None) or [])
        except Exception:
            plan = []
        if not plan:
            try:
                plan = self.engine.get_daily_plan(num_topics=3, current_topic=self.current_topic) or []
            except Exception:
                plan = []
        try:
            today_iso = datetime.date.today().isoformat()
            if self.sticky_coach_pick and self.last_coach_pick_date == today_iso:
                if self.last_coach_pick in self.engine.CHAPTERS:
                    if not self._should_override_sticky_coach_pick(self.last_coach_pick):
                        if not plan or self.last_coach_pick in plan:
                            return self.last_coach_pick
        except Exception:
            pass
        if plan:
            return plan[0]
        try:
            recs = self.engine.top_recommendations(1) or []
            if recs:
                return recs[0][0]
        except Exception:
            pass
        if self.current_topic in self.engine.CHAPTERS:
            return self.current_topic
        return self.engine.CHAPTERS[0] if self.engine.CHAPTERS else ""

    def _get_next_action_line(
        self,
        recommended_topic: str,
        weak_chapter: str | None,
        must_review_due: int,
        has_questions: bool,
    ) -> str:
        if has_questions and must_review_due > 0:
            return f"Next action: clear {must_review_due} must-review cards"
        if has_questions and weak_chapter:
            return f"Next action: weak drill — {weak_chapter}"
        if recommended_topic:
            return f"Next action: focus 25m — {recommended_topic}"
        return "Next action: focus 25m"

    def _get_topic_next_due_text(self, topic: str) -> str:
        if not topic:
            return ""
        try:
            srs_list = self.engine.srs_data.get(topic, [])
        except Exception:
            srs_list = []
        if not isinstance(srs_list, list) or not srs_list:
            return ""
        today = datetime.date.today()
        soonest = None
        has_new = False
        for item in srs_list:
            if not isinstance(item, dict):
                continue
            last = item.get("last_review")
            if last is None:
                has_new = True
                if soonest is None or today < soonest:
                    soonest = today
                continue
            if not isinstance(last, str):
                continue
            try:
                last_date = datetime.date.fromisoformat(last)
                interval = int(item.get("interval", 1) or 1)
            except Exception:
                continue
            due = last_date + datetime.timedelta(days=max(1, interval))
            if soonest is None or due < soonest:
                soonest = due
        if soonest is None:
            return ""
        if soonest <= today:
            return "Next review: new cards due now" if has_new else "Next review: due now"
        return f"Next review: {soonest.isoformat()}"

    def _format_pace_micro_target(self, delta: float) -> str:
        try:
            delta_val = float(delta)
        except Exception:
            return ""
        if delta_val <= 0:
            return ""
        daily = max(5, int(round(delta_val)))
        if daily >= 25:
            extra_poms = max(1, int(math.ceil(daily / 25.0)))
            return f"Add {daily} min today (about {extra_poms} extra Pomodoro{'s' if extra_poms > 1 else ''})."
        every_days = max(1, int(round(25.0 / max(delta_val, 1.0))))
        return f"Add {daily} min today (or 1 extra Pomodoro every {every_days} days)."

    def _get_week_key(self, day: datetime.date) -> str:
        try:
            iso = day.isocalendar()
            return f"{iso.year}-W{int(iso.week):02d}"
        except Exception:
            return day.isoformat()

    def _compute_weekly_hindsight(self) -> tuple[datetime.date, float] | None:
        progress = getattr(self.engine, "progress_log", [])
        if not isinstance(progress, list) or not progress:
            return None
        points = []
        for item in progress:
            if not isinstance(item, dict):
                continue
            date_str = item.get("date")
            try:
                date_val = datetime.date.fromisoformat(date_str) if date_str else None
            except Exception:
                date_val = None
            if not date_val:
                continue
            try:
                total_minutes = float(item.get("total_minutes", 0) or 0)
            except Exception:
                total_minutes = 0.0
            points.append((date_val, total_minutes))
        if not points:
            return None
        points.sort(key=lambda x: x[0])
        daily = []
        prev_total = None
        for date_val, total in points:
            if prev_total is None:
                day_minutes = total
            else:
                day_minutes = total - prev_total
            if day_minutes < 0:
                day_minutes = total
            daily.append((date_val, max(0.0, day_minutes)))
            prev_total = total
        cutoff = datetime.date.today() - datetime.timedelta(days=6)
        recent = [item for item in daily if item[0] >= cutoff]
        if not recent:
            return None
        best_date, best_minutes = max(recent, key=lambda x: x[1])
        if best_minutes <= 0:
            return None
        return best_date, best_minutes

    def _get_focus_goal_today(self, pace_info: dict | None, plan_size: int) -> int:
        base_goal = 1
        if plan_size >= 3:
            base_goal = 2
        try:
            required_avg = float(pace_info.get("required_avg", 0) or 0) if pace_info else 0.0
            verified_today = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
            remaining = max(0.0, required_avg - verified_today)
            if remaining > 0:
                goal_from_pace = int(math.ceil(remaining / 25.0))
                base_goal = max(base_goal, goal_from_pace)
        except Exception:
            pass
        return max(1, min(4, int(base_goal)))

    def _get_topic_due_count(self, topic: str, today: datetime.date | None = None) -> int:
        if not topic:
            return 0
        if today is None:
            today = datetime.date.today()
        try:
            srs_list = self.engine.srs_data.get(topic, [])
        except Exception:
            srs_list = []
        if not isinstance(srs_list, list) or not srs_list:
            return 0
        count = 0
        for item in srs_list:
            try:
                if self.engine.is_overdue(item, today):
                    count += 1
            except Exception:
                continue
        return count

    def _get_drill_topic(self) -> str:
        if not self._has_chapters():
            return ""
        today = datetime.date.today()
        best_topic = None
        best_due = -1
        try:
            must_review = getattr(self.engine, "must_review", {}) or {}
            if isinstance(must_review, dict):
                for ch, items in must_review.items():
                    if not isinstance(items, dict):
                        continue
                    due = 0
                    for due_str in items.values():
                        due_date = self.engine._parse_date(due_str)
                        if due_date and due_date <= today:
                            due += 1
                    if due > best_due:
                        best_due = due
                        best_topic = ch
        except Exception:
            best_topic = None
        if best_topic and best_due > 0:
            return best_topic
        try:
            comp = getattr(self.engine, "competence", {}) or {}
            if isinstance(comp, dict) and comp:
                return sorted(comp.items(), key=lambda x: x[1])[0][0]
        except Exception:
            pass
        return self._get_recommended_topic()

    def _get_weak_chapter(self, threshold: float = 60.0) -> str | None:
        try:
            comp = getattr(self.engine, "competence", {}) or {}
            if isinstance(comp, dict) and comp:
                weakest = sorted(comp.items(), key=lambda x: x[1])[0]
                if float(weakest[1] or 0) < threshold:
                    return weakest[0]
        except Exception:
            pass
        return None

    def _maybe_notify_weak_cleared(self, chapter: str, before: float, after: float) -> None:
        threshold = 60.0
        try:
            if before < threshold <= after and chapter not in self.weak_cleared_notified:
                self.weak_cleared_notified.add(chapter)
                self.save_preferences()
                self.send_notification(
                    "Weak Area Cleared",
                    f"{chapter} is now above {int(threshold)}%. Great work - keep it up.",
                )
        except Exception:
            pass

    def _get_quiz_target_for_topic(self, topic: str, max_questions: int) -> int:
        try:
            comp = float(self.engine.competence.get(topic, 0) or 0)
        except Exception:
            comp = 0.0
        try:
            quiz_results = getattr(self.engine, "quiz_results", {}) or {}
            last_quiz = float(quiz_results.get(topic, 0) or 0) if isinstance(quiz_results, dict) else 0.0
        except Exception:
            last_quiz = 0.0
        if comp < 60 or last_quiz < 70:
            target = 6
        elif comp >= 85 and last_quiz >= 85:
            target = 12
        else:
            target = 8
        return max(5, min(int(target), int(max_questions)))

    def _scale_quiz_target(self, base_target: int, max_questions: int, pace_status: str, plan_size: int) -> int:
        target = int(base_target)
        try:
            pace_info = self._get_pace_info()
            days_remaining = pace_info.get("days_remaining") if isinstance(pace_info, dict) else None
        except Exception:
            days_remaining = None
        if isinstance(days_remaining, int) and days_remaining > 0:
            if days_remaining <= 7:
                target += 3
            elif days_remaining <= 14:
                target += 2
            elif days_remaining <= 30:
                target += 1
        if pace_status == "behind":
            target += 2
            if plan_size >= 4:
                target += 2
        elif pace_status == "ahead":
            target -= 2
        elif pace_status == "on_track":
            if plan_size >= 4:
                target += 1
        return max(5, min(int(target), int(max_questions)))

    def _compute_exam_readiness_details(self) -> dict:
        try:
            mastery_summary = self.engine.get_mastery_summary()
            total_q = float(mastery_summary.get("total", 0))
            mastered_q = float(mastery_summary.get("mastered", 0))
            mastery_pct = (mastered_q / total_q * 100.0) if total_q > 0 else 0.0
        except Exception:
            try:
                mastery_pct = float(self.engine.get_overall_mastery())
            except Exception:
                mastery_pct = 0.0

        try:
            comp = getattr(self.engine, "competence", {}) or {}
            comp_vals = [float(v) for v in comp.values()] if isinstance(comp, dict) else []
            comp_avg = (sum(comp_vals) / len(comp_vals)) if comp_vals else 0.0
            comp_min = min(comp_vals) if comp_vals else 0.0
        except Exception:
            comp_avg = 0.0
            comp_min = 0.0

        try:
            quiz_results = getattr(self.engine, "quiz_results", {}) or {}
            quiz_vals = [float(v) for v in quiz_results.values()] if isinstance(quiz_results, dict) else []
            quiz_avg = (sum(quiz_vals) / len(quiz_vals)) if quiz_vals else 0.0
        except Exception:
            quiz_avg = 0.0

        readiness = 0.5 * mastery_pct + 0.3 * comp_avg + 0.2 * quiz_avg
        readiness = max(0.0, min(100.0, readiness))

        if mastery_pct >= 90 and quiz_avg >= 90 and comp_min >= 70:
            tier = "Elite"
        elif mastery_pct >= 80 and quiz_avg >= 85 and comp_min >= 60:
            tier = "Stage 2"
        elif mastery_pct >= 70 and quiz_avg >= 75 and comp_min >= 50:
            tier = "Stage 1"
        else:
            tier = "Foundation"

        return {
            "score": readiness,
            "tier": tier,
            "mastery_pct": mastery_pct,
            "comp_avg": comp_avg,
            "comp_min": comp_min,
            "quiz_avg": quiz_avg,
        }

    def _compute_exam_readiness(self) -> float:
        return float(self._compute_exam_readiness_details().get("score", 0.0))

    def _get_must_review_due_count(self, today: datetime.date | None = None) -> int:
        if today is None:
            today = datetime.date.today()
        count = 0
        try:
            must_review = getattr(self.engine, "must_review", {}) or {}
            if isinstance(must_review, dict):
                for items in must_review.values():
                    if not isinstance(items, dict):
                        continue
                    for due in items.values():
                        due_date = self.engine._parse_date(due)
                        if due_date and due_date <= today:
                            count += 1
        except Exception:
            return 0
        return count

    # --- UI builders ---
    def _wrap_expander_card(self, title: str, child: Gtk.Widget, expanded: bool = False) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("card")
        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.add_css_class("section-title")
        expander = Gtk.Expander()
        expander.set_label_widget(title_label)
        expander.set_child(child)
        expander.set_expanded(expanded)
        card.append(expander)
        return card

    def _build_next_action_card(
        self,
        recommended_topic: str,
        weak_chapter: str | None,
        must_review_due: int,
        has_questions: bool,
        pace_status: str,
    ) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.add_css_class("card")
        title = Gtk.Label(label="Next best action")
        title.set_halign(Gtk.Align.START)
        title.add_css_class("section-title")
        card.append(title)

        action_text = f"Do: Focus 25m — {recommended_topic}"
        primary_label = "Start focus"
        primary_cb = self.on_focus_now
        reason_lines = []

        if must_review_due > 0 and has_questions:
            action_text = f"Do: Clear {must_review_due} must-review cards"
            primary_label = "Clear reviews"
            primary_cb = self.on_clear_must_review
            reason_lines.append("Reason: reviews are due today")
        elif weak_chapter and has_questions:
            action_text = f"Do: Weak drill — {weak_chapter}"
            primary_label = "Weak drill"
            primary_cb = self.on_drill_weak
            reason_lines.append("Reason: weakest chapter needs lift")
        else:
            reason_lines.append("Reason: best momentum topic")

        if pace_status == "behind":
            reason_lines.append("Pace: behind — small push today")

        lines = [action_text]
        lines.extend(reason_lines)
        action_label = Gtk.Label(label="\n".join(lines))
        action_label.set_halign(Gtk.Align.START)
        action_label.set_wrap(True)
        action_label.add_css_class("muted")
        card.append(action_label)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        primary_btn = Gtk.Button(label=primary_label)
        primary_btn.connect("clicked", primary_cb)
        actions.append(primary_btn)
        if has_questions:
            secondary_label = "Quick quiz" if primary_cb != self.on_quick_quiz else "Focus now"
            secondary_btn = Gtk.Button(label=secondary_label)
            secondary_btn.connect(
                "clicked",
                self.on_quick_quiz if secondary_label == "Quick quiz" else self.on_focus_now,
            )
            actions.append(secondary_btn)
        card.append(actions)
        return card

    # --- Dialog helpers ---
    def _harden_window(self, window: Gtk.Window):
        try:
            def _on_close(_w, *_args):
                try:
                    _w.destroy()
                except Exception:
                    pass
                return True
            window.connect("close-request", _on_close)
        except Exception:
            pass
        return window

    def _new_dialog(self, *args, **kwargs) -> Gtk.Window:
        return self._harden_window(AppDialog(*args, **kwargs))

    def _new_message_dialog(self, *args, **kwargs):
        if getattr(self, "_force_message_dialog_fallback", False) and "force_fallback" not in kwargs:
            kwargs["force_fallback"] = True
        return AppMessageDialog(*args, **kwargs)

    def _new_about_dialog(self, *args, **kwargs) -> Gtk.AboutDialog:
        return self._harden_window(Gtk.AboutDialog(*args, **kwargs))

    # --- Module helpers ---
    def _get_available_modules(self) -> list[dict]:
        modules = []
        seen = set()

        def _add(mid: str, title: str, source: str) -> None:
            key = str(mid).strip().lower()
            if not key or key in seen:
                return
            seen.add(key)
            modules.append({"id": mid, "title": title, "source": source})

        _add(self.module_id, self.module_title, "current")

        candidates = []
        try:
            candidates.append(getattr(self.engine, "MODULES_DIR", ""))
        except Exception:
            pass
        candidates.append(os.path.join(os.path.dirname(__file__), "modules"))

        for folder in [p for p in candidates if p]:
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if not name.endswith(".json"):
                    continue
                mod_id = name[:-5]
                path = os.path.join(folder, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
                title = None
                if isinstance(data, dict):
                    title = data.get("title")
                if not isinstance(title, str) or not title.strip():
                    title = mod_id.replace("_", " ").upper()
                _add(mod_id, title.strip(), folder)

        if not modules:
            modules.append({"id": "acca_f9", "title": "ACCA F9", "source": "default"})
        modules.sort(key=lambda m: m["title"])
        return modules

    def _maybe_show_first_run(self) -> bool:
        if self.first_run_completed:
            return False
        self.on_first_run_tour(None, None)
        return False

    def _get_pace_info(self) -> dict:
        info: dict[str, Any] = {"status": "unknown"}
        try:
            info = self.engine.get_pace_status()
        except Exception:
            info = {"status": "unknown"}
        # Optional: Study Hub can override pace if it demands a stricter daily load.
        try:
            hub = getattr(self.engine, "study_hub_stats", {}) or {}
            if isinstance(hub, dict) and hub.get("total_questions") and info.get("status") != "unknown":
                days = int(info.get("days_remaining", 0) or 0)
                if days > 0:
                    total_q = int(hub.get("total_questions", 0))
                    taken = int(hub.get("questions_taken", 0))
                    avg_answer = int(hub.get("avg_answer_seconds", 0))
                    remaining_q = max(0, total_q - taken)
                    if remaining_q and avg_answer:
                        hub_required = (remaining_q * avg_answer) / 60 / max(1, days)
                        required_avg = float(info.get("required_avg", 0) or 0)
                        if hub_required > required_avg:
                            info["required_avg"] = hub_required
                            delta = hub_required - float(info.get("current_avg", 0) or 0)
                            info["delta"] = delta
                            if delta <= -5:
                                info["status"] = "ahead"
                            elif delta > 5:
                                info["status"] = "behind"
                            else:
                                info["status"] = "on_track"
        except Exception:
            pass
        # Exam-aware enforcement: low retrieval mix makes you "behind" even if minutes are high.
        try:
            retrieval_pct = self._get_retrieval_ratio_today()
            if retrieval_pct is not None and retrieval_pct < self._get_retrieval_min_pct():
                info["status"] = "behind"
                info["status_note"] = "low_retrieval"
                try:
                    info["delta"] = max(float(info.get("delta", 0) or 0), 5.0)
                except Exception:
                    info["delta"] = 5.0
        except Exception:
            pass
        return info

    def _has_chapters(self) -> bool:
        try:
            return bool(getattr(self, "_chapters_available", False) and self.engine.CHAPTERS)
        except Exception:
            return False

    def _ensure_chapters_ready(self, action: str) -> bool:
        if self._has_chapters():
            return True
        self.send_notification(
            action,
            "No chapters loaded. Add a module JSON (Module → Manage Modules) to begin.",
        )
        return False

    def _ensure_valid_topic(self) -> None:
        if not self._has_chapters():
            self.current_topic = ""
            return
        if self.current_topic not in self.engine.CHAPTERS:
            self.current_topic = self.engine.CHAPTERS[0]
            try:
                _topics = list(self.engine.CHAPTERS)
                idx = _topics.index(self.current_topic) if self.current_topic in _topics else 0
                self.topic_combo.set_selected(idx)
            except Exception:
                pass

    def update_study_room_card(self) -> None:
        if not getattr(self, "study_room_summary", None):
            return
        if getattr(self, "study_room_details_expander", None):
            try:
                focus_mode = bool(getattr(self, "focus_mode", False))
                self.study_room_details_expander.set_expanded(not focus_mode)
                self.study_room_details_expander.set_visible(not focus_mode)
            except Exception:
                pass
        if not self._has_chapters():
            self.study_room_summary.set_text(
                "No chapters loaded yet. Add a module JSON (Module → Manage Modules) to start."
            )
            if getattr(self, "study_room_details_expander", None):
                try:
                    self.study_room_details_expander.set_visible(False)
                except Exception:
                    pass
            if getattr(self, "study_room_mission_label", None):
                self.study_room_mission_label.set_text("Mission locked — no chapters loaded.")
            if getattr(self, "study_room_next_due_label", None):
                self.study_room_next_due_label.set_text("")
            if getattr(self, "study_room_mission_bar", None):
                try:
                    self.study_room_mission_bar.set_fraction(0.0)
                    self.study_room_mission_bar.set_text("0%")
                except Exception:
                    pass
            if getattr(self, "quiz_btn", None):
                self.quiz_btn.set_sensitive(False)
            if getattr(self, "study_room_quiz_btn", None):
                self.study_room_quiz_btn.set_sensitive(False)
            if getattr(self, "study_room_drill_btn", None):
                self.study_room_drill_btn.set_sensitive(False)
            if getattr(self, "pomodoro_btn_start", None):
                self.pomodoro_btn_start.set_sensitive(False)
            if getattr(self, "study_room_focus_btn", None):
                self.study_room_focus_btn.set_sensitive(False)
            return
        if getattr(self, "study_room_details_expander", None):
            try:
                self.study_room_details_expander.set_visible(True)
            except Exception:
                pass
        try:
            self._ensure_daily_counters()
        except Exception:
            pass
        self._ensure_valid_topic()
        today = datetime.date.today()
        recommended = self._get_recommended_topic()
        if not recommended:
            recommended = self.current_topic or (self.engine.CHAPTERS[0] if self.engine.CHAPTERS else "")
        if getattr(self, "study_room_next_due_label", None):
            next_due = self._get_topic_next_due_text(recommended)
            self.study_room_next_due_label.set_text(next_due or "")
            try:
                self.study_room_next_due_label.set_visible(bool(next_due))
            except Exception:
                pass
        try:
            self._update_coach_pick_card()
        except Exception:
            pass
        weak_chapter = self._get_weak_chapter(60.0)

        daily_plan = getattr(self, "_last_daily_plan", None) or []
        if not daily_plan:
            try:
                daily_plan = self.engine.get_daily_plan(num_topics=3, current_topic=self.current_topic) or []
            except Exception:
                daily_plan = []

        pace_info = self._get_pace_info()

        quiz_target = 8
        questions = []
        try:
            questions = self.engine.get_questions(recommended)
            base_quiz_target = self._get_quiz_target_for_topic(recommended, len(questions))
        except Exception:
            questions = []
            base_quiz_target = 8
        has_questions = bool(questions)
        if not has_questions:
            quiz_target = 0
        else:
            quiz_target = self._scale_quiz_target(
                base_quiz_target,
                len(questions),
                pace_info.get("status", "unknown"),
                len(daily_plan),
            )

        completed = 0
        for ch in daily_plan:
            try:
                if self._is_completed_today(ch):
                    completed += 1
            except Exception:
                pass

        must_review_due = self._get_must_review_due_count(today)

        focus_goal = self._get_focus_goal_today(pace_info, len(daily_plan))
        try:
            verified_today = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
        except Exception:
            verified_today = 0.0
        focus_done = verified_today >= (focus_goal * 25)
        quiz_done = True if not has_questions else int(self.quiz_questions_today or 0) >= int(quiz_target)
        review_done = must_review_due == 0

        mission_tasks = [(f"Focus {focus_goal}x Pomodoro", focus_done)]
        if has_questions:
            mission_tasks.append((f"Quiz {quiz_target} questions", quiz_done))
        if must_review_due:
            mission_tasks.append((f"Clear must-review ({must_review_due} due)", review_done))
        else:
            mission_tasks.append(("Clear must-review", review_done))

        if getattr(self, "study_room_mission_label", None):
            mission_lines = []
            for title, done in mission_tasks:
                icon = "x" if done else " "
                mission_lines.append(f"[{icon}] {title}")
            if not has_questions:
                mission_lines.append("Quiz mission locked — import questions")
            if weak_chapter:
                mission_lines.append(f"⚠ Mandatory focus: {weak_chapter} (until ≥60%)")
            self.study_room_mission_label.set_text("\n".join(mission_lines))

        if getattr(self, "study_room_mission_bar", None):
            mission_done = sum(1 for _t, done in mission_tasks if done)
            self.study_room_mission_bar.set_fraction(mission_done / max(1, len(mission_tasks)))
            self.study_room_mission_bar.set_text(f"Mission progress: {mission_done}/{len(mission_tasks)}")

        quiz_summary = ""
        try:
            quiz_results = getattr(self.engine, "quiz_results", {}) or {}
            if isinstance(quiz_results, dict) and quiz_results:
                values = [float(v) for v in quiz_results.values() if isinstance(v, (int, float))]
                if values:
                    best = max(values)
                    avg = sum(values) / len(values)
                    quiz_summary = f"Best {best:.0f}% • Avg {avg:.0f}%"
        except Exception:
            quiz_summary = ""

        next_block = ""
        try:
            if isinstance(self.engine.exam_date, datetime.date) and self.engine.has_availability():
                schedule = self.engine.generate_study_schedule(days=1)
                if schedule:
                    blocks = schedule[0].get("blocks", []) or []
                    if blocks:
                        blk = blocks[0]
                        kind = blk.get("kind", "Focus")
                        mins = int(blk.get("minutes", 0) or 0)
                        topic = blk.get("topic") or recommended
                        next_block = f"Next block: {kind} {mins}m — {topic}"
        except Exception:
            next_block = ""

        due_count = 0
        if has_questions:
            try:
                due_count = self._get_topic_due_count(recommended, today)
            except Exception:
                due_count = 0

        lines = [
            self._get_next_action_line(
                recommended_topic=recommended,
                weak_chapter=weak_chapter,
                must_review_due=must_review_due,
                has_questions=has_questions,
            )
        ]
        detail_lines = []
        if daily_plan:
            lines.append(f"Plan: {completed}/{len(daily_plan)} done")
        try:
            lines.append(f"Session: {int(self.study_streak or 0)}d streak • XP {int(self.xp_total)} (Lv {int(self.level)})")
        except Exception:
            pass
        try:
            raw = float(getattr(self, "pomodoro_minutes_today_raw", 0) or 0)
            verified = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
            if raw > 0:
                integrity = max(0.0, min(100.0, (verified / raw) * 100.0))
                lines.append(f"Today: {raw:.0f}m (verified {integrity:.0f}%)")
            else:
                lines.append("Today: not started")
        except Exception:
            pass
        if has_questions and not quiz_done:
            lines.append(f"Quiz target: {quiz_target} q")
        if must_review_due or due_count:
            review_bits = []
            if must_review_due:
                review_bits.append(f"must-review {must_review_due}")
            if due_count:
                review_bits.append(f"topic due {due_count}")
            lines.append("Reviews: " + " • ".join(review_bits))
        if next_block:
            lines.append(next_block)
        if quiz_summary:
            lines.append(f"Quiz: {quiz_summary}")

        # Time-based targets and action mix (exam-aware coaching)
        try:
            if has_questions and quiz_target > 0:
                avg_quiz = self._get_action_avg_minutes("quiz")
                if avg_quiz:
                    sessions_target = max(1, int(math.ceil(quiz_target / 8.0)))
                    target_minutes = avg_quiz * sessions_target
                    detail_lines.append(
                        f"Quiz time target: ~{target_minutes:.0f}m ({sessions_target}×{avg_quiz:.0f}m avg)"
                    )
        except Exception:
            pass
        try:
            action_minutes = self._get_action_minutes_today()
            focus_minutes = action_minutes.get("pomodoro_focus", 0.0)
            recall_minutes = action_minutes.get("pomodoro_recall", 0.0)
            quiz_minutes = action_minutes.get("quiz", 0.0)
            drill_minutes = action_minutes.get("drill", 0.0)
            review_minutes = action_minutes.get("review", 0.0)
            retrieval_minutes = recall_minutes + quiz_minutes + drill_minutes + review_minutes
            total_minutes = focus_minutes + retrieval_minutes
            if total_minutes >= 300:  # at least 5m total to avoid noisy ratios
                retrieval_pct = (retrieval_minutes / total_minutes) * 100.0
                detail_lines.append(f"Action mix: retrieval {retrieval_pct:.0f}% today")
        except Exception:
            pass

        # Pace + proficiency status (exam-date scaled)
        pace_line = ""
        proficiency_line = ""
        mastery_pct_val = None
        pace_delta_val = 0.0
        try:
            mastery_summary = None
            if hasattr(self.engine, "get_mastery_summary"):
                mastery_summary = self.engine.get_mastery_summary()
            if mastery_summary:
                total_q = float(mastery_summary.get("total", 0))
                mastered_q = float(mastery_summary.get("mastered", 0))
                mastery_pct = (mastered_q / total_q * 100.0) if total_q > 0 else 0.0
            else:
                mastery_pct = float(self.engine.get_overall_mastery())
            mastery_pct_val = mastery_pct
            proficiency_line = f"Mastery: {mastery_pct:.0f}%"
        except Exception:
            proficiency_line = ""

        try:
            if isinstance(self.engine.exam_date, datetime.date):
                pace_info = self._get_pace_info()
                days_remaining = int(pace_info.get("days_remaining", 0) or 0)
                required_avg = float(pace_info.get("required_avg", 0) or 0)
                current_avg = float(pace_info.get("current_avg", 0) or 0)
                delta = float(pace_info.get("delta", 0) or 0)
                pace_delta_val = delta
                if days_remaining <= 0:
                    pace_line = "Pace: exam date reached"
                elif delta <= 0:
                    pace_line = f"Pace: On track ✓ ({current_avg:.0f}/{required_avg:.0f} min/day)"
                else:
                    pace_line = f"Pace: +{delta:.0f} min/day to stay on track"
            else:
                pace_line = "Pace: set exam date to calibrate"
        except Exception:
            pace_line = ""

        if proficiency_line:
            detail_lines.append(proficiency_line)
        if pace_line:
            detail_lines.append(pace_line)
        note = self._get_confidence_note(recommended)
        if note:
            detail_lines.append(f"Coach note: {note}")
        try:
            if isinstance(self.engine.exam_date, datetime.date):
                pace_info = self._get_pace_info()
                required_avg = float(pace_info.get("required_avg", 0) or 0)
                verified_today = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
                if required_avg > 0:
                    remaining = max(0.0, required_avg - verified_today)
                    if remaining <= 0.1:
                        detail_lines.append("Today target: met")
                    else:
                        detail_lines.append(f"Today target: {remaining:.0f} min remaining")
        except Exception:
            pass
        try:
            if self.pomodoro_remaining > 0:
                current_report = self._format_focus_report()
                if current_report:
                    detail_lines.append(current_report)
            elif self._last_focus_report:
                detail_lines.append(self._last_focus_report)
        except Exception:
            pass

        # Coach nudge (penalty-free)
        coach_line = ""
        try:
            study_days = getattr(self.engine, "study_days", set()) or set()
            last_day = max(study_days) if study_days else None
            if isinstance(last_day, datetime.date):
                studied_today = last_day == today
            elif isinstance(last_day, str):
                studied_today = last_day == today.isoformat()
            else:
                studied_today = False
            if focus_done and quiz_done and review_done:
                coach_line = "Coach: mission complete — lock in a 5-minute recap."
            elif must_review_due:
                coach_line = f"Coach: clear {must_review_due} must-review cards first."
            elif weak_chapter:
                coach_line = f"Coach: mandatory focus on {weak_chapter} today."
            elif not studied_today:
                coach_line = "Coach: 10 minutes today keeps your streak alive - no penalties."
            elif pace_line.startswith("Pace: On track"):
                if mastery_pct_val is not None and mastery_pct_val >= 70:
                    coach_line = "Coach: on pace and proficiency rising - keep the momentum."
                else:
                    coach_line = "Coach: you're on pace - keep the momentum."
        except Exception:
            coach_line = ""

        if coach_line:
            detail_lines.append(coach_line)
        try:
            action_minutes = self._get_action_minutes_today()
            focus_minutes = action_minutes.get("pomodoro_focus", 0.0)
            recall_minutes = action_minutes.get("pomodoro_recall", 0.0)
            quiz_minutes = action_minutes.get("quiz", 0.0)
            drill_minutes = action_minutes.get("drill", 0.0)
            review_minutes = action_minutes.get("review", 0.0)
            retrieval_minutes = recall_minutes + quiz_minutes + drill_minutes + review_minutes
            total_minutes = focus_minutes + retrieval_minutes
            if total_minutes >= 300:
                retrieval_pct = (retrieval_minutes / total_minutes) * 100.0
                if retrieval_pct < 25 and focus_minutes >= 900:
                    detail_lines.append("Coach: add a 10‑min quiz block to rebalance retrieval.")
        except Exception:
            pass

        self.study_room_summary.set_text("\n".join(lines))
        if getattr(self, "study_room_details_label", None):
            if detail_lines:
                self.study_room_details_label.set_text("\n".join(detail_lines))
            else:
                self.study_room_details_label.set_text("No extra details yet.")
        if getattr(self, "quiz_btn", None):
            self.quiz_btn.set_sensitive(has_questions)
            if not has_questions:
                self.quiz_btn.set_tooltip_text("Import questions to enable quizzes.")
            else:
                self.quiz_btn.set_tooltip_text(None)
        if getattr(self, "study_room_quiz_btn", None):
            self.study_room_quiz_btn.set_sensitive(has_questions)
            if not has_questions:
                self.study_room_quiz_btn.set_tooltip_text("Import questions to enable quizzes.")
            else:
                self.study_room_quiz_btn.set_tooltip_text(None)
        if getattr(self, "study_room_drill_btn", None):
            self.study_room_drill_btn.set_sensitive(has_questions)
            if not has_questions:
                self.study_room_drill_btn.set_tooltip_text("Import questions to unlock drills.")
            else:
                self.study_room_drill_btn.set_tooltip_text(None)

    def _should_show_onboarding(self) -> bool:
        if self.onboarding_dismissed:
            return False
        return not isinstance(self.engine.exam_date, datetime.date)

    # --- Onboarding ---
    def _build_onboarding_card(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card")
        title = Gtk.Label(label="Getting Started")
        title.set_halign(Gtk.Align.START)
        title.add_css_class("section-title")
        card.append(title)

        steps = [
            "1) Set your exam date",
            "2) Set weekday/weekend availability",
            "3) Import Study Hub PDFs (scores)",
            "4) Import or add quiz questions",
        ]
        steps_label = Gtk.Label(label="\n".join(steps))
        steps_label.set_halign(Gtk.Align.START)
        steps_label.set_wrap(True)
        steps_label.add_css_class("muted")
        card.append(steps_label)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        exam_btn = Gtk.Button(label="Set exam date…")
        exam_btn.connect("clicked", self.on_set_exam_date)
        avail_btn = Gtk.Button(label="Set Availability")
        def _open_avail(_btn):
            if getattr(self, "availability_expander", None):
                self.availability_expander.set_expanded(True)
        avail_btn.connect("clicked", _open_avail)
        import_pdf_btn = Gtk.Button(label="Import PDF scores")
        import_pdf_btn.connect("clicked", self.on_import_pdf)
        import_q_btn = Gtk.Button(label="Import Questions")
        import_q_btn.connect("clicked", self.on_import_ai_questions)
        btn_row.append(exam_btn)
        btn_row.append(avail_btn)
        btn_row.append(import_pdf_btn)
        btn_row.append(import_q_btn)
        card.append(btn_row)

        dismiss_btn = Gtk.Button(label="Dismiss")
        def _dismiss(_btn):
            self.onboarding_dismissed = True
            self.save_preferences()
            self.update_dashboard()
        dismiss_btn.connect("clicked", _dismiss)
        card.append(dismiss_btn)
        return card

    def on_focus_now(self, _button):
        self._ensure_coach_selection()
        if not self._ensure_chapters_ready("Focus Now"):
            return
        topic = self._get_recommended_topic()
        if not topic:
            return
        self._set_current_topic(topic)
        if self.pomodoro_remaining > 0 and not self.pomodoro_paused:
            return
        if not self._enforce_retrieval_gate():
            return
        self.on_pomodoro_start(self.pomodoro_btn_start)

    def on_quick_quiz(self, _button):
        self._ensure_coach_selection()
        if not self._ensure_chapters_ready("Quick Quiz"):
            return
        topic = self._get_recommended_topic()
        if not topic:
            return
        self._set_current_topic(topic)
        self.on_take_quiz(self.quiz_btn)

    def on_drill_weak(self, _button):
        self._ensure_coach_selection()
        if not self._ensure_chapters_ready("Drill Weak Area"):
            return
        topic = self._get_drill_topic()
        if not topic:
            return
        self._set_current_topic(topic)
        self.start_quiz_session(topic=topic, total_override=8, kind="drill")

    def on_clear_must_review(self, _button):
        self._ensure_coach_selection()
        if not self._ensure_chapters_ready("Clear Must-Review"):
            return
        topic = self._get_drill_topic()
        if not topic:
            return
        self._set_current_topic(topic)
        # Shorter burst focused on overdue cards
        self.start_quiz_session(topic=topic, total_override=6, kind="review")

    def _finalize_pomodoro_session(
        self,
        minutes_spent: float,
        focus_report: str | None,
        session_label: str = "Pomodoro session",
        credit_override: float | None = None,
        credit_reason: str | None = None,
    ) -> str:
        credited_minutes = self._get_verified_pomodoro_minutes(minutes_spent)
        if credit_override is not None:
            try:
                credited_minutes = max(0.0, float(credit_override))
            except Exception:
                credited_minutes = 0.0
        counted = credited_minutes >= MIN_POMODORO_CREDIT_MINUTES
        self._last_pomodoro_counted = bool(counted)
        message_lines = [f"You studied for {minutes_spent:.1f} minutes."]
        if focus_report:
            message_lines.append(focus_report)
        if credit_override is not None and (credited_minutes <= 0) and credit_reason:
            message_lines.append(credit_reason)
        try:
            entry = {
                "date": datetime.date.today().isoformat(),
                "raw": float(minutes_spent),
                "verified": float(credited_minutes),
            }
            self.focus_integrity_log.append(entry)
            if len(self.focus_integrity_log) > 200:
                self.focus_integrity_log = self.focus_integrity_log[-200:]
        except Exception:
            pass

        before_comp = None
        after_comp = None
        try:
            if minutes_spent > 0:
                self._ensure_daily_counters()
                self.pomodoro_minutes_today_raw = float(self.pomodoro_minutes_today_raw or 0.0) + float(minutes_spent)
                if credited_minutes > 0:
                    self.pomodoro_minutes_today_verified = float(self.pomodoro_minutes_today_verified or 0.0) + float(credited_minutes)
        except Exception:
            pass
        if counted and credited_minutes > 0:
            try:
                before_comp = float(getattr(self.engine, "competence", {}).get(self.current_topic, 0) or 0)
            except Exception:
                before_comp = None
            try:
                self.engine.start_pomodoro(self.current_topic, credited_minutes)
            except Exception:
                pass
            try:
                self.daily_pomodoros_by_chapter.setdefault(self.current_topic, 0)
                self.daily_pomodoros_by_chapter[self.current_topic] += 1
            except Exception:
                pass
            try:
                today_iso = datetime.date.today().isoformat()
                if (
                    self._current_coach_pick_at_start == self.current_topic
                    and self.daily_pomodoros_by_chapter.get(self.current_topic, 0) >= 3
                    and self._last_momentum_date != today_iso
                ):
                    self._last_momentum_date = today_iso
                    self._unlock_achievement(
                        "momentum_streak",
                        "Momentum!",
                        "3 coach Pomodoros today. Keep the streak going.",
                    )
                    self.award_xp(12, "momentum_streak")
            except Exception:
                pass
            try:
                after_comp = float(getattr(self.engine, "competence", {}).get(self.current_topic, 0) or 0)
            except Exception:
                after_comp = None
            if before_comp is not None and after_comp is not None:
                self._maybe_notify_weak_cleared(self.current_topic, float(before_comp), float(after_comp))
            try:
                self.engine.save_data()
            except Exception:
                pass
            self.update_streak()
            self.update_streak_display()
            try:
                self.update_daily_plan()
            except Exception:
                pass

        xp_before = int(getattr(self, "xp_total", 0) or 0)
        reward = self._award_pomodoro_xp(credited_minutes)
        xp_after = int(getattr(self, "xp_total", 0) or 0)
        xp_delta = max(0, xp_after - xp_before)
        if not counted and minutes_spent > 0:
            message_lines.append(f"Session under {MIN_POMODORO_CREDIT_MINUTES}m — not counted.")
            if reward.get("short_counted"):
                message_lines.append(
                    f"Short session credit {self.short_pomodoro_today_count}/{MAX_SHORT_POMODOROS_PER_DAY}."
                )

        try:
            recap_lines = []
            topic = self.current_topic or "Unknown topic"
            recap_lines.append(f"Topic: {topic}")
            recap_lines.append(f"Time: {minutes_spent:.0f}m")
            if focus_report:
                recap_lines.append(focus_report)
            if counted and before_comp is not None and after_comp is not None:
                delta = after_comp - before_comp
                if abs(delta) >= 0.5:
                    recap_lines.append(f"Competence: {delta:+.0f}%")
            if xp_delta > 0:
                recap_lines.append(f"XP: +{xp_delta}")
            self._set_session_recap(session_label, recap_lines)
        except Exception:
            pass

        return "\n".join(message_lines)

    def on_pomodoro_start(self, button):
        self._ensure_coach_selection()
        if not self._ensure_chapters_ready("Pomodoro"):
            return
        self._focus_coach_pick_if_needed()
        if self.pomodoro_timer_id and self.pomodoro_remaining > 0 and not self.pomodoro_paused:
            return
        block_kind = self._get_next_block_kind()
        action_kind = "pomodoro_focus"
        if block_kind.lower().startswith("recall"):
            action_kind = "pomodoro_recall"
        if action_kind == "pomodoro_focus" and not self._enforce_retrieval_gate():
            return
        if self.on_break:
            if not self._can_skip_break():
                self.send_notification("Break Required", "Finish the break before starting a new Pomodoro.")
                return
            self._skip_break_action()
        self._stop_break_timer()
        if self.pomodoro_remaining > 0 and self.pomodoro_paused:
            self.pomodoro_paused = False
            self.pomodoro_btn_pause.set_label("Pause")
            self._set_pomodoro_active_state(True)
            self._resume_action_timer()
            return

        if self.pomodoro_timer_id:
            try:
                GLib.source_remove(self.pomodoro_timer_id)
            except Exception:
                pass
            self.pomodoro_timer_id = None
        self._begin_pomodoro(25, action_kind)
    def _calculate_mastery_distribution(self):
        if not hasattr(self.engine, 'get_mastery_stats'):
            return {"mastered": 0, "learning": 0, "new": 0}

        if hasattr(self.engine, "get_mastery_summary"):
            try:
                summary = self.engine.get_mastery_summary()
                return {
                    "mastered": int(summary.get("mastered", 0)),
                    "learning": int(summary.get("learning", 0)),
                    "new": int(summary.get("new", 0)),
                }
            except Exception:
                pass

        total_mastered = 0
        total_learning = 0
        total_new     = 0

        for chapter in self.engine.CHAPTERS:
            try:
                stats = self.engine.get_mastery_stats(chapter)
                total_mastered += int(stats.get("mastered", 0))
                total_learning += int(stats.get("learning", 0))
                total_new      += int(stats.get("new", 0))
            except Exception:
                # If the method is missing or returns unexpected data, skip gracefully
                pass

        return {
            "mastered": total_mastered,
            "learning": total_learning,
            "new": total_new
        }
    def on_pomodoro_pause(self, button):
        self.pomodoro_paused = not self.pomodoro_paused
        if self.pomodoro_paused:
            button.set_label("Resume")
            self._set_pomodoro_active_state(False)
            self._pause_action_timer()
            self.send_notification("Pomodoro Paused", "Take a break if needed.")
        else:
            button.set_label("Pause")
            self._set_pomodoro_active_state(True)
            self._resume_action_timer()
            self.send_notification("Pomodoro Resumed", "Back to focus!")

    def on_pomodoro_stop(self, button):
        if self.pomodoro_timer_id:
            GLib.source_remove(self.pomodoro_timer_id)
            self.pomodoro_timer_id = None
        self._stop_break_timer()
        self._set_pomodoro_active_state(False)
        self._stop_action_timer(finalize=True)

        minutes_spent = (self._pomodoro_target_minutes * 60 - self.pomodoro_remaining) / 60
        focus_report = self._stop_focus_tracking()
        self.pomodoro_remaining = 0
        self.update_pomodoro_timer_label()
        self.pomodoro_btn_pause.set_sensitive(False)
        self.pomodoro_btn_stop.set_sensitive(False)
        self.pomodoro_btn_start.set_sensitive(True)
        self.pomodoro_btn_pause.set_label("Pause")
        self.pomodoro_paused = False

        message = self._finalize_pomodoro_session(minutes_spent, focus_report, session_label="Pomodoro stopped")
        self.send_notification("Pomodoro Stopped", message)
        self.update_dashboard()
        self.update_recommendations()
        self.update_study_room_card()

    def pomodoro_tick(self):
        if not self.pomodoro_paused and self.pomodoro_remaining > 0:
            self.pomodoro_remaining -= 1
            self.update_pomodoro_timer_label()
            if self.pomodoro_remaining in (15 * 60, 5 * 60):
                if self.pomodoro_remaining not in getattr(self, "_pomodoro_notified", set()):
                    self._pomodoro_notified.add(self.pomodoro_remaining)
                    mins_left = self.pomodoro_remaining // 60
                    self.send_notification("Focus Check-in", f"{mins_left} minutes left. Keep going!")
            if self.pomodoro_remaining == 0:
                focus_report = self._stop_focus_tracking()
                minutes_spent = self._pomodoro_target_minutes
                completed_topic = self.current_topic
                if self._pomodoro_kind == "pomodoro_recall":
                    try:
                        self._stop_action_timer(finalize=True)
                    except Exception:
                        pass
                    try:
                        self._handle_recall_completion(completed_topic, minutes_spent, focus_report)
                    except Exception:
                        message = self._finalize_pomodoro_session(
                            minutes_spent,
                            focus_report,
                            session_label="Pomodoro complete (recall)",
                        )
                        self._finish_pomodoro_completion(
                            completed_topic,
                            minutes_spent,
                            focus_report,
                            message,
                            allow_recall_prompt=False,
                        )
                    return False
                message = self._finalize_pomodoro_session(minutes_spent, focus_report, session_label="Pomodoro complete")
                self._finish_pomodoro_completion(
                    completed_topic,
                    minutes_spent,
                    focus_report,
                    message,
                    allow_recall_prompt=True,
                )
                return False
        return True

    def _finish_pomodoro_completion(
        self,
        completed_topic: str | None,
        minutes_spent: float,
        focus_report: str | None,
        message: str,
        allow_recall_prompt: bool,
    ) -> None:
        priority = getattr(getattr(Gio, "NotificationPriority", None), "HIGH", None)
        self.send_notification("Pomodoro Completed", message, priority=priority)
        self._handle_pomodoro_complete_alerts("Pomodoro complete — break time.")
        self._set_pomodoro_active_state(False)
        self._stop_action_timer(finalize=True)
        self._start_break_timer()
        if getattr(self, "_last_pomodoro_counted", False):
            try:
                self._auto_advance_daily_focus(completed_topic)
            except Exception:
                pass
        self.update_dashboard()
        self.update_recommendations()
        self.update_study_room_card()
        try:
            self._maybe_prompt_reflection(completed_topic, context="Pomodoro complete")
        except Exception:
            pass
        if allow_recall_prompt:
            try:
                self._maybe_prompt_recall_block(completed_topic)
            except Exception:
                pass
        try:
            if getattr(self, "_last_pomodoro_counted", False):
                self._prompt_session_quality(
                    completed_topic,
                    minutes_spent,
                    kind=str(getattr(self, "_pomodoro_kind", "pomodoro")),
                )
        except Exception:
            pass
        self.pomodoro_btn_pause.set_sensitive(False)
        self.pomodoro_btn_stop.set_sensitive(False)
        self.pomodoro_btn_start.set_sensitive(True)

    def _handle_recall_completion(
        self,
        completed_topic: str | None,
        minutes_spent: float,
        focus_report: str | None,
    ) -> None:
        topic = completed_topic or self.current_topic
        self._prompt_recall_checkin(
            topic,
            minutes_spent,
            focus_report,
        )

    def _prompt_recall_checkin(
        self,
        topic: str | None,
        minutes_spent: float,
        focus_report: str | None,
    ) -> None:
        if not topic:
            topic = self.current_topic
        dialog = self._new_dialog(title="Recall Check‑in", transient_for=self, modal=True)
        dialog.add_buttons("I did recall", Gtk.ResponseType.OK, "No, not really", Gtk.ResponseType.REJECT)
        dialog.add_button("Skip", Gtk.ResponseType.CANCEL)
        content = dialog.get_content_area()
        content.set_spacing(8)
        heading = Gtk.Label(
            label="Did you actively recall without looking at notes? Add a quick bullet to earn credit."
        )
        heading.set_halign(Gtk.Align.START)
        heading.set_wrap(True)
        heading.add_css_class("muted")
        content.append(heading)
        textview = Gtk.TextView()
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buffer = textview.get_buffer()
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(90)
        scroller.set_child(textview)
        content.append(scroller)
        ok_btn = dialog.get_widget_for_response(Gtk.ResponseType.OK)
        if ok_btn:
            ok_btn.set_sensitive(False)

        def _update_ok(*_args):
            if not ok_btn:
                return
            start, end = buffer.get_bounds()
            note = buffer.get_text(start, end, True).strip()
            ok_btn.set_sensitive(bool(note))

        buffer.connect("changed", _update_ok)

        def _on_resp(d, resp):
            start, end = buffer.get_bounds()
            note = buffer.get_text(start, end, True).strip()
            did_recall = resp == Gtk.ResponseType.OK and bool(note)
            if did_recall:
                try:
                    notes = getattr(self.engine, "chapter_notes", {}) or {}
                    if not isinstance(notes, dict):
                        notes = {}
                    entry = notes.get(topic, {}) if isinstance(notes.get(topic), dict) else {}
                    history = entry.get("recall_notes")
                    if not isinstance(history, list):
                        history = []
                    history.append(
                        {
                            "date": datetime.date.today().isoformat(),
                            "note": note,
                        }
                    )
                    entry["recall_notes"] = history[-10:]
                    entry["recall_note"] = note
                    entry["updated"] = datetime.date.today().isoformat()
                    notes[topic] = entry
                    self.engine.chapter_notes = notes
                    self.engine.save_data()
                except Exception:
                    pass
                try:
                    self.micro_streak_recall = int(getattr(self, "micro_streak_recall", 0) or 0) + 1
                    if self.micro_streak_recall in (3, 5):
                        title = "Recall streak!"
                        subtitle = (
                            "3 strong recall blocks in a row."
                            if self.micro_streak_recall == 3
                            else "5 strong recall blocks in a row."
                        )
                        self.send_notification(title, subtitle)
                        self.award_xp(5 if self.micro_streak_recall == 3 else 8, "recall_streak")
                    self.save_preferences()
                except Exception:
                    pass
            else:
                self.micro_streak_recall = 0
                try:
                    self.save_preferences()
                except Exception:
                    pass
            credit_override = None if did_recall else 0.0
            credit_reason = None if did_recall else "Recall note required for credit."
            message = self._finalize_pomodoro_session(
                minutes_spent,
                focus_report,
                session_label="Pomodoro complete (recall)",
                credit_override=credit_override,
                credit_reason=credit_reason,
            )
            self._finish_pomodoro_completion(
                topic,
                minutes_spent,
                focus_report,
                message,
                allow_recall_prompt=False,
            )
            d.destroy()
            try:
                questions = self.engine.get_questions(topic)
            except Exception:
                questions = []
            if questions:
                try:
                    self.start_quiz_session(topic=topic, total_override=3, kind="quiz")
                except Exception:
                    pass

        dialog.connect("response", _on_resp)
        dialog.present()

    def update_pomodoro_timer_label(self):
        if self.on_break:
            minutes = self.break_remaining // 60
            seconds = self.break_remaining % 60
            label = "Long Break" if self.on_long_break else "Short Break"
            self.pomodoro_timer_label.set_label(f"{label} {minutes:02d}:{seconds:02d}")
            try:
                eta = datetime.datetime.now() + datetime.timedelta(seconds=max(0, int(self.break_remaining)))
                self.break_eta_label.set_text(f"Break ends at {eta.strftime('%H:%M')}")
            except Exception:
                self.break_eta_label.set_text("")
            return
        minutes = self.pomodoro_remaining // 60
        seconds = self.pomodoro_remaining % 60
        self.pomodoro_timer_label.set_label(f"{minutes:02d}:{seconds:02d}")
        if getattr(self, "break_eta_label", None):
            self.break_eta_label.set_text("")

    def _get_next_break_minutes(self) -> tuple[int, bool]:
        minutes = int(self.short_break_minutes or DEFAULT_SHORT_BREAK_MINUTES)
        is_long = False
        try:
            every = int(self.long_break_every or DEFAULT_LONG_BREAK_EVERY)
            if every > 0 and self.pomodoro_today_count > 0 and (self.pomodoro_today_count % every == 0):
                minutes = int(self.long_break_minutes or DEFAULT_LONG_BREAK_MINUTES)
                is_long = True
        except Exception:
            pass

        # Adaptive break tuning: nudge by focus integrity + recent session quality.
        try:
            weekly_integrity = self._get_focus_integrity_weekly()
            quality = self._get_recent_session_quality_stats()
            low_ratio = (quality["low"] / quality["total"]) if quality["total"] else 0.0
            good_ratio = (quality["good"] / quality["total"]) if quality["total"] else 0.0
            if (weekly_integrity is not None and weekly_integrity < 70) or low_ratio >= 0.4:
                minutes = max(3, minutes - 1)
                self.last_break_adjust_note = "Shorter break: low integrity or low-quality sessions."
            elif (weekly_integrity is not None and weekly_integrity >= 85) or good_ratio >= 0.6:
                minutes = min(12, minutes + 1)
                self.last_break_adjust_note = "Longer break: strong integrity or high-quality sessions."
            else:
                self.last_break_adjust_note = None
        except Exception:
            pass

        return max(1, minutes), is_long

    def _can_skip_break(self) -> bool:
        if self.on_long_break:
            return False
        if self.max_break_skips is None:
            return True
        return self.breaks_skipped_in_row < int(self.max_break_skips)

    def _start_break_timer(self) -> None:
        self._stop_break_timer()
        minutes, is_long = self._get_next_break_minutes()
        self.on_long_break = bool(is_long)
        self.break_remaining = max(0, int(minutes)) * 60
        self.on_break = True
        self.update_pomodoro_timer_label()
        self._update_banner_action_state()
        try:
            if getattr(self, "last_break_adjust_note", None):
                self.pomodoro_timer_label.set_tooltip_text(self.last_break_adjust_note)
        except Exception:
            pass
        label = "Long break started" if self.on_long_break else "Break Started"
        message = f"{int(minutes)}-minute break. You earned it."
        self.send_notification(label, message)
        self.break_timer_id = GLib.timeout_add_seconds(1, self._break_tick)

    def _break_tick(self):
        if self.break_remaining > 0:
            self.break_remaining -= 1
            self.update_pomodoro_timer_label()
            if self.break_remaining == 0:
                self._stop_break_timer()
                self.breaks_skipped_in_row = 0
                priority = getattr(getattr(Gio, "NotificationPriority", None), "HIGH", None)
                self.send_notification("Break Over", "Back to work. Start your next Pomodoro.", priority=priority)
                if self.pomodoro_sound_enabled:
                    path = self._ensure_pomodoro_sound_file()
                    if path:
                        self._play_sound_file(path)
                return False
            return True
        self._stop_break_timer()
        return False

    def _stop_break_timer(self) -> None:
        if self.break_timer_id:
            try:
                GLib.source_remove(self.break_timer_id)
            except Exception:
                pass
            self.break_timer_id = None
        if self.on_break:
            self.on_break = False
            self.break_remaining = 0
            self.update_pomodoro_timer_label()
        self.on_long_break = False
        self._update_banner_action_state()

    def _show_pomodoro_banner(self, text: str) -> None:
        if not getattr(self, "banner_revealer", None):
            return
        self.banner_label.set_text(text)
        self._update_banner_action_state()
        self.banner_revealer.set_reveal_child(True)
        if self._banner_hide_id:
            try:
                GLib.source_remove(self._banner_hide_id)
            except Exception:
                pass
            self._banner_hide_id = None
        self._banner_hide_id = GLib.timeout_add_seconds(15, self._hide_pomodoro_banner)

    def _hide_pomodoro_banner(self) -> bool:
        if getattr(self, "banner_revealer", None):
            self.banner_revealer.set_reveal_child(False)
        self._banner_hide_id = None
        return False

    def _update_banner_action_state(self) -> None:
        if getattr(self, "banner_action_btn", None):
            self.banner_action_btn.set_visible(bool(self.on_break))
            if self.on_break:
                can_skip = self._can_skip_break()
                self.banner_action_btn.set_sensitive(bool(can_skip))
                if can_skip:
                    self.banner_action_btn.set_label("Skip break")
                else:
                    self.banner_action_btn.set_label("Break required")

    def _skip_break_action(self) -> None:
        if not self.on_break:
            return
        if not self._can_skip_break():
            self.send_notification("Break Required", "Take this break to protect focus.")
            return
        self.breaks_skipped_in_row += 1
        self._stop_break_timer()
        self._hide_pomodoro_banner()
        suffix = ""
        if self.max_break_skips is not None and self.breaks_skipped_in_row >= int(self.max_break_skips):
            suffix = " Next break required."
        self.send_notification("Break Skipped", f"Start your next Pomodoro when ready.{suffix}")

    def _flash_window_title(self, seconds: int = 18, interval: int = 2) -> None:
        if not self.pomodoro_title_flash_enabled:
            return
        if self._title_flash_id:
            try:
                GLib.source_remove(self._title_flash_id)
            except Exception:
                pass
            self._title_flash_id = None
        original = self.get_title() or f"{self.module_title} Study Assistant"
        flash_title = "✅ Pomodoro Complete"
        self.set_title(flash_title)
        ticks = {"count": 0}
        max_ticks = max(1, int(seconds / max(1, interval)))

        def _toggle():
            ticks["count"] += 1
            if ticks["count"] >= max_ticks:
                self.set_title(original)
                self._title_flash_id = None
                return False
            if ticks["count"] % 2 == 0:
                self.set_title(flash_title)
            else:
                self.set_title(original)
            return True

        self._title_flash_id = GLib.timeout_add_seconds(interval, _toggle)

    def _ensure_pomodoro_sound_file(self) -> str | None:
        base = os.path.join(os.path.expanduser("~/.config/studyplan"), "sounds")
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            return None
        path = os.path.join(base, "pomodoro_complete_v2.wav")
        if os.path.exists(path):
            return path
        try:
            rate = 44100
            frames = []

            def _add_beep(duration: float, freq: float, amp: float = 0.35) -> None:
                count = int(duration * rate)
                for i in range(count):
                    t = i / rate
                    envelope = 1.0 - (i / max(1, count))
                    sample = int(amp * envelope * math.sin(2 * math.pi * freq * t) * 32767)
                    frames.append(sample)

            def _add_silence(duration: float) -> None:
                count = int(duration * rate)
                frames.extend([0] * count)

            _add_beep(0.18, 880.0, 0.35)
            _add_silence(0.08)
            _add_beep(0.18, 880.0, 0.35)
            _add_silence(0.08)
            _add_beep(0.28, 660.0, 0.32)
            with wave.open(path, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(b"".join(struct.pack("<h", s) for s in frames))
        except Exception:
            return None
        return path

    def _play_sound_file(self, path: str) -> None:
        if not path:
            return
        players = [
            ["paplay", path],
            ["pw-play", path],
            ["aplay", "-q", path],
            ["mpv", "--no-video", "--really-quiet", path],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
        ]
        for cmd in players:
            if shutil.which(cmd[0]):
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                break

    def _handle_pomodoro_complete_alerts(self, message: str) -> None:
        if self.pomodoro_banner_enabled:
            self._show_pomodoro_banner(message)
        if self.pomodoro_title_flash_enabled:
            self._flash_window_title()
        if self.pomodoro_sound_enabled:
            path = self._ensure_pomodoro_sound_file()
            if path:
                self._play_sound_file(path)


    def on_take_quiz(self, button):
        """
        Handle the "Take Quiz" button click event.

        If no questions are available for the current topic, show a
        notification dialog with an informative message.

        Otherwise, select the next question to be shown based on
        the SRS algorithm and show the quiz dialog.

        :param button: the button that was clicked
        :type button: Gtk.Button
        """
        self._ensure_coach_selection()
        if not self._ensure_chapters_ready("Quiz"):
            return
        self._focus_coach_pick_if_needed()
        self._ensure_valid_topic()
        questions = self.engine.get_questions(self.current_topic)
        if not questions:
            dialog = self._new_message_dialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE,
                text="No questions available for this chapter."
            )
            dialog.add_button("Import AI Questions", Gtk.ResponseType.OK)
            dialog.add_button("Export Template", Gtk.ResponseType.APPLY)
            dialog.add_button("Close", Gtk.ResponseType.CANCEL)
            def _on_resp(d, r):
                d.destroy()
                if r == Gtk.ResponseType.OK:
                    self.on_import_ai_questions(None)
                elif r == Gtk.ResponseType.APPLY:
                    self.on_export_template(None)
            dialog.connect("response", _on_resp)
            dialog.present()
            return
        self.start_quiz_session()

    def start_quiz_session(self, topic: str | None = None, total_override: int | None = None, kind: str = "quiz"):
        if not self._has_chapters():
            self.send_notification(
                "Quiz",
                "No chapters loaded. Add a module JSON (Module → Manage Modules) to begin.",
            )
            return
        if topic:
            self._set_current_topic(topic)
        if not self.current_topic:
            return
        questions = self.engine.get_questions(self.current_topic)
        if not questions:
            dialog = self._new_message_dialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE,
                text="No questions available for this chapter.",
            )
            dialog.add_button("Import AI Questions", Gtk.ResponseType.OK)
            dialog.add_button("Export Template", Gtk.ResponseType.APPLY)
            dialog.add_button("Close", Gtk.ResponseType.CANCEL)
            def _on_resp(d, r):
                d.destroy()
                if r == Gtk.ResponseType.OK:
                    self.on_import_ai_questions(None)
                elif r == Gtk.ResponseType.APPLY:
                    self.on_export_template(None)
            dialog.connect("response", _on_resp)
            dialog.present()
            return
        if total_override is not None:
            total = min(int(total_override), len(questions))
        else:
            total = min(self._get_quiz_target_for_topic(self.current_topic, len(questions)), len(questions))
        if total <= 0:
            return
        if hasattr(self.engine, "select_srs_questions"):
            try:
                session_indices = self.engine.select_srs_questions(self.current_topic, total)
            except Exception:
                session_indices = []
        else:
            session_indices = []

        if not session_indices:
            indices = list(range(len(questions)))
            random.shuffle(indices)
            session_indices = indices[:total]

        # Adaptive quiz difficulty: for strong topics, bias toward low-retention / overdue items.
        try:
            quiz_results = getattr(self.engine, "quiz_results", {}) or {}
            prior_score = float(quiz_results.get(self.current_topic, 0) or 0)
        except Exception:
            prior_score = 0.0

        if prior_score >= 80 and session_indices:
            try:
                today = datetime.date.today()
                must_review = getattr(self.engine, "must_review", {}) or {}
                due_indices = []
                if isinstance(must_review, dict):
                    for idx_str, due_str in must_review.get(self.current_topic, {}).items():
                        due_date = self.engine._parse_date(due_str)
                        if due_date and due_date <= today:
                            try:
                                idx = int(idx_str)
                                if 0 <= idx < len(questions):
                                    due_indices.append(idx)
                            except Exception:
                                continue
                # Rank by lowest retention (most forgotten)
                scored = []
                for idx in session_indices:
                    try:
                        retention = float(self.engine.get_retention_probability(self.current_topic, idx))
                    except Exception:
                        retention = 1.0
                    scored.append((retention, idx))
                scored.sort(key=lambda x: x[0])
                ordered = [idx for _r, idx in scored]
                # Ensure due indices are included first
                final = []
                for idx in due_indices:
                    if idx in session_indices and idx not in final:
                        final.append(idx)
                for idx in ordered:
                    if idx not in final:
                        final.append(idx)
                session_indices = final[:total]
            except Exception:
                pass

        self.quiz_session = {
            "indices": session_indices,
            "position": 0,
            "correct": 0,
            "questions": questions,
            "current_streak": 0,
            "best_streak": 0,
            "answers": {},
            "xp_start": int(getattr(self, "xp_total", 0) or 0),
            "topic": self.current_topic,
            "kind": kind,
        }
        self.selected_option = None
        self.show_quiz_dialog()

    def show_quiz_dialog(self):
        dialog = self._new_dialog(title="Quiz", transient_for=self, modal=True)
        dialog.set_default_size(460, 260)
        content_area = dialog.get_content_area()

        self.quiz_status_label = Gtk.Label()
        self.quiz_status_label.set_halign(Gtk.Align.START)
        content_area.append(self.quiz_status_label)

        self.quiz_progress = Gtk.ProgressBar()
        self.quiz_progress.set_show_text(True)
        content_area.append(self.quiz_progress)

        self.quiz_hint_label = Gtk.Label(label="Select an option, then Confirm.")
        self.quiz_hint_label.set_halign(Gtk.Align.START)
        self.quiz_hint_label.set_wrap(True)
        self.quiz_hint_label.add_css_class("muted")
        content_area.append(self.quiz_hint_label)

        # Containers for dynamic content
        self.quiz_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content_area.append(self.quiz_content_box)

        self.quiz_feedback = Gtk.Label()
        self.quiz_feedback.set_wrap(True)
        self.quiz_feedback.set_halign(Gtk.Align.START)
        content_area.append(self.quiz_feedback)

        # Button row
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.quiz_prev_btn = Gtk.Button(label="Previous")
        self.quiz_prev_btn.connect("clicked", self.on_quiz_prev, dialog)
        self.quiz_prev_btn.set_sensitive(False)
        btn_row.append(self.quiz_prev_btn)

        self.quiz_confirm_btn = Gtk.Button(label="Confirm")
        self.quiz_confirm_btn.connect("clicked", self.on_quiz_confirm, dialog)
        self.quiz_confirm_btn.set_sensitive(False)
        btn_row.append(self.quiz_confirm_btn)

        self.quiz_next_btn = Gtk.Button(label="Next")
        self.quiz_next_btn.connect("clicked", self.on_quiz_next, dialog)
        self.quiz_next_btn.set_sensitive(False)
        btn_row.append(self.quiz_next_btn)

        self.quiz_finish_btn = Gtk.Button(label="Finish")
        def _finish_quiz(_b=None):
            self._stop_action_timer(finalize=True)
            dialog.destroy()
        self.quiz_finish_btn.connect("clicked", _finish_quiz)
        btn_row.append(self.quiz_finish_btn)

        content_area.append(btn_row)

        self.render_quiz_question()
        try:
            kind = self.quiz_session.get("kind", "quiz")
        except Exception:
            kind = "quiz"
        self._start_action_timer(kind, topic=self.current_topic)
        try:
            def _on_close(_w, *_args):
                self._stop_action_timer(finalize=True)
                return False
            dialog.connect("close-request", _on_close)
        except Exception:
            pass
        dialog.present()

    def render_quiz_question(self):
        # Clear previous content
        child = self.quiz_content_box.get_first_child()
        while child:
            self.quiz_content_box.remove(child)
            child = self.quiz_content_box.get_first_child()

        self.quiz_feedback.set_label("")
        if getattr(self, "quiz_confirm_btn", None):
            self.quiz_confirm_btn.set_sensitive(False)
        self.quiz_next_btn.set_sensitive(False)
        if getattr(self, "quiz_prev_btn", None):
            self.quiz_prev_btn.set_sensitive(self.quiz_session["position"] > 0)
        self.selected_option = None
        self.quiz_option_buttons = {}

        idx = self.quiz_session["indices"][self.quiz_session["position"]]
        question = self.quiz_session["questions"][idx]

        pos = self.quiz_session["position"] + 1
        total = len(self.quiz_session["indices"])
        score = self.quiz_session["correct"]
        self.quiz_status_label.set_markup(f"<b>Question {pos}/{total}</b>   Score: {score}")
        self.quiz_progress.set_fraction(pos / max(1, total))
        self.quiz_progress.set_text(f"{pos}/{total}")
        if getattr(self, "quiz_next_btn", None):
            self.quiz_next_btn.set_label("Finish" if pos == total else "Next")
        if getattr(self, "quiz_hint_label", None):
            self.quiz_hint_label.set_visible(True)

        header = Gtk.Label(label=f"Question {pos} of {total}")
        header.set_halign(Gtk.Align.START)
        self.quiz_content_box.append(header)

        q_label = Gtk.Label(label=question["question"])
        q_label.set_wrap(True)
        q_label.set_halign(Gtk.Align.START)
        self.quiz_content_box.append(q_label)

        shuffled_options = question["options"][:]
        random.shuffle(shuffled_options)

        first_btn = None
        for opt in shuffled_options:
            btn = Gtk.CheckButton(label=opt)
            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)
            btn.connect("toggled", self.on_option_toggled, opt)
            self.quiz_content_box.append(btn)
            self.quiz_option_buttons[opt] = btn

        answer_state = self.quiz_session.get("answers", {}).get(idx)
        if isinstance(answer_state, dict):
            selected = answer_state.get("selected")
            if selected in self.quiz_option_buttons:
                self.quiz_option_buttons[selected].set_active(True)
                self.selected_option = selected
            if answer_state.get("confirmed"):
                is_correct = bool(answer_state.get("is_correct"))
                message = "Correct! ✓" if is_correct else f"Incorrect. ✗  Correct: {question['correct']}"
                if "explanation" in question:
                    message += f"\n\n💡{question['explanation']}"
                self.quiz_feedback.set_label(message)
                for btn in self.quiz_option_buttons.values():
                    btn.set_sensitive(False)
                correct_btn = self.quiz_option_buttons.get(question["correct"])
                if correct_btn:
                    correct_btn.add_css_class("success")
                if not is_correct and selected:
                    selected_btn = self.quiz_option_buttons.get(selected)
                    if selected_btn:
                        selected_btn.add_css_class("error")
                self.quiz_confirm_btn.set_sensitive(False)
                self.quiz_next_btn.set_sensitive(True)
                if getattr(self, "quiz_hint_label", None):
                    self.quiz_hint_label.set_visible(False)

    def on_option_toggled(self, button, opt):
        if button.get_active():
            self.selected_option = opt
            if getattr(self, "quiz_confirm_btn", None):
                self.quiz_confirm_btn.set_sensitive(True)

    def on_quiz_confirm(self, button, dialog):
        idx = self.quiz_session["indices"][self.quiz_session["position"]]
        if self.quiz_session.get("answers", {}).get(idx, {}).get("confirmed"):
            return
        if self.selected_option is None:
            warn_dialog = self._new_message_dialog(
                transient_for=dialog,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Please select an option."
            )
            warn_dialog.connect("response", lambda d, r: d.destroy())
            warn_dialog.present()
            return

        question = self.quiz_session["questions"][idx]

        is_correct = self.selected_option == question["correct"]
        self.quiz_session.setdefault("answers", {})[idx] = {
            "selected": self.selected_option,
            "confirmed": True,
            "is_correct": bool(is_correct),
        }
        try:
            self._increment_quiz_questions_today(1)
        except Exception:
            pass
        if is_correct:
            self.quiz_session["correct"] += 1
            self.quiz_session["current_streak"] = self.quiz_session.get("current_streak", 0) + 1
            if self.quiz_session["current_streak"] > self.quiz_session.get("best_streak", 0):
                self.quiz_session["best_streak"] = self.quiz_session["current_streak"]
            self.award_xp(2, "quiz_correct")
            if self.quiz_session["current_streak"] in (3, 5):
                bonus = 5 if self.quiz_session["current_streak"] == 3 else 10
                self.award_xp(bonus, "quiz_streak")
                self.send_notification(
                    "Quiz Streak!",
                    f"{self.quiz_session['current_streak']} correct in a row. Bonus +{bonus} XP!",
                )
            if self.quiz_session["current_streak"] == 10 and "perfect_10" not in self.achievements:
                self._unlock_achievement("perfect_10", "Perfect 10", "10 correct answers in a row!")
                self.award_xp(20, "perfect_10")
            if self.quiz_session.get("best_streak", 0) >= 8 and "quiz_sharpshooter" not in self.achievements:
                self._unlock_achievement("quiz_sharpshooter", "Quiz Sharpshooter", "8+ best streak in a quiz!")
                self.award_xp(15, "quiz_sharpshooter")
        else:
            try:
                if hasattr(self.engine, "flag_incorrect"):
                    self.engine.flag_incorrect(self.current_topic, idx, days=2)
            except Exception:
                pass
            try:
                if hasattr(self.engine, "record_difficulty"):
                    self.engine.record_difficulty(self.current_topic, idx)
            except Exception:
                pass
            self.quiz_session["current_streak"] = 0

        delta = 10 if is_correct else -5
        before_comp = float(getattr(self.engine, "competence", {}).get(self.current_topic, 0) or 0)
        try:
            self.engine.update_competence(self.current_topic, delta, question_index=idx)
        except Exception:
            pass
        after_comp = float(getattr(self.engine, "competence", {}).get(self.current_topic, 0) or 0)
        if before_comp is not None and after_comp is not None:
            self._maybe_notify_weak_cleared(self.current_topic, float(before_comp), float(after_comp))
        try:
            self.engine.update_srs(self.current_topic, idx, is_correct)
        except Exception:
            pass

        message = "Correct! ✓" if is_correct else f"Incorrect. ✗  Correct: {question['correct']}"
        if "explanation" in question:
            message += f"\n\n💡{question['explanation']}"
        self.quiz_feedback.set_label(message)
        for btn in self.quiz_option_buttons.values():
            btn.set_sensitive(False)
        correct_btn = self.quiz_option_buttons.get(question["correct"])
        if correct_btn:
            correct_btn.add_css_class("success")
        if not is_correct:
            selected_btn = self.quiz_option_buttons.get(self.selected_option)
            if selected_btn:
                selected_btn.add_css_class("error")

        pos = self.quiz_session["position"] + 1
        total = len(self.quiz_session["indices"])
        score = self.quiz_session["correct"]
        self.quiz_status_label.set_markup(f"<b>Question {pos}/{total}</b>   Score: {score}")

        self.engine.save_data()
        self.update_streak()
        self.update_streak_display()
        self.update_dashboard()
        self.update_recommendations()
        self.update_study_room_card()

        self.quiz_confirm_btn.set_sensitive(False)
        self.quiz_next_btn.set_sensitive(True)
        if getattr(self, "quiz_hint_label", None):
            self.quiz_hint_label.set_visible(False)

    def on_quiz_prev(self, button, dialog):
        if self.quiz_session["position"] <= 0:
            return
        self.quiz_session["position"] -= 1
        self.render_quiz_question()

    def on_quiz_next(self, button, dialog):
        self.quiz_session["position"] += 1
        if self.quiz_session["position"] >= len(self.quiz_session["indices"]):
            score = self.quiz_session["correct"]
            total = len(self.quiz_session["indices"])
            self.quiz_sessions_completed += 1
            try:
                self._increment_quiz_sessions_today(1)
            except Exception:
                pass
            self.save_preferences()

            ratio = score / max(1, total)
            try:
                new_score = ratio * 100.0
                self.engine.record_quiz_result(self.current_topic, new_score)
            except Exception:
                new_score = ratio * 100.0
            try:
                if self.current_topic:
                    self.daily_recall_by_chapter.setdefault(self.current_topic, 0)
                    self.daily_recall_by_chapter[self.current_topic] += 1
            except Exception:
                pass
            try:
                self._maybe_notify_confidence_delta(self.current_topic, new_score)
            except Exception:
                pass
            try:
                if hasattr(self.engine, "mark_completed_today"):
                    self.engine.mark_completed_today(self.current_topic)
                if hasattr(self.engine, "record_quiz_history"):
                    self.engine.record_quiz_history(
                        self.current_topic,
                        list(self.quiz_session.get("indices", []))
                    )
                self.engine.save_data()
            except Exception:
                pass
            bonus = 0
            if ratio >= 0.8:
                bonus = 10
            if ratio >= 1.0:
                bonus = 15
                self._unlock_achievement("quiz_perfect", "Perfect Quiz!", "100% score. Outstanding!")
            if bonus:
                self.award_xp(bonus, "quiz_complete")
            if self.quiz_sessions_completed == 1:
                self._unlock_achievement("quiz_first", "Quiz Starter", "First quiz completed!")
            if self.quiz_sessions_completed == 10:
                self._unlock_achievement("quiz_10", "Quiz Runner", "10 quizzes completed!")
            if self.quiz_sessions_completed == 50:
                self._unlock_achievement("quiz_50", "Quiz Master", "50 quizzes completed!")
            try:
                xp_start = int(self.quiz_session.get("xp_start", self.xp_total) or 0)
                xp_after = int(getattr(self, "xp_total", 0) or 0)
                xp_delta = max(0, xp_after - xp_start)
                recap_lines = []
                topic = self.quiz_session.get("topic") or self.current_topic or "Unknown topic"
                recap_lines.append(f"Topic: {topic}")
                recap_lines.append(f"Score: {score}/{total} ({ratio * 100:.0f}%)")
                best_streak = int(self.quiz_session.get("best_streak", 0) or 0)
                if best_streak:
                    recap_lines.append(f"Best streak: {best_streak}")
                if xp_delta:
                    recap_lines.append(f"XP: +{xp_delta}")
                self._set_session_recap("Quiz complete", recap_lines)
            except Exception:
                pass
            result_dialog = self._new_message_dialog(
                transient_for=dialog,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=f"Quiz complete! Score: {score}/{total}"
            )
            def _on_result_close(d, _r):
                d.destroy()
                try:
                    self._maybe_prompt_reflection(self.current_topic, context="Quiz complete")
                except Exception:
                    pass
            result_dialog.connect("response", _on_result_close)
            result_dialog.present()
            self._stop_action_timer(finalize=True)
            dialog.destroy()
            self.update_dashboard()
            self.update_recommendations()
            self.update_study_room_card()
            return

        self.render_quiz_question()

    def on_import_pdf(self, button):
        dialog = self._new_dialog(title="Select PDF File", transient_for=self, modal=True)
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL, "_Open", Gtk.ResponseType.ACCEPT
        )
        content_area = dialog.get_content_area()
        content_area.set_spacing(8)

        file_chooser = Gtk.FileChooserWidget(action=Gtk.FileChooserAction.OPEN)
        file_chooser.set_hexpand(True)
        file_chooser.set_vexpand(True)
        content_area.append(file_chooser)
        self.import_file_chooser = file_chooser

        dialog.connect("response", self.on_import_pdf_response)
        dialog.present()

    def _lines_from_text_dict(self, text_dict) -> list[str]:
        lines_with_pos = []
        blocks = text_dict.get("blocks", []) if isinstance(text_dict, dict) else []
        for block in blocks:
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []) or []:
                spans = line.get("spans", []) or []
                if not spans:
                    continue
                spans_sorted = sorted(spans, key=lambda s: (s.get("bbox", [0, 0])[0]))
                text = " ".join(s.get("text", "") for s in spans_sorted).strip()
                text = " ".join(text.split())
                if not text:
                    continue
                bbox = line.get("bbox") or block.get("bbox") or [0, 0, 0, 0]
                y = float(bbox[1]) if len(bbox) > 1 else 0.0
                x = float(bbox[0]) if len(bbox) > 0 else 0.0
                lines_with_pos.append((y, x, text))
        if not lines_with_pos:
            return []
        lines_with_pos.sort(key=lambda t: (t[0], t[1]))
        merged: list[list[Any]] = []
        y_tol = 2.0
        for y, x, text in lines_with_pos:
            if not merged or abs(y - float(merged[-1][0])) > y_tol:
                merged.append([y, x, text])
            else:
                merged[-1][2] = f"{str(merged[-1][2])} {text}"
        return [str(m[2]) for m in merged]

    def _looks_sparse(self, lines: list[str]) -> bool:
        if not lines:
            return True
        combined = " ".join(lines)
        alnum = sum(1 for ch in combined if ch.isalnum())
        if alnum < 120 or len(lines) < 6:
            return True
        keywords = ("Questions Taken", "Correct", "Quiz", "Revision", "Chapter", "Ch")
        if not any(k in combined for k in keywords):
            return True
        return False

    def _extract_page_lines(self, page) -> tuple[list[str], bool, bool]:
        try:
            text_dict = page.get_text("dict")
            lines = self._lines_from_text_dict(text_dict)
        except Exception:
            lines = []
        if not self._looks_sparse(lines):
            return lines, False, False
        # OCR fallback for low-text pages
        try:
            textpage = page.get_textpage_ocr()
        except Exception:
            return lines, False, True
        ocr_dict = None
        try:
            ocr_dict = textpage.extractDICT()
        except Exception:
            try:
                ocr_dict = page.get_text("dict", textpage=textpage)
            except Exception:
                ocr_dict = None
        if ocr_dict:
            ocr_lines = self._lines_from_text_dict(ocr_dict)
            if ocr_lines:
                return ocr_lines, True, False
        try:
            ocr_text = textpage.extractTEXT()
        except Exception:
            ocr_text = ""
        ocr_lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
        return (ocr_lines or lines), bool(ocr_lines), False

    def _extract_pdf_text_advanced(self, file_path: str) -> tuple[str, dict]:
        if fitz is None:
            return "", {"ocr_used": False, "ocr_pages": 0, "ocr_failed_pages": 0}
        ocr_used = False
        ocr_pages = 0
        ocr_failed_pages = 0
        all_lines = []
        with fitz.open(file_path) as doc:
            for page in doc:
                page_lines, used_ocr, ocr_failed = self._extract_page_lines(page)
                if used_ocr:
                    ocr_used = True
                    ocr_pages += 1
                if ocr_failed:
                    ocr_failed_pages += 1
                all_lines.extend(page_lines)
        return "\n".join(all_lines), {
            "ocr_used": ocr_used,
            "ocr_pages": ocr_pages,
            "ocr_failed_pages": ocr_failed_pages,
        }

    def on_import_pdf_response(self, dialog: Gtk.Window, response: Gtk.ResponseType) -> None:
        """
        Handle response from file chooser dialog for importing PDF scores.
        If the user selected a file, extract the text from the PDF and
        import it into the study plan engine.
        """
        if response == Gtk.ResponseType.ACCEPT:
            file_path = None
            try:
                file_path = self._get_file_path(self.import_file_chooser)
            except Exception:
                file_path = None
            if not file_path:
                dialog.destroy()
                error_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="No file selected."
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()
                return
            dialog.destroy()

            if fitz is None:
                error_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="PyMuPDF not installed. Install with 'pip install pymupdf'."
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()
                return

            competence_before = dict(getattr(self.engine, "competence", {}) or {})
            quiz_before = dict(getattr(self.engine, "quiz_results", {}) or {})

            try:
                pdf_text, meta = self._extract_pdf_text_advanced(file_path)
                result = self.engine.import_pdf_scores(pdf_text, allow_lower=self.allow_lower_scores)
                self.engine.save_data()
                self.update_dashboard()
                self.update_recommendations()
                updated = result.get("updated", {}) if isinstance(result, dict) else {}
                lowered = result.get("lowered", {}) if isinstance(result, dict) else {}
                skipped = result.get("skipped_lines", 0) if isinstance(result, dict) else 0
                stats = result.get("study_hub_stats", {}) if isinstance(result, dict) else {}
                quiz_scores = result.get("quiz_scores", {}) if isinstance(result, dict) else {}
                practice_scores = result.get("practice_scores", {}) if isinstance(result, dict) else {}
                detail_scores = result.get("detail_scores", {}) if isinstance(result, dict) else {}
                detail_type = result.get("detail_type") if isinstance(result, dict) else None
                diagnostics = result.get("diagnostics", {}) if isinstance(result, dict) else {}
                sources = diagnostics.get("sources", []) if isinstance(diagnostics, dict) else []
                parsed_chapters = diagnostics.get("parsed_chapters", []) if isinstance(diagnostics, dict) else []
                confidence = diagnostics.get("confidence") if isinstance(diagnostics, dict) else None
                confidence_score = diagnostics.get("confidence_score", 0) if isinstance(diagnostics, dict) else 0
                warnings = diagnostics.get("warnings", []) if isinstance(diagnostics, dict) else []
                skipped_samples = diagnostics.get("skipped_samples", []) if isinstance(diagnostics, dict) else []
                skipped_score_lines = result.get("skipped_score_lines", 0) if isinstance(result, dict) else 0
                if quiz_scores or practice_scores or detail_scores:
                    self.last_hub_import_date = datetime.date.today().isoformat()
                    self._plan_refresh_override = True
                    self.save_preferences()
                updated_lines = "\n".join([f"{k}: {v}%" for k, v in updated.items()])
                msg = "PDF scores imported successfully."
                if updated_lines:
                    msg += f"\n\nUpdated:\n{updated_lines}"
                if lowered:
                    lowered_preview = ", ".join([f"{k}: {v}%" for k, v in list(lowered.items())[:5]])
                    msg += f"\n\nApplied lower scores: {len(lowered)}"
                    if lowered_preview:
                        msg += f"\n{lowered_preview}"
                if skipped:
                    msg += f"\n\nSkipped lines: {skipped}"
                if stats.get("total_questions") is not None:
                    msg += (
                        f"\n\nStudy Hub:\n"
                        f"Questions Taken: {stats.get('questions_taken', 0)} of {stats.get('total_questions', 0)}\n"
                        f"Correct: {stats.get('correct_percent', 0)}%"
                    )
                if sources:
                    source_labels = {
                        "quiz_dashboard": "Quiz dashboard",
                        "quiz_report": "Quiz report",
                        "practice_report": "Practice report",
                        "practice_overview": "Practice overview",
                        "quiz_detail": "Quiz detail",
                        "practice_detail": "Practice detail",
                        "fallback": "Fallback matching",
                    }
                    pretty = ", ".join(
                        [source_labels.get(s, s.replace("_", " ").title()) for s in sources if isinstance(s, str)]
                    )
                    msg += f"\n\nDetected: {pretty}"
                if parsed_chapters:
                    msg += f"\nChapters matched: {len(parsed_chapters)}"
                if confidence:
                    msg += f"\nConfidence: {str(confidence).capitalize()} ({int(confidence_score)}%)"
                if skipped_score_lines:
                    msg += f"\nScore lines skipped: {skipped_score_lines}"
                if result.get("category_totals"):
                    msg += f"\n\nCategories parsed: {len(result.get('category_totals', {}))}"
                if quiz_scores:
                    quiz_preview = ", ".join([f"{k}: {v}%" for k, v in list(quiz_scores.items())[:5]])
                    msg += f"\n\nQuiz scores parsed: {len(quiz_scores)}"
                    if quiz_preview:
                        msg += f"\n{quiz_preview}"
                if practice_scores:
                    practice_preview = ", ".join([f"{k}: {v}%" for k, v in list(practice_scores.items())[:5]])
                    msg += f"\n\nPractice report parsed: {len(practice_scores)}"
                    if practice_preview:
                        msg += f"\n{practice_preview}"
                if detail_scores:
                    detail_preview = ", ".join([f"{k}: {v}%" for k, v in list(detail_scores.items())[:5]])
                    label = "Detail scores parsed"
                    if detail_type == "practice":
                        label = "Practice detail parsed"
                    elif detail_type == "quiz":
                        label = "Quiz detail parsed"
                    msg += f"\n\n{label}: {len(detail_scores)}"
                    if detail_preview:
                        msg += f"\n{detail_preview}"
                if warnings:
                    warn_lines = "\n".join([f"- {w}" for w in warnings])
                    msg += f"\n\nWarnings:\n{warn_lines}"
                if skipped_samples:
                    samples = "\n".join([f"- {s}" for s in skipped_samples])
                    msg += f"\n\nSkipped examples:\n{samples}"
                if meta.get("ocr_used"):
                    msg += f"\n\nOCR used on {meta.get('ocr_pages', 0)} page(s) for accuracy."
                elif meta.get("ocr_failed_pages"):
                    msg += f"\n\nOCR unavailable for {meta.get('ocr_failed_pages', 0)} page(s); used text extraction."
                competence_after = dict(getattr(self.engine, "competence", {}) or {})
                diff_rows = []
                for ch in self.engine.CHAPTERS:
                    before = float(competence_before.get(ch, 0) or 0)
                    after = float(competence_after.get(ch, 0) or 0)
                    if abs(after - before) > 0.01:
                        diff_rows.append(
                            (
                                ch,
                                f"{before:.0f}%",
                                f"{after:.0f}%",
                                f"{after - before:+.0f}%",
                            )
                        )
                diff_rows.sort(key=lambda x: abs(float(x[3].replace('%', ''))), reverse=True)

                quiz_merge = dict(quiz_scores)
                if detail_type == "quiz":
                    for ch, pct in detail_scores.items():
                        try:
                            pct_val = float(pct)
                        except Exception:
                            continue
                        prev = float(quiz_merge.get(ch, 0) or 0)
                        if pct_val > prev:
                            quiz_merge[ch] = int(round(pct_val))
                quiz_rows = [(ch, f"{int(pct)}%") for ch, pct in sorted(quiz_merge.items(), key=lambda x: x[1], reverse=True)]

                title = "PDF Import Summary"
                if warnings or (confidence == "low") or (not parsed_chapters and skipped_score_lines):
                    title = "PDF Import Summary (Check warnings)"
                success_dialog = self._new_dialog(title=title, transient_for=self, modal=True)
                success_dialog.add_button("OK", Gtk.ResponseType.OK)
                success_dialog.set_default_size(540, 560)
                content = success_dialog.get_content_area()
                content.set_spacing(10)

                summary_label = Gtk.Label(label=msg)
                summary_label.set_wrap(True)
                summary_label.set_halign(Gtk.Align.START)
                summary_label.set_xalign(0.0)
                content.append(summary_label)

                content.append(
                    self._build_import_table(
                        "Competence changes",
                        ["Chapter", "Before", "After", "Δ"],
                        diff_rows,
                        min_height=160,
                    )
                )
                if quiz_rows:
                    content.append(
                        self._build_import_table(
                            "Quiz results (completion only)",
                            ["Chapter", "Score"],
                            quiz_rows,
                            min_height=120,
                        )
                    )

                success_dialog.connect("response", lambda d, r: d.destroy())
                success_dialog.present()
                try:
                    entry = {
                        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                        "file": file_path,
                        "updated": len(updated),
                        "lowered": len(lowered),
                        "skipped_score_lines": int(skipped_score_lines),
                        "sources": sources,
                        "parsed_chapters": len(parsed_chapters),
                        "confidence": confidence,
                        "confidence_score": int(confidence_score),
                        "warnings": warnings,
                        "ocr_used": bool(meta.get("ocr_used")),
                        "ocr_pages": int(meta.get("ocr_pages", 0) or 0),
                        "ocr_failed_pages": int(meta.get("ocr_failed_pages", 0) or 0),
                    }
                    self._log_import_history(entry)
                except Exception:
                    pass
            except ImportError:
                error_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="PyMuPDF not installed. Install with 'pip install pymupdf'."
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()
            except Exception as e:
                self._log_error("import_pdf_scores", e)
                error_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text=f"Error importing PDF: {e}"
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()
        else:
            dialog.destroy()

    def on_import_ai_questions(self, button):
        if getattr(self, "_dialog_smoke_mode", False):
            dialog = self._harden_window(Gtk.FileChooserDialog(  # gtk4_lint:ignore
                title="Import AI Questions (JSON)",
                transient_for=self,
                action=Gtk.FileChooserAction.OPEN,
            ))
            dialog.add_buttons(
                "_Cancel", Gtk.ResponseType.CANCEL, "_Open", Gtk.ResponseType.ACCEPT
            )
            dialog.connect("response", self.on_import_ai_questions_response)
            dialog.present()
            return
        dialog = Gtk.FileChooserNative(
            title="Import AI Questions (JSON)",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="_Open",
            cancel_label="_Cancel",
        )
        self._active_native_dialog = dialog
        dialog.connect("response", self.on_import_ai_questions_response)
        dialog.connect("response", lambda *_args: setattr(self, "_active_native_dialog", None))
        dialog.show()

    def on_import_ai_questions_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            file_path = self._get_file_path(dialog)
            dialog.destroy()

            try:
                if not file_path:
                    raise ValueError("No file selected.")
                result = self.engine.import_questions_json(file_path)
                added = result.get("added", 0) if isinstance(result, dict) else 0
                chapters = result.get("chapters", []) if isinstance(result, dict) else []
                chapter_text = ", ".join(chapters) if chapters else "N/A"
                success_dialog = self._new_message_dialog(
                        transient_for=self,
                        modal=True,
                        message_type=Gtk.MessageType.INFO,
                        buttons=Gtk.ButtonsType.OK,
                        text=f"AI questions imported: {added}\nChapters: {chapter_text}"
                )
                success_dialog.connect("response", lambda d, r: d.destroy())
                success_dialog.present()
            except Exception as e:
                self._log_error("import_ai_questions", e)
                error_dialog = self._new_message_dialog(
                        transient_for=self,
                        modal=True,
                        message_type=Gtk.MessageType.ERROR,
                        buttons=Gtk.ButtonsType.OK,
                        text=f"Error importing Json questions: {e}"
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()
        else:
            dialog.destroy()


    def on_export_data(self, button):
        if getattr(self, "_dialog_smoke_mode", False):
            dialog = self._harden_window(Gtk.FileChooserDialog(  # gtk4_lint:ignore
                title="Export Data to CSV",
                transient_for=self,
                action=Gtk.FileChooserAction.SAVE,
            ))
            dialog.add_buttons(
                "_Cancel", Gtk.ResponseType.CANCEL, "_Save", Gtk.ResponseType.ACCEPT
            )
            dialog.connect("response", self.on_export_data_response)
            dialog.present()
            return
        dialog = Gtk.FileChooserNative(
            title="Export Data to CSV",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label="_Save",
            cancel_label="_Cancel",
        )
        self._active_native_dialog = dialog
        dialog.connect("response", self.on_export_data_response)
        dialog.connect("response", lambda *_args: setattr(self, "_active_native_dialog", None))
        dialog.show()

    def on_export_data_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            file_path = self._get_file_path(dialog)
            dialog.destroy()
            try:
                if not file_path:
                    raise ValueError("No file selected.")
                with open(file_path, 'w', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(["Chapter", "Competence (%)"])
                    for chapter, score in self.engine.competence.items():
                        writer.writerow([chapter, score])
                success_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Data exported successfully."
                )
                success_dialog.connect("response", lambda d, r: d.destroy())
                success_dialog.present()
            except Exception as e:
                error_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text=f"Error exporting data: {e}"
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()
        else:
            dialog.destroy()

    def on_export_template(self, button):
        if getattr(self, "_dialog_smoke_mode", False):
            dialog = self._harden_window(Gtk.FileChooserDialog(  # gtk4_lint:ignore
                title="Export Import Template",
                transient_for=self,
                action=Gtk.FileChooserAction.SAVE,
            ))
            dialog.add_buttons(
                "_Cancel", Gtk.ResponseType.CANCEL, "_Save", Gtk.ResponseType.ACCEPT
            )
            dialog.connect("response", self.on_export_template_response)
            dialog.present()
            return
        dialog = Gtk.FileChooserNative(
            title="Export Import Template",
            transient_for=self,
            action=Gtk.FileChooserAction.SAVE,
            accept_label="_Save",
            cancel_label="_Cancel",
        )
        self._active_native_dialog = dialog
        dialog.connect("response", self.on_export_template_response)
        dialog.connect("response", lambda *_args: setattr(self, "_active_native_dialog", None))
        dialog.show()

    def on_export_template_response(self, dialog, response):
        if response != Gtk.ResponseType.ACCEPT:
            dialog.destroy()
            return

        file_path = self._get_file_path(dialog)
        dialog.destroy()

        if not file_path:
            return

        json_template = {
            "chapter": "DCF Methods",
            "questions": [
                {
                    "question": "What is the main advantage of NPV?",
                    "options": ["Considers time value", "Easy to compute", "Ignores risk", "Uses profit"],
                    "correct": "Considers time value",
                    "explanation": "NPV discounts cash flows to present value."
                }
            ]
        }

        csv_template = (
            "chapter,question,option1,option2,option3,option4,correct,explanation\n"
            "DCF Methods,What is the main advantage of NPV?,Considers time value,Easy to compute,Ignores risk,Uses profit,Considers time value,NPV discounts cash flows to present value.\n"
        )

        try:
            if file_path.lower().endswith(".csv"):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(csv_template)
            else:
                if not file_path.lower().endswith(".json"):
                    file_path = file_path + ".json"
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(json_template, f, indent=2, ensure_ascii=False)

            success_dialog = self._new_message_dialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Template exported successfully."
            )
            success_dialog.connect("response", lambda d, r: d.destroy())
            success_dialog.present()
        except Exception as e:
            error_dialog = self._new_message_dialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=f"Error exporting template: {e}"
            )
            error_dialog.connect("response", lambda d, r: d.destroy())
            error_dialog.present()

    def on_reset_data(self, button):
        confirm_dialog = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Are you sure you want to reset all data?"
        )
        confirm_dialog.connect("response", self.on_reset_confirm)
        confirm_dialog.present()

    def on_reset_confirm(self, dialog, response):
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.engine.reset_data()
            self.update_dashboard()
            self.update_recommendations()
            self.update_daily_plan()
            self.update_streak_display()

    def on_view_health_log(self, button):
        log_path = os.path.expanduser("~/.config/studyplan/migration.log")
        if not os.path.exists(log_path):
            self._show_text_dialog("Data Health Log", "No health log found yet.", Gtk.MessageType.INFO)
            return

        try:
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except OSError as e:
            self._show_text_dialog("Data Health Log", f"Failed to read health log: {e}", Gtk.MessageType.ERROR)
            return

        self._show_scrolling_text("Data Health Log", content if content else "(log is empty)")

    def show_notification(self, title, message):
        self._show_text_dialog(title, message, Gtk.MessageType.INFO)

    def on_set_exam_date(self, _button):
        dialog = self._new_dialog(title="Set Exam Date", transient_for=self, modal=True)
        dialog.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_Set", Gtk.ResponseType.OK)
        content_area = dialog.get_content_area()

        calendar = Gtk.Calendar()
        if isinstance(self.engine.exam_date, datetime.date):
            try:
                calendar.select_month(self.engine.exam_date.month - 1, self.engine.exam_date.year)
                calendar.select_day(self.engine.exam_date.day)
            except Exception:
                pass
        content_area.append(calendar)

        dialog.connect("response", self.on_set_exam_date_response, calendar)
        dialog.present()

    def on_set_exam_date_response(self, dialog, response, calendar):
        if response == Gtk.ResponseType.OK:
            year: int | None = None
            month: int | None = None
            day: int | None = None
            try:
                date_val = calendar.get_date()
                if isinstance(date_val, datetime.date):
                    year, month, day = date_val.year, date_val.month, date_val.day
                elif isinstance(date_val, tuple) and len(date_val) >= 3:
                    y_val, m_val, d_val = date_val[0], date_val[1], date_val[2]
                    if isinstance(y_val, int) and isinstance(m_val, int) and isinstance(d_val, int):
                        year, month, day = y_val, m_val, d_val
            except Exception:
                year = month = day = None

            new_date = None
            try:
                if isinstance(year, int) and isinstance(month, int) and isinstance(day, int):
                    new_date = datetime.date(int(year), int(month), int(day))
            except Exception:
                if month is not None and month in range(0, 12):
                    try:
                        if isinstance(year, int) and isinstance(day, int):
                            new_date = datetime.date(int(year), int(month + 1), int(day))
                    except Exception:
                        new_date = None
            if new_date is None:
                error_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Invalid exam date. Please select a valid date."
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()
                dialog.destroy()
                return
            try:
                self.engine.exam_date = new_date
                self.exam_date = new_date
                try:
                    self.engine.save_data()
                except Exception:
                    pass
                self.update_exam_date_display()
                self.update_daily_plan()
                self.update_dashboard()
                self.update_recommendations()
            except Exception as e:
                error_dialog = self._new_message_dialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text=f"Invalid exam date: {e}"
                )
                error_dialog.connect("response", lambda d, r: d.destroy())
                error_dialog.present()

        dialog.destroy()

    def update_exam_date_display(self):
        exam_date = getattr(self.engine, "exam_date", None)
        if isinstance(exam_date, datetime.date):
            days_to_exam = (exam_date - datetime.date.today()).days
            if days_to_exam < 0:
                self.days_label.set_label(f"Exam date passed: {-days_to_exam} days ago")
                self.exam_warning_label.set_visible(True)
            else:
                self.days_label.set_label(f"Days to exam: {days_to_exam}")
                self.exam_warning_label.set_visible(False)
        else:
            self.days_label.set_label("Exam date not set")
            self.exam_warning_label.set_visible(True)

    def on_save_availability(self, _button):
        try:
            weekday_val = int(self.availability_weekday_spin.get_value())
            weekend_val = int(self.availability_weekend_spin.get_value())
        except Exception:
            weekday_val = 0
            weekend_val = 0

        self.engine.set_availability(weekday_val, weekend_val)
        try:
            self.engine.save_data()
        except Exception:
            pass
        self.update_availability_display()
        self.update_daily_plan()
        self.update_dashboard()
        self.update_recommendations()

    def update_availability_display(self):
        avail = getattr(self.engine, "availability", {})
        weekday = avail.get("weekday") if isinstance(avail, dict) else None
        weekend = avail.get("weekend") if isinstance(avail, dict) else None

        if isinstance(weekday, int):
            self.availability_weekday_spin.set_value(weekday)
        else:
            self.availability_weekday_spin.set_value(0)

        if isinstance(weekend, int):
            self.availability_weekend_spin.set_value(weekend)
        else:
            self.availability_weekend_spin.set_value(0)

        is_ready = self.engine.has_availability()
        self.availability_warning_label.set_visible(not is_ready)
        self.update_study_room_card()

    def update_save_status_display(self):
        last_saved = getattr(self.engine, "last_saved_at", None)
        if last_saved:
            self.last_saved_label.set_label(f"Last saved: {last_saved}")
        else:
            self.last_saved_label.set_label("Last saved: not yet")

        backup_ok = getattr(self.engine, "last_backup_ok", None)
        if backup_ok is False:
            self.backup_warning_label.set_visible(True)
        else:
            self.backup_warning_label.set_visible(False)

    def _close_aux_windows(self) -> bool:
        try:
            app = self.get_application()
            windows = app.get_windows() if app else []
        except Exception:
            windows = []
        for win in windows:
            if win is self:
                continue
            try:
                win.destroy()
            except Exception:
                pass
        dlg = getattr(self, "_active_native_dialog", None)
        if dlg is not None:
            try:
                dlg.hide()
            except Exception:
                pass
            self._active_native_dialog = None
        return False

    def run_dialog_smoke_test(self) -> bool:
        self._force_message_dialog_fallback = True
        self._dialog_smoke_mode = True
        self._closing_from_recap = True
        self._dialog_smoke_steps = [
            ("About", lambda: self.on_about(None, None)),
            ("Shortcuts", lambda: self.on_show_shortcuts(None, None)),
            ("Preferences", lambda: self.on_open_preferences(None, None)),
            ("Focus Allowlist", lambda: self.on_edit_focus_allowlist(None, None)),
            ("Switch Module", lambda: self.on_switch_module(None, None)),
            ("Manage Modules", lambda: self.on_manage_modules(None, None)),
            ("Module Editor", lambda: self.on_edit_module(None, None)),
            ("Set Exam Date", lambda: self.on_set_exam_date(None)),
            ("Import PDF", lambda: self.on_import_pdf(None)),
            ("Import AI Questions", lambda: self.on_import_ai_questions(None)),
            ("Export Data", lambda: self.on_export_data(None)),
            ("Export Template", lambda: self.on_export_template(None)),
            ("Reset Data", lambda: self.on_reset_data(None)),
            ("Health Log", lambda: self.on_view_health_log(None)),
            ("Debug Info", lambda: self.on_debug_info(None, None)),
            ("First Run Tour", lambda: self.on_first_run_tour("smoke", None)),
            ("Quiz", lambda: self.on_take_quiz(None)),
        ]
        self._dialog_smoke_index = 0
        GLib.timeout_add(200, self._run_next_dialog_smoke_step)
        GLib.timeout_add(6000, self._force_end_smoke_test)
        return False

    def _force_end_smoke_test(self) -> bool:
        if not getattr(self, "_dialog_smoke_mode", False):
            return False
        self._force_message_dialog_fallback = False
        self._dialog_smoke_mode = False
        self._close_aux_windows()
        try:
            self.close()
        except Exception:
            pass
        return False

    def _run_next_dialog_smoke_step(self) -> bool:
        if self._dialog_smoke_index >= len(self._dialog_smoke_steps):
            self._force_message_dialog_fallback = False
            self._dialog_smoke_mode = False
            GLib.timeout_add(200, self._close_aux_windows)
            def _close_main():
                self._closing_from_recap = True
                self.close()
            GLib.timeout_add(1000, _close_main)
            return False
        label, func = self._dialog_smoke_steps[self._dialog_smoke_index]
        self._dialog_smoke_index += 1
        try:
            func()
        except Exception as exc:
            self._log_error("dialog_smoke_test", exc)
        GLib.timeout_add(200, self._close_aux_windows)
        GLib.timeout_add(450, self._run_next_dialog_smoke_step)
        return False

    def on_close_request(self, *_args):
        self._set_pomodoro_active_state(False)
        if self._closing_from_recap:
            try:
                self.engine.save_data()
            except Exception:
                pass
            self.update_save_status_display()
            return False
        self._show_daily_recap()
        return True

    def _build_daily_recap_text(self) -> str:
        today = datetime.date.today()
        pomodoros = int(self.pomodoro_today_count or 0)
        quiz_q = int(self.quiz_questions_today or 0)
        quiz_sessions = int(self.quiz_sessions_today or 0)
        daily_plan = getattr(self, "_last_daily_plan", []) or []
        completed = 0
        for ch in daily_plan:
            try:
                if self._is_completed_today(ch):
                    completed += 1
            except Exception:
                pass
        focus_report = self._last_focus_report or ""
        next_topic = self._get_recommended_topic()
        lines = [
            f"Daily Recap • {today.isoformat()}",
            f"Pomodoros: {pomodoros}",
            f"Quiz questions: {quiz_q}  •  Quiz sessions: {quiz_sessions}",
            f"Daily plan: {completed}/{len(daily_plan)} completed" if daily_plan else "Daily plan: not set",
            f"Next focus: {next_topic}",
        ]
        if focus_report:
            lines.append(focus_report)
        return "\n".join(lines)

    def _show_daily_recap(self) -> None:
        dialog = self._new_message_dialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=self._build_daily_recap_text(),
        )
        dialog.connect("response", self._on_recap_close)
        dialog.present()

    def _on_recap_close(self, dialog, _response):
        dialog.destroy()
        self._closing_from_recap = True
        self.close()

    def on_focus_mode_toggled(self, button):
        try:
            self.focus_mode = bool(button.get_active())
        except Exception:
            self.focus_mode = False
        if getattr(self, "tools_box", None):
            self.tools_box.set_visible(not self.focus_mode)
        if getattr(self, "tools_label", None):
            self.tools_label.set_visible(not self.focus_mode)
        if getattr(self, "availability_expander", None):
            self.availability_expander.set_visible(not self.focus_mode)
        if getattr(self, "rec_expander", None):
            self.rec_expander.set_visible(not self.focus_mode)
        if getattr(self, "study_room_details_expander", None):
            try:
                self.study_room_details_expander.set_expanded(not self.focus_mode)
                self.study_room_details_expander.set_visible(not self.focus_mode)
            except Exception:
                pass
        self.update_dashboard()
        try:
            self.update_study_room_card()
        except Exception:
            pass

    def update_dashboard(self) -> None:  # pyright: ignore[reportGeneralTypeIssues]
        # Clear old dashboard
        child = self.dashboard.get_first_child()
        while child:
            self.dashboard.remove(child)
            child = self.dashboard.get_first_child()

        focus_mode = bool(getattr(self, "focus_mode", False))

        try:
            self._update_risk_manager_progress()
        except Exception:
            pass

        charts_available = (plt is not None and FigureCanvas is not None)
        if not charts_available:
            charts_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            charts_card.add_css_class("card")
            charts_title = Gtk.Label(label="Charts")
            charts_title.set_halign(Gtk.Align.START)
            charts_title.add_css_class("section-title")
            charts_body = Gtk.Label(label="Charts unavailable — install matplotlib to enable charts.")
            charts_body.set_halign(Gtk.Align.START)
            charts_body.set_wrap(True)
            charts_body.add_css_class("muted")
            charts_card.append(charts_title)
            charts_card.append(charts_body)
            self.dashboard.append(charts_card)

        # Safe exam-date handling (engine.reset_data() may set exam_date to None)
        today = datetime.date.today()
        today_iso = today.isoformat()
        if self.last_coach_date != today_iso:
            try:
                smart_day = self._get_smart_review_day()
                if smart_day is None:
                    smart_day = 6
                if today.weekday() == smart_day and getattr(self, "last_weekly_review_date", None) != today_iso:
                    day_name = today.strftime("%A")
                    self.send_notification(
                        "Weekly Review Day",
                        f"{day_name} review: do a 10‑min quiz + update your weakest topics.",
                    )
                    self.last_weekly_review_date = today_iso
                    self.save_preferences()
            except Exception:
                pass
            self.last_coach_date = today_iso
            try:
                self.save_preferences()
            except Exception:
                pass
            try:
                self.update_daily_plan()
            except Exception:
                pass
        engine_exam_date = getattr(self.engine, "exam_date", None)
        if engine_exam_date is None:
            days_remaining = None
            days_text = "Exam date not set"
        else:
            days_remaining = max(0, (engine_exam_date - today).days)
            days_text = str(days_remaining)

        # Onboarding (first-run helper)
        if not focus_mode and self._should_show_onboarding():
            self.dashboard.append(self._build_onboarding_card())

        if not self._has_chapters():
            empty_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            empty_card.add_css_class("card")
            empty_title = Gtk.Label(label="No Module Loaded")
            empty_title.set_halign(Gtk.Align.START)
            empty_title.add_css_class("section-title")
            empty_card.append(empty_title)
            empty_text = Gtk.Label(
                label="Add a module JSON to unlock chapters, quizzes, and schedules.\n"
                "Menu: Module → Manage Modules"
            )
            empty_text.set_halign(Gtk.Align.START)
            empty_text.set_wrap(True)
            empty_text.add_css_class("muted")
            empty_card.append(empty_text)
            self.dashboard.append(empty_card)
            self.update_save_status_display()
            return

        # Weekly summary export (auto, once per week)
        try:
            summary_path = os.path.expanduser("~/.config/studyplan/weekly_report.txt")
            os.makedirs(os.path.dirname(summary_path), exist_ok=True)
            week_number = today.isocalendar().week
            if getattr(self, "last_weekly_summary_week", None) != week_number:
                summary_lines = self._get_daily_summary_lines(
                    self._get_recommended_topic(), self._get_weak_chapter(60.0)
                )
                summary_text = "\n".join([
                    f"Week {week_number} Summary ({today.isoformat()}):",
                    *summary_lines[:2],
                ])
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write(summary_text + "\n")
                self.last_weekly_summary_week = week_number
                self.save_preferences()
        except Exception:
            pass

        # Coach briefing and actions
        try:
            readiness_info = self._compute_exam_readiness_details()
        except Exception:
            readiness_info = {"score": 0.0, "tier": "Foundation", "mastery_pct": 0.0, "comp_min": 0.0}
        pace_info = self._get_pace_info()
        pace_status = pace_info.get("status", "unknown")
        weak_chapter = self._get_weak_chapter(60.0)
        try:
            recommended_topic = weak_chapter or self._get_recommended_topic()
        except Exception:
            recommended_topic = weak_chapter or self.current_topic
        try:
            questions = self.engine.get_questions(recommended_topic)
            base_quiz_target = self._get_quiz_target_for_topic(recommended_topic, len(questions))
        except Exception:
            questions = []
            base_quiz_target = 8
        has_questions = bool(questions)
        if not has_questions:
            quiz_target = 0
        else:
            quiz_target = self._scale_quiz_target(
                base_quiz_target,
                len(questions),
                pace_status,
                len(self._last_daily_plan or []),
            )

        must_review_due = self._get_must_review_due_count(today)

        focus_goal = self._get_focus_goal_today(pace_info, len(self._last_daily_plan or []))
        try:
            verified_today = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
        except Exception:
            verified_today = 0.0
        focus_done = verified_today >= (focus_goal * 25)
        quiz_done = True if not has_questions else int(self.quiz_questions_today or 0) >= int(quiz_target)
        review_done = must_review_due == 0

        coach_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        coach_box.add_css_class("card")
        coach_warnings: list[str] = []

        coach_title = Gtk.Label(label="Coach Briefing")
        coach_title.set_halign(Gtk.Align.START)
        coach_title.add_css_class("coach-title")
        coach_box.append(coach_title)

        readiness_score = float(readiness_info.get("score", 0.0) or 0.0)
        readiness_tier = readiness_info.get("tier", "Foundation")
        readiness_bar = Gtk.ProgressBar()
        readiness_bar.set_fraction(max(0.0, min(1.0, readiness_score / 100.0)))
        readiness_bar.set_text(f"{readiness_score:.0f}% • {readiness_tier}")
        readiness_bar.set_show_text(True)
        coach_box.append(readiness_bar)

        try:
            mastery_pct = float(readiness_info.get("mastery_pct", 0) or 0)
            comp_avg = float(readiness_info.get("comp_avg", 0) or 0)
            quiz_avg = float(readiness_info.get("quiz_avg", 0) or 0)
            breakdown = Gtk.Label(
                label=f"Mastery {mastery_pct:.0f}% • Competence {comp_avg:.0f}% • Quiz {quiz_avg:.0f}%"
            )
            breakdown.set_halign(Gtk.Align.START)
            breakdown.add_css_class("muted")
            coach_box.append(breakdown)
        except Exception:
            pass
        try:
            drift_note = self._get_confidence_drift_note(recommended_topic)
            if drift_note:
                coach_warnings.append(drift_note)
        except Exception:
            pass
        try:
            retrieval_pct = self._get_retrieval_ratio_today()
            target_pct = self._get_retrieval_min_pct()
            if retrieval_pct is not None:
                retrieval_bar = Gtk.ProgressBar()
                retrieval_bar.set_fraction(min(1.0, retrieval_pct / max(1.0, target_pct)))
                retrieval_bar.set_show_text(True)
                retrieval_bar.set_text(f"Retrieval {retrieval_pct:.0f}% / {target_pct:.0f}%")
                try:
                    thresholds = self._get_auto_thresholds()
                    lag_days = float(thresholds.get("quiz_lag_days", 14.0))
                    sat_pct = float(thresholds.get("saturation_pct", 65.0))
                    sat_min = float(thresholds.get("saturation_minutes", 45.0))
                    reasons = []
                    try:
                        days = self.engine.get_days_remaining()
                    except Exception:
                        days = None
                    if isinstance(days, int):
                        reasons.append(f"exam in {days}d")
                    try:
                        pace_info = self.engine.get_pace_status()
                        pace_status = pace_info.get("status", "unknown")
                        if pace_status in ("behind", "ahead"):
                            reasons.append(f"pace {pace_status}")
                    except Exception:
                        pass
                    weekly_integrity = self._get_focus_integrity_weekly()
                    if weekly_integrity is not None and weekly_integrity < 70:
                        reasons.append("low integrity")
                    quality = self._get_recent_session_quality_stats()
                    if quality.get("total", 0) and (quality.get("low", 0) / max(1, quality.get("total", 0))) >= 0.4:
                        reasons.append("low session quality")
                    reason_text = ", ".join(reasons) if reasons else "auto‑tuned"
                    retrieval_bar.set_tooltip_text(
                        f"Auto‑tuned thresholds ({reason_text}).\n"
                        f"Retrieval min: {target_pct:.0f}%\n"
                        f"Quiz lag window: {lag_days:.0f} days\n"
                        f"Saturation: {sat_pct:.0f}% after {sat_min:.0f}m"
                    )
                except Exception:
                    pass
                coach_box.append(retrieval_bar)
        except Exception:
            retrieval_pct = None
            target_pct = self._get_retrieval_min_pct()
        try:
            exam_index = float(readiness_score)
            if pace_status == "behind":
                exam_index -= 10
            elif pace_status == "ahead":
                exam_index += 5
            if retrieval_pct is not None:
                if retrieval_pct < target_pct:
                    exam_index -= 10
                else:
                    exam_index += 5
            exam_index = max(0.0, min(100.0, exam_index))
            index_label = Gtk.Label(label=f"Exam Readiness Index: {exam_index:.0f}")
            index_label.set_halign(Gtk.Align.START)
            index_label.add_css_class("muted")
            coach_box.append(index_label)
        except Exception:
            pass
        try:
            saturation = self._get_topic_saturation_today()
            if saturation:
                topic, pct, total_minutes = saturation
                coach_warnings.append(
                    f"Balance check: {topic} is {pct:.0f}% of today's {total_minutes:.0f}m."
                )
        except Exception:
            pass

        try:
            raw = float(getattr(self, "pomodoro_minutes_today_raw", 0) or 0)
            verified = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
            if raw > 0:
                integrity = max(0.0, min(100.0, (verified / raw) * 100.0))
                if integrity < 70:
                    coach_warnings.append(
                        f"Focus integrity today: {integrity:.0f}% — stay in allowed apps."
                    )
        except Exception:
            pass
        try:
            weekly_integrity = self._get_focus_integrity_weekly()
            if weekly_integrity is not None:
                integ_label = Gtk.Label(label=f"Weekly focus integrity: {weekly_integrity:.0f}%")
                integ_label.set_halign(Gtk.Align.START)
                integ_label.add_css_class("muted")
                coach_box.append(integ_label)
        except Exception:
            pass
        if coach_warnings:
            main_warning = Gtk.Label(label=coach_warnings[0])
            main_warning.set_halign(Gtk.Align.START)
            main_warning.add_css_class("status-warn")
            coach_box.append(main_warning)
            if len(coach_warnings) > 1:
                detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                for note in coach_warnings[1:]:
                    lbl = Gtk.Label(label=note)
                    lbl.set_halign(Gtk.Align.START)
                    lbl.add_css_class("muted")
                    detail_box.append(lbl)
                revealer = Gtk.Revealer()
                revealer.set_reveal_child(False)
                revealer.set_child(detail_box)
                toggle = Gtk.Button(label="Show details")
                toggle.add_css_class("flat")
                def _toggle_details(btn):
                    showing = revealer.get_reveal_child()
                    revealer.set_reveal_child(not showing)
                    btn.set_label("Hide details" if not showing else "Show details")
                toggle.connect("clicked", _toggle_details)
                coach_box.append(toggle)
                coach_box.append(revealer)

        try:
            progress = getattr(self.engine, "progress_log", [])
            trend_points: list[tuple[datetime.date, float]] = []
            if isinstance(progress, list):
                for item in progress:
                    if not isinstance(item, dict):
                        continue
                    date_str = item.get("date")
                    try:
                        date_val = datetime.date.fromisoformat(date_str) if date_str else None
                    except Exception:
                        date_val = None
                    if not date_val:
                        continue
                    trend_points.append((date_val, float(item.get("overall_mastery", 0) or 0)))
            trend_points.sort(key=lambda x: x[0])
            if trend_points:
                cutoff = today - datetime.timedelta(days=6)
                recent = [p for p in trend_points if p[0] >= cutoff]
                if len(recent) >= 2:
                    delta = recent[-1][1] - recent[0][1]
                    if delta >= 1.5:
                        trend_text = f"Trend: improving (last 7d {delta:+.1f}%)"
                    elif delta <= -1.5:
                        trend_text = f"Trend: slipping (last 7d {delta:+.1f}%)"
                    else:
                        trend_text = "Trend: stable (last 7d)"
                    trend_label = Gtk.Label(label=trend_text)
                    trend_label.set_halign(Gtk.Align.START)
                    trend_label.add_css_class("muted")
                    coach_box.append(trend_label)
        except Exception:
            pass
        try:
            hindsight = self._compute_weekly_hindsight()
            if hindsight:
                best_date, best_minutes = hindsight
                day_name = best_date.strftime("%a")
                hindsight_text = (
                    f"Weekly hindsight: {day_name} was strongest "
                    f"({best_minutes:.0f} min). Repeat that rhythm."
                )
                hindsight_label = Gtk.Label(label=hindsight_text)
                hindsight_label.set_halign(Gtk.Align.START)
                hindsight_label.add_css_class("muted")
                coach_box.append(hindsight_label)
                week_key = self._get_week_key(today)
                if self.last_hindsight_week != week_key:
                    self.last_hindsight_week = week_key
                    self.save_preferences()
        except Exception:
            pass

        today_label = Gtk.Label(label=f"Today focus: {recommended_topic or '—'}")
        today_label.set_halign(Gtk.Align.START)
        today_label.add_css_class("muted")
        coach_box.append(today_label)
        note = self._get_confidence_note(recommended_topic)
        if note and recommended_topic:
            note_label = Gtk.Label(label=f"Coach note: {note}")
            note_label.set_halign(Gtk.Align.START)
            note_label.set_wrap(True)
            note_label.add_css_class("muted")
            coach_box.append(note_label)

        mission_lines = []
        mission_tasks = [(f"Focus {focus_goal}x Pomodoro", focus_done)]
        if has_questions:
            mission_tasks.append((f"Quiz {quiz_target} questions", quiz_done))
        if must_review_due:
            mission_tasks.append((f"Clear must-review ({must_review_due} due)", review_done))
        else:
            mission_tasks.append(("Clear must-review", review_done))
        for title, done in mission_tasks:
            icon = "x" if done else " "
            mission_lines.append(f"[{icon}] {title}")
        if not has_questions:
            mission_lines.append("Quiz mission locked — import questions")
        if weak_chapter:
            mission_lines.append(f"⚠ Mandatory focus: {weak_chapter} (until ≥60%)")
        coach_label = Gtk.Label(label="\n".join(mission_lines))
        coach_label.set_halign(Gtk.Align.START)
        coach_label.set_wrap(True)
        coach_label.add_css_class("muted")
        coach_box.append(coach_label)

        mission_done = sum(1 for _t, done in mission_tasks if done)
        mission_bar = Gtk.ProgressBar()
        mission_bar.set_fraction(mission_done / max(1, len(mission_tasks)))
        mission_bar.set_show_text(True)
        mission_bar.set_text(f"Mission progress: {mission_done}/{len(mission_tasks)}")
        coach_box.append(mission_bar)

        pace_label = Gtk.Label()
        pace_label.set_halign(Gtk.Align.START)
        pace_label.set_wrap(True)
        if pace_status == "behind":
            pace_label.set_text("Intervention: extra topic + shorter breaks until on pace.")
            pace_label.add_css_class("status-bad")
        elif pace_status == "ahead":
            pace_label.set_text("Deep dive unlocked: longer focus blocks on hardest topics.")
            pace_label.add_css_class("status-ok")
        elif pace_status == "on_track":
            pace_label.set_text("Pace: on track. Keep steady focus.")
            pace_label.add_css_class("status-ok")
        else:
            pace_label.set_text("Pace: set exam date to calibrate.")
            pace_label.add_css_class("status-warn")
        coach_box.append(pace_label)

        try:
            required_avg = float(pace_info.get("required_avg", 0) or 0)
            current_avg = float(pace_info.get("current_avg", 0) or 0)
            if required_avg > 0:
                daily_label = Gtk.Label(label=f"Daily target (min): {current_avg:.0f}/{required_avg:.0f}")
            else:
                daily_label = Gtk.Label(label=f"Daily target (min): {current_avg:.0f}")
            daily_label.set_halign(Gtk.Align.START)
            daily_label.add_css_class("muted")
            coach_box.append(daily_label)
        except Exception:
            pass
        try:
            floor = float(readiness_info.get("comp_min", 0) or 0)
            floor_label = Gtk.Label(label=f"Floor (weakest chapter): {floor:.0f}%")
            floor_label.set_halign(Gtk.Align.START)
            floor_label.add_css_class("muted")
            coach_box.append(floor_label)
        except Exception:
            pass
        coach_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        coach_next_btn = Gtk.Button(label="Coach Next")
        coach_next_btn.connect("clicked", self.on_do_coach_next)
        focus_btn = Gtk.Button(label="Start Focus")
        focus_btn.connect("clicked", self.on_focus_now)
        drill_btn = Gtk.Button(label="Drill Weak")
        drill_btn.connect("clicked", self.on_drill_weak)
        review_btn = Gtk.Button(label="Clear Reviews")
        review_btn.connect("clicked", self.on_clear_must_review)
        drill_btn.set_sensitive(has_questions)
        review_btn.set_sensitive(has_questions)
        if not has_questions:
            drill_btn.set_tooltip_text("Import questions to unlock drills.")
            review_btn.set_tooltip_text("Import questions to unlock reviews.")
        coach_next_btn.set_tooltip_text("Follow the coach pick with the next best action.")
        coach_actions.append(coach_next_btn)
        coach_actions.append(focus_btn)
        coach_actions.append(drill_btn)
        coach_actions.append(review_btn)
        coach_box.append(coach_actions)
        self.dashboard.append(coach_box)

        try:
            if isinstance(self.action_time_log, dict) and self.action_time_log:
                analytics = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                analytics.add_css_class("card")
                title = Gtk.Label(label="Time Analytics")
                title.set_halign(Gtk.Align.START)
                title.add_css_class("section-title")
                analytics.append(title)
                lines = []
                name_map = {
                    "pomodoro_focus": "Pomodoro (Focus)",
                    "pomodoro_recall": "Pomodoro (Recall)",
                    "quiz": "Quiz",
                    "drill": "Weak Drill",
                    "review": "Clear Reviews",
                }
                for key, stats in self.action_time_log.items():
                    if not isinstance(stats, dict):
                        continue
                    secs = float(stats.get("seconds", 0) or 0)
                    sessions = int(stats.get("sessions", 0) or 0)
                    if secs <= 0 or sessions <= 0:
                        continue
                    minutes = secs / 60.0
                    avg = minutes / sessions if sessions else minutes
                    name = name_map.get(key, key.replace("_", " ").title())
                    lines.append(f"{name}: {minutes:.0f}m • {sessions} sessions • avg {avg:.0f}m")
                if lines:
                    label = Gtk.Label(label="\n".join(lines))
                    label.set_halign(Gtk.Align.START)
                    label.set_wrap(True)
                    label.add_css_class("muted")
                    analytics.append(label)
                    self.dashboard.append(analytics)
        except Exception:
            pass
        try:
            def _topic_lines(topics: list[tuple[str, float]], limit: int) -> list[str]:
                lines = []
                for idx, (topic, secs) in enumerate(topics[:limit], start=1):
                    minutes = secs / 60.0
                    if minutes <= 0:
                        continue
                    lines.append(f"{idx}. {topic} — {minutes:.0f}m")
                return lines

            focus_topics = self._get_topic_time_window(7, kinds={"pomodoro_focus"})
            retrieval_topics = self._get_topic_time_window(
                7, kinds={"pomodoro_recall", "quiz", "drill", "review"}
            )
            today_topics = self._get_topic_time_window(1)

            focus_lines = _topic_lines(focus_topics, 5)
            if focus_lines:
                leaderboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                leaderboard.add_css_class("card")
                title = Gtk.Label(label="Focus Topics (7 days)")
                title.set_halign(Gtk.Align.START)
                title.add_css_class("section-title")
                leaderboard.append(title)
                label = Gtk.Label(label="\n".join(focus_lines))
                label.set_halign(Gtk.Align.START)
                label.set_wrap(True)
                label.add_css_class("muted")
                leaderboard.append(label)
                self.dashboard.append(leaderboard)

            retrieval_lines = _topic_lines(retrieval_topics, 5)
            if retrieval_lines:
                leaderboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                leaderboard.add_css_class("card")
                title = Gtk.Label(label="Retrieval Topics (7 days)")
                title.set_halign(Gtk.Align.START)
                title.add_css_class("section-title")
                leaderboard.append(title)
                label = Gtk.Label(label="\n".join(retrieval_lines))
                label.set_halign(Gtk.Align.START)
                label.set_wrap(True)
                label.add_css_class("muted")
                leaderboard.append(label)
                self.dashboard.append(leaderboard)

            today_lines = _topic_lines(today_topics, 3)
            if today_lines:
                leaderboard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                leaderboard.add_css_class("card")
                title = Gtk.Label(label="Today's Top Topics")
                title.set_halign(Gtk.Align.START)
                title.add_css_class("section-title")
                leaderboard.append(title)
                label = Gtk.Label(label="\n".join(today_lines))
                label.set_halign(Gtk.Align.START)
                label.set_wrap(True)
                label.add_css_class("muted")
                leaderboard.append(label)
                self.dashboard.append(leaderboard)
        except Exception:
            pass
        try:
            summary_lines = self._get_daily_summary_lines(recommended_topic, weak_chapter)
            if summary_lines:
                summary_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                summary_card.add_css_class("card")
                title = Gtk.Label(label="Daily Summary")
                title.set_halign(Gtk.Align.START)
                title.add_css_class("section-title")
                summary_card.append(title)
                label = Gtk.Label(label="\n".join(summary_lines[:2]))
                label.set_halign(Gtk.Align.START)
                label.set_wrap(True)
                label.add_css_class("muted")
                summary_card.append(label)
                self.dashboard.append(summary_card)
        except Exception:
            pass

        try:
            if charts_available:
                topics = list(self.engine.CHAPTERS)
                if topics:
                    comp = getattr(self.engine, "competence", {}) or {}
                    quiz = getattr(self.engine, "quiz_results", {}) or {}
                    def _safe_float(val):
                        try:
                            return float(val)
                        except Exception:
                            return 0.0
                    competence_vals = [_safe_float(comp.get(t, 0)) for t in topics]
                    mastery_vals = []
                    for t in topics:
                        m = self._get_topic_mastery_pct(t, min_total=0)
                        mastery_vals.append(m if m is not None else 0.0)
                    quiz_vals = [_safe_float(quiz.get(t, 0)) for t in topics]

                    drift_vals = []
                    for i, t in enumerate(topics):
                        drift = competence_vals[i] - max(mastery_vals[i], quiz_vals[i])
                        drift_vals.append(max(0.0, drift))

                    top = sorted(enumerate(drift_vals), key=lambda x: x[1], reverse=True)[:6]
                    top = [t for t in top if t[1] > 0]
                    if top:
                        top_indices = [i for i, _ in top]
                        labels = [topics[i] for i in top_indices]
                        values = [drift_vals[i] for i in top_indices]
                        plt_module = plt
                        canvas_cls = FigureCanvas
                        if plt_module is None or canvas_cls is None:
                            raise RuntimeError("Charts unavailable")
                        fig, ax = plt_module.subplots(figsize=(5.6, 3.0), dpi=100)
                        fig.patch.set_facecolor("#232428")
                        ax.set_facecolor("#232428")
                        ax.bar(range(len(labels)), values, color="#f6c453")
                        ax.set_ylim(0, 100)
                        ax.set_ylabel("Gap %", color="#e6e6e6")
                        ax.set_xticks(range(len(labels)))
                        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8, color="#e6e6e6")
                        ax.tick_params(axis="y", colors="#e6e6e6")
                        for spine in ax.spines.values():
                            spine.set_color("#3a3c43")
                        ax.grid(axis="y", color="#3a3c43", linestyle="--", linewidth=0.6, alpha=0.6)
                        ax.set_title("Confidence Drift (Top Gaps)", color="#e6e6e6")
                        fig.tight_layout()
                        canvas = canvas_cls(fig)
                        canvas.set_tooltip_text("Tip: hold Ctrl and scroll to zoom charts.")
                        canvas.set_size_request(430, 240)
                        self.dashboard.append(canvas)
                        try:
                            plt_module.close(fig)
                        except Exception:
                            pass
        except Exception:
            pass

        if not focus_mode:
            try:
                next_action = self._build_next_action_card(
                    recommended_topic=recommended_topic,
                    weak_chapter=weak_chapter,
                    must_review_due=must_review_due,
                    has_questions=has_questions,
                    pace_status=pace_status,
                )
                self.dashboard.append(next_action)
            except Exception:
                pass
            try:
                recap = getattr(self, "_last_session_recap", None)
                if isinstance(recap, dict) and recap.get("lines"):
                    recap_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    recap_card.add_css_class("card")
                    recap_title = recap.get("title", "Session recap")
                    when = recap.get("when")
                    title_text = f"{recap_title}" if not when else f"{recap_title} • {when}"
                    title = Gtk.Label(label=title_text)
                    title.set_halign(Gtk.Align.START)
                    title.add_css_class("section-title")
                    recap_card.append(title)
                    recap_label = Gtk.Label(label="\n".join(recap.get("lines", [])))
                    recap_label.set_halign(Gtk.Align.START)
                    recap_label.set_wrap(True)
                    recap_label.add_css_class("muted")
                    recap_card.append(recap_label)
                    self.dashboard.append(recap_card)
            except Exception:
                pass
            try:
                counts = getattr(self.engine, "difficulty_counts", {}) or {}
                totals = {}
                if isinstance(counts, dict):
                    for ch, items in counts.items():
                        if not isinstance(items, dict):
                            continue
                        total = 0
                        for val in items.values():
                            try:
                                total += int(val)
                            except Exception:
                                pass
                        if total > 0:
                            totals[ch] = total
                if totals:
                    hardest = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:3]
                    hard_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    hard_card.add_css_class("card")
                    hard_title = Gtk.Label(label="Hardest Concepts")
                    hard_title.set_halign(Gtk.Align.START)
                    hard_title.add_css_class("section-title")
                    hard_card.append(hard_title)
                    lines = [f"{i+1}. {ch} — {cnt} misses" for i, (ch, cnt) in enumerate(hardest)]
                    hard_label = Gtk.Label(label="\n".join(lines))
                    hard_label.set_halign(Gtk.Align.START)
                    hard_label.set_wrap(True)
                    hard_label.add_css_class("muted")
                    hard_card.append(hard_label)
                    self.dashboard.append(hard_card)
            except Exception:
                pass
            try:
                recap_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                recap_card.add_css_class("card")
                recap_title = Gtk.Label(label="Coach Recap (7 days)")
                recap_title.set_halign(Gtk.Align.START)
                recap_title.add_css_class("section-title")
                recap_card.append(recap_title)
                lines = []
                cutoff = today - datetime.timedelta(days=6)
                progress = getattr(self.engine, "progress_log", [])
                recap_points: list[tuple[datetime.date, float, float]] = []
                if isinstance(progress, list):
                    for item in progress:
                        if not isinstance(item, dict):
                            continue
                        date_str = item.get("date")
                        try:
                            date_val = datetime.date.fromisoformat(date_str) if date_str else None
                        except Exception:
                            date_val = None
                        if not date_val or date_val < cutoff:
                            continue
                        mastery_val = float(item.get("overall_mastery", 0) or 0)
                        minutes_val = float(item.get("total_minutes", 0) or 0)
                        recap_points.append((date_val, mastery_val, minutes_val))
                recap_points.sort(key=lambda x: x[0])
                if recap_points:
                    minutes_week = recap_points[-1][2] - recap_points[0][2] if len(recap_points) >= 2 else recap_points[-1][2]
                    lines.append(f"Total focus time: {max(0, minutes_week):.0f} min")
                    delta = recap_points[-1][1] - recap_points[0][1]
                    lines.append(f"Mastery change: {delta:+.1f}%")
                study_days = getattr(self.engine, "study_days", set()) or set()
                active_days = 0
                for d in study_days:
                    try:
                        date_val = d if isinstance(d, datetime.date) else datetime.date.fromisoformat(d)
                    except Exception:
                        continue
                    if date_val >= cutoff:
                        active_days += 1
                lines.append(f"Active days: {active_days}/7")
                if pace_status != "unknown":
                    lines.append(f"Pace: {pace_status.replace('_', ' ')}")
                if not lines:
                    lines.append("Keep logging study time to unlock the recap.")
                recap_label = Gtk.Label(label="\n".join(lines))
                recap_label.set_halign(Gtk.Align.START)
                recap_label.set_wrap(True)
                recap_label.add_css_class("muted")
                recap_card.append(recap_label)
                self.dashboard.append(recap_card)
            except Exception:
                pass

        if not focus_mode:
            today_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            today_card.add_css_class("card")
            today_title = Gtk.Label(label="Today Overview")
            today_title.set_halign(Gtk.Align.START)
            today_title.add_css_class("section-title")
            today_card.append(today_title)
            mission_done = sum(1 for _t, done in mission_tasks if done)
            mission_total = len(mission_tasks)
            pace_label_text = "Pace: set exam date" if pace_status == "unknown" else f"Pace: {pace_status.replace('_', ' ')}"
            today_lines = [
                f"Next focus: {recommended_topic}",
                f"Mission: {mission_done}/{mission_total} complete",
                f"Readiness: {readiness_score:.0f}% • {readiness_tier}",
                f"{pace_label_text}",
            ]
            if must_review_due:
                today_lines.append(f"Must-review due: {must_review_due}")
            if weak_chapter:
                today_lines.append(f"Mandatory focus: {weak_chapter}")
            if not has_questions:
                today_lines.append("Quiz: import questions to unlock")
            today_lines.append(f"Days to exam: {days_text}")
            today_label = Gtk.Label(label="\n".join(today_lines))
            today_label.set_halign(Gtk.Align.START)
            today_label.set_wrap(True)
            today_label.add_css_class("muted")
            today_card.append(today_label)
            self.dashboard.append(today_card)

        if focus_mode:
            mini = Gtk.Label(
                label="Focus Mode: Coach briefing only. Finish today's mission before diving deeper."
            )
            mini.set_halign(Gtk.Align.START)
            mini.set_wrap(True)
            mini.add_css_class("muted")
            self.dashboard.append(mini)
            self.update_save_status_display()
            return

        # Overall mastery (use summary when available for speed)
        overall_mastery = 0.0
        retention_progress = None
        mastery_summary = None
        if hasattr(self.engine, "get_mastery_summary"):
            try:
                mastery_summary = self.engine.get_mastery_summary()
                total_q = float(mastery_summary.get("total", 0))
                mastered_q = float(mastery_summary.get("mastered", 0))
                learning_q = float(mastery_summary.get("learning", 0))
                overall_mastery = (mastered_q / total_q * 100.0) if total_q > 0 else 0.0
                retention_progress = ((mastered_q + learning_q) / total_q * 100.0) if total_q > 0 else None
            except Exception:
                mastery_summary = None
        if mastery_summary is None:
            try:
                overall_mastery = float(self.engine.get_overall_mastery())
            except Exception:
                overall_mastery = 0.0
            try:
                mastery_stats = self._calculate_mastery_distribution()
                total_cards = float(mastery_stats.get("total", 0))
                mastered_cards = float(mastery_stats.get("mastered", 0))
                learning_cards = float(mastery_stats.get("learning", 0))
                retention_progress = ((mastered_cards + learning_cards) / total_cards * 100.0) if total_cards > 0 else None
            except Exception:
                retention_progress = None

        header = Gtk.Label()
        header.set_markup(f"<b><big>Overall Mastery</big></b>\n{overall_mastery:.1f}%")
        header.set_halign(Gtk.Align.START)
        header.add_css_class("title")
        header.set_tooltip_text(
            "Mastery reflects SRS review stability (repeated reviews over time). "
            "Competence reflects performance and can rise faster."
        )
        self.dashboard.append(header)

        bar = Gtk.ProgressBar()
        bar.set_fraction(max(0.0, min(1.0, overall_mastery / 100.0)))
        bar.set_show_text(True)
        bar.set_text(f"{overall_mastery:.1f}%")
        bar.set_tooltip_text(
            "Mastery grows as cards are reviewed and stabilized by SRS, "
            "so it can lag behind competence."
        )
        if overall_mastery < 50:
            bar.add_css_class("error")
        elif overall_mastery < 80:
            bar.add_css_class("warning")
        else:
            bar.add_css_class("success")
        self.dashboard.append(bar)
        retention_label = None
        if retention_progress is not None:
            retention_label = Gtk.Label(
                label=f"Retention progress (learning + mastered): {retention_progress:.1f}%"
            )
            retention_label.set_halign(Gtk.Align.START)
            retention_label.set_wrap(True)
            retention_label.add_css_class("hint")
            retention_label.set_visible(False)
            self.dashboard.append(retention_label)
        mastery_note = Gtk.Label(
            label="Mastery = retention (SRS). Competence = performance."
        )
        mastery_note.set_halign(Gtk.Align.START)
        mastery_note.set_wrap(True)
        mastery_note.add_css_class("hint")
        mastery_note.set_visible(False)
        motion = Gtk.EventControllerMotion()
        def _show_hint(*_args):
            mastery_note.set_visible(True)
            if retention_label is not None:
                retention_label.set_visible(True)
        def _hide_hint(*_args):
            mastery_note.set_visible(False)
            if retention_label is not None:
                retention_label.set_visible(False)
        motion.connect("enter", _show_hint)
        motion.connect("leave", _hide_hint)
        bar.add_controller(motion)
        motion_header = Gtk.EventControllerMotion()
        motion_header.connect("enter", _show_hint)
        motion_header.connect("leave", _hide_hint)
        header.add_controller(motion_header)
        self.dashboard.append(mastery_note)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("rule")
        self.dashboard.append(sep)

        # Pie chart (optional)
        if charts_available:
            try:
                is_compact = bool(getattr(self, "_compact_mode", False))
                mastery_stats = self._calculate_mastery_distribution()
                mastered = int(mastery_stats.get("mastered", 0))
                learning = int(mastery_stats.get("learning", 0))
                new_cards = int(mastery_stats.get("new", 0))
                sizes = [mastered, learning, new_cards]
                total_cards = sum(sizes)

                overdue_cards = 0
                try:
                    for chapter in self.engine.CHAPTERS:
                        for card in self.engine.srs_data.get(chapter, []) or []:
                            if self.engine.is_overdue(card, today):
                                overdue_cards += 1
                except Exception:
                    overdue_cards = 0

                if total_cards > 0:
                    def _pct(pct):
                        return f"{pct:.0f}%" if pct >= 6 else ""

                    fig_w, fig_h = (4.6, 3.6) if not is_compact else (4.2, 3.1)
                    plt_module = plt
                    canvas_cls = FigureCanvas
                    if plt_module is None or canvas_cls is None:
                        raise RuntimeError("Charts unavailable")
                    fig, ax = plt_module.subplots(figsize=(fig_w, fig_h), dpi=110)
                    fig.patch.set_facecolor("#232428")
                    ax.set_facecolor("#232428")
                    colors = ["#4fd1c5", "#f6c453", "#b794f4"]
                    pie_result = ax.pie(
                        sizes,
                        labels=None,
                        autopct=_pct,
                        pctdistance=0.78,
                        startangle=90,
                        counterclock=False,
                        colors=colors,
                        textprops={"fontsize": 9, "color": "#e6e6e6", "fontweight": "bold"},
                        wedgeprops={"linewidth": 1.1, "edgecolor": "#1e1f22", "width": 0.35},
                    )
                    wedges = pie_result[0]
                    autotexts = pie_result[2] if len(pie_result) > 2 else []
                    for t in autotexts:
                        t.set_fontsize(9)
                        t.set_color("#e6e6e6")

                    ax.text(
                        0,
                        0.10,
                        f"{total_cards}",
                        ha="center",
                        va="center",
                        color="#e6e6e6",
                        fontsize=13,
                        fontweight="bold",
                    )
                    ax.text(
                        0,
                        -0.08,
                        "cards",
                        ha="center",
                        va="center",
                        color="#aab0bb",
                        fontsize=9,
                    )
                    if overdue_cards > 0:
                        ax.text(
                            0,
                            -0.28,
                            f"{overdue_cards} overdue",
                            ha="center",
                            va="center",
                            color="#f6c453",
                            fontsize=8,
                        )

                    legend_labels = [
                        f"Mastered {mastered}",
                        f"Learning {learning}",
                        f"New {new_cards}",
                    ]
                    ax.legend(
                        wedges,
                        legend_labels,
                        loc="lower center",
                        bbox_to_anchor=(0.5, -0.06),
                        ncol=3,
                        frameon=False,
                        labelcolor="#c9cdd4",
                        fontsize=9,
                    )
                    ax.set_title("Mastery Distribution (SRS)", color="#e6e6e6", fontsize=11, pad=8)
                    ax.set_aspect("equal")
                    fig.subplots_adjust(bottom=0.18)
                    canvas = canvas_cls(fig)
                    canvas.set_tooltip_text("Tip: hold Ctrl and scroll to zoom charts.")
                    if is_compact:
                        canvas.set_size_request(360, 260)
                    else:
                        canvas.set_size_request(400, 300)
                    self.dashboard.append(canvas)
                    try:
                        plt_module.close(fig)
                    except Exception:
                        pass
            except Exception as e:
                print(f"Chart error: {e}")

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("rule")
        self.dashboard.append(sep)

        # Progress over time chart
        if charts_available:
            try:
                progress = getattr(self.engine, "progress_log", [])
                progress_points: list[tuple[datetime.date, float, float]] = []
                if isinstance(progress, list):
                    for item in progress:
                        if not isinstance(item, dict):
                            continue
                        date_str = item.get("date")
                        try:
                            date_val = datetime.date.fromisoformat(date_str) if date_str else None
                        except Exception:
                            date_val = None
                        if not date_val:
                            continue
                        try:
                            mastery_val = float(item.get("overall_mastery", 0) or 0)
                        except Exception:
                            mastery_val = 0.0
                        try:
                            minutes_val = float(item.get("total_minutes", 0) or 0)
                        except Exception:
                            minutes_val = 0.0
                        progress_points.append((date_val, mastery_val, minutes_val))
                progress_points.sort(key=lambda x: x[0])
                if len(progress_points) >= 2:
                    dates = [p[0] for p in progress_points]
                    masteries = [p[1] for p in progress_points]
                    minutes_series = [p[2] for p in progress_points]
                    dates_series: list[Any] = dates
                    plt_module = plt
                    canvas_cls = FigureCanvas
                    if plt_module is None or canvas_cls is None:
                        raise RuntimeError("Charts unavailable")
                    fig, ax = plt_module.subplots(figsize=(5, 3.2), dpi=100)
                    fig.patch.set_facecolor("#232428")
                    ax.set_facecolor("#232428")
                    mastery_line, = ax.plot(dates_series, masteries, color="#4fd1c5", linewidth=2, label="Mastery %")
                    ax.set_ylim(0, 100)
                    ax.set_ylabel("Mastery %", color="#4fd1c5")
                    ax.tick_params(axis="y", colors="#4fd1c5")
                    ax2 = ax.twinx()
                    minutes_line, = ax2.plot(dates_series, minutes_series, color="#f6c453", linewidth=1.6, label="Total Minutes")
                    ax2.set_ylabel("Total Minutes", color="#f6c453")
                    ax2.tick_params(axis="y", colors="#f6c453")
                    ax.set_title("Progress Over Time", color="#e6e6e6")
                    ax.tick_params(colors="#e6e6e6")
                    for spine in ax.spines.values():
                        spine.set_color("#3a3c43")
                    for spine in ax2.spines.values():
                        spine.set_color("#3a3c43")
                    ax.grid(color="#3a3c43", linestyle="--", linewidth=0.6, alpha=0.6)
                    ax.legend(handles=[mastery_line, minutes_line], loc="upper left", fontsize=8, facecolor="#232428", framealpha=0.6)
                    fig.autofmt_xdate()
                    fig.tight_layout()
                    canvas = canvas_cls(fig)
                    canvas.set_tooltip_text("Tip: hold Ctrl and scroll to zoom charts.")
                    canvas.set_size_request(400, 260)
                    self.dashboard.append(canvas)
                    try:
                        plt_module.close(fig)
                    except Exception:
                        pass
                else:
                    empty_progress = Gtk.Label(label="Progress chart needs at least 2 days of data.")
                    empty_progress.set_halign(Gtk.Align.START)
                    empty_progress.add_css_class("muted")
                    self.dashboard.append(empty_progress)
            except Exception as e:
                print(f"Progress chart error: {e}")

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("rule")
        self.dashboard.append(sep)

        # Per-topic snapshot chart
        if charts_available:
            try:
                topics = list(self.engine.CHAPTERS)
                if not topics:
                    raise ValueError("No topics")
                comp = getattr(self.engine, "competence", {}) or {}
                quiz = getattr(self.engine, "quiz_results", {}) or {}
                def _safe_float(val):
                    try:
                        return float(val)
                    except Exception:
                        return 0.0
                # If many chapters, focus on the lowest-competence ones for readability.
                subtitle = "All topics"
                if len(topics) > 12:
                    topics = sorted(topics, key=lambda ch: _safe_float(comp.get(ch, 0)))[:12]
                    subtitle = "Top 12 priority"

                competence_vals = []
                mastery_vals = []
                quiz_vals = []
                for ch in topics:
                    competence_vals.append(_safe_float(comp.get(ch, 0)))
                    quiz_vals.append(_safe_float(quiz.get(ch, 0)))
                    try:
                        stats = self.engine.get_mastery_stats(ch)
                        total_cards_val: float = float(stats.get("total", 0) or 0)
                        mastered_cards_val: float = float(stats.get("mastered", 0) or 0)
                        mastery_vals.append((mastered_cards_val / total_cards_val * 100.0) if total_cards_val > 0 else 0.0)
                    except Exception:
                        mastery_vals.append(0.0)

                fig_w, fig_h = (6.2, 3.4) if not is_compact else (5.6, 3.0)
                plt_module = plt
                canvas_cls = FigureCanvas
                if plt_module is None or canvas_cls is None:
                    raise RuntimeError("Charts unavailable")
                fig, ax = plt_module.subplots(figsize=(fig_w, fig_h), dpi=100)
                fig.patch.set_facecolor("#232428")
                ax.set_facecolor("#232428")
                x = list(range(len(topics)))
                width = 0.25
                ax.bar([i - width for i in x], competence_vals, width, color="#4fd1c5", label="Competence")
                ax.bar(x, mastery_vals, width, color="#b794f4", label="Mastery")
                ax.bar([i + width for i in x], quiz_vals, width, color="#f6c453", label="Quiz")
                ax.set_ylim(0, 100)
                ax.set_ylabel("%", color="#e6e6e6")
                ax.set_xticks(x)
                ax.set_xticklabels(topics, rotation=35, ha="right", fontsize=8, color="#e6e6e6")
                ax.tick_params(axis="y", colors="#e6e6e6")
                for spine in ax.spines.values():
                    spine.set_color("#3a3c43")
                ax.grid(axis="y", color="#3a3c43", linestyle="--", linewidth=0.6, alpha=0.6)
                ax.set_title(f"Per-Topic Snapshot ({subtitle})", color="#e6e6e6")
                ax.legend(loc="upper right", fontsize=8, facecolor="#232428", framealpha=0.6)
                fig.tight_layout()
                canvas = canvas_cls(fig)
                canvas.set_tooltip_text("Tip: hold Ctrl and scroll to zoom charts.")
                canvas.set_size_request(430, 260)
                self.dashboard.append(canvas)
                try:
                    plt_module.close(fig)
                except Exception:
                    pass
            except Exception as e:
                print(f"Per-topic chart error: {e}")

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("rule")
        self.dashboard.append(sep)

        # Study time stats
        try:
            total_pomodoro = int(self.engine.pomodoro_log.get("total_minutes", 0))
        except Exception:
            total_pomodoro = 0

        try:
            total_sessions = len(getattr(self.engine, "study_days", []))
        except Exception:
            total_sessions = 0

        historical_avg = (total_pomodoro / total_sessions) if total_sessions > 0 else 0.0

        try:
            remaining_minutes = int(self.engine.get_remaining_minutes_needed())
        except Exception:
            remaining_minutes = 0

        if isinstance(days_remaining, int):
            days_divisor = max(1, days_remaining)
            required_avg = remaining_minutes / days_divisor
            required_avg_display = f"{required_avg:.1f} min"
        else:
            required_avg = 0.0
            required_avg_display = "N/A"

        # If Study Hub totals exist, use them for a stricter daily requirement
        try:
            hub = getattr(self.engine, "study_hub_stats", {})
            if isinstance(hub, dict) and hub.get("total_questions"):
                total_q = int(hub.get("total_questions", 0))
                taken = int(hub.get("questions_taken", 0))
                avg_answer = int(hub.get("avg_answer_seconds", 0))
                remaining_q = max(0, total_q - taken)
                if remaining_q and avg_answer and isinstance(days_remaining, int):
                    days_divisor = max(1, days_remaining)
                    hub_required = (remaining_q * avg_answer) / 60 / days_divisor
                    required_avg = max(required_avg, hub_required)
                    required_avg_display = f"{required_avg:.1f} min"
        except Exception:
            pass

        stats_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        stats_card.add_css_class("card")
        stats_title = Gtk.Label(label="Study Snapshot")
        stats_title.set_halign(Gtk.Align.START)
        stats_title.add_css_class("section-title")
        stats_card.append(stats_title)
        stats_lines = [
            f"Total study time: {total_pomodoro} min",
            f"Study sessions: {total_sessions}",
            f"Required avg per day: {required_avg_display}",
            f"Historical avg per day: {historical_avg:.1f} min",
            f"Days to exam: {days_text}",
        ]
        try:
            study_days = getattr(self.engine, "study_days", set()) or set()
            last_date = None
            for day in study_days:
                if isinstance(day, datetime.date):
                    dval = day
                elif isinstance(day, str):
                    try:
                        dval = datetime.date.fromisoformat(day)
                    except Exception:
                        continue
                else:
                    continue
                if last_date is None or dval > last_date:
                    last_date = dval
            if last_date:
                delta_days = (today - last_date).days
                if delta_days <= 0:
                    last_line = "Last study: today"
                elif delta_days == 1:
                    last_line = "Last study: yesterday"
                else:
                    last_line = f"Last study: {delta_days} days ago"
            else:
                last_line = "Last study: none yet"
            stats_lines.insert(2, last_line)
        except Exception:
            pass
        try:
            raw = float(getattr(self, "pomodoro_minutes_today_raw", 0) or 0)
            verified = float(getattr(self, "pomodoro_minutes_today_verified", 0) or 0)
            if raw > 0:
                integrity = max(0.0, min(100.0, (verified / raw) * 100.0))
                stats_lines.insert(3, f"Focus integrity (today): {integrity:.0f}%")
        except Exception:
            pass
        stats_label = Gtk.Label(label="\n".join(stats_lines))
        stats_label.set_halign(Gtk.Align.START)
        stats_label.set_wrap(True)
        stats_label.add_css_class("muted")
        stats_card.append(stats_label)
        self.dashboard.append(stats_card)

        # Weekly summary (last 7 days)
        try:
            progress = getattr(self.engine, "progress_log", [])
            weekly_points: list[tuple[datetime.date, float, float]] = []
            active_days_week: int | None = None
            try:
                study_days = getattr(self.engine, "study_days", set()) or set()
                active_dates = set()
                for day in study_days:
                    if isinstance(day, datetime.date):
                        dval = day
                    elif isinstance(day, str):
                        try:
                            dval = datetime.date.fromisoformat(day)
                        except Exception:
                            continue
                    else:
                        continue
                    active_dates.add(dval)
                cutoff = today - datetime.timedelta(days=6)
                active_days_week = len([d for d in active_dates if d >= cutoff])
            except Exception:
                active_days_week = None
            if isinstance(progress, list):
                for item in progress:
                    if not isinstance(item, dict):
                        continue
                    date_str = item.get("date")
                    try:
                        date_val = datetime.date.fromisoformat(date_str) if date_str else None
                    except Exception:
                        date_val = None
                    if not date_val:
                        continue
                    weekly_points.append(
                        (
                            date_val,
                            float(item.get("overall_mastery", 0) or 0),
                            float(item.get("total_minutes", 0) or 0),
                        )
                    )
            weekly_points.sort(key=lambda x: x[0])
            if weekly_points:
                cutoff = today - datetime.timedelta(days=6)
                recent_points = [p for p in weekly_points if p[0] >= cutoff]
                if recent_points:
                    # Use the last point before cutoff as baseline when available
                    baseline = None
                    for p in reversed(weekly_points):
                        if p[0] < cutoff:
                            baseline = p
                            break
                    baseline_minutes = float(baseline[2]) if baseline else 0.0
                    baseline_mastery = float(baseline[1]) if baseline else float(recent_points[0][1])
                    minutes_last = float(recent_points[-1][2])
                    delta_minutes = max(0.0, minutes_last - baseline_minutes)
                    mastery_last = float(recent_points[-1][1])
                    delta_mastery = mastery_last - baseline_mastery
                    span_days = max(1, (recent_points[-1][0] - recent_points[0][0]).days + 1)
                    avg_daily = delta_minutes / span_days
                    weekly_text = (
                        f"Last {span_days} days\n"
                        f"Total minutes: {delta_minutes:.0f}\n"
                        f"Avg per day: {avg_daily:.0f} min\n"
                        f"Mastery change: {delta_mastery:+.1f}%"
                    )
                    if active_days_week is not None:
                        weekly_text += f"\nActive days: {active_days_week}/{min(7, span_days)}"
                    weekly_label = Gtk.Label(label=weekly_text)
                    weekly_label.set_halign(Gtk.Align.START)
                    weekly_label.set_wrap(True)
                    weekly_label.add_css_class("muted")
                    weekly_card = self._wrap_expander_card("Weekly Summary (Last 7 Days)", weekly_label, expanded=False)
                    self.dashboard.append(weekly_card)
                else:
                    fallback = "Weekly Summary: not enough data yet."
                    if active_days_week is not None:
                        fallback = f"{fallback}\nActive days: {active_days_week}/7"
                    weekly_label = Gtk.Label(label=fallback)
                    weekly_label.set_halign(Gtk.Align.START)
                    weekly_label.set_wrap(True)
                    weekly_label.add_css_class("muted")
                    weekly_card = self._wrap_expander_card("Weekly Summary (Last 7 Days)", weekly_label, expanded=False)
                    self.dashboard.append(weekly_card)
        except Exception:
            pass

        # Plan view (next 7 days)
        try:
            schedule = []
            if isinstance(self.engine.exam_date, datetime.date) and self.engine.has_availability():
                schedule = self.engine.generate_study_schedule(days=7)

            if not isinstance(self.engine.exam_date, datetime.date):
                schedule_text = "Set an exam date to generate a schedule."
            elif not self.engine.has_availability():
                schedule_text = "Set availability minutes to generate a schedule."
            else:
                lines = []
                for item in schedule:
                    date_str = item.get("date", "")
                    minutes = int(item.get("minutes", 0) or 0)
                    topics = item.get("topics", []) or []
                    per_topic = int(item.get("minutes_per_topic", 0) or 0)
                    if minutes <= 0:
                        lines.append(f"{date_str}: 0 min (no availability)")
                    elif item.get("blocks"):
                        block_lines = []
                        for blk in item.get("blocks", []):
                            kind = blk.get("kind", "Focus")
                            topic = blk.get("topic", "")
                            mins = int(blk.get("minutes", 0) or 0)
                            if topic:
                                block_lines.append(f"- {kind} {mins}m: {topic}")
                            else:
                                block_lines.append(f"- {kind} {mins}m")
                        lines.append(f"{date_str}: {minutes} min\n  " + "\n  ".join(block_lines))
                    elif topics:
                        topic_str = ", ".join(topics)
                        lines.append(f"{date_str}: {minutes} min (~{per_topic} min/topic) — {topic_str}")
                    else:
                        lines.append(f"{date_str}: {minutes} min")
                schedule_text = "\n".join(lines)

            schedule_label = Gtk.Label(label=schedule_text)
            schedule_label.set_halign(Gtk.Align.START)
            schedule_label.set_wrap(True)
            schedule_label.add_css_class("muted")

            plan_card = self._wrap_expander_card("Plan View (Next 7 Days)", schedule_label, expanded=False)
            self.dashboard.append(plan_card)
        except Exception:
            pass

        # Insights and detailed stats (cards)
        if not focus_mode:
            try:
                mastery = self._calculate_mastery_distribution()
                total_questions = 0
                try:
                    total_questions = sum(len(self.engine.get_questions(ch)) for ch in self.engine.CHAPTERS)
                except Exception:
                    total_questions = 0

                if mastery_summary is None and hasattr(self.engine, "get_mastery_summary"):
                    mastery_summary = self.engine.get_mastery_summary()
                if mastery_summary:
                    avg_interval = float(mastery_summary.get("avg_interval", 0.0))
                    avg_ease = float(mastery_summary.get("avg_ease", 0.0))
                else:
                    total_cards = 0
                    total_interval = 0.0
                    total_ease = 0.0
                    for ch in self.engine.CHAPTERS:
                        stats = self.engine.get_mastery_stats(ch)
                        cards = int(stats.get("total", 0))
                        if cards > 0:
                            total_cards += cards
                            total_interval += float(stats.get("avg_interval", 0)) * cards
                            total_ease += float(stats.get("avg_ease", 0)) * cards
                    avg_interval = (total_interval / total_cards) if total_cards else 0.0
                    avg_ease = (total_ease / total_cards) if total_cards else 0.0

                mastery_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                mastery_card.add_css_class("card")
                mastery_title = Gtk.Label(label="Mastery Snapshot")
                mastery_title.set_halign(Gtk.Align.START)
                mastery_title.add_css_class("section-title")
                mastery_card.append(mastery_title)
                mastery_lines = [
                    f"Overall mastery: {overall_mastery:.1f}%",
                    f"Questions: {total_questions}",
                    f"Mastered/Learning/New: {mastery.get('mastered', 0)} / {mastery.get('learning', 0)} / {mastery.get('new', 0)}",
                    f"Avg interval: {avg_interval:.1f} days",
                    f"Avg ease: {avg_ease:.2f}",
                ]
                mastery_label = Gtk.Label(label="\n".join(mastery_lines))
                mastery_label.set_halign(Gtk.Align.START)
                mastery_label.set_wrap(True)
                mastery_label.add_css_class("muted")
                mastery_card.append(mastery_label)
                self.dashboard.append(mastery_card)
            except Exception:
                pass

            try:
                comp = getattr(self.engine, "competence", {})
                weak_lines = ["No competence data yet."]
                strong_lines = []
                if isinstance(comp, dict) and comp:
                    weakest = sorted(comp.items(), key=lambda x: x[1])[:3]
                    strong = sorted(comp.items(), key=lambda x: x[1], reverse=True)[:3]
                    weak_lines = [f"- {ch}: {score:.0f}%" for ch, score in weakest]
                    strong_lines = [f"- {ch}: {score:.0f}%" for ch, score in strong]

                ws_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                ws_card.add_css_class("card")
                ws_title = Gtk.Label(label="Weak vs Strong")
                ws_title.set_halign(Gtk.Align.START)
                ws_title.add_css_class("section-title")
                ws_card.append(ws_title)
                weak_label = Gtk.Label(label="Weakest\n" + "\n".join(weak_lines))
                weak_label.set_halign(Gtk.Align.START)
                weak_label.set_wrap(True)
                weak_label.add_css_class("muted")
                ws_card.append(weak_label)
                if strong_lines:
                    strong_label = Gtk.Label(label="Strongest\n" + "\n".join(strong_lines))
                    strong_label.set_halign(Gtk.Align.START)
                    strong_label.set_wrap(True)
                    strong_label.add_css_class("muted")
                    ws_card.append(strong_label)
                self.dashboard.append(ws_card)
            except Exception:
                pass

            try:
                daily_plan = self.engine.get_daily_plan(num_topics=3) or []
                completed = sum(1 for ch in daily_plan if self._is_completed_today(ch))
                total = len(daily_plan)
                percent = (completed / total * 100) if total else 0.0

                overdue = 0
                due_soon = 0
                due_week = 0
                next_due = None
                due_cutoff = today + datetime.timedelta(days=2)
                week_cutoff = today + datetime.timedelta(days=7)
                for ch in self.engine.CHAPTERS:
                    srs_list = self.engine.srs_data.get(ch, [])
                    for item in srs_list:
                        if self.engine.is_overdue(item, today):
                            overdue += 1
                        last = item.get("last_review")
                        if last is None:
                            due_soon += 1
                            due_week += 1
                        else:
                            try:
                                last_date = datetime.date.fromisoformat(last)
                                interval = int(item.get("interval", 1))
                                due = last_date + datetime.timedelta(days=interval)
                                if due <= due_cutoff:
                                    due_soon += 1
                                if due <= week_cutoff:
                                    due_week += 1
                            except Exception:
                                pass
                        last = item.get("last_review")
                        if last:
                            try:
                                last_date = datetime.date.fromisoformat(last)
                                interval = int(item.get("interval", 1))
                                due = last_date + datetime.timedelta(days=interval)
                                if next_due is None or due < next_due:
                                    next_due = due
                            except Exception:
                                pass
                next_due_text = next_due.isoformat() if next_due else "N/A"

                must_review_due = self._get_must_review_due_count(today)
                quiz_results = getattr(self.engine, "quiz_results", {}) or {}
                quiz_best: float | None = None
                quiz_avg_val: float | None = None
                if isinstance(quiz_results, dict) and quiz_results:
                    values = [float(v) for v in quiz_results.values() if isinstance(v, (int, float))]
                    if values:
                        quiz_best = max(values)
                        quiz_avg_val = sum(values) / len(values)
                gap_line = ""
                try:
                    comp = getattr(self.engine, "competence", {}) or {}
                    gaps = []
                    if isinstance(quiz_results, dict) and isinstance(comp, dict):
                        for ch, quiz_val in quiz_results.items():
                            if not isinstance(quiz_val, (int, float)):
                                continue
                            comp_val = comp.get(ch, 0) or 0
                            try:
                                comp_val = float(comp_val)
                            except Exception:
                                comp_val = 0.0
                            diff = float(quiz_val) - comp_val
                            if abs(diff) >= 25:
                                gaps.append((abs(diff), diff, ch))
                    if gaps:
                        _abs, diff, ch = sorted(gaps, key=lambda x: x[0], reverse=True)[0]
                        gap_line = f"Quiz/competence gap: {ch} ({diff:+.0f}%)"
                except Exception:
                    gap_line = ""

                reviews_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                reviews_card.add_css_class("card")
                reviews_title = Gtk.Label(label="Reviews & Pace")
                reviews_title.set_halign(Gtk.Align.START)
                reviews_title.add_css_class("section-title")
                reviews_card.append(reviews_title)
                review_lines = [
                    f"Daily plan: {completed}/{total} ({percent:.0f}%)" if total else "Daily plan: not set",
                    f"Overdue cards: {overdue}",
                    f"Review load: 48h {due_soon} • 7d {due_week}",
                    f"Next due: {next_due_text}",
                    f"Must-review due: {must_review_due}",
                ]
                if quiz_best is not None and quiz_avg_val is not None:
                    review_lines.append(f"Quiz best/avg: {quiz_best:.0f}% / {quiz_avg_val:.0f}%")
                if gap_line:
                    review_lines.append(gap_line)
                review_label = Gtk.Label(label="\n".join(review_lines))
                review_label.set_halign(Gtk.Align.START)
                review_label.set_wrap(True)
                review_label.add_css_class("muted")
                reviews_card.append(review_label)
                self.dashboard.append(reviews_card)
            except Exception:
                pass

            # Study Hub stats (collapsible)
            try:
                hub = getattr(self.engine, "study_hub_stats", {})
                if isinstance(hub, dict) and hub.get("total_questions"):
                    hub_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                    total_q = int(hub.get("total_questions", 0))
                    taken = int(hub.get("questions_taken", 0))
                    correct_pct = int(hub.get("correct_percent", 0))
                    avg_answer = int(hub.get("avg_answer_seconds", 0))
                    remaining_q = max(0, total_q - taken)
                    remaining_minutes_est = (remaining_q * avg_answer) / 60 if avg_answer else 0
                    qpd = 0.0
                    try:
                        days_remaining = self.engine.get_days_remaining()
                        if days_remaining > 0:
                            qpd = remaining_q / days_remaining
                    except Exception:
                        pass
                    hub_label = Gtk.Label(
                        label=(
                            f"Questions answered: {taken}/{total_q} ({correct_pct}%)\n"
                            f"Estimated remaining: {remaining_minutes_est:.0f} min\n"
                            f"Questions/day target: {qpd:.1f}"
                        )
                    )
                    hub_label.set_halign(Gtk.Align.START)
                    hub_label.set_wrap(True)
                    hub_label.add_css_class("muted")
                    hub_box.append(hub_label)
                    try:
                        last_import = getattr(self, "last_hub_import_date", None)
                        age_line = "Data age: unknown"
                        if last_import:
                            try:
                                last_date = datetime.date.fromisoformat(str(last_import))
                            except Exception:
                                last_date = None
                            if last_date:
                                age = (datetime.date.today() - last_date).days
                                age_line = f"Data age: {age} day{'s' if age != 1 else ''}"
                        age_label = Gtk.Label(label=age_line)
                        age_label.set_halign(Gtk.Align.START)
                        age_label.add_css_class("muted")
                        hub_box.append(age_label)
                    except Exception:
                        pass

                    categories = hub.get("category_totals") if isinstance(hub, dict) else None
                    if isinstance(categories, dict) and categories:
                        category_items: list[tuple[str, float]] = []
                        for name, v in categories.items():
                            total_val = float(v.get("total", 0) or 0)
                            taken_val = float(v.get("taken", 0) or 0)
                            if total_val <= 0:
                                continue
                            pct = (taken_val / total_val) * 100.0
                            category_items.append((name, pct))
                        category_items.sort(key=lambda x: x[1])
                        weakest = category_items[:5]
                        if weakest:
                            lines_text = "\n".join([f"- {name}: {pct:.0f}%" for name, pct in weakest])
                            cat_label = Gtk.Label(label=f"Categories (weakest):\n{lines_text}")
                            cat_label.set_halign(Gtk.Align.START)
                            cat_label.set_wrap(True)
                            cat_label.add_css_class("muted")
                            hub_box.append(cat_label)

                    chapter_comp = hub.get("chapter_completion") if isinstance(hub, dict) else None
                    if isinstance(chapter_comp, dict) and chapter_comp:
                        chapter_items = sorted(chapter_comp.items(), key=lambda x: x[1])
                        weakest = chapter_items[:5]
                        lines_text = "\n".join([f"- {name}: {pct:.0f}%" for name, pct in weakest])
                        ch_label = Gtk.Label(label=f"By Chapter (weakest):\n{lines_text}")
                        ch_label.set_halign(Gtk.Align.START)
                        ch_label.set_wrap(True)
                        ch_label.add_css_class("muted")
                        hub_box.append(ch_label)

                    hub_card = self._wrap_expander_card("Study Hub", hub_box, expanded=False)
                    self.dashboard.append(hub_card)
            except Exception:
                pass

        # Data health snapshot (collapsible)
        if not focus_mode:
            health = getattr(self.engine, "data_health", None)
            if isinstance(health, dict):
                health_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                health_text = (
                    "Data Health:\n"
                    f"Competence fixed: {health.get('competence_fixed', 0)}\n"
                    f"SRS fixed: {health.get('srs_fixed', 0)}\n"
                    f"Pomodoro fixed: {health.get('pomodoro_fixed', 0)}\n"
                    f"Study days fixed: {health.get('study_days_fixed', 0)}\n"
                    f"Exam date fixed: {health.get('exam_date_fixed', 0)}"
                )
                health_label = Gtk.Label(label=health_text)
                health_label.set_halign(Gtk.Align.START)
                health_label.set_wrap(True)
                health_label.add_css_class("muted")
                health_box.append(health_label)
                health_card = self._wrap_expander_card("Data Health Checks", health_box, expanded=False)
                self.dashboard.append(health_card)

        self.update_save_status_display()

    def update_recommendations(self):
        try:
            child = self.rec_box.get_first_child()
            while child:
                self.rec_box.remove(child)
                child = self.rec_box.get_first_child()

            if not self._has_chapters():
                label = Gtk.Label(
                    label="No recommendations yet — add a module JSON to populate chapters."
                )
                label.set_halign(Gtk.Align.START)
                label.set_wrap(True)
                label.add_css_class("muted")
                self.rec_box.append(label)
                return

            recommendations = self.engine.top_recommendations(5) or []
            if not recommendations:
                label = Gtk.Label(label="No recommendations yet — keep studying to unlock them.")
                label.set_halign(Gtk.Align.START)
                label.set_wrap(True)
                label.add_css_class("muted")
                self.rec_box.append(label)
                return

            for chapter, score in recommendations:
                label = Gtk.Label(label=f"{chapter} ({score}%)")
                label.set_halign(Gtk.Align.START)
                self.rec_box.append(label)
        except AttributeError as e:
            self._log_error("update_recommendations", e)
            print(f"AttributeError: {e}")
        except Exception as e:
            self._log_error("update_recommendations", e)
            print(f"Error: {e}")
        self.update_study_room_card()

    def _wrap_plan_row(self, child: Gtk.Widget) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row.set_child(child)
        return row

    # --- Daily plan UI helpers ---
    def update_daily_plan(self, num_topics: int = 3) -> None:
        # Clear existing items
        child = self.plan_box.get_first_child()
        while child:
            self.plan_box.remove(child)
            child = self.plan_box.get_first_child()

        if not self._has_chapters():
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            label = Gtk.Label(
                label="No chapters loaded yet — add a module JSON (Module → Manage Modules)."
            )
            label.set_halign(Gtk.Align.START)
            label.set_wrap(True)
            label.add_css_class("muted")
            hint = Gtk.Label(label="Tip: once a module is loaded, your daily focus list appears here.")
            hint.set_halign(Gtk.Align.START)
            hint.set_wrap(True)
            hint.add_css_class("muted")
            box.append(label)
            box.append(hint)
            self.plan_box.append(self._wrap_plan_row(box))
            return

        # Exam countdown mode: increase daily topics as the exam approaches.
        try:
            num_topics = self.engine.get_recommended_daily_topic_count(num_topics)
        except Exception:
            pass

        # Daily plan stays stable within the same day unless a major import refreshes it.
        today_iso = datetime.date.today().isoformat()
        use_cached = bool(self._last_daily_plan) and self._last_daily_plan_date == today_iso and not self._plan_refresh_override
        if use_cached:
            daily_plan = list(self._last_daily_plan)
        else:
            daily_plan = self.engine.get_daily_plan(num_topics=num_topics, current_topic=self.current_topic) or []
            self._last_daily_plan = list(daily_plan)
            self._last_daily_plan_date = today_iso
            self._plan_refresh_override = False
        if not daily_plan:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            label = Gtk.Label(label="No focus topics yet.")
            label.set_halign(Gtk.Align.START)
            label.set_wrap(True)
            hint = Gtk.Label(label="Tip: set an exam date or import questions to generate a plan.")
            hint.set_halign(Gtk.Align.START)
            hint.set_wrap(True)
            hint.add_css_class("muted")
            box.append(label)
            box.append(hint)
            self.plan_box.append(self._wrap_plan_row(box))
            return

        # Safe completed count (engine mismatch won't crash UI)
        def _safe_is_completed(ch: str) -> bool:
            try:
                return bool(self._is_completed_today(ch))
            except Exception:
                return False

        completed_count = sum(1 for ch in daily_plan if _safe_is_completed(ch))
        total_count = len(daily_plan)

        summary_label = Gtk.Label()
        summary_label.set_halign(Gtk.Align.START)
        summary_label.set_wrap(True)
        summary_label.add_css_class("plan-meta")
        mode = ""
        try:
            days_remaining = self.engine.get_days_remaining()
            if days_remaining <= 45:
                mode = " — Countdown Mode"
        except Exception:
            pass
        summary_label.set_markup(
            f"<b>Daily progress: {completed_count} of {total_count} chapters completed{mode}</b>\n"
            "Resets daily."
        )
        summary_label.set_margin_bottom(4)
        self.plan_box.append(self._wrap_plan_row(summary_label))

        try:
            has_any_questions = any(
                isinstance(self.engine.QUESTIONS.get(ch), list) and self.engine.QUESTIONS.get(ch)
                for ch in self.engine.CHAPTERS
            )
        except Exception:
            has_any_questions = False
        try:
            retrieval_pct = self._get_retrieval_ratio_today()
            if has_any_questions and retrieval_pct is not None and retrieval_pct < self._get_retrieval_min_pct():
                cue = Gtk.Label(label="Coach insert: Retrieval block (Quiz 10m)")
                cue.set_halign(Gtk.Align.START)
                cue.set_wrap(True)
                cue.add_css_class("status-warn")
                self.plan_box.append(self._wrap_plan_row(cue))
        except Exception:
            pass

        # Chapter items
        for chapter in daily_plan:
            chapter_label = self._create_clickable_chapter_label(chapter, num_topics)
            self.plan_box.append(self._wrap_plan_row(chapter_label))
        self.update_study_room_card()


    def _create_chapter_summary_label(self):
        summary_label = Gtk.Label()
        summary_label.set_halign(Gtk.Align.START)

        def update_summary(daily_plan):
            completed_count = sum(1 for ch in daily_plan if self._is_completed_today(ch))
            total_count = len(daily_plan)
            summary_label.set_markup(f"<b>Daily progress: {completed_count} of {total_count} chapters completed</b>")

        return summary_label

    def _create_clickable_chapter_label(self, chapter, num_topics):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label()
        title.set_halign(Gtk.Align.START)
        title.set_xalign(0.0)
        title.set_wrap(True)
        title.add_css_class("plan-title")
        meta = Gtk.Label()
        meta.set_halign(Gtk.Align.START)
        meta.set_xalign(0.0)
        meta.set_wrap(True)
        meta.add_css_class("muted")
        meta.add_css_class("plan-meta")
        meta.set_visible(False)
        box.append(title)
        box.append(meta)

        def update_markup():
            safe_chapter = chapter
            if hasattr(GLib, "markup_escape_text"):
                try:
                    safe_chapter = GLib.markup_escape_text(chapter)
                except Exception:
                    safe_chapter = chapter

            try:
                high_priority = bool(self.engine.is_high_priority(chapter))
            except Exception:
                high_priority = False
            try:
                completed = bool(self._is_completed_today(chapter))
            except Exception:
                completed = False

            comp_val = None
            try:
                comp = getattr(self.engine, "competence", {}) or {}
                if isinstance(comp, dict):
                    comp_val = float(comp.get(chapter, 0) or 0)
            except Exception:
                comp_val = None

            quiz_val = None
            try:
                quiz_results = getattr(self.engine, "quiz_results", {}) or {}
                if isinstance(quiz_results, dict) and chapter in quiz_results:
                    quiz_val = float(quiz_results.get(chapter, 0) or 0)
            except Exception:
                quiz_val = None

            must_due = 0
            overdue = 0
            today = datetime.date.today()
            try:
                must_review = getattr(self.engine, "must_review", {}) or {}
                if isinstance(must_review, dict):
                    items = must_review.get(chapter, {}) or {}
                    if isinstance(items, dict):
                        for due in items.values():
                            due_date = self.engine._parse_date(due)
                            if due_date and due_date <= today:
                                must_due += 1
            except Exception:
                must_due = 0
            try:
                srs_list = self.engine.srs_data.get(chapter, []) or []
                for item in srs_list:
                    if self.engine.is_overdue(item, today):
                        overdue += 1
            except Exception:
                overdue = 0

            status_bits = []
            if comp_val is not None:
                status_bits.append(f"{comp_val:.0f}% comp")
            if quiz_val is not None and quiz_val > 0:
                status_bits.append(f"{quiz_val:.0f}% quiz")
            if overdue > 0:
                status_bits.append(f"{overdue} overdue")
            elif must_due > 0:
                status_bits.append(f"{must_due} due")
            if completed:
                status_bits.append("✔ today")

            threshold = float(getattr(self.engine, "mandatory_weak_threshold", 60) or 60)
            mandatory = comp_val is not None and comp_val < threshold

            for cls in ("status-bad", "status-warn"):
                try:
                    title.remove_css_class(cls)
                except Exception:
                    pass
            if mandatory:
                title.add_css_class("status-bad")

            base = safe_chapter
            if mandatory:
                base = f"⚠ {base}"
            if high_priority:
                base = f"<b>{base}</b>"
            markup = base

            if completed:
                markup = f"<span foreground='#7f8792'>{markup}</span>"

            try:
                coach_pick = self._get_recommended_topic()
            except Exception:
                coach_pick = ""
            if coach_pick and chapter == coach_pick:
                markup = f"🎯 {markup}"

            title.set_markup(markup)
            if status_bits:
                meta.set_text(" • ".join(status_bits))
                meta.set_visible(True)
            else:
                meta.set_text("")
                meta.set_visible(False)

            tooltip_lines = []
            if comp_val is not None:
                tooltip_lines.append(f"Competence: {comp_val:.0f}%")
            if quiz_val is not None and quiz_val > 0:
                tooltip_lines.append(f"Last quiz: {quiz_val:.0f}%")
            if overdue > 0:
                tooltip_lines.append(f"Overdue SRS: {overdue}")
            if must_due > 0:
                tooltip_lines.append(f"Must-review due: {must_due}")
            if completed:
                tooltip_lines.append("Completed today.")
            if tooltip_lines:
                tooltip_lines.append("Click to focus this chapter.")
            else:
                tooltip_lines = ["Click to focus this chapter."]
            box.set_tooltip_text("\n".join(tooltip_lines))

        update_markup()  # initial render
        gesture = Gtk.GestureClick()
        box.add_controller(gesture)

        def on_pressed(_g, _b, _x, _y):
            try:
                self._set_current_topic(chapter)
            except Exception:
                pass
            self.update_study_room_card()

        gesture.connect("pressed", on_pressed)
        return box


    def update_streak_display(self):
        """
        Updates the study streak display label with the latest streak data.

        Raises:
            AttributeError: If self.streak_label or self.study_streak is None.
            Exception: If an unexpected error occurs during update.
        """
        try:
            if self.streak_label is None:
                raise AttributeError("self.streak_label is None")
            if self.study_streak is None:
                raise AttributeError("self.study_streak is None")
            self.streak_label.set_markup(
                f"Study Streak: {self.study_streak} days"
            )
            self.update_xp_display()
        except AttributeError as e:
            print(f"AttributeError: {e}")
        except Exception as e:
            print(f"Exception: {e}")

    def update_streak(self):
        today = datetime.date.today()
        previous = int(self.study_streak or 0)

        if self.last_study_date is None:
            self.study_streak = 1
        elif self.last_study_date == today:
            return  # Already studied today
        elif self.last_study_date == today - datetime.timedelta(days=1):
            self.study_streak += 1
        else:
            self.study_streak = 1

        self.last_study_date = today
        self.save_streak_data()
        self._check_streak_milestones(previous)
        # No need to call update_streak_display() here — caller will do it

    def save_streak_data(self):
        streak_file = os.path.expanduser("~/.config/studyplan/streak.json")
        try:
            os.makedirs(os.path.dirname(streak_file), exist_ok=True)
            with open(streak_file, "w") as f:
                data = {
                    "last_study_date": self.last_study_date.isoformat() if self.last_study_date is not None else None,
                    "study_streak": self.study_streak if self.study_streak is not None else 0
                }
                json.dump(data, f)
        except (TypeError, OSError) as e:
            print(f"Error saving streak data: {e}")
        except Exception as e:
            print(f"Exception: {e}")

    def load_streak_data(self):
        try:
            streak_file = os.path.expanduser("~/.config/studyplan/streak.json")
            if os.path.exists(streak_file):
                try:
                    with open(streak_file, "r") as f:
                        data = json.load(f)
                        if data is not None and "last_study_date" in data:
                            try:
                                self.last_study_date = datetime.date.fromisoformat(data["last_study_date"])
                            except ValueError:
                                print(f"Invalid last_study_date format in {streak_file}")
                                self.last_study_date = None
                        self.study_streak = data.get("study_streak", 0)
                except json.JSONDecodeError:
                    print(f"Load error: {self.__class__.__name__}.load_streak_data caught JSONDecodeError")
                    self.study_streak = 0
                except Exception as e:
                    print(f"Load error: {e}")
                    self.study_streak = 0
        except Exception as e:
            print(f"Load error: {e}")
            self.study_streak = 0

class StudyApp(Gtk.Application):
    def __init__(self, exam_date=None, dialog_smoke_test: bool = False):
        super().__init__(application_id=APP_ID)
        self.exam_date = exam_date
        self.dialog_smoke_test = bool(dialog_smoke_test)

    def do_activate(self):
        try:
            win = StudyPlanGUI(self, self.exam_date)
            win.present()
            if self.dialog_smoke_test:
                GLib.idle_add(win.run_dialog_smoke_test)
        except Exception as exc:
            import traceback
            try:
                log_path = os.path.expanduser("~/.config/studyplan/app.log")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write("\n[Startup Error]\n")
                    f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}\n")
                    f.write(str(exc) + "\n")
                    f.write(traceback.format_exc() + "\n")
            except Exception:
                pass
            try:
                err_win = Gtk.ApplicationWindow(application=self)
                err_win.set_title("Study Assistant — Startup Error")
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                box.set_margin_top(16)
                box.set_margin_bottom(16)
                box.set_margin_start(16)
                box.set_margin_end(16)
                label = Gtk.Label(
                    label="Startup error. Details were written to ~/.config/studyplan/app.log"
                )
                label.set_wrap(True)
                label.set_halign(Gtk.Align.START)
                box.append(label)
                err_win.set_child(box)
                err_win.present()
            except Exception:
                pass

if __name__ == "__main__":
    import sys
    init_result = Gtk.init_check()
    gtk_ok = init_result[0] if isinstance(init_result, tuple) else init_result
    if not gtk_ok:
        print("No display available; Gtk UI cannot start.")
        sys.exit(0)
    if Gdk.Display.get_default() is None:
        print("No display available; Gtk UI cannot start.")
        sys.exit(0)
    exam_date = None
    dialog_smoke_test = False
    for arg in sys.argv[1:]:
        if arg in ("--smoke-dialogs", "--dialog-smoke-test"):
            dialog_smoke_test = True
            continue
        if arg.startswith("-"):
            continue
        try:
            exam_date = datetime.datetime.strptime(arg, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD.")
            sys.exit(1)
    app = StudyApp(exam_date, dialog_smoke_test=dialog_smoke_test)
    app.run()
