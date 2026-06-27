"""Utilities for evaluating the quality of question banks.

Analyzes JSON structures that contain questions/options/correct/explanation
and emits quality metrics so domain experts can fix or enrich weak items.
Poor-quality questions (e.g. "see explanation" in options, duplicates, or a
correct option that is far longer/shorter than distractors) can be quarantined
and removed from the active bank.
"""

from __future__ import annotations

import json
import os
import re
import difflib
from typing import Any, Dict, List, Tuple

from .logging_config import get_logger

logger = get_logger(__name__)

# Option text that indicates a placeholder / poor question (any phrasing like "see explanation").
SEE_EXPLANATION_PATTERN = re.compile(
    r"\b(see|refer\s+to|view|check|read)\s+(the\s+)?(explanation|answer|solution|rationale)\b",
    re.IGNORECASE,
)
# Also match "explanation below", "see below", "answer in explanation", etc.
SEE_EXPLANATION_LOOSE = re.compile(
    r"\b(explanation|solution|rationale|answer)\s*(below|above|in\s+text|attached)?\b|\bsee\s+below\b",
    re.IGNORECASE,
)
META_OPTION_PATTERN = re.compile(
    r"\b(all of the above|none of the above|all of these|both a and b|both b and c|both a and c)\b",
    re.IGNORECASE,
)
# LLM gap-generation failures: template phrases instead of real distractors.
_GAP_OPTION_PLACEHOLDER_FULL = re.compile(r"(?i)^\s*(?:full|complete)\s+option\s+text\s*[:\s]*[abcd]\s*$")
_GAP_OPTION_GENERIC = re.compile(
    r"(?i)^\s*(?:option|choice)\s*[abcd]\s*$|^\s*[abcd][\.\:\)]\s*(?:option|text|choice)\s*\d?\s*$"
)
_GAP_OPTION_TBD = re.compile(r"(?i)\b(?:placeholder|tbd|todo|lorem\s+ipsum|\[insert)\b")
# Single-letter correct field (LLM used 'A'/'B'/'C'/'D' instead of full option text).
# The app shuffles options on screen, so a bare letter reference is positionally meaningless.
_CORRECT_IS_BARE_LETTER = re.compile(r"^[A-Da-d]$")
CALC_KEYWORDS_PATTERN = re.compile(
    r"\b(calculate|compute|derive|estimate|evaluate|discount|npv|irr|wacc|capm|variance|sensitivity)\b",
    re.IGNORECASE,
)

# MCQ length-balance contract: auto-quarantine, strict gap-generation validation, and LLM prompts
# (studyplan.ai.prompt_design) share these thresholds so behaviour stays aligned.
MCQ_GAP_MIN_DISTRACTOR_OPTIONS = 3
MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_LONG_RULE = 10
MCQ_GAP_LONG_OUTLIER_VS_DISTRACTOR_MEAN = 2.5  # reject if len(correct) >= this * mean(other options)
MCQ_GAP_SHORT_OUTLIER_VS_DISTRACTOR_MEAN = 0.35  # reject if len(correct) <= this * mean(other options)
MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_SHORT_RULE = 24


def gap_options_look_like_llm_placeholders(options: list[str]) -> bool:
    """True when all four strings look like template / placeholder MCQ options from a weak model."""
    if len(options) != 4:
        return False
    norm = [str(o or "").strip() for o in options]
    if any(not x for x in norm):
        return True
    hits = 0
    for o in norm:
        if _GAP_OPTION_PLACEHOLDER_FULL.search(o) or _GAP_OPTION_GENERIC.search(o):
            hits += 1
        if _GAP_OPTION_TBD.search(o):
            hits += 1
    if hits >= 2:
        return True
    # Same wording with only A/B/C/D changed, e.g. "Full option text A" … "Full option text D"
    stems = [re.sub(r"(?i)\s*[abcd]\s*$", "", o).strip().lower() for o in norm]
    if stems and len(set(stems)) == 1 and len(stems[0]) >= 8:
        return True
    return False


def correct_is_bare_letter(item: dict[str, Any]) -> bool:
    """
    Return True when the 'correct' field is a single letter (A/B/C/D).

    The app randomises option display order on screen, so a bare letter reference is
    positionally meaningless — the question is unanswerably ambiguous without knowing
    the original rendering order.  The correct field must always be the full text of
    the winning option, exactly matching one entry in options[].
    """
    if not isinstance(item, dict):
        return False
    raw = str(item.get("correct", "") or "").strip()
    return bool(_CORRECT_IS_BARE_LETTER.match(raw))


