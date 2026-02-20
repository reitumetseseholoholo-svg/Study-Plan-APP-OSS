import json

from studyplan_app import _compute_strict_soak_exit_code, _evaluate_soak_kpi_thresholds


def test_evaluate_soak_kpi_thresholds_passes_when_metrics_meet_thresholds():
    kpi = {
        "samples": 8,
        "p50_latency_ms": 20000.0,
        "p90_latency_ms": 50000.0,
        "latency_spread_ratio": 2.0,
    }
    failures = _evaluate_soak_kpi_thresholds(kpi)
    assert failures == []


def test_evaluate_soak_kpi_thresholds_reports_expected_failures():
    kpi = {
        "samples": 3,
        "p50_latency_ms": 30000.0,
        "p90_latency_ms": 70000.0,
        "latency_spread_ratio": 3.1,
    }
    failures = _evaluate_soak_kpi_thresholds(kpi)
    metrics = {item["metric"] for item in failures}
    assert "samples" in metrics
    assert "p50_latency_ms" in metrics
    assert "p90_latency_ms" in metrics
    assert "latency_spread_ratio" in metrics


def test_compute_strict_soak_exit_code_uses_status_and_kpi(tmp_path):
    path = tmp_path / "soak_last.json"

    payload = {
        "status": "passed",
        "kpi": {
            "samples": 10,
            "p50_latency_ms": 18000.0,
            "p90_latency_ms": 45000.0,
            "latency_spread_ratio": 2.2,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _compute_strict_soak_exit_code(str(path)) == 0

    payload["kpi"]["latency_spread_ratio"] = 3.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _compute_strict_soak_exit_code(str(path)) == 1

    payload["status"] = "failed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _compute_strict_soak_exit_code(str(path)) == 1

    assert _compute_strict_soak_exit_code(str(tmp_path / "missing.json")) == 1
