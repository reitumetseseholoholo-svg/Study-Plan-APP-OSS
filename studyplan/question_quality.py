"""Utilities for evaluating the quality of question banks.

Analyzes JSON structures that contain questions/options/correct/explanation
and emits quality metrics so domain experts can fix or enrich weak items.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Tuple

from .logging_config import get_logger

logger = get_logger(__name__)


class QuestionQuality:
    """Holds quality assessment results for a single question."""

    def __init__(self, item: dict[str, Any]):
        self.item = item
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.score = 1.0  # start perfect, deduct for issues

    def assess(self) -> None:
        self._check_structure()
        self._check_options()
        self._check_explanation()
        self._check_readability()

    def _check_structure(self) -> None:
        if "question" not in self.item or not self.item["question"].strip():
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
            self.warnings.append("duplicate option text")
            self.score -= 0.2
        correct = str(self.item.get("correct", "")).strip()
        if correct not in opts:
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
        text = self.item.get("question", "")
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
