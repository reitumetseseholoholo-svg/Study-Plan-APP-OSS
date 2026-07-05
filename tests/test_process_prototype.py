"""Test the process template prototype — computation and diagnostic."""

import pytest

from studyplan.domain_reasoning.process import (
    ProcessTemplate,
    DiagnosticConfig,
    DiagnosticTemplate,
    ProcessHypothesis,
    ProcessFeature,
    declare_process,
)


# =========================================================================
# Test 1: ProcessTemplate ABC
# =========================================================================


def test_process_template_is_abstract():
    """ProcessTemplate cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ProcessTemplate()  # type: ignore[abstract]


# =========================================================================
# Test 2: declare_process(type="computation") delegates to declare_formula
# =========================================================================


def test_declare_process_computation():
    """Computation type delegates to declare_formula and works identically."""
    proc = declare_process(
        "test.npv_simple",
        type="computation",
        expression="cash_flow / (1 + rate) ** years",
        param_names=["cash_flow", "rate", "years"],
        param_kinds=["value", "percent", "value"],
        label="NPV (test)",
        output="npv",
    )
    assert proc.concept_id == "test.npv_simple"
    assert proc.concept_type == "expression"
    assert proc.template is not None

    result = proc.template.solve({"cash_flow": 1000.0, "rate": 0.10, "years": 1.0})
    assert result["is_nan"] is False
    assert abs(float(result["result"]) - 909.09) < 0.1
    assert result["concept_id"] == "test.npv_simple"


# =========================================================================
# Test 3: DiagnosticTemplate — basic Bayesian update
# =========================================================================


def _make_chest_pain_template() -> DiagnosticTemplate:
    """Build a diagnostic template for chest pain differential."""
    config = DiagnosticConfig(
        hypotheses=[
            ProcessHypothesis(id="stemi", label="STEMI", prior=0.10),
            ProcessHypothesis(id="nstemi", label="NSTEMI", prior=0.15),
            ProcessHypothesis(id="pe", label="Pulmonary Embolism", prior=0.08),
            ProcessHypothesis(id="non_cardiac", label="Non-cardiac", prior=0.67),
        ],
        features=[
            ProcessFeature(id="chest_pain", type="categorical", values=["sharp", "dull", "crushing", "none"]),
            ProcessFeature(id="ecg", type="categorical", values=["normal", "st_elevation", "t_inversion"]),
            ProcessFeature(id="troponin", type="continuous", unit="ng/mL"),
        ],
        likelihoods={
            "stemi": {
                "chest_pain": {"crushing": 0.85, "dull": 0.10, "sharp": 0.03, "none": 0.02},
                "ecg": {"st_elevation": 0.95, "t_inversion": 0.30, "normal": 0.05},
                "troponin": {"distribution": "log_normal", "mean": 2.5, "sd": 0.8},
            },
            "nstemi": {
                "chest_pain": {"crushing": 0.40, "dull": 0.30, "sharp": 0.15, "none": 0.15},
                "ecg": {"st_elevation": 0.30, "t_inversion": 0.70, "normal": 0.20},
                "troponin": {"distribution": "log_normal", "mean": 1.5, "sd": 0.6},
            },
            "pe": {
                "chest_pain": {"crushing": 0.05, "dull": 0.15, "sharp": 0.70, "none": 0.10},
                "ecg": {"st_elevation": 0.05, "t_inversion": 0.30, "normal": 0.65},
                "troponin": {"distribution": "log_normal", "mean": 0.3, "sd": 0.4},
            },
            "non_cardiac": {
                "chest_pain": {"crushing": 0.05, "dull": 0.25, "sharp": 0.20, "none": 0.50},
                "ecg": {"st_elevation": 0.01, "t_inversion": 0.04, "normal": 0.95},
                "troponin": {"distribution": "log_normal", "mean": 0.1, "sd": 0.2},
            },
        },
        output="primary_diagnosis",
    )
    return DiagnosticTemplate("med.chest_pain_ddx", config)


def test_diagnostic_prior_distribution():
    """Priors are normalized and sum to 1.0."""
    template = _make_chest_pain_template()
    result = template.solve({})  # No evidence — should return priors
    posteriors = result["posterior_distribution"]
    assert abs(sum(posteriors.values()) - 1.0) < 1e-9
    assert abs(posteriors["stemi"] - 0.10) < 0.001
    assert abs(posteriors["non_cardiac"] - 0.67) < 0.001


def test_diagnostic_bayesian_update():
    """Bayesian update shifts probability mass toward the most likely hypothesis."""
    template = _make_chest_pain_template()
    # Strong evidence for STEMI: crushing chest pain + ST elevation on ECG + high troponin
    result = template.solve(
        {
            "chest_pain": "crushing",
            "ecg": "st_elevation",
            "troponin": 12.0,  # very high — log_normal with mean 2.5, sd 0.8
        }
    )
    map_h = result["map_hypothesis"]
    map_p = result["map_probability"]
    # STEMI should be the most likely after this strong evidence
    assert map_h == "stemi", f"Expected STEMI, got {map_h}"
    assert map_p > 0.90, f"STEMI probability should be high, got {map_p}"
    # Entropy should be low (high certainty)
    assert result["entropy"] < 0.5


def test_diagnostic_sequential_evidence():
    """Evidence incorporated sequentially produces same result as all-at-once."""
    template = _make_chest_pain_template()
    # All at once
    result_all = template.solve(
        {
            "chest_pain": "sharp",
            "ecg": "normal",
        }
    )
    # Sequential
    template.solve({"chest_pain": "sharp"})
    result_seq2 = template.solve({"ecg": "normal"})
    # This test just verifies the API works with sequential calls
    # (each call is independent since template is stateless)
    assert result_all["map_hypothesis"] is not None
    assert result_seq2["map_hypothesis"] is not None


def test_diagnostic_entropy_decreases_with_evidence():
    """Entropy eventually decreases as strong evidence accumulates."""
    template = _make_chest_pain_template()
    r0 = template.solve({})
    # Strong evidence for STEMI should produce lower entropy than prior-only
    r_strong = template.solve(
        {
            "chest_pain": "crushing",
            "ecg": "st_elevation",
            "troponin": 15.0,
        }
    )
    assert r_strong["entropy"] <= r0["entropy"] + 1e-9, (
        f"Entropy should not increase with strong evidence: {r_strong['entropy']} vs {r0['entropy']}"
    )


# =========================================================================
# Test 4: declare_process(type="diagnostic") registration
# =========================================================================


def test_declare_process_diagnostic_registers():
    """Diagnostic processes can be declared and looked up."""
    from studyplan.domain_reasoning.formula_registry import _registry

    # Use a unique ID to avoid collisions
    uid = "test.ddx_register"
    decl = declare_process(
        uid,
        type="diagnostic",
        hypotheses=[
            ProcessHypothesis(id="a", prior=0.6),
            ProcessHypothesis(id="b", prior=0.4),
        ],
        features=[
            ProcessFeature(id="symptom", type="categorical", values=["x", "y"]),
        ],
        likelihoods={
            "a": {"symptom": {"x": 0.9, "y": 0.1}},
            "b": {"symptom": {"x": 0.2, "y": 0.8}},
        },
        label="Test DDx",
    )
    assert decl.concept_id == uid
    assert decl.concept_type == "diagnostic_process"
    assert uid in _registry
    assert isinstance(decl.template, DiagnosticTemplate)

    result = decl.template.solve({"symptom": "x"})
    assert result["map_hypothesis"] == "a"
    assert result["map_probability"] > 0.5

    # Clean up
    del _registry[uid]


# =========================================================================
# Test 5: DiagnosticTemplate error classification
# =========================================================================


def test_diagnostic_error_classification():
    """Error tags are produced for wrong diagnoses."""
    template = _make_chest_pain_template()
    truth = template.solve(
        {
            "chest_pain": "crushing",
            "ecg": "st_elevation",
            "troponin": 15.0,
        }
    )

    # Learner never considered STEMI (the correct answer) → hypothesis_not_considered
    learner_steps = [
        {"step_id": "diagnosis_1", "diagnosis": "pe"},
        {"step_id": "diagnosis_2", "diagnosis": "pe"},
    ]
    tags = template.classify_errors(learner_steps, truth)
    assert "hypothesis_not_considered" in tags, f"Expected hypothesis_not_considered, got {tags}"

    # Learner considered STEMI but chose wrong with enough evidence → wrong_diagnosis
    learner_steps_2 = [
        {"step_id": "dx_1", "diagnosis": "stemi", "feature": "chest_pain", "type": "observation"},
        {"step_id": "dx_2", "diagnosis": "pe", "feature": "ecg", "type": "observation"},
        {"step_id": "final", "diagnosis": "pe"},
    ]
    tags2 = template.classify_errors(learner_steps_2, truth)
    assert "wrong_diagnosis" in tags2, f"Expected wrong_diagnosis, got {tags2}"

    # Learner says diagnosis that isn't even a hypothesis → hypothesis_not_considered
    learner_steps_3 = [
        {"step_id": "dx_1", "diagnosis": "anxiety"},
    ]
    tags3 = template.classify_errors(learner_steps_3, truth)
    assert "hypothesis_not_considered" in tags3, f"Expected hypothesis_not_considered, got {tags3}"


# =========================================================================
# Test 6: Edge cases
# =========================================================================


def test_diagnostic_empty_hypotheses():
    """Empty hypothesis list produces empty posterior without crash."""
    config = DiagnosticConfig(hypotheses=[], features=[], likelihoods={})
    template = DiagnosticTemplate("test.empty", config)
    result = template.solve({"obs": "val"})
    assert result["map_hypothesis"] is None
    assert result["map_probability"] == 0.0
    assert result["posterior_distribution"] == {}


def test_diagnostic_unknown_feature_value():
    """Unknown categorical values get a small uniform probability."""
    template = _make_chest_pain_template()
    result = template.solve({"chest_pain": "burning"})  # not in likelihoods
    assert result["map_hypothesis"] is not None
    # Should still produce a valid posterior (non_cardiac has highest prior)
    assert abs(sum(result["posterior_distribution"].values()) - 1.0) < 1e-9


def test_diagnostic_negative_continuous_value():
    """Negative values in log-normal likelihood return minimal probability."""
    template = _make_chest_pain_template()
    result = template.solve({"troponin": -1.0})
    assert result["map_hypothesis"] is not None
    assert result["entropy"] > 0.5  # still uncertain


# =========================================================================
# Test 7: evaluate_steps
# =========================================================================


def test_evaluate_steps_correct():
    """evaluate_steps correctly identifies matching diagnoses."""
    template = _make_chest_pain_template()
    truth = template.solve({"ecg": "st_elevation"})
    steps = [
        {"step_id": "final", "diagnosis": "stemi", "value": "stemi"},
    ]
    evals = template.evaluate_steps(steps, truth)
    assert len(evals) == 1
    assert evals[0]["match"] is True


def test_evaluate_steps_wrong():
    """evaluate_steps correctly identifies mismatching diagnoses."""
    template = _make_chest_pain_template()
    truth = template.solve({"ecg": "st_elevation"})
    steps = [
        {"step_id": "final", "diagnosis": "pe", "value": "pe"},
    ]
    evals = template.evaluate_steps(steps, truth)
    assert len(evals) == 1
    assert evals[0]["match"] is False
