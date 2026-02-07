import json

from studyplan_app import _compute_strict_smoke_exit_code, _evaluate_smoke_kpi_thresholds


def test_evaluate_smoke_kpi_thresholds_passes_when_metrics_meet_thresholds():
    kpi = {
        "coach_pick_consistency_rate": 0.999,
        "coach_only_toggle_integrity_rate": 1.0,
        "coach_next_burst_integrity_rate": 1.0,
        "ui_trigger_integrity_rate": 1.0,
    }
    failures = _evaluate_smoke_kpi_thresholds(kpi)
    assert failures == []


def test_evaluate_smoke_kpi_thresholds_reports_expected_failures():
    kpi = {
        "coach_pick_consistency_rate": 0.95,
        "coach_only_toggle_integrity_rate": 0.98,
        "coach_next_burst_integrity_rate": 1.0,
        "ui_trigger_integrity_rate": 0.9,
    }
    failures = _evaluate_smoke_kpi_thresholds(kpi)
    metrics = {item["metric"] for item in failures}
    assert "coach_pick_consistency_rate" in metrics
    assert "coach_only_toggle_integrity_rate" in metrics
    assert "coach_next_burst_integrity_rate" not in metrics
    assert "ui_trigger_integrity_rate" in metrics


def test_compute_strict_smoke_exit_code_uses_status_and_kpi(tmp_path):
    path = tmp_path / "smoke_last.json"

    # Passing status + passing KPI -> success.
    payload = {
        "status": "passed",
        "kpi": {
            "coach_pick_consistency_rate": 1.0,
            "coach_only_toggle_integrity_rate": 1.0,
            "coach_next_burst_integrity_rate": 1.0,
            "ui_trigger_integrity_rate": 1.0,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _compute_strict_smoke_exit_code(str(path)) == 0

    # Passed status but failing KPI should fail strict mode.
    payload["kpi"]["coach_pick_consistency_rate"] = 0.5
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _compute_strict_smoke_exit_code(str(path)) == 1

    # Explicit failed status should fail strict mode.
    payload["status"] = "failed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert _compute_strict_smoke_exit_code(str(path)) == 1

    # Missing report should fail strict mode.
    assert _compute_strict_smoke_exit_code(str(tmp_path / "missing.json")) == 1
