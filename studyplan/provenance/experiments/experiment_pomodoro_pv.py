"""PV-01: Pomodoro Timer — Phenomenon-first Prospective Validation.

Protocol: Phenomenon-starting (not principle-starting).
  Derive minimal structure from the Pomodoro phenomenon itself,
  then compare against CCI kernel primitives.

Target: studyplan_engine.py Pomodoro timer (production code).
  Clean target — never read during CCI derivation (Cycles 1-2).

Status: Experiment in progress (not architecture — observations only).
"""

from __future__ import annotations
from dataclasses import dataclass, field


# ──────────────────────────────────────────────
# Step 1: Blind phenomenon description
# ──────────────────────────────────────────────
# Written BEFORE reading CCI primitives or implementation code.
# Describes only what is externally observable.

PHENOMENON_DESCRIPTION = """
The Pomodoro timer structures focused work into discrete intervals:

USER-FACING BEHAVIOR
  - Start a focus session (default 25 min, from schedule)
  - Countdown timer ticks every second
  - 2-min warning notification before expiry
  - 1-min warning notification
  - Timer expiry → session marked complete → break begins
  - Break (5 min default) → after 4th focus, long break (15 min)
  - Focus and break alternate until user stops
  - Pause/resume any session
  - Abandon mid-session → streak resets, session NOT logged
  - Every completed focus is logged permanently

DATA CONTRACTS (from AGENTS.md, no implementation reading):
  pomodoro_log = {"total_minutes": int, "by_chapter": {str: int}}
  action_time_log["pomodoro_focus"] = {"seconds": float, "sessions": int}
  action_time_log["pomodoro_recall"] = {"seconds": float, "sessions": int}

INTEGRATIONS (from AGENTS.md):
  Dashboard — reads pomodoro_log, renders stats
  Streak tracking — resets on abandon, increments on completion
  Study plan — block minutes from schedule, not hardcoded
  Action logging — every start/complete logged

OPEN QUESTIONS (known unknowns):
  - Are breaks logged separately or implied by focus sequence?
  - Does recall use a separate timer or share focus structure?
  - Does long-break counter persist across app restarts?
"""


# ──────────────────────────────────────────────
# Step 2: Minimal model (phenomenon-derived)
# ──────────────────────────────────────────────
# Core concepts: Block, Session, Log, Streak
# Design constraint: must be representable using ViewState primitives.


@dataclass(frozen=True)
class Block:
    """An uninterrupted work interval with a type and duration."""

    type: str  # "focus" | "break" | "long_break"
    duration_minutes: int
    started_at: str | None = None  # ISO timestamp, None = not yet started
    chapter: str | None = None
    paused_elapsed: int = 0  # seconds paused so far (pause/resume support)

    @property
    def remaining_seconds(self) -> int | None:
        """Derivable: duration - elapsed. NOT stored — computed."""
        if self.started_at is None:
            return None
        total_seconds = self.duration_minutes * 60
        elapsed = self.paused_elapsed
        # In the real implementation, elapsed also includes wall-clock time
        # since started_at minus paused_elapsed. This is the derivation.
        return max(0, total_seconds - elapsed)


@dataclass(frozen=True)
class Session:
    """The permanent record of one completed focus block."""

    type: str  # "focus" | "recall"
    duration_minutes: int
    completed_at: str  # ISO timestamp
    chapter: str | None = None
    was_abandoned: bool = False


@dataclass(frozen=True)
class Log:
    """Append-only collection of completed sessions."""

    sessions: tuple[Session, ...] = field(default_factory=tuple)

    @property
    def focus_sessions(self) -> tuple[Session, ...]:
        return tuple(s for s in self.sessions if s.type == "focus" and not s.was_abandoned)

    @property
    def consecutive_focus_count(self) -> int:
        """Number of consecutive completed focus sessions (streak)."""
        count = 0
        for s in sorted(
            [s for s in self.sessions if s.type == "focus"],
            key=lambda x: x.completed_at,
            reverse=True,
        ):
            if s.was_abandoned:
                break
            count += 1
        return count


# ──────────────────────────────────────────────
# Step 3: CCI lens — what the kernel provides
# ──────────────────────────────────────────────
#
# Artifact types available (schema v3, frozen):
#   "config_value" — flexible; can encode any data as metadata
#   "runtime_trace_event" — closest to "a thing that happened"
#
# Primitives available:
#   identity — no-op
#   projection — filter artifacts/transforms by predicate
#   traversal — BFS over transform edges from seed set
#   reduction — equivalence classes (stub: singletons only)
#   compose — chain primitives
#   collect_inherited_constraints — BFS constraint collection
#
# MAPPING:
#
#   Session → Artifact(type="config_value")
#     Metadata: {type, duration_minutes, completed_at, chapter, was_abandoned}
#
#   Block → Ephemeral app state (not in ViewState)
#     The "current timer" is mutable and single-valued.
#     ViewState handles the ARCHIVAL side (the Log).
#     The runtime timer is app-layer ephemeral state.
#
#   Log → ViewState.artifact_space
#     Collection of Session artifacts.
#     No transforms needed for the log — it's append-only.
#
#   Schedule duration → config_value artifact + generative_mapping transform
#     Same pattern as FM topic parameters.
#
#   Block alternation → Transform chain:
#     focus_complete → generative_mapping → break_begin
#     break_complete → generative_mapping → focus_begin
#     long_break rule: constraint on the alternation transform
#
#   Streak → Application-layer aggregation over projected artifacts:
#     projection(filter_type="artifact", predicate=lambda a: ...)
#     → sorted list → consecutive count
#     The kernel has no sort/aggregate primitive.
#     Streak lives at the application layer.
#
# FIT ASSESSMENT:
#   Good fit:   Session as config_value artifact
#   Good fit:   Log as artifact_space (immutable, append-only)
#   Good fit:   Schedule duration as config_value + generative_mapping
#   Good fit:   Block alternation as transform chain with constraints
#   Workaround: Timer tick is derivable from (started_at, duration), not stored
#   Workaround: Pause/resume needs paused_elapsed field (overcomplicates derivation)
#   Misfit:     Ordering (streak requires sorted sequence, kernel is set-based)
#   Misfit:     Notifications at temporal thresholds (kernel has no event scheduling)
#   Gap:        No "pomodoro_session" or "timer_event" in ARTIFACT_TYPES

