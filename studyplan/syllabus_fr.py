"""
ACCA FR (F7) Financial Reporting syllabus parsing.

Parses FR syllabus PDF text (e.g. from pdftotext or PyMuPDF) into learning outcomes
with accurate section IDs (A1, B1, ... D2, E1) and maps each outcome to the correct
F7 chapter for syllabus_structure. Used by the app's Import Syllabus PDF and by
scripts/import_f7_syllabus_outcomes.py.

Supports both FR S25–J26 and S26–J27 (and later) syllabus formats; structure is unchanged.
"""
from __future__ import annotations

import re
from typing import Any

# F7 chapters (must match modules/acca_f7.json exactly)
F7_CHAPTERS: list[str] = [
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

# Syllabus section (A1, A2, B1, ... D2, E1) -> F7 chapter title (default for that section)
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
    "B7": "Chapter 15: IAS 37 Provisions, Contingent Liabilities and Contingent Assets",
    "B8": "Chapter 17: IAS 12 Income Taxes",
    "B9": "Chapter 20: IAS 33 Earnings per Share",
    "B10": "Chapter 5: IFRS 15 Revenue from Contracts with Customers",
    "B11": "Chapter 9: Government Grants",
    "B12": "Chapter 19: Foreign Currency Transactions",
    "C1": "Chapter 26: Analysis and Interpretation",
    "C2": "Chapter 26: Analysis and Interpretation",
    "C3": "Chapter 26: Analysis and Interpretation",
    "C4": "Chapter 26: Analysis and Interpretation",
    "D1": "Chapter 3: IFRS 18 Presentation and Disclosure in Financial Statements",
    "D2": "Chapter 22: Consolidated Statement of Financial Position",
    "E1": "Chapter 1: International Financial Reporting Standards",
    "E2": "Chapter 1: International Financial Reporting Standards",
    "E3": "Chapter 1: International Financial Reporting Standards",
    "E4": "Chapter 1: International Financial Reporting Standards",
}

# B7: outcome g) is IAS 10 Events after the Reporting Period (Ch16); a–f are Ch15
B7_EVENTS_AFTER_LETTERS = {"g"}

# D2: each outcome letter maps to a specific chapter (SFP, P/L, consolidation adjustments)
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

# D1c is Statement of Cash Flows (Ch27); D1a, D1b are Ch3
D1_CASH_FLOW_LETTER = "c"


def _clean(line: str) -> str:
    line = line.replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", line).strip()


def _map_outcome_to_chapter(section_id: str, letter: str, section: str) -> str | None:
    letter_low = letter.lower()
    if section == "B" and section_id == "B7" and letter_low in B7_EVENTS_AFTER_LETTERS:
        return "Chapter 16: IAS 10 Events after the Reporting Period"
    if section == "D" and section_id == "D2":
        return D2_OUTCOME_TO_CHAPTER.get(letter_low, SECTION_TO_CHAPTER.get("D2"))
    if section == "D" and section_id == "D1" and letter_low == D1_CASH_FLOW_LETTER:
        return "Chapter 27: IAS 7 Statement of Cash Flows"
    return SECTION_TO_CHAPTER.get(section_id)


def parse_syllabus_text(text: str) -> list[dict[str, Any]]:
    """
    Parse FR syllabus text and return list of {id, text, level, chapter}.

    Tracks section (A–E), subsection number (1–12), and lettered outcomes a), b) ...
    with .[1] or .[2] or .[3] intellectual level. Works for both S25–J26 and S26–J27
    (and later) FR syllabus PDFs; structure is the same.
    """
    lines = [_clean(ln) for ln in text.splitlines() if _clean(ln)]
    outcomes: list[dict[str, Any]] = []
    current_section = ""
    current_sub = 0
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

    in_guide = False
    for i, line in enumerate(lines):
        if "5. Detailed study guide" in line or (i > 0 and "5. Detailed study guide" in lines[i - 1]):
            in_guide = True
        if in_guide and ("6. Summary of changes" in line or (i > 0 and "6. Summary of changes" in lines[i - 1])):
            break
        if not in_guide:
            continue

        m_sec = re.match(r"^([A-E])\s+(.+)$", line)
        if m_sec and len(line) < 120:
            flush_outcome()
            current_section = m_sec.group(1).upper()
            current_sub = 0
            continue

        m_num = re.match(r"^(\d{1,2})\.\s+(.+)$", line)
        if m_num and current_section and len(line) < 150:
            flush_outcome()
            try:
                current_sub = int(m_num.group(1))
            except ValueError:
                pass
            continue

        m_out = re.match(r"^([a-z]\))\s*(.*)$", line)
        if m_out and current_section and current_sub:
            flush_outcome()
            outcome_letter = m_out.group(1).replace(")", "").strip()
            rest = (m_out.group(2) or "").strip()
            outcome_text_parts = [rest] if rest else []
            outcome_level = None
            lev = re.search(r"\.\[([123])\]\s*$", rest)
            if lev:
                try:
                    outcome_level = int(lev.group(1))
                    outcome_text_parts = [re.sub(r"\s*\.\[[123]\]\s*$", "", rest).strip()]
                except ValueError:
                    pass
            continue

        if outcome_text_parts and line and not re.match(r"^[A-E]\s", line) and not re.match(r"^\d{1,2}\.\s", line):
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

    flush_outcome()
    return outcomes


