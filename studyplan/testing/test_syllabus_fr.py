"""Tests for studyplan.syllabus_fr (FR syllabus parsing and section→chapter mapping)."""

from __future__ import annotations

import pytest

from studyplan.syllabus_fr import (
    F7_CHAPTERS,
    build_syllabus_structure,
    extract_capabilities_from_text,
    extract_subtopics_from_section_4,
    is_fr_syllabus_text,
    parse_syllabus_text,
)


# Sample FR syllabus text (start of "5. Detailed study guide") – S25–J26 / S26–J27 style
SAMPLE_FR_DETAILED_GUIDE = """
Financial Reporting (FR)
Syllabus and Study guide.
September 2025 to June 2026

2. Main capabilities
A      Discuss and apply conceptual and regulatory frameworks for financial reporting
B      Account for transactions in accordance with IFRS Accounting Standards
C      Analyse and interpret financial statements.
D      Prepare and present financial statements for single entities and business combinations
E      Demonstrate employability and technology skills

5. Detailed study guide

A The conceptual and regulatory framework for financial reporting

1. The need for a conceptual framework and the characteristics of useful information

a) Describe what is meant by a conceptual framework for financial reporting.[2]
b) Discuss whether a conceptual framework is necessary and what an alternative system might be.[2]
c) Discuss what is meant by relevance and faithful representation and describe the qualities that enhance these characteristics.[2]

2. Recognition and measurement

a) Explain the purpose of recognition in financial statements and discuss the recognition criteria.[2]
b) Explain and compute amounts using the following measures: [2]
   i) historical cost
   ii) current cost
   iii) value in use/ fulfilment value
   iv) fair value

B Accounting for transactions in financial statements

1. Tangible non-current assets

a) Define and compute the initial cost of property, plant and equipment.[2]
b) Explain and apply the revaluation model.[2]

7. Provisions and events after the reporting period

a) Identify and account for provisions.[2]
b) Explain the recognition criteria for provisions.[2]
g) Account for events after the reporting period.[2]

D Preparation of financial statements

2. Preparation of consolidated financial statements for a simple group

a) Prepare a consolidated statement of financial position.[2]
b) Prepare a consolidated statement of profit or loss.[2]
c) Account for the effects of acquisition and disposal of subsidiaries.[2]

6. Summary of changes to Financial Reporting (FR)
"""


def test_is_fr_syllabus_text_accepts_fr_syllabus() -> None:
    assert is_fr_syllabus_text("Financial Reporting (FR)\nSyllabus and Study guide.") is True
    assert is_fr_syllabus_text("FR)\nSyllabus\nDETAILED STUDY GUIDE") is True


def test_is_fr_syllabus_text_rejects_non_fr() -> None:
    assert is_fr_syllabus_text("Financial Management (FM)\nSyllabus.") is False
    assert is_fr_syllabus_text("") is False


def test_parse_syllabus_text_extracts_section_and_lettered_outcomes() -> None:
    outcomes = parse_syllabus_text(SAMPLE_FR_DETAILED_GUIDE)
    assert len(outcomes) >= 10
    ids = [o["id"] for o in outcomes]
    assert "A1a" in ids
    assert "A1b" in ids
    assert "A2a" in ids
    assert "B1a" in ids
    assert "B7g" in ids
    assert "D2a" in ids
    assert "D2b" in ids


def test_parse_syllabus_text_maps_outcomes_to_f7_chapters() -> None:
    outcomes = parse_syllabus_text(SAMPLE_FR_DETAILED_GUIDE)
    chapters_used = {o["chapter"] for o in outcomes}
    assert "Chapter 2: Conceptual Framework" in chapters_used
    assert "Chapter 7: IAS 16 Property, Plant and Equipment" in chapters_used
    assert "Chapter 16: IAS 10 Events after the Reporting Period" in chapters_used  # B7g
    assert "Chapter 22: Consolidated Statement of Financial Position" in chapters_used  # D2a
    assert "Chapter 24: Consolidated Statement of Profit or Loss" in chapters_used  # D2b
    assert "Chapter 23: Consolidation Adjustments" in chapters_used  # D2c


