#!/usr/bin/env python3
"""Summarize ai_tutor_telemetry_events from preferences.json (Phase 0).

Usage:
  python scripts/llm_telemetry_aggregate.py [path/to/preferences.json]

Or set STUDYPLAN_CONFIG_HOME and omit the path to read CONFIG_HOME/preferences.json.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def main() -> int:
    if len(sys.argv) > 1:
        pref_path = Path(sys.argv[1]).expanduser()
    else:
        home = os.environ.get("STUDYPLAN_CONFIG_HOME", "").strip()
        if not home:
            home = str(Path.home() / ".config" / "studyplan")
        pref_path = Path(home) / "preferences.json"
    if not pref_path.is_file():
        print(f"No preferences file: {pref_path}", file=sys.stderr)
        return 1
    try:
        data = json.loads(pref_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read JSON: {exc}", file=sys.stderr)
        return 1
    events = data.get("ai_tutor_telemetry_events") or []
    if not isinstance(events, list) or not events:
        print("No ai_tutor_telemetry_events in file.")
        return 0
    rows = [e for e in events if isinstance(e, dict)]
    print(f"File: {pref_path}")
    print(f"Events (raw): {len(rows)}")
    purposes = Counter(str(e.get("purpose") or "unknown") for e in rows)
    print("By purpose:", dict(purposes.most_common()))
    lat_ok = [float(e.get("latency_ms", 0) or 0) for e in rows if int(e.get("latency_ms", 0) or 0) > 0]
    lat_ok.sort()
    if lat_ok:
        print(
            f"Latency ms — avg: {statistics.mean(lat_ok):.1f}, "
            f"p50: {_percentile(lat_ok, 0.5):.1f}, "
            f"p90: {_percentile(lat_ok, 0.9):.1f}"
        )
    pt_ok = [float(e.get("prompt_tokens_est", 0) or 0) for e in rows]
    rt_ok = [float(e.get("response_tokens_est", 0) or 0) for e in rows]
    if pt_ok:
        print(f"Avg prompt_tokens_est: {statistics.mean(pt_ok):.1f}")
    if rt_ok:
        print(f"Avg response_tokens_est: {statistics.mean(rt_ok):.1f}")
    omitted = sum(1 for e in rows if int(e.get("learning_context_omitted", 0) or 0) == 1)
    if omitted:
        print(f"Turns with learning_context_omitted=1: {omitted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