# STRING on why ordering is a real misfit:
# projection returns frozenset[Artifact] — unordered.
# Most aggregates (streak, last_session, session_count_between)
# require ordered sequences by completed_at.
# The kernel can project, but an application layer must sort and aggregate.
# This is a clean boundary: the kernel is set-based; ordering is an app concern.


# ──────────────────────────────────────────────
# Step 4: Falsifiable predictions
# ──────────────────────────────────────────────

PREDICTIONS: dict[str, dict] = {
    "P1_session_as_artifact": {
        "statement": "A completed focus session can be encoded as an Artifact(type='config_value') "
        "with metadata containing type, duration, completed_at, chapter, was_abandoned. "
        "No new artifact type is required.",
        "test": "Build a ViewState with 3 session artifacts, project by type='focus', verify 2 returned.",
        "falsified_if": "The kernel rejects config_value artifacts with pomodoro metadata, "
        "or projection cannot filter by metadata fields.",
        "status": "untested",
    },
    "P2_streak_as_projection_plus_count": {
        "statement": "Streak (consecutive completed focus sessions) can be computed "
        "as: projection on focus sessions → sort by completed_at → "
        "linear scan counting non-abandoned. The kernel handles projection; "
        "sorting and counting are application-layer.",
        "test": "Project focus sessions from a ViewState with interleaved focus/abandoned, "
        "sort by completed_at, count consecutive non-abandoned from most recent.",
        "falsified_if": "Projection cannot filter on Artifact metadata values, "
        "or artifact ordering cannot be reconstructed from metadata.",
        "status": "untested",
    },
    "P3_block_alternation_as_transform_chain": {
        "statement": "The focus↔break alternation (with long break every 4th break) "
        "can be expressed as a chain of generative_mapping transforms "
        "with constraints encoding the alternation rule.",
        "test": "Define transforms focus→break and break→focus. "
        "Traverse from focus to long_break and verify path includes exactly "
        "8 steps (4 focus + 4 break, with the 4th break being long).",
        "falsified_if": "generative_mapping transforms cannot model stateful alternation "
        "(the counter requires metadata, not just graph topology).",
        "status": "untested",
    },
    "P4_ephemeral_not_archival": {
        "statement": "The kernel's immutable ViewState naturally handles the archival side "
        "(Session Log) but NOT the mutable current timer state. "
        "The current timer is ephemeral app state, not kernel provenance.",
        "test": "The kernel's compose primitive can chain projections over the log "
        "without any reference to 'current timer state.' "
        "All timer queries succeed without mutable state in ViewState.",
        "falsified_if": "Any kernel query about the timer requires mutable state "
        "that cannot be pre-computed from the log.",
        "status": "untested",
    },
    "P5_order_misfit": {
        "statement": "Ordered-sequence aggregation (streak, last_N) does not fit "
        "the kernel's set-based primitive model. The kernel provides "
        "no sort or ordered-aggregate primitive. This is a genuine "
        "architectural boundary, not a missing feature.",
        "test": "Attempt to compute streak using only compose(projection, traversal, reduction). "
        "Show it requires ≥1 application-layer helper outside the kernel.",
        "falsified_if": "Streak can be computed using only existing kernel primitives "
        "without any application-layer sort/aggregate.",
        "status": "untested",
    },
}


# ──────────────────────────────────────────────
# Step 5: Results (filled after test execution)
# ──────────────────────────────────────────────

RESULTS: dict[str, str] = {
    "P1_session_as_artifact": "",
    "P2_streak_as_projection_plus_count": "",
    "P3_block_alternation_as_transform_chain": "",
    "P4_ephemeral_not_archival": "",
    "P5_order_misfit": "",
}


def summarize() -> str:
    confirmed = sum(1 for v in PREDICTIONS.values() if v["status"] == "confirmed")
    refuted = sum(1 for v in PREDICTIONS.values() if v["status"] == "refuted")
    untested = sum(1 for v in PREDICTIONS.values() if v["status"] == "untested")
    total = len(PREDICTIONS)

    lines = [
        "=" * 60,
        "PV-01: Pomodoro Timer — Results Summary",
        "=" * 60,
        f"Total predictions: {total}",
        f"  ✔ Confirmed: {confirmed}",
        f"  ✘ Refuted:   {refuted}",
        f"  ? Untested:  {untested}",
        "",
    ]
    for pid, pdata in PREDICTIONS.items():
        status = pdata.get("status", "untested")
        symbol = {"confirmed": "✔", "refuted": "✘", "untested": "?"}.get(status, "?")
        lines.append(f"  {symbol} {pid}: {pdata['statement'][:80]}...")
    lines.append("")
    lines.append(
        f"Agreement rate: {confirmed}/{total - untested} ({confirmed / max(total - untested, 1) * 100:.0f}%) of tested"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(PHENOMENON_DESCRIPTION)
    print()
    print(summarize())
