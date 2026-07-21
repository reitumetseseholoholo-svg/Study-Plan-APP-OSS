"""Tests for studyplan/trace_bridge.py — CCI ↔ provenance trace integration."""

from __future__ import annotations


import pytest

from studyplan.cci.event import CognitiveEvent, ExecutionTrace
from studyplan.provenance.kernel.types import (
    QueryTraceEntry,
    QueryResult,
    Artifact,
)
from studyplan.trace_bridge import (
    embed_provenance_in_event,
    extract_provenance_from_event,
    correlate_traces,
    provenance_entries_to_cci_events,
    unified_trace_view,
    PROVENANCE_PAYLOAD_KEY,
)


# ── Fixtures ──


@pytest.fixture
def sample_prov_entry() -> QueryTraceEntry:
    return QueryTraceEntry(
        primitive="projection",
        args={"filter_type": "artifact", "predicate": "a.id == 'hj1'"},
        input_hash="aaaa1111",
        output_hash="bbbb2222",
        result=QueryResult(
            artifacts=frozenset(
                {
                    Artifact(id="hj1", type="config_value", target="test"),
                }
            ),
        ),
    )


@pytest.fixture
def sample_cci_event() -> CognitiveEvent:
    return CognitiveEvent(
        type="step",
        payload={"transition": "classify", "state": {"score": 0.85}},
        transition_id="step_1",
        state_hash_before="hash_before_1",
        state_hash_after="hash_after_1",
    )


@pytest.fixture
def sample_exec_trace(sample_cci_event) -> ExecutionTrace:
    trace = ExecutionTrace()
    trace.record("initialize", {"state": {}}, transition_id="init")
    trace.record("step", {"transition": "classify"}, transition_id="step_1")
    trace.record("terminate", {"final_state": {}}, transition_id="term")
    return trace


# ── embed_provenance_in_event ──


class TestEmbedProvenance:
    def test_embeds_content_hash_in_payload(self, sample_cci_event, sample_prov_entry):
        result = embed_provenance_in_event(sample_cci_event, sample_prov_entry)
        prov_block = result.payload.get(PROVENANCE_PAYLOAD_KEY)
        assert prov_block is not None
        assert prov_block["content_hash"] == "bbbb2222"
        assert prov_block["primitive"] == "projection"

    def test_original_event_not_mutated(self, sample_cci_event, sample_prov_entry):
        original_payload = dict(sample_cci_event.payload)
        embed_provenance_in_event(sample_cci_event, sample_prov_entry)
        assert sample_cci_event.payload == original_payload

    def test_preserves_existing_payload(self, sample_cci_event, sample_prov_entry):
        result = embed_provenance_in_event(sample_cci_event, sample_prov_entry)
        assert result.payload["transition"] == "classify"
        assert result.payload["state"] == {"score": 0.85}

    def test_preserves_event_type_and_hashes(self, sample_cci_event, sample_prov_entry):
        result = embed_provenance_in_event(sample_cci_event, sample_prov_entry)
        assert result.type == "step"
        assert result.state_hash_before == "hash_before_1"
        assert result.state_hash_after == "hash_after_1"
        assert result.transition_id == "step_1"

    def test_uses_input_hash_when_output_empty(self, sample_cci_event):
        entry = QueryTraceEntry(
            primitive="traversal",
            args={},
            input_hash="cccc3333",
            output_hash="",
        )
        result = embed_provenance_in_event(sample_cci_event, entry)
        prov_block = result.payload.get(PROVENANCE_PAYLOAD_KEY)
        assert prov_block["content_hash"] == "cccc3333"

    def test_does_not_mutate_payload_when_called_twice(self, sample_cci_event, sample_prov_entry):
        r1 = embed_provenance_in_event(sample_cci_event, sample_prov_entry)
        r2 = embed_provenance_in_event(r1, sample_prov_entry)
        assert r1.payload is not r2.payload
        assert r1.payload[PROVENANCE_PAYLOAD_KEY]["content_hash"] == "bbbb2222"


# ── extract_provenance_from_event ──


