#!/usr/bin/env python3
"""
Parse ACCA FR (F7) syllabus PDF text and map each learning outcome to an F7 chapter.
Outputs syllabus_structure for merging into modules/acca_f7.json.

Uses studyplan.syllabus_fr for parsing and section→chapter mapping. Supports both
FR S25–J26 and S26–J27 (and later) syllabus PDFs.

Usage:
  pdftotext -layout "path/to/FR S25-J26 syllabus and study guide.pdf" - | python scripts/import_f7_syllabus_outcomes.py
  pdftotext -layout "path/to/fr_s26_j27_syllabus_and_study_guide.pdf" - | python scripts/import_f7_syllabus_outcomes.py
  or
  python scripts/import_f7_syllabus_outcomes.py < syllabus_text.txt

Run from project root so that studyplan is importable, or set PYTHONPATH to the repo root.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on path when run as script
_script_dir = Path(__file__).resolve().parent
_root = _script_dir.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from studyplan.syllabus_fr import (
    F7_CHAPTERS,
    build_syllabus_structure,
    parse_syllabus_text,
)

# Fallback: full list of 95 FR outcome IDs and their F7 chapter (when PDF parse yields few outcomes)
FR_CHAPTER_KEY_TO_TITLE: dict[str, str] = {
    "Ch1": F7_CHAPTERS[0],
    "Ch2": F7_CHAPTERS[1],
    "Ch3": F7_CHAPTERS[2],
    "Ch4": F7_CHAPTERS[3],
    "Ch5": F7_CHAPTERS[4],
    "Ch6": F7_CHAPTERS[5],
    "Ch7": F7_CHAPTERS[6],
    "Ch8": F7_CHAPTERS[7],
    "Ch9": F7_CHAPTERS[8],
    "Ch10": F7_CHAPTERS[9],
    "Ch11": F7_CHAPTERS[10],
    "Ch12": F7_CHAPTERS[11],
    "Ch13": F7_CHAPTERS[12],
    "Ch14": F7_CHAPTERS[13],
    "Ch15": F7_CHAPTERS[14],
    "Ch16": F7_CHAPTERS[15],
    "Ch17": F7_CHAPTERS[16],
    "Ch18": F7_CHAPTERS[17],
    "Ch19": F7_CHAPTERS[18],
    "Ch20": F7_CHAPTERS[19],
    "Ch21": F7_CHAPTERS[20],
    "Ch22": F7_CHAPTERS[21],
    "Ch23": F7_CHAPTERS[22],
    "Ch24": F7_CHAPTERS[23],
    "Ch25": F7_CHAPTERS[24],
    "Ch26": F7_CHAPTERS[25],
    "Ch27": F7_CHAPTERS[26],
}
FR_OUTCOME_IDS_AND_CHAPTERS: list[tuple[str, str, int]] = [
    *[("A1" + c, "Ch2", 2) for c in "abcdefg"],
    *[("A2" + c, "Ch2", 2) for c in "abcde"],
    *[("A3" + c, "Ch1", 2) for c in "abcdef"],
    *[("A4" + c, "Ch21", 2) for c in "abcdefghi"],
    *[("B1" + c, "Ch7", 2) for c in "abcdefg"],
    *[("B2" + c, "Ch11", 2) for c in "abcde"],
    *[("B3" + c, "Ch13", 2) for c in "abcde"],
    *[("B4" + c, "Ch6", 2) for c in "ab"],
    *[("B5" + c, "Ch18", 2) for c in "abcdef"],
    *[("B6" + c, "Ch14", 2) for c in "abc"],
    *[("B7" + c, "Ch16" if c == "g" else "Ch15", 2) for c in "abcdefg"],
    *[("B8" + c, "Ch17", 2) for c in "abc"],
    *[("B9" + c, "Ch20", 2) for c in "abcdef"],
    *[("B10" + c, "Ch5", 2) for c in "abcdef"],
    ("B11a", "Ch9", 2),
    *[("B12" + c, "Ch19", 2) for c in "ab"],
    *[("C1" + c, "Ch26", 2) for c in "abcd"],
    *[("C2" + c, "Ch26", 2) for c in "abcdef"],
    *[("C3" + c, "Ch26", 2) for c in "abcd"],
    ("C4a", "Ch26", 2),
    *[("D1" + c, "Ch27" if c == "c" else "Ch3", 2) for c in "abc"],
    ("D2a", "Ch22", 2),
    ("D2b", "Ch24", 2),
    *[("D2" + c, "Ch23", 2) for c in "cdefgh"],
    ("D2i", "Ch22", 2),
    ("E1", "Ch1", 2),
    ("E2", "Ch1", 2),
    ("E3", "Ch1", 2),
    ("E4", "Ch1", 2),
]


def main() -> int:
    if sys.stdin.isatty():
        for name in (
            "FR S25-J26 syllabus and study guide.pdf",
            "fr_s26_j27_syllabus_and_study_guide.pdf",
        ):
            pdf_path = Path.cwd() / name
            if not pdf_path.exists():
                pdf_path = Path.home() / "Downloads" / name
            if pdf_path.exists():
                import subprocess
                result = subprocess.run(
                    ["pdftotext", "-layout", str(pdf_path), "-"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                text = result.stdout or ""
                break
        else:
            text = ""
        if not text.strip():
            print(
                "Pipe syllabus text to stdin, or place an FR syllabus PDF in current dir or ~/Downloads.",
                file=sys.stderr,
            )
            return 1
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("No syllabus text read.", file=sys.stderr)
        return 1

    outcomes = parse_syllabus_text(text)
    if not outcomes or len(outcomes) < 50:
        if outcomes:
            print("Warning: few outcomes parsed; using static 95-outcome map.", file=sys.stderr)
        outcomes = []
        for oid, ch_key, level in FR_OUTCOME_IDS_AND_CHAPTERS:
            outcomes.append({
                "id": oid,
                "text": f"Learning outcome {oid}",
                "level": level,
                "chapter": FR_CHAPTER_KEY_TO_TITLE[ch_key],
            })

    structure = build_syllabus_structure(outcomes)
    print(json.dumps({"syllabus_structure": structure, "outcome_count": len(outcomes)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
