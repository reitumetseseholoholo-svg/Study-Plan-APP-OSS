"""Tests for ProvenanceIntegrator — app-facing facade over provenance architecture.

Hypothesis H-PI-01:
    A thin ProvenanceIntegrator wrapping DomainRegistry + ExecutionContext
    can replace all three app provenance code paths without changing the
    return dict format that downstream consumers rely on.

Predictions:
    P1: capture_trace returns the same dict shape as the old _capture_provenance_trace.
    P2: tutor_context returns a formatted string for LLM prompts.
    P3: The integrator handles missing topics gracefully (returns error dict or None).
    P4: Both ALL_TOPICS and formula registry topics are supported.
    P5: Multiple calls with the same topic return consistent results.

Hypothesis CI-B-01 (Compiler→Integrator Bridge):
    Compiler identity resolution decisions propagate to provenance queries.
Predictions:
    P6: push_identity_aliases changes trace output artifact names.
    P7: clear_identity_aliases restores original artifact names.
"""

from __future__ import annotations

import pytest

from studyplan.provenance.lab.integration import (
    ProvenanceIntegrator,
    push_identity_aliases,
    get_identity_aliases,
    clear_identity_aliases,
)
from studyplan_ai_tutor import build_provenance_context


@pytest.fixture
def integrator() -> ProvenanceIntegrator:
    return ProvenanceIntegrator()


@pytest.fixture(autouse=True)
def _isolate_aliases() -> None:
    """Save and restore the module-level alias map around every test.

    Prevents cross-test contamination since the alias map is a
    module-level singleton shared across all integrator instances.
    """
    saved = get_identity_aliases()
    yield
    push_identity_aliases(saved)


class TestResolveTopic:
    """P4: Both ALL_TOPICS and formula registry topics are supported."""

    def test_resolve_all_topics(self, integrator):
        assert integrator.resolve_topic("CAPM") == "CAPM"
        assert integrator.resolve_topic("NPV") == "NPV"

    def test_resolve_formula_registry(self, integrator):
        # Formula registry should have fm.wacc or similar
        resolved = integrator.resolve_topic("wacc")
        assert "wacc" in resolved.lower()

    def test_resolve_nonexistent(self, integrator):
        assert integrator.resolve_topic("nonexistent_topic_xyz") == ""


class TestCaptureTrace:
    """P1: capture_trace returns the same dict shape as old _capture_provenance_trace."""

    REQUIRED_KEYS = {
        "topic",
        "artifact_id",
        "step_count",
        "steps",
        "assumptions",
        "consumes",
        "dependency_path",
        "prerequisite_artifacts",
        "total_constraints",
    }

    def test_capture_capm(self, integrator):
        result = integrator.capture_trace("CAPM")
        assert result is not None
        assert "error" not in result, result.get("error")
        assert self.REQUIRED_KEYS.issubset(result.keys())
        assert result["topic"] == "CAPM"
        assert isinstance(result["assumptions"], list)
        assert isinstance(result["dependency_path"], list)

    def test_capture_formula_topic(self, integrator):
        result = integrator.capture_trace("wacc")
        assert result is not None
        assert "error" not in result, result.get("error")
        assert self.REQUIRED_KEYS.issubset(result.keys())

    def test_capture_nonexistent(self, integrator):
        result = integrator.capture_trace("nonexistent")
        assert result is not None
        assert "error" in result

    def test_capture_empty_topic(self, integrator):
        result = integrator.capture_trace("")
        assert result is None

    def test_capture_all_topics_have_expected_keys(self, integrator):
        for topic in ("CAPM", "NPV", "IRR", "APV", "GordonGrowth"):
            result = integrator.capture_trace(topic)
            assert result is not None, f"Failed for {topic}"
            assert "error" not in result, f"{topic}: {result.get('error')}"
            assert self.REQUIRED_KEYS.issubset(result.keys())
            assert len(result["assumptions"]) > 0, f"No assumptions for {topic}"


