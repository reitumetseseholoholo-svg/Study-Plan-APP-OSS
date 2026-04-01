#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_json_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_benchmark(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("ts_utc", "mode", "status", "models", "model_count", "pass_models", "gates"):
        if key not in report:
            errors.append(f"benchmark missing key: {key}")
    if str(report.get("status", "") or "") not in {"pass", "fail"}:
        errors.append("benchmark status must be pass|fail")
    models = report.get("models", [])
    if not isinstance(models, list):
        errors.append("benchmark models must be list")
        models = []
    model_count = int(report.get("model_count", 0) or 0)
    pass_models = int(report.get("pass_models", 0) or 0)
    if model_count != len(models):
        errors.append("benchmark model_count mismatch")
    if pass_models < 0 or pass_models > model_count:
        errors.append("benchmark pass_models out of range")
    gates = report.get("gates", {})
    if not isinstance(gates, dict):
        errors.append("benchmark gates must be object")
    else:
        for key in ("threshold", "min_pass_rate", "min_avg_score", "max_disallow_violations"):
            if key not in gates:
                errors.append(f"benchmark gates missing key: {key}")
    for idx, row in enumerate(models):
        if not isinstance(row, dict):
            errors.append(f"benchmark models[{idx}] must be object")
            continue
        if not str(row.get("model", "") or "").strip():
            errors.append(f"benchmark models[{idx}] missing model")
        summary = row.get("summary", {})
        if not isinstance(summary, dict):
            errors.append(f"benchmark models[{idx}] summary must be object")
            continue
        for key in ("pass_rate", "avg_score", "disallow_violations"):
            if key not in summary:
                errors.append(f"benchmark models[{idx}] summary missing {key}")
    return errors


def _validate_compare(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("ts_utc", "status", "models", "compared_model_count", "thresholds"):
        if key not in report:
            errors.append(f"compare missing key: {key}")
    if str(report.get("status", "") or "") not in {"pass", "fail"}:
        errors.append("compare status must be pass|fail")
    models = report.get("models", [])
    if not isinstance(models, list):
        errors.append("compare models must be list")
        models = []
    compared_count = int(report.get("compared_model_count", 0) or 0)
    if compared_count != len(models):
        errors.append("compare compared_model_count mismatch")
    thresholds = report.get("thresholds", {})
    if not isinstance(thresholds, dict):
        errors.append("compare thresholds must be object")
    else:
        for key in ("max_pass_rate_drop", "max_avg_score_drop", "max_disallow_increase"):
            if key not in thresholds:
                errors.append(f"compare thresholds missing key: {key}")
            elif not _is_number(thresholds.get(key)):
                errors.append(f"compare thresholds {key} must be number")
    for idx, row in enumerate(models):
        if not isinstance(row, dict):
            errors.append(f"compare models[{idx}] must be object")
            continue
        if str(row.get("status", "") or "") not in {"pass", "fail"}:
            errors.append(f"compare models[{idx}] status must be pass|fail")
        delta = row.get("delta", {})
        if not isinstance(delta, dict):
            errors.append(f"compare models[{idx}] delta must be object")
            continue
        for key in ("pass_rate_drop", "avg_score_drop", "disallow_increase"):
            if key not in delta:
                errors.append(f"compare models[{idx}] delta missing {key}")
    return errors


def _validate_trend(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("ts_utc", "status", "runs", "window_count", "thresholds", "metrics"):
        if key not in report:
            errors.append(f"trend missing key: {key}")
    if str(report.get("status", "") or "") not in {"pass", "fail"}:
        errors.append("trend status must be pass|fail")
    runs = report.get("runs", [])
    if not isinstance(runs, list):
        errors.append("trend runs must be list")
        runs = []
    window_count = int(report.get("window_count", 0) or 0)
    if window_count != len(runs):
        errors.append("trend window_count mismatch")
    thresholds = report.get("thresholds", {})
    metrics = report.get("metrics", {})
    if not isinstance(thresholds, dict):
        errors.append("trend thresholds must be object")
    if not isinstance(metrics, dict):
        errors.append("trend metrics must be object")
    else:
        for key in ("failed_runs", "regression_events", "latest_pass_rate", "latest_avg_score"):
            if key not in metrics:
                errors.append(f"trend metrics missing key: {key}")
    for idx, row in enumerate(runs):
        if not isinstance(row, dict):
            errors.append(f"trend runs[{idx}] must be object")
            continue
        for key in ("file", "report_status", "pass_rate", "avg_score", "disallow_violations"):
            if key not in row:
                errors.append(f"trend runs[{idx}] missing {key}")
    return errors


def run() -> int:
    parser = argparse.ArgumentParser(description="Validate tutor-quality benchmark/compare/trend JSON artifacts.")
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--compare", required=True)
    parser.add_argument("--trend", required=True)
    parser.add_argument("--report", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_VALIDATE_REPORT", "tutor_quality_validate_report.json"))
    args = parser.parse_args()

    benchmark_path = os.path.abspath(os.path.expanduser(str(args.benchmark)))
    compare_path = os.path.abspath(os.path.expanduser(str(args.compare)))
    trend_path = os.path.abspath(os.path.expanduser(str(args.trend)))
    out_path = os.path.abspath(os.path.expanduser(str(args.report)))

    benchmark = _load_json_file(benchmark_path)
    compare = _load_json_file(compare_path)
    trend = _load_json_file(trend_path)

    benchmark_errors = _validate_benchmark(benchmark)
    compare_errors = _validate_compare(compare)
    trend_errors = _validate_trend(trend)
    all_errors = benchmark_errors + compare_errors + trend_errors

    status = "pass" if not all_errors else "fail"
    out = {
        "status": status,
        "benchmark_file": benchmark_path,
        "compare_file": compare_path,
        "trend_file": trend_path,
        "error_count": int(len(all_errors)),
        "errors": all_errors[:200],
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=True)
    print(json.dumps({"status": status, "error_count": int(len(all_errors)), "report": out_path}, ensure_ascii=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(run())
