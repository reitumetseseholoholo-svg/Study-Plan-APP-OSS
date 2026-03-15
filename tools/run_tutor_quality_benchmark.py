#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.tutor_quality.quality_scorer import build_reference_response, score_matrix


DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MATRIX = str(ROOT / "tests" / "tutor_quality" / "matrix_v1.json")
DEFAULT_EXPECTED = str(ROOT / "tests" / "tutor_quality" / "expected_scores_v1.json")
DEFAULT_REPORT = "tutor_quality_report.json"
DEFAULT_MIN_PASS_RATE = 0.85
DEFAULT_MIN_AVG_SCORE = 0.80
DEFAULT_MAX_DISALLOW_VIOLATIONS = 0


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


def _load_gate_profile(path: str) -> dict[str, Any]:
    payload = _load_json_file(path)
    candidate = payload.get("gates", payload)
    if not isinstance(candidate, dict):
        raise ValueError(f"Gate profile in {path} must be a JSON object")
    out: dict[str, Any] = {}
    for key in (
        "threshold",
        "min_pass_rate",
        "min_avg_score",
        "max_disallow_violations",
        "require_all_models_pass",
    ):
        if key in candidate:
            out[key] = candidate.get(key)
    return out


def _request_json(host: str, path: str, payload: dict[str, Any] | None, timeout: int) -> tuple[dict[str, Any] | None, str | None]:
    endpoint = path if path.startswith("/") else f"/{path}"
    url = f"{host.rstrip('/')}{endpoint}"
    headers = {"Accept": "application/json"}
    data: bytes | None = None
    method = "GET"
    if isinstance(payload, dict):
        method = "POST"
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
            raw = resp.read().decode("utf-8", "replace")
        parsed = json.loads(raw) if raw.strip() else {}
        if isinstance(parsed, dict):
            return parsed, None
        return {"data": parsed}, None
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace").strip()
        except Exception:
            detail = ""
        msg = f"HTTP {exc.code}"
        if detail:
            msg = f"{msg}: {detail}"
        return None, msg
    except Exception as exc:  # pragma: no cover - network/system dependent
        return None, str(exc)


def _parse_models_arg(value: str) -> list[str]:
    models: list[str] = []
    for token in str(value or "").replace("\n", ",").split(","):
        name = str(token or "").strip()
        if name and name not in models:
            models.append(name)
    return models


