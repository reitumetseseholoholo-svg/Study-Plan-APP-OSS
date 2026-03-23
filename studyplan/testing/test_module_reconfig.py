"""Tests for RAG reconfig: pre-chunked retrieval, syllabus preference, stable ids, confidence."""
from __future__ import annotations

import os

import pytest

from studyplan.module_reconfig.reconfig import (
    _chapter_slug,
    _derive_chapters_from_rag_text,
    _extract_syllabus_meta,
    _stable_outcome_id,
    analyze_outcome_count_regressions,
    compute_reconfig_confidence,
    load_reconfig_checkpoint,
    reconfig_outcome_totals_and_changed_chapters,
    reconfig_run_fingerprint,
    reconfigure_from_rag,
    retrieve_from_chunks_by_path,
    validate_syllabus_structure,
)


def test_chapter_slug() -> None:
    assert _chapter_slug("Chapter 1: The UK Tax System") == "chapter_1_the_uk_tax_system"
    assert _chapter_slug("Ch1") == "ch1"
    assert _chapter_slug("") == "ch"


def test_stable_outcome_id_new() -> None:
    oid, stable = _stable_outcome_id("Ch1", 0, "Explain the concept of X", {})
    assert oid == "ch1_1"
    assert stable is False
    oid2, stable2 = _stable_outcome_id("Investment Decisions", 2, "Apply DCF", {})
    assert oid2 == "investment_decisions_3"
    assert stable2 is False


def test_stable_outcome_id_reuse() -> None:
    existing = {"Ch1": [{"id": "lo_1", "text": "Explain the concept of X"}]}
    oid, stable = _stable_outcome_id("Ch1", 0, "Explain the concept of X", existing)
    assert oid == "lo_1"
    assert stable is True


def test_retrieve_from_chunks_by_path_prefers_matching_terms() -> None:
    chunks = {
        "/a.pdf": [{"text": "Chapter 1: Introduction. Learning outcome 1.1 explain framework."}],
        "/b.pdf": [{"text": "Unrelated content about other topics."}],
    }
    out = retrieve_from_chunks_by_path(
        chunks, ["Chapter 1: Introduction"], ["Chapter 1: Introduction"], max_chars=5000
    )
    assert "framework" in out or "Chapter" in out
    assert "Learning" in out or "outcome" in out


def test_retrieve_from_chunks_by_path_syllabus_boost() -> None:
    syllabus_path = os.path.abspath("/syllabus.pdf")
    other_path = os.path.abspath("/other.pdf")
    chunks = {
        other_path: [{"text": "Chapter 1 intro and outcome 1.1 explain."}],
        syllabus_path: [{"text": "Chapter 1 intro and outcome 1.1 explain (syllabus)."}],
    }
    out = retrieve_from_chunks_by_path(
        chunks,
        ["Chapter 1"],
        ["Chapter 1"],
        max_chars=2000,
        syllabus_paths=[syllabus_path],
    )
    assert "syllabus" in out


def test_analyze_outcome_count_regressions_severe() -> None:
    orig = {
        "syllabus_structure": {
            "A": {"learning_outcomes": [{"id": str(i), "text": f"outcome {i}"} for i in range(10)]},
        },
    }
    prop = {
        "syllabus_structure": {
            "A": {"learning_outcomes": [{"id": str(i), "text": f"outcome {i}"} for i in range(4)]},
        },
    }
    severe, warns = analyze_outcome_count_regressions(orig, prop, severe_ratio=0.3, warn_ratio=0.2)
    assert severe
    assert severe[0]["chapter"] == "A"
    assert not warns or all(x["chapter"] != "A" for x in warns)


def test_analyze_outcome_count_regressions_warn_only() -> None:
    orig = {
        "syllabus_structure": {
            "B": {"learning_outcomes": [{"id": str(i), "text": f"o{i}"} for i in range(10)]},
        },
    }
    prop = {
        "syllabus_structure": {
            "B": {"learning_outcomes": [{"id": str(i), "text": f"o{i}"} for i in range(8)]},
        },
    }
    severe, warns = analyze_outcome_count_regressions(orig, prop, severe_ratio=0.3, warn_ratio=0.2)
    assert not severe
    assert warns


