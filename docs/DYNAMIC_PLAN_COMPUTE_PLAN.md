# Dynamic plan compute — app plan and features

Plan to make the **daily plan** (and related planning/feature surfaces) a **dynamic compute**: driven by live data, explicit inputs, and optional strategies so the app always shows a plan that reflects current state instead of a once-per-day snapshot.

---

## Goals

1. **Live plan**: The daily plan (and, where useful, recommendations / coach pick) is recomputed when relevant data changes or when the user switches context, not only at start-of-day.
2. **Explicit inputs**: One clear “plan compute” pipeline: same inputs (competence, outcome coverage, syllabus, exam date, SRS, flow, etc.) every time; no hidden caches that skip updates.
3. **Optional strategies**: Support different “modes” (e.g. outcome-coverage-first, retention-heavy, balanced) so the plan formula can be chosen or tuned without code changes.
4. **Feature visibility**: Optionally make which plan-related features or cards are shown depend on dynamic context (e.g. show “Outcome coverage” only when the module has syllabus data).

---

## Current behaviour (brief)

| Piece | Current behaviour | Limitation |
|-------|-------------------|------------|
| **Daily plan** | `get_daily_plan()` scores chapters (urgency, weights, flow, SRS, ML risk, etc.); result cached in engine (`daily_plan_cache` + date) and in UI (`_last_daily_plan` + `_last_daily_plan_date`). Recompute only when day changes or `_plan_refresh_override` is set (e.g. after PDF import). | Plan is stable “within the day” by design; completing a topic or doing a quiz does not automatically refresh the list. User must rely on coach pick or manual refresh for “what’s next”. |
| **Refresh triggers** | `update_daily_plan()` is called from dashboard load, post-import, and a few other places; debounced. Override can force refresh. | No systematic “invalidate on any competence/outcome/SRS change”. |
| **Recommendations** | AI Coach and top-5 recommendations use engine readiness + optional model; cached until explicit regenerate. | Not tied to a single “plan compute” pipeline. |
| **Coach pick** | Snapshot-based; invalidated when plan refreshes. | Depends on plan being up to date. |

---

## 1. Dynamic compute: when to run

### 1.1 Triggers (when to recompute the plan)

- **Explicit**: User clicks “Refresh plan” or “Next topic” that implies recompute.
- **Data change**: After any write that affects plan inputs:
  - Competence update (quiz, import, manual reset)
  - Outcome event (`record_outcome_event`)
  - SRS update (answer recorded, must-review change)
  - Exam date / availability change
  - Module or syllabus load (chapters, weights, outcome set)
  - Chapter flow or importance_weights edit
- **Visibility**: When the dashboard (or plan widget) becomes visible after being hidden, optionally recompute so the user sees a fresh plan (or at least “plan may have changed” + refresh).
- **Timer (optional)**: Lightweight “recompute at most every N minutes” when app is in foreground, so e.g. background sync or another tab doesn’t leave the plan stale forever.

**Implementation**: Central “plan invalidate” API (e.g. `invalidate_plan()` or `request_plan_refresh(reason)`) that sets a dirty flag and schedules a debounced recompute. All data-change paths that affect the plan call it. UI can call it on visibility if desired.

### 1.2 Cache policy

- **Option A – Dynamic by default**: Do **not** cache plan by day; every time the UI needs the plan, call `get_daily_plan()` with current engine state. Simplest “dynamic compute”; may be slightly more CPU if called often (mitigate with debounce on the *request* side).
- **Option B – Cache until invalidated**: Keep a cache (e.g. `_last_daily_plan` + timestamp or version). Recompute only when invalidated (see triggers above) or when cache is older than a threshold (e.g. 5–10 minutes). Balances freshness and cost.
- **Option C – Hybrid**: Cache per day for “stability” but **invalidate on material events** (competence, outcome, SRS, exam date, syllabus). So “same day” is stable only if nothing changed; any important change triggers recompute.

Recommendation: **Option C** so we keep “plan doesn’t flip every second” but make it clearly dynamic when state changes.

---

## 2. Single “plan compute” pipeline

### 2.1 Inputs (explicit)

Treat the plan as a pure function of:

- **Chapters** (order, flow, importance_weights)
- **Competence** (per chapter)
- **Outcome coverage** (outcome_stats, syllabus_structure) when present
- **SRS** (per-chapter cards, overdue, new)
- **Exam date** (days remaining → sticky thresholds, retention mode, exam_weight)
- **Current topic** (for neighbor/flow bonus)
- **ML recall risk** (when available)
- **Pomodoro / focus** (e.g. today’s minutes per chapter for sticky logic)
- **Optional**: User preference for “plan mode” (see §3)

Engine already has these; the only change is to **always** read them at compute time (no “plan cache” in the engine that skips reading latest competence/outcome_stats, or clear that cache on writes).

### 2.2 Outputs

- **Daily plan**: Ordered list of chapters (top N).
- **Optional**: Same pipeline can output a “plan reason” per chapter (e.g. “weak”, “due reviews”, “outcome gap”) for UI or coach briefing.

