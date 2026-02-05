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


def _build_dataset(stats: dict, threshold: float) -> tuple[list[list[float]], list[int]]:
    X: list[list[float]] = []
    y: list[int] = []
    today = datetime.date.today()
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
            last_seen = entry.get("last_seen")
            days_since = 999.0
            if isinstance(last_seen, str) and last_seen:
                try:
                    last_date = datetime.date.fromisoformat(last_seen)
                    days_since = float((today - last_date).days)
                except Exception:
                    days_since = 999.0
            correct_rate = 0.0 if attempts <= 0 else (correct / max(1.0, attempts))
            features = [
                _log1p_safe(attempts),
                max(0.0, correct_rate),
                max(0.0, streak),
                _log1p_safe(avg_time),
                _log1p_safe(days_since),
            ]
            X.append(features)
            y.append(1 if correct_rate >= threshold else 0)
    return X, y


def main() -> int:
    parser = argparse.ArgumentParser(description="Train recall prediction model using scikit-learn.")
    parser.add_argument(
        "--data",
        default=os.path.expanduser("~/.config/studyplan/acca_f9/data.json"),
        help="Path to data.json",
    )
    parser.add_argument(
        "--out",
        default=os.path.expanduser("~/.config/studyplan/recall_model.pkl"),
        help="Output model path (.pkl)",
    )
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--max_iter", type=int, default=400)
    parser.add_argument("--C", type=float, default=1.0)
    args = parser.parse_args()

    data_path = _resolve_data_path(args.data)
    if not data_path or not os.path.exists(data_path):
        print(f"Data file not found: {args.data}")
        return 1
    stats = _load_stats(data_path)
    X, y = _build_dataset(stats, threshold=float(args.threshold))
    if len(X) < 25:
        print("Not enough samples to train (need 25+).")
        return 1

    try:
        from sklearn.linear_model import LogisticRegression
        import joblib
    except Exception as exc:
        print(f"Missing dependency: {exc}")
        return 2

    model = LogisticRegression(max_iter=int(args.max_iter), C=float(args.C))
    model.fit(X, y)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    joblib.dump(model, args.out)
    print(f"Model saved to {args.out} ({len(X)} samples).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
