#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
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


def _load_json_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


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


def _model_summary_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    models = report.get("models", [])
    if not isinstance(models, list):
        return out
    for row in models:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model", "") or "").strip()
        summary = row.get("summary", {})
        if not model or not isinstance(summary, dict):
            continue
        out[model] = summary
    return out


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


def _pick_models(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    named_model: str,
    require_model_match: bool,
) -> tuple[list[str], list[str]]:
    baseline_map = _model_summary_map(baseline)
    candidate_map = _model_summary_map(candidate)
    reasons: list[str] = []

    target = str(named_model or "").strip()
    if target:
        if target not in baseline_map:
            reasons.append(f"Baseline missing model '{target}'")
        if target not in candidate_map:
            reasons.append(f"Candidate missing model '{target}'")
        return ([target] if not reasons else []), reasons

    if len(baseline_map) == 1 and len(candidate_map) == 1:
        b_name = next(iter(baseline_map.keys()), "")
        c_name = next(iter(candidate_map.keys()), "")
        if b_name and c_name:
            if b_name == c_name:
                return [b_name], reasons
            if not require_model_match:
                return [c_name], reasons
            reasons.append(f"Single-model reports differ: baseline '{b_name}' vs candidate '{c_name}'")
            return [], reasons

    shared = sorted(set(baseline_map.keys()) & set(candidate_map.keys()))
    if shared:
        return shared, reasons
    if require_model_match:
        reasons.append("No overlapping model names between baseline and candidate reports")
        return [], reasons
    if candidate_map:
        return [sorted(candidate_map.keys())[0]], reasons
    reasons.append("Candidate report has no model summaries")
    return [], reasons


