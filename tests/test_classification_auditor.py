"""Tests for the ClassificationAuditor — payload-based tree topology."""

from __future__ import annotations

from typing import Any

from studyplan.domain_reasoning.concept_types.classification_concept import (
    Branch,
    ClassificationConfig,
    ClassificationNode,
    ClassificationTemplate,
)

from studyplan.cci import (
    CognitiveRuntime,
    ClassificationAuditor,
)
from studyplan.frontends.finance import ClassificationProcess


def _shallow_tree(label: str) -> ClassificationTemplate:
    root = ClassificationNode(
        question="Assess",
        branches=[
            Branch(condition="score > 50", result=label),
            Branch(condition="True", result="other"),
        ],
    )
    return ClassificationTemplate(
        "test.shallow",
        ClassificationConfig(tree=root, output_slot="result"),
    )


def _deep_tree(label: str) -> ClassificationTemplate:
    root = ClassificationNode(
        question="Assess",
        branches=[
            Branch(
                condition="score > 0",
                children=[
                    Branch(
                        condition="score > 30",
                        children=[
                            Branch(condition="score > 50", result=label),
                            Branch(condition="True", result="medium"),
                        ],
                    ),
                    Branch(condition="True", result="low"),
                ],
            ),
            Branch(condition="True", result="invalid"),
        ],
    )
    return ClassificationTemplate(
        "test.deep",
        ClassificationConfig(tree=root, output_slot="result"),
    )


def _execute(template: ClassificationTemplate, inputs: dict[str, Any]) -> dict[str, Any]:
    runtime = CognitiveRuntime()
    process = ClassificationProcess(template)
    trace = runtime.execute(process, inputs)
    auditor = ClassificationAuditor()
    return auditor.interpret(trace, concept_id=template.concept_id)


# =========================================================================
# Single-level tree
# =========================================================================


def test_auditor_shallow_tree_depth() -> None:
    result = _execute(_shallow_tree("high_risk"), {"score": 80})
    assert result["tree_depth"] == 1
    assert result["decision_count"] == 1


def test_auditor_shallow_tree_matched_conditions() -> None:
    result = _execute(_shallow_tree("high_risk"), {"score": 80})
    assert result["matched_conditions"] == ["score > 50"]


def test_auditor_shallow_tree_path_richness() -> None:
    result = _execute(_shallow_tree("high_risk"), {"score": 80})
    assert result["path_richness"] == 0.0


def test_auditor_shallow_tree_result() -> None:
    result = _execute(_shallow_tree("approved"), {"score": 75})
    assert result["result"] == "approved"


# =========================================================================
# Three-level tree
# =========================================================================


def test_auditor_deep_tree_depth() -> None:
    result = _execute(_deep_tree("high_risk"), {"score": 80})
    assert result["tree_depth"] == 3
    assert result["decision_count"] == 3


def test_auditor_deep_tree_matched_conditions() -> None:
    result = _execute(_deep_tree("high_risk"), {"score": 80})
    assert result["matched_conditions"] == ["score > 0", "score > 30", "score > 50"]


def test_auditor_deep_tree_path_richness() -> None:
    result = _execute(_deep_tree("high_risk"), {"score": 80})
    assert result["path_richness"] == 2.0 / 3.0


def test_auditor_deep_tree_medium_path() -> None:
    result = _execute(_deep_tree("medium"), {"score": 40})
    assert result["result"] == "medium"
    assert result["tree_depth"] == 3
    # Third level: score > 50 is False, falls through to catch-all True
    assert result["matched_conditions"] == ["score > 0", "score > 30", "True"]


def test_auditor_deep_tree_low_path() -> None:
    result = _execute(_deep_tree("low"), {"score": 10})
    assert result["result"] == "low"
    assert result["tree_depth"] == 2
    # Second level: score > 30 is False, falls through to catch-all True
    assert result["matched_conditions"] == ["score > 0", "True"]


# =========================================================================
# No-match path
# =========================================================================


def test_auditor_no_match() -> None:
    template = ClassificationTemplate(
        "test.nomatch",
        ClassificationConfig(
            tree=ClassificationNode(
                question="Check",
                branches=[Branch(condition="x > 100", result="high")],
            ),
            output_slot="result",
        ),
    )
    result = _execute(template, {"x": 10})
    assert result["result"] is None
    assert result["tree_depth"] >= 0


# =========================================================================
# Single leaf (no branches)
# =========================================================================


def test_auditor_leaf_node() -> None:
    template = ClassificationTemplate(
        "test.leaf",
        ClassificationConfig(
            tree=ClassificationNode(result="constant"),
            output_slot="result",
        ),
    )
    result = _execute(template, {})
    assert result["result"] == "constant"
    assert result["tree_depth"] == 0
    assert result["path_richness"] == -1.0
