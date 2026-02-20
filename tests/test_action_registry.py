import types

from studyplan.app.action_registry import (
    DEFAULT_UI_ACTION_BINDINGS,
    iter_default_ui_action_bindings,
    resolve_ui_action_bindings,
)


def test_default_action_bindings_are_unique_and_nonempty():
    bindings = list(iter_default_ui_action_bindings())
    assert bindings
    names = [row.name for row in bindings]
    assert len(names) == len(set(names))


def test_resolve_ui_action_bindings_reports_missing_handlers():
    owner = types.SimpleNamespace(
        on_menu_set_exam_date=lambda *_args: None,
        on_menu_set_availability=lambda *_args: None,
    )
    subset = tuple(DEFAULT_UI_ACTION_BINDINGS[:3])
    resolved, missing = resolve_ui_action_bindings(owner, bindings=subset)
    assert len(resolved) == 2
    assert "import_pdf" in missing


def test_resolve_ui_action_bindings_returns_callables_for_present_handlers():
    owner = types.SimpleNamespace(
        on_menu_import_pdf=lambda *_args: None,
        on_menu_import_syllabus_pdf=lambda *_args: None,
        on_menu_import_ai=lambda *_args: None,
    )
    subset = tuple(DEFAULT_UI_ACTION_BINDINGS[2:5])
    resolved, missing = resolve_ui_action_bindings(owner, bindings=subset)
    assert not missing
    assert [name for name, _handler in resolved] == ["import_pdf", "import_syllabus_pdf", "import_ai"]
