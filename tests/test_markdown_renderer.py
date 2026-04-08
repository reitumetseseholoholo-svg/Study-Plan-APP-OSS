"""Unit tests for studyplan.ui.markdown_renderer.

Uses a lightweight stub TextBuffer so the tests run without a GTK display.
"""
from __future__ import annotations

import sys
import types
import unittest


# ---------------------------------------------------------------------------
# Stub GTK TextBuffer / TextTag infrastructure (no display required)
# ---------------------------------------------------------------------------

class _FakeTag:
    def __init__(self, name: str, **props):
        self.name = name
        self.props = props


class _FakeTagTable:
    def __init__(self):
        self._tags: dict[str, _FakeTag] = {}

    def lookup(self, name: str) -> _FakeTag | None:
        return self._tags.get(name)

    def add(self, tag: _FakeTag) -> None:
        self._tags[tag.name] = tag


class _FakeBuffer:
    """Minimal TextBuffer stub that records inserted text and tags."""

    def __init__(self):
        self._tag_table = _FakeTagTable()
        # List of (text, [tag_names]) tuples in insertion order.
        self.segments: list[tuple[str, list[str]]] = []

    # --- tag management ---
    def get_tag_table(self):
        return self._tag_table

    def create_tag(self, name: str, **props) -> _FakeTag:
        tag = _FakeTag(name, **props)
        self._tag_table.add(tag)
        return tag

    # --- TextBuffer API ---
    def set_text(self, text: str) -> None:
        self.segments = [("__set__" + text, [])]

    def get_end_iter(self):
        return object()  # opaque sentinel; not used by stub

    def insert(self, _iter, text: str) -> None:
        self.segments.append((text, []))

    def insert_with_tags(self, _iter, text: str, *tags) -> None:
        tag_names = [t.name for t in tags if hasattr(t, "name")]
        self.segments.append((text, tag_names))

    # --- helpers for tests ---
    @property
    def plain_text(self) -> str:
        return "".join(s for s, _ in self.segments if not s.startswith("__set__"))

    def tag_names_for(self, text_fragment: str) -> list[str]:
        """Return the tags applied to the *first* segment containing text_fragment."""
        for s, tags in self.segments:
            if text_fragment in s:
                return tags
        return []


# ---------------------------------------------------------------------------
# Patch gi so the module can be imported without a real GTK installation
# ---------------------------------------------------------------------------

def _install_gi_stub():
    """Insert a minimal gi / gi.repository stub into sys.modules."""
    if "gi" in sys.modules:
        return  # already present (real or stub)

    gi_mod = types.ModuleType("gi")
    gi_repo = types.ModuleType("gi.repository")
    gi_mod.repository = gi_repo  # type: ignore[attr-defined]

    # Pango stub values used by markdown_renderer tag specs
    pango_mod = types.ModuleType("gi.repository.Pango")
    pango_mod.Weight = types.SimpleNamespace(BOLD=700)  # type: ignore[attr-defined]
    pango_mod.Style = types.SimpleNamespace(ITALIC=2)   # type: ignore[attr-defined]

    # Gtk stub (needs Align for ui_builder)
    class _GtkAlignStub:
        START = "START"
        END = "END"
        CENTER = "CENTER"
        FILL = "FILL"
        BASELINE = "BASELINE"

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.Align = _GtkAlignStub  # type: ignore[attr-defined]

    gi_repo.Pango = pango_mod   # type: ignore[attr-defined]
    gi_repo.Gtk = gtk_mod       # type: ignore[attr-defined]

    sys.modules["gi"] = gi_mod
    sys.modules["gi.repository"] = gi_repo
    sys.modules["gi.repository.Pango"] = pango_mod
    sys.modules["gi.repository.Gtk"] = gtk_mod


def _install_studyplan_ui_stub():
    """Stub out studyplan.ui_builder so UIBuilder import doesn't fail without GTK."""
    if "studyplan.ui_builder" not in sys.modules:
        builder_stub = types.ModuleType("studyplan.ui_builder")
        builder_stub.UIBuilder = object  # type: ignore[attr-defined]
        sys.modules["studyplan.ui_builder"] = builder_stub


_install_gi_stub()
_install_studyplan_ui_stub()

