"""
Tutor action prompts from the quality matrix (explain, apply, exam_technique, drill).

Provides a single source of truth so the in-app tutor and the tutor quality benchmark
use the same prompts when (module_id, chapter, action_type) match. See PROMPT_QUALITY_SLICE.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Default matrix filename; path resolved via get_tutor_matrix_path().
MATRIX_FILENAME = "matrix_v1.json"

_matrix_cache: dict[str, dict[str, Any]] = {}  # path -> loaded matrix


def get_tutor_matrix_path() -> Path | None:
    """
    Return path to the tutor quality matrix JSON, or None if not found.

    Uses STUDYPLAN_TUTOR_QUALITY_MATRIX if set; otherwise looks for
    tests/tutor_quality/matrix_v1.json relative to the repo root (when running from source).
    """
    env_path = (os.environ.get("STUDYPLAN_TUTOR_QUALITY_MATRIX") or "").strip()
    if env_path:
        p = Path(env_path).resolve()
        return p if p.is_file() else None
    # Repo layout: studyplan/ai/tutor_prompts.py -> parents[2] = repo root
    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "tests" / "tutor_quality" / MATRIX_FILENAME
    return candidate if candidate.is_file() else None


def load_tutor_matrix(path: Path | None) -> dict[str, Any]:
    """Load the matrix JSON; returns empty dict if path is None or file invalid. Cached by path."""
    if path is None:
        return {}
    key = str(path.resolve())
    if key in _matrix_cache:
        return _matrix_cache[key]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            _matrix_cache[key] = {}
            return {}
        _matrix_cache[key] = data
        return data
    except Exception:
        _matrix_cache[key] = {}
        return {}


def _chapter_match(matrix_chapter: str, app_chapter: str) -> bool:
    """True if the matrix chapter and app chapter refer to the same topic (exact or normalized)."""
    m = (matrix_chapter or "").strip()
    a = (app_chapter or "").strip()
    if not m or not a:
        return False
    if m == a:
        return True
    if m.lower() == a.lower():
        return True
    # One contains the other (e.g. "Chapter 5: IFRS 15" vs "IFRS 15 Revenue from Contracts")
    if m in a or a in m:
        return True
    return False


def get_prompt_for_tutor_action(
    module_id: str,
    chapter: str,
    action_type: str,
    *,
    matrix_path: Path | None = None,
) -> str | None:
    """
    Return the canonical prompt for (module_id, chapter, action_type) from the tutor quality matrix.

    action_type must be one of: explain, apply, exam_technique, drill.
    Returns None if the matrix is missing, or no matching case is found (caller should use fallback template).
    """
    path = matrix_path if matrix_path is not None else get_tutor_matrix_path()
    data = load_tutor_matrix(path)
    cases = data.get("cases")
    if not isinstance(cases, list):
        return None
    module_id = (module_id or "").strip()
    chapter = (chapter or "").strip()
    action_type = (action_type or "").strip().lower()
    if not module_id or not action_type:
        return None
    if action_type not in ("explain", "apply", "exam_technique", "drill"):
        return None
    for case in cases:
        if not isinstance(case, dict):
            continue
        if str(case.get("module_id") or "").strip() != module_id:
            continue
        if str(case.get("action_type") or "").strip().lower() != action_type:
            continue
        if not _chapter_match(str(case.get("chapter") or ""), chapter):
            continue
        prompt = (case.get("prompt") or "").strip()
        if prompt:
            return prompt
    # No exact match: try first case for (module_id, action_type) as fallback for same module
    for case in cases:
        if not isinstance(case, dict):
            continue
        if str(case.get("module_id") or "").strip() != module_id:
            continue
        if str(case.get("action_type") or "").strip().lower() != action_type:
            continue
        prompt = (case.get("prompt") or "").strip()
        if prompt:
            return prompt
    return None
