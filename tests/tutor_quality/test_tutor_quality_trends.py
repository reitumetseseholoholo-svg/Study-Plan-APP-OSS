from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
TREND_SCRIPT = ROOT / "tools" / "analyze_tutor_quality_trends.py"
BASELINE_REPORT = ROOT / "tests" / "tutor_quality" / "reference_report_v1.json"
POLICY_FILE = ROOT / "tests" / "tutor_quality" / "policy_profiles_v1.json"


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert isinstance(payload, dict)
    return payload


def _write_report(path: Path, *, ts_utc: str, pass_rate: float, avg_score: float, status: str = "pass", model: str = "reference_baseline") -> None:
    payload = _read_json(BASELINE_REPORT)
    payload["ts_utc"] = ts_utc
    payload["status"] = status
    payload["best_model"] = model
    payload["models"][0]["model"] = model
    payload["models"][0]["summary"]["pass_rate"] = float(pass_rate)
    payload["models"][0]["summary"]["avg_score"] = float(avg_score)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def test_trend_passes_with_stable_window(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.json"
    r2 = tmp_path / "r2.json"
    _write_report(r1, ts_utc="2026-03-01T00:00:00Z", pass_rate=1.0, avg_score=1.0)
    _write_report(r2, ts_utc="2026-03-02T00:00:00Z", pass_rate=1.0, avg_score=1.0)
    out = tmp_path / "trend_pass.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(TREND_SCRIPT),
            "--reports",
            f"{r1},{r2}",
            "--model",
            "reference_baseline",
            "--window-size",
            "5",
            "--max-failed-runs",
            "0",
            "--max-regression-events",
            "0",
            "--max-pass-rate-drop",
            "0",
            "--max-avg-score-drop",
            "0",
            "--report",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(out)
    assert report.get("status") == "pass"
    assert int(report.get("window_count", 0) or 0) == 2


def test_trend_fails_on_regression_event(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.json"
    r2 = tmp_path / "r2.json"
    _write_report(r1, ts_utc="2026-03-01T00:00:00Z", pass_rate=1.0, avg_score=1.0)
    _write_report(r2, ts_utc="2026-03-02T00:00:00Z", pass_rate=1.0, avg_score=0.9)
    out = tmp_path / "trend_fail_regression.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(TREND_SCRIPT),
            "--reports",
            f"{r1},{r2}",
            "--model",
            "reference_baseline",
            "--max-regression-events",
            "0",
            "--max-avg-score-drop",
            "0.05",
            "--report",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "trend gate should fail on excessive drop"
    report = _read_json(out)
    assert report.get("status") == "fail"
    assert "regression_events" in str(report.get("reason", ""))


def test_trend_fails_when_latest_below_floor(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.json"
    r2 = tmp_path / "r2.json"
    _write_report(r1, ts_utc="2026-03-01T00:00:00Z", pass_rate=0.95, avg_score=0.95)
    _write_report(r2, ts_utc="2026-03-02T00:00:00Z", pass_rate=0.7, avg_score=0.7)
    out = tmp_path / "trend_fail_floor.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(TREND_SCRIPT),
            "--reports",
            f"{r1},{r2}",
            "--model",
            "reference_baseline",
            "--min-latest-pass-rate",
            "0.85",
            "--min-latest-avg-score",
            "0.8",
            "--report",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "trend gate should fail when latest metrics fall below minimum"
    report = _read_json(out)
    assert report.get("status") == "fail"
    assert "latest_pass_rate" in str(report.get("reason", "")) or "latest_avg_score" in str(report.get("reason", ""))


def test_trend_policy_profile_applies_thresholds(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.json"
    r2 = tmp_path / "r2.json"
    _write_report(r1, ts_utc="2026-03-01T00:00:00Z", pass_rate=1.0, avg_score=1.0)
    _write_report(r2, ts_utc="2026-03-02T00:00:00Z", pass_rate=1.0, avg_score=0.94)
    out = tmp_path / "trend_policy_fail.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(TREND_SCRIPT),
            "--reports",
            f"{r1},{r2}",
            "--model",
            "reference_baseline",
            "--policy-file",
            str(POLICY_FILE),
            "--policy",
            "strict_release",
            "--report",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, "strict_release policy should reject any regression"
    report = _read_json(out)
    assert report.get("status") == "fail"
    assert report.get("policy_name") == "strict_release"


def test_trend_cli_overrides_policy_thresholds(tmp_path: Path) -> None:
    r1 = tmp_path / "r1.json"
    r2 = tmp_path / "r2.json"
    _write_report(r1, ts_utc="2026-03-01T00:00:00Z", pass_rate=1.0, avg_score=1.0)
    _write_report(r2, ts_utc="2026-03-02T00:00:00Z", pass_rate=1.0, avg_score=0.94)
    out = tmp_path / "trend_policy_override_pass.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(TREND_SCRIPT),
            "--reports",
            f"{r1},{r2}",
            "--model",
            "reference_baseline",
            "--policy-file",
            str(POLICY_FILE),
            "--policy",
            "strict_release",
            "--max-avg-score-drop",
            "0.1",
            "--report",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = _read_json(out)
    assert report.get("status") == "pass"
