"""Render markdown-formatted text into a GTK4 TextBuffer with rich text tags.

Supports:
- H1 / H2 / H3 headings (bold + scaled font size)
- **bold** and *italic* inline spans
- `inline code` (monospace)
- Fenced code blocks (``` … ```) in monospace
- Pipe tables (| … | rows) rendered as clean financial-statement-style blocks:
  aligned columns without pipe characters, Unicode rule separators (─),
  bold header row, right-aligned numeric columns, and bold emphasis for
  total/subtotal rows — so exhibits look like professional IFRS statements
  rather than CLI grids.
- Unordered bullet lists (- / * / •)
- Ordered lists (1. 2. …)
- Horizontal rules (--- / ***)

The module is intentionally GTK-import-safe: the top-level functions perform the
gi import lazily so that unit tests and non-GUI code paths can import this module
without a display.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # Gtk / Pango types are imported lazily below


# ---------------------------------------------------------------------------
# Tag definitions
# ---------------------------------------------------------------------------

# Map tag-name → dict of TextTag property overrides.
# Numeric weight/style values map to Pango constants (BOLD=700, ITALIC=2).
_TAG_SPECS: dict[str, dict[str, Any]] = {
    "heading1": {"weight": 700, "scale": 1.44},
    "heading2": {"weight": 700, "scale": 1.22},
    "heading3": {"weight": 700, "scale": 1.10},
    "bold":     {"weight": 700},
    "italic":   {"style": 2},
    "bold_italic": {"weight": 700, "style": 2},
    "code_inline":  {"family": "monospace"},
    "code_block":   {"family": "monospace"},
    "table":        {"family": "monospace"},
    "table_header": {"family": "monospace", "weight": 700},
    "table_total":  {"family": "monospace", "weight": 700},
    "table_sep":    {"family": "monospace", "foreground": "#888888"},
    "h_rule":       {"foreground": "#888888"},
    "list_bullet":  {},
}


def _ensure_buffer_tags(buf: Any) -> None:
    """Create TextTags on *buf* if they don't already exist."""
    tag_table = buf.get_tag_table()
    for name, props in _TAG_SPECS.items():
        if tag_table.lookup(name) is None:
            buf.create_tag(name, **props)


# ---------------------------------------------------------------------------
# Inline markdown parser
# ---------------------------------------------------------------------------

# Pattern to match inline spans: **bold**, *italic*, ***bold-italic***, `code`
_INLINE_RE = re.compile(
    r"(\*\*\*(?P<bolditalic>.+?)\*\*\*"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|__(?P<bold2>.+?)__"
    r"|\*(?P<italic>.+?)\*"
    r"|_(?P<italic2>.+?)_"
    r"|`(?P<code>[^`]+)`)",
    re.DOTALL,
)


def _insert_inline(buf: Any, text: str, extra_tag: str | None = None) -> None:
    """Insert *text* with inline markdown formatting applied."""
    tag_table = buf.get_tag_table()

    def _ins(s: str, *tag_names: str) -> None:
        if not s:
            return
        tags = []
        for n in tag_names:
            t = tag_table.lookup(n)
            if t is not None:
                tags.append(t)
        it = buf.get_end_iter()
        if tags:
            buf.insert_with_tags(it, s, *tags)
        else:
            buf.insert(it, s)

    pos = 0
    for m in _INLINE_RE.finditer(text):
        before = text[pos : m.start()]
        if before:
            _ins(before, *([extra_tag] if extra_tag else []))

        if m.group("bolditalic") is not None:
            inner = m.group("bolditalic")
            tags = ["bold_italic"] + ([extra_tag] if extra_tag else [])
            _ins(inner, *tags)
        elif m.group("bold") is not None or m.group("bold2") is not None:
            inner = m.group("bold") or m.group("bold2") or ""
            tags = ["bold"] + ([extra_tag] if extra_tag else [])
            _ins(inner, *tags)
        elif m.group("italic") is not None or m.group("italic2") is not None:
            inner = m.group("italic") or m.group("italic2") or ""
            tags = ["italic"] + ([extra_tag] if extra_tag else [])
            _ins(inner, *tags)
        elif m.group("code") is not None:
            _ins(m.group("code"), "code_inline")
        pos = m.end()

    tail = text[pos:]
    if tail:
        _ins(tail, *([extra_tag] if extra_tag else []))


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

_TABLE_SEP_RE = re.compile(r"^\|[-| :]+\|?\s*$")


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and len(s) > 1


