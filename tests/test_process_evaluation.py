"""Test the evaluation process template — multi-criteria weighted judgement."""

from studyplan.domain_reasoning.process import (
    EvaluationConfig,
    EvaluationCriterion,
    EvaluationTemplate,
    declare_process,
    ProcessTemplate,
)


# =========================================================================
# Helpers
# =========================================================================


def _gc_template() -> EvaluationTemplate:
    """Audit going-concern assessment — a classic ACCA AA / AAA scenario."""
    config = EvaluationConfig(
        criteria=[
            EvaluationCriterion(id="liquidity", label="Liquidity position", weight=0.30),
            EvaluationCriterion(id="profitability", label="Profitability trend", weight=0.25),
            EvaluationCriterion(id="governance", label="Governance quality", weight=0.20),
            EvaluationCriterion(id="market", label="Market conditions", weight=0.15),
            EvaluationCriterion(id="forecast", label="Forecast reliability", weight=0.10),
        ],
        candidates=["going_concern", "break_up"],
        output="gc_opinion",
    )
    return EvaluationTemplate("audit.gc_assessment", config)


# =========================================================================
# Test 1: ProcessTemplate ABC
# =========================================================================


def test_evaluation_is_process_template():
    """EvaluationTemplate is a valid ProcessTemplate subclass."""
    template = _gc_template()
    assert isinstance(template, ProcessTemplate)
    # Can instantiate directly (not abstract)
    _ = template.solve({})


# =========================================================================
# Test 2: Scoring and ranking
# =========================================================================


def test_evaluation_simple_majority():
    """Candidate with higher weighted scores wins."""
    template = _gc_template()
    result = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    assert result["judgment"] == "going_concern"
    assert result["scores"]["going_concern"] > result["scores"]["break_up"]
    assert result["confidence"] > 0.0


def test_evaluation_strong_runner_up():
    """Runner-up with close scores produces low confidence."""
    template = _gc_template()
    result = template.solve(
        {
            "liquidity": {"going_concern": 0.51, "break_up": 0.49},
            "profitability": {"going_concern": 0.52, "break_up": 0.48},
            "governance": {"going_concern": 0.50, "break_up": 0.50},
            "market": {"going_concern": 0.49, "break_up": 0.51},
            "forecast": {"going_concern": 0.50, "break_up": 0.50},
        }
    )
    assert result["judgment"] == "going_concern"
    assert result["confidence"] < 0.05  # very tight


def test_evaluation_weighted_scoring():
    """Weight distribution correctly affects the outcome."""
    template = _gc_template()

    # Scenario A: strong liquidity (highest weight) favours GC, but all other
    # criteria heavily favour break_up with wider margins → break_up wins
    result_a = template.solve(
        {
            "liquidity": {"going_concern": 0.95, "break_up": 0.05},
            "profitability": {"going_concern": 0.10, "break_up": 0.90},
            "governance": {"going_concern": 0.15, "break_up": 0.85},
            "market": {"going_concern": 0.30, "break_up": 0.70},
            "forecast": {"going_concern": 0.40, "break_up": 0.60},
        }
    )
    # GC:  0.30*0.95 + 0.25*0.10 + 0.20*0.15 + 0.15*0.30 + 0.10*0.40 = 0.425
    # BU:  0.30*0.05 + 0.25*0.90 + 0.20*0.85 + 0.15*0.70 + 0.10*0.60 = 0.575
    assert result_a["judgment"] == "break_up"

    # Scenario B: swap — going concern wins again
    result_b = template.solve(
        {
            "liquidity": {"going_concern": 0.95, "break_up": 0.05},
            "profitability": {"going_concern": 0.80, "break_up": 0.20},
            "governance": {"going_concern": 0.70, "break_up": 0.30},
            "market": {"going_concern": 0.40, "break_up": 0.60},
            "forecast": {"going_concern": 0.60, "break_up": 0.40},
        }
    )
    assert result_b["judgment"] == "going_concern"


# =========================================================================
# Test 3: Ranked output and contributions
# =========================================================================


def test_evaluation_ranked_order():
    """Ranked list is ordered from highest to lowest score."""
    template = _gc_template()
    result = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    assert len(result["ranked"]) == 2
    assert result["ranked"][0][0] == "going_concern"
    assert result["ranked"][0][1] >= result["ranked"][1][1]


