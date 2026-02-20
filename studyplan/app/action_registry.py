from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ActionBinding:
    name: str
    handler_name: str


DEFAULT_UI_ACTION_BINDINGS: tuple[ActionBinding, ...] = (
    ActionBinding("set_exam_date", "on_menu_set_exam_date"),
    ActionBinding("set_availability", "on_menu_set_availability"),
    ActionBinding("import_pdf", "on_menu_import_pdf"),
    ActionBinding("import_syllabus_pdf", "on_menu_import_syllabus_pdf"),
    ActionBinding("import_ai", "on_menu_import_ai"),
    ActionBinding("import_snapshot", "on_menu_import_snapshot"),
    ActionBinding("recover_snapshot", "on_menu_recover_snapshot"),
    ActionBinding("restore_latest_snapshot", "on_menu_restore_latest_snapshot"),
    ActionBinding("export_csv", "on_menu_export_csv"),
    ActionBinding("export_template", "on_menu_export_template"),
    ActionBinding("export_question_stats", "on_menu_export_question_stats"),
    ActionBinding("weekly_report", "on_view_weekly_report"),
    ActionBinding("reset_data", "on_menu_reset_data"),
    ActionBinding("preferences", "on_open_preferences"),
    ActionBinding("debug_info", "on_debug_info"),
    ActionBinding("view_logs", "on_view_logs"),
    ActionBinding("view_health_log", "on_menu_view_health_log"),
    ActionBinding("run_health_check", "on_menu_run_health_check"),
    ActionBinding("view_syllabus_cache_stats", "on_menu_view_syllabus_cache_stats"),
    ActionBinding("clear_syllabus_cache", "on_menu_clear_syllabus_cache"),
    ActionBinding("view_reflections", "on_view_reflections"),
    ActionBinding("open_ai_tutor", "on_open_ai_tutor"),
    ActionBinding("open_ai_coach", "on_open_ai_coach"),
    ActionBinding("train_ml_models", "on_train_ml_models"),
    ActionBinding("toggle_menu", "on_toggle_menu_action"),
    ActionBinding("edit_focus_allowlist", "on_edit_focus_allowlist"),
    ActionBinding("set_confidence_note", "on_set_confidence_note"),
    ActionBinding("competence_table", "on_show_competence_table"),
    ActionBinding("reset_competence", "on_reset_chapter_competence"),
    ActionBinding("reset_all_competence", "on_reset_all_competence"),
    ActionBinding("about", "on_about"),
    ActionBinding("quit_app", "on_quit_app"),
    ActionBinding("shortcuts", "on_show_shortcuts"),
    ActionBinding("switch_module", "on_switch_module"),
    ActionBinding("first_run_tour", "on_first_run_tour"),
    ActionBinding("manage_modules", "on_manage_modules"),
    ActionBinding("edit_module", "on_edit_module"),
)


def iter_default_ui_action_bindings() -> tuple[ActionBinding, ...]:
    return DEFAULT_UI_ACTION_BINDINGS


def resolve_ui_action_bindings(
    owner: Any,
    bindings: tuple[ActionBinding, ...] | None = None,
) -> tuple[list[tuple[str, Callable[..., Any]]], list[str]]:
    rows = bindings if bindings is not None else DEFAULT_UI_ACTION_BINDINGS
    resolved: list[tuple[str, Callable[..., Any]]] = []
    missing: list[str] = []
    for binding in rows:
        handler = getattr(owner, binding.handler_name, None)
        if callable(handler):
            resolved.append((binding.name, handler))
        else:
            missing.append(binding.name)
    return resolved, missing
