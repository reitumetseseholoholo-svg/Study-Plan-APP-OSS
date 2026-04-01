#!/usr/bin/env python3
"""
Update a module JSON with a canonical chapter list (robust method).

Usage:
  python scripts/update_module_chapters.py modules/acca_f8.json chapters.json [--in-place]
  python scripts/update_module_chapters.py modules/acca_f8.json chapters.yaml --in-place
  echo '["Ch 1: Foo", "Ch 2: Bar"]' | python scripts/update_module_chapters.py modules/acca_f8.json - [--in-place]

Chapter spec file format:
  - JSON: array of strings, or array of {"title": "...", "weight": 10} (weight optional).
  - YAML: same structure.

If --in-place is set, the module JSON file is overwritten; otherwise the result is printed to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Allow importing studyplan when run from repo root or scripts/
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from studyplan.module_chapters import (
    apply_chapters_to_config,
    load_chapter_spec_from_path,
    normalize_chapter_spec,
    validate_chapter_config,
)


def _load_module_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise ValueError(f"Cannot read module config {path!r}: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in module config {path!r}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Module JSON must be an object")
    return data


def _load_chapter_spec(path: str | None) -> list:
    if path is None or path == "-":
        raw = sys.stdin.read()
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("Stdin chapter spec must be a JSON array")
        return data
    return load_chapter_spec_from_path(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update module JSON with a canonical chapter list (chapters, flow, weights)."
    )
    parser.add_argument(
        "module_json",
        help="Path to the module JSON file (e.g. modules/acca_f8.json)",
    )
    parser.add_argument(
        "chapters_file",
        nargs="?",
        default=None,
        help="Path to chapter spec (JSON/YAML) or '-' to read JSON array from stdin",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the module JSON file with the result",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.module_json):
        print(f"Error: module file not found: {args.module_json}", file=sys.stderr)
        return 1

    try:
        config = _load_module_config(args.module_json)
    except Exception as e:
        print(f"Error loading module JSON: {e}", file=sys.stderr)
        return 1

    if args.chapters_file is None and not sys.stdin.isatty():
        args.chapters_file = "-"

    if args.chapters_file is None:
        print(
            "Error: provide a chapter spec file path, or pipe a JSON array to stdin (use '-' as chapters_file).",
            file=sys.stderr,
        )
        return 1

    try:
        spec = _load_chapter_spec(args.chapters_file)
    except Exception as e:
        print(f"Error loading chapter spec: {e}", file=sys.stderr)
        return 1

    updated = apply_chapters_to_config(config, spec)
    warnings = validate_chapter_config(updated)
    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)

    out = json.dumps(updated, indent=2, ensure_ascii=False)

    if args.in_place:
        with open(args.module_json, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"Updated {args.module_json} ({len(updated.get('chapters', []))} chapters).", file=sys.stderr)
    else:
        print(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