def test_parse_syllabus_text_preserves_levels() -> None:
    outcomes = parse_syllabus_text(SAMPLE_FR_DETAILED_GUIDE)
    levels = [o["level"] for o in outcomes]
    assert all(lev in (1, 2, 3) for lev in levels)
    assert 2 in levels


def test_build_syllabus_structure_keys_by_f7_chapters() -> None:
    outcomes = parse_syllabus_text(SAMPLE_FR_DETAILED_GUIDE)
    structure = build_syllabus_structure(outcomes)
    assert set(structure.keys()) == set(F7_CHAPTERS)
    ch2 = structure["Chapter 2: Conceptual Framework"]
    assert ch2["capability"] == "A"
    assert len(ch2["learning_outcomes"]) >= 3
    assert ch2["outcome_count"] == len(ch2["learning_outcomes"])
    b7g_chapter = "Chapter 16: IAS 10 Events after the Reporting Period"
    ch16 = structure[b7g_chapter]
    assert any(o["id"] == "B7g" for o in ch16["learning_outcomes"])


def test_build_syllabus_structure_with_custom_chapter_list() -> None:
    outcomes = parse_syllabus_text(SAMPLE_FR_DETAILED_GUIDE)
    custom = [F7_CHAPTERS[0], F7_CHAPTERS[1]]
    structure = build_syllabus_structure(outcomes, chapter_list=custom)
    assert set(structure.keys()) == set(custom)
    assert len(structure) == 2


def test_extract_capabilities_from_text() -> None:
    caps = extract_capabilities_from_text(SAMPLE_FR_DETAILED_GUIDE)
    assert "A" in caps
    assert "B" in caps
    assert "C" in caps
    assert "D" in caps
    assert "E" in caps
    assert "conceptual" in caps["A"].lower() or "regulatory" in caps["A"].lower()


def test_f7_chapters_count_and_format() -> None:
    assert len(F7_CHAPTERS) == 27
    assert F7_CHAPTERS[0].startswith("Chapter 1:")
    assert F7_CHAPTERS[26].startswith("Chapter 27:")


# Section 4 "The syllabus" sample (numbered areas under A, B, ...)
SAMPLE_FR_SECTION_4 = """
3. Approach to examining
4. The syllabus
A The conceptual and regulatory framework
1. The need for a conceptual framework
2. Recognition and measurement
B Accounting for transactions
1. Tangible non-current assets
2. Inventories
7. Provisions and events after the reporting period
D Preparation of financial statements
2. Preparation of consolidated financial statements
5. Detailed study guide
"""


def test_extract_subtopics_from_section_4() -> None:
    titles = extract_subtopics_from_section_4(SAMPLE_FR_SECTION_4)
    assert "A1" in titles
    assert "A2" in titles
    assert "B1" in titles
    assert "B2" in titles
    assert "B7" in titles
    assert "D2" in titles
    assert "need for a conceptual framework" in titles["A1"].lower()
    assert "Recognition and measurement" in titles["A2"]
    assert "Provisions and events" in titles["B7"] or "provisions" in titles["B7"].lower()
    assert "consolidated" in titles["D2"].lower()


def test_build_syllabus_structure_includes_subtopics_from_section_4() -> None:
    outcomes = parse_syllabus_text(SAMPLE_FR_DETAILED_GUIDE)
    section4_titles = extract_subtopics_from_section_4(SAMPLE_FR_SECTION_4)
    structure = build_syllabus_structure(
        outcomes, chapter_list=F7_CHAPTERS, section4_titles=section4_titles
    )
    ch2 = structure["Chapter 2: Conceptual Framework"]
    assert "subtopics" in ch2
    assert len(ch2["subtopics"]) >= 1
    assert any("conceptual framework" in s.lower() or "recognition" in s.lower() for s in ch2["subtopics"])
