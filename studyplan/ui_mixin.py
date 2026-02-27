"""UI Mixin for adding UIBuilder to GTK window classes."""

from __future__ import annotations

from typing import Any, Callable
from gi.repository import Gtk  # pyright: ignore[reportAttributeAccessIssue]

from studyplan.ui_builder import UIBuilder


class UIBuilderMixin:
    """Mixin that adds a _ui property to GTK widgets for fluent widget creation.
    
    Usage:
        class MyWindow(Gtk.ApplicationWindow, UIBuilderMixin):
            def __init__(self):
                super().__init__()
                self._init_ui_builder()
                
                # Now use self._ui throughout
                label = self._ui.section_title("My Section")
                self.set_child(label)
    """

    _ui: UIBuilder | None = None

    def _init_ui_builder(self) -> None:
        """Initialize the UI builder. Call this in __init__ after super().__init__()"""
        self._ui = UIBuilder(self)

    @property
    def ui(self) -> UIBuilder:
        """Access the UI builder. Raises if not initialized."""
        if self._ui is None:
            raise RuntimeError(
                "UIBuilder not initialized. Call _init_ui_builder() in __init__"
            )
        return self._ui


class WidgetCache:
    """Cache for widgets to avoid recreating identical widgets.
    
    Useful for dynamic UI updates where you need to check if a widget
    already exists before creating a new one.
    """

    def __init__(self) -> None:
        self._cache: dict[str, Gtk.Widget] = {}

    def get_or_create(
        self,
        key: str,
        factory: Callable[[], Gtk.Widget],
    ) -> Gtk.Widget:
        """Get cached widget or create new one."""
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    def invalidate(self, key: str | None = None) -> None:
        """Remove widget(s) from cache."""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    def get(self, key: str) -> Gtk.Widget | None:
        """Get cached widget if exists."""
        return self._cache.get(key)


class ReactiveWidget:
    """Widget that updates when data changes.
    
    Simplifies patterns where UI needs to refresh when underlying data changes.
    """

    def __init__(self, widget: Gtk.Widget, update_fn: Callable[[Gtk.Widget, Any], None]) -> None:
        self.widget = widget
        self._update_fn = update_fn
        self._data: Any = None

    def update(self, data: Any) -> None:
        """Update widget with new data."""
        if data != self._data:
            self._data = data
            self._update_fn(self.widget, data)


class SectionBuilder:
    """Builder for complex sections with title, content, and actions.
    
    Usage:
        section = SectionBuilder(ui)
        section.with_title("Study Room")
                 .with_card(lambda c: c.append(ui.label("Content")))
                 .with_action("Start", self.on_start)
                 .build(parent_container)
    """

    def __init__(self, ui: UIBuilder) -> None:
        self._ui = ui
        self._title: str | None = None
        self._card_content: Callable[[Gtk.Box], None] | None = None
        self._actions: list[tuple[str, Callable[..., Any]]] = []
        self._css_classes: list[str] = []

    def with_title(self, title: str) -> "SectionBuilder":
        """Set section title."""
        self._title = title
        return self

    def with_card(self, content_fn: Callable[[Gtk.Box], None]) -> "SectionBuilder":
        """Set card content builder function."""
        self._card_content = content_fn
        return self

    def with_action(self, label: str, handler: Callable[..., Any]) -> "SectionBuilder":
        """Add an action button."""
        self._actions.append((label, handler))
        return self

    def with_css_class(self, css_class: str) -> "SectionBuilder":
        """Add CSS class to card."""
        self._css_classes.append(css_class)
        return self

    def build(self, parent: Gtk.Box) -> Gtk.Box:
        """Build and append to parent."""
        if self._title:
            parent.append(self._ui.section_title(self._title))

        card = self._ui.hero_card()
        for cls in self._css_classes:
            card.add_css_class(cls)

        if self._card_content:
            self._card_content(card)

        if self._actions:
            action_row = self._ui.hbox(spacing=8)
            for label, handler in self._actions:
                action_row.append(self._ui.button(label, on_click=handler))
            card.append(action_row)

        parent.append(card)
        return card
