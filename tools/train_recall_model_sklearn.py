#!/usr/bin/env python3
import argparse
import datetime
import json
import math
import os
from typing import Any


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


def _recency_weight(days_since: float, half_life_days: float, min_weight: float) -> float:
    half_life = max(1.0, float(half_life_days))
    floor = max(0.0, min(1.0, float(min_weight)))
    ds = max(0.0, float(days_since))
    try:
        decay = math.exp(-math.log(2.0) * ds / half_life)
    except Exception:
        decay = floor
    return max(floor, min(1.0, decay))


def _load_stats(data_path: str) -> dict:
    if not data_path or not os.path.exists(data_path):
        return {}
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    stats = data.get("question_stats", {}) if isinstance(data, dict) else {}
    return stats if isinstance(stats, dict) else {}


def _build_dataset(
    stats: dict,
    threshold: float,
    recency_half_life_days: float,
    recency_min_weight: float,
) -> tuple[list[list[float]], list[int], list[float]]:
    X: list[list[float]] = []
    y: list[int] = []
    w: list[float] = []
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
            w.append(
                _recency_weight(
                    days_since=days_since,
                    half_life_days=recency_half_life_days,
                    min_weight=recency_min_weight,
                )
            )
    return X, y, w


def _safe_prob_list(values: Any, size: int) -> list[float]:
    probs: list[float] = []
    if not isinstance(values, (list, tuple)):
        return [0.5] * size
    for v in values[:size]:
        try:
            p = float(v)
        except Exception:
            p = 0.5
        probs.append(max(0.0, min(1.0, p)))
    if len(probs) < size:
        probs.extend([0.5] * (size - len(probs)))
    return probs


def _parse_c_grid(raw: str, fallback_c: float) -> list[float]:
    values: list[float] = []
    text = str(raw or "").strip()
    if text:
        for part in text.split(","):
            p = part.strip()
            if not p:
                continue
            try:
                v = float(p)
            except Exception:
                continue
            if v > 0:
                values.append(v)
    if not values:
        values = [max(1e-6, float(fallback_c))]
    uniq = sorted({round(v, 10) for v in values})
    return [float(v) for v in uniq]


def _brier_score(y_true: list[int], probs: list[float]) -> float:
    n = max(1, len(y_true))
    total = 0.0
    for yt, p in zip(y_true, probs):
        total += (float(yt) - float(p)) ** 2
    return total / n


def _expected_calibration_error(y_true: list[int], probs: list[float], bins: int = 10) -> float:
    n = max(1, len(y_true))
    b = max(2, int(bins))
    ece = 0.0
    for i in range(b):
        lo = i / b
        hi = (i + 1) / b
        in_bin: list[int] = []
        for idx, p in enumerate(probs):
            if (p >= lo and p < hi) or (i == b - 1 and p == hi):
                in_bin.append(idx)
        if not in_bin:
            continue
        acc = sum(float(y_true[j]) for j in in_bin) / len(in_bin)
        conf = sum(float(probs[j]) for j in in_bin) / len(in_bin)
        ece += (len(in_bin) / n) * abs(acc - conf)
    return float(ece)


