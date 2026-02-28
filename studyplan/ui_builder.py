"""UI Builder - Fluent widget creation utilities for reducing GTK boilerplate."""

from __future__ import annotations

from typing import Callable
from gi.repository import Gtk, Pango  # pyright: ignore[reportAttributeAccessIssue]


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
        wrap: bool = False,
        ellipsize: Pango.EllipsizeMode | None = None,
        max_width_chars: int | None = None,
        tooltip: str | None = None,
    ) -> Gtk.Label:
        """Create a label with common configurations."""
        lbl = Gtk.Label(label=text)
        lbl.set_halign(halign)
        
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

    def info_line(
        self,
        text: str = "",
        max_width_chars: int = 80,
    ) -> Gtk.Label:
        """Single-line muted label with ellipsis and auto-tooltip.

        Use this for dashboard/card info lines that should never wrap or
        push layout.  The full text is always available via tooltip.
        """
        lbl = Gtk.Label(label=text)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_wrap(False)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_max_width_chars(max_width_chars)
        lbl.add_css_class("muted")
        lbl.add_css_class("single-line-lock")
        if text:
            lbl.set_tooltip_text(text)
        return lbl

    def body_label(
        self,
        text: str = "",
        max_width_chars: int = 90,
    ) -> Gtk.Label:
        """Multi-line wrapping muted label for longer content blocks."""
        lbl = Gtk.Label(label=text)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lbl.set_max_width_chars(max_width_chars)
        lbl.set_xalign(0.0)
        lbl.add_css_class("muted")
        lbl.add_css_class("allow-wrap")
        return lbl

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
