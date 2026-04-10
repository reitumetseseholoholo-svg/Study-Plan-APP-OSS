# Developer Documentation — Study Assistant

This document covers the application architecture, key subsystems, internal design decisions, and operational guides for developers.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module System](#module-system)
3. [SRS Scheduling (FSRS-4.5 and SM-2)](#srs-scheduling-fsrs-45-and-sm-2)
4. [Coach and Recommendation Engine](#coach-and-recommendation-engine)
5. [AI Cockpit (Autopilot)](#ai-cockpit-autopilot)
6. [AI Tutor and RAG Pipeline](#ai-tutor-and-rag-pipeline)
7. [Prompt Engineering Design (3Es + Fail-Safe)](#prompt-engineering-design-3es--fail-safe)
8. [Bayesian Cognitive Runtime](#bayesian-cognitive-runtime)
9. [Socratic FSM](#socratic-fsm)
10. [Semantic Routing and Outcome Linking](#semantic-routing-and-outcome-linking)
11. [Syllabus Ingestion Strategy](#syllabus-ingestion-strategy)
12. [ML Training Pipeline](#ml-training-pipeline)
13. [Persistence and Snapshot Recovery](#persistence-and-snapshot-recovery)
14. [Performance Caching](#performance-caching)
15. [GTK4 Application Architecture](#gtk4-application-architecture)
16. [Testing Architecture](#testing-architecture)
17. [CI Workflow](#ci-workflow)
18. [Configuration Reference](#configuration-reference)
19. [Deployment](#deployment)

---

## Architecture Overview

Study Assistant is a **single-process GTK4 desktop application**. There is no backend server, no external database, and no network dependency at runtime (local LLM and all data files are local).

```
┌─────────────────────────────────────────────────────────┐
│                      studyplan_app.py                   │
│           GTK4 UI  (StudyPlanGUI / StudyApp)            │
│  ┌─────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │  Dashboard  │  │  Quiz / Timer │  │  AI Tutor WS │  │
│  └──────┬──────┘  └───────┬───────┘  └──────┬───────┘  │
└─────────┼─────────────────┼─────────────────┼──────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│                   studyplan_engine.py                   │
│  StudyPlanEngine — data model, SRS, scheduling, ML,     │
│  syllabus parsing, persistence, semantic routing        │
└────────────────────────┬────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    studyplan/        studyplan/     studyplan/
     fsrs.py          ai/ (LLM)    cognitive_state.py
     contracts.py     services.py  mastery_kernel.py
     config.py        ...          coach_fsm.py
```

### Files and their roles

| File | Role |
|---|---|
| `studyplan_app.py` | GTK4 main window. All UI construction, event handlers, Pomodoro, quiz flow, AI cockpit, preferences. ~51,000 lines. |
| `studyplan_engine.py` | Data model, SRS (FSRS-4.5/SM-2), daily plan, coach urgency scoring, ML inference, syllabus parsing, semantic routing, persistence. ~13,500 lines. |
| `studyplan_ai_tutor.py` | AI tutor session management: prompt assembly, RAG retrieval, Ollama/gateway calls, streaming, response sanitization. |
| `studyplan_app_kpi_routing.py` | KPI thresholds and smoke/soak test routing helpers. GTK-independent. |
| `studyplan_app_path_utils.py` | Path helpers extracted for unit-testability without GTK. |
| `studyplan_ui_runtime.py` | UI state at startup (module title, exam date, etc.). GTK-independent. |
| `studyplan_file_safety.py` | `enforce_file_size_limit`, `secure_path_permissions`. |
| `studyplan/config.py` | `Config` class — single source of truth for all runtime configuration. All settings are environment-variable-driven with typed defaults. |
| `studyplan/contracts.py` | Typed dataclass API contracts shared between engine, tutor, and services. |
| `studyplan/services.py` | Python Protocol interfaces (`TutorService`, `CoachService`, `RagService`, `AutopilotService`, etc.). |

### Key design invariants

1. **`studyplan/` is GTK-free**. Any module under `studyplan/` must be importable without `gi`/GTK4. This keeps the unit-test surface large.
2. **GTK-independent helpers** for things extracted from `studyplan_app.py` go into `studyplan_app_path_utils.py`, `studyplan_app_kpi_routing.py`, or `studyplan_ui_runtime.py` so they can be unit-tested without a display.
3. **Atomic writes** for all JSON persistence (`_atomic_write_json`): write to a temp file then `os.replace`.
4. **No secrets in code** — all API keys come from environment variables or the preferences JSON.

---

## Module System

A **module** is a self-contained study subject (e.g. ACCA F9 / Financial Management). Each module has:

- `title` — display name
- `chapters` — ordered list of topic names
- `chapter_flow` — directed prerequisite graph
- `importance_weights` — integer weights for urgency scoring
- `target_total_hours` — total study hours target
- `questions` — optional built-in question bank
- `syllabus_structure` — learning outcomes per chapter (from PDF import or manual entry)
- `capabilities` — exam capability codes (e.g. `"A": "Financial management function"`)
- `syllabus_meta` — source PDF metadata, parse confidence, effective window

### Module loading order

`StudyPlanEngine._load_module_config(module_id)` tries candidates in order:
1. `modules/<id>.json` (repo built-in)
2. `~/.config/studyplan/modules/<id>.json` (user-installed)

The first valid dict wins. The loaded path is available as `engine._last_loaded_module_config_path`.

### Module validation

`engine.validate_module_config(config)` returns a list of warning strings. The app surfaces these in the module editor before saving. The `module_schema.json` in the repo root is used by the editor for field-level validation.

### Per-module data isolation

All user progress, SRS data, and questions are stored under `~/.config/studyplan/<module_id>/` so switching modules never mixes data.

---

## SRS Scheduling (FSRS-4.5 and SM-2)

### Default: FSRS-4.5

`studyplan/fsrs.py` implements the Free Spaced Repetition Scheduler (FSRS v4.5). It models per-card **memory stability** (S) and **difficulty** (D) using 17 community-tuned weight parameters.

**Key classes:**

- `FSRSCard` — per-card state: `stability`, `difficulty`, `reps`, `lapses`, `last_review`, `due`
- `FSRSScheduler` — `review(card, rating)` returns an updated `FSRSCard`; `is_due(card)` checks review eligibility
- `fsrs_update_srs_item(srs_item, is_correct)` — engine integration helper; mutates and returns the SRS dict, also writing legacy SM-2 keys (`interval`, `efactor`) for backward compatibility

**Ratings used by the engine:**

| Outcome | Rating |
|---|---|
| Correct | 3 (Good) |
| Incorrect | 1 (Again) |
| Fine-grained (optional) | Caller sets `srs_item["fsrs_rating"] = 1..4` before calling |

**Desired retention optimizer** (`optimize_desired_retention_from_history`): sweeps candidate retention targets against the user's actual recall history to find the best-fit value. Exposed in the engine as a diagnostic tool.

### SM-2 fallback

Set `STUDYPLAN_SRS_ALGORITHM=sm2` (or `legacy`) to use the original SM-2 scheduler. The engine delegates via `_update_srs_fsrs` / `_update_srs_sm2` split at `engine.update_srs()`.

FSRS and SM-2 keys coexist in the SRS dict so data files remain forward-compatible. When FSRS is active, `is_overdue`, `get_due_today_by_chapter`, `get_retention_probability`, and `select_due_review_questions` prefer FSRS fields (`fsrs_due`, `fsrs_stability`) when available.

---

## Coach and Recommendation Engine

The coach computes **urgency scores** for each chapter and surfaces them as recommendations.

### `top_recommendations(n)` — urgency scoring formula

```
urgency = (100 - competence)
        × syllabus_depth_boost
        × syllabus_pressure_boost
        + (overdue_srs_count × 5)
        + (ml_recall_risk × 30 × exam_weight)
        + semantic_drift_bonus          # up to 24 pts + 14 for severe
        × exam_proximity_multiplier    # ×2 if ≤7 days, ×1.5 if ≤14
```

`exam_weight` is 2.0 (≤7 days), 1.6 (≤21 days), 1.3 (≤45 days), else 1.0.

### `get_daily_plan(n)` — multi-factor daily topic selection

Daily plan uses additional signals beyond urgency:

- **Neighbor bonus** — if the preceding chapter is ≥60% competent and current is <80%, boost by 15 pts
- **Flow bonus** — if a prerequisite is ≥70% competent and dependent is <80%, boost by 18 pts
- **Prerequisite boost** — if a downstream chapter is weak or high-risk, reinforce the prerequisite
- **ML risk** — `get_chapter_recall_risk()` contributes if a model is available
- **Retention mode** — ≤21 days to exam tightens stickiness thresholds

The plan is **cached for the day** (`daily_plan_cache` + `daily_plan_cache_date`) to prevent flip-flopping mid-session.

### Exam-readiness index

The exam readiness index shown on the dashboard is computed from:
- Weighted average competence across chapters (by `importance_weights`)
- SRS retrieval quota (% of due cards answered in the current review period)
- Pace status (hours studied vs. pace required to reach target hours by exam date)

### Coach Pick

Coach Pick is the single top recommendation for the day. It is pinned once selected (sticky) unless a major data import triggers a refresh. The audit trail is written to `~/.config/studyplan/coach_debug.log`.

---

## AI Cockpit (Autopilot)

The autopilot is a **second AI system** separate from the tutor chat. It operates on JSON action plans, not conversational text.

### Architecture

```
Autopilot tick (GLib timeout, every N seconds)
  └── _run_global_ai_tutor_autopilot_tick()
        ├── Check rate limits (_consume_global_ai_tutor_action_budget)
        ├── Build action prompt (JSON plan request)
        ├── Send to LLM (autopilot purpose)
        ├── Parse JSON action plan
        ├── Validate action is in AI_TUTOR_SAFE_AUTONOMOUS_ACTIONS (cockpit mode)
        └── Execute via _dispatch_ai_tutor_action()
              └── _record_ai_tutor_action_budget_use()
```

### Autonomy modes

| Mode | Behaviour |
|---|---|
| `cockpit` (default) | Execute safe actions immediately |
| `assist` | Execute safe actions, notify after |
| `suggest` | Queue as suggestion, wait for user approval |

Defined in `studyplan_app.py:AI_TUTOR_AUTONOMY_MODES`.

### Safe action set

`AI_TUTOR_SAFE_AUTONOMOUS_ACTIONS` (18 actions): `focus_start`, `timer_pause`, `timer_resume`, `timer_stop`, `tutor_open`, `coach_open`, `coach_next`, `quick_quiz_start`, `drill_start`, `weak_drill_start`, `leitner_drill_start`, `error_drill_start`, `leech_drill_start`, `interleave_start`, `review_start`

Actions not in this set (`quiz_start`, `gap_drill_generate`, `section_c_start`) always require user confirmation regardless of mode.

### Rate limiting

```python
AI_TUTOR_AUTOPILOT_MAX_ACTIONS_PER_WINDOW = 6
AI_TUTOR_AUTOPILOT_ACTION_WINDOW_SECONDS = 600     # 10 minutes
AI_TUTOR_AUTOPILOT_QUIET_AFTER_SUCCESS_SECONDS = 90
AI_TUTOR_AUTOPILOT_DECISION_REFRESH_SECONDS = 120
```

`_consume_global_ai_tutor_action_budget()` enforces these limits. `_record_ai_tutor_action_budget_use()` records each execution.

### Dashboard display

`_refresh_dashboard_cockpit_status()` updates the AI Cockpit card on the dashboard with:
- Current mode and autopilot status (active/paused/off)
- Last executed action (from `_ai_tutor_recent_action_log`)
- Next pending action (from `_ai_tutor_pending_suggestion`)

---

## AI Tutor and RAG Pipeline

The tutor system (`studyplan_ai_tutor.py`) manages the full request lifecycle:

```
User message
  └── assemble_tutor_prompt()
        ├── Tutor memory (last 14 activity entries)
        ├── Working memory (active chapter, Socratic state)
        ├── Conversation history (adaptive truncation for long histories)
        ├── RAG snippets (syllabus + notes PDF chunks)
        └── Pedagogical mode + coach identity lines

  └── LLM call (Ollama / llama.cpp / gateway)
        ├── Purpose classification (tutor, coach, gap_gen, section_c, ...)
        ├── Model routing (per-purpose JSON config)
        ├── Streaming with stall detection (AI_TUTOR_STREAM_STALL_MS = 900ms)
        └── Response sanitization (remove think tags, fix spacing)
```

### Long-history handling

When conversation turns exceed `AI_TUTOR_LONG_HISTORY_THRESHOLD = 24`:
- Keep only the most recent `AI_TUTOR_LONG_HISTORY_RECENT_LIMIT = 10` turns verbatim
- Summarise older turns (max `AI_TUTOR_LONG_HISTORY_SUMMARY_MAX_CHARS = 1100` chars) using `adaptive_tutor_recent_cap`

### RAG chunking

Default parameters: `RAG_CHUNK_CHARS_DEFAULT = 900`, `RAG_OVERLAP_CHARS_DEFAULT = 120`, `RAG_MAX_CHUNKS_DEFAULT = 1200`.

When `sentence-transformers` is available, retrieval uses semantic similarity with the `all-MiniLM-L6-v2` model and optional cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`). Otherwise it falls back to BM25-style lexical retrieval.

### Purpose classification

`studyplan/ai/tutor_llm_purpose.py` classifies each LLM request into a purpose:
`tutor`, `coach`, `deep_reason`, `autopilot`, `gap_generation`, `section_c_generation`, `section_c_evaluation`, `section_c_judgment`, `section_c_loop_diff`, `general`

Purpose drives model routing (see `studyplan/ai/model_routing.py`), telemetry, and context budget policy.

### LLM backend priority

1. **LLM Gateway** (if `LLM_GATEWAY_ENABLED=1`) — OpenAI-compatible endpoint (OpenRouter, OpenAI, Anthropic, Gemini, etc.)
2. **Managed llama.cpp server** (if `LLAMA_CPP_MANAGED_SERVER=1`) — starts/stops `llama-server` automatically
3. **Ollama** (auto-discovered at `http://127.0.0.1:11434`)
4. **Direct GGUF** via llama.cpp Python runtime
5. **Brave Search AI** (if `BRAVE_SEARCH_AI_ENABLED=1`)
6. **Deterministic fallback** (`studyplan/ai/recovery.py`) — returns a structured error response; never raises

---

## Prompt Engineering Design (3Es + Fail-Safe)

Source: `studyplan/ai/prompt_design.py`

All AI prompts follow the **3Es** principle:
- **Economy** — shared phrase constants (no duplication); one change updates every prompt
- **Efficiency** — schema-first, rules-then-payload; structured JSON output enforced at the schema level
- **Effectiveness** — layered prompts with base identity + variable context; Socratic constraints injected by FSM state

**Fail-safe**: every generation path has a `RETRY_SUFFIX_*` for a relaxed second attempt, and `recovery.py` provides a deterministic fallback that never raises.

### Coach identity lines

`TUTOR_COACH_IDENTITY_LINES` (in `studyplan/ai/tutor_prompt_layers.py`) defines the base tutor identity:
- Exam-readiness-per-minute maximisation
- Priority order: SRS pressure → weak-topic repair → retrieval practice → formula accuracy → exam clarity
- Formatting rules (Markdown tables for financials, no LaTeX, no study-guide references)
- Elaborative encoding and continuity with working memory

### Pedagogical mode

`derive_pedagogical_mode(history, topic, mastery)` returns one of: `explain`, `practice`, `exam_technique`, `revision`, `freeform`. Injected into the prompt as metadata for telemetry and routing.

### Golden prompt fixture

`tests/fixtures/golden_tutor_prompts.json` captures deterministic prompt outputs for regression testing. If a code change alters prompt structure, regenerate this fixture and explain the change in the PR.

---

## Bayesian Cognitive Runtime

`studyplan/mastery_kernel.py` — `MasteryKernel`

Maintains a **shadow-mode** Beta-distribution posterior per chapter. This is separate from the SRS scheduler and does not affect review intervals; it improves tutoring policy decisions.

### Update rule

On each quiz attempt:
```
attention = 1 / (1 + (latency_ms/10000)²)   # high attention for fast answers
hint_discount = 0.7^hints_used

if correct:
    alpha += max(0.1, attention × (1 if no hints else 0.5))
else:
    beta += 1.0
    update_confusion_links(chapter)  # fast wrong → add prerequisite to confusion map
```

`struggle_mode = fast_error OR hint_dependency OR error_streak`

### Cognitive state

`studyplan/cognitive_state.py` — `CognitiveState`:
- `posteriors: dict[chapter, CompetencyPosterior]` — Beta posteriors (α, β)
- `working_memory: WorkingMemoryBuffer` — active chapter, question, Socratic state, context chunks, struggle flags
- `confusion_links: dict[chapter, set[str]]` — prerequisite chapters that may explain errors
- `struggle_mode: bool` — overall struggle signal

`CognitiveState` is persisted separately from `data.json` under a `cognitive_state` key in the data file, with schema-version migration support.

---

## Socratic FSM

`studyplan/coach_fsm.py` — `SocraticFSM`

A 5-state FSM that constrains what the AI tutor can do based on the learner's current mastery and behaviour:

```
DIAGNOSE ──(correct)──► SCAFFOLD ──(mastery≥0.85)──► CHALLENGE
   │                        │
   │(quiz start/error)      │(mastery 0.65-0.85)
   ▼                        ▼
PRODUCTIVE_STRUGGLE      CONSOLIDATE
```

| State | Permission | Prompt constraint |
|---|---|---|
| DIAGNOSE | `socratic_only` | Ask one clarifying question first |
| PRODUCTIVE_STRUGGLE | `socratic_only` | Guide only; never give the answer |
| SCAFFOLD | `hint_ok` | Partial hint, then ask what comes next |
| CONSOLIDATE | `explain_ok` | Confirm understanding before moving on |
| CHALLENGE | `explain_ok` | Present harder variants or edge cases |

The FSM transitions on events: `QUIZ_START`, `QUIZ_END`, `ERROR`, `INCORRECT_ATTEMPT`, `CORRECT_ATTEMPT`, `PARTIAL_CORRECT`, `TUTOR_REQUEST`. It reads `CognitiveState.posteriors` for mastery and `struggle_mode` for triage.

---

## Semantic Routing and Outcome Linking

### Semantic model

When `sentence-transformers` is installed, the engine maintains shared embedding models (class-level singletons protected by `_SEMANTIC_SHARED_MODEL_LOCK`):
- Encoder: `all-MiniLM-L6-v2`
- Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`

Embeddings are cached (LRU, max 2048 entries) and warmed up at startup (up to 6 chapters, budget 3000ms).

### Circuit breaker

`SEMANTIC_ROUTE_FAIL_STREAK_LIMIT = 3` and `SEMANTIC_ROUTE_CIRCUIT_SECONDS = 180` implement a circuit breaker: if semantic routing fails 3 times consecutively, it opens for 3 minutes and falls back to lexical matching.

### Canonical concept graph

`engine.build_canonical_concept_graph(force=False)` builds a stable graph of concepts and their relationships from syllabus outcomes. The graph is versioned (`CONCEPT_GRAPH_SCHEMA_VERSION = 1`) and stored in `data.json`.

### Outcome cluster graph

Outcome clusters group related learning outcomes by semantic similarity (`SEMANTIC_CLUSTER_SIM_THRESHOLD = 0.72`). The outcome cluster graph supports outcome-gap quiz routing and the Insights outcome coverage view.

### Semantic drift KPI

When `competence[chapter] - outcome_mastery[chapter] > SEMANTIC_DRIFT_COMPETENCE_GAP_PCT (20%)` and the chapter has `> SEMANTIC_DRIFT_MIN_OUTCOMES (5)` outcomes and the last quiz was `> SEMANTIC_DRIFT_QUIZ_LAG_DAYS (14)` days ago, a drift alert is raised. This feeds into the urgency score (+24 pts, +14 for severe) and is shown in the Insights tab.

---

## Syllabus Ingestion Strategy

For stable setups, treat versioned module JSON as the **source of truth** and use PDF import + RAG only to review and update when a new syllabus is published.

### Recommended workflow

1. **First setup**: `Module → Import Syllabus PDF…` with RAG improvement → review draft → save as `modules/<id>.json`
2. **Each exam cycle**: Re-import the new PDF and diff the draft against the committed JSON; merge changes manually
3. **Auto-improvement**: For CI/unattended environments, set `STUDYPLAN_AUTO_IMPROVE_SYLLABUS_AI=1` to auto-run RAG when confidence < 75%
4. **Outcome linking**: After any syllabus update, run `Module → Refresh syllabus intelligence & link outcomes` to keep outcome-question links fresh

### Parser internals

`engine.parse_syllabus_pdf_text(text)` is a heuristic multi-pass parser:
1. Check for FR-syllabus format (`studyplan/syllabus_fr.py`)
2. Parse capability headings (ACCA A–H style and OCR variants)
3. Parse learning outcomes under each capability
4. Fallback: scan for letter-prefix headings only

`engine.parse_syllabus_with_ai(text, chapters)` uses an LLM with chunked retrieval:
- Chunk PDF into 850-character segments with overlap
- Build per-chapter queries and retrieve relevant chunks
- Decode JSON response with retry on parse failure (`RETRY_SUFFIX_*`)
- Merge AI outcomes with heuristic parse results

### Caching

Both the parse result and the AI-augmented result are cached:
- In-memory: `SYLLABUS_PARSE_CACHE_MAX = 12` entries (LRU by PDF hash)
- Disk: `SYLLABUS_IMPORT_CACHE_MAX = 12`, max 24 on disk, max age 30 days, schema version 2

Cache stats: `engine.get_syllabus_import_cache_stats()` | Clear: `engine.clear_syllabus_import_cache()`

---

## ML Training Pipeline

Three sklearn models improve coach quality when trained on the user's quiz history.

### Recall model (LogisticRegression, 5 features)

Features per SRS card:
1. Days since last review
2. Current interval
3. Efactor (SM-2) or mapped from FSRS difficulty
4. Correct-rate over last N attempts
5. Chapter importance weight

Training (`tools/train_recall_model_sklearn.py`):
- Requires ≥ 100 answered questions and `ML_MIN_SAMPLES = 100` positive samples
- Uses recency-weighted sample importance
- Class-balancing via `class_weight="balanced"`
- Grid-searches `C` candidates
- Optional probability calibration (Platt / isotonic)
- Promotion gates: Brier score ≤ `RECALL_MODEL_MAX_ECE`, AUC ≥ `RECALL_MODEL_MIN_AUC = 0.58`, improvement over existing model

### Difficulty and interval models

Trained similarly. The interval model (`tools/train_interval_model_sklearn.py`) predicts the optimal next review interval given stability, difficulty, and days since review.

### Runtime safety

- Models are loaded lazily; load failures fall back gracefully (no crash)
- The sklearn recall model is rejected at load time if the feature count metadata mismatches the engine's `RECALL_FEATURE_COUNT = 5`
- Models are stored at `~/.config/studyplan/<model>.pkl`

---

## Persistence and Snapshot Recovery

### Data files

```
~/.config/studyplan/<module_id>/data.json      # progress, SRS, competence, cognitive state
~/.config/studyplan/<module_id>/questions.json # AI-generated questions
```

### Atomic write

`engine._atomic_write_json(path, payload)` writes to `<path>.tmp` then calls `os.replace()` to guarantee atomicity. File size is checked against `MAX_DATA_FILE_BYTES = 64 MB` before write.

### Rolling backups

`engine._write_rolling_backup(path, payload)` keeps the last `BACKUP_RETENTION = 20` snapshots as `.bak` files in `~/.config/studyplan/<module_id>/backups/`. Backups are named with a timestamp + random suffix to prevent collisions.

### Auto-recovery

`engine._recover_data_from_latest_snapshot(load_error)`: if `load_data()` raises an exception, the engine automatically tries the most recent valid backup. If that also fails, it starts with an empty state (no crash).

### Snapshot import/export

`engine.import_data_snapshot(file_path)` — import a `.bak` or `.json` snapshot with size limit and JSON validation.
`engine.list_backup_snapshots(limit=50)` — list available backups with timestamps and sizes.

### Schema migration

`studyplan/testing/test_schema_migration.py` tests forward migration of data files. The `COGNITIVE_STATE_SCHEMA_VERSION` constant governs the cognitive state sub-schema.

---

## Performance Caching

`studyplan/performance_monitor.py` and `studyplan/performance_integration.py` implement an LRU TTL cache for expensive computations.

### Cached categories

| Key | Default TTL |
|---|---|
| `cognitive_state` | 300s |
| `hint_strategy` | 600s |
| `ui_render` | 30s |
| `pdf_text` | 3600s |
| `rag_doc` | 1800s |
| `ollama` | 120s |
| `coach_pick` | 300s |

### Configuration

```
STUDYPLAN_PERFORMANCE_CACHE_ENABLED=1            # on by default
STUDYPLAN_PERFORMANCE_CACHE_MAX_SIZE=<n>         # default: host-dependent
STUDYPLAN_PERFORMANCE_CACHE_TTL_COACH_PICK=300   # per-category TTL overrides
```

View stats: **Tools → More → View Performance Stats** | Clear: **Tools → More → Clear Performance Cache**

---

## GTK4 Application Architecture

`StudyPlanGUI` (a `Gtk.ApplicationWindow`) is constructed by `StudyApp.do_activate()`. The class is large by necessity — GTK4 requires widget construction and callback wiring in the same scope.

### Startup sequence

1. `_smoke_bootstrap()` — configure process env vars (loky, joblib) before any imports
2. `StudyApp.do_activate()` → `StudyPlanGUI.__init__()` → `StudyPlanEngine.__init__()`
3. `engine.load_data()` — load or auto-recover data
4. `_build_main_window()` → `_build_left_panel()`, `_build_dashboard()`, `_build_tutor_workspace()`
5. `load_preferences()` — restore window state, AI settings, user prefs
6. `_start_background_tasks()` — autopilot tick, semantic warmup, model poll

### Action registry

All menu actions are declared in `studyplan/app/action_registry.py` as `ActionBinding` dataclasses. The registry maps action names to handler method names and is installed via `_install_action_bindings()`. This makes the action surface testable without a live GTK window.

### GTK4 lint

`tools/gtk4_lint.py` checks for deprecated GTK4 patterns (e.g. `set_markup` without markup safety, deprecated widget methods). Run it as a pre-commit check.

---

## Testing Architecture

### Test surface

| Suite | Where | GTK needed? | Coverage |
|---|---|---|---|
| Unit (default) | `tests/` | No | ~388 tests |
| Integration | `studyplan/testing/` | No | ~80 tests |
| Full (with GTK) | both | Yes | ~545 tests |
| Tutor quality | `tests/tutor_quality/` | No | Prompt quality scores |

### Tutor quality pipeline

`tools/run_tutor_quality_pipeline.py` runs a multi-scenario quality benchmark and compares against reference scores. Gate policies (`tests/tutor_quality/policy_profiles_v1.json`) vary by branch:

| Branch | Policy |
|---|---|
| `release/*` | `strict_release` |
| `main` | `balanced_main` |
| `feature/*` | `feature_relaxed` |

The reference report (`tests/tutor_quality/reference_report_v1.json`) is the regression baseline. The comparison report and trend report are uploaded as CI artifacts.

### Smoke test KPIs

Three KPIs must pass for the strict smoke gate:

| KPI | Threshold |
|---|---|
| `coach_pick_consistency_rate` | ≥ 0.999 |
| `coach_only_toggle_integrity_rate` | == 1.0 |
| `coach_next_burst_integrity_rate` | == 1.0 |

---

## CI Workflow

`.github/workflows/linux-ci.yml` runs on every PR and push to `main`/`release/**`/`feature/**`:

1. **lint-type** — `python tools/gtk4_lint.py` + `pyright`
2. **unit** — `pytest -q`
3. **smoke** (after lint+unit) — `xvfb-run -a timeout 180s python studyplan_app.py --dialog-smoke-strict`
4. **perf** (after lint+unit) — `python tools/run_perf_benchmark.py`; on `release/*` branches requires Ollama
5. **tutor-quality** (after lint+unit) — policy-gated quality benchmark

`.github/workflows/windows-installer.yml` builds a Windows `.exe` installer via PyInstaller + Inno Setup on push to `main` or `v*` tags (or manual dispatch).

`.github/workflows/tutor-quality-nightly.yml` runs a deeper quality benchmark nightly.

---

## Configuration Reference

All configuration lives in `studyplan/config.py` as the `Config` class. Every setting is overridable via environment variable. Key groups:

### Paths

| Env var | Default | Description |
|---|---|---|
| `STUDYPLAN_CONFIG_HOME` | `~/.config/studyplan` | Root data directory |
| `STUDYPLAN_DATA_PATH` | `./data/state` | Engine persistence base path |
| `STUDYPLAN_OLLAMA_MODELS_DIR` | platform default | Ollama blobs directory |

### SRS

| Env var | Default | Description |
|---|---|---|
| `STUDYPLAN_SRS_ALGORITHM` | `fsrs` | `fsrs`, `sm2`, or `legacy` |

### LLM

| Env var | Default | Description |
|---|---|---|
| `STUDYPLAN_LLM_GATEWAY_ENABLED` | `0` | Enable OpenAI-compatible cloud gateway |
| `STUDYPLAN_LLM_GATEWAY_ENDPOINT` | — | Gateway URL |
| `STUDYPLAN_LLM_GATEWAY_MODEL` | — | Primary model ID |
| `STUDYPLAN_LLM_GATEWAY_MODEL_FALLBACKS` | — | Comma-separated fallback model IDs |
| `STUDYPLAN_LLM_GATEWAY_API_KEY` | — | Bearer token (also `OPENROUTER_API_KEY`) |
| `STUDYPLAN_LLAMA_CPP_MANAGED_SERVER` | `1` | Auto-start/stop llama-server |
| `STUDYPLAN_LLAMA_SERVER_BIN` | — | Path to `llama-server` binary |
| `STUDYPLAN_LLAMA_SERVER_PORT` | `8090` | llama-server port |
| `STUDYPLAN_LLAMA_SERVER_N_GPU_LAYERS` | `0` | GPU offload layers (0 = CPU only) |

### Performance

| Env var | Default | Description |
|---|---|---|
| `STUDYPLAN_PERFORMANCE_CACHE_ENABLED` | `1` | Enable performance cache |
| `STUDYPLAN_AUTO_QUESTION_GENERATION_CAP` | `1500` | Max AI-generated questions per module |
| `STUDYPLAN_AUTO_QUESTION_GENERATION_DAILY_BUDGET` | `30` | Max generated per day |

---

## Deployment

`deploy.py` provides a simple one-command promote/revert flow for release management:

```bash
python deploy.py promote <version>   # tag and deploy
python deploy.py revert              # rollback to previous
python deploy.py status              # show current deployed version
```

For the Windows installer, trigger the `Windows Installer` workflow manually or push a `v*` tag. The resulting `.exe` is available as a CI artifact.

For low-RAM / embedded Linux deployments with a local LLM, see `contrib/garuda-low-ram-llm/` for kernel tuning and BTRFS configuration notes.

For running Ollama as a systemd service, see `contrib/studyplan-llm-systemd/`.
