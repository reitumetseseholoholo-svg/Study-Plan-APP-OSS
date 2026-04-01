from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
PIPELINE_SCRIPT = ROOT / "tools" / "run_tutor_quality_pipeline.py"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert isinstance(payload, dict)
    return payload


def test_pipeline_reference_mode_passes(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(PIPELINE_SCRIPT),
            "--mode",
            "reference",
            "--policy",
            "balanced_main",
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    pipeline = _read_json(tmp_path / "tutor_quality_pipeline_report.json")
    assert pipeline.get("status") == "pass"
    steps = list(pipeline.get("steps", []) or [])
    assert len(steps) == 4
    assert all(str(step.get("status", "")) == "pass" for step in steps)


def test_pipeline_fails_if_benchmark_gate_is_impossible(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(PIPELINE_SCRIPT),
            "--mode",
            "reference",
            "--policy",
            "balanced_main",
            "--benchmark-args",
            "--min-avg-score 1.01",
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "pipeline should fail when benchmark step fails"
    pipeline = _read_json(tmp_path / "tutor_quality_pipeline_report.json")
    assert pipeline.get("status") == "fail"
    steps = list(pipeline.get("steps", []) or [])
    assert len(steps) >= 1
    assert str(steps[0].get("name", "")) == "benchmark"
    assert str(steps[0].get("status", "")) == "fail"