class TestExtractProvenance:
    def test_extracts_embedded_data(self, sample_cci_event, sample_prov_entry):
        embedded = embed_provenance_in_event(sample_cci_event, sample_prov_entry)
        extracted = extract_provenance_from_event(embedded)
        assert extracted is not None
        assert extracted["content_hash"] == "bbbb2222"
        assert extracted["primitive"] == "projection"

    def test_returns_none_when_not_embedded(self, sample_cci_event):
        assert extract_provenance_from_event(sample_cci_event) is None

    def test_returns_none_for_empty_payload(self):
        ev = CognitiveEvent(
            type="step",
            payload={},
            transition_id="step_1",
        )
        assert extract_provenance_from_event(ev) is None

    def test_returns_none_for_malformed_block(self, sample_cci_event):
        ev = CognitiveEvent(
            type="step",
            payload={PROVENANCE_PAYLOAD_KEY: "not_a_dict"},
            transition_id="step_1",
        )
        assert extract_provenance_from_event(ev) is None

    def test_returns_none_when_content_hash_missing(self, sample_cci_event):
        ev = CognitiveEvent(
            type="step",
            payload={PROVENANCE_PAYLOAD_KEY: {"primitive": "test"}},
            transition_id="step_1",
        )
        assert extract_provenance_from_event(ev) is None


# ── correlate_traces ──


class TestCorrelateTraces:
    def test_correlates_by_content_hash(self, sample_exec_trace, sample_prov_entry):
        embedded = embed_provenance_in_event(
            sample_exec_trace.events[1],
            sample_prov_entry,
        )
        trace = ExecutionTrace()
        for ev in sample_exec_trace.events:
            if ev is sample_exec_trace.events[1]:
                trace.record(
                    embedded.type,
                    dict(embedded.payload),
                    transition_id=embedded.transition_id,
                    state_hash_before=embedded.state_hash_before,
                    state_hash_after=embedded.state_hash_after,
                )
            else:
                trace.record(ev.type, dict(ev.payload), transition_id=ev.transition_id)

        result = correlate_traces(trace, (sample_prov_entry,))
        assert "0" in result
        matches = result["0"]
        assert len(matches) == 1
        assert matches[0]["match_type"] == "content_hash"
        assert matches[0]["event_type"] == "step"

    def test_returns_empty_when_no_correlation(self, sample_exec_trace, sample_prov_entry):
        result = correlate_traces(sample_exec_trace, (sample_prov_entry,))
        assert result == {}

    def test_correlates_multiple_entries(self, sample_exec_trace):
        e1 = QueryTraceEntry(primitive="projection", args={}, input_hash="a1", output_hash="b1")
        e2 = QueryTraceEntry(primitive="traversal", args={}, input_hash="a2", output_hash="b2")
        trace = ExecutionTrace()
        for ev in sample_exec_trace.events:
            trace.record(ev.type, dict(ev.payload), transition_id=ev.transition_id)
        ev1 = embed_provenance_in_event(trace.events[0], e1)
        ev2 = embed_provenance_in_event(trace.events[1], e2)
        trace2 = ExecutionTrace()
        trace2.record(
            ev1.type,
            dict(ev1.payload),
            transition_id=ev1.transition_id,
            state_hash_before=ev1.state_hash_before,
            state_hash_after=ev1.state_hash_after,
        )
        trace2.record(
            ev2.type,
            dict(ev2.payload),
            transition_id=ev2.transition_id,
            state_hash_before=ev2.state_hash_before,
            state_hash_after=ev2.state_hash_after,
        )
        result = correlate_traces(trace2, (e1, e2))
        assert "0" in result
        assert "1" in result

    def test_skips_non_matching_events(self, sample_exec_trace, sample_prov_entry):
        ev = embed_provenance_in_event(sample_exec_trace.events[0], sample_prov_entry)
        trace = ExecutionTrace()
        trace.record(ev.type, dict(ev.payload), transition_id=ev.transition_id)
        different_entry = QueryTraceEntry(
            primitive="reduction",
            args={},
            input_hash="xxxx",
            output_hash="yyyy",
        )
        result = correlate_traces(trace, (different_entry,))
        assert result == {}


