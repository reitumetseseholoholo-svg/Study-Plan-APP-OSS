"""Classification concept — decision tree traversal.

A classification concept models decision trees where each node asks a
question and branches based on the answer.  Examples: entity type
determination (sole trader vs partnership vs company), contract
classification, financial instrument categorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Branch:
    """One branch in a classification decision tree."""

    condition: str
    result: str | None = None
    children: list[Branch] | None = None


@dataclass
class ClassificationNode:
    """A node in the classification decision tree.

    Either ``question`` is set (decision node) or ``result`` is set (leaf).
    ``branches`` contains the child branches.
    """

    question: str | None = None
    result: str | None = None
    branches: list[Branch] | None = None


@dataclass
class ClassificationConfig:
    """Configuration for a ``classification`` type concept.

    ``tree`` is the root decision node.  Each node asks a question and
    branches by condition; leaf nodes produce a classification result.
    ``output_slot`` is the step identifier for the result.
    """

    tree: ClassificationNode
    output_slot: str = "classification_result"


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class ClassificationTemplate:
    """ConceptTemplate implementation for decision tree classification.

    Traverses the tree by evaluating branch conditions against the input
    context, building a trace of the decision path.
    """

    concept_id: str
    template_version: str

    def __init__(
        self,
        concept_id: str,
        config: ClassificationConfig,
        version: str = "1.0.0",
    ) -> None:
        self.concept_id = concept_id
        self.template_version = version
        self._tree = config.tree
        self._output_slot = config.output_slot

    # ------------------------------------------------------------------
    # Public API (ConceptTemplate protocol)
    # ------------------------------------------------------------------

    def solve(self, inputs: dict[str, Any]) -> dict[str, Any]:
        ctx: dict[str, float] = {}
        for k, v in inputs.items():
            if isinstance(v, (int, float)):
                ctx[str(k)] = float(v)

        path: list[dict[str, Any]] = []
        result = self._traverse(self._tree, ctx, path)

        return {
            "concept_id": self.concept_id,
            "result": result,
            "inputs": dict(inputs),
            "is_nan": result is None,
            "steps": path
            + [
                {
                    "step_id": self._output_slot,
                    "description": "Classification result",
                    "value": result,
                }
            ],
            "classification_path": [p.get("question") or p.get("matched_condition", "") for p in path],
        }

    def evaluate_steps(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not learner_steps or not truth:
            return []
        truth_result = truth.get("result")
        results: list[dict[str, Any]] = []
        for step in learner_steps:
            step_val = step.get("value")
            match = step_val == truth_result
            results.append(
                {
                    "step_id": step.get("step_id", ""),
                    "expected": truth_result,
                    "actual": step_val,
                    "match": match,
                }
            )
        return results

    def classify_errors(
        self,
        learner_steps: list[dict[str, Any]],
        truth: dict[str, Any],
    ) -> list[str]:
        tags: list[str] = []
        if not learner_steps or not truth:
            return tags
        truth_result = truth.get("result")
        truth_path = truth.get("classification_path", [])
        for step in learner_steps:
            step_val = step.get("value")
            if step_val != truth_result:
                tags.append("classification_mismatch")
                break
        if not truth_path:
            return tags
        learner_classification = None
        for step in learner_steps:
            if step.get("step_id") == "classification":
                learner_classification = step.get("value")
                break
        if learner_classification and learner_classification != truth_result:
            tags.append(f"wrong_category_{truth_result}")
        return tags

    # ------------------------------------------------------------------
    # Internal: tree traversal
    # ------------------------------------------------------------------

    def _traverse(
        self,
        node: ClassificationNode,
        ctx: dict[str, float],
        path: list[dict[str, Any]],
    ) -> str | None:
        if node.result is not None:
            return node.result

        if node.question is None or not node.branches:
            return None

        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression

        path.append({"step_id": "decision", "question": node.question, "value": None})

        for branch in node.branches:
            if isinstance(branch.condition, bool) and branch.condition:
                path[-1]["value"] = branch.result
                if branch.result is not None:
                    return branch.result
                if branch.children:
                    return self._traverse_children(branch.children, ctx, path)
            else:
                try:
                    cond_val = _eval_rule_expression(branch.condition, ctx)
                    if bool(cond_val):
                        path[-1]["value"] = branch.result
                        path[-1]["matched_condition"] = branch.condition
                        if branch.result is not None:
                            return branch.result
                        if branch.children:
                            return self._traverse_children(branch.children, ctx, path)
                except (ValueError, NameError):
                    continue

        path[-1]["value"] = None
        return None

    def _traverse_children(
        self,
        children: list[Branch],
        ctx: dict[str, float],
        path: list[dict[str, Any]],
    ) -> str | None:
        from studyplan.domain_reasoning.concept_types.rule_concept import _eval_rule_expression

        for child in children:
            cond = child.condition
            if isinstance(cond, bool) and cond:
                path.append({"step_id": "decision", "value": child.result, "matched_condition": str(cond)})
                if child.result is not None:
                    return child.result
                if child.children:
                    return self._traverse_children(child.children, ctx, path)
                return None
            try:
                cond_val = _eval_rule_expression(cond, ctx)
                if bool(cond_val):
                    path.append(
                        {
                            "step_id": "decision",
                            "value": child.result,
                            "matched_condition": cond,
                        }
                    )
                    if child.result is not None:
                        return child.result
                    if child.children:
                        return self._traverse_children(child.children, ctx, path)
                    return None
            except (ValueError, NameError):
                continue
        return None


# ---------------------------------------------------------------------------
# Candidate extractor
# ---------------------------------------------------------------------------


def _make_classification_candidate_fn(
    config: ClassificationConfig,
) -> Callable[..., list[dict[str, Any]]]:
    """Build a candidate function for classification concepts.

    Enumerates all possible leaf outcomes from the decision tree as
    candidate classifications.
    """

    def candidate_fn(nums: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        _collect_leaves(config.tree, candidates, "")
        return candidates[:5]

    return candidate_fn


def _collect_leaves(
    node: ClassificationNode,
    results: list[dict[str, Any]],
    prefix: str,
) -> None:
    if node.result is not None:
        results.append({"classification": node.result, "path": prefix})
        return
    if node.branches:
        for i, b in enumerate(node.branches):
            lbl = b.result or f"branch_{i}"
            new_prefix = f"{prefix}/{lbl}" if prefix else lbl
            fake_node = ClassificationNode(
                result=b.result,
                branches=b.children,
            )
            _collect_leaves(fake_node, results, new_prefix)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_classification_template(
    concept_id: str,
    config: ClassificationConfig,
) -> ClassificationTemplate:
    """Factory: build a ``ClassificationTemplate`` from configuration."""
    return ClassificationTemplate(
        concept_id=concept_id,
        config=config,
    )
