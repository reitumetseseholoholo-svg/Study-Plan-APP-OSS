#!/usr/bin/env python3
"""Export all flashcards (questions + SRS state) to a CSV file.

Usage
-----
    python scripts/export_flashcards.py [OUTPUT.csv] [--module MODULE_ID]

If OUTPUT is omitted the file is written to ``~/flashcards_export.csv``.

The CSV is compatible with the study-plan CSV import format so it can be
re-imported after editing.  It also includes SRS-state columns for use with
third-party tools such as Anki.

Environment variables
---------------------
STUDYPLAN_MODULE_ID
    Module to export (overrides --module).
STUDYPLAN_CONFIG_HOME
    Override for the config home directory.
"""
from __future__ import annotations

import argparse
import os
import sys

# Ensure repo root is on the path when invoked from the scripts directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export flashcards with SRS state to a CSV file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "output",
        nargs="?",
        default=os.path.expanduser("~/flashcards_export.csv"),
        help="Destination CSV path (default: ~/flashcards_export.csv)",
    )
    p.add_argument(
        "--module",
        default=os.environ.get("STUDYPLAN_MODULE_ID", ""),
        metavar="MODULE_ID",
        help="Module ID to export (e.g. acca_f7).  Defaults to the default module.",
    )
    p.add_argument(
        "--chapters",
        nargs="+",
        metavar="CHAPTER",
        help="Restrict export to specific chapter names (space-separated).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    output_path = os.path.expanduser(str(args.output))
    output_dir = os.path.dirname(output_path) or "."
    if not os.path.isdir(output_dir):
        print(f"Error: output directory does not exist: {output_dir}", file=sys.stderr)
        return 1

    print("Loading study plan engine…", flush=True)
    try:
        from studyplan_engine import StudyPlanEngine
    except ImportError as exc:
        print(f"Error: could not import StudyPlanEngine: {exc}", file=sys.stderr)
        return 1

    module_id = str(args.module or "").strip() or None
    engine = StudyPlanEngine(module_id=module_id)

    chapters = args.chapters if args.chapters else None

    print(f"Exporting flashcards → {output_path}")
    try:
        result = engine.export_flashcards_csv(output_path, chapters=chapters)
    except Exception as exc:
        print(f"Error during export: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: {result['rows_written']} cards exported across "
        f"{len(result['chapters'])} chapter(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