def option_looks_like_see_explanation(option_text: str) -> bool:
    """True if the option is a placeholder like 'See explanation' (any wording)."""
    if not option_text or not isinstance(option_text, str):
        return False
    text = " ".join(str(option_text).split()).strip()
    if len(text) < 6:
        return False
    if SEE_EXPLANATION_PATTERN.search(text):
        return True
    # Short options that are only "see explanation" style
    if len(text) < 35 and SEE_EXPLANATION_LOOSE.search(text):
        return True
    return False


def _tokenize_for_similarity(text: str) -> list[str]:
    if not text or not isinstance(text, str):
        return []
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    tokens = [t for t in cleaned.split() if len(t) >= 2]
    return tokens


def _jaccard_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _options_list_from_item(item: dict[str, Any]) -> list[str]:
    """Normalize item.options to a list of stripped strings (supports list or A–D dict)."""
    opts = item.get("options") or []
    if isinstance(opts, dict):
        opts = [opts.get(k) for k in ("A", "B", "C", "D") if opts.get(k) is not None]
    if not isinstance(opts, list):
        return []
    return [str(x or "").strip() for x in opts]


def _resolve_correct_option_text(item: dict[str, Any], opts: list[str]) -> str | None:
    """
    Map item['correct'] to the canonical option string when possible (letter, index, or exact text).
    """
    if len(opts) < 2:
        return None
    raw = str(item.get("correct", "") or "").strip()
    if not raw:
        return None
    if raw in opts:
        return raw
    upper = raw.upper()
    if len(upper) == 1 and "A" <= upper <= "Z":
        idx = ord(upper) - ord("A")
        if 0 <= idx < len(opts):
            return opts[idx]
    if raw.isdigit():
        k = int(raw)
        if 0 <= k < len(opts):
            return opts[k]
        if 1 <= k <= len(opts):
            return opts[k - 1]
    rl = raw.lower()
    for o in opts:
        if o.lower() == rl:
            return o
    return None


def correct_option_length_guessable_reason(item: dict[str, Any]) -> str | None:
    """
    If the keyed correct answer is much longer or much shorter than distractors on average,
    return a quarantine reason; otherwise None.

    Distractor-only averages avoid penalising items where all four options are long but
    the correct one is only moderately above the mean of all four.
    """
    opts = _options_list_from_item(item)
    if len(opts) < 2 or any(not o for o in opts):
        return None
    correct_text = _resolve_correct_option_text(item, opts)
    if not correct_text or correct_text not in opts:
        return None
    others = [o for o in opts if o != correct_text]
    if len(others) < MCQ_GAP_MIN_DISTRACTOR_OPTIONS:
        return None
    clen = len(correct_text)
    lens = [len(o) for o in others]
    avg_other = sum(lens) / max(1, len(lens))
    if avg_other < MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_LONG_RULE:
        return None
    if clen >= MCQ_GAP_LONG_OUTLIER_VS_DISTRACTOR_MEAN * avg_other:
        return "correct_option_much_longer_than_distractors"
    if (
        avg_other >= MCQ_GAP_MIN_AVG_DISTRACTOR_CHARS_SHORT_RULE
        and clen <= MCQ_GAP_SHORT_OUTLIER_VS_DISTRACTOR_MEAN * avg_other
    ):
        return "correct_option_much_shorter_than_distractors"
    return None