def test_evaluation_contributions():
    """Contributions detail how each criterion affected each candidate."""
    template = _gc_template()
    result = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    assert len(result["contributions"]) > 0
    # Each contribution has criterion, candidate, weight, score, weighted_contribution
    for c in result["contributions"]:
        assert "criterion" in c
        assert "candidate" in c
        assert "weight" in c
        assert "score" in c
        assert "weighted_contribution" in c


# =========================================================================
# Test 4: Justification (top drivers)
# =========================================================================


def test_evaluation_justification():
    """Justification identifies criteria that most strongly differentiate top choice."""
    template = _gc_template()
    result = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.5, "break_up": 0.5},  # neutral
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    assert len(result["justification"]) > 0
    # Liquidity should be the top driver (biggest weighted difference)
    top_driver = result["justification"][0]
    assert top_driver["criterion"] == "liquidity"
    assert top_driver["difference"] > 0.0


# =========================================================================
# Test 5: Entropy
# =========================================================================


def test_evaluation_entropy():
    """Tied scores produce high entropy; landslide produces low entropy."""
    template = _gc_template()

    # Landslide
    landslide = template.solve(
        {
            "liquidity": {"going_concern": 0.99, "break_up": 0.01},
            "profitability": {"going_concern": 0.99, "break_up": 0.01},
            "governance": {"going_concern": 0.99, "break_up": 0.01},
            "market": {"going_concern": 0.99, "break_up": 0.01},
            "forecast": {"going_concern": 0.99, "break_up": 0.01},
        }
    )
    assert landslide["entropy"] < 0.3

    # Dead heat
    tied = template.solve(
        {
            "liquidity": {"going_concern": 0.5, "break_up": 0.5},
            "profitability": {"going_concern": 0.5, "break_up": 0.5},
            "governance": {"going_concern": 0.5, "break_up": 0.5},
            "market": {"going_concern": 0.5, "break_up": 0.5},
            "forecast": {"going_concern": 0.5, "break_up": 0.5},
        }
    )
    assert tied["entropy"] > 0.9  # near-maximum for 2 candidates


# =========================================================================
# Test 6: Error classification
# =========================================================================


def test_evaluation_wrong_judgment():
    """Wrong_judgment tag fires when final answer doesn't match truth."""
    template = _gc_template()
    truth = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    learner_steps = [
        {"step_id": "s1", "judgment": "break_up", "criterion": "market", "candidate": "break_up", "score": 0.6},
    ]
    tags = template.classify_errors(learner_steps, truth)
    assert "wrong_judgment" in tags, f"Expected wrong_judgment, got {tags}"


def test_evaluation_missing_criterion():
    """Missing_criterion tag fires when learner didn't consider a declared criterion."""
    template = _gc_template()
    truth = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    # Learner only considered liquidity and market — missed profitability, governance, forecast
    learner_steps = [
        {"step_id": "s1", "criterion": "liquidity", "candidate": "going_concern", "score": 0.9},
        {"step_id": "s2", "criterion": "market", "candidate": "break_up", "score": 0.6},
        {"step_id": "final", "judgment": "going_concern"},
    ]
    tags = template.classify_errors(learner_steps, truth)
    assert "missing_criterion" in tags


def test_evaluation_no_tags_when_correct():
    """No error tags when the learner's judgment matches truth."""
    template = _gc_template()
    truth = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    learner_steps = [
        {"step_id": "s1", "criterion": "liquidity", "candidate": "going_concern", "score": 0.9},
        {"step_id": "s2", "criterion": "profitability", "candidate": "going_concern", "score": 0.8},
        {"step_id": "s3", "criterion": "governance", "candidate": "going_concern", "score": 0.7},
        {"step_id": "s4", "criterion": "market", "candidate": "break_up", "score": 0.6},
        {"step_id": "s5", "criterion": "forecast", "candidate": "going_concern", "score": 0.6},
        {"step_id": "final", "judgment": "going_concern"},
    ]
    tags = template.classify_errors(learner_steps, truth)
    assert tags == [], f"Expected no error tags, got {tags}"


# =========================================================================
# Test 7: Expected Information Gain
# =========================================================================


