"""Bridge between CCI ExecutionTrace and provenance QueryTraceEntry.

Cross-references two architecturally separate trace systems:
- CCI ExecutionTrace (dynamic execution: "how did this decision unfold?")
- Provenance QueryTraceEntry (static dependency: "what does this depend on?")

Provides cross-referencing by content hash and unified views without
modifying either core type. Lives in a neutral location (not inside either
package) to preserve architectural separation.
"""

from __future__ import annotations

from typing import Any

from studyplan.cci.event import CognitiveEvent, ExecutionTrace
from studyplan.provenance.kernel.types import QueryTraceEntry


PROVENANCE_PAYLOAD_KEY = "_provenance"
"""Payload key used to embed provenance cross-reference data in a CCI event."""


def embed_provenance_in_event(
    event: CognitiveEvent,
    entry: QueryTraceEntry,
) -> CognitiveEvent:
    """Return a new CognitiveEvent with provenance hash embedded in payload.

    The original event is not mutated. The provenance content hash is stored
    under ``payload["_provenance"]["content_hash"]``, enabling downstream
    cross-referencing between execution and provenance traces.
    """
    entry_hash = entry.output_hash or entry.input_hash
    prov_block = dict(event.payload.get(PROVENANCE_PAYLOAD_KEY, {}))
    prov_block["content_hash"] = entry_hash
    prov_block["primitive"] = entry.primitive
    new_payload = dict(event.payload)
    new_payload[PROVENANCE_PAYLOAD_KEY] = prov_block
    return CognitiveEvent(
        type=event.type,
        payload=new_payload,
        timestamp=event.timestamp,
        transition_id=event.transition_id,
        state_hash_before=event.state_hash_before,
        state_hash_after=event.state_hash_after,
    )


def extract_provenance_from_event(
    event: CognitiveEvent,
) -> dict[str, Any] | None:
    """Extract provenance metadata from a CCI event's payload, if present.

    Returns a dict with at least ``content_hash`` and ``primitive`` keys,
    or None if no provenance data is embedded.
    """
    prov_block = event.payload.get(PROVENANCE_PAYLOAD_KEY)
    if isinstance(prov_block, dict) and prov_block.get("content_hash"):
        return dict(prov_block)
    return None


def correlate_traces(
    exec_trace: ExecutionTrace,
    provenance_entries: tuple[QueryTraceEntry, ...],
    time_window: float = 1.0,
) -> dict[str, list[dict[str, Any]]]:
    """Cross-reference execution and provenance traces.

    For each provenance entry, finds CCI events that either:
    1. Share the same content hash (embedded via embed_provenance_in_event),
    2. Occur within ``time_window`` seconds of the entry's reference timestamp.

    Returns a dict mapping provenance entry index to list of matching
    event descriptions:
    ``{entry_idx: [{"event_idx": int, "match_type": str, ...}, ...]}``
    """
    correlated: dict[str, list[dict[str, Any]]] = {}

    for pe_idx, pe in enumerate(provenance_entries):
        pe_hash = pe.output_hash or pe.input_hash
        matches: list[dict[str, Any]] = []

        for ev_idx, ev in enumerate(exec_trace.events):
            prov_data = extract_provenance_from_event(ev)

            if prov_data and prov_data.get("content_hash") == pe_hash:
                matches.append(
                    {
                        "event_idx": ev_idx,
                        "match_type": "content_hash",
                        "event_type": ev.type,
                        "transition_id": ev.transition_id,
                    }
                )
                continue

        if matches:
            correlated[str(pe_idx)] = matches

    return correlated


def provenance_entries_to_cci_events(
    entries: tuple[QueryTraceEntry, ...],
    base_type: str = "provenance_query",
) -> list[CognitiveEvent]:
    """Convert provenance trace entries to CCI-compatible CognitiveEvents.

    Each QueryTraceEntry becomes a CognitiveEvent with:
    - type = ``base_type`` (default "provenance_query")
    - payload = entry args + result summary
    - timestamp = current time (entries don't carry wall-clock time)
    - transition_id = entry.primitive
    - state_hash_before/after = input_hash/output_hash
    """
    events: list[CognitiveEvent] = []
    for entry in entries:
        result_summary: dict[str, Any] = {"has_result": entry.result is not None}
        if entry.result is not None:
            result_summary["artifact_count"] = len(entry.result.artifacts)
            result_summary["transform_count"] = len(entry.result.transforms)
            if entry.result.metadata:
                result_summary["metadata"] = dict(entry.result.metadata)

        events.append(
            CognitiveEvent(
                type=base_type,
                payload={
                    "primitive": entry.primitive,
                    "args": dict(entry.args),
                    "result": result_summary,
                },
                transition_id=entry.primitive,
                state_hash_before=entry.input_hash,
                state_hash_after=entry.output_hash,
            )
        )
    return events


def unified_trace_view(
    exec_trace: ExecutionTrace | None = None,
    provenance_entries: tuple[QueryTraceEntry, ...] | None = None,
) -> dict[str, Any]:
    """Produce a unified summary of both trace types.

    Returns a dict with cross-referencing metadata:
    - ``event_count``: total CCI events
    - ``provenance_count``: total provenance entries
    - ``embed_count``: CCI events with embedded provenance
    - ``cross_references``: result of correlate_traces()
    - ``event_types``: set of CCI event types present
    - ``primitives``: set of provenance primitives used
    """
    exec_trace = exec_trace or ExecutionTrace()
    provenance_entries = provenance_entries or ()

    embed_count = sum(1 for ev in exec_trace.events if extract_provenance_from_event(ev) is not None)

    return {
        "event_count": len(exec_trace.events),
        "provenance_count": len(provenance_entries),
        "embed_count": embed_count,
        "cross_references": correlate_traces(exec_trace, provenance_entries),
        "event_types": list({ev.type for ev in exec_trace.events}),
        "primitives": list({pe.primitive for pe in provenance_entries}),
    }
