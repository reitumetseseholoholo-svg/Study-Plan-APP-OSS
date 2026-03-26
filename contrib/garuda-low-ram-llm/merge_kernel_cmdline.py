#!/usr/bin/env python3
"""Merge Study Plan low-RAM kernel tokens into dracut and/or GRUB cmdlines.

Tokens live in kernel-cmdline-studyplan-tuning.txt (one line, space-separated).
For key=value pairs, any existing token with the same key is removed before appending.
Bare flags are appended only if not already present.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


def _merge_tokens(existing: str, additions: list[str]) -> str:
    parts = list(existing.split())
    for add in additions:
        add = str(add or "").strip()
        if not add:
            continue
        if "=" in add:
            key = add.split("=", 1)[0]
            parts = [p for p in parts if not p.startswith(key + "=")]
            parts.append(add)
        elif add not in parts:
            parts.append(add)
    return " ".join(parts)


def _load_additions(repo: pathlib.Path) -> list[str]:
    path = repo / "kernel-cmdline-studyplan-tuning.txt"
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    return [t for t in raw.split() if t]


def merge_dracut(path: pathlib.Path, additions: list[str]) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        merged = _merge_tokens(inner, additions)
        return f'kernel_cmdline="{merged}"'

    new_text, n = re.subn(
        r'^kernel_cmdline="([^"]*)"\s*$',
        repl,
        text,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise SystemExit(
            f"Expected exactly one kernel_cmdline= line in {path}, matched {n}"
        )
    return new_text


def merge_grub_default(path: pathlib.Path, additions: list[str]) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        merged = _merge_tokens(inner, additions)
        return f'GRUB_CMDLINE_LINUX_DEFAULT="{merged}"'

    new_text, n = re.subn(
        r'^GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"\s*$',
        repl,
        text,
        flags=re.MULTILINE,
    )
    if n != 1:
        raise SystemExit(
            f"Expected exactly one GRUB_CMDLINE_LINUX_DEFAULT= in {path}, matched {n}"
        )
    return new_text


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--repo",
        type=pathlib.Path,
        required=True,
        help="Path to contrib/garuda-low-ram-llm",
    )
    p.add_argument(
        "--dracut",
        type=pathlib.Path,
        default=None,
        help="Path to dracut-custom.conf to rewrite in place",
    )
    p.add_argument(
        "--grub",
        type=pathlib.Path,
        default=None,
        help="Path to grub defaults to rewrite in place",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print merged lines only; do not write files",
    )
    args = p.parse_args()
    repo = args.repo.resolve()
    additions = _load_additions(repo)
    if not additions:
        print("No tokens in kernel-cmdline-studyplan-tuning.txt", file=sys.stderr)
        sys.exit(1)

    if args.dracut:
        path = args.dracut.resolve()
        new = merge_dracut(path, additions)
        if args.dry_run:
            m = re.search(
                r'^kernel_cmdline="([^"]*)"\s*$',
                new,
                flags=re.MULTILINE,
            )
            print("dracut kernel_cmdline:", m.group(1) if m else "?")
        else:
            path.write_text(new, encoding="utf-8")

    if args.grub:
        path = args.grub.resolve()
        new = merge_grub_default(path, additions)
        if args.dry_run:
            m = re.search(
                r'^GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"\s*$',
                new,
                flags=re.MULTILINE,
            )
            print("GRUB_CMDLINE_LINUX_DEFAULT:", m.group(1) if m else "?")
        else:
            path.write_text(new, encoding="utf-8")

    if not args.dracut and not args.grub:
        p.error("pass at least one of --dracut or --grub")


if __name__ == "__main__":
    main()