def _is_table_sep(line: str) -> bool:
    return bool(_TABLE_SEP_RE.match(line.strip()))


# Pattern for numeric cell values (integers, decimals, currency, %, parenthesised negatives)
_NUMERIC_CELL_RE = re.compile(
    r"^\s*[£$€(]?\s*[\d,]*\.?\d+\)?\s*%?\s*$"
)

# Pattern to strip inline markup characters from a cell before width measurement
_INLINE_MARKUP_RE = re.compile(r"\*{1,3}|_{1,2}|`")


def _strip_inline_markup(text: str) -> str:
    """Remove markdown inline markers so cell widths are measured correctly."""
    return _INLINE_MARKUP_RE.sub("", text)


def _is_numeric_cell(value: str) -> bool:
    return bool(_NUMERIC_CELL_RE.match(value))


def _parse_table_cells(line: str) -> list[str]:
    """Extract and strip cell strings from a pipe-delimited table row."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_total_row(cells: list[str]) -> bool:
    """Return True if this row should be rendered with total/subtotal emphasis.

    Detects rows whose first cell (markup stripped) starts with "total",
    "subtotal", or "grand total" — the conventional phrasing used in IFRS
    financial statements for aggregate line items.
    """
    if not cells:
        return False
    first_clean = _strip_inline_markup(cells[0]).strip().lower()
    return first_clean.startswith(("total", "subtotal", "grand total"))


def _format_aligned_table(table_lines: list[str]) -> list[tuple[str, bool, bool, bool]]:
    """Return a list of ``(formatted_line, is_sep, is_header, is_total)`` tuples.

    Columns are padded to uniform widths (based on the widest cell in each
    column).  Numeric columns (all body-row values match a number pattern) are
    right-aligned; all other columns are left-aligned.  The first non-separator
    row is treated as the header.  Total/subtotal rows (first cell starts with
    "total" or "subtotal") are flagged so callers can apply bold emphasis.

    Rows are rendered **without** surrounding pipe characters so the output
    looks like a professional financial statement rather than a CLI grid.
    Separator rows are rendered as a line of Unicode box-drawing characters
    (─) matching the width of the data rows.
    """
    # Parse each row: None means separator row, list[str] means data row
    parsed: list[list[str] | None] = []
    for line in table_lines:
        if _is_table_sep(line):
            parsed.append(None)
        else:
            parsed.append(_parse_table_cells(line))

    data_rows = [r for r in parsed if r is not None]
    if not data_rows:
        return [(line + "\n", False, False, False) for line in table_lines]

    num_cols = max(len(r) for r in data_rows)

    # Pad short rows to num_cols
    for r in data_rows:
        while len(r) < num_cols:
            r.append("")

    # Compute column widths from display text (markup stripped)
    col_widths = [3] * num_cols  # minimum 3
    for r in data_rows:
        for j, cell in enumerate(r):
            col_widths[j] = max(col_widths[j], len(_strip_inline_markup(cell)))

    # Detect numeric columns from body rows (rows after the header)
    body_rows = data_rows[1:] if len(data_rows) > 1 else []
    numeric_col = [False] * num_cols
    if body_rows:
        for j in range(num_cols):
            col_vals = [r[j] for r in body_rows if j < len(r) and r[j]]
            if col_vals and all(_is_numeric_cell(v) for v in col_vals):
                numeric_col[j] = True

    # Width of the rule line: two leading spaces + columns joined by two spaces
    rule_width = 2 + sum(col_widths) + 2 * max(num_cols - 1, 0)

    result: list[tuple[str, bool, bool, bool]] = []
    is_header_seen = False

    for item in parsed:
        if item is None:
            # Render separator as a Unicode horizontal rule (no pipes)
            sep = "─" * rule_width
            result.append((sep + "\n", True, False, False))
        else:
            padded_cells: list[str] = []
            for j, cell in enumerate(item):
                w = col_widths[j] if j < len(col_widths) else len(cell)
                display = _strip_inline_markup(cell)
                if not is_header_seen:
                    # Header: left-aligned
                    padded_cells.append(display.ljust(w))
                elif numeric_col[j]:
                    padded_cells.append(display.rjust(w))
                else:
                    padded_cells.append(display.ljust(w))
            # Two-space indent + two-space column separators (no outer pipes)
            row_str = "  " + "  ".join(padded_cells)
            is_hdr = not is_header_seen
            is_header_seen = is_header_seen or is_hdr
            is_total = not is_hdr and _is_total_row(item)
            result.append((row_str + "\n", False, is_hdr, is_total))

    return result


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def render_markdown_to_buffer(text: str, buf: Any) -> None:
    """Clear *buf* and insert *text* parsed as Markdown with formatting tags.

    Safe to call from the GTK main thread any time the response changes. During
    live streaming use plain ``buf.insert`` for performance; call this once the
    stream finishes to apply rich formatting to the completed response.
    """
    buf.set_text("")
    if not text:
        return

    _ensure_buffer_tags(buf)
    tag_table = buf.get_tag_table()

    def _ins(s: str, *tag_names: str) -> None:
        """Insert plain text with optional tags."""
        if not s:
            return
        tags = [tag_table.lookup(n) for n in tag_names]
        tags = [t for t in tags if t is not None]
        it = buf.get_end_iter()
        if tags:
            buf.insert_with_tags(it, s, *tags)
        else:
            buf.insert(it, s)

    lines = text.split("\n")
    i = 0
    in_code_block = False

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # ------------------------------------------------------------------
        # Fenced code block toggle
        # ------------------------------------------------------------------
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                # language hint (e.g. ```python) is intentionally ignored;
                # reserved for future syntax-highlight routing
                i += 1
                continue
            else:
                in_code_block = False
                _ins("\n")
                i += 1
                continue

        if in_code_block:
            _ins(raw + "\n", "code_block")
            i += 1
            continue

        # ------------------------------------------------------------------
        # Horizontal rule
        # ------------------------------------------------------------------
        if re.match(r"^\s*(---+|\*\*\*+|___+)\s*$", raw):
            _ins("─" * 40 + "\n", "h_rule")
            i += 1
            continue

        # ------------------------------------------------------------------
        # ATX headings  (#  ##  ###)
        # ------------------------------------------------------------------
        hm = re.match(r"^(#{1,3})\s+(.*)", raw)
        if hm:
            level = len(hm.group(1))
            tag_name = f"heading{min(level, 3)}"
            _insert_inline(buf, hm.group(2).strip(), extra_tag=tag_name)
            _ins("\n")
            i += 1
            continue

        # ------------------------------------------------------------------
        # Setext headings (underlined with === or ---)
        # ------------------------------------------------------------------
        if i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if re.match(r"^=+$", next_stripped) and stripped:
                _insert_inline(buf, stripped, extra_tag="heading1")
                _ins("\n")
                i += 2
                continue
            if re.match(r"^-+$", next_stripped) and stripped and not _is_table_row(raw):
                _insert_inline(buf, stripped, extra_tag="heading2")
                _ins("\n")
                i += 2
                continue

        # ------------------------------------------------------------------
        # Pipe tables
        # ------------------------------------------------------------------
        if _is_table_row(raw):
            # Collect contiguous table rows
            table_lines: list[str] = []
            while i < len(lines) and (_is_table_row(lines[i]) or _is_table_sep(lines[i])):
                table_lines.append(lines[i])
                i += 1
            # Render with column alignment; header row is bold; totals are bold
            for fmt_line, is_sep, is_hdr, is_total in _format_aligned_table(table_lines):
                if is_sep:
                    _ins(fmt_line, "table_sep")
                elif is_hdr:
                    _ins(fmt_line, "table_header")
                elif is_total:
                    _ins(fmt_line, "table_total")
                else:
                    _ins(fmt_line, "table")
            _ins("\n")
            continue

        # ------------------------------------------------------------------
        # Unordered list items  (- / * / •)
        # ------------------------------------------------------------------
        lm = re.match(r"^(\s*)([-*•])\s+(.*)", raw)
        if lm:
            indent = lm.group(1)
            content = lm.group(3)
            _ins(indent + "• ")
            _insert_inline(buf, content)
            _ins("\n")
            i += 1
            continue

        # ------------------------------------------------------------------
        # Ordered list items  (1. 2. …)
        # ------------------------------------------------------------------
        olm = re.match(r"^(\s*)(\d+)\.\s+(.*)", raw)
        if olm:
            indent = olm.group(1)
            num = olm.group(2)
            content = olm.group(3)
            _ins(f"{indent}{num}. ")
            _insert_inline(buf, content)
            _ins("\n")
            i += 1
            continue

        # ------------------------------------------------------------------
        # Blank line → preserve as paragraph break
        # ------------------------------------------------------------------
        if not stripped:
            _ins("\n")
            i += 1
            continue

        # ------------------------------------------------------------------
        # Regular paragraph line with possible inline formatting
        # ------------------------------------------------------------------
        _insert_inline(buf, raw)
        _ins("\n")
        i += 1
