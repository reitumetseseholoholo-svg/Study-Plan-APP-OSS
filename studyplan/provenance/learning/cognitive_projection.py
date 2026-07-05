"""CognitiveProjectionEngine — event → latent cognitive state projection.

Essentialist question:
    What phenomenon does this projection exist to preserve?
Answer:
    Grounded cognitive inference — the property that learner state is
    *derived* from observable interaction patterns, not invented from
    psychological theory.  Every output signal is a pure function of
    existing compiler.* events.

Rule 2 (Necessary Existence):
    No new state.  No new event types.  The projection is ephemeral —
    recomputed from event history on every call.  Only the event bus
    is persistent.

Signals and their event-derived proxies:
    Uncertainty     ← review_decision.decision_latency_ms
                      + candidate_compared count per group
    Confusion edges ← candidate_compared.compared_ids co-occurrence
                      + review_decision.alternatives pairs
    Stability       ← low revisit rate across decisions
                      + confidence consistency
    Familiarity     ← recency-weighted interaction count
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from studyplan.provenance.learning.events import EventEnvelope


@dataclass(frozen=True)
class NodeProjection:
    """Latent cognitive state for a single concept/identity.

    All scores are 0–1.  Derived entirely from event history.
    """

    identity_id: str
    label: str = ""
    uncertainty_score: float = 0.0
    stability_score: float = 1.0
    interaction_count: int = 0
    last_seen: float = 0.0


@dataclass(frozen=True)
class ConfusionEdge:
    """Empirical confusion structure inferred from comparison patterns.

    weight:         0–1, co-comparison frequency
    directionality: -1 to 1, asymmetry of confusion (sign flips = symmetric)
    """

    source_id: str
    target_id: str
    weight: float = 0.0
    directionality: float = 0.0


@dataclass(frozen=True)
class CognitiveProjection:
    """Ephemeral snapshot of latent cognitive signals.

    Computed on demand from event bus history.  Never persisted.
    """

    nodes: dict[str, NodeProjection] = field(default_factory=dict)
    confusion_edges: list[ConfusionEdge] = field(default_factory=list)
    event_count: int = 0
    computed_at: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.nodes and not self.confusion_edges


class CognitiveProjectionEngine:
    """Project compiler event history → latent cognitive signals.

    Usage::

        engine = CognitiveProjectionEngine()
        projection = engine.project(get_compiler_bus().history())
        projection.nodes["fm:WACC"].uncertainty_score  # 0–1
    """

    def project(self, events: list[EventEnvelope]) -> CognitiveProjection:
        """Compute cognitive projection from an event list.

        Pure function.  No side effects.  No state.
        """
        if not events:
            return CognitiveProjection(event_count=0, computed_at=0.0)

        import time

        now = time.time()

        uncertainty = self._project_uncertainty(events)
        confusion = self._project_confusion_edges(events)
        stability = self._project_stability(events)
        familiarity = self._project_familiarity(events, now)

        node_ids = set()
        node_ids.update(uncertainty.keys())
        node_ids.update(stability.keys())
        node_ids.update(familiarity.keys())

        nodes: dict[str, NodeProjection] = {}
        for nid in sorted(node_ids):
            label = uncertainty.get(nid, {}).get("label", "")
            nodes[nid] = NodeProjection(
                identity_id=nid,
                label=label,
                uncertainty_score=uncertainty.get(nid, {}).get("score", 0.0),
                stability_score=stability.get(nid, 1.0),
                interaction_count=familiarity.get(nid, {}).get("count", 0),
                last_seen=familiarity.get(nid, {}).get("last_seen", 0.0),
            )

        return CognitiveProjection(
            nodes=nodes,
            confusion_edges=sorted(confusion, key=lambda e: (e.source_id, e.target_id)),
            event_count=len(events),
            computed_at=now,
        )

    # ── Projection functions ──────────────────────────────────

    def _project_uncertainty(
        self,
        events: list[EventEnvelope],
    ) -> dict[str, dict[str, Any]]:
        """Uncertainty from decision latency + comparison count.

        High latency → high uncertainty.
        Many comparisons per group → high uncertainty.
        Score = min(1.0, (normalized_latency + normalized_comparisons) / 2)
        """
        from collections import defaultdict

        latencies: list[float] = []
        comparisons: dict[str, list[int]] = defaultdict(list)

        for ev in events:
            p = ev.payload
            if ev.type == "compiler.review_decision":
                lat = p.get("decision_latency_ms", 0)
                if isinstance(lat, (int, float)) and lat > 0:
                    latencies.append(float(lat))

            if ev.type == "compiler.candidate_compared":
                gid = p.get("group_id", "")
                if gid:
                    comparisons[gid].append(1)

        result: dict[str, dict[str, Any]] = {}

        for ev in events:
            p = ev.payload
            if ev.type == "compiler.review_decision":
                lat = p.get("decision_latency_ms", 0)
                lat_score = 0.5
                if isinstance(lat, (int, float)) and lat > 0 and latencies:
                    lat_score = min(1.0, lat / max(latencies))

                cmp_count = 0
                for alt in p.get("alternatives", []):
                    if alt:
                        cmp_count += 1
                for cid in p.get("candidate_ids", []):
                    if cid not in result:
                        result[cid] = {"score": 0.0, "label": ""}
                    result[cid]["label"] = ", ".join(p.get("candidate_labels", []))

                    comp_score = min(1.0, cmp_count / max(cmp_count, 1))
                    score = (lat_score + comp_score) / 2.0
                    result[cid]["score"] = round(min(1.0, max(0.0, score)), 4)

        return result

    def _project_confusion_edges(
        self,
        events: list[EventEnvelope],
    ) -> list[ConfusionEdge]:
        """Confusion edges from co-comparison patterns.

        Every pair of IDs compared together gets +1 weight.
        Also pairs chosen_vs_alternative from review_decisions.
        Normalized to 0-1 by max weight.
        """
        from collections import defaultdict

        edge_weights: dict[tuple[str, str], float] = defaultdict(float)

        for ev in events:
            p = ev.payload
            if ev.type == "compiler.candidate_compared":
                primary = p.get("primary_id", "")
                compared = p.get("compared_ids", [])
                if primary and compared:
                    for cid in compared:
                        if cid and cid != primary:
                            key = tuple(sorted([primary, cid]))
                            edge_weights[key] += 1.0

            if ev.type == "compiler.review_decision":
                chosen = p.get("chosen_id", "")
                alts = p.get("alternatives", [])
                if chosen and alts:
                    for alt in alts:
                        if alt and alt != chosen:
                            key = tuple(sorted([chosen, alt]))
                            edge_weights[key] += 0.5

        if not edge_weights:
            return []

        max_w = max(edge_weights.values())
        edges: list[ConfusionEdge] = []
        for (a, b), w in edge_weights.items():
            weight = round(w / max_w, 4)
            edges.append(
                ConfusionEdge(
                    source_id=a,
                    target_id=b,
                    weight=weight,
                    directionality=0.0,
                )
            )

        return edges

    def _project_stability(
        self,
        events: list[EventEnvelope],
    ) -> dict[str, float]:
        """Stability from decision revisit rate.

        Concepts with fewer unique decisions per interaction → high stability.
        Concepts with consistent confidence across decisions → high stability.
        """
        from collections import defaultdict

        decisions: dict[str, list[float]] = defaultdict(list)
        revisit_count: dict[str, int] = defaultdict(int)

        for ev in events:
            p = ev.payload
            if ev.type == "compiler.review_decision":
                conf = p.get("confidence", 0.5)
                if not isinstance(conf, (int, float)):
                    conf = 0.5
                for cid in p.get("candidate_ids", []):
                    if cid:
                        decisions[cid].append(float(conf))
                        revisit_count[cid] += 1

        result: dict[str, float] = {}
        for nid, confs in decisions.items():
            if not confs:
                result[nid] = 1.0
                continue
            n = len(confs)
            mean_conf = sum(confs) / n

            variance = sum((c - mean_conf) ** 2 for c in confs) / n
            consistency = max(0.0, 1.0 - math.sqrt(variance))

            revisit_penalty = min(1.0, n / 10.0)
            stability = max(0.0, round(consistency * (1.0 - 0.2 * revisit_penalty), 4))
            result[nid] = stability

        return result

    def _project_familiarity(
        self,
        events: list[EventEnvelope],
        now: float,
    ) -> dict[str, dict[str, Any]]:
        """Familiarity from recency-weighted interaction count.

        Counts every event referencing an identity.
        Decays with time since last interaction.
        """
        half_life = 86400.0 * 7  # 7 days in seconds

        from collections import defaultdict

        interactions: dict[str, int] = defaultdict(int)
        last_seen: dict[str, float] = {}

        for ev in events:
            p = ev.payload
            candidate_ids: list[str] = []
            if "candidate_ids" in p:
                candidate_ids = p["candidate_ids"]
            elif "compared_ids" in p:
                candidate_ids = p["compared_ids"]
            elif "identity_id" in p:
                candidate_ids = [p["identity_id"]]

            for cid in candidate_ids:
                if cid:
                    interactions[cid] += 1
                    if ev.timestamp > last_seen.get(cid, 0):
                        last_seen[cid] = ev.timestamp

        result: dict[str, dict[str, Any]] = {}
        for nid, count in interactions.items():
            last = last_seen.get(nid, now)
            delta = max(0.0, now - last)
            decay = math.exp(-delta / half_life)
            result[nid] = {
                "count": count,
                "last_seen": last,
                "decay": round(decay, 4),
            }

        return result
