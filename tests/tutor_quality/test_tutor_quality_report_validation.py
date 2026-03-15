from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
VALIDATE_SCRIPT = ROOT / "tools" / "validate_tutor_quality_reports.py"
BASELINE_REPORT = ROOT / "tests" / "tutor_quality" / "reference_report_v1.json"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def _make_compare_payload() -> dict:
    return {
        "ts_utc": "2026-03-08T00:00:00Z",
        "status": "pass",
        "models": [
            {
                "model": "reference_baseline",
                "status": "pass",
                "delta": {
                    "pass_rate_drop": 0.0,
                    "avg_score_drop": 0.0,
                    "disallow_increase": 0,
                },
            }
        ],
        "compared_model_count": 1,
        "thresholds": {
            "max_pass_rate_drop": 0.0,
            "max_avg_score_drop": 0.0,
            "max_disallow_increase": 0,
        },
    }


def _make_trend_payload() -> dict:
    return {
        "ts_utc": "2026-03-08T00:00:00Z",
        "status": "pass",
        "runs": [
            {
                "file": "tests/tutor_quality/reference_report_v1.json",
                "report_status": "pass",
                "pass_rate": 1.0,
                "avg_score": 1.0,
                "disallow_violations": 0,
            }
        ],
        "window_count": 1,
        "thresholds": {
            "max_failed_runs": 0,
            "max_regression_events": 0,
            "max_pass_rate_drop": 0.0,
            "max_avg_score_drop": 0.0,
            "max_disallow_increase": 0,
            "min_latest_pass_rate": 0.85,
            "min_latest_avg_score": 0.8,
        },
        "metrics": {
            "failed_runs": 0,
            "regression_events": 0,
            "latest_pass_rate": 1.0,
            "latest_avg_score": 1.0,
        },
    }


def test_validate_reports_passes_with_valid_triplet(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    compare_path = tmp_path / "compare.json"
    trend_path = tmp_path / "trend.json"
    out_path = tmp_path / "validate_report.json"
    _write_json(benchmark_path, _read_json(BASELINE_REPORT))
    _write_json(compare_path, _make_compare_payload())
    _write_json(trend_path, _make_trend_payload())

    proc = subprocess.run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--benchmark",
            str(benchmark_path),
            "--compare",
            str(compare_path),
            "--trend",
            str(trend_path),
            "--report",
            str(out_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(out_path)
    assert report.get("status") == "pass"
    assert int(report.get("error_count", 0) or 0) == 0


def test_validate_reports_fails_on_missing_benchmark_key(tmp_path: Path) -> None:
    benchmark = _read_json(BASELINE_REPORT)
    benchmark.pop("models", None)
    benchmark_path = tmp_path / "benchmark_missing.json"
    compare_path = tmp_path / "compare.json"
    trend_path = tmp_path / "trend.json"
    out_path = tmp_path / "validate_report_fail.json"
    _write_json(benchmark_path, benchmark)
    _write_json(compare_path, _make_compare_payload())
    _write_json(trend_path, _make_trend_payload())

    proc = subprocess.run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--benchmark",
            str(benchmark_path),
            "--compare",
            str(compare_path),
            "--trend",
            str(trend_path),
            "--report",
            str(out_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "validator should fail when required key is missing"
    report = _read_json(out_path)
    assert report.get("status") == "fail"
    assert "benchmark missing key: models" in "\n".join(list(report.get("errors", []) or []))


def test_validate_reports_fails_on_count_mismatch(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    compare = _make_compare_payload()
    compare["compared_model_count"] = 2
    compare_path = tmp_path / "compare_bad_count.json"
    trend = _make_trend_payload()
    trend["window_count"] = 2
    trend_path = tmp_path / "trend_bad_count.json"
    out_path = tmp_path / "validate_report_counts_fail.json"
    _write_json(benchmark_path, _read_json(BASELINE_REPORT))
    _write_json(compare_path, compare)
    _write_json(trend_path, trend)

    proc = subprocess.run(
        [
            sys.executable,
            str(VALIDATE_SCRIPT),
            "--benchmark",
            str(benchmark_path),
            "--compare",
            str(compare_path),
            "--trend",
            str(trend_path),
            "--report",
            str(out_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "validator should fail on invariant mismatch"
    report = _read_json(out_path)
    assert report.get("status") == "fail"
    err_blob = "\n".join(list(report.get("errors", []) or []))
    assert "compare compared_model_count mismatch" in err_blob
    assert "trend window_count mismatch" in err_blob