def _chapter_capability(chapter: str) -> str:
    """Return capability letter (A–E) for a chapter title."""
    if "Conceptual Framework" in chapter or "International Financial Reporting" in chapter:
        return "A"
    if any(
        x in chapter
        for x in [
            "IAS 16",
            "IAS 38",
            "IAS 36",
            "Inventories",
            "Financial Instruments",
            "IFRS 16",
            "IAS 37",
            "IAS 10",
            "IAS 12",
            "IAS 33",
            "IFRS 15",
            "Government",
            "Foreign Currency",
            "IFRS 5",
        ]
    ):
        return "B"
    if "Analysis and Interpretation" in chapter:
        return "C"
    if "Consolidat" in chapter or "IAS 7" in chapter or "IFRS 18" in chapter or "IAS 8" in chapter:
        return "D"
    return "E"


def extract_subtopics_from_section_4(text: str) -> dict[str, str]:
    """
    Extract section 4 "The syllabus" numbered titles as section_id -> title.

    Parses lines like "A Conceptual framework", "1. First area", "2. Second area"
    under "4. The syllabus" and returns e.g. {"A1": "First area", "A2": "Second area"}.
    Used to populate syllabus_structure subtopics per chapter for a better concept graph.
    """
    section_titles: dict[str, str] = {}
    lines = [_clean(ln) for ln in text.splitlines() if _clean(ln)]
    in_section_4 = False
    current_letter: str | None = None
    for line in lines:
        if re.match(r"^\s*4\.\s*the\s+syllabus\b", line, re.IGNORECASE):
            in_section_4 = True
            current_letter = None
            continue
        if in_section_4 and re.match(r"^\s*5\.\s*deta", line, re.IGNORECASE):
            break
        if not in_section_4:
            continue
        m_letter = re.match(r"^([A-E])\s+(.+)$", line)
        if m_letter and len(line) < 200:
            current_letter = m_letter.group(1).upper()
            continue
        m_num = re.match(r"^(\d{1,2})\.\s+(.+)$", line)
        if m_num and current_letter:
            try:
                num = int(m_num.group(1))
                title = (m_num.group(2) or "").strip()
                if title:
                    section_id = f"{current_letter}{num}"
                    section_titles[section_id] = title
            except ValueError:
                pass
    return section_titles


def build_syllabus_structure(
    outcomes: list[dict[str, Any]],
    *,
    chapter_list: list[str] | None = None,
    section4_titles: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Group outcomes by chapter for syllabus_structure.

    If chapter_list is provided (e.g. from base config), use those exact keys so
    the result merges cleanly with the module. Otherwise use F7_CHAPTERS.
    If section4_titles is provided (from extract_subtopics_from_section_4), each
    chapter gets subtopics from the section-4 titles that map to that chapter.
    """
    chapters = chapter_list if chapter_list is not None else F7_CHAPTERS
    by_chapter: dict[str, list[dict[str, Any]]] = {ch: [] for ch in chapters}
    for o in outcomes:
        ch = o.get("chapter")
        if ch and ch in by_chapter:
            by_chapter[ch].append({
                "id": o["id"],
                "text": o["text"],
                "level": int(o.get("level", 2)),
            })
    section4 = section4_titles or {}
    # Section order for stable subtopic order per chapter (A1, A2, A3, A4, B1, ...)
    section_order = [f"{l}{n}" for l in "ABCDE" for n in range(1, 13)]
    result: dict[str, dict[str, Any]] = {}
    for ch in chapters:
        subtopics: list[str] = []
        for sid in section_order:
            if SECTION_TO_CHAPTER.get(sid) == ch and sid in section4:
                subtopics.append(section4[sid])
        result[ch] = {
            "capability": _chapter_capability(ch),
            "subtopics": subtopics,
            "learning_outcomes": by_chapter[ch],
            "outcome_count": len(by_chapter[ch]),
        }
    return result


def extract_capabilities_from_text(text: str) -> dict[str, str]:
    """
    Extract Main capabilities (A–E) from FR syllabus text (section 2).
    Returns dict mapping letter -> full title.
    """
    capabilities: dict[str, str] = {}
    lines = [_clean(ln) for ln in text.splitlines() if _clean(ln)]
    in_cap = False
    for line in lines:
        if re.match(r"^\s*2\.\s*main\s+capab", line, re.IGNORECASE):
            in_cap = True
            continue
        if in_cap and re.match(r"^\s*3\.\s*", line):
            break
        if in_cap:
            m = re.match(r"^([A-E])\s+(.+)$", line)
            if m:
                capabilities[m.group(1)] = m.group(2).strip()
    return capabilities


def is_fr_syllabus_text(text: str) -> bool:
    """Return True if the text appears to be an ACCA FR (Financial Reporting) syllabus."""
    if not text or not isinstance(text, str):
        return False
    t = text.strip().upper()
    if "FINANCIAL REPORTING (FR)" in t or "FINANCIAL REPORTING ( FR )" in t:
        return True
    if "FR)" in t and "SYLLABUS" in t and "STUDY GUIDE" in t:
        return True
    if re.search(r"\bFR\b.*SYLLABUS", t) and "DETAILED STUDY GUIDE" in t:
        return True
    return False