def test_reconfig_outcome_totals_and_changed_chapters() -> None:
    o = {"syllabus_structure": {"A": {"learning_outcomes": [{"id": "1", "text": "a"}]}, "B": {"learning_outcomes": []}}}
    p = {"syllabus_structure": {"A": {"learning_outcomes": [{"id": "1", "text": "a"}, {"id": "2", "text": "b"}]}, "B": {"learning_outcomes": []}}}
    old_t, new_t, chg = reconfig_outcome_totals_and_changed_chapters(o, p)
    assert old_t == 1 and new_t == 2 and chg == 1


def test_reconfig_run_fingerprint_stable() -> None:
    cfg = {"chapters": ["X", "Y"]}
    fp1 = reconfig_run_fingerprint(cfg, ["/a.pdf", "/b.pdf"], fast_mode=True, target_chapters_only=True)
    fp2 = reconfig_run_fingerprint(cfg, ["/b.pdf", "/a.pdf"], fast_mode=True, target_chapters_only=True)
    assert fp1 == fp2


def test_load_reconfig_checkpoint_roundtrip(tmp_path) -> None:
    from studyplan.module_reconfig.reconfig import _write_reconfig_checkpoint_file

    p = tmp_path / "ck.json"
    payload = {"version": 1, "next_batch_start": 5, "by_chapter": {"C": [{"id": "c1", "text": "t", "level": 2}]}}
    _write_reconfig_checkpoint_file(str(p), payload)
    loaded = load_reconfig_checkpoint(str(p))
    assert loaded and loaded.get("next_batch_start") == 5


def test_compute_reconfig_confidence_alignment() -> None:
    proposed = {
        "chapters": ["A", "B"],
        "syllabus_structure": {"A": {"learning_outcomes": [{"id": "a1", "text": "x"}]}},
    }
    orig = {"chapters": ["A", "B"], "syllabus_structure": {}}
    c = compute_reconfig_confidence(proposed, orig)
    assert 0 <= c <= 1
    assert c > 0


def test_compute_reconfig_confidence_stability() -> None:
    proposed = {
        "chapters": ["A"],
        "syllabus_structure": {"A": {"learning_outcomes": [{"id": "a1", "text": "Same text"}]}},
        "syllabus_meta": {},
    }
    orig = {
        "chapters": ["A"],
        "syllabus_structure": {"A": {"learning_outcomes": [{"id": "a1", "text": "Same text"}]}},
    }
    c = compute_reconfig_confidence(proposed, orig)
    assert c >= 0.05
    # outcome_id_stability_ratio is set on proposed syllabus_meta for UI/diagnostics
    assert proposed.get("syllabus_meta", {}).get("outcome_id_stability_ratio") == 1.0


def test_validate_syllabus_structure_valid() -> None:
    config = {
        "syllabus_structure": {
            "Ch1": {"learning_outcomes": [{"id": "1", "text": "Explain X", "level": 1}]},
        },
    }
    assert validate_syllabus_structure(config) == []


def test_validate_syllabus_structure_missing_id() -> None:
    config = {
        "syllabus_structure": {
            "Ch1": {"learning_outcomes": [{"id": "", "text": "Explain X", "level": 1}]},
        },
    }
    errs = validate_syllabus_structure(config)
    assert any("id" in e.lower() for e in errs)


def test_validate_syllabus_structure_invalid_level() -> None:
    config = {
        "syllabus_structure": {
            "Ch1": {"learning_outcomes": [{"id": "1", "text": "Explain X", "level": 4}]},
        },
    }
    errs = validate_syllabus_structure(config)
    assert any("level" in e.lower() for e in errs)


