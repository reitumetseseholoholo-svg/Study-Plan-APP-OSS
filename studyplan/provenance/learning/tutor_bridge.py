from __future__ import annotations


from studyplan.provenance.learning.event_bus import EventBus
from studyplan.provenance.learning.events import EventEnvelope


def build_learning_context(bus: EventBus) -> str | None:
    """Extract the latest kernel intelligence state from the event bus.

    Returns a formatted string for injection into the tutor prompt,
    or None if there is no relevant data yet.
    """
    lines: list[str] = []

    belief = _latest_event(bus, "belief.state_update")
    interp = _latest_event(bus, "interpretation.result")
    transition = _latest_event(bus, "transition.update")
    scheduler = _latest_event(bus, "scheduler.runqueue")
    rollout_ev = _latest_event(bus, "rollout.simulation")

    if belief is None and interp is None and scheduler is None and transition is None and rollout_ev is None:
        return None

    lines.append("[LEARNING CONTEXT]")

    if interp is not None:
        p = interp.payload
        lines.append(
            f"  Last attempt: {p['error_type']} (severity: {p['severity']:.2f}, confidence: {p['confidence']:.2f})"
        )
        if p.get("misconceptions"):
            lines.append(f"  Misconceptions: {'; '.join(p['misconceptions'])}")

    if belief is not None:
        p = belief.payload
        lines.append(f"  Mastery: {p['mastery_mean']:.2f} ± {p['mastery_variance']:.2f}")
        errors = p.get("error_beliefs", {})
        top_errors = sorted(errors.items(), key=lambda x: -x[1])[:3]
        if top_errors and top_errors[0][0] != "none":
            err_str = "; ".join(f"{k}: {v:.2f}" for k, v in top_errors)
            lines.append(f"  Error profile: {err_str}")

    if transition is not None:
        p = transition.payload
        delta = p.get("delta", {})
        dm = delta.get("mastery_mean", 0.0)
        lines.append(f"  Learning delta: {dm:+.3f} ({p['intervention']})")

    if scheduler is not None:
        p = scheduler.payload
        queue = p.get("queue", [])
        if queue:
            next_action = queue[0]
            lines.append(f"  Next planned: {next_action['intervention']} (priority: {next_action['priority']:.2f})")
            if len(queue) > 1:
                alt = queue[1]
                lines.append(f"  Alternative: {alt['intervention']} (priority: {alt['priority']:.2f})")

    if rollout_ev is not None:
        p = rollout_ev.payload
        traj = p.get("predicted_trajectory", [])
        if traj:
            start = traj[0].get("mastery", 0.0)
            end = traj[-1].get("mastery", 0.0)
            lines.append(
                f"  Predicted: {start:.2f} → {end:.2f} "
                f"(gain: {p['expected_gain']:.3f}, uncertainty: {p['uncertainty']:.3f})"
            )

    lines.append("")
    return "\n".join(lines)


def _latest_event(bus: EventBus, event_type: str) -> EventEnvelope | None:
    events = bus.events_by_type(event_type)
    return events[-1] if events else None
