from __future__ import annotations

from typing import Any


ACTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "explain": ("because", "means", "therefore"),
    "apply": ("step", "calculate", "decision"),
    "exam_technique": ("structure", "time", "scenario"),
    "drill": ("question", "answer", "pitfall"),
}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _clean_phrase_list(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        token = _normalize_text(str(row))
        if token and token not in out:
            out.append(token)
    return out


def build_reference_response(case: dict[str, Any]) -> str:
    expected = case.get("expected", {})
    qc = expected.get("quality_checks") if isinstance(expected, dict) else {}
    must = _clean_phrase_list(expected.get("must_include", []))[:3]
    action_type = str(case.get("action_type", "")).strip().lower()
    keywords = ACTION_KEYWORDS.get(action_type, ())
    core = ", ".join(must) if must else "core points"
    if action_type == "explain":
        base = (
            f"This means {core}. Because these concepts define the logic, "
            f"therefore the explanation stays exam-focused."
        )
    elif action_type == "apply":
        base = (
            f"Step 1: calculate using {core}. "
            f"Step 2: calculate final position. "
            f"Decision: choose the option supported by the calculation."
        )
    elif action_type == "exam_technique":
        base = (
            f"Use clear structure, control time, and tie every point to the scenario. "
            f"Include {core} in the answer layout."
        )
    elif action_type == "drill":
        base = (
            f"Question: apply {core}. "
            f"Answer: provide the final value and short working. "
            f"Pitfall: avoid skipping the key adjustment."
        )
    else:
        kw_text = " ".join(keywords)
        base = f"{kw_text} {core}".strip()
    if isinstance(qc, dict) and qc.get("require_rag_style_citation"):
        base = f"{base.rstrip()} Align facts with course notes using [S1] when citing.".strip()
    return base


def score_tutor_response(
    case: dict[str, Any],
    response: str,
    *,
    threshold: float = 0.75,
) -> dict[str, Any]:
    expected = case.get("expected", {})
    qc = expected.get("quality_checks") if isinstance(expected, dict) else {}
    must = _clean_phrase_list(expected.get("must_include", []))
    disallow = _clean_phrase_list(expected.get("disallow", []))
    action_type = str(case.get("action_type", "")).strip().lower()
    action_keywords = tuple(_clean_phrase_list(list(ACTION_KEYWORDS.get(action_type, ()))))
    text = _normalize_text(response)

    must_hits = [phrase for phrase in must if phrase in text]
    disallow_hits = [phrase for phrase in disallow if phrase in text]
    action_hits = [token for token in action_keywords if token in text]

    must_ratio = float(len(must_hits)) / float(max(1, len(must)))
    action_ratio = float(len(action_hits)) / float(max(1, len(action_keywords)))
    disallow_ratio = max(0.0, 1.0 - (float(len(disallow_hits)) / float(max(1, len(disallow)))))
    score = (0.70 * must_ratio) + (0.20 * action_ratio) + (0.10 * disallow_ratio)

    passed = bool(score >= float(threshold) and not disallow_hits and must_ratio >= (2.0 / 3.0))
    rag_citation_ok = True
    if isinstance(qc, dict) and qc.get("require_rag_style_citation"):
        rag_citation_ok = "[s" in text
        if not rag_citation_ok:
            passed = False
    return {
        "case_id": str(case.get("id", "")).strip(),
        "module_id": str(case.get("module_id", "")).strip(),
        "action_type": action_type,
        "score": float(max(0.0, min(1.0, score))),
        "passed": passed,
        "must_hit_count": int(len(must_hits)),
        "must_total": int(len(must)),
        "disallow_hit_count": int(len(disallow_hits)),
        "action_hit_count": int(len(action_hits)),
        "rag_citation_ok": bool(rag_citation_ok),
    }


def score_matrix(
    matrix: dict[str, Any],
    responses_by_id: dict[str, str],
    *,
    threshold: float = 0.75,
) -> dict[str, Any]:
    cases = matrix.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    rows: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id", "")).strip()
        response = str(responses_by_id.get(case_id, "") or "")
        rows.append(score_tutor_response(case, response, threshold=threshold))

    total = int(len(rows))
    pass_count = int(sum(1 for row in rows if bool(row.get("passed", False))))
    avg_score = 0.0
    if rows:
        avg_score = float(sum(float(row.get("score", 0.0) or 0.0) for row in rows)) / float(len(rows))
    disallow_violations = int(sum(1 for row in rows if int(row.get("disallow_hit_count", 0) or 0) > 0))
    return {
        "total": total,
        "pass_count": pass_count,
        "pass_rate": float(pass_count) / float(max(1, total)),
        "avg_score": float(avg_score),
        "disallow_violations": disallow_violations,
        "results": rows,
    }
