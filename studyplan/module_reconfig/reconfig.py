"""
RAG-amplified module reconfiguration: learning outcomes, sections, aliases, weights.

Consumes pre-chunked RAG content (syllabus + study guide PDFs) and an optional
LLM to produce a proposed module config with accurate syllabus_structure,
capabilities, aliases, and importance_weights. Lightweight: reuses cached
chunks, batched retrieval, schema-bound extraction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

# Chunks: list of dicts with at least "text"; optional "id", "source".
# chunks_by_path: path -> list of such dicts.
ChunksByPath = dict[str, list[dict[str, Any]]]
LLMGenerate = Callable[[str, int], str]

# Minimum confidence (0..1) to auto-apply reconfig without user review.
DEFAULT_AUTO_APPLY_CONFIDENCE_THRESHOLD = 0.75
# Auto-save a disk draft when confidence is in [low, threshold) (manual review still possible).
DEFAULT_PENDING_RECONFIG_CONFIDENCE_LOW = 0.45

# Chapter-level outcome count drop vs previous config (only chapters with old count > 0).
DEFAULT_OUTCOME_DROP_SEVERE_RATIO = 0.30
DEFAULT_OUTCOME_DROP_WARN_RATIO = 0.20

RECONFIG_CHECKPOINT_VERSION = 1


def validate_capabilities_and_aliases(config: dict[str, Any]) -> list[str]:
    """
    Validate capabilities (letter -> string) and aliases (alias -> canonical string) for reconfig quality.
    Returns a list of error messages; empty if valid.
    """
    errors: list[str] = []
    caps = config.get("capabilities")
    if isinstance(caps, dict) and caps:
        for k, v in caps.items():
            key = str(k).strip().upper()
            if not key or len(key) != 1 or not key.isalpha():
                errors.append(f"capabilities: key '{k}' must be a single letter (A-Z)")
            if not isinstance(v, str) or not str(v).strip():
                errors.append(f"capabilities: value for '{k}' must be a non-empty string")
    aliases = config.get("aliases")
    if isinstance(aliases, dict) and aliases:
        for k, v in aliases.items():
            if not isinstance(k, str) or not str(k).strip():
                errors.append("aliases: key must be a non-empty string")
            if v is not None and not isinstance(v, str):
                errors.append(f"aliases: value for '{k}' must be a string (canonical chapter)")
            elif isinstance(v, str) and not v.strip():
                errors.append(f"aliases: value for '{k}' must be non-empty")
    return errors


def validate_syllabus_structure(config: dict[str, Any]) -> list[str]:
    """
    Validate syllabus_structure against the strict schema (learning_outcomes with id, text, level).
    Returns a list of error messages; empty if valid.
    """
    errors: list[str] = []
    structure = config.get("syllabus_structure")
    if not isinstance(structure, dict):
        return errors
    for chapter, info in structure.items():
        if not isinstance(info, dict):
            continue
        outcomes = info.get("learning_outcomes")
        if not isinstance(outcomes, list):
            continue
        for i, item in enumerate(outcomes):
            if not isinstance(item, dict):
                errors.append(f"syllabus_structure.{chapter}.learning_outcomes[{i}] must be an object")
                continue
            id_val = item.get("id")
            text_val = item.get("text")
            level_val = item.get("level")
            if not isinstance(id_val, str) or not str(id_val).strip():
                errors.append(f"syllabus_structure.{chapter}.learning_outcomes[{i}].id must be a non-empty string")
            if not isinstance(text_val, str) or not str(text_val).strip():
                errors.append(f"syllabus_structure.{chapter}.learning_outcomes[{i}].text must be a non-empty string")
            if level_val is not None:
                try:
                    lev = int(level_val)
                    if lev < 1 or lev > 3:
                        errors.append(f"syllabus_structure.{chapter}.learning_outcomes[{i}].level must be 1, 2, or 3")
                except (TypeError, ValueError):
                    errors.append(f"syllabus_structure.{chapter}.learning_outcomes[{i}].level must be an integer 1-3")
    return errors


def validate_module_config(config: dict[str, Any]) -> list[str]:
    """
    Validate module config for reconfig output quality: syllabus_structure, capabilities, aliases.
    Returns a list of error messages; empty if valid.
    """
    errors = validate_syllabus_structure(config) + validate_capabilities_and_aliases(config)
    return errors


def chapter_outcome_counts(config: dict[str, Any]) -> dict[str, int]:
    """Per-chapter count of learning_outcomes in syllabus_structure."""
    structure = config.get("syllabus_structure") or {}
    if not isinstance(structure, dict):
        return {}
    out: dict[str, int] = {}
    for ch, info in structure.items():
        key = str(ch).strip()
        if not key:
            continue
        if not isinstance(info, dict):
            out[key] = 0
            continue
        los = info.get("learning_outcomes")
        out[key] = len(los) if isinstance(los, list) else 0
    return out


def analyze_outcome_count_regressions(
    original_config: dict[str, Any],
    proposed_config: dict[str, Any],
    *,
    severe_ratio: float | None = None,
    warn_ratio: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Compare per-chapter outcome counts before/after a proposed reconfig.
    Returns (severe, warnings) where each entry is
    {"chapter", "old", "new", "drop_ratio"} for chapters whose count dropped.
    Severe: drop_ratio >= severe_ratio (default 30%). Warn: >= warn_ratio (default 20%) but not severe.
    """
    def _ratio_from_env(key: str, default: float) -> float:
        raw = os.environ.get(key, "").strip()
        if not raw:
            return default
        try:
            return max(0.01, min(0.95, float(raw)))
        except ValueError:
            return default

    sr = (
        float(severe_ratio)
        if severe_ratio is not None
        else _ratio_from_env("STUDYPLAN_RECONFIG_OUTCOME_DROP_SEVERE", DEFAULT_OUTCOME_DROP_SEVERE_RATIO)
    )
    wr = (
        float(warn_ratio)
        if warn_ratio is not None
        else _ratio_from_env("STUDYPLAN_RECONFIG_OUTCOME_DROP_WARN", DEFAULT_OUTCOME_DROP_WARN_RATIO)
    )
    sr = max(0.01, min(0.95, float(sr)))
    wr = max(0.01, min(0.95, float(wr)))
    if wr > sr:
        wr = sr
    old_c = chapter_outcome_counts(original_config)
    new_c = chapter_outcome_counts(proposed_config)
    severe: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for ch in sorted(set(old_c) | set(new_c)):
        o = int(old_c.get(ch, 0))
        n = int(new_c.get(ch, 0))
        if o <= 0 or n >= o:
            continue
        drop = (o - n) / float(o)
        entry: dict[str, Any] = {
            "chapter": ch,
            "old": o,
            "new": n,
            "drop_ratio": round(drop, 4),
        }
        if drop >= sr:
            severe.append(entry)
        elif drop >= wr:
            warnings.append(entry)
    return severe, warnings


