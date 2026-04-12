# Next 3 Implementation Tasks (March 2026)

This is a focused, low-risk roadmap for the next engineering steps.
Order is chosen by impact first, then implementation safety.

---

## 1) Add module path safety assertion + targeted legacy path test ✅

**Why this first**
- Prevents silent cross-module or legacy-path drift in the core data layer.
- Fast to implement and high confidence from deterministic tests.

**Status**
- Implemented in `studyplan_engine.py` with `_assert_data_paths_under_module(...)`.
- Covered by targeted engine tests, including legacy `acca_f9` module-directory preference when module-scoped files are present.

**Scope**
- Add a small helper in engine init path checks (debug-safe, deterministic):
  - Assert resolved `data.json` and `questions.json` are under the active module directory when that directory exists.
  - Preserve intended legacy behavior where explicitly required (do not break migration).
- Add a focused test that validates `acca_f9` resolves to module directory files when present.

**Result**
- Engine now raises a clear error when active module paths escape expected module dir constraints.
- Legacy fallback remains limited to intended `acca_f9` migration conditions.
- Targeted regression tests pass.

**Suggested tests**
- `tests/test_studyplan_app_paths.py`
- `tests/test_studyplan_engine.py` (new targeted path case)

---

## 2) Wire `PracticeLoopFSM` into GTK runtime transitions ✅

**Why second**
- Largest user-facing behavior win among currently documented gaps.
- Improves consistency and debuggability of tutor/practice state transitions.

**Status**
- Implemented in `studyplan/practice_loop_controller.py`, `studyplan/ui/gtk4/practice_session.py`, and `studyplan_app.py`.
- GTK/runtime practice flows now record item presentation, submission, hint, assessment, transfer, and session-end transitions through `PracticeLoopFSM` with existing `SocraticFSM` fallback retained.

**Result**
- Practice-loop lifecycle changes now use the table-driven FSM in both the GTK4 practice session and tutor workspace runtime.
- Session metadata persists the current FSM state for recreated runtime loop objects.
- Transition logging and integration coverage make state mismatches easier to diagnose.

**Acceptance criteria**
- Practice loop transitions are driven by the FSM table (not ad-hoc state branching).
- Existing practice-loop behavior remains stable in common flows.
- Tests cover at least one end-to-end transition chain in app/controller integration.

**Suggested tests**
- `studyplan/testing/test_practice_loop_fsm.py` (extend if needed)
- `studyplan/testing/integration/test_practice_loop_e2e.py`

---

## 3) Add global RAG cache cap with LRU eviction

**Why third**
- Best resilience/perf tradeoff among open RAG items.
- Addresses memory growth risk without changing model behavior quality.

**Current gap**
- `RAG_AND_MODULE_IMPROVEMENTS.md` marks global session LRU/hard cap as open.

**Scope**
- Introduce a global chunk-cache budget (item count and/or byte estimate).
- Evict least-recently-used entries when threshold is exceeded.
- Keep current per-doc caps and retrieval behavior unchanged.

**Acceptance criteria**
- Cache size stays bounded under repeated multi-PDF tutor/reconfig usage.
- No functional regression in retrieval path correctness.
- Metrics or debug counters expose evictions for observability.

**Suggested tests**
- Unit tests for eviction order and cap enforcement in RAG cache layer.
- Regression tests for tutor context retrieval with cache churn.

---

## Out of scope for this 3-task pass

- Post-retrieval near-duplicate chunk suppression.
- Canonical chapter extraction pass from RAG.
- Rich token/batch telemetry expansion.

These remain valuable, but are lower priority than correctness hardening and runtime FSM integration.
