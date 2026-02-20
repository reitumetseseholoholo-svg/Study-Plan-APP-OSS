from studyplan.telemetry.slo import evaluate_latency_slo


def test_evaluate_latency_slo_pass_case():
    report = evaluate_latency_slo(
        [600, 700, 800, 900, 1200, 1300, 1500, 1700],
        p50_target_ms=25000,
        p90_target_ms=60000,
        spread_target_ratio=2.4,
        min_samples=8,
    )
    assert report["status"] == "pass"
    assert report["samples"] == 8
    assert report["p90_latency_ms"] >= report["p50_latency_ms"]


def test_evaluate_latency_slo_fail_case():
    report = evaluate_latency_slo(
        [30000, 35000, 38000, 42000, 91000, 98000, 110000, 120000],
        p50_target_ms=25000,
        p90_target_ms=60000,
        spread_target_ratio=2.4,
        min_samples=8,
    )
    assert report["status"] == "fail"
    assert report["samples"] == 8
    assert report["p90_latency_ms"] >= 90000


def test_evaluate_latency_slo_insufficient_samples():
    report = evaluate_latency_slo(
        [1000, 1100, 1200],
        p50_target_ms=25000,
        p90_target_ms=60000,
        spread_target_ratio=2.4,
        min_samples=8,
    )
    assert report["status"] == "insufficient"
    assert report["samples"] == 3
