#!/usr/bin/env python3
"""
Shadow / A/B comparison for tutor quality (roadmap Phase 5.3).

Scores two frozen response maps (e.g. from two prompt presets or two models) against
the same matrix without changing in-app behavior. Use after capturing responses offline:

1. Run ``run_tutor_quality_benchmark.py`` (or your own harness) twice; export
   ``case_id -> response`` JSON for variant A and B.
2. Run this tool to diff pass rates, avg scores, and per-case deltas.

Example::

    python tools/run_tutor_quality_shadow_compare.py \\
      --matrix tests/tutor_quality/matrix_v1.json \\
      --responses-a /tmp/tutor_responses_baseline.json \\
      --responses-b /tmp/tutor_responses_candidate.json \\
      --report /tmp/shadow_compare.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.tutor_quality.quality_scorer import score_matrix  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _responses_map(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in raw.items():
        kid = str(key or "").strip()
        if not kid:
            continue
        out[kid] = str(val if val is not None else "")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two tutor response maps (shadow A/B).")
    parser.add_argument("--matrix", required=True, help="Path to matrix JSON (e.g. matrix_v1.json).")
    parser.add_argument("--responses-a", required=True, help="JSON object: case_id -> response text (variant A).")
    parser.add_argument("--responses-b", required=True, help="JSON object: case_id -> response text (variant B).")
    parser.add_argument("--threshold", type=float, default=0.75, help="Scorer pass threshold.")
    parser.add_argument("--report", default="", help="Optional path to write comparison JSON.")
    args = parser.parse_args()

    matrix_path = Path(args.matrix).resolve()
    matrix = _load_json(matrix_path)
    map_a = _responses_map(_load_json(Path(args.responses_a).resolve()))
    map_b = _responses_map(_load_json(Path(args.responses_b).resolve()))

    sa = score_matrix(matrix, map_a, threshold=float(args.threshold))
    sb = score_matrix(matrix, map_b, threshold=float(args.threshold))

    by_id_a = {str(r.get("case_id", "")): r for r in sa.get("results", []) if isinstance(r, dict)}
    by_id_b = {str(r.get("case_id", "")): r for r in sb.get("results", []) if isinstance(r, dict)}
    case_ids = sorted(set(by_id_a.keys()) | set(by_id_b.keys()))

    deltas: list[dict[str, Any]] = []
    for cid in case_ids:
        ra = by_id_a.get(cid, {})
        rb = by_id_b.get(cid, {})
        sa_ = float(ra.get("score", 0.0) or 0.0)
        sb_ = float(rb.get("score", 0.0) or 0.0)
        pa = bool(ra.get("passed", False))
        pb = bool(rb.get("passed", False))
        if sa_ != sb_ or pa != pb:
            deltas.append(
                {
                    "case_id": cid,
                    "score_a": sa_,
                    "score_b": sb_,
                    "score_delta": round(sb_ - sa_, 4),
                    "passed_a": pa,
                    "passed_b": pb,
                }
            )

    report = {
        "matrix": str(matrix_path),
        "threshold": float(args.threshold),
        "a": {
            "pass_rate": float(sa.get("pass_rate", 0.0) or 0.0),
            "avg_score": float(sa.get("avg_score", 0.0) or 0.0),
            "pass_count": int(sa.get("pass_count", 0) or 0),
            "total": int(sa.get("total", 0) or 0),
        },
        "b": {
            "pass_rate": float(sb.get("pass_rate", 0.0) or 0.0),
            "avg_score": float(sb.get("avg_score", 0.0) or 0.0),
            "pass_count": int(sb.get("pass_count", 0) or 0),
            "total": int(sb.get("total", 0) or 0),
        },
        "delta_pass_rate": round(float(sb.get("pass_rate", 0.0) or 0.0) - float(sa.get("pass_rate", 0.0) or 0.0), 4),
        "delta_avg_score": round(float(sb.get("avg_score", 0.0) or 0.0) - float(sa.get("avg_score", 0.0) or 0.0), 4),
        "differing_cases": deltas,
    }

    print(
        f"A: pass_rate={report['a']['pass_rate']:.4f} avg_score={report['a']['avg_score']:.4f} "
        f"({report['a']['pass_count']}/{report['a']['total']})"
    )
    print(
        f"B: pass_rate={report['b']['pass_rate']:.4f} avg_score={report['b']['avg_score']:.4f} "
        f"({report['b']['pass_count']}/{report['b']['total']})"
    )
    print(f"Δ pass_rate={report['delta_pass_rate']:+.4f}  Δ avg_score={report['delta_avg_score']:+.4f}")
    print(f"Cases with score or pass change: {len(deltas)}")

    out_path = str(args.report or "").strip()
    if out_path:
        Path(out_path).write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
