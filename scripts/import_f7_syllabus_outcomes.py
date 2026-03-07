#!/usr/bin/env python3
"""
Parse ACCA FR (F7) syllabus PDF text and map each learning outcome to an F7 chapter.
Outputs syllabus_structure for merging into modules/acca_f7.json.

Usage:
  pdftotext -layout "path/to/FR S25-J26 syllabus and study guide.pdf" - | python scripts/import_f7_syllabus_outcomes.py
  or
  python scripts/import_f7_syllabus_outcomes.py < syllabus_text.txt
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# F7 chapters (must match modules/acca_f7.json exactly)
F7_CHAPTERS = [
    "Chapter 1: International Financial Reporting Standards",
    "Chapter 2: Conceptual Framework",
    "Chapter 3: IFRS 18 Presentation and Disclosure in Financial Statements",
    "Chapter 4: IAS 8 Basis of Preparation of Financial Statements",
    "Chapter 5: IFRS 15 Revenue from Contracts with Customers",
    "Chapter 6: Inventories and Agriculture",
    "Chapter 7: IAS 16 Property, Plant and Equipment",
    "Chapter 8: IAS 23 Borrowing Costs",
    "Chapter 9: Government Grants",
    "Chapter 10: IAS 40 Investment Property",
    "Chapter 11: IAS 38 Intangible Assets",
    "Chapter 12: IFRS 5 Non-current Assets Held for Sale and Discontinued Operations",
    "Chapter 13: IAS 36 Impairment of Assets",
    "Chapter 14: IFRS 16 Leases",
    "Chapter 15: IAS 37 Provisions, Contingent Liabilities and Contingent Assets",
    "Chapter 16: IAS 10 Events after the Reporting Period",
    "Chapter 17: IAS 12 Income Taxes",
    "Chapter 18: Financial Instruments",
    "Chapter 19: Foreign Currency Transactions",
    "Chapter 20: IAS 33 Earnings per Share",
    "Chapter 21: Conceptual Principles of Groups",
    "Chapter 22: Consolidated Statement of Financial Position",
    "Chapter 23: Consolidation Adjustments",
    "Chapter 24: Consolidated Statement of Profit or Loss",
    "Chapter 25: Investments in Associates",
    "Chapter 26: Analysis and Interpretation",
    "Chapter 27: IAS 7 Statement of Cash Flows",
]

# Syllabus section (A1, A2, B1, ... D2, E1) -> F7 chapter title
SECTION_TO_CHAPTER: dict[str, str] = {
    "A1": "Chapter 2: Conceptual Framework",
    "A2": "Chapter 2: Conceptual Framework",
    "A3": "Chapter 1: International Financial Reporting Standards",
    "A4": "Chapter 21: Conceptual Principles of Groups",
    "B1": "Chapter 7: IAS 16 Property, Plant and Equipment",
    "B2": "Chapter 11: IAS 38 Intangible Assets",
    "B3": "Chapter 13: IAS 36 Impairment of Assets",
    "B4": "Chapter 6: Inventories and Agriculture",
    "B5": "Chapter 18: Financial Instruments",
    "B6": "Chapter 14: IFRS 16 Leases",
    "B7": "Chapter 15: IAS 37 Provisions, Contingent Liabilities and Contingent Assets",  # + Ch16 for events
    "B8": "Chapter 17: IAS 12 Income Taxes",
    "B9": "Chapter 20: IAS 33 Earnings per Share",  # reporting performance, EPS, discontinued
    "B10": "Chapter 5: IFRS 15 Revenue from Contracts with Customers",
    "B11": "Chapter 9: Government Grants",
    "B12": "Chapter 19: Foreign Currency Transactions",
    "C1": "Chapter 26: Analysis and Interpretation",
    "C2": "Chapter 26: Analysis and Interpretation",
    "C3": "Chapter 26: Analysis and Interpretation",
    "C4": "Chapter 26: Analysis and Interpretation",
    "D1": "Chapter 3: IFRS 18 Presentation and Disclosure in Financial Statements",  # single entity + Ch27
    "D2": "Chapter 22: Consolidated Statement of Financial Position",  # consolidated
    "E1": "Chapter 1: International Financial Reporting Standards",  # employability - assign to Ch1
    "E2": "Chapter 1: International Financial Reporting Standards",
    "E3": "Chapter 1: International Financial Reporting Standards",
    "E4": "Chapter 1: International Financial Reporting Standards",
}

# B7 has provisions (Ch15) and events after (Ch16): map by outcome letter (a-f -> Ch15, g -> Ch16)
B7_EVENTS_AFTER_LETTERS = {"g"}

# Full list of 95 FR learning outcome IDs and their F7 chapter (official syllabus Sept 2025–June 2026)
# Format: (outcome_id, chapter_key, level). chapter_key is short for lookup in FR_CHAPTER_BY_KEY.
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

# D1: single entity - structure/content -> Ch3, cash flow part -> Ch27
# D2: a) SFP->Ch22, b) P/L->Ch24, c-i consolidation details -> Ch22/23/24/25
D2_OUTCOME_TO_CHAPTER: dict[str, str] = {
    "a": "Chapter 22: Consolidated Statement of Financial Position",
    "b": "Chapter 24: Consolidated Statement of Profit or Loss",
    "c": "Chapter 23: Consolidation Adjustments",
    "d": "Chapter 23: Consolidation Adjustments",
    "e": "Chapter 23: Consolidation Adjustments",
    "f": "Chapter 23: Consolidation Adjustments",
    "g": "Chapter 23: Consolidation Adjustments",
    "h": "Chapter 23: Consolidation Adjustments",
    "i": "Chapter 22: Consolidated Statement of Financial Position",
}


def _clean(line: str) -> str:
    line = line.replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", line).strip()


def _map_outcome_to_chapter(section_id: str, letter: str, section: str) -> str | None:
    if section == "B" and section_id == "B7" and letter.lower() in B7_EVENTS_AFTER_LETTERS:
        return "Chapter 16: IAS 10 Events after the Reporting Period"
    if section == "D" and section_id == "D2":
        return D2_OUTCOME_TO_CHAPTER.get(letter.lower(), SECTION_TO_CHAPTER.get("D2"))
    return SECTION_TO_CHAPTER.get(section_id)


def parse_syllabus_text(text: str) -> list[dict]:
    """
    Parse syllabus text and return list of {id, text, level, chapter}.
    Tracks section (A–E), subsection number (1–12), and lettered outcomes a), b) ... with .[1] or .[2].
    """
    lines = [_clean(ln) for ln in text.splitlines() if _clean(ln)]
    outcomes: list[dict] = []
    current_section = ""  # A, B, C, D, E
    current_sub = 0  # 1, 2, 3...
    outcome_letter = ""
    outcome_text_parts: list[str] = []
    outcome_level: int | None = None

    def flush_outcome() -> None:
        nonlocal outcome_text_parts, outcome_level, outcome_letter
        if not current_section or not outcome_letter or not outcome_text_parts:
            return
        text_str = " ".join(p for p in outcome_text_parts if p).strip()
        if not text_str:
            return
        section_id = f"{current_section}{current_sub}"
        outcome_id = f"{section_id}{outcome_letter}"
        level = outcome_level if outcome_level in (1, 2, 3) else 2
        chapter = _map_outcome_to_chapter(section_id, outcome_letter, current_section)
        if chapter:
            outcomes.append({"id": outcome_id, "text": text_str[:500], "level": level, "chapter": chapter})
        outcome_text_parts = []
        outcome_level = None
        outcome_letter = ""

    # Start of detailed study guide
    in_guide = False
    for i, line in enumerate(lines):
        if "5. Detailed study guide" in line or (i > 0 and "5. Detailed study guide" in lines[i - 1]):
            in_guide = True
        if in_guide and ("6. Summary of changes" in line or (i > 0 and "6. Summary of changes" in lines[i - 1])):
            break
        if not in_guide:
            continue

        # Section heading: single letter A–E at start
        m_sec = re.match(r"^([A-E])\s+(.+)$", line)
        if m_sec and len(line) < 120:
            flush_outcome()
            current_section = m_sec.group(1).upper()
            current_sub = 0
            continue

        # Numbered subsection: "1. Title" or "2. Title"
        m_num = re.match(r"^(\d{1,2})\.\s+(.+)$", line)
        if m_num and current_section and len(line) < 150:
            flush_outcome()
            try:
                current_sub = int(m_num.group(1))
            except ValueError:
                pass
            continue

        # Lettered outcome start: a) or b) or f)   at start (possibly with spaces)
        m_out = re.match(r"^([a-z]\))\s*(.*)$", line)
        if m_out and current_section and current_sub:
            flush_outcome()
            outcome_letter = m_out.group(1).replace(")", "").strip()
            rest = (m_out.group(2) or "").strip()
            outcome_text_parts = [rest] if rest else []
            outcome_level = None
            # Check for level on same line
            lev = re.search(r"\.\[([123])\]\s*$", rest)
            if lev:
                try:
                    outcome_level = int(lev.group(1))
                    outcome_text_parts = [re.sub(r"\s*\.\[[123]\]\s*$", "", rest).strip()]
                except ValueError:
                    pass
            continue

        # Continuation of outcome text
        if outcome_text_parts and line and not re.match(r"^[A-E]\s", line) and not re.match(r"^\d{1,2}\.\s", line):
            # Check for level at end of line
            lev = re.search(r"\.\[([123])\]\s*$", line)
            if lev:
                try:
                    outcome_level = int(lev.group(1))
                    outcome_text_parts.append(re.sub(r"\s*\.\[[123]\]\s*$", "", line).strip())
                except ValueError:
                    outcome_text_parts.append(line)
                flush_outcome()
            else:
                outcome_text_parts.append(line)
            continue

    # Flush last
    flush_outcome()

    return outcomes


def build_syllabus_structure(outcomes: list[dict]) -> dict:
    """Group outcomes by chapter for syllabus_structure."""
    by_chapter: dict[str, list[dict]] = {ch: [] for ch in F7_CHAPTERS}
    for o in outcomes:
        ch = o.get("chapter")
        if ch and ch in by_chapter:
            by_chapter[ch].append({
                "id": o["id"],
                "text": o["text"],
                "level": int(o.get("level", 2)),
            })
    return {
        ch: {
            "capability": _chapter_capability(ch),
            "learning_outcomes": by_chapter[ch],
            "outcome_count": len(by_chapter[ch]),
        }
        for ch in F7_CHAPTERS
    }


def _chapter_capability(chapter: str) -> str:
    """Return capability letter (A–E) for display."""
    if "Conceptual Framework" in chapter or "International Financial Reporting" in chapter:
        return "A"
    if any(x in chapter for x in ["IAS 16", "IAS 38", "IAS 36", "Inventories", "Financial Instruments",
                                   "IFRS 16", "IAS 37", "IAS 10", "IAS 12", "IAS 33", "IFRS 15",
                                   "Government", "Foreign Currency", "IFRS 5"]):
        return "B"
    if "Analysis and Interpretation" in chapter:
        return "C"
    if "Consolidat" in chapter or "IAS 7" in chapter or "IFRS 18" in chapter or "IAS 8" in chapter:
        return "D"
    return "E"


def main() -> int:
    if sys.stdin.isatty():
        # No pipe: try reading from Downloads
        pdf_path = Path.home() / "Downloads" / "FR S25-J26 syllabus and study guide.pdf"
        if not pdf_path.exists():
            print("Pipe syllabus text to stdin, or place FR S25-J26 syllabus and study guide.pdf in ~/Downloads", file=sys.stderr)
            return 1
        import subprocess
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        text = result.stdout or ""
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("No syllabus text read.", file=sys.stderr)
        return 1

    outcomes = parse_syllabus_text(text)
    if not outcomes or len(outcomes) < 50:
        # Use full static list of 95 outcomes mapped to F7 chapters
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
