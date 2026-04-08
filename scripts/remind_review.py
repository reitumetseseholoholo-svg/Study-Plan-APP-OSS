#!/usr/bin/env python3
"""Send a desktop notification when SRS reviews are due.

Uses ``notify-send`` (libnotify) if available, otherwise prints to stdout.
Designed to be called from a cron job or a systemd timer.

Usage
-----
    python scripts/remind_review.py [--module MODULE_ID] [--min-due N]

Typical cron entry (runs every 30 minutes):
    */30 * * * * DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus \\
        python /path/to/scripts/remind_review.py --module acca_f7

Typical systemd timer: see ``scripts/studyplan-remind.timer`` for an example.

Exit codes
----------
0  Notification fired (or printed).
1  Error loading engine.
2  Due count below --min-due threshold; no notification sent.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_APP_NAME = "Study Plan"
_ICON = "appointment-soon"  # Standard freedesktop icon, widely available.


def _notify(summary: str, body: str, urgency: str = "normal") -> None:
    """Fire a desktop notification, falling back to stdout."""
    if shutil.which("notify-send"):
        cmd = [
            "notify-send",
            "--app-name", _APP_NAME,
            "--icon", _ICON,
            "--urgency", urgency,
            summary,
            body,
        ]
        try:
            subprocess.run(cmd, check=False, timeout=5)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Fallback: plain text
    print(f"[{_APP_NAME}] {summary}: {body}")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Send a desktop notification when SRS reviews are due.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--module",
        default=os.environ.get("STUDYPLAN_MODULE_ID", ""),
        metavar="MODULE_ID",
        help="Module ID (e.g. acca_f7).  Defaults to the active module.",
    )
    p.add_argument(
        "--min-due",
        type=int,
        default=1,
        metavar="N",
        help="Minimum number of due cards before firing a notification (default: 1).",
    )
    p.add_argument(
        "--urgency",
        choices=["low", "normal", "critical"],
        default="normal",
        help="Notification urgency level (default: normal).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        from studyplan_engine import StudyPlanEngine
    except ImportError as exc:
        print(f"Error: could not import StudyPlanEngine: {exc}", file=sys.stderr)
        return 1

    module_id = str(args.module or "").strip() or None
    try:
        engine = StudyPlanEngine(module_id=module_id)
    except Exception as exc:
        print(f"Error loading engine: {exc}", file=sys.stderr)
        return 1

    try:
        due_by_chapter = engine.get_due_today_by_chapter()
        total_due = sum(due_by_chapter.values())
        top_chapters = sorted(due_by_chapter.items(), key=lambda kv: kv[1], reverse=True)[:3]
    except Exception as exc:
        print(f"Error reading due counts: {exc}", file=sys.stderr)
        return 1

    if total_due < args.min_due:
        # Nothing to notify about.
        return 2

    module_label = str(engine.module_id or module_id or "Study Plan").upper()
    summary = f"{module_label}: {total_due} review{'s' if total_due != 1 else ''} due"

    body_parts = []
    for ch, count in top_chapters:
        # Shorten long chapter names.
        ch_display = ch if len(ch) <= 35 else ch[:32] + "…"
        body_parts.append(f"• {ch_display}: {count}")
    if len(due_by_chapter) > 3:
        body_parts.append(f"  + {len(due_by_chapter) - 3} more chapter(s)")
    body_parts.append("\nOpen the app to start reviewing.")
    body = "\n".join(body_parts)

    _notify(summary, body, urgency=args.urgency)
    return 0


if __name__ == "__main__":
    sys.exit(main())