def _roc_auc(y_true: list[int], probs: list[float]) -> float | None:
    if len(y_true) < 2:
        return None
    positives = [p for y, p in zip(y_true, probs) if int(y) == 1]
    negatives = [p for y, p in zip(y_true, probs) if int(y) == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = float(len(positives) * len(negatives))
    for pp in positives:
        for pn in negatives:
            if pp > pn:
                wins += 1.0
            elif pp == pn:
                wins += 0.5
    return wins / total if total > 0 else None


def _predict_probs(model: Any, X_holdout: list[list[float]]) -> list[float] | None:
    try:
        raw = model.predict_proba(X_holdout)
    except Exception:
        return None
    probs: list[float] = []
    try:
        for row in raw:
            probs.append(float(row[1]))
    except Exception:
        return None
    return _safe_prob_list(probs, len(X_holdout))


def _load_existing_model(path: str) -> Any | None:
    if not path or not os.path.exists(path):
        return None
    try:
        import joblib
    except Exception:
        return None
    try:
        payload = joblib.load(path)
    except Exception:
        return None
    if isinstance(payload, dict):
        model = payload.get("model")
        if model is not None and hasattr(model, "predict_proba"):
            return model
        return None
    if hasattr(payload, "predict_proba"):
        return payload
    return None


def _resolve_calibration_mode(requested: str, train_size: int) -> str:
    if requested != "auto":
        return requested
    return "isotonic" if train_size >= 500 else "sigmoid"


def _fit_logistic_candidate(
    LogisticRegression: Any,
    CalibratedClassifierCV: Any | None,
    X_train: list[list[float]],
    y_train: list[int],
    w_train: list[float],
    c_val: float,
    max_iter: int,
    class_weight: str | None,
    calibration_mode: str,
) -> Any | None:
    try:
        base = LogisticRegression(
            max_iter=max_iter,
            C=float(c_val),
            class_weight=class_weight,
        )
    except Exception:
        return None

    mode = str(calibration_mode or "none").strip().lower()
    if mode == "none" or CalibratedClassifierCV is None:
        try:
            base.fit(X_train, y_train, sample_weight=w_train)
            return base
        except Exception:
            return None

    positive = sum(1 for v in y_train if int(v) == 1)
    negative = len(y_train) - positive
    min_class = min(positive, negative)
    if min_class < 2:
        try:
            base.fit(X_train, y_train, sample_weight=w_train)
            return base
        except Exception:
            return None

    cv = 3 if min_class >= 3 else 2
    try:
        calibrated = CalibratedClassifierCV(estimator=base, method=mode, cv=cv)
    except TypeError:
        try:
            calibrated = CalibratedClassifierCV(base_estimator=base, method=mode, cv=cv)
        except Exception:
            calibrated = None
    except Exception:
        calibrated = None
    if calibrated is None:
        try:
            base.fit(X_train, y_train, sample_weight=w_train)
            return base
        except Exception:
            return None
    try:
        calibrated.fit(X_train, y_train, sample_weight=w_train)
        return calibrated
    except TypeError:
        try:
            calibrated.fit(X_train, y_train)
            return calibrated
        except Exception:
            pass
    except Exception:
        pass
    try:
        base.fit(X_train, y_train, sample_weight=w_train)
        return base
    except Exception:
        return None


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
    parser.add_argument(
        "--c_grid",
        default="0.25,0.5,1.0,2.0,4.0",
        help="Comma-separated C candidates. Empty uses --C only.",
    )
    parser.add_argument(
        "--class_weight",
        choices=["none", "balanced"],
        default="balanced",
        help="Class weighting strategy for LogisticRegression.",
    )
    parser.add_argument(
        "--calibration",
        choices=["none", "sigmoid", "isotonic", "auto"],
        default="auto",
        help="Probability calibration method for logistic outputs.",
    )
    parser.add_argument(
        "--max_ece",
        type=float,
        default=0.20,
        help="Maximum expected calibration error required for promotion.",
    )
    parser.add_argument("--test_size", type=float, default=0.2)
    parser.add_argument("--random_state", type=int, default=42)
    parser.add_argument(
        "--recency_half_life_days",
        type=float,
        default=30.0,
        help="Half-life in days for sample recency weighting.",
    )
    parser.add_argument(
        "--recency_min_weight",
        type=float,
        default=0.35,
        help="Minimum sample weight after recency decay.",
    )
    parser.add_argument(
        "--min_improvement_brier",
        type=float,
        default=0.001,
        help="Minimum Brier score improvement over current model to promote.",
    )
    parser.add_argument(
        "--min_baseline_gain",
        type=float,
        default=0.002,
        help="Minimum Brier improvement over baseline to allow promotion.",
    )
    args = parser.parse_args()

    data_path = _resolve_data_path(args.data)
    if not data_path or not os.path.exists(data_path):
        print(f"Data file not found: {args.data}")
        return 1
    stats = _load_stats(data_path)
    recency_half_life_days = float(args.recency_half_life_days)
    recency_min_weight = float(args.recency_min_weight)
    X, y, w = _build_dataset(
        stats,
        threshold=float(args.threshold),
        recency_half_life_days=recency_half_life_days,
        recency_min_weight=recency_min_weight,
    )
    if len(X) < 25:
        print("Not enough samples to train (need 25+).")
        return 1

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        try:
            from sklearn.calibration import CalibratedClassifierCV
        except Exception:
            CalibratedClassifierCV = None
        import joblib
    except Exception as exc:
        print(f"Missing dependency: {exc}")
        return 2

    test_size = min(0.5, max(0.1, float(args.test_size)))
    random_state = int(args.random_state)
    y_unique = set(int(v) for v in y)
    stratify = y if len(y_unique) > 1 else None
    try:
        X_train, X_test, y_train, y_test, w_train, w_test = train_test_split(
            X,
            y,
            w,
            test_size=test_size,
            random_state=random_state,
            stratify=stratify,
        )
    except Exception:
        split_idx = max(1, int(len(X) * (1.0 - test_size)))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        w_train, w_test = w[:split_idx], w[split_idx:]
    if not X_test:
        X_test = X_train
        y_test = y_train
        w_test = w_train

    if len(set(int(v) for v in y_train)) < 2:
        print("Not enough class diversity in training split (need both positive and negative labels).")
        return 1

    class_weight: str | None = None if args.class_weight == "none" else "balanced"
    calibration_used = _resolve_calibration_mode(str(args.calibration), len(X_train))
    max_ece = max(0.0, float(args.max_ece))
    c_grid = _parse_c_grid(args.c_grid, float(args.C))

    best_model: Any | None = None
    best_probs: list[float] | None = None
    best_c: float | None = None
    best_brier: float | None = None
    best_auc: float | None = None
    best_ece: float | None = None
    for c_val in c_grid:
        candidate = _fit_logistic_candidate(
            LogisticRegression=LogisticRegression,
            CalibratedClassifierCV=CalibratedClassifierCV,
            X_train=X_train,
            y_train=y_train,
            w_train=w_train,
            c_val=float(c_val),
            max_iter=int(args.max_iter),
            class_weight=class_weight,
            calibration_mode=calibration_used,
        )
        if candidate is None:
            continue
        probs = _predict_probs(candidate, X_test)
        if probs is None:
            continue
        brier = _brier_score(y_test, probs)
        auc = _roc_auc(y_test, probs)
        ece = _expected_calibration_error(y_test, probs, bins=10)
        if (
            best_brier is None
            or brier < best_brier
            or (abs(brier - best_brier) < 1e-9 and (best_ece is None or ece < best_ece))
        ):
            best_model = candidate
            best_probs = probs
            best_c = float(c_val)
            best_brier = float(brier)
            best_auc = auc
            best_ece = float(ece)

    if best_model is None or best_probs is None or best_brier is None or best_c is None or best_ece is None:
        print("Training failed: no valid model candidate produced probabilities.")
        return 1
    model = best_model
    new_probs = best_probs
    new_brier = best_brier
    new_auc = best_auc
    new_ece = best_ece

    train_pos_rate = (sum(int(v) for v in y_train) / max(1, len(y_train))) if y_train else 0.5
    baseline_probs = [train_pos_rate] * len(y_test)
    baseline_brier = _brier_score(y_test, baseline_probs)

    existing_model = _load_existing_model(args.out)
    old_brier = None
    old_auc = None
    old_ece = None
    if existing_model is not None:
        old_probs = _predict_probs(existing_model, X_test)
        if old_probs is not None:
            old_brier = _brier_score(y_test, old_probs)
            old_auc = _roc_auc(y_test, old_probs)
            old_ece = _expected_calibration_error(y_test, old_probs, bins=10)

    beats_baseline = (baseline_brier - new_brier) >= float(args.min_baseline_gain)
    beats_existing = (
        old_brier is None
        or (old_brier - new_brier) >= float(args.min_improvement_brier)
    )
    beats_calibration = new_ece <= max_ece
    should_promote = beats_baseline and beats_existing and beats_calibration

    new_meta = {
        "trained_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sample_count": len(X),
        "train_count": len(X_train),
        "test_count": len(X_test),
        "threshold": float(args.threshold),
        "test_size": test_size,
        "random_state": random_state,
        "class_weight": args.class_weight,
        "calibration": calibration_used,
        "selected_c": round(float(best_c), 6),
        "c_grid": [round(float(v), 6) for v in c_grid],
        "recency_weighting": {
            "half_life_days": round(float(recency_half_life_days), 3),
            "min_weight": round(float(recency_min_weight), 3),
            "train_weight_mean": round(sum(float(v) for v in w_train) / max(1, len(w_train)), 6),
        },
        "metrics": {
            "brier": round(float(new_brier), 6),
            "auc": round(float(new_auc), 6) if new_auc is not None else None,
            "ece": round(float(new_ece), 6),
            "baseline_brier": round(float(baseline_brier), 6),
            "beats_baseline": bool(beats_baseline),
            "old_brier": round(float(old_brier), 6) if old_brier is not None else None,
            "old_auc": round(float(old_auc), 6) if old_auc is not None else None,
            "old_ece": round(float(old_ece), 6) if old_ece is not None else None,
            "beats_existing": bool(beats_existing),
            "max_ece": round(float(max_ece), 6),
            "beats_calibration": bool(beats_calibration),
            "promoted": bool(should_promote),
        },
    }

    if should_promote:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        payload = {"model": model, "meta": new_meta}
        joblib.dump(payload, args.out)
        print(
            f"Model promoted -> {args.out} "
            f"(samples={len(X)}, brier={new_brier:.4f}, ece={new_ece:.4f}, "
            f"auc={new_auc if new_auc is not None else 'n/a'})"
        )
    else:
        print(
            "Model not promoted "
            f"(new_brier={new_brier:.4f}, new_ece={new_ece:.4f}, baseline_brier={baseline_brier:.4f}, "
            f"old_brier={old_brier if old_brier is not None else 'n/a'}, max_ece={max_ece:.4f})."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
