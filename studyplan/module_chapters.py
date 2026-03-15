"""
Canonical handling of module chapter lists for ACCA StudyPlan.

Use this module to:
- Define chapter lists in a single source of truth (list of titles, optional weights).
- Build linear chapter_flow and importance_weights consistently.
- Apply a chapter spec to a module config (JSON) without touching other keys.

Chapter spec format (any of):
- List of strings: ["Chapter 1: Title", "Chapter 2: Title", ...]
- List of dicts: [{"title": "Chapter 1: Title", "weight": 12}, {"title": "Chapter 2: Title"}, ...]
  (weight optional; if omitted, default_weight is used, typically 10)
"""
from __future__ import annotations

import json
import os
from typing import Any

# Default weight when not specified (engine uses 5–40 range).
DEFAULT_CHAPTER_WEIGHT = 10
MIN_WEIGHT = 5
MAX_WEIGHT = 40


def _coerce_weight(value: Any, default: int = DEFAULT_CHAPTER_WEIGHT) -> int:
    if value is None:
        return default
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(MIN_WEIGHT, min(MAX_WEIGHT, v))


def normalize_chapter_spec(
    spec: list[dict[str, Any]] | list[str],
    *,
    default_weight: int = DEFAULT_CHAPTER_WEIGHT,
) -> tuple[list[str], dict[str, int]]:
    """
    Normalize a chapter spec into a canonical list of titles and per-chapter weights.

    - spec: List of chapter titles (str) or list of {"title": str, "weight": int?}.
    - default_weight: Used when a list item has no "weight" (dict form) or for all items (str form).

    Returns:
        (chapters, importance_weights) with no duplicates (first occurrence kept), no empty titles.
    """
    chapters: list[str] = []
    weights: dict[str, int] = {}
    seen_lower: set[str] = set()

    for item in spec or []:
        if isinstance(item, str):
            title = str(item).strip()
            weight = default_weight
        elif isinstance(item, dict):
            title = str((item.get("title") or item.get("name") or "")).strip()
            weight = _coerce_weight(item.get("weight"), default_weight)
        else:
            continue
        if not title:
            continue
        key = title.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        chapters.append(title)
        weights[title] = weight

    # Ensure every chapter has a weight (default if missing).
    for ch in chapters:
        if ch not in weights:
            weights[ch] = default_weight

    return chapters, weights


def build_linear_chapter_flow(chapters: list[str]) -> dict[str, list[str]]:
    """
    Build a linear chapter_flow: each chapter points to the next; last points to [].
    """
    flow: dict[str, list[str]] = {}
    for i, ch in enumerate(chapters):
        if i + 1 < len(chapters):
            flow[ch] = [chapters[i + 1]]
        else:
            flow[ch] = []
    return flow


def apply_chapters_to_config(
    config: dict[str, Any],
    chapter_spec: list[dict[str, Any]] | list[str],
    *,
    default_weight: int = DEFAULT_CHAPTER_WEIGHT,
    preserve_questions: bool = True,
    preserve_semantic_aliases: bool = True,
    preserve_existing_weights: bool = True,
) -> dict[str, Any]:
    """
    Update a module config with a canonical chapter list and derived flow/weights.

    - config: Existing module JSON (or empty dict). Not mutated; a copy is returned.
    - chapter_spec: As in normalize_chapter_spec (list of titles or list of {title, weight?}).
    - default_weight: Used when a chapter has no explicit weight.
    - preserve_questions: If True, keep config["questions"] unchanged (default True).
    - preserve_semantic_aliases: If True, keep config["semantic_aliases"] unchanged (default True).
    - preserve_existing_weights: If True, for any chapter already in config["importance_weights"],
      use that value instead of the spec default (default True). New chapters still get default or
      spec weight.

    Returns:
        New dict with chapters, chapter_flow, importance_weights set from spec;
        title, questions, semantic_aliases, and other keys preserved from config.
    """
    out = dict(config)
    chapters, importance_weights = normalize_chapter_spec(
        chapter_spec, default_weight=default_weight
    )
    if not chapters:
        return out

    if preserve_existing_weights and isinstance(config.get("importance_weights"), dict):
        existing = config["importance_weights"]
        for ch in chapters:
            if ch in existing:
                try:
                    w = int(float(existing[ch]))
                    importance_weights[ch] = max(MIN_WEIGHT, min(MAX_WEIGHT, w))
                except (TypeError, ValueError):
                    pass

    out["chapters"] = list(chapters)
    out["chapter_flow"] = build_linear_chapter_flow(chapters)
    out["importance_weights"] = dict(importance_weights)

    if preserve_questions and "questions" not in out:
        out["questions"] = {}
    if preserve_semantic_aliases and "semantic_aliases" not in out:
        out["semantic_aliases"] = {}

    return out


def load_chapter_spec_from_path(path: str) -> list[dict[str, Any]] | list[str]:
    """
    Load a chapter spec from a JSON or YAML file.

    - JSON: array of strings or array of objects with "title" and optional "weight".
    - YAML: same structure (list of strings or list of {title: ..., weight: ...}).

    Returns the raw list for use with normalize_chapter_spec / apply_chapters_to_config.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        raise ValueError(f"Cannot read chapter spec file {path!r}: {e}") from e
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[reportMissingModuleSource]
        except ImportError:
            raise RuntimeError("YAML support requires PyYAML; install with: pip install pyyaml")
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in chapter spec {path!r}: {e}") from e
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in chapter spec {path!r}: {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"Chapter spec file must contain a list; got {type(data).__name__}")
    return data


def validate_chapter_config(config: dict[str, Any]) -> list[str]:
    """
    Run basic validation on a config's chapter structure. Returns list of warning/error messages.
    """
    messages: list[str] = []
    chapters = config.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        messages.append("config has no or empty 'chapters' list")
        return messages

    flow = config.get("chapter_flow")
    weights = config.get("importance_weights")

    if isinstance(flow, dict):
        for ch, targets in flow.items():
            if ch not in chapters:
                messages.append(f"chapter_flow key not in chapters: {ch!r}")
            if isinstance(targets, list):
                for t in targets:
                    if t not in chapters:
                        messages.append(f"chapter_flow target not in chapters: {t!r}")

    if isinstance(weights, dict):
        for ch in chapters:
            if ch not in weights:
                messages.append(f"chapter missing from importance_weights: {ch!r}")
        for ch in weights:
            if ch not in chapters:
                messages.append(f"importance_weights key not in chapters: {ch!r}")

    return messages