def reconfig_run_fingerprint(
    config: dict[str, Any],
    chunk_paths: list[str],
    *,
    fast_mode: bool,
    target_chapters_only: bool,
) -> str:
    """Stable id for a reconfig run (chapters list + RAG paths + mode flags)."""
    ch = json.dumps(config.get("chapters") or [], ensure_ascii=True, sort_keys=True)
    paths = sorted(
        os.path.normpath(os.path.abspath(os.path.expanduser(str(p)))).replace("\\", "/")
        for p in chunk_paths
        if str(p).strip()
    )
    raw = f"v{RECONFIG_CHECKPOINT_VERSION}|{ch}|{json.dumps(paths, ensure_ascii=True)}|{fast_mode}|{target_chapters_only}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def load_reconfig_checkpoint(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _write_reconfig_checkpoint_file(path: str, payload: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
    os.replace(tmp, path)


def reconfig_outcome_totals_and_changed_chapters(
    original_config: dict[str, Any],
    proposed_config: dict[str, Any],
) -> tuple[int, int, int]:
    """Return (old_total_outcomes, new_total_outcomes, chapters_with_changed_count)."""
    old_c = chapter_outcome_counts(original_config)
    new_c = chapter_outcome_counts(proposed_config)
    old_total = sum(old_c.values())
    new_total = sum(new_c.values())
    keys = set(old_c) | set(new_c)
    changed = sum(1 for k in keys if old_c.get(k, 0) != new_c.get(k, 0))
    return old_total, new_total, changed


def compute_reconfig_confidence(
    proposed: dict[str, Any],
    original_config: dict[str, Any],
    validation_errors: list[str] | None = None,
) -> float:
    """
    Compute a 0..1 confidence score for a proposed reconfig to support auto-apply decisions.
    Higher when: validation passes, outcome count is substantial, chapter coverage is good,
    outcome ids are stable vs original, chapters align with config, and capabilities/aliases
    were extracted.
    """
    if validation_errors:
        return 0.0
    score = 0.0
    structure = proposed.get("syllabus_structure") or {}
    chapters = proposed.get("chapters") or original_config.get("chapters") or []
    if not isinstance(chapters, list):
        chapters = []
    chapter_list = [str(c).strip() for c in chapters if str(c).strip()]
    n_chapters = len(chapter_list)
    chapter_set = set(chapter_list)
    total_outcomes = 0
    chapters_with_outcomes = 0
    for ch, info in (structure or {}).items():
        if not isinstance(info, dict):
            continue
        los = info.get("learning_outcomes")
        if isinstance(los, list):
            total_outcomes += len(los)
            if los:
                chapters_with_outcomes += 1
    if n_chapters <= 0:
        return 0.0
    coverage = chapters_with_outcomes / n_chapters if n_chapters else 0.0
    score += 0.30 * min(1.0, coverage)  # chapter coverage
    score += 0.25 * min(1.0, total_outcomes / max(1, n_chapters * 3))  # outcomes per chapter
    if total_outcomes >= n_chapters:
        score += 0.10
    # Chapter alignment: structure keys should be in config chapters
    structure_chapters = [c for c in structure.keys() if str(c).strip()]
    aligned = sum(1 for c in structure_chapters if c in chapter_set)
    alignment_ratio = aligned / len(structure_chapters) if structure_chapters else 1.0
    score += 0.10 * min(1.0, alignment_ratio)
    # Outcome id stability: how many proposed outcomes reuse original id (by matching text)
    orig_structure = original_config.get("syllabus_structure") or {}
    stable_count = 0
    for ch, info in (structure or {}).items():
        if not isinstance(info, dict):
            continue
        los = info.get("learning_outcomes")
        if not isinstance(los, list):
            continue
        orig_los = (orig_structure.get(ch) or {}).get("learning_outcomes") or []
        if not isinstance(orig_los, list):
            continue
        orig_by_text = {}
        for o in orig_los:
            if isinstance(o, dict):
                t = re.sub(r"\s+", " ", (o.get("text") or "").lower().strip())
                if t and o.get("id"):
                    orig_by_text[t] = str(o.get("id", "")).strip()
        for o in los:
            if isinstance(o, dict):
                t = re.sub(r"\s+", " ", (o.get("text") or "").lower().strip())
                if t and orig_by_text.get(t) == str(o.get("id") or "").strip():
                    stable_count += 1
    stability_ratio = (stable_count / total_outcomes) if total_outcomes > 0 else 0.0
    if total_outcomes > 0:
        score += 0.10 * min(1.0, stability_ratio)  # stable outcome ids boost confidence
    # Expose outcome_id_stability_ratio for UI/diagnostics
    meta = proposed.get("syllabus_meta")
    if isinstance(meta, dict):
        meta["outcome_id_stability_ratio"] = round(stability_ratio, 4)
    caps = proposed.get("capabilities")
    if isinstance(caps, dict) and caps:
        score += 0.10
    aliases = proposed.get("aliases")
    if isinstance(aliases, dict) and aliases:
        score += 0.10
    return round(min(1.0, max(0.0, score)), 2)