def _is_numeric_option(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    compact = text.strip()
    return bool(re.match(r"^\(?-?\$?\d", compact))


def _normalize_option_surface(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
    compact = " ".join(str(text).strip().lower().split())
    compact = re.sub(r"[^\w\s%$().,-]", "", compact)
    return compact.strip()


def _option_mentions_in_text(text: str, option: str) -> bool:
    base = _normalize_option_surface(text)
    target = _normalize_option_surface(option)
    if not base or not target or len(target) < 3:
        return False
    return target in base


def _near_duplicate_distractor_reason(item: dict[str, Any]) -> str | None:
    opts = _options_list_from_item(item)
    correct_text = _resolve_correct_option_text(item, opts)
    if len(opts) < 3:
        return None
    distractors = [o for o in opts if o and o != correct_text]
    if len(distractors) < 2:
        return None
    normalized = [_normalize_option_surface(opt) for opt in distractors if _normalize_option_surface(opt)]
    for idx, left in enumerate(normalized):
        for right in normalized[idx + 1 :]:
            if not left or not right:
                continue
            if left == right:
                return "near_duplicate_distractors"
            left_tokens = _tokenize_for_similarity(left)
            right_tokens = _tokenize_for_similarity(right)
            sim = _jaccard_similarity(left_tokens, right_tokens)
            if sim >= 0.9:
                return "near_duplicate_distractors"
            seq_ratio = difflib.SequenceMatcher(None, left, right).ratio()
            if sim >= 0.55 and seq_ratio >= 0.72:
                return "near_duplicate_distractors"
            shorter = left if len(left) <= len(right) else right
            longer = right if shorter == left else left
            if len(shorter) >= 12 and shorter in longer and sim >= 0.65:
                return "near_duplicate_distractors"
    return None


def _parse_numeric_option(text: str) -> tuple[bool, str]:
    raw = str(text or "").strip()
    if not raw:
        return False, ""
    if not re.search(r"\d", raw):
        return False, ""
    kind = "plain"
    if "%" in raw:
        kind = "percent"
    elif "$" in raw or "\u00a3" in raw or "\u20ac" in raw:
        kind = "currency"
    compact = raw.replace(",", "").replace("$", "").replace("\u00a3", "").replace("\u20ac", "").replace("%", "").strip()
    if compact.startswith("(") and compact.endswith(")"):
        compact = "-" + compact[1:-1].strip()
    if compact.startswith("+"):
        compact = compact[1:].strip()
    if re.match(r"^-?\d+(?:\.\d+)?$", compact):
        return True, kind
    if re.match(r"^-?\d+(?:\.\d+)?\s+[A-Za-z][A-Za-z\s./-]*$", compact):
        return True, kind
    return False, kind


def _parse_numeric_value(text: str) -> tuple[bool, float | None, str]:
    raw = str(text or "").strip()
    ok, kind = _parse_numeric_option(raw)
    if not ok:
        return False, None, kind
    compact = raw.replace(",", "").replace("$", "").replace("\u00a3", "").replace("\u20ac", "").replace("%", "").strip()
    if compact.startswith("(") and compact.endswith(")"):
        compact = "-" + compact[1:-1].strip()
    if compact.startswith("+"):
        compact = compact[1:].strip()
    try:
        return True, float(compact), kind
    except Exception:
        match = re.match(r"^(-?\d+(?:\.\d+)?)\s+[A-Za-z][A-Za-z\s./-]*$", compact)
        if match:
            try:
                return True, float(match.group(1)), kind
            except Exception:
                pass
        return False, None, kind


def _numeric_values_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    tolerance = max(0.01, abs(right) * 0.0001)
    return abs(float(left) - float(right)) <= tolerance


def _extract_numeric_values(text: str) -> list[float]:
    raw = str(text or "")
    if not raw:
        return []
    values: list[float] = []
    for match in re.finditer(r"(?<![A-Za-z0-9])-?\(?[\$\u00a3\u20ac]?\d[\d,]*(?:\.\d+)?%?\)?", raw):
        ok, value, _kind = _parse_numeric_value(match.group(0))
        if ok and value is not None:
            values.append(value)
    return values


def _numeric_option_format_issue(item: dict[str, Any]) -> str | None:
    opts = _options_list_from_item(item)
    if len(opts) < 2:
        return None
    parsed = [_parse_numeric_option(opt) for opt in opts]
    parseable = [kind for ok, kind in parsed if ok]
    numericish = [kind for ok, kind in parsed if ok or kind]
    if len(numericish) < 2:
        return None
    if any((not ok) and kind for ok, kind in parsed):
        return "malformed_numeric_option"
    kinds = {kind for kind in parseable if kind}
    if len(parseable) >= 3 and len(kinds) > 1:
        return "numeric_option_format_inconsistent"
    return None


def _numeric_answer_consistency_issue(item: dict[str, Any]) -> str | None:
    question_text = str(item.get("question", "") or "")
    explanation = str(item.get("explanation", "") or "").strip()
    opts = _options_list_from_item(item)
    if len(opts) < 3 or not explanation:
        return None
    parsed_options = [(opt, *_parse_numeric_value(opt)) for opt in opts]
    numeric_options = [(opt, value, kind) for opt, ok, value, kind in parsed_options if ok and value is not None]
    if len(numeric_options) < 3:
        return None
    correct_text = _resolve_correct_option_text(item, opts)
    if not correct_text:
        return None
    correct_ok, correct_value, correct_kind = _parse_numeric_value(correct_text)
    if not correct_ok or correct_value is None:
        return "numeric_options_but_correct_not_numeric"
    explanation_values = _extract_numeric_values(explanation)
    if not explanation_values:
        if CALC_KEYWORDS_PATTERN.search(question_text):
            return "numeric_explanation_missing_answer_value"
        return None
    mentions_correct_value = any(_numeric_values_close(value, correct_value) for value in explanation_values)
    for opt, value, kind in numeric_options:
        if opt == correct_text:
            continue
        if kind and correct_kind and kind != correct_kind:
            continue
        if (
            any(_numeric_values_close(value, mentioned) for mentioned in explanation_values)
            and not mentions_correct_value
        ):
            return "explanation_numeric_supports_distractor"
    if CALC_KEYWORDS_PATTERN.search(question_text) and not mentions_correct_value:
        return "numeric_explanation_missing_answer_value"
    return None


def _explanation_consistency_issue(item: dict[str, Any]) -> str | None:
    explanation = str(item.get("explanation", "") or "").strip()
    if len(explanation) < 12:
        return None
    opts = _options_list_from_item(item)
    correct_text = _resolve_correct_option_text(item, opts)
    if not opts or not correct_text:
        return None
    mentioned: list[str] = []
    for opt in opts:
        if _option_mentions_in_text(explanation, opt):
            mentioned.append(opt)
    if not mentioned:
        return None
    if correct_text in mentioned:
        return None
    unique_mentioned = []
    seen: set[str] = set()
    for opt in mentioned:
        key = _normalize_option_surface(opt)
        if key and key not in seen:
            unique_mentioned.append(opt)
            seen.add(key)
    if len(unique_mentioned) == 1:
        return "explanation_supports_distractor"
    return None


def _estimate_difficulty(question_text: str, options: list[str]) -> str:
    score = 0
    q_text = str(question_text or "").strip()
    words = q_text.split()
    if len(words) >= 28:
        score += 2
    elif len(words) >= 18:
        score += 1
    if CALC_KEYWORDS_PATTERN.search(q_text):
        score += 2
    if options and all(_is_numeric_option(opt) for opt in options):
        score += 1
    if re.search(r"\b(explain|define|state)\b", q_text, re.IGNORECASE):
        score = max(0, score - 1)
    if score <= 1:
        return "easy"
    if score <= 3:
        return "medium"
    return "hard"


def assess_question_quality_extended(item: Any) -> dict[str, Any]:
    """Extended quality assessment including distractor similarity and difficulty guess."""
    base = QuestionQuality(item)
    base.assess()
    report = base.report()
    issues: list[str] = list(report.get("errors", [])) + list(report.get("warnings", []))
    penalty = 0.0

    question_text = ""
    options: list[str] = []
    correct = ""
    if isinstance(item, dict):
        question_text = str(item.get("question", "") or "")
        raw_options = item.get("options", [])
        if isinstance(raw_options, list):
            options = [str(x or "").strip() for x in raw_options]
        correct = str(item.get("correct", "") or "").strip()

    max_similarity = 0.0
    if options and correct:
        correct_tokens = _tokenize_for_similarity(correct)
        for opt in options:
            if str(opt or "").strip() == correct:
                continue
            sim = _jaccard_similarity(correct_tokens, _tokenize_for_similarity(opt))
            max_similarity = max(max_similarity, sim)
        if max_similarity >= 0.85:
            issues.append("distractor_too_similar")
            penalty += 0.15

    if options and correct:
        lengths = [len(opt) for opt in options if isinstance(opt, str)]
        if lengths:
            avg_len = sum(lengths) / max(1, len(lengths))
            corr_len = len(correct)
            if avg_len > 0 and (corr_len >= avg_len * 2.0 or corr_len <= avg_len * 0.55):
                issues.append("correct_length_outlier")
                penalty += 0.10

    if any(META_OPTION_PATTERN.search(str(opt or "")) for opt in options):
        issues.append("meta_option_present")
        penalty += 0.10

    if isinstance(item, dict):
        near_dup_issue = _near_duplicate_distractor_reason(item)
        if near_dup_issue and near_dup_issue not in issues:
            issues.append(near_dup_issue)
            penalty += 0.12
        numeric_issue = _numeric_option_format_issue(item)
        if numeric_issue and numeric_issue not in issues:
            issues.append(numeric_issue)
            penalty += 0.1
        numeric_answer_issue = _numeric_answer_consistency_issue(item)
        if numeric_answer_issue and numeric_answer_issue not in issues:
            issues.append(numeric_answer_issue)
            penalty += 0.25
        explanation_issue = _explanation_consistency_issue(item)
        if explanation_issue and explanation_issue not in issues:
            issues.append(explanation_issue)
            penalty += 0.2

    difficulty_guess = _estimate_difficulty(question_text, options)
    base_score = float(report.get("score", 0.0) or 0.0)
    score = max(0.0, min(1.0, base_score - penalty))
    return {
        "score": round(score, 2),
        "base_score": round(base_score, 2),
        "issues": issues,
        "difficulty_guess": difficulty_guess,
        "max_distractor_similarity": round(max_similarity, 2),
    }


class QuestionQuality:
    """Holds quality assessment results for a single question."""

    def __init__(self, item: Any):
        self._invalid_payload = not isinstance(item, dict)
        self.item: dict[str, Any] = item if isinstance(item, dict) else {}
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.score = 1.0  # start perfect, deduct for issues

    def assess(self) -> None:
        if self._invalid_payload:
            self.errors.append("question item is not an object")
            self.score = 0.0
            return
        self._check_structure()
        self._check_options()
        self._check_explanation()
        self._check_readability()

    def _check_structure(self) -> None:
        question_text = str(self.item.get("question", "") or "").strip()
        if not question_text:
            self.errors.append("missing question text")
            self.score -= 0.5
        if "options" not in self.item or not isinstance(self.item["options"], list):
            self.errors.append("missing/invalid options list")
            self.score -= 0.5
        if "correct" not in self.item or not str(self.item.get("correct", "")).strip():
            self.errors.append("missing correct answer")
            self.score -= 0.3
        if self.errors:
            return

    def _check_options(self) -> None:
        opts = [str(x or "").strip() for x in self.item.get("options", [])]
        unique = set(opts)
        if len(opts) != len(unique):
            self.errors.append("duplicate option text")
            self.score -= 0.5
        # Option that says "see explanation" (any wording) = poor quality, remove from bank
        for o in opts:
            if option_looks_like_see_explanation(o):
                self.errors.append("option is 'see explanation' placeholder")
                self.score -= 0.5
                break
        # LLM-generated placeholder options such as "Full option text A" = unanswerably fake
        if gap_options_look_like_llm_placeholders(opts):
            self.errors.append("options are LLM placeholder templates")
            self.score -= 0.5
        correct = str(self.item.get("correct", "")).strip()
        # Bare letter (A/B/C/D) in 'correct' means the LLM used position-based referencing.
        # The app shuffles options on display, so this answer is ambiguous and untrustworthy.
        if _CORRECT_IS_BARE_LETTER.match(correct):
            self.errors.append("correct field is a bare letter (A/B/C/D) — must be full option text")
            self.score -= 0.5
        elif correct not in opts:
            self.errors.append("correct answer not present in options")
            self.score -= 0.4
        # check variety
        lengths = [len(o) for o in opts]
        if lengths and max(lengths) / max(1, min(lengths)) > 5:
            self.warnings.append("option lengths vary widely")
            self.score -= 0.1
        # numeric consistency
        if all(re.match(r"^\$?\d", o) for o in opts):
            # all options start with numbers or currency
            # ensure correct also numeric
            if not re.match(r"^\$?\d", correct):
                self.warnings.append("numeric options but nonnumeric correct answer")
                self.score -= 0.1

    def _check_explanation(self) -> None:
        expl = str(self.item.get("explanation", "")).strip()
        if not expl:
            self.warnings.append("no explanation provided")
            self.score -= 0.2
        elif len(expl) < 20:
            self.warnings.append("explanation very short")
            self.score -= 0.1

    def _check_readability(self) -> None:
        text = str(self.item.get("question", "") or "")
        # basic readability: sentence length
        sentences = re.split(r"[.!?]", text)
        if any(len(s.split()) > 30 for s in sentences):
            self.warnings.append("very long sentence in question")
            self.score -= 0.1
        # trailing spaces
        if text != text.strip():
            self.warnings.append("question text has leading/trailing whitespace")

    def report(self) -> dict[str, Any]:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "score": round(max(0.0, min(1.0, self.score)), 2),
        }


class QuestionBankEvaluator:
    """Walks through a directory or JSON file(s) and evaluates all questions."""

    def __init__(self, paths: List[str]):
        self.paths = paths
        self.results: List[Tuple[str, QuestionQuality]] = []

    def run(self) -> None:
        for path in self.paths:
            if os.path.isdir(path):
                for fname in os.listdir(path):
                    if fname.lower().endswith(".json"):
                        self._evaluate_file(os.path.join(path, fname))
            elif os.path.isfile(path):
                self._evaluate_file(path)

    def _evaluate_file(self, filepath: str) -> None:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("failed to load question file", extra={"file": filepath, "error": str(e)})
            return
        # data expected to be dict of chapters -> list of items
        if isinstance(data, dict):
            for chapter, items in data.items():
                if isinstance(items, list):
                    for idx, item in enumerate(items):
                        q = QuestionQuality(item)
                        q.assess()
                        self.results.append((f"{filepath}:{chapter}[{idx}]", q))
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                q = QuestionQuality(item)
                q.assess()
                self.results.append((f"{filepath}[{idx}]", q))

    def summary(self) -> dict[str, Any]:
        total = len(self.results)
        if total == 0:
            return {"total": 0}
        scores = [q.score for _, q in self.results]
        bad = [r for r in self.results if r[1].score < 0.6]
        return {
            "total": total,
            "average_score": round(sum(scores) / total, 2),
            "low_quality_count": len(bad),
        }

    def report_bad(self, threshold: float = 0.6) -> List[Tuple[str, dict[str, Any]]]:
        return [(loc, q.report()) for loc, q in self.results if q.score < threshold]


def _normalize_question_text_for_similarity(text: str) -> str:
    """Normalize for duplicate/similarity detection."""
    if not text or not isinstance(text, str):
        return ""
    t = " ".join(str(text).lower().split())
    t = re.sub(r"[^\w\s]", "", t)
    return t.strip()


def get_poor_quality_indices(
    chapter: str,
    items: List[dict[str, Any]],
    *,
    detect_see_explanation: bool = True,
    detect_similar: bool = True,
    similar_min_words: int = 8,
    detect_length_guessable: bool = True,
    detect_bare_letter_correct: bool = True,
) -> List[Tuple[int, str]]:
    """
    Return indices of poor-quality questions that should be removed from the bank.
    Each element is (index, reason). Reasons include: 'see_explanation_in_options',
    'similar_question', 'correct_option_much_longer_than_distractors',
    'correct_option_much_shorter_than_distractors', 'correct_is_bare_letter'.
    """
    poor: List[Tuple[int, str]] = []
    if not items:
        return poor
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        opts = _options_list_from_item(item)
        if detect_see_explanation:
            for o in opts:
                if option_looks_like_see_explanation(str(o or "")):
                    poor.append((idx, "see_explanation_in_options"))
                    break
        if not any(i == idx for i, _ in poor):
            # Duplicate options within a single question (any two options share the same text).
            norm_opts = [str(o or "").strip().lower() for o in opts]
            if len(norm_opts) != len(set(norm_opts)):
                poor.append((idx, "duplicate_options"))
        if not any(i == idx for i, _ in poor):
            # LLM placeholder options such as "Full option text A/B/C/D".
            if gap_options_look_like_llm_placeholders(opts):
                poor.append((idx, "placeholder_options"))
        if detect_bare_letter_correct and not any(i == idx for i, _ in poor):
            if correct_is_bare_letter(item):
                poor.append((idx, "correct_is_bare_letter"))
        if detect_length_guessable and not any(i == idx for i, _ in poor):
            lg_reason = correct_option_length_guessable_reason(item)
            if lg_reason:
                poor.append((idx, lg_reason))
        if not any(i == idx for i, _ in poor):
            numeric_issue = _numeric_option_format_issue(item) or _numeric_answer_consistency_issue(item)
            if numeric_issue:
                poor.append((idx, numeric_issue))
        if not any(i == idx for i, _ in poor):
            explanation_issue = _explanation_consistency_issue(item)
            if explanation_issue:
                poor.append((idx, explanation_issue))
    if not detect_similar or similar_min_words < 1:
        return sorted(poor, key=lambda x: x[0])
    # Build normalized question text; mark later duplicates/similar as poor
    seen_normalized: Dict[str, int] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if any(i == idx for i, _ in poor):
            continue
        qtext = _normalize_question_text_for_similarity(item.get("question") or "")
        if len(qtext.split()) < similar_min_words:
            continue
        if qtext in seen_normalized:
            poor.append((idx, "similar_question"))
            continue
        duplicate_of = None
        for prev_norm, prev_idx in list(seen_normalized.items()):
            words_prev = set(prev_norm.split())
            words_cur = set(qtext.split())
            if not words_prev or not words_cur:
                continue
            inter = len(words_prev & words_cur)
            union = len(words_prev | words_cur)
            if union > 0 and (inter / union) >= 0.85:
                duplicate_of = prev_idx
                break
        if duplicate_of is not None:
            poor.append((idx, "similar_question"))
            continue
        seen_normalized[qtext] = idx
    return sorted(poor, key=lambda x: x[0])


GENERATED_QUESTION_HARD_REJECTION_ISSUES = {
    "correct_is_bare_letter",
    "correct_not_in_options",
    "duplicate_options",
    "empty_option",
    "explanation_numeric_supports_distractor",
    "explanation_supports_distractor",
    "malformed_numeric_option",
    "missing_correct",
    "near_duplicate_distractors",
    "numeric_explanation_missing_answer_value",
    "numeric_option_format_inconsistent",
    "numeric_options_but_correct_not_numeric",
    "options_not_four",
    "placeholder_options",
    "placeholder_options_only",
    "question_too_short",
    "see_explanation_in_options",
}


def generated_question_rejection_reasons(
    item: Any,
    *,
    strict: bool = True,
    score_threshold: float = 0.6,
) -> list[str]:
    """Return deterministic reasons to reject/quarantine a generated question.

    This intentionally does not ask another LLM to repair the item. Callers may do
    lossless parsing/normalization before this check, then reject anything that
    fails answer-key, numeric, or quality gates.
    """
    if not isinstance(item, dict):
        return ["non_object_row"]
    reasons: list[str] = []
    opts = _options_list_from_item(item)
    question = str(item.get("question", "") or "").strip()
    correct = str(item.get("correct", "") or "").strip()
    str(item.get("explanation", "") or "").strip()

    if len(question) < (8 if strict else 4):
        reasons.append("question_too_short")
    if len(opts) != 4:
        reasons.append("options_not_four")
    elif any(not opt for opt in opts):
        reasons.append("empty_option")
    if opts and len({opt.lower() for opt in opts}) != len(opts):
        reasons.append("duplicate_options")
    if gap_options_look_like_llm_placeholders(opts):
        reasons.append("placeholder_options")
    if correct_is_bare_letter(item):
        reasons.append("correct_is_bare_letter")
    elif opts and correct and correct not in opts:
        reasons.append("correct_not_in_options")
    elif opts and not correct:
        reasons.append("missing_correct")
    for opt in opts:
        if option_looks_like_see_explanation(opt):
            reasons.append("see_explanation_in_options")
            break

    for issue in (
        correct_option_length_guessable_reason(item),
        _near_duplicate_distractor_reason(item),
        _numeric_option_format_issue(item),
        _numeric_answer_consistency_issue(item),
        _explanation_consistency_issue(item),
    ):
        if issue:
            reasons.append(str(issue))

    report = assess_question_quality_extended(item)
    for issue in list(report.get("issues", []) or []):
        text = str(issue or "").strip()
        if text in GENERATED_QUESTION_HARD_REJECTION_ISSUES:
            reasons.append(text)
    if strict and float(report.get("score", 0.0) or 0.0) < float(score_threshold):
        reasons.append("low_quality_score")

    seen: set[str] = set()
    out: list[str] = []
    for reason in reasons:
        key = str(reason or "").strip()
        if key and key not in seen:
            out.append(key)
            seen.add(key)
    return out


if __name__ == "__main__":
    import sys

    paths = sys.argv[1:] or ["."]
    evaluator = QuestionBankEvaluator(paths)
    evaluator.run()
    print("Summary:", evaluator.summary())
    bad = evaluator.report_bad()
    if bad:
        print("Low-quality items:")
        for loc, rpt in bad[:20]:
            print(loc, rpt)
