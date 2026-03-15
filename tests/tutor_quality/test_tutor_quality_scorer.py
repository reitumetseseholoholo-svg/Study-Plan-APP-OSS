from __future__ import annotations

import json
from pathlib import Path

from tests.tutor_quality.quality_scorer import (
    build_reference_response,
    score_matrix,
    score_tutor_response,
)


HERE = Path(__file__).resolve().parent
MATRIX_PATH = HERE / "matrix_v1.json"
EXPECTED_PATH = HERE / "expected_scores_v1.json"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict), f"{path.name} must be a JSON object"
    return data


def _round4(value: float) -> float:
    return round(float(value or 0.0), 4)


def test_reference_responses_match_expected_fixture_scores() -> None:
    matrix = _load_json(MATRIX_PATH)
    expected = _load_json(EXPECTED_PATH)
    threshold = float(expected.get("threshold", 0.75) or 0.75)
    per_case = expected.get("per_case", {})
    assert isinstance(per_case, dict) and per_case

    cases = matrix.get("cases", [])
    assert isinstance(cases, list) and cases
    for case in cases:
        assert isinstance(case, dict)
        case_id = str(case.get("id", "")).strip()
        assert case_id in per_case, f"missing expected fixture row for {case_id}"
        response = build_reference_response(case)
        row = score_tutor_response(case, response, threshold=threshold)
        expected_row = per_case[case_id]
        assert _round4(row["score"]) == _round4(expected_row["score"]), f"score drift for {case_id}"
        assert bool(row["passed"]) is bool(expected_row["passed"]), f"pass drift for {case_id}"


def test_matrix_summary_matches_expected_fixture() -> None:
    matrix = _load_json(MATRIX_PATH)
    expected = _load_json(EXPECTED_PATH)
    threshold = float(expected.get("threshold", 0.75) or 0.75)
    cases = matrix.get("cases", [])
    assert isinstance(cases, list)
    responses_by_id: dict[str, str] = {}
    for case in cases:
        assert isinstance(case, dict)
        case_id = str(case.get("id", "")).strip()
        responses_by_id[case_id] = build_reference_response(case)

    result = score_matrix(matrix, responses_by_id, threshold=threshold)
    summary_expected = expected.get("summary", {})
    assert isinstance(summary_expected, dict)
    assert int(result["total"]) == int(summary_expected["total"])
    assert int(result["pass_count"]) == int(summary_expected["pass_count"])
    assert _round4(result["pass_rate"]) == _round4(summary_expected["pass_rate"])
    assert _round4(result["avg_score"]) == _round4(summary_expected["avg_score"])
    assert int(result["disallow_violations"]) == int(summary_expected["disallow_violations"])


def test_disallow_phrase_forces_failure() -> None:
    matrix = _load_json(MATRIX_PATH)
    cases = matrix.get("cases", [])
    assert isinstance(cases, list) and cases
    case = next(row for row in cases if isinstance(row, dict) and row.get("id") == "f9_explain_wacc")
    assert isinstance(case, dict)
    threshold = 0.75
    poisoned = "This is guaranteed pass advice with no valid exam grounding."
    scored = score_tutor_response(case, poisoned, threshold=threshold)
    assert scored["passed"] is False
    assert int(scored["disallow_hit_count"]) >= 1
