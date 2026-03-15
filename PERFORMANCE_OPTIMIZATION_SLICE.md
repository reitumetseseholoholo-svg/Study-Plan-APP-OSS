# Next performance optimization slice

Focused, bounded set of optimizations to implement in one pass. Target: **startup and dashboard/recommendation responsiveness** without changing behaviour.

**Status**: Slices 1–3 **implemented**. Slice 1: engine total-question-count cache with invalidation in `load_questions`, `save_questions`, `add_question`, `_add_questions_with_stats`; test `test_get_total_question_count_cache_invalidated_after_add_question` in `tests/test_studyplan_engine.py`. Slices 2 and 3: app already uses `_perf_cache` for `readiness:details` and `recommendations:top5` (TTL 6 s) and `_invalidate_readiness_and_recommendations_cache()` on quiz/reset. Slice 4 (defer load_questions) remains optional.

---

## Current state (brief)

- **Startup**: `StudyPlanEngine.__init__` runs on main thread (load_data, load_questions, migrations, save_data). Window appears after engine is fully ready, so time-to-first-paint is dominated by engine init.
- **Dashboard**: Already debounced (120 ms), throttled (0.8 s), and rendered via `GLib.idle_add`. `_render_dashboard` clears children, builds cards, calls `_compute_exam_readiness_details()` (which calls `engine.get_mastery_summary()` and related). Perf is recorded via `PerformanceProfiler` when available.
- **Recommendations**: Debounced; `_render_recommendations` calls `engine.top_recommendations(5)`. No caching of result.
- **Question count**: `engine.get_total_question_count()` iterates all chapters and sums `len(QUESTIONS.get(ch, []))`. Used by autopilot snapshot, daily gap check, tutor logic—called frequently; result changes only when questions are added/removed/saved.
- **Caching**: `_perf_cache` (PerformanceCacheService) exists with TTL and LRU; used for coach pick snapshot and ad-hoc keys. Syllabus parse/import has its own disk-backed cache.

---

## Slice 1: Cache total question count (engine + invalidation) — DONE

**Goal**: Avoid repeated O(chapters) iteration when nothing changed.

**Changes**:
- **Engine**: Add `_cached_total_question_count: int | None` and `_cached_total_question_count_valid: bool`. In `get_total_question_count()`, return cache if valid; else compute, store, set valid True, return. Invalidate (set valid False) in: `load_questions()`, `save_questions()`, and any code path that mutates `self.QUESTIONS` (e.g. after import/add/remove).
- **Invalidation points**: `load_questions` (after merge), `save_questions` (after write), and any method that modifies `self.QUESTIONS` (search for `self.QUESTIONS[` assignments or `.append` on question lists).

**Risk**: Low. Invalidation must be complete or cache can be stale; unit test: change questions, assert count updates.

**Effort**: Small (1–2 hours).

---

## Slice 2: Short-TTL cache for readiness and mastery summary — DONE (already in app)

**Goal**: When dashboard/recommendations refresh multiple times in quick succession (e.g. after quiz close, timer, or multiple idle_adds), avoid recomputing readiness and mastery every time.

**Changes**:
- **App**: In `_compute_exam_readiness_details()`, check `_perf_cache.get("readiness:details")` with a short TTL (e.g. 5–8 seconds). On cache hit, return cached dict. On miss, compute as now, then `_perf_cache.set("readiness:details", result, ttl_seconds=5)` (or 8), return result.
- **Invalidation**: On actions that change readiness (e.g. after quiz completion, reset data, save_data that updates competence/quiz_results/outcome_stats), call `_perf_cache.delete("readiness:details")` or set a version key that changes. Safe option: TTL-only (no explicit invalidation) so after 5–8 s any refresh gets fresh data; or add invalidation in the 3–5 call sites that clearly change readiness.
- **Optional**: Cache `engine.get_mastery_summary()` in the same way under key `"mastery:summary"` (same TTL), and use it inside `_compute_exam_readiness_details` and anywhere else that only needs a recent snapshot. Reduces repeated iteration over `srs_data` when dashboard and other UI both ask for mastery.

**Risk**: Low. Worst case, user sees slightly stale readiness for up to TTL seconds after a quiz/reset. Mitigation: invalidate on quiz complete and reset.

**Effort**: Small–medium (1–2 hours including invalidation points).

---

## Slice 3: Cache top_recommendations(5) with short TTL — DONE (already in app)

**Goal**: Same as Slice 2 but for recommendations list; avoid repeated `engine.top_recommendations(5)` when nothing changed.

