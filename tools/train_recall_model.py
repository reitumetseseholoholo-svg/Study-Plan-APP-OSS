#!/usr/bin/env python3
import argparse
import datetime
import json
import math
import os


def _sigmoid(z: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-z))
    except Exception:
        return 0.5


def _log1p_safe(val: float) -> float:
    try:
        return math.log1p(max(0.0, float(val)))
    except Exception:
        return 0.0


def _load_stats(data_path: str) -> dict:
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
        for entry in chapter_stats.values():
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


def _train_logreg(
    X: list[list[float]],
    y: list[int],
    epochs: int,
    lr: float,
    l2: float,
) -> tuple[list[float], float]:
    if not X:
        return [0.0] * 5, 0.0
    n_features = len(X[0])
    weights = [0.0] * n_features
    bias = 0.0
    n = float(len(X))
    for _ in range(max(1, epochs)):
        grad_w = [0.0] * n_features
        grad_b = 0.0
        for xi, yi in zip(X, y):
            z = bias
            for w, x in zip(weights, xi):
                z += w * x
            pred = _sigmoid(z)
            err = pred - float(yi)
            for i in range(n_features):
                grad_w[i] += err * xi[i]
            grad_b += err
        for i in range(n_features):
            grad_w[i] = (grad_w[i] / n) + (l2 * weights[i])
        grad_b = grad_b / n
        for i in range(n_features):
            weights[i] -= lr * grad_w[i]
        bias -= lr * grad_b
    return weights, bias


def main() -> int:
    parser = argparse.ArgumentParser(description="Train recall prediction model from question_stats.")
    parser.add_argument(
        "--data",
        default=os.path.expanduser("~/.config/studyplan/acca_f9/data.json"),
        help="Path to data.json",
    )
    parser.add_argument(
        "--out",
        default=os.path.expanduser("~/.config/studyplan/recall_model.json"),
        help="Output model path",
    )
    parser.add_argument("--epochs", type=int, default=400)
    parser.add_argument("--lr", type=float, default=0.2)
    parser.add_argument("--l2", type=float, default=0.01)
    parser.add_argument("--threshold", type=float, default=0.7)
    args = parser.parse_args()

    stats = _load_stats(args.data)
    X, y = _build_dataset(stats, threshold=float(args.threshold))
    if len(X) < 25:
        print("Not enough samples to train (need 25+).")
        return 1
    weights, bias = _train_logreg(X, y, epochs=int(args.epochs), lr=float(args.lr), l2=float(args.l2))
    model = {
        "version": 1,
        "trained_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "samples": len(X),
        "threshold": float(args.threshold),
        "features": [
            "log1p_attempts",
            "correct_rate",
            "streak",
            "log1p_avg_time_sec",
            "log1p_days_since_last_seen",
        ],
        "weights": weights,
        "intercept": bias,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    print(f"Model saved to {args.out} ({len(X)} samples).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
