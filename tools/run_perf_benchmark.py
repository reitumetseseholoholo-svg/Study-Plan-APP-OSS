#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studyplan.telemetry.slo import evaluate_latency_slo

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_PROMPTS = [
    "Explain NPV vs IRR and when they conflict.",
    "Give a compact worked example for WACC with debt tax shield.",
    "Compare aggressive and conservative working capital policy in exam terms.",
    "Create a 4-step memory scaffold for CAPM assumptions.",
    "How do you evaluate lease vs buy in this module?",
    "Explain Miller-Orr model inputs and interpretation.",
]


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _pick_model(host: str, timeout: int, preferred: str) -> tuple[str, str | None]:
    if preferred.strip():
        return preferred.strip(), None
    data, err = _request_json(host, "/api/tags", payload=None, timeout=timeout)
    if err:
        return "", err
    for item in list((data or {}).get("models", []) or []):
        if isinstance(item, dict):
            name = str(item.get("name", "") or "").strip()
            if name:
                return name, None
    return "", "No local Ollama models available"


def _load_prompts(path: str) -> list[str]:
    file_path = str(path or "").strip()
    if not file_path:
        return list(DEFAULT_PROMPTS)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return list(DEFAULT_PROMPTS)
    prompts: list[str] = []
    if isinstance(payload, list):
        for row in payload:
            text = str(row or "").strip()
            if text:
                prompts.append(text)
    elif isinstance(payload, dict):
        for row in list(payload.get("prompts", []) or []):
            text = str(row or "").strip()
            if text:
                prompts.append(text)
    return prompts or list(DEFAULT_PROMPTS)


def _latency_percentile(latencies: list[int], quantile: float) -> float:
    if not latencies:
        return 0.0
    sorted_vals = sorted(max(0, int(v)) for v in latencies)
    idx = max(0, min(len(sorted_vals) - 1, int(math.ceil(float(quantile) * len(sorted_vals))) - 1))
    return float(sorted_vals[idx])


def run() -> int:
    parser = argparse.ArgumentParser(description="Run fixed prompt latency benchmark against local Ollama.")
    parser.add_argument("--host", default=os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    parser.add_argument("--model", default=os.environ.get("STUDYPLAN_PERF_MODEL", ""))
    parser.add_argument("--prompts-file", default=os.environ.get("STUDYPLAN_PERF_PROMPTS_FILE", ""))
    parser.add_argument("--report", default=os.environ.get("STUDYPLAN_PERF_REPORT", "perf_report.json"))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("STUDYPLAN_PERF_TIMEOUT_SECONDS", "120")))
    parser.add_argument("--num-ctx", type=int, default=int(os.environ.get("STUDYPLAN_PERF_NUM_CTX", "2048")))
    parser.add_argument("--num-thread", type=int, default=int(os.environ.get("STUDYPLAN_PERF_NUM_THREAD", os.environ.get("OLLAMA_NUM_THREADS", "6"))))
    parser.add_argument("--temperature", type=float, default=float(os.environ.get("STUDYPLAN_PERF_TEMPERATURE", "0.2")))
    parser.add_argument("--warmup", type=int, default=int(os.environ.get("STUDYPLAN_PERF_WARMUP", "1")))
    parser.add_argument("--require-ollama", type=int, default=int(os.environ.get("STUDYPLAN_PERF_REQUIRE_OLLAMA", "0")))
    parser.add_argument("--allow-warn", type=int, default=int(os.environ.get("STUDYPLAN_PERF_ALLOW_WARN", "0")))
    args = parser.parse_args()

    host = str(args.host or DEFAULT_HOST).strip() or DEFAULT_HOST
    timeout = max(10, min(600, int(args.timeout)))
    report_path = os.path.abspath(os.path.expanduser(str(args.report or "perf_report.json")))
    prompts = _load_prompts(str(args.prompts_file or ""))
    model, model_err = _pick_model(host, timeout=max(10, min(30, timeout)), preferred=str(args.model or ""))

    if not model:
        report = {
            "ts_utc": _now_iso(),
            "host": host,
            "model": "",
            "status": "failed" if int(args.require_ollama) else "skipped",
            "error": str(model_err or "No model available"),
            "samples": 0,
        }
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=True)
        if int(args.require_ollama):
            return 1
        print(f"perf benchmark skipped: {report['error']}")
        return 0

    payload_template = {
        "model": model,
        "stream": False,
        "options": {
            "num_ctx": int(max(256, min(8192, int(args.num_ctx)))),
            "num_thread": int(max(1, min(64, int(args.num_thread)))),
            "temperature": max(0.0, min(1.0, float(args.temperature))),
        },
    }

    # warmup
    for _ in range(max(0, int(args.warmup))):
        warm_payload = dict(payload_template)
        warm_payload["prompt"] = "Warmup"
        _request_json(host, "/api/generate", payload=warm_payload, timeout=timeout)

    latencies: list[int] = []
    failures: list[str] = []
    runs: list[dict[str, Any]] = []
    for idx, prompt in enumerate(prompts, start=1):
        req_payload = dict(payload_template)
        req_payload["prompt"] = str(prompt)
        started = time.monotonic()
        data, err = _request_json(host, "/api/generate", payload=req_payload, timeout=timeout)
        elapsed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
        ok = err is None and isinstance(data, dict) and bool(str(data.get("response", "") or "").strip())
        runs.append(
            {
                "id": idx,
                "latency_ms": int(elapsed_ms),
                "ok": bool(ok),
                "error": str(err or ""),
                "prompt_chars": len(str(prompt or "")),
            }
        )
        if ok:
            latencies.append(int(elapsed_ms))
        else:
            failures.append(str(err or "empty response"))

    slo = evaluate_latency_slo(
        latencies,
        p50_target_ms=int(os.environ.get("STUDYPLAN_AI_TUTOR_SLO_P50_MS", "25000")),
        p90_target_ms=int(os.environ.get("STUDYPLAN_AI_TUTOR_SLO_P90_MS", "60000")),
        spread_target_ratio=float(os.environ.get("STUDYPLAN_AI_TUTOR_SLO_SPREAD_RATIO", "2.4")),
        min_samples=max(3, min(len(prompts), int(os.environ.get("STUDYPLAN_AI_TUTOR_SLO_MIN_SAMPLES", "8")))),
    )
    p95 = _latency_percentile(latencies, 0.95)
    status = str(slo.get("status", "insufficient") or "insufficient")

    report = {
        "ts_utc": _now_iso(),
        "host": host,
        "model": model,
        "prompt_count": len(prompts),
        "samples": len(latencies),
        "failed_prompts": len(failures),
        "failures": failures[:8],
        "runs": runs,
        "metrics": {
            "avg_latency_ms": float(sum(latencies) / len(latencies)) if latencies else 0.0,
            "p50_latency_ms": float(slo.get("p50_latency_ms", 0.0) or 0.0),
            "p90_latency_ms": float(slo.get("p90_latency_ms", 0.0) or 0.0),
            "p95_latency_ms": float(p95),
            "latency_spread_ratio": float(slo.get("latency_spread_ratio", 1.0) or 1.0),
        },
        "slo": slo,
        "status": status,
    }

    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)

    print(json.dumps({"status": status, "model": model, "report": report_path, "samples": len(latencies)}))

    if len(failures) > 0:
        return 1
    if status == "pass":
        return 0
    if status == "warn" and int(args.allow_warn):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
