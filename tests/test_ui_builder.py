from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango  # type: ignore[import-untyped]

from studyplan.ui import UIBuilder


def test_label_applies_common_options():
    ui = UIBuilder()
    lbl = ui.label(
        "Hello",
        css_classes=["muted", "allow-wrap"],
        wrap=True,
        ellipsize=Pango.EllipsizeMode.END,
        max_width_chars=42,
        tooltip="tip",
    )
    assert isinstance(lbl, Gtk.Label)
    assert lbl.get_label() == "Hello"
    assert lbl.get_wrap() is True
    assert lbl.get_ellipsize() == Pango.EllipsizeMode.END
    assert lbl.get_max_width_chars() == 42
    assert lbl.get_tooltip_text() == "tip"
    assert lbl.has_css_class("muted") is True
    assert lbl.has_css_class("allow-wrap") is True


def test_warning_label_defaults_match_expected_policy():
    ui = UIBuilder()
    lbl = ui.warning_label("Warning")
    assert lbl.get_wrap() is False
    assert lbl.get_ellipsize() == Pango.EllipsizeMode.END
    assert lbl.get_max_width_chars() == 96
    assert lbl.has_css_class("single-line-lock") is True
    assert lbl.has_css_class("nudge-warn") is True


def test_label_defaults_xalign_from_halign_and_accepts_override():
    ui = UIBuilder()
    left = ui.label("L", halign=Gtk.Align.START)
    right = ui.label("R", halign=Gtk.Align.END)
    center = ui.label("C", halign=Gtk.Align.CENTER)
    custom = ui.label("X", halign=Gtk.Align.START, xalign=0.33)
    assert left.get_xalign() == pytest.approx(0.0, abs=0.001)
    assert right.get_xalign() == pytest.approx(1.0, abs=0.001)
    assert center.get_xalign() == pytest.approx(0.5, abs=0.001)
    assert custom.get_xalign() == pytest.approx(0.33, abs=0.001)


def test_card_variants_apply_expected_classes():
    ui = UIBuilder()

    card = ui.card()
    hero = ui.hero_card()
    feature = ui.feature_card()

    assert card.has_css_class("card") is True
    assert hero.has_css_class("card") is True
    assert hero.has_css_class("hero-card") is True
    assert feature.has_css_class("card") is True
    assert feature.has_css_class("hero-card") is True
    assert feature.has_css_class("feature-card") is True


def test_scroller_helpers_apply_policies_and_classes():
    ui = UIBuilder()

    list_sw = ui.list_scroller()
    panel_sw = ui.panel_scroller()

    list_h, list_v = list_sw.get_policy()
    panel_h, panel_v = panel_sw.get_policy()

    assert list_h == Gtk.PolicyType.NEVER
    assert list_v == Gtk.PolicyType.AUTOMATIC
    assert list_sw.has_css_class("card") is True
    assert list_sw.has_css_class("list-card") is True

    assert panel_h == Gtk.PolicyType.NEVER
    assert panel_v == Gtk.PolicyType.AUTOMATIC
    assert panel_sw.has_css_class("panel") is True
    assert panel_sw.has_css_class("panel-scroll") is True


def test_button_helpers_apply_styles_and_sensitivity():
    ui = UIBuilder()

    flat = ui.flat_button("Flat")
    action = ui.action_button("Action")
    disabled = ui.button("Disabled", sensitive=False)

    assert isinstance(flat, Gtk.Button)
    assert isinstance(action, Gtk.Button)
    assert flat.has_css_class("flat") is True
    assert action.has_css_class("coach-action") is True
    assert disabled.get_sensitive() is False
