# Prospective Validation 01 — SCORED

**Protocol**: RESEARCH_PROTOCOL.md v3 (frozen)
**Target**: GTK4 GUI (`studyplan_app.py` — dashboard rendering)
**Analysis date**: 2026-07-04
**Prior exposure**: AGENTS.md (partial — documented in locked predictions)

---

## Scoring

| ID | Prediction | Result | Evidence |
|----|-----------|--------|----------|
| P1 | Dashboard follows init → rebuild×N → cleanup lifecycle | **✔** | Entry gate (53705) → setup/preprocessing (53739) → build ~35 sections (53890) → reconcile orphans (56886) → finalize (56887). Digest fast-skip prevents unnecessary full renders (53715). |
| P2 | Engine data is immutable after receipt by GUI | **◐** | Data references are captured once per render (53882–53888) but NOT copied — same dict objects as engine. No GUI code writes back to engine data, so immutability is practiced by convention but not enforced. |
| P3 | Dashboard refresh events carry provenance | **✘** | `update_dashboard()` has no `reason` parameter across all 30 call sites. No provenance enum, no `_refresh_cause` attribute, no tracking of what triggered the render. |
| P4 | Dashboard does not import/reference CognitiveProcess | **✔** | Process types imported at module level (line 140, 148) but used ONLY in on-demand `_capture_cognitive_trace`. Main dashboard consumes interpreted engine dicts only. |
| P5 | Each render fetches fresh data, no stale accumulation | **✔** | `getattr(self.engine, ...)` re-reads data each render (53882–53888). Chart cache avoids unnecessary rebuilds when data unchanged — not stale accumulation. |
| P6 | GUI consumes interpreter output, not raw traces | **✔** | Dashboard consumes `competence`, `quiz_results`, `srs_data`, `progress_log` — interpreted engine output. Raw trace iteration limited to on-demand "Decision trace" feature. |
| P7 | GUI checks validity signals before rendering | **✔** | Fallback defaults (`or {}`), type checks (`isinstance`), data volume gates (`if len >= 2`), `_safe_float()` converter, early return on missing data. |
| P8 | Chart cache keys are deterministic data signatures | **✔** | All signatures use data-only tuples with `round()` normalization. No timestamps, random values, or counters. Same data → same key. |
| P9 | Data fetching separated from rendering (three-role partition) | **◐** | Clear two-phase structure: data preprocessing (53882–53958) then widget creation (~54000–56884). BUT not strict — several sections re-access engine mid-render (54127, 55765, 56624, 56535). |
| P10 | State-producing functions return well-defined shapes | **✘** | `_render_dashboard` modifies widget tree directly, returns nothing. Callbacks don't return state shapes. The "step returns next_state" contract does not generalize to GUI rendering. |
| P11 | GUI accepts multiple interchangeable data sources | **✘** | All data from `self.engine` via direct attribute access. No dependency injection, no abstraction layer, no mock injection point. Only variation is `or {}` fallback. |
| P12 | Different widgets have different constructor patterns | **✔** | ~35 sections built with diverse patterns: simple Gtk.Box, nested structures, helper calls, chart builders, on-demand buttons. Constructor divergence is the norm. |
| P13 | Each widget independently iterates its data | **✔** | Each dashboard section has its own data-fetching and widget-building logic. Shared `_build_gtk_chart_widget` is visual helper, not data iteration helper. |
| P14 | No uniform comparison envelope in GUI | **✔** | No step evaluator comparison pattern exists. Each widget displays comparison data (progress, competence, scores) in its own way. |

---

## Unexpected Discoveries (★)

| # | Finding | Location | Why surprising |
|---|---------|----------|----------------|
| ★1 | **Digest fast-skip**: A 7-field digest (`focus_mode, tile_mode, coach_pick_topic, exam_date, current_topic, has_chapters, onboarding`) can skip the entire dashboard render. Prevents all ~35 sections from rebuilding when high-level state hasn't changed. | 53715–53733 | No equivalent in CCI, where execution always runs unconditionally. The "do nothing" path is a first-class optimization in the GUI. |
| ★2 | **Materialized views**: Single-pass derived caches computed before rendering: `_parsed_progress` (date→mastery→minutes), `_sorted_competence` (sorted), `_srs_overdue_by_ch`/`_srs_due_soon_by_ch`/`_srs_due_week_by_ch`/`_srs_next_due` (per-chapter aggregates). | 53882–53958 | CCI has no preprocessing phase — data flows through trace → interpreter → output without aggregation. The GUI pre-aggregates before consumption. |
| ★3 | **On-demand lazy charts**: Activity chart, concept forest, cognitive trace are hidden behind buttons. Data is computed only when user clicks. | 56783–56882 | CCI is always eager — execute produces the trace, interpreters consume it immediately. The GUI defers expensive computation to interaction time. |
| ★4 | **Guard-centric refresh**: Entry gate checks (shutdown, in-progress, rate limit at 0.8s) + digest fast-skip — three separate mechanisms to avoid rendering. | 53705–53736 | CCI has no pre-execution guards. The runtime just runs. The GUI's refresh model is about avoiding work; CCI's model is about producing evidence. |

