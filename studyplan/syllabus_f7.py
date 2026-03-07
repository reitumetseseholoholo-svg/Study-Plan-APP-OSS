"""
Built-in ACCA FR (F7) syllabus: learning outcome IDs mapped to F7 chapters.
Used by the engine to auto-fill syllabus_structure when loading the F7 module,
so no script or manual JSON merge is required.
"""
from __future__ import annotations

# Outcome (id, chapter_index_1based, level). Chapter index 1..27 matches F7 order.
F7_OUTCOMES: list[tuple[str, int, int]] = [
    *[("A1" + c, 2, 2) for c in "abcdefg"],
    *[("A2" + c, 2, 2) for c in "abcde"],
    *[("A3" + c, 1, 2) for c in "abcdef"],
    *[("A4" + c, 21, 2) for c in "abcdefghi"],
    *[("B1" + c, 7, 2) for c in "abcdefg"],
    *[("B2" + c, 11, 2) for c in "abcde"],
    *[("B3" + c, 13, 2) for c in "abcde"],
    *[("B4" + c, 6, 2) for c in "ab"],
    *[("B5" + c, 18, 2) for c in "abcdef"],
    *[("B6" + c, 14, 2) for c in "abc"],
    *[("B7" + c, 16 if c == "g" else 15, 2) for c in "abcdefg"],
    *[("B8" + c, 17, 2) for c in "abc"],
    *[("B9" + c, 20, 2) for c in "abcdef"],
    *[("B10" + c, 5, 2) for c in "abcdef"],
    ("B11a", 9, 2),
    *[("B12" + c, 19, 2) for c in "ab"],
    *[("C1" + c, 26, 2) for c in "abcd"],
    *[("C2" + c, 26, 2) for c in "abcdef"],
    *[("C3" + c, 26, 2) for c in "abcd"],
    ("C4a", 26, 2),
    *[("D1" + c, 27 if c == "c" else 3, 2) for c in "abc"],
    ("D2a", 22, 2),
    ("D2b", 24, 2),
    *[("D2" + c, 23, 2) for c in "cdefgh"],
    ("D2i", 22, 2),
    ("E1", 1, 2),
    ("E2", 1, 2),
    ("E3", 1, 2),
    ("E4", 1, 2),
]


def _capability(chapter_title: str) -> str:
    if "Conceptual Framework" in chapter_title or "International Financial Reporting" in chapter_title:
        return "A"
    if any(
        x in chapter_title
        for x in [
            "IAS 16", "IAS 38", "IAS 36", "Inventories", "Financial Instruments",
            "IFRS 16", "IAS 37", "IAS 10", "IAS 12", "IAS 33", "IFRS 15",
            "Government", "Foreign Currency", "IFRS 5",
        ]
    ):
        return "B"
    if "Analysis and Interpretation" in chapter_title:
        return "C"
    if "Consolidat" in chapter_title or "IAS 7" in chapter_title or "IFRS 18" in chapter_title or "IAS 8" in chapter_title:
        return "D"
    return "E"


def get_f7_syllabus_structure(chapters: list[str]) -> dict[str, dict]:
    """
    Build syllabus_structure for FR (F7) from the built-in outcome→chapter mapping.
    chapters: list of chapter titles in F7 order (1-based index = position in list).
    Returns a dict suitable for engine.syllabus_structure (chapter title -> capability, learning_outcomes).
    """
    if not chapters:
        return {}
    # index 1..27 -> chapter title (chapters[0] = Ch1, ...)
    by_chapter: dict[str, list[dict]] = {ch: [] for ch in chapters}
    for outcome_id, ch_num, level in F7_OUTCOMES:
        if 1 <= ch_num <= len(chapters):
            ch_title = chapters[ch_num - 1]
            by_chapter[ch_title].append({
                "id": outcome_id,
                "text": f"Learning outcome {outcome_id}",
                "level": level,
            })
    return {
        ch: {
            "capability": _capability(ch),
            "learning_outcomes": by_chapter[ch],
            "outcome_count": len(by_chapter[ch]),
        }
        for ch in chapters
    }
