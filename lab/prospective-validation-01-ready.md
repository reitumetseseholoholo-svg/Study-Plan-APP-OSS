# Prospective Validation 01 — LOCKED PREDICTIONS

**Protocol**: RESEARCH_PROTOCOL.md v3 (frozen per Constitutional Amendment I)
**Target**: GTK4 GUI (`studyplan_app.py` — dashboard, study room, coach panel)
**Prior exposure**: AGENTS.md (dashboard architecture, chart caching, coach briefing)
**Locked**: 2026-07-04, before reading any GUI code beyond AGENTS.md

---

## Predictions

### P1 — Lifecycle (I1)

**Prediction**: The dashboard rendering function will follow `initialize → [rebuild ×N] → cleanup`. There will be a setup phase (create containers, attach CSS, connect signals), followed by a periodic rebuild triggered by timer or data-change events, followed by a destroy phase on window close.

**Prior knowledge**: I know `_render_dashboard` exists and "clears and rebuilds all dashboard children every refresh." But I don't know the exact lifecycle structure.

**Rationale**: If I1 is a Kernel law, its pattern (init → step×N → terminate) should generalize to any repeatedly-executed operation in the system, including UI rendering.

---

### P2 — Trace Immutability (I2)

**Prediction**: When the GUI reads data from the engine for display, it will take a snapshot (copy) rather than holding a live reference. Charts rendered from cached data will not mutate after rendering begins.

**Prior knowledge**: I know chart caching uses `_cached_*_sig` + `_cached_*_widget` pairs and that signature comparison prevents rebuild when data is unchanged. This suggests immutability is practiced but I don't know if it's enforced.

**Rationale**: I2 predicts that any downstream consumer treats its input as read-only. If the GUI mutates engine data after reading, it violates the spirit of I2.

---

### P3 — Causal Provenance (I3)

**Prediction**: Dashboard refresh triggers will carry provenance — at minimum which event caused the refresh (timer tick, data update, user action). UI event handlers will record what triggered them.

**Prior knowledge**: None specific. I know there's a timer and manual refresh but not whether provenance is tracked.

**Rationale**: If every event must carry causal provenance, UI events should too. Without it, you can't determine why the UI refreshed.

---

### P4 — Runtime Agnosticism (I4)

**Prediction**: The GUI will consume data through interpreters or a data layer, not by directly accessing `CognitiveProcess` instances. The dashboard will not import or reference `ComputationProcess`, `ClassificationProcess`, etc.

**Prior knowledge**: I know `_eng` (engine reference), `_chapters`, `_competence`, `_progress_log`, `_srs_data` are cached as locals. These look like interpreted results, not raw process state.

**Rationale**: I4 predicts a clean boundary between execution and consumption. The GUI should be algebra-agnostic.

---

### P5 — Process Statelessness (I5)

**Prediction**: Each `_render_dashboard` call will fetch fresh data from the engine and rebuild from scratch. Widgets will not accumulate state across refresh cycles.

**Prior knowledge**: AGENTS.md explicitly states "clears and rebuilds all dashboard children every refresh." This prediction is fully contaminated.

**Rationale**: I5 predicts fresh state per invocation. The dashboard refresh should not depend on stale data from previous renders.

---

### P6 — Interpreter Independence / Trace Sufficiency (I6)

**Prediction**: GUI components that display cognitive results (quiz results, mastery scores, competence charts) will consume interpreted result dicts, not raw `ExecutionTrace` objects. No UI code will iterate `trace.events` directly to extract display data.

**Prior knowledge**: None specific.

**Rationale**: I6 predicts the trace is the sole data source for interpretation, and interpreters produce the output. The GUI should consume interpreter output, not raw traces.

---

### P7 — Validity Signal (I7)

**Prediction**: Any GUI component that displays a cognitive result (quiz outcome, concept mastery, classification result) will check for a validity signal (null, NaN, error flag) before rendering. Components will have explicit "empty state" rendering.

**Prior knowledge**: None specific.

**Rationale**: I7 predicts that validity checks are universal at consumption points. The GUI should not assume engine data is always valid.

