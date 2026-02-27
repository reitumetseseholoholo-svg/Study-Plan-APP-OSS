"""UI Mixin for adding UIBuilder to GTK window classes."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Generic, TypeVar
from gi.repository import Gtk, GLib

from studyplan.ui_builder import UIBuilder

T = TypeVar("T")


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
        factory: callable,
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

    def clear(self) -> None:
        """Clear all cached widgets."""
        self._cache.clear()
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


class ReactiveWidget:
    """Widget that updates when data changes.
    
    Simplifies patterns where UI needs to refresh when underlying data changes.
    """

    def __init__(self, widget: Gtk.Widget, update_fn: callable) -> None:
        self.widget = widget
        self._update_fn = update_fn
        self._data: Any = None

    def update(self, data: Any) -> None:
        """Update widget with new data."""
        if data != self._data:
            self._data = data
            self._update_fn(self.widget, data)
    
    def get_data(self) -> Any:
        """Get current reactive data."""
        return self._data


class ErrorHandler:
    """Professional error handling for UI operations."""
    
    def __init__(self, window: Gtk.Widget | None = None):
        self._window = window
        self._error_callbacks: list[Callable[[str, str], None]] = []
        self._last_error: tuple[str, str] | None = None
    
    def on_error(self, callback: Callable[[str, str], None]) -> None:
        """Register error callback (title, message)."""
        self._error_callbacks.append(callback)
    
    def handle_error(self, title: str, message: str, details: str = "") -> None:
        """Handle an error with notifications and logging."""
        self._last_error = (title, message)
        
        # Log error
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"{title}: {message}" + (f"\n{details}" if details else ""))
        
        # Call registered callbacks
        for callback in self._error_callbacks:
            try:
                callback(title, message)
            except Exception as e:
                logger.warning(f"Error callback failed: {e}")
    
    def get_last_error(self) -> tuple[str, str] | None:
        """Get the last error that was handled."""
        return self._last_error
    
    def show_error_dialog(self, title: str, message: str, details: str = "") -> None:
        """Show error in a dialog if window is available."""
        if not self._window:
            self.handle_error(title, message, details)
            return
        
        dialog = Gtk.MessageDialog(
            transient_for=self._window,
            flags=Gtk.DialogFlags.MODAL,
            type_=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            message_format=title,
        )
        dialog.format_secondary_text(message + (f"\n\n{details}" if details else ""))
        
        self.handle_error(title, message, details)
        dialog.run()
        dialog.destroy()


class LoadingManager:
    """Manage loading and busy states in UI."""
    
    def __init__(self):
        self._is_loading = False
        self._load_count = 0  # Support nested loading states
        self._callbacks: list[Callable[[bool], None]] = []
    
    def start_loading(self) -> None:
        """Mark as loading."""
        self._load_count += 1
        if not self._is_loading:
            self._is_loading = True
            self._notify(True)
    
    def stop_loading(self) -> None:
        """Mark as loaded."""
        self._load_count = max(0, self._load_count - 1)
        if self._load_count == 0 and self._is_loading:
            self._is_loading = False
            self._notify(False)
    
    def is_loading(self) -> bool:
        """Check if currently loading."""
        return self._is_loading
    
    def on_loading_changed(self, callback: Callable[[bool], None]) -> None:
        """Register callback for loading state changes."""
        self._callbacks.append(callback)
    
    def _notify(self, is_loading: bool) -> None:
        """Notify all subscribers of loading state change."""
        for callback in self._callbacks:
            try:
                callback(is_loading)
            except Exception:
                pass
    
    def reset(self) -> None:
        """Reset loading state."""
        self._is_loading = False
        self._load_count = 0


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
        self._card_content: callable | None = None
        self._actions: list[tuple[str, callable]] = []
        self._css_classes: list[str] = []

    def with_title(self, title: str) -> "SectionBuilder":
        """Set section title."""
        self._title = title
        return self

    def with_card(self, content_fn: callable) -> "SectionBuilder":
        """Set card content builder function."""
        self._card_content = content_fn
        return self

    def with_action(self, label: str, handler: callable) -> "SectionBuilder":
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


class ToastNotification:
    """Simple toast/notification system for UI feedback."""
    
    def __init__(self, window: Gtk.Widget | None = None):
        self._window = window
        self._notifications: list[tuple[str, str]] = []
    
    def info(self, title: str, message: str = "") -> None:
        """Show information notification."""
        self._notify("info", title, message)
    
    def success(self, title: str, message: str = "") -> None:
        """Show success notification."""
        self._notify("success", title, message)
    
    def warning(self, title: str, message: str = "") -> None:
        """Show warning notification."""
        self._notify("warning", title, message)
    
    def error(self, title: str, message: str = "") -> None:
        """Show error notification."""
        self._notify("error", title, message)
    
    def _notify(self, level: str, title: str, message: str) -> None:
        """Internal notification handler."""
        self._notifications.append((level, f"{title}: {message}" if message else title))
        
        # In production, this would trigger a real toast UI
        # For now, just log
        import logging
        logger = logging.getLogger(__name__)
        log_fn = {
            "info": logger.info,
            "success": logger.info,
            "warning": logger.warning,
            "error": logger.error,
        }.get(level, logger.info)
        log_fn(f"{level.upper()}: {title+" - "+message if message else title}")
    
    def get_recent(self, count: int = 5) -> list[tuple[str, str]]:
        """Get recent notifications."""
        return self._notifications[-count:]


class DialogBuilder:
    """Builder for creating professional dialogs."""
    
    def __init__(self, window: Gtk.Widget, title: str = ""):
        self._window = window
        self._title = title
        self._message = ""
        self._secondary_message = ""
        self._buttons: list[tuple[int, str]] = []
        self._modal = True
        self._destroy_on_close = True
    
    def with_message(self, message: str) -> "DialogBuilder":
        """Set primary message."""
        self._message = message
        return self
    
    def with_secondary_message(self, message: str) -> "DialogBuilder":
        """Set secondary message."""
        self._secondary_message = message
        return self
    
    def with_button(self, response_id: int, label: str) -> "DialogBuilder":
        """Add a button to the dialog."""
        self._buttons.append((response_id, label))
        return self
    
    def with_ok_cancel(self) -> "DialogBuilder":
        """Add standard OK/Cancel buttons."""
        self._buttons = [
            (Gtk.ResponseType.CANCEL, "Cancel"),
            (Gtk.ResponseType.OK, "OK"),
        ]
        return self
    
    def modal(self, is_modal: bool = True) -> "DialogBuilder":
        """Set modal behavior."""
        self._modal = is_modal
        return self
    
    def build(self) -> Gtk.MessageDialog:
        """Build and return the dialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self._window,
            flags=Gtk.DialogFlags.MODAL if self._modal else 0,
            type_=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            message_format=self._title,
        )
        
        if self._message:
            dialog.format_secondary_text(self._message)
        
        for response_id, label in self._buttons:
            dialog.add_button(label, response_id)
        
        return dialog