def test_reconfigure_from_rag_sets_unmapped_chapters() -> None:
    """Reconfig should set syllabus_meta.unmapped_chapters for chapters with no outcomes."""
    config = {"chapters": ["Ch1", "Ch2", "Ch3"], "syllabus_structure": {}, "syllabus_meta": {}}
    chunks = {"/s.pdf": [{"text": "Ch1 only. Outcome: explain NPV."}]}

    def mock_llm(prompt: str, max_tokens: int) -> str:
        if "exam_code" in prompt:
            return '{"exam_code":"FM","effective_window":"2024"}'
        if "capabilities" in prompt:
            return '{"capabilities":{"A":"Framework"},"aliases":{},"chapter_to_capability":{"Ch1":"A","Ch2":"A","Ch3":"A"}}'
        return '{"outcomes":[{"chapter":"Ch1","text":"explain NPV","level":2}]}'

    out = reconfigure_from_rag(config, chunks, ["Ch1", "Ch2", "Ch3"], mock_llm)
    meta = out.get("syllabus_meta") or {}
    unmapped = meta.get("unmapped_chapters") or []
    assert "Ch2" in unmapped
    assert "Ch3" in unmapped
    assert "Ch1" not in unmapped


def test_extract_syllabus_meta_returns_empty_when_no_llm() -> None:
    """_extract_syllabus_meta returns only reference_pdfs when llm_generate is None."""
    existing = {}
    out = _extract_syllabus_meta(
        "ACCA FM syllabus 2024",
        ["/s.pdf"],
        {"/s.pdf": [{"text": "FM syllabus"}]},
        None,
        existing,
    )
    assert "reference_pdfs" in out
    assert out.get("reference_pdfs") == ["/s.pdf"]
    assert "exam_code" not in out or out.get("exam_code") is None


def test_derive_chapters_from_rag_text_acca_style() -> None:
    """When module config has no chapters, RAG syllabus text can supply structure via section headings.
    Source-agnostic: same logic runs on ACCA official, Study Hub, BPP, or Kaplan PDF text once in RAG."""
    text = (
        "4. The syllabus\n"
        "A Financial management function\n"
        "1. The nature and purpose of financial management\n"
        "2. Financial objectives and strategy\n"
        "B Financial management environment\n"
        "1. The economic environment\n"
        "C Working capital management\n"
        "1. Nature and elements of working capital\n"
    )
    out = _derive_chapters_from_rag_text(text, None)
    assert isinstance(out, list)
    assert len(out) >= 3
    # Main syllabus sections (section 4 style) must be present
    assert any("A." in s and "Financial management" in s for s in out)
    assert any("B." in s for s in out)
    assert any("C." in s for s in out)


def test_reconfigure_from_rag_derives_chapters_when_config_has_none() -> None:
    """RAG syllabus PDF can act as syllabus structure when module config has no chapters."""
    config = {"chapters": [], "syllabus_structure": {}, "syllabus_meta": {}}
    chunks = {
        "/syllabus.pdf": [
            {"text": "4. The syllabus\nA Financial management function\n1. Purpose.\nB Economic environment\n1. Impact."},
        ],
    }

    def mock_llm(prompt: str, max_tokens: int) -> str:
        if "exam_code" in prompt:
            return '{"exam_code":"FM","effective_window":"2024"}'
        if "capabilities" in prompt or "sections" in prompt:
            return '{"capabilities":{"A":"FM function"},"aliases":{},"chapter_to_capability":{"A. Financial management function":"A","B. Economic environment":"A"}}'
        return '{"outcomes":[{"chapter":"A. Financial management function","text":"Explain purpose","level":2}]}'

    out = reconfigure_from_rag(config, chunks, [], mock_llm)
    assert isinstance(out, dict)
    chs = out.get("chapters") or []
    assert len(chs) >= 1, "reconfig must derive chapters from RAG when config had none"
    structure = out.get("syllabus_structure") or {}
    assert isinstance(structure, dict)