def should_auto_reconfigure(
    config: dict[str, Any],
    rag_paths: list[str],
    *,
    get_path_mtime: Callable[[str], float] | None = None,
) -> tuple[bool, str]:
    """
    Decide if automatic reconfiguration should run for this module.
    Returns (True, reason) when reconfig is recommended, (False, reason) otherwise.
    Triggers when: RAG paths exist and (no prior reconfig, or zero outcomes, or a RAG file is newer than reconfigured_at).
    """
    if not rag_paths:
        return False, "no RAG PDFs"
    chapters = config.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return False, "no chapters"
    meta = config.get("syllabus_meta") or {}
    reconfigured_at = (meta.get("reconfigured_at") or "").strip()
    structure = config.get("syllabus_structure") or {}
    total_outcomes = sum(
        len(info.get("learning_outcomes") or [])
        for info in structure.values()
        if isinstance(info, dict) and isinstance(info.get("learning_outcomes"), list)
    )
    if not reconfigured_at and total_outcomes == 0:
        return True, "no prior reconfig and no outcomes"
    if total_outcomes == 0:
        return True, "no outcomes"
    if not reconfigured_at:
        return True, "no prior reconfig"
    get_mtime = get_path_mtime or (lambda p: os.path.getmtime(p) if os.path.isfile(p) else 0.0)
    reconfig_ts = 0.0
    try:
        s = reconfigured_at.replace("Z", "+00:00").strip()[:30]
        dt = datetime.fromisoformat(s)
        reconfig_ts = dt.timestamp()
    except Exception:
        pass
    for path in rag_paths:
        try:
            mtime = get_mtime(path)
            if mtime > reconfig_ts:
                return True, "RAG file newer than last reconfig"
        except Exception:
            continue
    return False, "RAG not newer than last reconfig"


def _all_chunk_texts(chunks_by_path: ChunksByPath, max_chars: int = 32000) -> str:
    """Concatenate chunk texts from all paths, up to max_chars."""
    parts: list[str] = []
    total = 0
    for path, chunks in chunks_by_path.items():
        if total >= max_chars:
            break
        for c in chunks:
            if not isinstance(c, dict):
                continue
            text = str(c.get("text", "") or "").strip()
            if not text:
                continue
            if total + len(text) + 1 > max_chars:
                parts.append(text[: max_chars - total - 20].rstrip() + "\n[...]")
                total = max_chars
                break
            parts.append(text)
            total += len(text) + 1
    return "\n\n".join(parts)


def _retrieve_for_chapters(
    full_text: str,
    chapters: list[str],
    batch: list[str],
    *,
    chunk_chars: int = 900,
) -> str:
    """
    Simple retrieval: split full_text into chunks, score by overlap with chapter/batch terms,
    return top chunks concatenated. Prefer retrieve_from_chunks_by_path when you already
    have chunks_by_path to avoid re-splitting.
    """
    if not full_text or not batch:
        return full_text.strip()[:8000] if full_text else ""
    lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
    if not lines:
        return full_text.strip()[:8000]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > chunk_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    terms: set[str] = set()
    for ch in batch:
        for token in re.findall(r"[a-z0-9]{2,}", (ch or "").lower()):
            terms.add(token)
    scored: list[tuple[float, int]] = []
    for idx, c in enumerate(chunks):
        low = c.lower()
        score = sum(1.0 for t in terms if t in low)
        if score > 0:
            if re.search(r"^[a-z][\)\.]\s+|\d+\.\s+", c):
                score += 0.5
            scored.append((score, idx))
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:8]
    if not top:
        return full_text.strip()[:8000]
    return "\n\n".join(chunks[i] for _, i in top)


def _chapter_slug(chapter: str) -> str:
    """Safe slug for chapter (used in stable outcome ids)."""
    s = re.sub(r"[^a-z0-9\s\-]", "", (chapter or "").lower().strip())
    return re.sub(r"\s+", "_", s).strip("_") or "ch"


def _stable_outcome_id(
    chapter: str, index: int, text: str, existing_by_chapter: dict[str, list[dict[str, Any]]]
) -> tuple[str, bool]:
    """
    Prefer reusing an existing outcome id when the normalized text matches; otherwise
    use chapter_slug + '_' + index (1-based) for stability across runs.
    Returns (outcome_id, id_stable) where id_stable is True when the id was reused from existing.
    """
    norm = re.sub(r"\s+", " ", (text or "").lower().strip())
    existing = existing_by_chapter.get(chapter) or []
    for o in existing:
        if not isinstance(o, dict):
            continue
        ot = (o.get("text") or "").strip()
        if re.sub(r"\s+", " ", ot.lower()) == norm:
            oid = o.get("id")
            if isinstance(oid, str) and oid.strip():
                return oid.strip(), True
    return f"{_chapter_slug(chapter)}_{index + 1}", False


def retrieve_from_chunks_by_path(
    chunks_by_path: ChunksByPath,
    chapters: list[str],
    batch: list[str],
    *,
    max_chars: int = 8000,
    syllabus_paths: list[str] | None = None,
) -> str:
    """
    Score pre-chunked docs by term overlap with batch chapter names; prefer chunks from
    syllabus_paths when provided. Returns concatenated top chunks up to max_chars.
    """
    if not batch:
        return ""
    terms: set[str] = set()
    for ch in batch:
        for token in re.findall(r"[a-z0-9]{2,}", (ch or "").lower()):
            terms.add(token)
    syllabus_set = {os.path.normpath(os.path.abspath(p)) for p in (syllabus_paths or []) if p}

    # (score, path, chunk_index, text) with syllabus boost
    scored: list[tuple[float, str, int, str]] = []
    for path, chunks in chunks_by_path.items():
        if not chunks:
            continue
        path_norm = os.path.normpath(os.path.abspath(path))
        boost = 2.0 if path_norm in syllabus_set else 1.0
        for idx, c in enumerate(chunks):
            if not isinstance(c, dict):
                continue
            text = str(c.get("text", "") or "").strip()
            if not text:
                continue
            low = text.lower()
            score = sum(1.0 for t in terms if t in low) * boost
            if re.search(r"^[a-z][\)\.]\s+|\d+\.\s+", text):
                score += 0.5 * boost
            if score > 0:
                scored.append((score, path, idx, text))
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))

    parts: list[str] = []
    total = 0
    for _, _path, _idx, text in scored:
        if total >= max_chars:
            break
        if total + len(text) + 2 > max_chars:
            parts.append(text[: max_chars - total - 20].rstrip() + "\n[...]")
            break
        parts.append(text)
        total += len(text) + 2
    return "\n\n".join(parts) if parts else ""