# ── provenance_entries_to_cci_events ──


class TestProvenanceToCCIEvents:
    def test_converts_empty_entries(self):
        result = provenance_entries_to_cci_events(())
        assert result == []

    def test_converts_single_entry(self, sample_prov_entry):
        result = provenance_entries_to_cci_events((sample_prov_entry,))
        assert len(result) == 1
        ev = result[0]
        assert ev.type == "provenance_query"
        assert ev.transition_id == "projection"
        assert ev.state_hash_before == "aaaa1111"
        assert ev.state_hash_after == "bbbb2222"
        assert ev.payload["primitive"] == "projection"
        assert ev.payload["result"]["artifact_count"] == 1

    def test_converts_multiple_entries(self, sample_prov_entry):
        e1 = sample_prov_entry
        e2 = QueryTraceEntry(
            primitive="traversal", args={"edge_type": "generative_mapping"}, input_hash="c1", output_hash="c2"
        )
        result = provenance_entries_to_cci_events((e1, e2))
        assert len(result) == 2
        assert result[0].transition_id == "projection"
        assert result[1].transition_id == "traversal"

    def test_converts_entry_without_result(self):
        entry = QueryTraceEntry(
            primitive="traversal", args={"edge_type": "test"}, input_hash="x1", output_hash="x2", result=None
        )
        result = provenance_entries_to_cci_events((entry,))
        assert len(result) == 1
        assert result[0].payload["result"]["has_result"] is False

    def test_custom_base_type(self, sample_prov_entry):
        result = provenance_entries_to_cci_events((sample_prov_entry,), base_type="compile_step")
        assert result[0].type == "compile_step"

    def test_converts_entry_with_metadata(self):
        entry = QueryTraceEntry(
            primitive="reduction",
            args={"key": "value"},
            input_hash="i1",
            output_hash="o1",
            result=QueryResult(metadata={"count": 5, "kind": "test"}),
        )
        result = provenance_entries_to_cci_events((entry,))
        assert result[0].payload["result"]["metadata"]["count"] == 5
        assert result[0].payload["result"]["metadata"]["kind"] == "test"


# ── unified_trace_view ──


class TestUnifiedTraceView:
    def test_view_with_empty_traces(self):
        result = unified_trace_view()
        assert result["event_count"] == 0
        assert result["provenance_count"] == 0
        assert result["embed_count"] == 0
        assert result["cross_references"] == {}
        assert result["event_types"] == []
        assert result["primitives"] == []

    def test_view_with_only_execution_trace(self, sample_exec_trace):
        result = unified_trace_view(exec_trace=sample_exec_trace)
        assert result["event_count"] == 3
        assert result["provenance_count"] == 0
        assert result["embed_count"] == 0
        assert "initialize" in result["event_types"]

    def test_view_with_only_provenance(self, sample_prov_entry):
        result = unified_trace_view(provenance_entries=(sample_prov_entry,))
        assert result["event_count"] == 0
        assert result["provenance_count"] == 1
        assert "projection" in result["primitives"]

    def test_view_with_embedded_provenance(self, sample_exec_trace, sample_prov_entry):
        ev = embed_provenance_in_event(sample_exec_trace.events[1], sample_prov_entry)
        trace = ExecutionTrace()
        for orig_ev in sample_exec_trace.events:
            if orig_ev is sample_exec_trace.events[1]:
                trace.record(ev.type, dict(ev.payload), transition_id=ev.transition_id)
            else:
                trace.record(orig_ev.type, dict(orig_ev.payload), transition_id=orig_ev.transition_id)
        result = unified_trace_view(exec_trace=trace, provenance_entries=(sample_prov_entry,))
        assert result["embed_count"] == 1
        assert result["provenance_count"] == 1
        assert result["cross_references"] != {}

    def test_view_reports_event_types_set(self, sample_exec_trace):
        result = unified_trace_view(exec_trace=sample_exec_trace)
        assert set(result["event_types"]) == {"initialize", "step", "terminate"}
