#!/usr/bin/env python3
"""Simple GTK4 lint: flags common GTK3 APIs in .py files.
Heuristic filters are included to avoid false positives with our wrappers.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

PATTERNS = [
    (r"Gtk\.Assistant\b", "Gtk.Assistant (removed in GTK4)"),
    (r"Gtk\.MessageDialog\b", "Gtk.MessageDialog (removed in GTK4)"),
    (r"Gtk\.Dialog\b", "Gtk.Dialog (removed in GTK4)"),
    (r"Gtk\.FileChooserDialog\b", "Gtk.FileChooserDialog (use FileChooserNative)"),
    (r"Gtk\.ComboBox(Text)?\b", "Gtk.ComboBox/ComboBoxText (GTK4 uses DropDown)"),
    (r"Gtk\.TreeView\b", "Gtk.TreeView (deprecated/removed in GTK4)"),
    (r"Gtk\.ListStore\b", "Gtk.ListStore (GTK4 uses ListModel)"),
    (r"Gtk\.ShortcutsWindow\b", "Gtk.ShortcutsWindow (GTK4 still exists but often broken)"),
]

IGNORE_BY_PATTERN = {
    "Gtk.FileChooserDialog (use FileChooserNative)": ["_dialog_smoke_mode"],
}

IGNORE = ["# gtk4_lint:ignore"]


def iter_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*.py"):
        if ".venv" in path.parts:
            continue
        if "tools" in path.parts:
            continue
        files.append(path)
    return files


def should_ignore(msg: str, line: str) -> bool:
    for tag in IGNORE:
        if tag in line:
            return True
    for needle in IGNORE_BY_PATTERN.get(msg, []):
        if needle in line:
            return True
    return False


def lint_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    findings = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        for pattern, msg in PATTERNS:
            if re.search(pattern, line):
                if should_ignore(msg, line):
                    continue
                findings.append(f"{path}:{i}: {msg}: {line.strip()}")
    return findings


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    all_findings = []
    for path in iter_files(root):
        all_findings.extend(lint_file(path))
    if all_findings:
        print("GTK4 lint findings:")
        for item in all_findings:
            print(item)
        return 1
    print("GTK4 lint: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