def test_evaluation_eig_positive():
    """EIG for an unresolved criterion is positive when scores are uncertain."""
    template = _gc_template()
    tied_scores = {"going_concern": 0.5, "break_up": 0.5}
    eig = template.expected_information_gain(tied_scores, "liquidity")
    assert eig > 0.0, f"Expected positive EIG for uncertain state, got {eig}"


def test_evaluation_eig_zero_when_certain():
    """EIG is zero when the outcome is already certain."""
    template = _gc_template()
    certain_scores = {"going_concern": 1.0, "break_up": 0.0}
    eig = template.expected_information_gain(certain_scores, "liquidity")
    assert eig == 0.0


def test_evaluation_eig_empty():
    """EIG is zero when no scores are provided."""
    template = _gc_template()
    eig = template.expected_information_gain({}, "liquidity")
    assert eig == 0.0


# =========================================================================
# Test 8: evaluate_steps
# =========================================================================


def test_evaluation_evaluate_steps_correct():
    """evaluate_steps correctly identifies matching judgments."""
    template = _gc_template()
    truth = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    steps = [{"step_id": "final", "judgment": "going_concern"}]
    evals = template.evaluate_steps(steps, truth)
    assert evals[0]["match"] is True


def test_evaluation_evaluate_steps_wrong():
    """evaluate_steps correctly identifies mismatching judgments."""
    template = _gc_template()
    truth = template.solve(
        {
            "liquidity": {"going_concern": 0.9, "break_up": 0.1},
            "profitability": {"going_concern": 0.8, "break_up": 0.2},
            "governance": {"going_concern": 0.7, "break_up": 0.3},
            "market": {"going_concern": 0.4, "break_up": 0.6},
            "forecast": {"going_concern": 0.6, "break_up": 0.4},
        }
    )
    steps = [{"step_id": "final", "judgment": "break_up"}]
    evals = template.evaluate_steps(steps, truth)
    assert evals[0]["match"] is False


# =========================================================================
# Test 9: declare_process(type="evaluation")
# =========================================================================


def test_declare_process_evaluation_registers():
    """Evaluation processes can be declared and looked up."""
    from studyplan.domain_reasoning.formula_registry import _registry

    uid = "test.eval_register"
    decl = declare_process(
        uid,
        type="evaluation",
        criteria=[
            EvaluationCriterion(id="c1", weight=0.6),
            EvaluationCriterion(id="c2", weight=0.4),
        ],
        candidates=["a", "b"],
        label="Test Eval",
    )
    assert decl.concept_id == uid
    assert decl.concept_type == "evaluation_process"
    assert uid in _registry
    assert isinstance(decl.template, EvaluationTemplate)

    result = decl.template.solve(
        {
            "c1": {"a": 0.9, "b": 0.1},
            "c2": {"a": 0.3, "b": 0.7},
        }
    )
    assert result["judgment"] == "a"  # 0.9*0.6 + 0.3*0.4 = 0.66 vs 0.1*0.6 + 0.7*0.4 = 0.34

    del _registry[uid]


# =========================================================================
# Test 10: Edge cases
# =========================================================================


def test_evaluation_no_candidates():
    """Empty candidates produce None judgment."""
    config = EvaluationConfig(criteria=[], candidates=[])
    template = EvaluationTemplate("test.empty", config)
    result = template.solve({})
    assert result["judgment"] is None
    assert result["scores"] == {}
    assert result["confidence"] == 0.0


def test_evaluation_single_candidate():
    """Single candidate always wins."""
    config = EvaluationConfig(
        criteria=[EvaluationCriterion(id="c1", weight=1.0)],
        candidates=["only_option"],
    )
    template = EvaluationTemplate("test.solo", config)
    result = template.solve({"c1": {"only_option": 0.5}})
    assert result["judgment"] == "only_option"
    assert result["scores"]["only_option"] == 0.5


def test_evaluation_clamp_to_range():
    """Scores exceeding the declared range are clamped."""
    config = EvaluationConfig(
        criteria=[
            EvaluationCriterion(id="c1", weight=1.0, score_range=(0.0, 1.0)),
        ],
        candidates=["a"],
    )
    template = EvaluationTemplate("test.clamp", config)
    result = template.solve({"c1": {"a": 5.0}})  # outside range
    assert result["scores"]["a"] == 1.0  # clamped to max
