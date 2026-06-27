"""Tests for the step matcher — learner working extraction and step comparison."""

from studyplan.domain_reasoning.step_matcher import (
    parse_learner_workings,
    match_learner_steps,
    compute_step_error_tags,
    _label_similarity,
    _normalize_label,
    _values_match,
)


class TestParseLearnerWorkings:
    def test_empty(self):
        assert parse_learner_workings("") == []
        assert parse_learner_workings("  ") == []
        assert parse_learner_workings(None) == []

    def test_simple_label_equals_value(self):
        result = parse_learner_workings("WACC = 11.2%")
        assert len(result) == 1
        assert "wacc" in result[0]["step_id"]
        assert result[0]["value"] == 11.2

    def test_label_equals_expression_equals_value(self):
        result = parse_learner_workings("Cost of equity = 5% + 1.2*(10%-5%) = 11%")
        assert len(result) >= 1
        assert result[-1]["value"] == 11.0

    def test_multiline_workings(self):
        text = (
            "WACC = 5% + 1.2*(10%-5%) = 11%\nPV of Year 1 = 1000/1.1 = 909.09\nNPV = -5000 + 909.09 + 826.45 = 735.54"
        )
        result = parse_learner_workings(text)
        assert len(result) >= 3
        labels = [r["step_id"] for r in result]
        assert any("wacc" in item for item in labels)
        assert any("pv" in item for item in labels)
        assert any("npv" in item for item in labels)

    def test_label_colon_value(self):
        result = parse_learner_workings("Cost of equity: 11.2%")
        assert len(result) == 1
        assert result[0]["value"] == 11.2

    def test_parenthesized_parts(self):
        result = parse_learner_workings("(a) WACC = 11.2%\n(b) NPV = 735.54")
        assert len(result) >= 2
        labels = [r["step_id"] for r in result]
        assert any("wacc" in item for item in labels)
        assert any("npv" in item for item in labels)

    def test_currency_symbols_handled(self):
        result = parse_learner_workings("Total PV = $1,234.56")
        assert len(result) == 1
        assert abs(result[0]["value"] - 1234.56) < 0.01

    def test_duplicate_values_deduplicated(self):
        result = parse_learner_workings("x = 10\nTotal = 10")
        assert len(result) <= 2

    def test_ignore_small_integers_in_context(self):
        result = parse_learner_workings("Year 1 cash flow = 100")
        assert len(result) >= 1
        assert result[0]["value"] == 100

    def test_context_with_formulas(self):
        text = "Asset Beta = 0.8 * (1 + (1-0.25) * 0.5) = 1.1"
        result = parse_learner_workings(text)
        assert len(result) >= 1
        assert abs(result[-1]["value"] - 1.1) < 0.01


class TestNormalizeLabel:
    def test_basic_normalize(self):
        assert "wacc" in _normalize_label("WACC")
        assert "npv" in _normalize_label("NPV")
        assert "irr" in _normalize_label("IRR")

    def test_known_mappings(self):
        assert "pv" in _normalize_label("PV of Year 1")
        assert "npv" in _normalize_label("Net Present Value")
        assert "cost_equity" in _normalize_label("Cost of equity")
        assert "receivables_days" in _normalize_label("Receivable days")

    def test_fallback(self):
        assert _normalize_label("!@#$%") == "unknown"


class TestValuesMatch:
    def test_exact_match(self):
        assert _values_match(11.2, 11.2)

    def test_within_tolerance(self):
        assert _values_match(100.0, 101.5)  # 1.5% < 2%

    def test_outside_tolerance(self):
        assert not _values_match(100.0, 105.0)  # 5% > 2%

    def test_nan_handling(self):
        assert not _values_match(float("nan"), 100.0)
        assert not _values_match(100.0, float("nan"))

    def test_custom_tolerance(self):
        assert _values_match(100.0, 104.0, tolerance=0.05)
        assert not _values_match(100.0, 110.0, tolerance=0.05)


class TestLabelSimilarity:
    def test_exact_match(self):
        assert _label_similarity("wacc", "wacc") == 1.0

    def test_word_overlap(self):
        sim = _label_similarity("cost_of_equity", "cost_equity")
        assert 0.3 < sim < 1.0

    def test_no_overlap(self):
        assert _label_similarity("wacc", "npv") == 0.0


