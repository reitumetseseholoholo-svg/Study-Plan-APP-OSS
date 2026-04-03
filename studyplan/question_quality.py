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
_GAP_OPTION_PLACEHOLDER_FULL = re.compile(
    r"(?i)^\s*(?:full|complete)\s+option\s+text\s*[:\s]*[abcd]\s*$"
)
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
                    if fname.lower().endswith('.json'):
                        self._evaluate_file(os.path.join(path, fname))
            elif os.path.isfile(path):
                self._evaluate_file(path)

    def _evaluate_file(self, filepath: str) -> None:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
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


if __name__ == "__main__":
    import sys

    paths = sys.argv[1:] or ['.']
    evaluator = QuestionBankEvaluator(paths)
    evaluator.run()
    print("Summary:", evaluator.summary())
    bad = evaluator.report_bad()
    if bad:
        print("Low-quality items:")
        for loc, rpt in bad[:20]:
            print(loc, rpt)
