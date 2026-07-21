"""ProvenanceIntegrator — app-facing facade over the provenance architecture.

Essentialist Question:
    What phenomenon does this integrator exist to preserve?
Answer:
    Integration coherence — the property that provenance queries flow through
    a single, tested, layered API rather than three ad-hoc patterns duplicated
    across studyplan_app.py (lines 53587, 8591, 24643).

Hypothesis H-PI-01:
    A thin ProvenanceIntegrator wrapping DomainRegistry + ExecutionContext
    can replace all three app provenance code paths without changing the
    return dict format that downstream consumers (_build_provenance_trace_widget,
    build_provenance_context) rely on.

Predictions:
    P1: capture_trace(topic) returns identical dict shape as the old
        _capture_provenance_trace.
    P2: tutor_context(chapter, mode_hint) returns the same formatted string
        as the old inline code in _generate().
    P3: The DomainRegistry cache replaces the manual _provenance_vs_cache dict.
    P4: All three app sites can use the same ProvenanceIntegrator instance.
    P5: Zero changes to the return-consumption code (_build_provenance_trace_widget,
        build_provenance_context).

Falsification:
    F1: A dict key differs between integrator output and old _capture_provenance_trace.
    F2: tutor_context returns a different string than the old inline code.
    F3: The integrator raises an exception that the old try/except blocks didn't catch.

Protocol observation H-PI-02 (Class A, Jul 2026):
    ExecutionContext lifetime must follow ViewState lifetime, not request lifetime.
    A topic receives many tutor requests. Each request previously created a fresh
    ExecutionContext, discarding the O(N×E) precompute. The fix is to cache
    ExecutionContext per resolved topic — the precompute runs once per ViewState.
    Prediction: Any long-lived ViewState consumer (Debugger, Observatory, Tutor)
    should reuse the same ExecutionContext. Falsification: a topic's ViewState
    changes mid-session (new compilation) and the cached EC returns stale data.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from studyplan.provenance.domain_registry import (
    DomainEntry,
    DomainRegistry,
    get_default_registry,
)
from studyplan.provenance.execution import ExecutionContext
from studyplan.provenance.kernel import Transformation

# ── Identity alias map — CI-B-01 bridge ────────────────────────────
# Module-level store so that compiler identity resolution decisions
# propagate to all ProvenanceIntegrator instances without coupling
# the integrator to the compiler workspace lifecycle.

_IDENTITY_ALIASES: dict[str, str] = {}


def push_identity_aliases(aliases: dict[str, str]) -> None:
    """Replace the identity alias map with a new mapping.

    Called after compilation to push the GIR's local-to-canonical
    mapping into the provenance query pipeline.  Clears the alias
    map when *aliases* is empty or None.
    """
    global _IDENTITY_ALIASES
    _IDENTITY_ALIASES = dict(aliases) if aliases else {}


def get_identity_aliases() -> dict[str, str]:
    """Return a copy of the current identity alias map."""
    return dict(_IDENTITY_ALIASES)


def clear_identity_aliases() -> None:
    """Remove all identity aliases, restoring raw artifact IDs."""
    global _IDENTITY_ALIASES
    _IDENTITY_ALIASES = {}


class ProvenanceIntegrator:
    """App-facing facade over provenance compilation and querying.

    Wires DomainRegistry (compilation + caching) + ExecutionContext
    (queries) into the interface the Study Workbench expects.

    ExecutionContext is cached per resolved topic. The precompute runs
    once per ViewState, not once per request (H-PI-02).

    Usage::

        integrator = ProvenanceIntegrator()
        trace = integrator.capture_trace("WACC")
        ctx_str = integrator.tutor_context("WACC", mode_hint="assumption_query")
    """

    def __init__(self, registry: DomainRegistry | None = None):
        self._registry = registry or get_default_registry()
        self._ec_cache: dict[str, tuple[ExecutionContext, DomainEntry]] = {}

    # ── ExecutionContext cache — H-PI-02 ──────────────────────

    def _get_ec(self, resolved: str) -> tuple[ExecutionContext, DomainEntry] | None:
        """Return cached or new (ExecutionContext, DomainEntry) for a resolved topic.

        The ExecutionContext owns the precompute cache (_precompute runs
        once on first query). Reusing the EC across multiple requests
        for the same topic avoids redundant O(N×E) BFS traversal.

        Returns (ec, entry) or None if the topic is not registered.
        """
        cached = self._ec_cache.get(resolved)
        if cached is not None:
            return cached

        entry = self._registry.get(resolved)
        if entry is None:
            return None

        ec = ExecutionContext(entry.viewstate)
        pair = (ec, entry)
        self._ec_cache[resolved] = pair
        return pair

    # ── Topic resolution ──────────────────────────────────────

    def resolve_topic(self, topic: str) -> str:
        """Normalize app topic name to a provenance key."""
        return self._registry.resolve_topic_key(topic)

    # ── Assumption confidence (T-PC-01 default) ───────────────

    def _compute_assumption_confidence(self, entry: DomainEntry) -> dict[str, float]:
        """Per-assumption confidence from inheritance depth.

        Direct assumptions (on the target's own transform) = 0.95.
        Each backward hop decays confidence by 0.10, floor at 0.50.

        Uses the ViewState's transform graph — zero domain knowledge,
        zero kernel changes.
        """
        vs = entry.viewstate
        target_id = entry.output_artifact_id

        reverse: dict[str, list[Transformation]] = {}
        for t in vs.transform_space:
            reverse.setdefault(t.output_artifact_id, []).append(t)

        result: dict[str, float] = {}
        visited: set[str] = set()
        q: deque = deque()
        q.append((target_id, 0))
        visited.add(target_id)

        while q:
            artifact, depth = q.popleft()
            for t in reverse.get(artifact, []):
                for k, v in t.constraints:
                    if k == "assumption" and v not in result:
                        conf = max(0.50, round(0.95 - 0.10 * depth, 2))
                        result[v] = conf
                next_ids = {t.input_artifact_id}
                for k, v in t.constraints:
                    if k == "consumes":
                        next_ids.add(v)
                for next_id in next_ids:
                    if next_id not in visited:
                        visited.add(next_id)
                        q.append((next_id, depth + 1))

        return result

    # ── Trace capture ─────────────────────────────────────────

    def capture_trace(self, topic: str = "") -> dict[str, Any] | None:
        """Compile topic and run provenance queries.

        Returns the same dict format as the old _capture_provenance_trace:
          {topic, artifact_id, step_count, steps, assumptions, consumes,
           dependency_path, prerequisite_artifacts, total_constraints}
        or {"error": "..."} if resolution/compilation fails.
        """
        if not topic:
            return None

        resolved = self.resolve_topic(topic)
        if not resolved:
            return {"error": f"No compiled spec or formula for '{topic}'."}

        result = self._get_ec(resolved)
        if result is None:
            return {"error": f"Topic '{resolved}' resolved but not in registry."}

        ctx, entry = result
        target_id = entry.output_artifact_id

        trace = ctx.inherited_assumptions_fast(target_id)
        prereq = ctx.base_prerequisites_fast(target_id)

        raw_assumptions: list[str] = trace.get("assumptions", [])
        raw_consumes: list[str] = trace.get("consumes", [])

        return {
            "topic": topic,
            "artifact_id": target_id,
            "step_count": 1,
            "steps": [],
            "assumptions": [self._normalize_artifact(a) for a in raw_assumptions],
            "consumes": [self._normalize_artifact(c) for c in raw_consumes],
            "dependency_path": list(trace.get("dependency_path", ())),
            "prerequisite_artifacts": prereq.get("base_prerequisites", []),
            "total_constraints": trace.get("total_constraints", 0),
        }

    # ── Tutor context ─────────────────────────────────────────

    def tutor_context(
        self, chapter: str, mode_hint: str = "", confidence_map: dict[str, float] | None = None
    ) -> str | None:
        """Format provenance context string for tutor prompt.

        Returns a formatted string suitable for build_provenance_context,
        or None if provenance data is unavailable.

        *confidence_map* (T-PC-01): optional override {assumption_name → score}.
        When provided, each assumption rendered as "name [score]" in the
        context string.  When absent (None, the default), scores are
        auto-computed from constraint inheritance depth — direct assumptions
        (same transform) get 0.95, inherited assumptions decay by 0.10 per
        backward hop, floor at 0.50.
        """
        if not chapter:
            return None

        resolved = self.resolve_topic(chapter)
        if not resolved:
            return None

        result = self._get_ec(resolved)
        if result is None:
            return None

        ctx, entry = result
        target_id = entry.output_artifact_id

        data = ctx.inherited_assumptions_fast(target_id)
        if not data:
            return None

        # Normalize through identity alias map (CI-B-01)
        data = dict(data)
        if "assumptions" in data:
            data["assumptions"] = [self._normalize_artifact(a) for a in data["assumptions"]]
        if "consumes" in data:
            data["consumes"] = [self._normalize_artifact(c) for c in data["consumes"]]

        # Inject confidence map (T-PC-01): auto-compute from depth when
        # no explicit map is provided, enabling it for every tutor call.
        if confidence_map is not None:
            data["assumption_confidence"] = confidence_map
        else:
            auto_conf = self._compute_assumption_confidence(entry)
            if auto_conf:
                data["assumption_confidence"] = auto_conf

        from studyplan_ai_tutor import build_provenance_context

        return build_provenance_context(data, mode_hint=mode_hint)

    # ── Identity alias bridge ────────────────────────────────

    def _normalize_artifact(self, name: str) -> str:
        """Resolve *name* through the identity alias map if present.

        When the Compiler has merged local identity IDs (e.g.
        "pdf:doc3:formula.Cost_of_Equity") into canonical IDs
        (e.g. "Cost_of_Equity"), the alias map rewrites raw
        artifact names to their canonical form.

        The module-level map is set by push_identity_aliases()
        and is shared across all integrator instances.
        """
        return _IDENTITY_ALIASES.get(name, name)

    # ── Registry access ───────────────────────────────────────

    @property
    def registry(self) -> DomainRegistry:
        return self._registry

    def clear_cache(self) -> None:
        """Clear the ExecutionContext cache.

        Forces re-precompute on the next request for each topic.
        """
        self._ec_cache.clear()