from studyplan.ui.markdown_renderer import render_markdown_to_buffer  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRenderMarkdownToBuffer(unittest.TestCase):

    def _render(self, text: str) -> _FakeBuffer:
        buf = _FakeBuffer()
        render_markdown_to_buffer(text, buf)
        return buf

    # ------------------------------------------------------------------
    # Headings
    # ------------------------------------------------------------------

    def test_h1_heading_applies_heading1_tag(self):
        buf = self._render("# Revenue Recognition")
        self.assertIn("heading1", buf.tag_names_for("Revenue Recognition"))

    def test_h2_heading(self):
        buf = self._render("## Statement of Financial Position")
        self.assertIn("heading2", buf.tag_names_for("Statement of Financial Position"))

    def test_h3_heading(self):
        buf = self._render("### Notes to Accounts")
        self.assertIn("heading3", buf.tag_names_for("Notes to Accounts"))

    def test_heading_text_content_preserved(self):
        buf = self._render("## Cash Flow")
        self.assertIn("Cash Flow", buf.plain_text)

    # ------------------------------------------------------------------
    # Bold / italic
    # ------------------------------------------------------------------

    def test_bold_applies_bold_tag(self):
        buf = self._render("The **total assets** are listed below.")
        self.assertIn("bold", buf.tag_names_for("total assets"))

    def test_italic_applies_italic_tag(self):
        buf = self._render("*Net profit* is the bottom line.")
        self.assertIn("italic", buf.tag_names_for("Net profit"))

    def test_bold_italic_combined(self):
        buf = self._render("***Key figure*** matters.")
        self.assertIn("bold_italic", buf.tag_names_for("Key figure"))

    # ------------------------------------------------------------------
    # Inline code
    # ------------------------------------------------------------------

    def test_inline_code_monospace(self):
        buf = self._render("Use `IFRS 15` for revenue.")
        self.assertIn("code_inline", buf.tag_names_for("IFRS 15"))

    # ------------------------------------------------------------------
    # Fenced code block
    # ------------------------------------------------------------------

    def test_fenced_code_block_monospace(self):
        md = "```\nRevenue     100\nCOGS        (60)\n```"
        buf = self._render(md)
        self.assertIn("code_block", buf.tag_names_for("Revenue"))

    def test_fenced_code_block_lang_hint_stripped(self):
        md = "```python\nprint('hello')\n```"
        buf = self._render(md)
        # The fence line itself should not appear in the output
        self.assertNotIn("```", buf.plain_text)

    # ------------------------------------------------------------------
    # Pipe tables (financial exhibits)
    # ------------------------------------------------------------------

    def test_pipe_table_row_monospace(self):
        md = "| Item | Amount |\n|------|--------|\n| Revenue | 100 |"
        buf = self._render(md)
        self.assertIn("table", buf.tag_names_for("| Revenue | 100 |"))

    def test_pipe_table_separator_gets_sep_tag(self):
        md = "| Item | Amount |\n|------|--------|\n| Revenue | 100 |"
        buf = self._render(md)
        self.assertIn("table_sep", buf.tag_names_for("|------|--------|"))

    def test_pipe_table_content_preserved(self):
        md = "| Revenue | 500,000 |"
        buf = self._render(md)
        self.assertIn("Revenue", buf.plain_text)
        self.assertIn("500,000", buf.plain_text)

    # ------------------------------------------------------------------
    # Bullet lists
    # ------------------------------------------------------------------

    def test_unordered_list_bullet_character(self):
        buf = self._render("- First item\n- Second item")
        self.assertIn("•", buf.plain_text)
        self.assertIn("First item", buf.plain_text)

    def test_ordered_list_number_preserved(self):
        buf = self._render("1. Prepare SoFP\n2. Prepare SoPL")
        self.assertIn("1.", buf.plain_text)
        self.assertIn("Prepare SoFP", buf.plain_text)

    # ------------------------------------------------------------------
    # Horizontal rule
    # ------------------------------------------------------------------

    def test_horizontal_rule_renders(self):
        buf = self._render("---")
        self.assertIn("─", buf.plain_text)

    # ------------------------------------------------------------------
    # Empty / plain text fallback
    # ------------------------------------------------------------------

    def test_empty_string_no_crash(self):
        buf = self._render("")
        self.assertEqual(buf.plain_text, "")

    def test_plain_text_preserved_no_tags(self):
        buf = self._render("Just plain text here.")
        self.assertIn("Just plain text here.", buf.plain_text)

    # ------------------------------------------------------------------
    # Financial statement example (integration)
    # ------------------------------------------------------------------

    def test_financial_statement_table_example(self):
        md = (
            "## Statement of Financial Position\n\n"
            "| Line Item | 2024 (£000) | 2023 (£000) |\n"
            "|-----------|-------------|-------------|\n"
            "| **Property, plant & equipment** | 450 | 420 |\n"
            "| Inventories | 80 | 75 |\n"
            "| **Total assets** | 530 | 495 |\n"
        )
        buf = self._render(md)
        self.assertIn("heading2", buf.tag_names_for("Statement of Financial Position"))
        self.assertIn("Total assets", buf.plain_text)
        self.assertIn("530", buf.plain_text)


if __name__ == "__main__":
    unittest.main()
