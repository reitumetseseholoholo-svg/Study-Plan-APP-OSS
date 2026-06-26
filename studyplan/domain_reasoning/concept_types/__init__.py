"""Per-type concept implementations.

Each module in this package implements one concept type, providing
``make_template()`` and ``make_candidate_fn()`` factory functions that
return the appropriate solver template and candidate extractor for the type.
"""

from __future__ import annotations

from studyplan.domain_reasoning.concept_types.expression_concept import (
    make_expression_template,
    ExpressionTemplate,
)
from studyplan.domain_reasoning.concept_types.rule_concept import (
    make_rule_template,
    RuleChainTemplate,
    RuleChainStep,
    Rule,
    RuleChainConfig,
)
from studyplan.domain_reasoning.concept_types.lookup_concept import (
    make_lookup_template,
    LookupTemplate,
    LookupRule,
    LookupConfig,
)
from studyplan.domain_reasoning.concept_types.classification_concept import (
    make_classification_template,
    ClassificationTemplate,
    ClassificationNode,
    Branch,
    ClassificationConfig,
)

__all__ = [
    "make_expression_template",
    "ExpressionTemplate",
    "make_rule_template",
    "RuleChainTemplate",
    "RuleChainStep",
    "Rule",
    "RuleChainConfig",
    "make_lookup_template",
    "LookupTemplate",
    "LookupRule",
    "LookupConfig",
    "make_classification_template",
    "ClassificationTemplate",
    "ClassificationNode",
    "Branch",
    "ClassificationConfig",
]
