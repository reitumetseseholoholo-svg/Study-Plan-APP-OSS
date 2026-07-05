"""Tests for CognitiveProjectionEngine — event → latent cognitive state."""

from studyplan.provenance.learning.events import (
    review_decision,
    candidate_compared,
    provenance_viewed,
    ambiguity_detected,
)
from studyplan.provenance.learning.cognitive_projection import (
    CognitiveProjectionEngine,
)


class TestCognitiveProjectionEngine:
    """P1: project() returns a valid CognitiveProjection from events."""

    def test_empty_events_returns_empty(self):
        engine = CognitiveProjectionEngine()
        cp = engine.project([])
        assert cp.is_empty
        assert cp.event_count == 0

    def test_single_decision_produces_node(self):
        engine = CognitiveProjectionEngine()
        events = [
            review_decision(
                candidate_ids=["fm:WACC"],
                candidate_labels=["WACC"],
                chosen_id="fm:WACC",
                alternatives=[],
                decision="merged",
                confidence=0.85,
                decision_latency_ms=1200,
                evidence_viewed=["provenance"],
                manual_notes="",
            ),
        ]
        cp = engine.project(events)
        assert not cp.is_empty
        assert "fm:WACC" in cp.nodes
        assert cp.nodes["fm:WACC"].interaction_count > 0
        assert cp.nodes["fm:WACC"].stability_score > 0

    def test_uncertainty_from_latency(self):
        """High latency → higher uncertainty score."""
        engine = CognitiveProjectionEngine()
        fast_decision = review_decision(
            candidate_ids=["fm:CAPM"],
            candidate_labels=["CAPM"],
            chosen_id="fm:CAPM",
            alternatives=[],
            decision="merged",
            confidence=0.95,
            decision_latency_ms=500,
            evidence_viewed=[],
            manual_notes="",
        )
        slow_decision = review_decision(
            candidate_ids=["fm:WACC"],
            candidate_labels=["WACC"],
            chosen_id="fm:WACC",
            alternatives=[],
            decision="merged",
            confidence=0.95,
            decision_latency_ms=15000,
            evidence_viewed=[],
            manual_notes="",
        )
        cp_fast = engine.project([fast_decision])
        cp_slow = engine.project([slow_decision])
        assert cp_slow.nodes["fm:WACC"].uncertainty_score >= cp_fast.nodes["fm:CAPM"].uncertainty_score

    def test_comparison_creates_confusion_edges(self):
        engine = CognitiveProjectionEngine()
        events = [
            candidate_compared(
                group_id="g1",
                primary_id="fm:NPV",
                compared_ids=["fm:IRR"],
                compared_labels=["IRR"],
                opened_side_by_side=True,
            ),
            candidate_compared(
                group_id="g1",
                primary_id="fm:NPV",
                compared_ids=["fm:IRR"],
                compared_labels=["IRR"],
                opened_side_by_side=True,
            ),
        ]
        cp = engine.project(events)
        assert len(cp.confusion_edges) >= 1
        found = False
        for e in cp.confusion_edges:
            if "fm:NPV" in (e.source_id, e.target_id) and "fm:IRR" in (e.source_id, e.target_id):
                found = True
                break
        assert found, "Expected confusion edge between NPV and IRR"

    def test_stability_from_consistent_decisions(self):
        engine = CognitiveProjectionEngine()
        events = [
            review_decision(
                candidate_ids=["fm:CAPM"],
                candidate_labels=["CAPM"],
                chosen_id="fm:CAPM",
                alternatives=[],
                decision="merged",
                confidence=0.95,
                decision_latency_ms=1000,
                evidence_viewed=[],
                manual_notes="",
            ),
            review_decision(
                candidate_ids=["fm:CAPM"],
                candidate_labels=["CAPM"],
                chosen_id="fm:CAPM",
                alternatives=[],
                decision="merged",
                confidence=0.90,
                decision_latency_ms=800,
                evidence_viewed=[],
                manual_notes="",
            ),
        ]
        cp = engine.project(events)
        assert cp.nodes["fm:CAPM"].stability_score > 0.5

    def test_familiarity_from_recency(self):
        engine = CognitiveProjectionEngine()
        import time

        now = time.time()
        events = [
            review_decision(
                candidate_ids=["fm:WACC"],
                candidate_labels=["WACC"],
                chosen_id="fm:WACC",
                alternatives=[],
                decision="merged",
                confidence=0.85,
                decision_latency_ms=1000,
                evidence_viewed=["provenance"],
                manual_notes="",
            ),
        ]
        cp = engine.project(events)
        assert cp.nodes["fm:WACC"].interaction_count == 1
        assert cp.nodes["fm:WACC"].last_seen > 0

    def test_multiple_events_aggregate(self):
        """Many events on same concept produce higher interaction count."""
        engine = CognitiveProjectionEngine()
        events = [
            review_decision(
                candidate_ids=["fm:X"],
                candidate_labels=["X"],
                chosen_id="fm:X",
                alternatives=[],
                decision="merged",
                confidence=0.8,
                decision_latency_ms=500,
                evidence_viewed=[],
                manual_notes="",
            ),
            review_decision(
                candidate_ids=["fm:X"],
                candidate_labels=["X"],
                chosen_id="fm:X",
                alternatives=[],
                decision="merged",
                confidence=0.7,
                decision_latency_ms=600,
                evidence_viewed=[],
                manual_notes="",
            ),
            provenance_viewed(
                identity_id="fm:X",
                identity_label="X",
                source_kind="fm",
                source_id="fm:source",
            ),
        ]
        cp = engine.project(events)
        assert cp.nodes["fm:X"].interaction_count == 3

    def test_mixed_event_types_produce_union_of_nodes(self):
        engine = CognitiveProjectionEngine()
        events = [
            review_decision(
                candidate_ids=["fm:A"],
                candidate_labels=["A"],
                chosen_id="fm:A",
                alternatives=[],
                decision="merged",
                confidence=0.9,
                decision_latency_ms=1000,
                evidence_viewed=[],
                manual_notes="",
            ),
            provenance_viewed(
                identity_id="fm:B",
                identity_label="B",
                source_kind="pdf",
                source_id="pdf:doc",
            ),
        ]
        cp = engine.project(events)
        assert "fm:A" in cp.nodes
        assert "fm:B" in cp.nodes

    def test_reprojection_ephemeral(self):
        """Same events produce same projection (deterministic)."""
        engine = CognitiveProjectionEngine()
        events = [
            review_decision(
                candidate_ids=["fm:X"],
                candidate_labels=["X"],
                chosen_id="fm:X",
                alternatives=[],
                decision="merged",
                confidence=0.9,
                decision_latency_ms=1000,
                evidence_viewed=[],
                manual_notes="",
            ),
        ]
        cp1 = engine.project(events)
        cp2 = engine.project(events)
        assert cp1.nodes["fm:X"].stability_score == cp2.nodes["fm:X"].stability_score
        assert cp1.nodes["fm:X"].uncertainty_score == cp2.nodes["fm:X"].uncertainty_score

    def test_events_by_type_passthrough(self):
        """project() respects the full event list regardless of type."""
        engine = CognitiveProjectionEngine()
        events = [
            ambiguity_detected(
                source_id="src1",
                candidate_ids=["fm:Y", "fm:Z"],
                candidate_labels=["Y", "Z"],
                similarity_scores=[0.85],
            ),
            review_decision(
                candidate_ids=["fm:Y"],
                candidate_labels=["Y"],
                chosen_id="fm:Y",
                alternatives=["fm:Z"],
                decision="merged",
                confidence=0.75,
                decision_latency_ms=3000,
                evidence_viewed=["compare"],
                manual_notes="",
            ),
        ]
        cp = engine.project(events)
        assert "fm:Y" in cp.nodes
        assert "fm:Z" in cp.nodes  # from alternatives