### 2.3 Where it runs

- **Engine**: `get_daily_plan(num_topics, current_topic)` remains the single implementation; it must use **current** engine state (no internal day-scoped cache that ignores recent writes, or invalidate that cache when competence/outcome_stats/SRS/exam_date change).
- **App**: Calls `get_daily_plan()` when rendering the plan widget; whether to use a cached list is a UI-level decision (see §1.2). After any action that changes plan inputs, call `invalidate_plan()` so the next render gets a fresh compute.

---

## 3. Optional: pluggable plan strategies

To make the “formula” a **dynamic** choice rather than hardcoded:

### 3.1 Strategy concept

- **Strategy** = a named mode that changes weights or filters in the plan scoring (e.g. “outcome_coverage_first”, “retention”, “balanced”, “exam_cram”).
- **Storage**: Preference or module-level config, e.g. `plan_strategy: "balanced"`.
- **Engine**: `get_daily_plan(..., strategy=None)` uses the strategy to adjust:
  - Which signals are boosted (e.g. outcome-coverage-first: big weight on uncovered outcomes; retention: big weight on SRS overdue and ML risk).
  - Optional filters (e.g. “only chapters with due reviews” in pure retention mode).

### 3.2 Example strategies

| Strategy | Emphasis |
|---------|----------|
| `balanced` | Current behaviour (urgency, weights, flow, SRS, syllabus depth, ML risk). |
| `outcome_coverage` | Prioritise chapters with most uncovered syllabus outcomes; reduce weight of “already high coverage” chapters. |
| `retention` | Prioritise SRS overdue and high ML recall risk; good for final weeks. |
| `exam_cram` | Shorter list, highest urgency only; more sticky to “current topic” until threshold. |

Implementation can be a small registry: `get_daily_plan(..., strategy="outcome_coverage")` multiplies or adds a term derived from `get_capability_coverage_debt` / `_chapter_has_uncovered_outcomes` before sorting.

---

## 4. Feature visibility (dynamic surfaces)

Make **which** plan-related features or cards appear depend on context:

### 4.1 Context flags (computed)

- `has_syllabus`: `syllabus_structure` non-empty and has outcomes.
- `has_exam_date`: exam_date set.
- `has_questions`: at least one chapter with questions.
- `has_outcome_coverage`: outcome_stats or outcome_ids in use.
- `has_rag`: at least one RAG PDF.

### 4.2 Where to use them

- **Dashboard / Study Room**: Show “Outcome coverage” card or link to View Module Metadata only when `has_syllabus` (and optionally `has_outcome_coverage`). Hide or simplify when no syllabus.
- **Plan widget**: If no exam date and no questions, show different hint (“Set exam date or import questions to get a plan”) and optionally still show a small “suggested” list from importance_weights only.
- **Coach briefing**: Include “outcome coverage” line only when `has_syllabus`; include “retention” / “due reviews” only when SRS data exists.
- **Tools menu / Insights**: Already conditional in places; can be made consistent with the same flags.

### 4.3 Implementation

- **Engine**: Expose a small `get_plan_context()` or `get_feature_flags()` that returns `{ "has_syllabus": bool, "has_exam_date": bool, ... }` from current state.
- **App**: When building dashboard or plan UI, read these flags and show/hide or rephrase blocks. No new “feature toggles” table; just computed from data.

---

## 5. Implementation order

| Phase | Focus | Deliverables |
|-------|--------|--------------|
| **1** | Invalidation and cache policy | (1) Add `invalidate_plan()` (or equivalent) and call it from all paths that update competence, outcome_stats, SRS, exam date, syllabus, or module config. (2) Change cache policy to Option C: cache per day but invalidate on those events so plan recomputes when state changes. (3) Ensure engine `get_daily_plan()` uses current state (remove or invalidate engine-side daily_plan_cache when data change). |
| **2** | Single pipeline and visibility | (1) Document the list of inputs to the plan in code or a short doc. (2) Add `get_plan_context()` (or feature flags) and use it in the dashboard to show/hide outcome coverage and related blocks. |
| **3** | Optional strategies | (1) Add `plan_strategy` preference (or module config). (2) In `get_daily_plan()`, accept optional strategy and apply weights/filters (e.g. outcome_coverage, retention). (3) Expose strategy in Settings or Module Editor. |
| **4** | Refresh on visibility (optional) | When dashboard/plan widget gains focus or becomes visible, optionally call `invalidate_plan()` or a lightweight “if cache older than N minutes, refresh” so returning users see an up-to-date plan. |

---

## 6. Success criteria

- Completing a topic or recording a quiz/outcome event causes the daily plan (and coach pick) to reflect the new state after the next refresh (automatic via invalidation or on next open).
- Plan is computed from a single, explicit set of inputs; no stale engine cache that ignores recent writes.
- Optionally: user can select a plan strategy (e.g. outcome-coverage-first) and see the plan reorder accordingly.
- Optionally: dashboard and plan UI show or hide blocks (e.g. outcome coverage) based on whether the module has syllabus/data, so the app feels “dynamic” to the context.