def _list_ollama_models(host: str, timeout: int) -> tuple[list[str], str | None]:
    data, err = _request_json(host, "/api/tags", payload=None, timeout=timeout)
    if err:
        return [], err
    out: list[str] = []
    for item in list((data or {}).get("models", []) or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        if name and name not in out:
            out.append(name)
    if not out:
        return [], "No local Ollama models found"
    return out, None


def _build_case_prompt(case: dict[str, Any]) -> str:
    module_id = str(case.get("module_id", "") or "").strip()
    chapter = str(case.get("chapter", "") or "").strip()
    action_type = str(case.get("action_type", "") or "").strip()
    user_prompt = str(case.get("prompt", "") or "").strip()
    return (
        "You are an ACCA exam tutor. Respond in plain text only.\n"
        "Keep the answer concise, accurate, and exam-focused.\n"
        f"Module: {module_id}\n"
        f"Chapter: {chapter}\n"
        f"Task type: {action_type}\n"
        f"Request: {user_prompt}\n"
    )


def _run_reference_model(matrix: dict[str, Any], threshold: float) -> dict[str, Any]:
    cases = matrix.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    responses_by_id: dict[str, str] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id", "") or "").strip()
        if not case_id:
            continue
        responses_by_id[case_id] = build_reference_response(case)
    summary = score_matrix(matrix, responses_by_id, threshold=threshold)
    return {
        "model": "reference_baseline",
        "mode": "reference",
        "error_count": 0,
        "errors": [],
        "summary": summary,
    }


def _run_ollama_model(
    matrix: dict[str, Any],
    model: str,
    *,
    host: str,
    timeout: int,
    num_ctx: int,
    temperature: float,
    threshold: float,
) -> dict[str, Any]:
    cases = matrix.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    responses_by_id: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id", "") or "").strip()
        if not case_id:
            continue
        payload = {
            "model": model,
            "stream": False,
            "prompt": _build_case_prompt(case),
            "options": {
                "num_ctx": int(max(256, min(16384, int(num_ctx)))),
                "temperature": float(max(0.0, min(1.0, float(temperature)))),
            },
        }
        data, err = _request_json(host, "/api/generate", payload=payload, timeout=timeout)
        if err:
            errors.append({"case_id": case_id, "error": str(err)})
            responses_by_id[case_id] = ""
            continue
        text = str((data or {}).get("response", "") or "").strip()
        if not text:
            errors.append({"case_id": case_id, "error": "empty response"})
        responses_by_id[case_id] = text
    summary = score_matrix(matrix, responses_by_id, threshold=threshold)
    return {
        "model": str(model),
        "mode": "ollama",
        "error_count": int(len(errors)),
        "errors": errors[:50],
        "summary": summary,
    }


def _evaluate_gates(
    summary: dict[str, Any],
    *,
    min_pass_rate: float,
    min_avg_score: float,
    max_disallow_violations: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    pass_rate = float(summary.get("pass_rate", 0.0) or 0.0)
    avg_score = float(summary.get("avg_score", 0.0) or 0.0)
    disallow_violations = int(summary.get("disallow_violations", 0) or 0)

    if pass_rate < float(min_pass_rate):
        reasons.append(f"pass_rate {pass_rate:.4f} < {float(min_pass_rate):.4f}")
    if avg_score < float(min_avg_score):
        reasons.append(f"avg_score {avg_score:.4f} < {float(min_avg_score):.4f}")
    if disallow_violations > int(max_disallow_violations):
        reasons.append(f"disallow_violations {disallow_violations} > {int(max_disallow_violations)}")
    return ("pass" if not reasons else "fail"), reasons


def run() -> int:
    parser = argparse.ArgumentParser(description="Run tutor quality benchmark matrix with deterministic scoring gates.")
    parser.add_argument("--mode", choices=("reference", "ollama"), default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_MODE", "reference"))
    parser.add_argument("--matrix", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_MATRIX", DEFAULT_MATRIX))
    parser.add_argument("--expected", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_EXPECTED", DEFAULT_EXPECTED))
    parser.add_argument("--gates-file", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_GATES_FILE", ""))
    parser.add_argument("--report", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_REPORT", DEFAULT_REPORT))
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--min-pass-rate", type=float, default=None)
    parser.add_argument("--min-avg-score", type=float, default=None)
    parser.add_argument("--max-disallow-violations", type=int, default=None)
    parser.add_argument("--host", default=os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    parser.add_argument("--models", default=os.environ.get("STUDYPLAN_TUTOR_QUALITY_MODELS", ""))
    parser.add_argument("--max-models", type=int, default=_env_int("STUDYPLAN_TUTOR_QUALITY_MAX_MODELS", 2))
    parser.add_argument("--timeout", type=int, default=_env_int("STUDYPLAN_TUTOR_QUALITY_TIMEOUT_SECONDS", 120))
    parser.add_argument("--num-ctx", type=int, default=_env_int("STUDYPLAN_TUTOR_QUALITY_NUM_CTX", 3072))
    parser.add_argument("--temperature", type=float, default=_env_float("STUDYPLAN_TUTOR_QUALITY_TEMPERATURE", 0.2))
    parser.add_argument("--require-all-models-pass", type=int, default=None)
    parser.add_argument("--allow-missing-models", type=int, default=_env_int("STUDYPLAN_TUTOR_QUALITY_ALLOW_MISSING_MODELS", 0))
    args = parser.parse_args()

    matrix_path = os.path.abspath(os.path.expanduser(str(args.matrix or DEFAULT_MATRIX)))
    expected_path = os.path.abspath(os.path.expanduser(str(args.expected or DEFAULT_EXPECTED)))
    gates_file = os.path.abspath(os.path.expanduser(str(args.gates_file or ""))) if str(args.gates_file or "").strip() else ""
    report_path = os.path.abspath(os.path.expanduser(str(args.report or DEFAULT_REPORT)))
    mode = str(args.mode or "reference").strip().lower()

    matrix = _load_json_file(matrix_path)
    expected = _load_json_file(expected_path)
    gate_profile: dict[str, Any] = {}
    if gates_file:
        gate_profile = _load_gate_profile(gates_file)

    expected_threshold = float(expected.get("threshold", 0.75) or 0.75)
    threshold = expected_threshold
    env_threshold = _env_float("STUDYPLAN_TUTOR_QUALITY_THRESHOLD", 0.0)
    if env_threshold > 0.0:
        threshold = env_threshold
    if "threshold" in gate_profile:
        threshold = float(gate_profile.get("threshold") or threshold)
    if args.threshold is not None:
        threshold = float(args.threshold)
    threshold = max(0.0, min(1.0, threshold))

    min_pass_rate = _env_float("STUDYPLAN_TUTOR_QUALITY_MIN_PASS_RATE", DEFAULT_MIN_PASS_RATE)
    min_avg_score = _env_float("STUDYPLAN_TUTOR_QUALITY_MIN_AVG_SCORE", DEFAULT_MIN_AVG_SCORE)
    max_disallow_violations = _env_int("STUDYPLAN_TUTOR_QUALITY_MAX_DISALLOW", DEFAULT_MAX_DISALLOW_VIOLATIONS)
    require_all_models_pass = bool(_env_int("STUDYPLAN_TUTOR_QUALITY_REQUIRE_ALL", 0))
    if "min_pass_rate" in gate_profile:
        min_pass_rate = float(gate_profile.get("min_pass_rate") or min_pass_rate)
    if "min_avg_score" in gate_profile:
        min_avg_score = float(gate_profile.get("min_avg_score") or min_avg_score)
    if "max_disallow_violations" in gate_profile:
        max_disallow_violations = int(gate_profile.get("max_disallow_violations") or max_disallow_violations)
    if "require_all_models_pass" in gate_profile:
        require_all_models_pass = bool(int(gate_profile.get("require_all_models_pass") or 0))
    if args.min_pass_rate is not None:
        min_pass_rate = float(args.min_pass_rate)
    if args.min_avg_score is not None:
        min_avg_score = float(args.min_avg_score)
    if args.max_disallow_violations is not None:
        max_disallow_violations = int(args.max_disallow_violations)
    if args.require_all_models_pass is not None:
        require_all_models_pass = bool(int(args.require_all_models_pass))

    model_rows: list[dict[str, Any]] = []
    fatal_error = ""
    if mode == "reference":
        model_rows.append(_run_reference_model(matrix, threshold))
    else:
        host = str(args.host or DEFAULT_HOST).strip() or DEFAULT_HOST
        timeout = max(10, min(600, int(args.timeout)))
        models = _parse_models_arg(str(args.models or ""))
        if not models:
            discovered, discover_err = _list_ollama_models(host, timeout=max(10, min(timeout, 30)))
            if discover_err:
                fatal_error = str(discover_err)
            else:
                models = discovered
        if models:
            max_models = max(1, int(args.max_models))
            models = models[:max_models]
            for model in models:
                model_rows.append(
                    _run_ollama_model(
                        matrix,
                        model,
                        host=host,
                        timeout=timeout,
                        num_ctx=int(args.num_ctx),
                        temperature=float(args.temperature),
                        threshold=threshold,
                    )
                )
        elif not bool(args.allow_missing_models):
            fatal_error = fatal_error or "No models available for ollama mode"

    gate_cfg = {
        "min_pass_rate": float(min_pass_rate),
        "min_avg_score": float(min_avg_score),
        "max_disallow_violations": int(max_disallow_violations),
    }
    gate_meta = {"threshold": threshold, **gate_cfg}
    pass_rows = 0
    for row in model_rows:
        summary = row.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        gate_status, gate_reasons = _evaluate_gates(summary, **gate_cfg)
        row["gate_status"] = gate_status
        row["gate_reasons"] = gate_reasons
        if gate_status == "pass":
            pass_rows += 1

    status = "pass"
    reason = ""
    if fatal_error:
        status = "fail"
        reason = fatal_error
    elif not model_rows:
        status = "fail"
        reason = "No benchmark rows produced"
    else:
        if require_all_models_pass:
            if pass_rows != len(model_rows):
                status = "fail"
                reason = f"{pass_rows}/{len(model_rows)} models passed gates"
        elif pass_rows <= 0:
            status = "fail"
            reason = "No model passed quality gates"

    best_model = ""
    if model_rows:
        ranked = sorted(
            model_rows,
            key=lambda row: (
                1 if str(row.get("gate_status", "fail")) == "pass" else 0,
                float(((row.get("summary", {}) or {}).get("avg_score", 0.0) or 0.0)),
                float(((row.get("summary", {}) or {}).get("pass_rate", 0.0) or 0.0)),
            ),
            reverse=True,
        )
        best_model = str(ranked[0].get("model", "") or "")

    report = {
        "ts_utc": _now_iso(),
        "mode": mode,
        "status": status,
        "reason": reason,
        "matrix_file": matrix_path,
        "expected_file": expected_path,
        "gate_profile_file": gates_file,
        "gates": gate_meta,
        "require_all_models_pass": bool(require_all_models_pass),
        "pass_models": int(pass_rows),
        "model_count": int(len(model_rows)),
        "best_model": best_model,
        "models": model_rows,
    }

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)

    print(
        json.dumps(
            {
                "status": status,
                "mode": mode,
                "best_model": best_model,
                "pass_models": int(pass_rows),
                "model_count": int(len(model_rows)),
                "report": report_path,
            },
            ensure_ascii=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(run())