class TestTutorContext:
    """P2: tutor_context returns a formatted string for LLM prompts."""

    def test_tutor_context_capm(self, integrator):
        result = integrator.tutor_context("CAPM")
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Provenance context" in result or "Kernel-verified" in result
        assert "CAPM" in result or "Topic" in result

    def test_tutor_context_formula_topic(self, integrator):
        result = integrator.tutor_context("wacc")
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_tutor_context_nonexistent(self, integrator):
        result = integrator.tutor_context("nonexistent_topic")
        assert result is None

    def test_tutor_context_empty(self, integrator):
        result = integrator.tutor_context("")
        assert result is None

    def test_tutor_context_with_mode_hint(self, integrator):
        result = integrator.tutor_context("CAPM", mode_hint="assumption_query")
        assert result is not None
        assert "Kernel-verified" in result


class TestConsistency:
    """P5: Multiple calls with the same topic return consistent results."""

    def test_consistent_capture(self, integrator):
        r1 = integrator.capture_trace("CAPM")
        r2 = integrator.capture_trace("CAPM")
        assert r1 is not None and r2 is not None
        assert r1["assumptions"] == r2["assumptions"]
        assert r1["dependency_path"] == r2["dependency_path"]

    def test_consistent_tutor_context(self, integrator):
        r1 = integrator.tutor_context("CAPM")
        r2 = integrator.tutor_context("CAPM")
        assert r1 == r2


class TestIdentityAliasBridge:
    """CI-B-01: Compiler identity resolution → provenance query bridge.

    P6: push_identity_aliases changes trace output artifact names.
    P7: clear_identity_aliases restores original artifact names.
    """

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_module_level_get_set(self, topic):
        """P6a: push/get round-trip works."""
        push_identity_aliases({"market_efficiency": "EfficientMarket"})
        assert get_identity_aliases() == {"market_efficiency": "EfficientMarket"}

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_module_level_clear(self, topic):
        """P7a: clear removes all aliases."""
        push_identity_aliases({"market_efficiency": "EfficientMarket"})
        clear_identity_aliases()
        assert get_identity_aliases() == {}

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_capture_trace_normalizes_assumptions(self, integrator, topic):
        """P6: trace assumptions reflect aliases."""
        original = integrator.capture_trace(topic)
        assert original is not None and "error" not in original
        assert "market_efficiency" in original["assumptions"]

        push_identity_aliases({"market_efficiency": "EfficientMarket"})

        aliased = integrator.capture_trace(topic)
        assert aliased is not None and "error" not in aliased
        assert "market_efficiency" not in aliased["assumptions"]
        assert "EfficientMarket" in aliased["assumptions"]

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_capture_trace_normalizes_consumes(self, integrator, topic):
        """P6: trace consumes reflect aliases."""
        original = integrator.capture_trace(topic)
        assert original is not None and "error" not in original
        if not original["consumes"]:
            pytest.skip("No consumes to alias")

        consume_item = original["consumes"][0]
        aliased_name = f"ALIASED_{consume_item}"
        push_identity_aliases({consume_item: aliased_name})

        aliased = integrator.capture_trace(topic)
        assert aliased is not None and "error" not in aliased
        assert consume_item not in aliased["consumes"]
        assert aliased_name in aliased["consumes"]

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_clear_restores_original_names(self, integrator, topic):
        """P7: clear_identity_aliases restores un-aliased trace."""
        original = integrator.capture_trace(topic)
        assert original is not None and "error" not in original

        push_identity_aliases({"market_efficiency": "EfficientMarket"})
        clear_identity_aliases()

        restored = integrator.capture_trace(topic)
        assert restored is not None and "error" not in restored
        assert restored["assumptions"] == original["assumptions"]

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_unrelated_names_pass_through(self, integrator, topic):
        """Non-matching artifact names are unchanged."""
        original = integrator.capture_trace(topic)
        assert original is not None and "error" not in original

        push_identity_aliases({"nonexistent_alias_key_xyz": "SomeCanonical"})

        aliased = integrator.capture_trace(topic)
        assert aliased is not None and "error" not in aliased
        assert aliased["assumptions"] == original["assumptions"]
        assert aliased["consumes"] == original["consumes"]

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_multiple_aliases_applied(self, integrator, topic):
        """Multiple simultaneous aliases all apply."""
        push_identity_aliases(
            {
                "market_efficiency": "EfficientMarket",
                "diversified_investor": "DiversifiedPortfolio",
            }
        )

        aliased = integrator.capture_trace(topic)
        assert aliased is not None and "error" not in aliased
        assert "EfficientMarket" in aliased["assumptions"]
        assert "DiversifiedPortfolio" in aliased["assumptions"]
        assert "market_efficiency" not in aliased["assumptions"]
        assert "diversified_investor" not in aliased["assumptions"]

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_push_empty_clears(self, integrator, topic):
        """P6b: push empty dict clears aliases."""
        original = integrator.capture_trace(topic)
        assert original is not None and "error" not in original

        push_identity_aliases({"market_efficiency": "EfficientMarket"})
        push_identity_aliases({})

        cleared = integrator.capture_trace(topic)
        assert cleared is not None and "error" not in cleared
        assert cleared["assumptions"] == original["assumptions"]

    @pytest.mark.parametrize("topic", ["CAPM"])
    def test_push_none_clears(self, integrator, topic):
        """P6c: push None clears aliases."""
        original = integrator.capture_trace(topic)
        assert original is not None and "error" not in original

        push_identity_aliases({"market_efficiency": "EfficientMarket"})
        push_identity_aliases(None)

        cleared = integrator.capture_trace(topic)
        assert cleared is not None and "error" not in cleared
        assert cleared["assumptions"] == original["assumptions"]