def run() -> int:
    parser = argparse.ArgumentParser(description="Compare tutor quality reports and fail on metric regressions.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--policy-file", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_POLICY_FILE", ""))
    parser.add_argument("--policy", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_POLICY", ""))
    parser.add_argument("--max-pass-rate-drop", type=float, default=None)
    parser.add_argument("--max-avg-score-drop", type=float, default=None)
    parser.add_argument("--max-disallow-increase", type=int, default=None)
    parser.add_argument("--require-model-match", type=int, default=None)
    parser.add_argument("--report", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_COMPARE_REPORT", "tutor_quality_compare_report.json"))
    args = parser.parse_args()

    baseline_path = os.path.abspath(os.path.expanduser(str(args.baseline)))
    candidate_path = os.path.abspath(os.path.expanduser(str(args.candidate)))
    report_path = os.path.abspath(os.path.expanduser(str(args.report)))
    policy_file = os.path.abspath(os.path.expanduser(str(args.policy_file or ""))) if str(args.policy_file or "").strip() else ""
    policy_name = str(args.policy or "").strip()

    baseline = _load_json_file(baseline_path)
    candidate = _load_json_file(candidate_path)
    policy_block: dict[str, Any] = {}
    if policy_file and policy_name:
        policy_block = _load_policy_block(policy_file, policy_name, "compare")

    max_pass_rate_drop = _env_float("STUDYPLAN_TUTOR_QUALITY_MAX_PASS_RATE_DROP", 0.02)
    max_avg_score_drop = _env_float("STUDYPLAN_TUTOR_QUALITY_MAX_AVG_SCORE_DROP", 0.03)
    max_disallow_increase = _env_int("STUDYPLAN_TUTOR_QUALITY_MAX_DISALLOW_INCREASE", 0)
    require_model_match = bool(_env_int("STUDYPLAN_TUTOR_QUALITY_REQUIRE_MODEL_MATCH", 1))
    if "max_pass_rate_drop" in policy_block:
        max_pass_rate_drop = _coerce_float(policy_block.get("max_pass_rate_drop"))
    if "max_avg_score_drop" in policy_block:
        max_avg_score_drop = _coerce_float(policy_block.get("max_avg_score_drop"))
    if "max_disallow_increase" in policy_block:
        max_disallow_increase = _coerce_int(policy_block.get("max_disallow_increase"))
    if "require_model_match" in policy_block:
        require_model_match = bool(_coerce_int(policy_block.get("require_model_match")))
    if args.max_pass_rate_drop is not None:
        max_pass_rate_drop = float(args.max_pass_rate_drop)
    if args.max_avg_score_drop is not None:
        max_avg_score_drop = float(args.max_avg_score_drop)
    if args.max_disallow_increase is not None:
        max_disallow_increase = int(args.max_disallow_increase)
    if args.require_model_match is not None:
        require_model_match = bool(int(args.require_model_match))

    compared_models, pre_reasons = _pick_models(
        baseline,
        candidate,
        named_model=str(args.model or ""),
        require_model_match=require_model_match,
    )

    max_pass_rate_drop = max(0.0, float(max_pass_rate_drop))
    max_avg_score_drop = max(0.0, float(max_avg_score_drop))
    max_disallow_increase = max(0, int(max_disallow_increase))

    baseline_map = _model_summary_map(baseline)
    candidate_map = _model_summary_map(candidate)
    reasons = list(pre_reasons)
    comparisons: list[dict[str, Any]] = []

    for model in compared_models:
        b = baseline_map.get(model, {})
        c = candidate_map.get(model, {})
        b_pass_rate = _coerce_float(b.get("pass_rate"))
        c_pass_rate = _coerce_float(c.get("pass_rate"))
        b_avg = _coerce_float(b.get("avg_score"))
        c_avg = _coerce_float(c.get("avg_score"))
        b_disallow = _coerce_int(b.get("disallow_violations"))
        c_disallow = _coerce_int(c.get("disallow_violations"))

        pass_rate_drop = b_pass_rate - c_pass_rate
        avg_score_drop = b_avg - c_avg
        disallow_increase = c_disallow - b_disallow

        model_status = "pass"
        model_reasons: list[str] = []
        if pass_rate_drop > (max_pass_rate_drop + EPS):
            model_status = "fail"
            model_reasons.append(f"pass_rate drop {pass_rate_drop:.4f} > {max_pass_rate_drop:.4f}")
        if avg_score_drop > (max_avg_score_drop + EPS):
            model_status = "fail"
            model_reasons.append(f"avg_score drop {avg_score_drop:.4f} > {max_avg_score_drop:.4f}")
        if disallow_increase > max_disallow_increase:
            model_status = "fail"
            model_reasons.append(f"disallow increase {disallow_increase} > {max_disallow_increase}")

        if model_reasons:
            reasons.extend([f"{model}: {entry}" for entry in model_reasons])
        comparisons.append(
            {
                "model": model,
                "status": model_status,
                "baseline": {
                    "pass_rate": b_pass_rate,
                    "avg_score": b_avg,
                    "disallow_violations": b_disallow,
                },
                "candidate": {
                    "pass_rate": c_pass_rate,
                    "avg_score": c_avg,
                    "disallow_violations": c_disallow,
                },
                "delta": {
                    "pass_rate_drop": float(pass_rate_drop),
                    "avg_score_drop": float(avg_score_drop),
                    "disallow_increase": int(disallow_increase),
                },
                "reasons": model_reasons,
            }
        )

    status = "pass" if not reasons else "fail"
    out = {
        "ts_utc": _now_iso(),
        "status": status,
        "reason": "; ".join(reasons[:20]),
        "baseline_file": baseline_path,
        "candidate_file": candidate_path,
        "model_selector": str(args.model or ""),
        "policy_file": policy_file,
        "policy_name": policy_name,
        "require_model_match": require_model_match,
        "thresholds": {
            "max_pass_rate_drop": max_pass_rate_drop,
            "max_avg_score_drop": max_avg_score_drop,
            "max_disallow_increase": max_disallow_increase,
        },
        "compared_model_count": int(len(comparisons)),
        "models": comparisons,
    }

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=True)

    print(
        json.dumps(
            {
                "status": status,
                "compared_model_count": int(len(comparisons)),
                "report": report_path,
            },
            ensure_ascii=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(run())