def _capability_from_chapter(chapter: str) -> str:
    """Heuristic capability letter from chapter title (matches engine-style)."""
    t = (chapter or "").lower()
    if "framework" in t or "concept" in t or "international" in t:
        return "A"
    if any(
        x in t
        for x in [
            "ias ", "ifrs ", "impairment", "lease", "tax", "revenue", "instrument",
            "ppe", "intangible", "inventor", "provision", "foreign", "government", "eps",
        ]
    ):
        return "B"
    if "analysis" in t or "interpretation" in t:
        return "C"
    if "consolidat" in t or "cash flow" in t or "presentation" in t:
        return "D"
    return "A"


def _build_importance_weights(syllabus_structure: dict[str, Any]) -> dict[str, float]:
    """Derive importance weights from outcome count and level mix (lightweight, no LLM)."""
    weights: dict[str, float] = {}
    for chapter, info in syllabus_structure.items():
        if not isinstance(info, dict):
            continue
        outcome_count = int(info.get("outcome_count", 0) or 0)
        outcomes = info.get("learning_outcomes")
        if isinstance(outcomes, list):
            outcome_count = max(outcome_count, len(outcomes))
        level_3 = 0
        if isinstance(outcomes, list):
            for o in outcomes:
                if isinstance(o, dict) and int(o.get("level", 2) or 2) == 3:
                    level_3 += 1
        base = 1.0 + min(0.5, outcome_count / 80.0)
        if outcome_count > 0 and level_3 > 0:
            base += min(0.3, level_3 / 20.0)
        weights[chapter] = round(base, 2)
    return weights


def compute_target_chapters_for_reconfig(
    config: dict[str, Any],
    *,
    min_outcome_count: int = 0,
    below_median_only: bool = True,
) -> list[str]:
    """
    Chapters that need outcome extraction: zero outcomes or below median.
    Used for incremental reconfig so we only run LLM for under-specified chapters.
    """
    chapters = config.get("chapters")
    if not isinstance(chapters, list):
        return []
    chapters_clean = [str(c).strip() for c in chapters if str(c).strip()]
    structure = config.get("syllabus_structure") or {}
    if not isinstance(structure, dict):
        structure = {}
    counts: list[tuple[str, int]] = []
    for ch in chapters_clean:
        info = structure.get(ch) if isinstance(structure, dict) else {}
        outcomes = info.get("learning_outcomes") if isinstance(info, dict) else None
        n = len(outcomes) if isinstance(outcomes, list) else 0
        counts.append((ch, n))
    target: list[str] = [ch for ch, n in counts if n <= min_outcome_count]
    if below_median_only and counts:
        outcomes_per_ch = [n for _, n in counts]
        outcomes_per_ch.sort()
        mid = len(outcomes_per_ch) // 2
        median = outcomes_per_ch[mid] if outcomes_per_ch else 0
        target = [ch for ch, n in counts if n <= min_outcome_count or n < median]
    return target