class TestProvenanceConfidence:
    """T-PC-01: Confidence scores in provenance context change LLM-facing output.

    P1: build_provenance_context formats name [confidence] when
        assumption_confidence is present in data dict.
    P2: Without assumption_confidence, output is unchanged (backward compat).
    P3: Missing entries in confidence dict leave those names un-annotated.
    """

    BASE_DATA = {
        "artifact": "WACC",
        "assumptions": ["market_efficiency", "diversified_investor"],
        "consumes": ["CAPM", "Cost_of_Debt"],
        "dependency_path": ("Rf", "CAPM", "WACC"),
        "total_constraints": 5,
    }

    def test_without_confidence_unchanged(self):
        """P2: default (no confidence) output is preserved."""
        result = build_provenance_context(self.BASE_DATA)
        assert "market_efficiency" in result
        assert "diversified_investor" in result
        assert "[0.95]" not in result
        assert "[" not in result

    def test_with_confidence_formats_scores(self):
        """P1: confidence scores appear in assumption lines."""
        data = dict(self.BASE_DATA)
        data["assumption_confidence"] = {
            "market_efficiency": 0.95,
            "diversified_investor": 0.85,
        }
        result = build_provenance_context(data)
        assert "market_efficiency [0.95]" in result
        assert "diversified_investor [0.85]" in result

    def test_missing_confidence_leaves_name_plain(self):
        """P3: assumptions without confidence entry show plain name."""
        data = dict(self.BASE_DATA)
        data["assumption_confidence"] = {"market_efficiency": 0.95}
        result = build_provenance_context(data)
        assert "market_efficiency [0.95]" in result
        assert "diversified_investor" in result
        assert "diversified_investor [" not in result

    def test_empty_confidence_dict_no_annotation(self):
        """Empty confidence dict = no annotations."""
        data = dict(self.BASE_DATA)
        data["assumption_confidence"] = {}
        result = build_provenance_context(data)
        assert "[0.95]" not in result
        assert "[" not in result

    def test_none_confidence_field_ignored(self):
        """assumption_confidence=None is treated as absent."""
        data = dict(self.BASE_DATA)
        data["assumption_confidence"] = None
        result = build_provenance_context(data)
        assert "[" not in result

    def test_assumption_query_mode_with_confidence(self):
        """confidence works in assumption_query mode."""
        data = dict(self.BASE_DATA)
        data["assumption_confidence"] = {"market_efficiency": 0.99}
        result = build_provenance_context(data, mode_hint="assumption_query")
        assert "Kernel-verified" in result
        assert "market_efficiency [0.99]" in result

    def test_partial_confidence_some_annotated_some_plain(self):
        """Mixed annotated and unannotated assumptions."""
        data = dict(self.BASE_DATA)
        data["assumptions"] = ["a", "b", "c"]
        data["assumption_confidence"] = {"a": 0.9, "c": 0.5}
        result = build_provenance_context(data)
        assert "a [0.9]" in result
        assert "b" in result
        assert "b [" not in result
        assert "c [0.5]" in result
