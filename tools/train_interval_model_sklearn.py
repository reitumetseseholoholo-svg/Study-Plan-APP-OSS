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


def _load_data(data_path: str) -> dict:
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _build_dataset(data: dict) -> tuple[list[list[float]], list[float]]:
    stats = data.get("question_stats", {}) if isinstance(data, dict) else {}
    srs = data.get("srs_data", {}) if isinstance(data, dict) else {}
    X: list[list[float]] = []
    y: list[float] = []
    today = datetime.date.today()
    if not isinstance(stats, dict) or not isinstance(srs, dict):
        return X, y
    for chapter, chapter_stats in stats.items():
        if not isinstance(chapter_stats, dict):
            continue
        srs_list = srs.get(chapter, [])
        if not isinstance(srs_list, list):
            continue
        for idx_str, entry in chapter_stats.items():
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(idx_str)
            except Exception:
                continue
            if idx < 0 or idx >= len(srs_list):
                continue
            srs_item = srs_list[idx]
            if not isinstance(srs_item, dict):
                continue
            last_review = srs_item.get("last_review")
            if not last_review:
                continue
            try:
                interval = float(srs_item.get("interval", 1) or 1)
            except Exception:
                interval = 1.0
            try:
                efactor = float(srs_item.get("efactor", 2.5) or 2.5)
            except Exception:
                efactor = 2.5
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
                _log1p_safe(max(1.0, interval)),
                max(1.3, min(2.5, efactor)),
            ]
            X.append(features)
            y.append(_log1p_safe(interval))
    return X, y


def main() -> int:
    parser = argparse.ArgumentParser(description="Train interval calibration model (Ridge).")
    parser.add_argument(
        "--data",
        default=os.path.expanduser("~/.config/studyplan/acca_f9/data.json"),
        help="Path to data.json",
    )
    parser.add_argument(
        "--out",
        default=os.path.expanduser("~/.config/studyplan/interval_model.pkl"),
        help="Output model path (.pkl)",
    )
    parser.add_argument("--alpha", type=float, default=1.0)
    args = parser.parse_args()

    data = _load_data(args.data)
    X, y = _build_dataset(data)
    if len(X) < 30:
        print("Not enough samples to train (need 30+).")
        return 1

    try:
        from sklearn.linear_model import Ridge
        import joblib
    except Exception as exc:
        print(f"Missing dependency: {exc}")
        return 2

    model = Ridge(alpha=float(args.alpha))
    model.fit(X, y)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    joblib.dump({"model": model, "feature_count": len(X[0])}, args.out)
    print(f"Model saved to {args.out} ({len(X)} samples).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
