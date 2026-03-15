from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "run_tutor_quality_benchmark.py"
MATRIX = ROOT / "tests" / "tutor_quality" / "matrix_v1.json"
EXPECTED = ROOT / "tests" / "tutor_quality" / "expected_scores_v1.json"
GATES = ROOT / "tests" / "tutor_quality" / "gates_v1.json"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert isinstance(payload, dict)
    return payload


def test_runner_reference_mode_passes_default_gates(tmp_path: Path) -> None:
    report_path = tmp_path / "quality_report_pass.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "reference",
            "--matrix",
            str(MATRIX),
            "--expected",
            str(EXPECTED),
            "--report",
            str(report_path),
            "--min-pass-rate",
            "0.99",
            "--min-avg-score",
            "0.99",
            "--max-disallow-violations",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(report_path)
    assert report.get("status") == "pass"
    assert report.get("mode") == "reference"
    assert int(report.get("model_count", 0) or 0) == 1
    assert int(report.get("pass_models", 0) or 0) == 1


def test_runner_reference_mode_fails_with_impossible_gate(tmp_path: Path) -> None:
    report_path = tmp_path / "quality_report_fail.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "reference",
            "--matrix",
            str(MATRIX),
            "--expected",
            str(EXPECTED),
            "--report",
            str(report_path),
            "--min-avg-score",
            "1.01",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "runner should fail when gates are impossible"
    report = _read_json(report_path)
    assert report.get("status") == "fail"
    assert "No model passed quality gates" in str(report.get("reason", ""))


def test_runner_reference_mode_passes_with_gates_file(tmp_path: Path) -> None:
    report_path = tmp_path / "quality_report_gates_pass.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "reference",
            "--matrix",
            str(MATRIX),
            "--expected",
            str(EXPECTED),
            "--gates-file",
            str(GATES),
            "--report",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(report_path)
    assert report.get("status") == "pass"
    assert report.get("gate_profile_file") == str(GATES)
    gates = report.get("gates", {})
    assert isinstance(gates, dict)
    assert float(gates.get("min_pass_rate", 0.0) or 0.0) == 0.85
    assert float(gates.get("min_avg_score", 0.0) or 0.0) == 0.8


def test_runner_cli_gate_overrides_gates_file(tmp_path: Path) -> None:
    strict_gate_path = tmp_path / "strict_gates.json"
    strict_gate_path.write_text(
        json.dumps(
            {
                "version": 1,
                "gates": {
                    "min_avg_score": 1.01,
                },
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "quality_report_gates_override.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "reference",
            "--matrix",
            str(MATRIX),
            "--expected",
            str(EXPECTED),
            "--gates-file",
            str(strict_gate_path),
            "--min-avg-score",
            "0.99",
            "--report",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(report_path)
    assert report.get("status") == "pass"
    gates = report.get("gates", {})
    assert isinstance(gates, dict)
    assert float(gates.get("min_avg_score", 0.0) or 0.0) == 0.99
