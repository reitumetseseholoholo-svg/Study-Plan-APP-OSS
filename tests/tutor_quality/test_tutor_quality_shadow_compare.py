"""CLI shadow compare tool (Phase 5.3)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.tutor_quality.quality_scorer import build_reference_response

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "run_tutor_quality_shadow_compare.py"
MATRIX = ROOT / "tests" / "tutor_quality" / "matrix_v1.json"


def _load_matrix_cases() -> list[dict]:
    with MATRIX.open("r", encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases", [])
    assert isinstance(cases, list)
    return [c for c in cases if isinstance(c, dict)]


def test_shadow_compare_identical_maps_reports_zero_deltas(tmp_path: Path) -> None:
    responses: dict[str, str] = {}
    for case in _load_matrix_cases():
        cid = str(case.get("id", "") or "").strip()
        if cid:
            responses[cid] = build_reference_response(case)
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_a.write_text(json.dumps(responses, ensure_ascii=True), encoding="utf-8")
    path_b.write_text(json.dumps(responses, ensure_ascii=True), encoding="utf-8")
    report = tmp_path / "out.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--matrix",
            str(MATRIX),
            "--responses-a",
            str(path_a),
            "--responses-b",
            str(path_b),
            "--report",
            str(report),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert float(payload.get("delta_pass_rate", 1.0)) == 0.0
    assert float(payload.get("delta_avg_score", 1.0)) == 0.0
    assert payload.get("differing_cases") == []


def test_shadow_compare_detects_regression(tmp_path: Path) -> None:
    cases = _load_matrix_cases()
    assert cases
    first = cases[0]
    cid = str(first.get("id", "") or "").strip()
    assert cid
    good = build_reference_response(first)
    bad = "x"
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    path_a.write_text(json.dumps({cid: good}, ensure_ascii=True), encoding="utf-8")
    path_b.write_text(json.dumps({cid: bad}, ensure_ascii=True), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--matrix",
            str(MATRIX),
            "--responses-a",
            str(path_a),
            "--responses-b",
            str(path_b),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "Δ pass_rate" in proc.stdout or "pass_rate=" in proc.stdout
