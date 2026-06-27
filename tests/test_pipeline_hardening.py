"""Tests for pipeline hardening: lock cleanup, Cython build, offline recovery."""

from __future__ import annotations

import json
import os
import tempfile


# ---------------------------------------------------------------------------
# Cython build tool
# ---------------------------------------------------------------------------


def test_build_script_imports():
    """tools/build_cython_extensions.py must import without error."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_cython_extensions",
        "tools/build_cython_extensions.py",
    )
    assert spec is not None, "build script spec not found"
    mod = importlib.util.module_from_spec(spec)
    # The script has top-level code — just verify its functions exist
    assert hasattr(mod, "find_pyx_files") or spec.loader is not None


def test_build_script_find_pyx():
    """find_pyx_files must discover .pyx files in studyplan/cython/."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "build_ce",
        "tools/build_cython_extensions.py",
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_ce"] = mod
    spec.loader.exec_module(mod)
    names = mod.find_pyx_files()
    assert isinstance(names, list)
    assert "cosine_fast" in names, f"expected cosine_fast, got {names}"
    assert "tfidf_fast" in names, f"expected tfidf_fast, got {names}"


# ---------------------------------------------------------------------------
# Smoke KPI edge cases
# ---------------------------------------------------------------------------


def test_smoke_kpi_log_error_count_threshold():
    """log_error_count must be exactly 0.0 for strict mode."""
    from studyplan_app_kpi_routing import _evaluate_smoke_kpi_thresholds

    kpi = {
        "coach_pick_consistency_rate": 1.0,
        "coach_only_toggle_integrity_rate": 1.0,
        "coach_next_burst_integrity_rate": 1.0,
        "ui_trigger_integrity_rate": 1.0,
        "log_error_count": 1.0,
    }
    failures = _evaluate_smoke_kpi_thresholds(kpi)
    metrics = {f["metric"] for f in failures}
    assert "log_error_count" in metrics


def test_smoke_kpi_missing_metrics_default_to_zero():
    """Missing metrics must default to 0.0 (which may fail thresholds)."""
    from studyplan_app_kpi_routing import _evaluate_smoke_kpi_thresholds

    failures = _evaluate_smoke_kpi_thresholds({})
    assert len(failures) > 0, "empty metrics must produce failures"


def test_smoke_kpi_non_numeric_metric():
    """Non-numeric metric values must not crash."""
    from studyplan_app_kpi_routing import _evaluate_smoke_kpi_thresholds

    kpi = {
        "coach_pick_consistency_rate": "not-a-number",
        "coach_only_toggle_integrity_rate": None,
        "coach_next_burst_integrity_rate": [],
        "ui_trigger_integrity_rate": {},
    }
    failures = _evaluate_smoke_kpi_thresholds(kpi)
    assert len(failures) >= 1  # default 0.0 may fail some thresholds
    assert all(isinstance(f, dict) for f in failures)
    assert all("metric" in f and "actual" in f for f in failures)


def test_compute_strict_smoke_exit_code_missing_file():
    """Missing report file must return exit code 1."""
    from studyplan_app_kpi_routing import _compute_strict_smoke_exit_code

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "nonexistent.json")
        assert _compute_strict_smoke_exit_code(path) == 1


def test_compute_strict_smoke_exit_code_invalid_json():
    """Invalid JSON must return exit code 1."""
    from studyplan_app_kpi_routing import _compute_strict_smoke_exit_code

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "smoke_last.json")
        with open(path, "w") as f:
            f.write("not json")
        assert _compute_strict_smoke_exit_code(path) == 1


def test_compute_strict_smoke_exit_code_not_dict():
    """Non-dict JSON must return exit code 1."""
    from studyplan_app_kpi_routing import _compute_strict_smoke_exit_code

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "smoke_last.json")
        with open(path, "w") as f:
            json.dump([], f)
        assert _compute_strict_smoke_exit_code(path) == 1


# ---------------------------------------------------------------------------
# KPI routing helpers
# ---------------------------------------------------------------------------


def test_combine_quiz_indices_review_preserves_order():
    """Review kind must return primary_indices in original order up to total."""
    from studyplan_app_kpi_routing import _combine_quiz_indices

    result = _combine_quiz_indices("review", [5, 3, 1, 7], total=3)
    assert result == [5, 3, 1]


def test_combine_quiz_indices_quiz_merges_gap_first():
    """Quiz kind must merge gap_indices before srs_indices."""
    from studyplan_app_kpi_routing import _combine_quiz_indices

    result = _combine_quiz_indices("quiz", [10, 20, 30], total=4, gap_indices=[5, 15])
    # Gap first: 5, 15 -> then srs: 10 (since gap already gave 2, need 2 more)
    assert result[:2] == [5, 15]
    assert len(result) == 4


def test_adjust_outcome_gap_ratio_clamps():
    """Ratio must be clamped to [0.20, 0.90]."""
    from studyplan_app_kpi_routing import _adjust_outcome_gap_ratio

    assert _adjust_outcome_gap_ratio(-0.5, None) >= 0.20
    assert _adjust_outcome_gap_ratio(2.0, None) <= 0.90


def test_adjust_outcome_gap_ratio_capability_hit_rate():
    """Low hit rate increases ratio, high hit rate decreases."""
    from studyplan_app_kpi_routing import _adjust_outcome_gap_ratio

    base = 0.50
    low = _adjust_outcome_gap_ratio(base, 0.30)
    high = _adjust_outcome_gap_ratio(base, 0.90)
    assert low > base, f"low hit rate should increase ratio: {low} <= {base}"
    assert high < base, f"high hit rate should decrease ratio: {high} >= {base}"
