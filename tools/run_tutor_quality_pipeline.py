#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run_step(name: str, cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return {
        "name": name,
        "status": "pass" if proc.returncode == 0 else "fail",
        "returncode": int(proc.returncode),
        "cmd": cmd,
        "stdout": str(proc.stdout or "")[-8000:],
        "stderr": str(proc.stderr or "")[-8000:],
    }


def _split_args(blob: str) -> list[str]:
    text = str(blob or "").strip()
    if not text:
        return []
    return [str(x) for x in shlex.split(text) if str(x).strip()]


def run() -> int:
    parser = argparse.ArgumentParser(description="Run full tutor-quality pipeline (benchmark -> compare -> trend -> validate).")
    parser.add_argument("--mode", choices=("reference", "ollama"), default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_MODE", "reference"))
    parser.add_argument("--matrix", default=str(ROOT / "tests" / "tutor_quality" / "matrix_v1.json"))
    parser.add_argument("--expected", default=str(ROOT / "tests" / "tutor_quality" / "expected_scores_v1.json"))
    parser.add_argument("--gates-file", default=str(ROOT / "tests" / "tutor_quality" / "gates_v1.json"))
    parser.add_argument("--baseline-report", default=str(ROOT / "tests" / "tutor_quality" / "reference_report_v1.json"))
    parser.add_argument("--policy-file", default=str(ROOT / "tests" / "tutor_quality" / "policy_profiles_v1.json"))
    parser.add_argument("--policy", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_POLICY", "balanced_main"))
    parser.add_argument("--model", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_MODEL", "reference_baseline"))
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--benchmark-report-name", default="tutor_quality_report.json")
    parser.add_argument("--compare-report-name", default="tutor_quality_compare_report.json")
    parser.add_argument("--trend-report-name", default="tutor_quality_trend_report.json")
    parser.add_argument("--validate-report-name", default="tutor_quality_validate_report.json")
    parser.add_argument("--pipeline-report-name", default="tutor_quality_pipeline_report.json")
    parser.add_argument("--benchmark-args", default="")
    parser.add_argument("--compare-args", default="")
    parser.add_argument("--trend-args", default="")
    parser.add_argument("--validate-args", default="")
    args = parser.parse_args()

    out_dir = os.path.abspath(os.path.expanduser(str(args.output_dir or ".")))
    os.makedirs(out_dir, exist_ok=True)

    benchmark_report = os.path.join(out_dir, str(args.benchmark_report_name or "tutor_quality_report.json"))
    compare_report = os.path.join(out_dir, str(args.compare_report_name or "tutor_quality_compare_report.json"))
    trend_report = os.path.join(out_dir, str(args.trend_report_name or "tutor_quality_trend_report.json"))
    validate_report = os.path.join(out_dir, str(args.validate_report_name or "tutor_quality_validate_report.json"))
    pipeline_report = os.path.join(out_dir, str(args.pipeline_report_name or "tutor_quality_pipeline_report.json"))

    benchmark_cmd = [
        sys.executable,
        str(ROOT / "tools" / "run_tutor_quality_benchmark.py"),
        "--mode",
        str(args.mode or "reference"),
        "--matrix",
        os.path.abspath(os.path.expanduser(str(args.matrix))),
        "--expected",
        os.path.abspath(os.path.expanduser(str(args.expected))),
        "--gates-file",
        os.path.abspath(os.path.expanduser(str(args.gates_file))),
        "--report",
        benchmark_report,
    ] + _split_args(str(args.benchmark_args or ""))

    compare_cmd = [
        sys.executable,
        str(ROOT / "tools" / "compare_tutor_quality_reports.py"),
        "--baseline",
        os.path.abspath(os.path.expanduser(str(args.baseline_report))),
        "--candidate",
        benchmark_report,
        "--model",
        str(args.model or "reference_baseline"),
        "--policy-file",
        os.path.abspath(os.path.expanduser(str(args.policy_file))),
        "--policy",
        str(args.policy or "balanced_main"),
        "--report",
        compare_report,
    ] + _split_args(str(args.compare_args or ""))

    trend_cmd = [
        sys.executable,
        str(ROOT / "tools" / "analyze_tutor_quality_trends.py"),
        "--reports",
        f"{os.path.abspath(os.path.expanduser(str(args.baseline_report)))},{benchmark_report}",
        "--model",
        str(args.model or "reference_baseline"),
        "--policy-file",
        os.path.abspath(os.path.expanduser(str(args.policy_file))),
        "--policy",
        str(args.policy or "balanced_main"),
        "--report",
        trend_report,
    ] + _split_args(str(args.trend_args or ""))

    validate_cmd = [
        sys.executable,
        str(ROOT / "tools" / "validate_tutor_quality_reports.py"),
        "--benchmark",
        benchmark_report,
        "--compare",
        compare_report,
        "--trend",
        trend_report,
        "--report",
        validate_report,
    ] + _split_args(str(args.validate_args or ""))

    steps: list[dict[str, Any]] = []
    for name, cmd in (
        ("benchmark", benchmark_cmd),
        ("compare", compare_cmd),
        ("trend", trend_cmd),
        ("validate", validate_cmd),
    ):
        result = _run_step(name, cmd)
        steps.append(result)
        if result.get("status") != "pass":
            break

    status = "pass" if steps and all(str(s.get("status", "")) == "pass" for s in steps) and len(steps) == 4 else "fail"
    out = {
        "status": status,
        "mode": str(args.mode or "reference"),
        "policy": str(args.policy or ""),
        "model": str(args.model or ""),
        "output_dir": out_dir,
        "reports": {
            "benchmark": benchmark_report,
            "compare": compare_report,
            "trend": trend_report,
            "validate": validate_report,
        },
        "steps": steps,
    }

    with open(pipeline_report, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=True)

    print(json.dumps({"status": status, "steps": len(steps), "report": pipeline_report}, ensure_ascii=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(run())
