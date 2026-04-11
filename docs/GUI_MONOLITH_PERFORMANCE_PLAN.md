# GUI Monolith Performance Plan

This plan is scoped to the repo-root GUI monolith in `studyplan_app.py`.
It does **not** try to optimize the smaller backend packages first.
The goal is to make the app feel faster by reducing repeated UI work,
sharing derived state, and avoiding refresh storms.

## Summary

The current app already has some good building blocks:

- `UIRefreshScheduler` coalesces some refresh requests.
- `PerformanceCacheService` stores short-lived derived state.
- `PerformanceProfiler` records render timing.
- Chart widgets already use signature-based caching in the dashboard.

The biggest remaining cost is structural:

- dashboard rebuilds still re-derive a lot of state
- workbench pages refresh eagerly
- several code paths trigger the same refreshes back-to-back
- engine-derived values are recomputed in multiple panels

The best performance work is therefore not a backend rewrite.
It is a GUI orchestration change.

## What Is Hot

High-cost GUI paths currently include:

- dashboard rebuilds in `studyplan_app.py`
- study room refreshes
- coach / insights / settings page refreshes
- readiness and recommendation recomputation
- repeated `engine.get_questions(...)` and `engine.get_daily_plan(...)` calls
- chart generation and chart input assembly

Relevant hotspots:

- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L41393)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L34504)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L32345)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L32408)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L33545)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L44180)

## Non-Goals

- Do not rework the smaller backend packages first.
- Do not change tutor model selection logic as the main performance fix.
- Do not rewrite the entire UI into a new framework.
- Do not remove the existing debouncing and cache layers.

## Phase 1: Build One Shared UI Snapshot

Create a short-lived `UIStateSnapshot` concept in `studyplan_app.py`.

The snapshot should hold only derived values that multiple panels reuse:

- exam readiness details
- daily plan summary
- coach pick summary
- recommendation list
- question counts
- undercovered capability summary
- semantic status summary

The important rule is that the GUI should read that snapshot once and fan
out to multiple panels, instead of asking the engine for the same data in
several refresh paths.

Implementation targets:

- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py)
- [studyplan/components/performance/caching.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan/components/performance/caching.py)

Acceptance criteria:

- dashboard, study room, coach, and insights can reuse the same derived data
- snapshot invalidation is explicit and small
- repeated refreshes during one interaction no longer re-query the engine

## Phase 2: Split Full Rebuilds Into Dirty Sections

The dashboard is still the biggest redraw cost.
Today it clears and rebuilds a large tree in one pass.

Refactor it so the app can update only the sections that changed:

- readiness summary
- coach briefing
- progress charts
- recommendation cards
- static informational cards

The aim is not to make the dashboard fully reactive.
The aim is to stop rebuilding the entire page when only one input changed.

Implementation targets:

- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L41393)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L42800)

Acceptance criteria:

- changing one metric updates only its section
- chart widgets remain signature-cached
- dashboard latency drops without changing visible behavior

## Phase 3: Lazy-Load Hidden Pages

The app currently refreshes all workbench pages during startup and several
state changes. That is convenient, but it burns time on views the user may
never open in that session.

Change the model so that:

- `dashboard` and `tutor` stay eager
- `coach`, `insights`, and `settings` refresh on first open
- hidden pages only refresh when a dirty flag says they need it

Implementation targets:

- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L32345)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L7674)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L7816)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L8009)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L8183)

Acceptance criteria:

- startup does less work before first paint
- opening a hidden page still renders correctly
- page refreshes remain safe after state changes

## Phase 4: Coalesce Refresh Storms

Many actions trigger `update_daily_plan()`, `update_study_room_card()`, and
`update_dashboard()` in sequence.

The plan should consolidate these into one UI refresh pass whenever possible.

Example pattern:

- mark data dirty
- schedule one refresh
- let the refresh fan out to all dependent panels

This is where `UIRefreshScheduler` should do more of the work.

Implementation targets:

- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L15553)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L34504)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L41395)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L44172)

Acceptance criteria:

- a single state mutation does not trigger three separate rebuilds
- refresh scheduling is still bounded and safe on GTK main thread
- no UI state is lost when updates collapse together

## Phase 5: Cache Derived Aggregates, Not Just Final Text

The app already caches some derived data.
The next gain is to cache the expensive aggregates that feed multiple panels.

Good cache candidates:

- readiness details
- recommendations list
- coach pick snapshot
- daily plan summary
- question counts
- semantic status summary
- undercovered capability summary

Keep the TTLs short where state changes frequently.
Invalidate explicitly after meaningful edits.

Implementation targets:

- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L33545)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L33157)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L44210)
- [studyplan/components/performance/caching.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan/components/performance/caching.py#L26)

Acceptance criteria:

- repeated reads within one UI burst reuse cached summaries
- cached values expire or invalidate safely
- cache memory remains bounded

## Phase 6: Add Profiling For The Right Operations

The profiler already exists.
Use it on the expensive GUI operations that matter:

- dashboard render
- study room update
- recommendations render
- daily plan render
- coach refresh
- startup refresh pass

This gives a baseline before and after each optimization step.

Implementation targets:

- [studyplan/components/performance/profiler.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan/components/performance/profiler.py)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L15635)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L34541)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L41437)
- [studyplan_app.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan_app.py#L44272)

Acceptance criteria:

- dashboard latency is measurable before and after changes
- slow refreshes are attributable to a specific section
- perf regression is visible in logs or stats

## Phase 7: Add Regression Tests

Tests should prove the GUI remains correct after performance work.

Recommended coverage:

- dashboard refresh coalescing
- study room refresh coalescing
- cached readiness invalidation
- cached recommendations invalidation
- hidden page lazy-load behavior
- startup refresh order

Useful test areas:

- [tests/test_studyplan_app_ollama.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/tests/test_studyplan_app_ollama.py)
- [studyplan/testing/test_performance_cache.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan/testing/test_performance_cache.py)
- [studyplan/testing/test_llama_runtime.py](/home/pyprog/APP/ACCA-Study-Plan-APP-OSS-/studyplan/testing/test_llama_runtime.py)

Suggested test names:

- `test_dashboard_refresh_coalesces_multiple_requests`
- `test_study_room_refresh_coalesces_multiple_requests`
- `test_readiness_snapshot_is_invalidated_after_state_change`
- `test_recommendations_snapshot_is_invalidated_after_state_change`
- `test_hidden_workbench_page_is_not_refreshed_until_opened`

## Implementation Order

1. Shared UI snapshot
2. Dashboard section diffing
3. Refresh coalescing
4. Lazy-load hidden pages
5. Aggregate caching
6. Profiling hooks
7. Tests

## Expected Outcome

If this plan is implemented well, the app should:

- feel noticeably faster on startup and tab changes
- stop repeating the same expensive reads across panels
- keep dashboard latency under control as the app grows
- preserve current behavior while improving responsiveness

The key principle is simple:

> reduce repeated work in the GUI monolith before touching deeper layers

