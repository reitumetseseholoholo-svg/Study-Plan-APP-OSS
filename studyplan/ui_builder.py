"""UI Builder - Fluent widget creation utilities for reducing GTK boilerplate."""

from __future__ import annotations

from typing import Callable
from gi.repository import Gtk, Pango  # type: ignore[reportMissingImports,reportAttributeAccessIssue,import-untyped]


class UIBuilder:
    """Fluent builder for common GTK widget patterns to reduce UI boilerplate.
    
    Usage:
        ui = UIBuilder(window)
        
        # Instead of:
        label = Gtk.Label(label="Title")
        label.set_halign(Gtk.Align.START)
        label.add_css_class("section-title")
        
        # Use:
        label = ui.section_title("Title")
        
        # Or more complex:
        warning = ui.label(
            text="Warning message",
            css_classes=["single-line-lock", "nudge-warn"],
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=96,
        )
    """

    def __init__(self, window: Gtk.Widget | None = None) -> None:
        self._window = window

    def label(
        self,
        text: str = "",
        halign: Gtk.Align = Gtk.Align.START,
        css_classes: list[str] | None = None,
        xalign: float | None = None,
        wrap: bool = False,
        ellipsize: Pango.EllipsizeMode | None = None,
        max_width_chars: int | None = None,
        tooltip: str | None = None,
    ) -> Gtk.Label:
        """Create a label with common configurations."""
        lbl = Gtk.Label(label=text)
        lbl.set_halign(halign)
        if xalign is None:
            if halign == Gtk.Align.END:
                xalign = 1.0
            elif halign == Gtk.Align.CENTER:
                xalign = 0.5
            else:
                xalign = 0.0
        try:
            lbl.set_xalign(float(max(0.0, min(1.0, xalign))))
        except Exception:
            lbl.set_xalign(0.0)
        
        if css_classes:
            for cls in css_classes:
                lbl.add_css_class(cls)
        
        lbl.set_wrap(wrap)
        
        if ellipsize is not None:
            lbl.set_ellipsize(ellipsize)
        
        if max_width_chars is not None:
            lbl.set_max_width_chars(max_width_chars)
        
        if tooltip:
            lbl.set_tooltip_text(tooltip)
        
        return lbl

    def section_title(self, text: str) -> Gtk.Label:
        """Create a section title label."""
        return self.label(text, css_classes=["section-title"])

    def muted_label(self, text: str = "", halign: Gtk.Align = Gtk.Align.START) -> Gtk.Label:
        """Create a muted/info label."""
        return self.label(text, halign=halign, css_classes=["muted"])

    def warning_label(self, text: str) -> Gtk.Label:
        """Create a warning label with ellipsis."""
        return self.label(
            text,
            css_classes=["single-line-lock", "nudge-warn"],
            ellipsize=Pango.EllipsizeMode.END,
            max_width_chars=96,
        )

    def card(self, orientation: Gtk.Orientation = Gtk.Orientation.VERTICAL, spacing: int = 6) -> Gtk.Box:
        """Create a card container."""
        box = Gtk.Box(orientation=orientation, spacing=spacing)
        box.add_css_class("card")
        return box

    def hero_card(self, orientation: Gtk.Orientation = Gtk.Orientation.VERTICAL, spacing: int = 4) -> Gtk.Box:
        """Create a hero/feature card with both card and hero-card classes."""
        box = Gtk.Box(orientation=orientation, spacing=spacing)
        box.add_css_class("card")
        box.add_css_class("hero-card")
        return box

    def feature_card(self, orientation: Gtk.Orientation = Gtk.Orientation.VERTICAL, spacing: int = 4) -> Gtk.Box:
        """Create a feature card with card, hero-card, and feature-card classes."""
        box = Gtk.Box(orientation=orientation, spacing=spacing)
        box.add_css_class("card")
        box.add_css_class("hero-card")
        box.add_css_class("feature-card")
        return box

    def button(
        self,
        label: str,
        css_class: str | None = None,
        on_click: Callable | None = None,
        sensitive: bool = True,
    ) -> Gtk.Button:
        """Create a button with optional handler and styling."""
        btn = Gtk.Button(label=label)
        if css_class:
            btn.add_css_class(css_class)
        if on_click:
            btn.connect("clicked", on_click)
        btn.set_sensitive(sensitive)
        return btn

    def flat_button(self, label: str, on_click: Callable | None = None) -> Gtk.Button:
        """Create a flat style button (for coach actions)."""
        return self.button(label, css_class="flat", on_click=on_click)

    def action_button(self, label: str, on_click: Callable | None = None) -> Gtk.Button:
        """Create a coach-action style button."""
        return self.button(label, css_class="coach-action", on_click=on_click)

    def scrolled_window(
        self,
        h_policy: Gtk.PolicyType = Gtk.PolicyType.NEVER,
        v_policy: Gtk.PolicyType = Gtk.PolicyType.AUTOMATIC,
        css_classes: list[str] | None = None,
    ) -> Gtk.ScrolledWindow:
        """Create a scrolled window with policies and optional CSS classes."""
        sw = Gtk.ScrolledWindow()
        sw.set_policy(h_policy, v_policy)
        if css_classes:
            for cls in css_classes:
                sw.add_css_class(cls)
        return sw

    def list_scroller(self) -> Gtk.ScrolledWindow:
        """Create a scrolled window for lists (card + list-card classes)."""
        return self.scrolled_window(
            css_classes=["card", "list-card"]
        )

    def panel_scroller(self) -> Gtk.ScrolledWindow:
        """Create a panel scroll area (panel + panel-scroll classes)."""
        sw = self.scrolled_window(
            v_policy=Gtk.PolicyType.AUTOMATIC,
            css_classes=["panel", "panel-scroll"]
        )
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        return sw

    def box(
        self,
        orientation: Gtk.Orientation,
        spacing: int = 0,
        css_classes: list[str] | None = None,
        halign: Gtk.Align | None = None,
        valign: Gtk.Align | None = None,
        hexpand: bool = False,
        vexpand: bool = False,
    ) -> Gtk.Box:
        """Create a box with common layout properties."""
        box = Gtk.Box(orientation=orientation, spacing=spacing)
        
        if css_classes:
            for cls in css_classes:
                box.add_css_class(cls)
        
        if halign is not None:
            box.set_halign(halign)
        if valign is not None:
            box.set_valign(valign)
        
        box.set_hexpand(hexpand)
        box.set_vexpand(vexpand)
        
        return box

    def hbox(self, spacing: int = 0, **kwargs) -> Gtk.Box:
        """Create a horizontal box."""
        return self.box(Gtk.Orientation.HORIZONTAL, spacing, **kwargs)

    def vbox(self, spacing: int = 0, **kwargs) -> Gtk.Box:
        """Create a vertical box."""
        return self.box(Gtk.Orientation.VERTICAL, spacing, **kwargs)

    def inline_toolbar(self) -> Gtk.Box:
        """Create an inline toolbar box."""
        return self.hbox(css_classes=["inline-toolbar"])

    def progress_bar(self, show_text: bool = True, css_class: str | None = None) -> Gtk.ProgressBar:
        """Create a progress bar."""
        pb = Gtk.ProgressBar()
        pb.set_show_text(show_text)
        if css_class:
            pb.add_css_class(css_class)
        return pb

    def spinner(self, active: bool = True) -> Gtk.Spinner:
        """Create a spinner widget."""
        spinner = Gtk.Spinner()
        if active:
            spinner.start()
        return spinner

    def separator(self, orientation: Gtk.Orientation = Gtk.Orientation.HORIZONTAL) -> Gtk.Separator:
        """Create a separator."""
        return Gtk.Separator(orientation=orientation)

    def stack(self, css_classes: list[str] | None = None) -> Gtk.Stack:
        """Create a stack widget."""
        stack = Gtk.Stack()
        if css_classes:
            for cls in css_classes:
                stack.add_css_class(cls)
        return stack

    def stack_switcher(self, stack: Gtk.Stack) -> Gtk.StackSwitcher:
        """Create a stack switcher bound to a stack."""
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(stack)
        return switcher

    def image(self, icon_name: str, pixel_size: int = 16) -> Gtk.Image:
        """Create an image from an icon name."""
        img = Gtk.Image.new_from_icon_name(icon_name)
        img.set_pixel_size(pixel_size)
        return img

    def badge(self, text: str, css_class: str = "badge") -> Gtk.Label:
        """Create a badge label."""
        return self.label(text, css_classes=[css_class])

    def kpi_line(self, text: str = "") -> Gtk.Label:
        """Create a KPI line label (muted + kpi-line classes)."""
        return self.label(text, css_classes=["muted", "kpi-line"])

    def metric_card(self, title: str, value_widget: Gtk.Widget) -> Gtk.Box:
        """Create a metric card with title and value widget."""
        card = self.card(spacing=4)
        title_lbl = self.section_title(title)
        card.append(title_lbl)
        card.append(value_widget)
        return card

    def quest_row(self, title: str, target: int) -> tuple[Gtk.Box, Gtk.Label, Gtk.ProgressBar]:
        """Create a quest row with label and progress bar.
        
        Returns:
            Tuple of (row_box, label, progress_bar)
        """
        row = self.vbox(spacing=2)
        lbl = self.label(title)
        progress = self.progress_bar()
        row.append(lbl)
        row.append(progress)
        return row, lbl, progress

    def flow_box(self, max_children_per_line: int = 3) -> Gtk.FlowBox:
        """Create a flow box for badges/chips."""
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_valign(Gtk.Align.START)
        flow.set_max_children_per_line(max_children_per_line)
        return flow

    def expander(self, label: str | None = None, css_class: str | None = None) -> Gtk.Expander:
        """Create an expander widget."""
        exp = Gtk.Expander()
        if label:
            exp.set_label(label)
        if css_class:
            exp.add_css_class(css_class)
        return exp

    def reveal(self, transition: Gtk.RevealerTransitionType = Gtk.RevealerTransitionType.SLIDE_DOWN) -> Gtk.Revealer:
        """Create a revealer widget."""
        rev = Gtk.Revealer()
        rev.set_transition_type(transition)
        rev.set_reveal_child(False)
        return rev
    # ──────────────────────────────────────────────────────────────────────────────
    # INPUT COMPONENTS - Professional form & input widgets
    # ──────────────────────────────────────────────────────────────────────────────

    def entry(
        self,
        placeholder_text: str = "",
        on_changed: Callable | None = None,
        on_activate: Callable | None = None,
        css_classes: list[str] | None = None,
        max_length: int | None = None,
        sensitive: bool = True,
        tooltip: str | None = None,
    ) -> Gtk.Entry:
        """Create a text entry field with validation support."""
        entry = Gtk.Entry()
        if placeholder_text:
            entry.set_placeholder_text(placeholder_text)
        if on_changed:
            entry.connect("changed", on_changed)
        if on_activate:
            entry.connect("activate", on_activate)
        if css_classes:
            for cls in css_classes:
                entry.add_css_class(cls)
        if max_length:
            entry.set_max_length(max(1, max_length))
        entry.set_sensitive(sensitive)
        if tooltip:
            entry.set_tooltip_text(tooltip)
        return entry

    def search_entry(
        self,
        on_search: Callable | None = None,
        placeholder: str = "Search...",
    ) -> Gtk.SearchEntry:
        """Create a search entry widget."""
        search = Gtk.SearchEntry()
        search.set_placeholder_text(placeholder)
        if on_search:
            search.connect("search-changed", on_search)
        return search

    def check_button(
        self,
        label: str = "",
        active: bool = False,
        on_toggled: Callable | None = None,
        tooltip: str | None = None,
    ) -> Gtk.CheckButton:
        """Create a check button with label."""
        btn = Gtk.CheckButton(label=label)
        btn.set_active(active)
        if on_toggled:
            btn.connect("toggled", on_toggled)
        if tooltip:
            btn.set_tooltip_text(tooltip)
        return btn

    def switch(
        self,
        label: str = "",
        active: bool = False,
        on_notify_active: Callable | None = None,
        tooltip: str | None = None,
    ) -> Gtk.Box:
        """Create a labeled switch (toggle) widget."""
        box = self.hbox(spacing=12)
        if label:
            lbl = self.label(label)
            box.append(lbl)
        
        switch = Gtk.Switch()
        switch.set_active(active)
        switch.set_halign(Gtk.Align.END)
        switch.set_hexpand(True)
        if on_notify_active:
            switch.connect("notify::active", on_notify_active)
        if tooltip:
            switch.set_tooltip_text(tooltip)
        
        box.append(switch)
        box.set_name("switch-row")
        return box

    def combo_box_text(
        self,
        items: list[str] | None = None,
        active_id: str = "",
        on_changed: Callable | None = None,
        tooltip: str | None = None,
    ) -> Gtk.ComboBoxText:
        """Create a combo box with text items."""
        combo = Gtk.ComboBoxText()
        if items:
            for item in items:
                combo.append_text(str(item))
        if active_id:
            combo.set_active_id(str(active_id))
        if on_changed:
            combo.connect("changed", on_changed)
        if tooltip:
            combo.set_tooltip_text(tooltip)
        return combo

    def spin_button(
        self,
        min_val: float = 0,
        max_val: float = 100,
        step: float = 1,
        value: float = 50,
        on_changed: Callable | None = None,
        tooltip: str | None = None,
    ) -> Gtk.SpinButton:
        """Create a spin button (numeric input)."""
        adjustment = Gtk.Adjustment(
            value=float(value),
            lower=float(min_val),
            upper=float(max_val),
            step_increment=float(step),
        )
        spin = Gtk.SpinButton(adjustment=adjustment)
        if on_changed:
            spin.connect("value-changed", on_changed)
        if tooltip:
            spin.set_tooltip_text(tooltip)
        return spin

    def scale(
        self,
        min_val: float = 0,
        max_val: float = 100,
        value: float = 50,
        step: float = 1,
        marks: dict[float, str] | None = None,
        on_changed: Callable | None = None,
    ) -> Gtk.Scale:
        """Create a slider/scale widget."""
        adjustment = Gtk.Adjustment(
            value=float(value),
            lower=float(min_val),
            upper=float(max_val),
            step_increment=float(step),
        )
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adjustment)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        
        if marks:
            for mark_val, mark_label in marks.items():
                scale.add_mark(float(mark_val), Gtk.PositionType.BOTTOM, mark_label)
        
        if on_changed:
            scale.connect("value-changed", on_changed)
        return scale

    # ──────────────────────────────────────────────────────────────────────────────
    # STATE BUILDERS - Error, Loading, and Empty states
    # ──────────────────────────────────────────────────────────────────────────────

    def error_state(
        self,
        title: str = "Error",
        message: str = "Something went wrong",
        details: str = "",
        on_retry: Callable | None = None,
    ) -> Gtk.Box:
        """Build an error state card with optional retry action."""
        card = self.card(spacing=8)
        card.add_css_class("state-error")
        
        # Title
        title_lbl = self.label(
            title,
            css_classes=["section-title", "error-title"],
            halign=Gtk.Align.CENTER,
        )
        card.append(title_lbl)
        
        # Message
        msg_lbl = self.label(
            message,
            css_classes=["muted"],
            halign=Gtk.Align.CENTER,
            wrap=True,
        )
        card.append(msg_lbl)
        
        # Details if provided
        if details:
            detail_lbl = self.label(
                details,
                css_classes=["muted", "small"],
                halign=Gtk.Align.CENTER,
                wrap=True,
            )
            card.append(detail_lbl)
        
        # Retry button if handler provided
        if on_retry:
            action_box = self.hbox(spacing=8)
            action_box.set_halign(Gtk.Align.CENTER)
            retry_btn = self.button("Retry", css_class="suggested-action", on_click=on_retry)
            action_box.append(retry_btn)
            card.append(action_box)
        
        return card

    def loading_state(
        self,
        message: str = "Loading...",
        show_animation: bool = True,
    ) -> Gtk.Box:
        """Build a professional loading state."""
        card = self.card(spacing=12)
        card.add_css_class("state-loading")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        
        if show_animation:
            spinner = self.spinner(active=True)
            spinner.set_halign(Gtk.Align.CENTER)
            card.append(spinner)
        
        msg_lbl = self.label(
            message,
            css_classes=["muted"],
            halign=Gtk.Align.CENTER,
        )
        card.append(msg_lbl)
        
        return card

    def empty_state(
        self,
        title: str = "Nothing here",
        message: str = "Try adding some content",
        icon_name: str = "folder-open-symbolic",
        on_action: Callable | None = None,
        action_label: str = "Get started",
    ) -> Gtk.Box:
        """Build an empty state card."""
        card = self.card(spacing=12)
        card.add_css_class("state-empty")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        
        # Icon
        if icon_name:
            icon = self.image(icon_name, pixel_size=64)
            icon.set_opacity(0.5)
            icon.set_halign(Gtk.Align.CENTER)
            card.append(icon)
        
        # Title
        title_lbl = self.label(
            title,
            css_classes=["section-title"],
            halign=Gtk.Align.CENTER,
        )
        card.append(title_lbl)
        
        # Message
        msg_lbl = self.label(
            message,
            css_classes=["muted"],
            halign=Gtk.Align.CENTER,
            wrap=True,
        )
        card.append(msg_lbl)
        
        # Action button
        if on_action:
            action_box = self.hbox(spacing=8)
            action_box.set_halign(Gtk.Align.CENTER)
            action_btn = self.button(action_label, css_class="suggested-action", on_click=on_action)
            action_box.append(action_btn)
            card.append(action_box)
        
        return card

    # ──────────────────────────────────────────────────────────────────────────────
    # FORM BUILDERS - Professional form layouts
    # ──────────────────────────────────────────────────────────────────────────────

    def form_row(
        self,
        label_text: str = "",
        widget: Gtk.Widget | None = None,
        help_text: str = "",
        required: bool = False,
    ) -> Gtk.Box:
        """Create a form row with label, widget, and help text."""
        row = self.vbox(spacing=4)
        
        # Label with required indicator
        if label_text:
            label_box = self.hbox(spacing=4)
            lbl = self.label(label_text, css_classes=["form-label"])
            label_box.append(lbl)
            
            if required:
                req_badge = self.badge("*", css_class="required-indicator")
                label_box.append(req_badge)
            
            row.append(label_box)
        
        # Widget
        if widget:
            row.append(widget)
        
        # Help text
        if help_text:
            help_lbl = self.muted_label(help_text)
            help_lbl.add_css_class("form-help")
            row.append(help_lbl)
        
        return row

    def form_section(
        self,
        title: str = "",
        rows: list[Gtk.Box] | None = None,
    ) -> Gtk.Box:
        """Create a form section with optional title."""
        section = self.vbox(spacing=8)
        section.add_css_class("form-section")
        
        if title:
            title_lbl = self.section_title(title)
            section.append(title_lbl)
        
        if rows:
            for row in rows:
                section.append(row)
        
        return section

    # ──────────────────────────────────────────────────────────────────────────────
    # ACCESSIBILITY & PROFESSIONAL PATTERNS
    # ──────────────────────────────────────────────────────────────────────────────

    def accessible_button(
        self,
        label: str,
        tooltip: str = "",
        css_class: str | None = None,
        on_click: Callable | None = None,
    ) -> Gtk.Button:
        """Create a button with accessibility features."""
        btn = self.button(label, css_class=css_class, on_click=on_click)
        
        # Set accessible name and description
        context = btn.get_accessible()
        if context:
            context.set_accessible_name(label)
            if tooltip:
                context.set_accessible_description(tooltip)
        
        # Add tooltip for keyboard users
        if tooltip:
            btn.set_tooltip_text(tooltip)
        
        # Make keyboard focusable
        btn.set_focusable(True)
        
        return btn

    def status_indicator(
        self,
        status: str = "info",
        text: str = "",
        css_class: str | None = None,
    ) -> Gtk.Box:
        """Create a status indicator with icon and text (info/success/warning/error)."""
        box = self.hbox(spacing=8)
        box.add_css_class("status-indicator")
        
        # Status icon
        icon_map = {
            "info": "dialog-information-symbolic",
            "success": "emblem-ok-symbolic",
            "warning": "dialog-warning-symbolic",
            "error": "dialog-error-symbolic",
        }
        icon_name = icon_map.get(status, "dialog-information-symbolic")
        icon = self.image(icon_name, pixel_size=20)
        icon.add_css_class(f"status-{status}")
        box.append(icon)
        
        # Text
        if text:
            lbl = self.label(text, css_classes=[f"status-text"], wrap=True)
            box.append(lbl)
        
        # Optional CSS class
        if css_class:
            box.add_css_class(css_class)
        
        return box

    def info_banner(
        self,
        message: str,
        status: str = "info",
        closeable: bool = False,
        on_close: Callable | None = None,
    ) -> Gtk.Box:
        """Create an information banner with status styling."""
        banner = self.hbox(spacing=8)
        banner.add_css_class("info-banner")
        banner.add_css_class(f"banner-{status}")
        banner.set_margin_start(12)
        banner.set_margin_end(12)
        banner.set_margin_top(8)
        banner.set_margin_bottom(8)
        
        # Status indicator
        indicator = self.status_indicator(status=status)
        banner.append(indicator)
        
        # Message
        msg = self.label(message, wrap=True)
        msg.set_hexpand(True)
        banner.append(msg)
        
        # Close button if requested
        if closeable and on_close:
            close_btn = self.button("", on_click=on_close)
            close_btn.add_css_class("flat")
            close_btn.set_icon_name("window-close-symbolic")
            banner.append(close_btn)
        
        return banner