def reconfigure_from_rag(
    config: dict[str, Any],
    chunks_by_path: ChunksByPath,
    chapters: list[str],
    llm_generate: LLMGenerate | None,
    *,
    max_tokens: int = 4096,
    max_input_chars: int = 12000,
    batch_size: int = 5,
    syllabus_paths: list[str] | None = None,
    fast_mode: bool = False,
    target_chapters_only: bool = True,
    resume_checkpoint: dict[str, Any] | None = None,
    checkpoint_path: str | None = None,
) -> dict[str, Any]:
    """
    Propose an updated module config from RAG chunks (syllabus + study guide).

    - config: current module config (chapters, syllabus_structure, capabilities, aliases, etc.).
    - chunks_by_path: path -> list of chunk dicts (each with "text", optional "id"/"source").
    - chapters: ordered chapter list (must match config or be the source of truth).
    - llm_generate: (prompt, max_tokens) -> raw string. If None, only structure derived from
      existing config + importance_weights is returned (no new outcomes).
    - syllabus_paths: optional list of PDF paths to prefer when retrieving (e.g. from
      syllabus_meta.source_pdf and reference_pdfs). Chunks from these paths get higher score.
    - fast_mode: if True, only run outcome extraction (skip syllabus_meta, capabilities/aliases,
      subtopics extraction) for fewer LLM calls and faster runs.
    - target_chapters_only: if True, only run outcome extraction for chapters with zero or
      below-median outcome count; other chapters keep existing structure (incremental).
    - resume_checkpoint: optional dict from load_reconfig_checkpoint (fast_mode runs only).
    - checkpoint_path: if set with fast_mode, writes progress after each batch for resume; removed
      when the run completes.

    Returns a full proposed config (copy of config with syllabus_structure, importance_weights,
    syllabus_meta.reconfigured_at / reconfigured_from_rag_paths updated). Learning outcomes
    are merged from LLM extraction when llm_generate is provided; otherwise existing
    syllabus_structure is kept and only importance_weights and meta are refreshed.
    """
    proposed = copy.deepcopy(config)
    proposed.setdefault("chapters", chapters)
    proposed.setdefault("syllabus_structure", {})
    proposed.setdefault("syllabus_meta", {})
    if not isinstance(proposed["syllabus_meta"], dict):
        proposed["syllabus_meta"] = {}
    meta = proposed["syllabus_meta"]
    meta["reconfigured_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["reconfigured_from_rag_paths"] = list(chunks_by_path.keys())

    full_text = _all_chunk_texts(chunks_by_path, max_chars=max_input_chars * 2)
    if not full_text:
        _apply_importance_only(proposed)
        return proposed

    # Focus 1: fix/complete syllabus_meta (exam_code, effective_window, reference_pdfs) — skipped in fast_mode
    ref_pdfs = list(syllabus_paths) if syllabus_paths else list(chunks_by_path.keys())
    if ref_pdfs:
        meta["reference_pdfs"] = [str(p).strip() for p in ref_pdfs if str(p).strip()]
    if llm_generate and not fast_mode:
        syllabus_meta_extracted = _extract_syllabus_meta(
            full_text, syllabus_paths, chunks_by_path, llm_generate, meta,
            max_context=5000, max_tokens=1024,
        )
        for k, v in syllabus_meta_extracted.items():
            if v is not None and (k not in meta or meta.get(k) in (None, "")):
                meta[k] = v

    structure = proposed.get("syllabus_structure")
    if not isinstance(structure, dict):
        structure = {}
        proposed["syllabus_structure"] = structure

    if llm_generate is None:
        _apply_importance_only(proposed)
        return proposed

    # Batched outcome extraction (same schema as parse_syllabus_with_ai)
    try:
        from studyplan.ai.prompt_design import (
            JSON_ONLY_NO_MARKDOWN,
            build_syllabus_extraction_prompt,
        )
    except ImportError:
        _apply_importance_only(proposed)
        return proposed

    chapters_clean = [str(c).strip() for c in chapters if str(c).strip()]
    if not chapters_clean:
        derived = _derive_chapters_from_rag_text(
            full_text, llm_generate, max_tokens=min(1024, max_tokens), max_context=8000
        )
        if derived:
            chapters_clean = derived
            proposed["chapters"] = list(chapters_clean)
        else:
            _apply_importance_only(proposed)
            return proposed

    existing_structure = (config.get("syllabus_structure") or {}) if isinstance(config.get("syllabus_structure"), dict) else {}
    existing_by_chapter: dict[str, list[dict[str, Any]]] = {}
    for ch, info in existing_structure.items():
        if isinstance(info, dict) and isinstance(info.get("learning_outcomes"), list):
            existing_by_chapter[ch] = list(info.get("learning_outcomes") or [])

    # Incremental: only run outcome extraction for target chapters (zero or below-median outcomes)
    if target_chapters_only:
        target_set = set(compute_target_chapters_for_reconfig(config, min_outcome_count=0, below_median_only=True))
        if not target_set:
            target_set = set(chapters_clean)
    else:
        target_set = set(chapters_clean)

    # Focus 2: unmapped chapters — process them first so extraction fills them (within target only)
    unmapped_before = [ch for ch in chapters_clean if ch in target_set and not (existing_by_chapter.get(ch))]
    rest_target = [ch for ch in chapters_clean if ch in target_set and ch not in set(unmapped_before)]
    ordered_chapters = list(unmapped_before) + rest_target

    # Focus 3 & 4: full capability list and chapter→capability mapping — skipped in fast_mode
    cap_map: dict[str, Any] = {}
    alias_map: dict[str, Any] = {}
    chapter_to_capability: dict[str, str] = {}
    if not fast_mode and llm_generate:
        raw_cap, raw_alias, raw_ch_to_cap = _extract_capabilities_and_aliases(
            full_text, chapters_clean, llm_generate, max_tokens=min(2048, max_tokens), max_context=6000
        )
        if raw_cap is not None:
            cap_map = raw_cap
        if raw_alias is not None:
            alias_map = raw_alias
        if raw_ch_to_cap is not None:
            chapter_to_capability = raw_ch_to_cap
        if isinstance(cap_map, dict) and cap_map:
            proposed["capabilities"] = {str(k).strip().upper(): str(v).strip() for k, v in cap_map.items() if str(k).strip() and str(v).strip()}
        if isinstance(alias_map, dict) and alias_map:
            existing_aliases = proposed.get("aliases")
            if not isinstance(existing_aliases, dict):
                existing_aliases = {}
            for ch_title, aliases in alias_map.items():
                if not isinstance(aliases, list):
                    continue
                key = str(ch_title).strip()
                if not key:
                    continue
                for a in aliases:
                    a_str = str(a).strip()
                    if a_str and a_str != key:
                        existing_aliases[a_str] = key
            proposed["aliases"] = existing_aliases

    write_checkpoint = bool(checkpoint_path) and fast_mode
    chunk_path_list = sorted(chunks_by_path.keys())
    fp_now = reconfig_run_fingerprint(
        config, list(chunk_path_list), fast_mode=fast_mode, target_chapters_only=target_chapters_only
    )
    if checkpoint_path and not resume_checkpoint:
        stale = load_reconfig_checkpoint(checkpoint_path)
        if stale and stale.get("fingerprint") and stale.get("fingerprint") != fp_now:
            try:
                os.remove(checkpoint_path)
            except OSError:
                pass

    resume = resume_checkpoint
    if resume and (
        resume.get("version") != RECONFIG_CHECKPOINT_VERSION
        or resume.get("fingerprint") != fp_now
        or resume.get("fast_mode") is not True
        or fast_mode is not True
    ):
        resume = None

    start_batch_offset = 0
    by_chapter: dict[str, list[dict[str, Any]]] = {ch: [] for ch in chapters_clean}
    seen_dedup: dict[str, set[str]] = {ch: set() for ch in chapters_clean}
    chapter_set = set(chapters_clean)

    if resume:
        if (
            resume.get("chapters_clean") != chapters_clean
            or resume.get("ordered_chapters") != ordered_chapters
            or int(resume.get("batch_size", batch_size) or batch_size) != batch_size
        ):
            resume = None
        else:
            start_batch_offset = max(0, int(resume.get("next_batch_start", 0)))
            bc_raw = resume.get("by_chapter") or {}
            if isinstance(bc_raw, dict):
                for ch in chapters_clean:
                    items = bc_raw.get(ch)
                    if isinstance(items, list):
                        restored: list[dict[str, Any]] = []
                        for it in items:
                            if not isinstance(it, dict):
                                continue
                            entry: dict[str, Any] = {
                                "id": str(it.get("id", "") or "").strip(),
                                "text": str(it.get("text", "") or "").strip(),
                                "level": max(1, min(3, int(it.get("level", 2) or 2))),
                            }
                            if "id_stable" in it:
                                entry["id_stable"] = bool(it.get("id_stable"))
                            restored.append(entry)
                        by_chapter[ch] = restored
            sd_raw = resume.get("seen_dedup") or {}
            if isinstance(sd_raw, dict):
                for ch in chapters_clean:
                    keys = sd_raw.get(ch)
                    if isinstance(keys, list):
                        seen_dedup[ch] = {str(x) for x in keys if str(x).strip()}

    for start in range(start_batch_offset, len(ordered_chapters), batch_size):
        batch = ordered_chapters[start : start + batch_size]
        context = retrieve_from_chunks_by_path(
            chunks_by_path,
            chapters_clean,
            batch,
            max_chars=max_input_chars,
            syllabus_paths=syllabus_paths,
        )
        if not context.strip():
            context = _all_chunk_texts(chunks_by_path, max_chars=max_input_chars)
        if not context.strip():
            context = full_text.strip()[:max_input_chars]
        chapters_blob = "\n".join(f"- {ch}" for ch in batch)
        prompt = build_syllabus_extraction_prompt(
            syllabus_text=context,
            chapters_blob=chapters_blob,
            rules=[
                "Use only the retrieved excerpts as evidence.",
                "Map every outcome to exactly one chapter from the provided batch.",
                "Copy outcome text verbatim from the syllabus; do not paraphrase or shorten.",
            ],
        )
        prompt = prompt + "\n\n" + JSON_ONLY_NO_MARKDOWN
        try:
            raw = llm_generate(prompt, max_tokens)
        except Exception:
            continue
        raw = (raw or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```\w*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw)
        try:
            data = json.loads(raw)
        except Exception:
            continue
        outcomes_list = data.get("outcomes") if isinstance(data, dict) else None
        if not isinstance(outcomes_list, list):
            continue
        for item in outcomes_list:
            if not isinstance(item, dict):
                continue
            ch = str(item.get("chapter", "") or "").strip()
            if ch not in chapter_set:
                continue
            try:
                level = int(item.get("level", 2) or 2)
            except (TypeError, ValueError):
                level = 2
            level = max(1, min(3, level))
            txt = str(item.get("text", "") or "").strip()
            if not txt:
                continue
            dedupe_key = re.sub(r"\s+", " ", txt.lower()).strip()
            if dedupe_key in seen_dedup.get(ch, set()):
                continue
            seen_dedup.setdefault(ch, set()).add(dedupe_key)
            oid, id_stable = _stable_outcome_id(ch, len(by_chapter[ch]), txt, existing_by_chapter)
            by_chapter[ch].append({"id": oid, "text": txt, "level": level, "id_stable": id_stable})

        next_idx = start + batch_size
        if write_checkpoint and checkpoint_path and next_idx < len(ordered_chapters):
            serial_by: dict[str, list[dict[str, Any]]] = {}
            for ch, items in by_chapter.items():
                serial_by[ch] = []
                for o in items:
                    row: dict[str, Any] = {
                        "id": o.get("id"),
                        "text": o.get("text"),
                        "level": o.get("level"),
                    }
                    if "id_stable" in o:
                        row["id_stable"] = o.get("id_stable")
                    serial_by[ch].append(row)
            serial_sd = {ch: sorted(seen_dedup.get(ch, set())) for ch in chapters_clean}
            try:
                _write_reconfig_checkpoint_file(
                    checkpoint_path,
                    {
                        "version": RECONFIG_CHECKPOINT_VERSION,
                        "fingerprint": fp_now,
                        "fast_mode": True,
                        "target_chapters_only": target_chapters_only,
                        "batch_size": batch_size,
                        "chapters_clean": list(chapters_clean),
                        "ordered_chapters": list(ordered_chapters),
                        "target_set": sorted(target_set),
                        "syllabus_paths": list(syllabus_paths or []),
                        "next_batch_start": next_idx,
                        "by_chapter": serial_by,
                        "seen_dedup": serial_sd,
                    },
                )
            except OSError:
                pass

    if write_checkpoint and checkpoint_path:
        try:
            if os.path.isfile(checkpoint_path):
                os.remove(checkpoint_path)
        except OSError:
            pass

    # Merge into structure: use chapter→capability mapping; set learning_outcomes and subtopics (Phase 4).
    def _cap_for_chapter(ch: str) -> str:
        if isinstance(chapter_to_capability, dict):
            c = chapter_to_capability.get(ch)
            if c:
                return c
        return (structure.get(ch) or {}).get("capability") or _capability_from_chapter(ch)

    # RAG subtopics: extract section/subtopic titles per chapter — skipped in fast_mode
    subtopics_by_chapter: dict[str, list[str]] = {}
    if not fast_mode and llm_generate:
        subtopics_by_chapter = _extract_subtopics_by_chapter(
            full_text, chapters_clean, llm_generate, max_context=5000, max_tokens=1024
        ) or {}

    for ch in chapters_clean:
        if target_chapters_only and ch not in target_set:
            continue
        los = by_chapter.get(ch)
        existing_sub = (structure.get(ch) or {}).get("subtopics") or []
        if not isinstance(existing_sub, list):
            existing_sub = []
        rag_sub = subtopics_by_chapter.get(ch) if isinstance(subtopics_by_chapter, dict) else None
        subtopics_list = list(rag_sub) if isinstance(rag_sub, list) and rag_sub else existing_sub
        if los:
            structure[ch] = {
                "capability": _cap_for_chapter(ch),
                "learning_outcomes": los,
                "outcome_count": len(los),
                "subtopics": [str(s).strip() for s in subtopics_list if str(s).strip()],
            }
        elif ch not in structure or not structure[ch].get("learning_outcomes"):
            structure[ch] = {
                "capability": _cap_for_chapter(ch),
                "learning_outcomes": [],
                "outcome_count": 0,
                "subtopics": [str(s).strip() for s in subtopics_list if str(s).strip()],
            }
        else:
            structure[ch]["subtopics"] = [str(s).strip() for s in subtopics_list if str(s).strip()]

    proposed["importance_weights"] = _build_importance_weights(structure)

    # Focus 2: record unmapped chapters (no outcomes after extraction) for review
    unmapped_after = [ch for ch in chapters_clean if not by_chapter.get(ch)]
    meta["unmapped_chapters"] = unmapped_after

    return proposed


def _extract_capabilities_and_aliases(
    full_text: str,
    chapters: list[str],
    llm_generate: LLMGenerate | None,
    *,
    max_tokens: int = 2048,
    max_context: int = 6000,
) -> tuple[dict[str, str] | None, dict[str, list[str]] | None, dict[str, str] | None]:
    """
    One LLM call: extract (1) full capability list A,B,C,... -> title,
    (2) aliases chapter -> [alias], (3) chapter_to_capability chapter -> letter.
    Returns (capabilities, aliases, chapter_to_capability) or (None, None, None) on failure.
    """
    if not llm_generate or not full_text or not chapters:
        return None, None, None
    context = full_text.strip()[:max_context]
    chapters_blob = "\n".join(f"- {ch}" for ch in chapters)
    from studyplan.ai.prompt_design import RECONFIG_CAPABILITIES_PROMPT_PREFIX
    prompt = (
        RECONFIG_CAPABILITIES_PROMPT_PREFIX
        + context
        + "\n---\nChapters (use these exact strings for aliases and chapter_to_capability keys):\n"
        + chapters_blob
    )
    try:
        from studyplan.ai.prompt_design import JSON_ONLY_NO_MARKDOWN
        prompt = prompt + "\n\n" + JSON_ONLY_NO_MARKDOWN
    except ImportError:
        prompt = prompt + "\n\nReturn only the JSON object. No markdown."
    try:
        raw = llm_generate(prompt, max_tokens)
    except Exception:
        return None, None, None
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except Exception:
        return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    cap_map = data.get("capabilities")
    alias_map = data.get("aliases")
    ch_to_cap = data.get("chapter_to_capability")
    caps = None
    if isinstance(cap_map, dict):
        caps = {str(k).strip().upper(): str(v).strip() for k, v in cap_map.items() if str(k).strip()}
    aliases = None
    if isinstance(alias_map, dict):
        aliases = {}
        for k, v in alias_map.items():
            key = str(k).strip()
            if not key:
                continue
            if isinstance(v, list):
                aliases[key] = [str(x).strip() for x in v if str(x).strip()]
            elif v:
                aliases[key] = [str(v).strip()]
        if not aliases:
            aliases = None
    chapter_to_cap: dict[str, str] | None = None
    if isinstance(ch_to_cap, dict) and ch_to_cap:
        chapter_to_cap = {}
        for k, v in ch_to_cap.items():
            key = str(k).strip()
            val = str(v).strip().upper()
            if key and len(val) == 1 and val.isalpha():
                chapter_to_cap[key] = val
        if not chapter_to_cap:
            chapter_to_cap = None
    return caps, aliases, chapter_to_cap


def _extract_subtopics_by_chapter(
    full_text: str,
    chapters: list[str],
    llm_generate: LLMGenerate | None,
    *,
    max_context: int = 5000,
    max_tokens: int = 1024,
) -> dict[str, list[str]]:
    """
    Extract main section/subtopic titles per chapter from syllabus text (RAG Phase 4).
    Returns dict chapter -> list of subtopic strings; empty dict on failure or no LLM.
    """
    if not llm_generate or not full_text.strip() or not chapters:
        return {}
    context = full_text.strip()[:max_context]
    chapters_blob = "\n".join(f"- {ch}" for ch in chapters)
    from studyplan.ai.prompt_design import RECONFIG_SUBTOPICS_PROMPT_PREFIX
    prompt = (
        RECONFIG_SUBTOPICS_PROMPT_PREFIX
        + context
        + "\n---\nChapters (use these exact strings as keys):\n"
        + chapters_blob
    )
    try:
        from studyplan.ai.prompt_design import JSON_ONLY_NO_MARKDOWN
        prompt = prompt + "\n\n" + JSON_ONLY_NO_MARKDOWN
    except ImportError:
        prompt = prompt + "\n\nReturn only the JSON object. No markdown."
    try:
        raw = llm_generate(prompt, max_tokens)
    except Exception:
        return {}
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str]] = {}
    chapter_set = {str(c).strip() for c in chapters if str(c).strip()}
    for k, v in data.items():
        key = str(k).strip()
        if key not in chapter_set:
            continue
        if isinstance(v, list):
            result[key] = [str(x).strip() for x in v if str(x).strip()]
        elif isinstance(v, str) and v.strip():
            result[key] = [v.strip()]
    return result


def _extract_syllabus_meta(
    full_text: str,
    syllabus_paths: list[str] | None,
    chunks_by_path: ChunksByPath,
    llm_generate: LLMGenerate | None,
    existing_meta: dict[str, Any],
    *,
    max_context: int = 5000,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """
    Extract/fix syllabus_meta from RAG text: exam_code, effective_window, reference_pdfs.
    Merges into existing_meta; reference_pdfs set from syllabus_paths or chunk paths.
    """
    out: dict[str, Any] = {}
    # reference_pdfs: prefer syllabus_paths, else paths we have chunks for
    paths = list(syllabus_paths) if syllabus_paths else list(chunks_by_path.keys())
    if paths:
        out["reference_pdfs"] = [str(p).strip() for p in paths if str(p).strip()]
    if not llm_generate or not full_text.strip():
        return out
    context = full_text.strip()[:max_context]
    from studyplan.ai.prompt_design import RECONFIG_SYLLABUS_META_PROMPT_PREFIX
    prompt = RECONFIG_SYLLABUS_META_PROMPT_PREFIX + context + "\n---"
    try:
        from studyplan.ai.prompt_design import JSON_ONLY_NO_MARKDOWN
        prompt = prompt + "\n\n" + JSON_ONLY_NO_MARKDOWN
    except ImportError:
        prompt = prompt + "\n\nReturn only the JSON object."
    try:
        raw = llm_generate(prompt, max_tokens)
    except Exception:
        return out
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except Exception:
        return out
    if isinstance(data, dict):
        if isinstance(data.get("exam_code"), str) and data["exam_code"].strip():
            out["exam_code"] = data["exam_code"].strip().upper()
        if isinstance(data.get("effective_window"), str) and data["effective_window"].strip():
            out["effective_window"] = data["effective_window"].strip()
    return out


def _apply_importance_only(proposed: dict[str, Any]) -> None:
    """Refresh importance_weights and meta only, keep existing syllabus_structure."""
    structure = proposed.get("syllabus_structure")
    if isinstance(structure, dict):
        proposed["importance_weights"] = _build_importance_weights(structure)
    else:
        proposed["importance_weights"] = {}


def _derive_chapters_from_rag_text(
    full_text: str,
    llm_generate: LLMGenerate | None,
    *,
    max_tokens: int = 1024,
    max_context: int = 8000,
) -> list[str]:
    """
    Derive an ordered list of chapter/section titles from RAG syllabus text when module config
    has no or weak chapters.

    Source-agnostic: the text can come from ACCA official syllabus PDFs, or from Study Hub / BPP /
    Kaplan (or other) study guides once extracted into RAG. We do not parse provider-specific
    formats; we look for common heading patterns and optionally ask the LLM to list sections.

    Patterns used (order of preference):
    - After "4. The syllabus" or similar: single letter A–Z + short title (e.g. "A. Financial
      management function") — these are the main syllabus sections. Long lines after A. (e.g.
      "A. Discuss the role and purpose of...") are capability descriptions from section 2, not
      chapter titles, and are skipped.
    - "Chapter N: Title" / "Part N: Title" (e.g. BPP/Kaplan style).
    - Numbered "1. Title" / "2. Title" (subsection or provider chapter titles).
    """
    if not full_text or not full_text.strip():
        return []
    lines = [ln.strip() for ln in full_text.strip().splitlines() if ln.strip()]
    if not lines:
        return []
    seen_slugs: set[str] = set()
    ordered: list[str] = []
    in_syllabus_section = False
    # Detect start of syllabus section (ACCA "4. The syllabus" or variants)
    syllabus_start_re = re.compile(r"^\s*(?:4\.\s*)?(?:the\s+)?syllabus\s*$", re.IGNORECASE)
    # ACCA section: single letter A–Z followed by . ) - and title. Prefer short titles (section
    # headings like "A. Financial management function"); skip long capability lines ("A. Discuss...").
    section_letter_re = re.compile(r"^([A-Z])[\.\)\s\-]+\s*(.+)$")
    # Numbered section (e.g. "1. The nature and purpose")
    section_number_re = re.compile(r"^(\d+)[\.\)]\s+(.+)$")
    chapter_re = re.compile(r"^(?:Chapter|Part)\s+\d+\s*:\s*(.+)$", re.IGNORECASE)
    for line in lines:
        if len(line) < 3:
            continue
        if syllabus_start_re.match(line) or "4. The syllabus" in line:
            in_syllabus_section = True
        title: str | None = None
        m = section_letter_re.match(line)
        if m:
            letter, rest = m.group(1), (m.group(2) or "").strip()
            if len(rest) >= 2:
                # In ACCA syllabi, section 2 ("Main capabilities") has long descriptions (A. Discuss...);
                # section 4 ("The syllabus") has short section titles (A. Financial management function).
                # Only take letter-headed lines after we've seen the syllabus section, or short ones (≤50 chars).
                if in_syllabus_section and len(rest) <= 70:
                    title = f"{letter}. {rest}"
                elif not in_syllabus_section and 2 <= len(rest) <= 50:
                    title = f"{letter}. {rest}"
        if not title:
            m = chapter_re.match(line)
            if m:
                title = (m.group(1) or "").strip()
                if title:
                    title = f"Chapter: {title}"
        if not title:
            m = section_number_re.match(line)
            if m:
                rest = (m.group(2) or "").strip()
                if len(rest) >= 4 and len(rest) < 120:
                    title = f"{m.group(1)}. {rest}"
        if title:
            slug = re.sub(r"\s+", " ", title.lower()).strip()
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                ordered.append(title)
    if ordered:
        return ordered
    if llm_generate and len(full_text.strip()) >= 200:
        context = full_text.strip()[:max_context]
        prompt = (
            "You are parsing a syllabus or study guide. List the main section or chapter titles only, one per line.\n"
            "Return a JSON object with a single key \"sections\" and value a list of strings (the titles in order).\n"
            "Use only the excerpt as evidence. Return only the JSON, no markdown.\n"
            "Excerpt:\n---\n" + context + "\n---"
        )
        try:
            from studyplan.ai.prompt_design import JSON_ONLY_NO_MARKDOWN
            prompt = prompt + "\n\n" + JSON_ONLY_NO_MARKDOWN
        except ImportError:
            pass
        try:
            raw = llm_generate(prompt, max_tokens)
            raw = (raw or "").strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw)
                raw = re.sub(r"\n?```\s*$", "", raw)
            data = json.loads(raw)
            if isinstance(data, dict):
                sections = data.get("sections")
                if isinstance(sections, list) and sections:
                    for s in sections:
                        t = str(s).strip()
                        if t and len(t) >= 2:
                            slug = re.sub(r"\s+", " ", t.lower()).strip()
                            if slug not in seen_slugs:
                                seen_slugs.add(slug)
                                ordered.append(t)
        except Exception:
            pass
    return ordered