class TestMatchLearnerSteps:
    def test_empty_truth(self):
        assert match_learner_steps([], []) == []

    def test_simple_match(self):
        truth = [{"step_id": "wacc", "value": 11.2, "description": "WACC calculation"}]
        learner = [{"step_id": "wacc", "value": 11.2, "raw_label": "WACC"}]
        matches = match_learner_steps(truth, learner)
        assert len(matches) == 1
        assert matches[0]["match"] is True
        assert matches[0]["actual"] == 11.2

    def test_mismatch(self):
        truth = [{"step_id": "wacc", "value": 11.2, "description": "WACC calculation"}]
        learner = [{"step_id": "wacc", "value": 9.8, "raw_label": "WACC"}]
        matches = match_learner_steps(truth, learner)
        assert len(matches) == 1
        assert matches[0]["match"] is False

    def test_partial_match(self):
        truth = [{"step_id": "wacc", "value": 11.2, "description": "WACC"}]
        learner = [{"step_id": "cost_of_equity", "value": 11.2, "raw_label": "Cost of equity"}]
        matches = match_learner_steps(truth, learner)
        assert len(matches) == 1
        # Should match because value matches and label has some overlap
        assert matches[0]["match"] is True

    def test_missing_learner_value(self):
        truth = [{"step_id": "wacc", "value": 11.2, "description": "WACC"}]
        matches = match_learner_steps(truth, [])
        assert len(matches) == 1
        assert matches[0]["match"] is False
        assert matches[0]["actual"] is None

    def test_multiple_steps(self):
        truth = [
            {"step_id": "wacc", "value": 11.2, "description": "WACC"},
            {"step_id": "pv_year_1", "value": 909.09, "description": "PV year 1"},
        ]
        learner = [
            {"step_id": "wacc", "value": 11.0, "raw_label": "WACC"},
            {"step_id": "pv_yr_1", "value": 909.09, "raw_label": "PV yr 1"},
        ]
        matches = match_learner_steps(truth, learner)
        assert len(matches) == 2
        assert matches[0]["step_id"] == "wacc"
        assert matches[1]["step_id"] == "pv_year_1"

    def test_no_value_in_truth_step(self):
        truth = [{"step_id": "wacc", "description": "Conceptual step"}]
        matches = match_learner_steps(truth, [])
        assert len(matches) == 1
        assert matches[0]["match"] is False
        assert matches[0]["expected"] is None


class TestComputeStepErrorTags:
    def test_no_errors(self):
        matches = [
            {"step_id": "wacc", "match": True, "expected": 11.2, "actual": 11.2},
            {"step_id": "npv", "match": True, "expected": 735.0, "actual": 735.0},
        ]
        assert compute_step_error_tags(matches) == []

    def test_some_errors(self):
        matches = [
            {"step_id": "wacc", "match": True, "expected": 11.2, "actual": 11.2},
            {"step_id": "npv", "match": False, "expected": 735.0, "actual": 700.0},
        ]
        tags = compute_step_error_tags(matches)
        assert "step_npv_mismatch" in tags
        assert "step_wacc_mismatch" not in tags

    def test_empty_step_id_skipped(self):
        matches = [
            {"step_id": "", "match": False, "expected": 11.2, "actual": 10.0},
        ]
        assert compute_step_error_tags(matches) == []

    def test_all_fail(self):
        matches = [
            {"step_id": "wacc", "match": False},
            {"step_id": "npv", "match": False},
        ]
        tags = compute_step_error_tags(matches)
        assert len(tags) == 2
        assert "step_wacc_mismatch" in tags
        assert "step_npv_mismatch" in tags


class TestIntegrationWithEvaluator:
    """End-to-end: parse learner workings → match with truth → get step eval."""

    def test_wacc_workings_parsed_and_matched(self):
        workings = "Cost of equity = 5% + 1.2*(10%-5%) = 11%\nCost of debt = 6% * (1-0.25) = 4.5%"
        truth_steps = [
            {"step_id": "cost_of_equity", "value": 11.0, "description": "Cost of equity via CAPM"},
            {"step_id": "cost_of_debt", "value": 4.5, "description": "After-tax cost of debt"},
        ]

        parsed = parse_learner_workings(workings)
        assert len(parsed) >= 2

        matches = match_learner_steps(truth_steps, parsed)
        assert len(matches) == 2
        assert matches[0]["step_id"] == "cost_of_equity"
        assert matches[0]["match"] is True
        assert matches[1]["step_id"] == "cost_of_debt"
        assert matches[1]["match"] is True

        tags = compute_step_error_tags(matches)
        assert tags == []

    def test_pv_multi_year_workings(self):
        workings = "PV yr 1 = 1000/1.1 = 909.09\nPV yr 2 = 1500/1.21 = 1239.67\nTotal PV = 909.09 + 1239.67 = 2148.76"
        truth_steps = [
            {"step_id": "pv_year_1", "value": 909.09, "description": "PV year 1"},
            {"step_id": "pv_year_2", "value": 1239.67, "description": "PV year 2"},
            {"step_id": "total_pv", "value": 2148.76, "description": "Total PV"},
        ]

        parsed = parse_learner_workings(workings)
        assert len(parsed) >= 3

        matches = match_learner_steps(truth_steps, parsed)
        assert len(matches) == 3
        assert all(m["match"] for m in matches)

    def test_step_mismatch_detected(self):
        workings = "WACC = 5% + 1.2*(10%-5%) = 11%\nNPV = -5000 + 909 = 5909"
        truth_steps = [
            {"step_id": "wacc", "value": 11.0, "description": "WACC"},
            {"step_id": "npv", "value": 735.54, "description": "NPV calculation"},
        ]

        parsed = parse_learner_workings(workings)
        matches = match_learner_steps(truth_steps, parsed)
        assert len(matches) == 2
        # WACC is correct
        assert matches[0]["step_id"] == "wacc"
        assert matches[0]["match"] is True
        # NPV is wrong (5909 vs 735.54)
        assert matches[1]["step_id"] == "npv"
        assert matches[1]["match"] is False

        tags = compute_step_error_tags(matches)
        assert "step_npv_mismatch" in tags