---

### P8 — State Hashing (I8)

**Prediction**: Chart caching will use deterministic signatures derived from the underlying data (not timestamps or random IDs). Same data → same cache key.

**Prior knowledge**: AGENTS.md mentions `_cached_*_sig` as a tuple of data values. This strongly predicts deterministic caching.

**Rationale**: I8 predicts that state identity is determined by content, not by reference. The GUI's cache should follow the same principle.

---

### P9 — State Partitioning (I9)

**Prediction**: The dashboard's render function will separate data acquisition (reading engine state) from rendering (building GTK widgets). The data (inputs) will be distinct from the display state (control) and the rendered output.

**Prior knowledge**: AGENTS.md mentions "Engine references cached as locals" and "single-pass derived caches" — suggesting data is pre-processed before rendering.

**Rationale**: I9 predicts that state is partitioned into three roles. The dashboard data flow should reflect this partitioning.

---

### P10 — Step Return Shape (I10)

**Prediction**: Functions within the GUI that produce new state (e.g., refresh callbacks, timer ticks) will return a well-defined shape containing at minimum the new state. Additional metadata may be present but at minimum the state change is explicit.

**Prior knowledge**: None specific. This is the hardest principle to generalize to GUI because it's specifically about step()'s return contract.

**Rationale**: Generalized: any function that transforms state should produce a clearly identifiable new state.

---

### P11 — Dual Protocol (I11)

**Prediction**: The GUI will accept multiple interchangeable data sources with the same interface. For example, dashboard data might come from the engine directly, from a cache, or from a test fixture — all through the same interface.

**Prior knowledge**: None specific.

**Rationale**: I11 predicts that multiple protocols can satisfy the same contract. The GUI's data layer should follow this pattern.

---

### P12 — Constructor Divergence (I12 — Candidate)

**Prediction**: Different GUI components (dashboard cards, chart widgets, coach panel) will have different constructor patterns. Some will be simple Gtk.Box instantiations, others will require complex configuration.

**Prior knowledge**: None specific. This is a weak prediction — it's almost a tautology in a large GUI.

**Rationale**: I12 predicts that constructor divergence is normal and not evidence of architectural inconsistency.

---

### P13 — Interpreter Event Iteration (I13 — Candidate)

**Prediction**: Each GUI component that renders from data will independently iterate over its data source. There will be no shared "iterate all data and dispatch to widgets" function in the CCI layer.

**Prior knowledge**: None specific. But I know there are ~35 dashboard sections, each likely self-contained.

**Rationale**: I13 predicts independent iteration. Each widget fetches and processes its own data.

---

### P14 — Step Comparison Envelope (I14)

**Prediction**: N/A — I14 is specific to step evaluator results. There should be no direct analogue in the GUI.

**Prediction**: The GUI will NOT have a uniform "comparison envelope" for displaying results. Comparison rendering will be ad-hoc per widget.

---

## Summary

| Prediction | Confidence | Prior knowledge contamination |
|------------|------------|------------------------------|
| P1 — Lifecycle | High | Partial (know _render_dashboard exists) |
| P2 — Immutability | Medium | Partial (know caching exists) |
| P3 — Provenance | Medium | None |
| P4 — Agnosticism | High | Medium (know engine refs cached) |
| P5 — Statelessness | High | **Fully contaminated** — known from AGENTS.md |
| P6 — Interpreter Independence | Medium | None |
| P7 — Validity Signal | Medium | None |
| P8 — State Hashing | High | **Fully contaminated** — known from AGENTS.md |
| P9 — State Partitioning | Medium | Partial (know data pre-processing exists) |
| P10 — Step Return Shape | Low | None |
| P11 — Dual Protocol | Low | None |
| P12 — Constructor Divergence | Low | None |
| P13 — Interpreter Event Iteration | Medium | None |
| P14 — Step Comparison Envelope | Medium | None |

---

## Lock timestamp

**Predictions locked at**: 2026-07-04
**Before reading**: Any GUI source code beyond AGENTS.md metadata
**Status**: LOCKED — no further modifications permitted