**Changes**:
- **App**: In `_render_recommendations` (or a small helper it calls), check `_perf_cache.get("recommendations:top5")` with TTL ~5–8 s. Hit: use cached list to build labels. Miss: call `self.engine.top_recommendations(5)`, cache result, then build labels.
- **Invalidation**: On competence change, study action, or save_data that affects recommendations. Optional: TTL-only for simplicity.

**Risk**: Low. Slightly stale recommendations for a few seconds.

**Effort**: Small (~30 min).

---

## Slice 4 (stretch): Defer load_questions to first idle after paint

**Goal**: Improve time-to-first-paint by not loading questions (and merging SRS) inside `StudyPlanEngine.__init__`. Window can show with “Loading questions…” or placeholder; then questions load and UI refreshes.

**Changes**:
- **Engine**: Split init so that `load_data()` still runs in `__init__` (needed for competence, study_days, etc.), but `load_questions()` is **not** called in `__init__`. Add a method e.g. `ensure_questions_loaded()` that idempotently calls `load_questions()` if not yet loaded (guard with `_questions_loaded` flag). Call `ensure_questions_loaded()` from app after first paint (e.g. in `_run_initial_refresh` via idle_add, or at start of first dashboard render). Ensure any code that assumes QUESTIONS are populated either runs after ensure_questions_loaded or tolerates empty QUESTIONS until then.
- **App**: After window present, schedule `engine.ensure_questions_loaded()` on a thread (or on idle if load_questions is fast enough), then `GLib.idle_add` refresh of dashboard/recommendations. Optionally show a subtle “Loading…” in the recommendations/dashboard area until questions are loaded.

**Risk**: Medium. Many code paths assume QUESTIONS and srs_data are populated; need to audit and possibly guard or defer tutor/quiz until questions loaded. F7 with 0 questions is already handled; the risk is ordering (e.g. get_total_question_count before load).

**Effort**: Medium (half day). Recommend doing Slices 1–3 first, then Slice 4 if startup is still the main complaint.

---

## Recommended order

| Order | Slice | Rationale |
|-------|--------|-----------|
| 1 | **Slice 1** (total question count cache) | Simple, clear invalidation, high call rate; unblocks cleaner autopilot/snapshot logic. |
| 2 | **Slice 2** (readiness/mastery cache) | Dashboard and multiple refresh paths call _compute_exam_readiness_details and get_mastery_summary; 5–8 s TTL gives quick wins. |
| 3 | **Slice 3** (top_recommendations cache) | Same pattern as Slice 2; small change. |
| 4 | **Slice 4** (defer load_questions) | Optional; do after 1–3 if startup time-to-paint is still the main issue. |

---

## Success criteria

- **Slice 1**: `get_total_question_count()` returns correct value; after load_questions/save_questions or question add/remove, next call returns updated count; no extra iteration when cache valid.
- **Slice 2**: With 5–8 s TTL, repeated dashboard/recommendation refreshes within TTL reuse cached readiness; after quiz complete or reset, readiness updates within TTL or immediately if invalidation added.
- **Slice 3**: Repeated recommendation refreshes within TTL reuse cached list; behaviour otherwise unchanged.
- **Slice 4** (if done): Window paints before questions finish loading; after ensure_questions_loaded, dashboard and quiz/tutor see full question set; no regressions when QUESTIONS load slowly or fail.

---

## Non-goals for this slice

- RAG or reconfig performance (already off main thread; reconfig uses pre-chunked retrieval).
- Reducing size of data.json or questions.json (separate “data efficiency” slice).
- Profiler/telemetry changes (existing profiler and dashboard perf recording stay as-is).
- Changing debounce/throttle values (120 ms, 0.8 s) unless measurements show need.

---

## Implementation notes

- **Slice 1**: In engine, add two attributes in `__init__` (e.g. after QUESTIONS init): `self._cached_total_question_count = None` and `self._cached_total_question_count_valid = False`. In `get_total_question_count()`, if `self._cached_total_question_count_valid` and `self._cached_total_question_count is not None`, return it; else compute, set both, return. In `load_questions` and `save_questions`, set `self._cached_total_question_count_valid = False`. Search for other mutations of `self.QUESTIONS` (e.g. in import or add-question flows) and invalidate there too.
- **Slice 2**: Use existing `_perf_cache`; key `"readiness:details"`. If cache has a TTL API, set 5–8 s. Invalidation: in the handler that runs after quiz completion (e.g. where you call update_dashboard/update_recommendations after quiz), add `getattr(self, "_perf_cache", None) and self._perf_cache.delete("readiness:details")` (or equivalent). Same for reset_data path if app calls one.
- **Slice 3**: Key `"recommendations:top5"`; same TTL; call from _render_recommendations.
