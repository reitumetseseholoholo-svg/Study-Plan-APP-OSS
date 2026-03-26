from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango


class GTK4StatusPanel(Gtk.Box):
    """Small reusable panel shell for the GTK4 example views."""

    def __init__(self, main_window: Gtk.ApplicationWindow, title: str, intro: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.main_window = main_window
        self.set_hexpand(True)
        self.set_vexpand(True)

        self.title_label = Gtk.Label(label=title)
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.add_css_class("title-2")

        self.body_label = Gtk.Label(label=intro)
        self.body_label.set_halign(Gtk.Align.START)
        self.body_label.set_xalign(0.0)
        self.body_label.set_wrap(True)
        self.body_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.body_label.add_css_class("body")

        self.append(self.title_label)
        self.append(self.body_label)

    def set_body(self, text: str) -> None:
        self.body_label.set_text(text or "")
