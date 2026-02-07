#!/usr/bin/env python3
import argparse
import datetime
import json
import math
import os


def _log1p_safe(val: float) -> float:
    try:
        return math.log1p(max(0.0, float(val)))
    except Exception:
        return 0.0


def _resolve_data_path(data_path: str) -> str:
    if data_path and os.path.exists(data_path):
        return data_path
    default_path = os.path.expanduser("~/.config/studyplan/data.json")
    if os.path.exists(default_path):
        return default_path
    fallback = os.path.expanduser("~/.config/studyplan/acca_f9/data.json")
    if os.path.exists(fallback):
        return fallback
    return data_path


def _load_stats(data_path: str) -> dict:
    if not data_path or not os.path.exists(data_path):
        return {}
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    stats = data.get("question_stats", {}) if isinstance(data, dict) else {}
    return stats if isinstance(stats, dict) else {}


def _build_dataset(stats: dict) -> list[list[float]]:
    X: list[list[float]] = []
    for chapter_stats in stats.values():
        if not isinstance(chapter_stats, dict):
            continue
        has_qid = any(str(k).startswith("q:") for k in chapter_stats.keys())
        for key, entry in chapter_stats.items():
            if has_qid and not str(key).startswith("q:"):
                continue
            if not isinstance(entry, dict):
                continue
            try:
                attempts = float(entry.get("attempts", 0) or 0)
            except Exception:
                attempts = 0.0
            if attempts <= 0:
                continue
            try:
                correct = float(entry.get("correct", 0) or 0)
            except Exception:
                correct = 0.0
            try:
                streak = float(entry.get("streak", 0) or 0)
            except Exception:
                streak = 0.0
            try:
                avg_time = float(entry.get("avg_time_sec", 0) or 0.0)
            except Exception:
                avg_time = 0.0
            miss_rate = 1.0 - min(1.0, max(0.0, correct / max(1.0, attempts)))
            streak_factor = 1.0 - min(1.0, max(0.0, streak / 5.0))
            X.append([
                max(0.0, miss_rate),
                _log1p_safe(avg_time),
                max(0.0, streak_factor),
            ])
    return X


def main() -> int:
    parser = argparse.ArgumentParser(description="Train difficulty clustering model (KMeans).")
    parser.add_argument(
        "--data",
        default=os.path.expanduser("~/.config/studyplan/acca_f9/data.json"),
        help="Path to data.json",
    )
    parser.add_argument(
        "--out",
        default=os.path.expanduser("~/.config/studyplan/difficulty_model.pkl"),
        help="Output model path (.pkl)",
    )
    parser.add_argument("--clusters", type=int, default=3)
    args = parser.parse_args()

    data_path = _resolve_data_path(args.data)
    if not data_path or not os.path.exists(data_path):
        print(f"Data file not found: {args.data}")
        return 1
    stats = _load_stats(data_path)
    X = _build_dataset(stats)
    if len(X) < 25:
        print("Not enough samples to train (need 25+).")
        return 1

    try:
        from sklearn.cluster import KMeans
        import joblib
    except Exception as exc:
        print(f"Missing dependency: {exc}")
        return 2

    k = max(2, int(args.clusters))
    model = KMeans(n_clusters=k, n_init="auto", random_state=42)
    model.fit(X)

    # Map clusters to easy/medium/hard by centroid "difficulty" score.
    centers = model.cluster_centers_
    scored = []
    for idx, center in enumerate(centers):
        # higher miss_rate, higher time, higher streak_factor => harder
        score = float(center[0]) + float(center[1]) + float(center[2])
        scored.append((idx, score))
    scored.sort(key=lambda x: x[1])
    label_map = {}
    if k == 2:
        label_map[scored[0][0]] = "easy"
        label_map[scored[1][0]] = "hard"
    else:
        label_map[scored[0][0]] = "easy"
        label_map[scored[-1][0]] = "hard"
        mid = [idx for idx, _ in scored[1:-1]]
        for idx in mid:
            label_map[idx] = "medium"

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    joblib.dump({"model": model, "label_map": label_map}, args.out)
    print(f"Model saved to {args.out} ({len(X)} samples, k={k}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
