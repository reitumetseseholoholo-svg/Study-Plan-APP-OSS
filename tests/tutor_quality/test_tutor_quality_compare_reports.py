from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
COMPARE_SCRIPT = ROOT / "tools" / "compare_tutor_quality_reports.py"
BASELINE_REPORT = ROOT / "tests" / "tutor_quality" / "reference_report_v1.json"
POLICY_FILE = ROOT / "tests" / "tutor_quality" / "policy_profiles_v1.json"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def test_compare_reports_passes_when_candidate_matches_baseline(tmp_path: Path) -> None:
    compare_report = tmp_path / "compare_report_pass.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(COMPARE_SCRIPT),
            "--baseline",
            str(BASELINE_REPORT),
            "--candidate",
            str(BASELINE_REPORT),
            "--model",
            "reference_baseline",
            "--max-pass-rate-drop",
            "0",
            "--max-avg-score-drop",
            "0",
            "--max-disallow-increase",
            "0",
            "--report",
            str(compare_report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(compare_report)
    assert report.get("status") == "pass"
    assert int(report.get("compared_model_count", 0) or 0) == 1


def test_compare_reports_fails_on_avg_score_regression(tmp_path: Path) -> None:
    candidate = _read_json(BASELINE_REPORT)
    candidate["models"][0]["summary"]["avg_score"] = 0.9
    candidate_path = tmp_path / "candidate_drop.json"
    _write_json(candidate_path, candidate)
    compare_report = tmp_path / "compare_report_fail.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(COMPARE_SCRIPT),
            "--baseline",
            str(BASELINE_REPORT),
            "--candidate",
            str(candidate_path),
            "--model",
            "reference_baseline",
            "--max-avg-score-drop",
            "0.05",
            "--report",
            str(compare_report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "comparison should fail on excessive avg_score drop"
    report = _read_json(compare_report)
    assert report.get("status") == "fail"
    assert "avg_score drop" in str(report.get("reason", ""))


def test_compare_reports_honors_tolerance_thresholds(tmp_path: Path) -> None:
    candidate = _read_json(BASELINE_REPORT)
    candidate["models"][0]["summary"]["pass_rate"] = 0.97
    candidate["models"][0]["summary"]["avg_score"] = 0.96
    candidate_path = tmp_path / "candidate_small_drop.json"
    _write_json(candidate_path, candidate)
    compare_report = tmp_path / "compare_report_tolerated.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(COMPARE_SCRIPT),
            "--baseline",
            str(BASELINE_REPORT),
            "--candidate",
            str(candidate_path),
            "--model",
            "reference_baseline",
            "--max-pass-rate-drop",
            "0.05",
            "--max-avg-score-drop",
            "0.05",
            "--report",
            str(compare_report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(compare_report)
    assert report.get("status") == "pass"


def test_compare_reports_fail_when_named_model_missing(tmp_path: Path) -> None:
    candidate = _read_json(BASELINE_REPORT)
    candidate["models"][0]["model"] = "other_model"
    candidate_path = tmp_path / "candidate_other_model.json"
    _write_json(candidate_path, candidate)
    compare_report = tmp_path / "compare_report_missing_model.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(COMPARE_SCRIPT),
            "--baseline",
            str(BASELINE_REPORT),
            "--candidate",
            str(candidate_path),
            "--model",
            "reference_baseline",
            "--report",
            str(compare_report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "comparison should fail when named model is absent"
    report = _read_json(compare_report)
    assert report.get("status") == "fail"
    assert "missing model" in str(report.get("reason", "")).lower()


def test_compare_reports_policy_profile_applies_thresholds(tmp_path: Path) -> None:
    candidate = _read_json(BASELINE_REPORT)
    candidate["models"][0]["summary"]["avg_score"] = 0.95
    candidate_path = tmp_path / "candidate_policy_drop.json"
    _write_json(candidate_path, candidate)
    compare_report = tmp_path / "compare_report_policy_fail.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(COMPARE_SCRIPT),
            "--baseline",
            str(BASELINE_REPORT),
            "--candidate",
            str(candidate_path),
            "--model",
            "reference_baseline",
            "--policy-file",
            str(POLICY_FILE),
            "--policy",
            "strict_release",
            "--report",
            str(compare_report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "strict_release policy should reject score drop"
    report = _read_json(compare_report)
    assert report.get("status") == "fail"
    assert report.get("policy_name") == "strict_release"


def test_compare_reports_cli_overrides_policy_thresholds(tmp_path: Path) -> None:
    candidate = _read_json(BASELINE_REPORT)
    candidate["models"][0]["summary"]["avg_score"] = 0.95
    candidate_path = tmp_path / "candidate_policy_override.json"
    _write_json(candidate_path, candidate)
    compare_report = tmp_path / "compare_report_policy_override_pass.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(COMPARE_SCRIPT),
            "--baseline",
            str(BASELINE_REPORT),
            "--candidate",
            str(candidate_path),
            "--model",
            "reference_baseline",
            "--policy-file",
            str(POLICY_FILE),
            "--policy",
            "strict_release",
            "--max-avg-score-drop",
            "0.1",
            "--report",
            str(compare_report),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(compare_report)
    assert report.get("status") == "pass"
