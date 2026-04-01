"""Tests for heuristic outcome linking (no LLM)."""

from __future__ import annotations

import types
from studyplan.outcome_linking import (
    _lexical_score,
    _tokens,
    link_questions_to_outcomes_heuristic,
    auto_refresh_syllabus_and_link_outcomes,
)


def test_tokens() -> None:
    assert _tokens("") == set()
    assert _tokens("Explain NPV and IRR") == {"explain", "npv", "and", "irr"}
    assert _tokens("ABC 123") == {"abc", "123"}


def test_lexical_score() -> None:
    assert _lexical_score("", "anything") == 0.0
    assert _lexical_score("Explain NPV", "NPV and discounted cash flows") >= 0.1
    assert _lexical_score("NPV", "NPV") >= 0.9
    assert _lexical_score("foo bar", "unrelated text") < 0.5


def test_link_questions_to_outcomes_heuristic_empty_engine() -> None:
    """No chapters -> returns summary with errors."""
    engine = types.SimpleNamespace(CHAPTERS=[], QUESTIONS={}, QUESTIONS_DEFAULT={}, save_questions=lambda: None)
    out = link_questions_to_outcomes_heuristic(engine)
    assert "questions_linked" in out
    assert out.get("questions_linked") == 0
    assert "no chapters" in (out.get("errors") or [])


def test_link_questions_to_outcomes_heuristic_no_outcomes() -> None:
    """Chapters but no syllabus outcomes -> no linking."""
    def get_intel(ch):
        return {}
    engine = types.SimpleNamespace(
        CHAPTERS=["Ch1"],
        QUESTIONS={"Ch1": [{"question": "What is NPV?", "outcome_ids": []}]},
        QUESTIONS_DEFAULT={"Ch1": []},
        get_syllabus_chapter_intelligence=get_intel,
        save_questions=lambda: None,
    )
    out = link_questions_to_outcomes_heuristic(engine)
    assert out.get("questions_linked") == 0


def test_link_questions_to_outcomes_heuristic_links_added_question() -> None:
    """Added question (not in default) gets outcome_ids when outcome text matches."""
    def get_intel(ch):
        if ch == "Ch1":
            return {
                "learning_outcomes": [
                    {"id": "o1", "text": "Explain NPV and discounted cash flow", "level": 2},
                    {"id": "o2", "text": "Apply IRR", "level": 2},
                ]
            }
        return {}

    questions_ch1 = [{"question": "Explain NPV and discounted cash flow methods.", "outcome_ids": []}]
    engine = types.SimpleNamespace(
        CHAPTERS=["Ch1"],
        QUESTIONS={"Ch1": questions_ch1},
        QUESTIONS_DEFAULT={"Ch1": []},
        get_syllabus_chapter_intelligence=get_intel,
        save_questions=lambda: None,
    )
    out = link_questions_to_outcomes_heuristic(engine, min_score=0.05)
    assert out.get("questions_linked") >= 1
    assert questions_ch1[0].get("outcome_ids") is not None
    assert "o1" in (questions_ch1[0].get("outcome_ids") or [])
    # stable outcome ids + confidence: heuristic linker stores link confidence (0..1)
    assert "outcome_link_confidence" in questions_ch1[0]
    assert 0 <= questions_ch1[0]["outcome_link_confidence"] <= 1


def test_auto_refresh_syllabus_and_link_outcomes() -> None:
    """Pipeline runs concept graph build (may no-op) and linker."""
    def build_graph(force=False):
        pass
    engine = types.SimpleNamespace(
        CHAPTERS=["Ch1"],
        QUESTIONS={"Ch1": []},
        QUESTIONS_DEFAULT={"Ch1": []},
        get_syllabus_chapter_intelligence=lambda ch: {},
        save_questions=lambda: None,
        build_canonical_concept_graph=build_graph,
    )
    result = auto_refresh_syllabus_and_link_outcomes(engine, rebuild_concept_graph=True)
    assert "concept_graph_built" in result
    assert "linking" in result
    assert result.get("concept_graph_built") is True
