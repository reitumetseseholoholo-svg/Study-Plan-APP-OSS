#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EPS = 1e-9


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _load_json_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _load_policy_block(path: str, policy_name: str, section: str) -> dict[str, Any]:
    payload = _load_json_file(path)
    profiles = payload.get("profiles", payload)
    if not isinstance(profiles, dict):
        raise ValueError(f"Policy file {path} is not a valid object")
    chosen = profiles.get(policy_name, {})
    if not isinstance(chosen, dict):
        return {}
    block = chosen.get(section, chosen)
    if not isinstance(block, dict):
        return {}
    return dict(block)


def _parse_ts(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return float(dt.datetime.fromisoformat(text).timestamp())
    except Exception:
        return 0.0


def _model_summary_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    models = report.get("models", [])
    if not isinstance(models, list):
        return out
    for row in models:
        if not isinstance(row, dict):
            continue
        name = str(row.get("model", "") or "").strip()
        summary = row.get("summary", {})
        if not name or not isinstance(summary, dict):
            continue
        out[name] = summary
    return out


def _collect_report_paths(reports_csv: str, reports_glob: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in str(reports_csv or "").split(","):
        path = os.path.abspath(os.path.expanduser(str(part or "").strip()))
        if not path:
            continue
        if path in seen:
            continue
        if os.path.isfile(path):
            seen.add(path)
            out.append(path)
    if str(reports_glob or "").strip():
        for match in sorted(glob.glob(str(reports_glob), recursive=True)):
            path = os.path.abspath(os.path.expanduser(str(match or "").strip()))
            if path and os.path.isfile(path) and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def run() -> int:
    parser = argparse.ArgumentParser(description="Analyze tutor-quality trend over multiple benchmark reports.")
    parser.add_argument("--reports", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_TREND_REPORTS", ""))
    parser.add_argument("--reports-glob", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_TREND_GLOB", ""))
    parser.add_argument("--model", default=None)
    parser.add_argument("--policy-file", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_POLICY_FILE", ""))
    parser.add_argument("--policy", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_POLICY", ""))
    parser.add_argument("--window-size", type=int, default=None)
    parser.add_argument("--max-failed-runs", type=int, default=None)
    parser.add_argument("--max-regression-events", type=int, default=None)
    parser.add_argument("--max-pass-rate-drop", type=float, default=None)
    parser.add_argument("--max-avg-score-drop", type=float, default=None)
    parser.add_argument("--max-disallow-increase", type=int, default=None)
    parser.add_argument("--min-latest-pass-rate", type=float, default=None)
    parser.add_argument("--min-latest-avg-score", type=float, default=None)
    parser.add_argument("--allow-empty", type=int, default=None)
    parser.add_argument("--report", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_TREND_REPORT", "tutor_quality_trend_report.json"))
    args = parser.parse_args()

    policy_file = os.path.abspath(os.path.expanduser(str(args.policy_file or ""))) if str(args.policy_file or "").strip() else ""
    policy_name = str(args.policy or "").strip()
    policy_block: dict[str, Any] = {}
    if policy_file and policy_name:
        policy_block = _load_policy_block(policy_file, policy_name, "trend")

    model = str(os.environ.get("STUDYPLAN_TUTOR_QUALITY_TREND_MODEL", "reference_baseline") or "reference_baseline").strip()
    if "model" in policy_block:
        model = str(policy_block.get("model", model) or model).strip() or model
    if args.model is not None:
        model = str(args.model or "").strip() or model

    window_size = _env_int("STUDYPLAN_TUTOR_QUALITY_TREND_WINDOW", 5)
    max_failed_runs = _env_int("STUDYPLAN_TUTOR_QUALITY_TREND_MAX_FAILED", 0)
    max_regression_events = _env_int("STUDYPLAN_TUTOR_QUALITY_TREND_MAX_REGRESSIONS", 0)
    max_pass_drop = _env_float("STUDYPLAN_TUTOR_QUALITY_TREND_MAX_PASS_DROP", 0.02)
    max_avg_drop = _env_float("STUDYPLAN_TUTOR_QUALITY_TREND_MAX_AVG_DROP", 0.03)
    max_disallow_increase = _env_int("STUDYPLAN_TUTOR_QUALITY_TREND_MAX_DISALLOW_INCREASE", 0)
    min_latest_pass = _env_float("STUDYPLAN_TUTOR_QUALITY_TREND_MIN_PASS_RATE", 0.85)
    min_latest_avg = _env_float("STUDYPLAN_TUTOR_QUALITY_TREND_MIN_AVG_SCORE", 0.80)
    allow_empty = _env_int("STUDYPLAN_TUTOR_QUALITY_TREND_ALLOW_EMPTY", 0)
    if "window_size" in policy_block:
        window_size = _coerce_int(policy_block.get("window_size"))
    if "max_failed_runs" in policy_block:
        max_failed_runs = _coerce_int(policy_block.get("max_failed_runs"))
    if "max_regression_events" in policy_block:
        max_regression_events = _coerce_int(policy_block.get("max_regression_events"))
    if "max_pass_rate_drop" in policy_block:
        max_pass_drop = _coerce_float(policy_block.get("max_pass_rate_drop"))
    if "max_avg_score_drop" in policy_block:
        max_avg_drop = _coerce_float(policy_block.get("max_avg_score_drop"))
    if "max_disallow_increase" in policy_block:
        max_disallow_increase = _coerce_int(policy_block.get("max_disallow_increase"))
    if "min_latest_pass_rate" in policy_block:
        min_latest_pass = _coerce_float(policy_block.get("min_latest_pass_rate"))
    if "min_latest_avg_score" in policy_block:
        min_latest_avg = _coerce_float(policy_block.get("min_latest_avg_score"))
    if "allow_empty" in policy_block:
        allow_empty = _coerce_int(policy_block.get("allow_empty"))
    if args.window_size is not None:
        window_size = int(args.window_size)
    if args.max_failed_runs is not None:
        max_failed_runs = int(args.max_failed_runs)
    if args.max_regression_events is not None:
        max_regression_events = int(args.max_regression_events)
    if args.max_pass_rate_drop is not None:
        max_pass_drop = float(args.max_pass_rate_drop)
    if args.max_avg_score_drop is not None:
        max_avg_drop = float(args.max_avg_score_drop)
    if args.max_disallow_increase is not None:
        max_disallow_increase = int(args.max_disallow_increase)
    if args.min_latest_pass_rate is not None:
        min_latest_pass = float(args.min_latest_pass_rate)
    if args.min_latest_avg_score is not None:
        min_latest_avg = float(args.min_latest_avg_score)
    if args.allow_empty is not None:
        allow_empty = int(args.allow_empty)

    paths = _collect_report_paths(str(args.reports or ""), str(args.reports_glob or ""))
    rows: list[dict[str, Any]] = []
    for path in paths:
        payload = _load_json_file(path)
        ts = _parse_ts(str(payload.get("ts_utc", "") or ""))
        if ts <= 0.0:
            try:
                ts = float(os.path.getmtime(path))
            except Exception:
                ts = 0.0
        summary_map = _model_summary_map(payload)
        summary = summary_map.get(model, {})
        has_model = bool(summary)
        rows.append(
            {
                "file": path,
                "ts": ts,
                "ts_utc": str(payload.get("ts_utc", "") or ""),
                "report_status": str(payload.get("status", "") or ""),
                "has_model": has_model,
                "pass_rate": _coerce_float(summary.get("pass_rate")) if has_model else 0.0,
                "avg_score": _coerce_float(summary.get("avg_score")) if has_model else 0.0,
                "disallow_violations": _coerce_int(summary.get("disallow_violations")) if has_model else 0,
            }
        )
    rows.sort(key=lambda item: float(item.get("ts", 0.0) or 0.0))
    window_size = max(1, int(window_size))
    window = rows[-window_size:]

    reasons: list[str] = []
    if not window and not bool(int(allow_empty)):
        reasons.append("No reports found for trend analysis")

    missing_model = [row for row in window if not bool(row.get("has_model", False))]
    if missing_model:
        reasons.append(f"Model '{model}' missing in {len(missing_model)} report(s)")

    failed_runs = 0
    for row in window:
        if str(row.get("report_status", "") or "").strip().lower() != "pass":
            failed_runs += 1
    max_failed_runs = max(0, int(max_failed_runs))
    if failed_runs > max_failed_runs:
        reasons.append(f"failed_runs {failed_runs} > {max_failed_runs}")

    max_pass_drop = max(0.0, float(max_pass_drop))
    max_avg_drop = max(0.0, float(max_avg_drop))
    max_disallow_increase = max(0, int(max_disallow_increase))
    regression_events = 0
    max_seen_pass_drop = 0.0
    max_seen_avg_drop = 0.0
    max_seen_disallow_increase = 0
    for prev, curr in zip(window, window[1:]):
        if (not bool(prev.get("has_model"))) or (not bool(curr.get("has_model"))):
            continue
        pass_drop = float(prev.get("pass_rate", 0.0) or 0.0) - float(curr.get("pass_rate", 0.0) or 0.0)
        avg_drop = float(prev.get("avg_score", 0.0) or 0.0) - float(curr.get("avg_score", 0.0) or 0.0)
        disallow_inc = int(curr.get("disallow_violations", 0) or 0) - int(prev.get("disallow_violations", 0) or 0)
        max_seen_pass_drop = max(max_seen_pass_drop, pass_drop)
        max_seen_avg_drop = max(max_seen_avg_drop, avg_drop)
        max_seen_disallow_increase = max(max_seen_disallow_increase, disallow_inc)
        if pass_drop > (max_pass_drop + EPS) or avg_drop > (max_avg_drop + EPS) or disallow_inc > max_disallow_increase:
            regression_events += 1

    max_regression_events = max(0, int(max_regression_events))
    if regression_events > max_regression_events:
        reasons.append(f"regression_events {regression_events} > {max_regression_events}")

    latest = window[-1] if window else {}
    min_latest_pass = max(0.0, min(1.0, float(min_latest_pass)))
    min_latest_avg = max(0.0, min(1.0, float(min_latest_avg)))
    latest_pass = float(latest.get("pass_rate", 0.0) or 0.0)
    latest_avg = float(latest.get("avg_score", 0.0) or 0.0)
    if window:
        if latest_pass < (min_latest_pass - EPS):
            reasons.append(f"latest_pass_rate {latest_pass:.4f} < {min_latest_pass:.4f}")
        if latest_avg < (min_latest_avg - EPS):
            reasons.append(f"latest_avg_score {latest_avg:.4f} < {min_latest_avg:.4f}")

    status = "pass" if not reasons else "fail"
    report_path = os.path.abspath(os.path.expanduser(str(args.report or "tutor_quality_trend_report.json")))
    out = {
        "ts_utc": _now_iso(),
        "status": status,
        "reason": "; ".join(reasons[:20]),
        "model": model,
        "policy_file": policy_file,
        "policy_name": policy_name,
        "window_size": window_size,
        "input_count": int(len(rows)),
        "window_count": int(len(window)),
        "thresholds": {
            "max_failed_runs": max_failed_runs,
            "max_regression_events": max_regression_events,
            "max_pass_rate_drop": max_pass_drop,
            "max_avg_score_drop": max_avg_drop,
            "max_disallow_increase": max_disallow_increase,
            "min_latest_pass_rate": min_latest_pass,
            "min_latest_avg_score": min_latest_avg,
        },
        "metrics": {
            "failed_runs": int(failed_runs),
            "regression_events": int(regression_events),
            "max_pass_rate_drop_seen": float(max_seen_pass_drop),
            "max_avg_score_drop_seen": float(max_seen_avg_drop),
            "max_disallow_increase_seen": int(max_seen_disallow_increase),
            "latest_pass_rate": latest_pass,
            "latest_avg_score": latest_avg,
        },
        "runs": [
            {
                "file": str(item.get("file", "") or ""),
                "ts_utc": str(item.get("ts_utc", "") or ""),
                "report_status": str(item.get("report_status", "") or ""),
                "has_model": bool(item.get("has_model", False)),
                "pass_rate": float(item.get("pass_rate", 0.0) or 0.0),
                "avg_score": float(item.get("avg_score", 0.0) or 0.0),
                "disallow_violations": int(item.get("disallow_violations", 0) or 0),
            }
            for item in window
        ],
    }

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=True)

    print(
        json.dumps(
            {
                "status": status,
                "window_count": int(len(window)),
                "regression_events": int(regression_events),
                "report": report_path,
            },
            ensure_ascii=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(run())