---

## Aggregate Metrics

```
predictions_made: 14
  ✔ confirmed:   9
  ◐ partial:     2
  ✘ refuted:     3
  ★ unexpected:  4

agreement_rate:    (9 + 2) / (9 + 2 + 3) = 11/14 = 78.6%
surprise_rate:     4 / 14 = 28.6%
predictive_accuracy: 9 / (9 + 3) = 75.0%
```

---

## What surprised us?

Four unexpected discoveries (★). The most significant:

1. **The GUI optimizes by not doing work.** CCI runs unconditionally and produces immutable evidence. The GUI has three independent mechanisms to avoid rendering (entry gate, digest skip, rate limiter). This is a fundamentally different philosophy: *avoid vs. produce*.

2. **Materialized views precede consumption.** The dashboard computes `_parsed_progress`, `_sorted_competence`, and `_srs_overdue_by_ch` in a single preprocessing pass before any widget is built. CCI has no equivalent — interpreters read the trace directly without pre-aggregation. The GUI architecture adds a "preprocessing" phase that CCI doesn't need because CCI's data is already structured.

3. **Lazy evaluation for expensive sections.** Three sections (activity chart, concept forest, cognitive trace) are not computed at all until the user clicks a button. This is an optimization strategy that doesn't exist in CCI, where everything is eager.

---

## What this means for the CCI principles

| Principle | Effect on confidence |
|-----------|---------------------|
| I1 (Lifecycle) | **Increased** — generalized to a completely different domain (UI rendering) with no refutation |
| I2 (Immutability) | **Maintained** — partially confirmed; convention-only enforcement is consistent with the Ownership scan finding |
| I3 (Provenance) | **Decreased** — no provenance in UI events. The principle may be specific to cognitive execution traces, not universal |
| I4 (Agnosticism) | **Increased** — clean boundary between cognitive execution and UI consumption confirmed |
| I5 (Statelessness) | **Increased** — each render fetches fresh data, confirming the pattern generalizes |
| I6 (Independence) | **Increased** — GUI consumes interpreted data only, confirming trace-sufficiency extends to the UI layer |
| I7 (Validity) | **Increased** — validity checks are universal at consumption points, confirming the principle generalizes |
| I8 (Hashing) | **Increased** — deterministic data signatures confirmed in a completely different caching context |
| I9 (Partitioning) | **Maintained** — partially confirmed; partition exists but is not strict |
| I10 (Step Return) | **Decreased** — does not generalize to GUI. May be specific to CCI's step() contract |
| I11 (Dual Protocol) | **Decreased** — does not generalize to GUI. May be specific to CCI's process/executor pattern |
| I12 (Constructor) | **Increased** — divergence confirmed as normal |
| I13 (Iteration) | **Increased** — independent iteration confirmed in a new context |
| I14 (Envelope) | **Maintained** — trivially confirmed (predicted absence) |

## Conclusions

1. **9 of 14 predictions confirmed or partially confirmed** — strong evidence that CCI principles generalize beyond their origin domain
2. **3 refuted** — I3 (provenance), I10 (step return), I11 (dual protocol) do not hold in the GUI. These may be CCI-specific, not universal architectural principles
3. **4 unexpected discoveries** — the GUI has architectural patterns (digest skip, materialized views, lazy evaluation, guard-centric refresh) not predicted by CCI. These may be GTK-specific optimizations, or they may be architectural patterns that CCI doesn't capture
4. **78.6% agreement rate** — approaching the 80% threshold for a mature principle set
5. **28.6% surprise rate** — above the 10% target, indicating the principle set is incomplete

The protocol survived its first Prospective Validation against an independent subsystem.
