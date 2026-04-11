# Next 3 Implementation Tasks (March 2026)

This is a focused, low-risk roadmap for the next engineering steps.
Order is chosen by impact first, then implementation safety.

---

## 1) Add module path safety assertion + targeted legacy path test

**Why this first**
- Prevents silent cross-module or legacy-path drift in the core data layer.
- Fast to implement and high confidence from deterministic tests.

**Current gap**
- `RAG_AND_MODULE_IMPROVEMENTS.md` still marks `_assert_data_paths_under_module` as open.
- A dedicated test for legacy `acca_f9` path behavior is also marked open.

**Scope**
- Add a small helper in engine init path checks (debug-safe, deterministic):
  - Assert resolved `data.json` and `questions.json` are under the active module directory when that directory exists.
  - Preserve intended legacy behavior where explicitly required (do not break migration).
- Add a focused test that validates `acca_f9` resolves to module directory files when present.

**Acceptance criteria**
- Engine raises a clear error when active module paths escape expected module dir constraints.
- Legacy fallback still works only in intended conditions.
- New tests pass alongside existing path tests.

**Suggested tests**
- `tests/test_studyplan_app_paths.py`
- `tests/test_studyplan_engine.py` (new targeted path case)

---

## 2) Wire `PracticeLoopFSM` into GTK runtime transitions

**Why second**
- Largest user-facing behavior win among currently documented gaps.
- Improves consistency and debuggability of tutor/practice state transitions.

**Current gap**
- `DEVELOPER_DOC.md` notes `PracticeLoopFSM` is implemented/tested but not wired into GTK runtime flow.

**Scope**
- Route runtime step transitions through `PracticeLoopFSM` state transitions for the tutor/practice loop.
- Keep existing fallback behavior where needed to avoid regressions.
- Add transition logging hooks (lightweight) to simplify diagnosis when state changes fail.

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
