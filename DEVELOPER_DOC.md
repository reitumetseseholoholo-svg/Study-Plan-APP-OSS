# Developer Documentation — Study Workbench

This document covers the application architecture, key subsystems, internal design decisions, and operational guides for developers.

**Study Workbench** (formerly "Study Assistant") is a self-contained desktop study environment for professional exam preparation. It is module-agnostic — you load any professional syllabus (ACCA, etc.) and the entire system adapts: SRS, coach, tutor, autopilot, analytics.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module System](#module-system)
3. [SRS Scheduling (FSRS-4.5 and SM-2)](#srs-scheduling-fsrs-45-and-sm-2)
4. [Coach and Recommendation Engine](#coach-and-recommendation-engine)
5. [AI Cockpit (Autopilot)](#ai-cockpit-autopilot)
6. [AI Tutor and RAG Pipeline](#ai-tutor-and-rag-pipeline)
7. [LLM Pipeline Architecture](#llm-pipeline-architecture)
8. [Prompt Engineering Design (3Es + Fail-Safe)](#prompt-engineering-design-3es--fail-safe)
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
18. [Domain Reasoning Engine](#domain-reasoning-engine)
19. [CCI Research Protocol & Algebra Ontology](#cci-research-protocol--algebra-ontology)
20. [Provenance Kernel](#provenance-kernel)
21. [Configuration Reference](#configuration-reference)
22. [Deployment](#deployment)

---

## Architecture Overview

Study Workbench is a **single-process GTK4 desktop application**. There is no backend server, no external database, and no network dependency at runtime (local LLM and all data files are local). Think of it as a local-first, AI-integrated study OS for your desktop.

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
│  syllabus parsing, semantic routing, persistence        │
└──────────────┬──────────────────────────┬───────────────┘
               │                          │
               ▼                          ▼
     studyplan/domain_reasoning/     studyplan/
     reasoning_engine.py             fsrs.py
     concepts.py                     contracts.py
     templates.py                    config.py
     evaluator.py                    ai/ (LLM)
     diagnostics.py                  services.py
     domains/acca_fm/                cognitive_state.py
       npv, wacc, capm, irr, ...    mastery_kernel.py
                                     coach_fsm.py
```

### Files and their roles

| File | Role |
|---|---|
| `studyplan_app.py` | GTK4 main window. All UI construction, event handlers, Pomodoro, quiz flow, AI cockpit, preferences. ~58,100 lines. |
| `studyplan_engine.py` | Data model, SRS (FSRS-4.5/SM-2), daily plan, coach urgency scoring, ML inference, syllabus parsing, semantic routing, persistence. ~14,900 lines. |
| `studyplan_ai_tutor.py` | AI tutor session management: prompt assembly, RAG retrieval, Ollama/gateway calls, streaming, response sanitization. ~3,700 lines. |
| `studyplan_app_kpi_routing.py` | KPI thresholds and smoke/soak test routing helpers. GTK-independent. |
| `studyplan_app_path_utils.py` | Path helpers extracted for unit-testability without GTK. |
| `studyplan_ui_runtime.py` | UI state at startup (module title, exam date, etc.). GTK-independent. |
| `studyplan_file_safety.py` | `enforce_file_size_limit`, `secure_path_permissions`. |
| `studyplan/config.py` | `Config` class — single source of truth for all runtime configuration. All settings are environment-variable-driven with typed defaults. |
| `studyplan/contracts.py` | Typed dataclass API contracts shared between engine, tutor, and services. |
| `studyplan/services.py` | Python Protocol interfaces (`TutorService`, `CoachService`, `RagService`, `AutopilotService`, etc.). |
| `studyplan/domain_reasoning/reasoning_engine.py` | Deterministic domain reasoning entry point: `reason_question()`, plan compilation, execution, multi-path fallback, gap analysis, confidence scoring. |
| `studyplan/domain_reasoning/concepts.py` | Concept registry: `BUILTIN_CONCEPTS`, `_OUTPUT_SLOT_GROUPS`, concept loading from module JSON. |
| `studyplan/domain_reasoning/templates.py` | `FormulaTemplate`: base class for executable solver templates with input schema, output schema, and `solve()`. |
| `studyplan/domain_reasoning/evaluator.py` | Step-by-step learner answer comparison and error classification against deterministic truth. |
| `studyplan/domain_reasoning/diagnostics.py` | Structured error pattern emission from solver comparison results. |
| `studyplan/domain_reasoning/domain_registry.py` | Per-exam registry hub: `DomainRegistry`, `register_domain()`, `get_registry()`, `list_domains()`. Routes concepts/templates/slot groups by domain prefix. |
| `studyplan/domain_reasoning/domains/acca_fm/` | FM domain solvers: `npv.py` (NPV), `wacc.py` (WACC), `capm.py` (CAPM), `irr.py` (IRR), `payback.py`, `arr.py`, `ccc.py` (Cash Cycle), `eoq.py` (EOQ), `gearing.py`. |
| `studyplan/domain_reasoning/domains/pmp.py` | PMP PoC domain: CPI, SPI, EAC formulas via `declare_formula()` DSL. Auto-registers at import time. |
| `studyplan/ai/llama_runtime.py` | `LlamaRuntime` — LLM orchestrator: tries Ollama → managed llama-server → cloud API |
| `studyplan/ai/llama_server.py` | `LlamaServerManager` — manages `llama-server` subprocess lifecycle |
| `studyplan/ai/circuit_breaker.py` | `CircuitBreaker` — per-backend failure tracking with auto-reset |
| `studyplan/ai/model_selector.py` | `ModelSelector` — task-aware model ranking and filtering |
| `studyplan/ai/gguf_registry.py` | `GgufRegistry` — scans for `.gguf` model files on disk |
| `studyplan/ai/llm_auth.py` | API key resolution for cloud LLM providers |
| `studyplan/ai/recovery.py` | Deterministic fallback response; never raises |
| `studyplan/ai/tutor_llm_purpose.py` | LLM request purpose classification |
| `studyplan/ai/model_routing.py` | Per-purpose model routing configuration |
| `studyplan/ai/prompt_design.py` | Prompt template management (3Es design) |
| `studyplan/ai/tutor_prompt_layers.py` | Base tutor identity and coach identity lines |
| `studyplan/provenance/kernel/primitives.py` | Provenance kernel — `collect_inherited_constraints`, ViewState algebra, artifact abstractions |
| `studyplan/provenance/experiments/` | Construction experiments (P0 provenance completeness, P1 ArtifactStore protocol) |
| `tools/algebra_observatory.py` | Algebra observatory v2 — confidence distributions, coherence metric, 7-algebra scorer |
| `tools/algebra_experiments.py` | Experiment harness — Phase 2 discovery experiments |
| `tools/algebra_residual_analysis.py` | Residual clustering (E1) and property augmentation (E2) |
| `tests/test_architectural_invariants.py` | 14 architectural invariant tests + P7 provenance algebra principle tests |

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

### Rust/PyO3 acceleration

`studyplan/rs/srs_select.py` transparently accelerates heavy SRS operations:
- `select_srs_from_scored(union_of_scored, ...)` — Phases 1–4 of `select_srs_questions` (scored tuples → selected indices); falls back to `_select_srs_from_scored_py()`
- `batch_score_srs(items, ...)` — batch overdue/retention scoring; falls back to `_batch_score_srs_py()`

The Rust path is auto-detected at import time (`from studyplan_rs import ...`). Pure-Python fallbacks are always available — no hard dependency on a Rust toolchain. See `studyplan/rs/` for the Cargo project.

### Provenance Validation (PV03)

The SRS engine was the target of Prospective Validation cycle PV03 (14 predictions,
10✔, 1◐, 3✘, 5★). Key findings:
- SRS is a **state manager**, not an execution-trace system — it violates I1 (Lifecycle),
  I2 (Trace Immutability), and I5 (Process Statelessness) by design
- Dual-language acceleration (Python + Rust/PyO3) was an unexpected discovery (★1)
- Three-phase selection pipeline (★2) and algorithmic dualism via env var (★3) are
  patterns outside CCI's scope
- The refuted principles delineate the boundary between **data-integrity systems**
  (SRS) and **execution-integrity systems** (CCI algebra processes)

See `docs/specification/predictions/pv03_predictions.md` for the full record.

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

### LLM Pipeline Architecture

The app supports **6 LLM backends** routed through a layered fallback chain managed by `LlamaRuntime` (`studyplan/ai/llama_runtime.py`).

#### Backend priority & fallback chain

The runtime tries backends in this order:

1. **Cloud API gateway** (if enabled) — OpenAI-compatible endpoint (OpenRouter, OpenAI, Anthropic, Gemini, etc.)
2. **Managed llama-server** — auto-starts/stops `llama-server` subprocess with GGUF models from disk
3. **Ollama** — auto-discovered at `http://127.0.0.1:11434`

If all three fail, an error is returned to the caller. Individual backend recovery steps:

| Backend | Circuit breaker | Cooldown | Probe |
|---------|----------------|----------|-------|
| Cloud endpoint | `_cloud_circuit_breaker` (3 failures) | 30s | TCP + HTTP call |
| Managed llama-server | None (re-created on next request) | — | `/health` endpoint (2s timeout) |
| Ollama | `_llm_model_health` per-model cooldown | 30-60s | `ollama list` (3s timeout) |

#### Backend files

| File | Role |
|------|------|
| `studyplan/ai/llama_runtime.py` | `LlamaRuntime` — orchestrator: tries Ollama first, falls back to managed llama-server, then cloud API |
| `studyplan/ai/llama_server.py` | `LlamaServerManager` — manages `llama-server` subprocess lifecycle, health checks, idle shutdown |
| `studyplan/ai/model_selector.py` | `ModelSelector` — ranks/filters models for task (context window, speed, etc.) |
| `studyplan/ai/model_ranker.py` | `ModelRanker` — cross-backend latency/quality ranking |
| `studyplan/ai/circuit_breaker.py` | `CircuitBreaker` — per-backend failure tracking with auto-reset |
| `studyplan/ai/gguf_registry.py` | `GgufRegistry` — scans standard directories for `.gguf` files |
| `studyplan/ai/llm_auth.py` | LLM auth — API key resolution for cloud providers |
| `studyplan/ai/recovery.py` | Deterministic structured-error fallback; never raises |
| `studyplan/ai/tutor_llm_purpose.py` | Request purpose classification (tutor, coach, autopilot, ...) |
| `studyplan/ai/model_routing.py` | Per-purpose model routing configuration |
| `studyplan/ai/prompt_design.py` | Prompt template management (3Es design) |
| `studyplan/ai/tutor_prompt_layers.py` | Base tutor identity, coach identity lines |

#### Connectivity detection

`_has_internet_connectivity()` (studyplan_app.py ~19215) probes reachability via TCP:
- Targets: `1.1.1.1:443`, `8.8.8.8:53`, plus the cloud endpoint's host
- Per-probe timeout: 1.5s
- Cache: 30s when online, **5s when offline** (reduced from 10s for faster re-detection)

`_cloud_connectivity_policy_mode()` resolves the effective mode:
- Instance attribute `cloud_connectivity_policy` (from Preferences) if set to `online` or `offline`
- Falls back to env var `STUDYPLAN_CLOUD_CONNECTIVITY_POLICY` (`auto`, `force_online`, `force_offline`)
- Defaults to `auto` (probe-based)

`_cloud_model_routing_mode()` returns `"online"` or `"offline"` by combining policy + probe result. `_remote_llm_backends_allowed()` gates all cloud API calls on this.

#### Cloud circuit breaker

`_cloud_circuit_breaker` (`CircuitBreaker`, threshold=3, cooldown=30s) in studyplan_app.py ~2371 protects `cloud_endpoint`. When the circuit is open, cloud API calls are skipped entirely and the managed llama-server is used instead. The breaker resets automatically after 30s.

#### Model routing per purpose

Each LLM request is classified into a purpose (`tutor`, `coach`, `deep_reason`, `autopilot`, `gap_generation`, `section_c_generation`, `section_c_evaluation`, `section_c_judgment`, `section_c_loop_diff`, `general`). The routing config in `studyplan/ai/model_routing.py` maps purpose → preferred model candidates. The router tries candidates in order, skipping any that are on cooldown or have open circuit breakers.

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
| `coach_briefing_digest` | session (per dashboard render cycle) |

### Coach 2× render multiplier (fixed)

Two locations had `_queue_coach_sync_if_mismatch()` called **before** `_ensure_coach_pick_consistency()`, guaranteeing a false-positive mismatch that scheduled an extra `update_dashboard()` — producing a 2× multiplier on every render:

1. `_render_dashboard`: moved after consistency sync
2. `_update_study_room_card_impl_inner`: moved after consistency sync

Combined with 7+ expensive engine queries in the coach card update, a single dashboard render used to trigger **14+ engine queries** in one burst. This is now eliminated.

### TF-IDF warmup thread storm (fixed)

`_semantic_prefetch_chapter_assets()` used `max_workers = min(len(work_items), max(1, os.cpu_count() or 4))` — spawning a ThreadPoolExecutor per chapter equal to CPU core count. Each worker called `TfidfVectorizer.fit_transform()` (CPU-bound). On an 8-core machine with 6 prefetch chapters, all cores saturated in a CPU-bound computation storm.

**Fix**: workers capped to max 2. TF-IDF `fit_transform` is CPU-bound; >2 threads adds OS scheduler overhead without throughput gain. Configurable via `SEMANTIC_WARMUP_PREFETCH_MAX_WORKERS`.

### Profiler report (`--perf-stats`)

The `PerformanceProfiler` (studyplan/components/performance/profiler.py) collects timing data for any operation instrumented via `_perf_record()` or `profiler.profile_operation()`. Data is collected at runtime but **not displayed** unless the `--perf-stats` CLI flag is passed:

```bash
python studyplan_app.py --perf-stats
```

When the window closes, a formatted report is printed to stdout containing:
- **Per-operation stats**: call count, avg/median/p95/p99/min/max durations, success rate, error count
- **Alerts**: operations exceeding their configured threshold (severity: warning/error/critical)
- **Recommendations**: auto-generated suggestions (high latency → cache, low success rate → investigate errors)

**Currently instrumented call sites** (studyplan_app.py):
- `coach_pick_update` — `_update_coach_pick_card` timing
- `study_room_update` — `_update_study_room_card` timing
- `daily_plan_render` — `_render_dashboard` daily plan section timing

Add new instrumentation anywhere via:
```python
self._perf_record("my_operation", duration_ms)
```
or wrap a function:
```python
result = self._perf_profiler.profile_operation("my_operation", my_func, arg1, arg2)
```

The profiler is initialized at startup by `_initialize_performance_services()` (line 2721). If the integration module is unavailable, `_perf_profiler`, `_perf_cache`, and `_perf_middleware` are `None` and all calls are no-ops.

### Configuration

```
STUDYPLAN_PERFORMANCE_CACHE_ENABLED=1            # on by default
STUDYPLAN_PERFORMANCE_CACHE_MAX_SIZE=<n>         # default: host-dependent
STUDYPLAN_PERFORMANCE_CACHE_TTL_COACH_PICK=300   # per-category TTL overrides
```

View stats: **Tools → More → View Performance Stats** | Clear: **Tools → More → Clear Performance Cache**

---

## Domain Reasoning Engine

`studyplan/domain_reasoning/reasoning_engine.py`

A GTK-free deterministic reasoning layer that executes domain concepts (formulas, procedures) and computes solution confidence. It augments the existing LLM/coach pipeline with verifiable intermediate computations.

### Architecture phases

**Phase 1 — Parameter key detection:** `_build_inputs_for()` probes candidate source functions to resolve which input keys a solver needs. Backward-compatible wrapper `_build_inputs_with_sources()` returns `(inputs, sources)` for provenance tracking.

**Phase 2 — Multi-path fallback:** `_OUTPUT_SLOT_GROUPS` derived from `BUILTIN_CONCEPTS`. `_find_alternatives()` queries same-slot providers. `_execute_plan` retries via alternatives when a step fails (e.g. `fm.cost_of_equity_dvm` falls back to `fm.capm`).

**Phase 3 — Input gap analysis:** `_plug_input_gaps()` runs after plan compilation. A greedy fixed-point algorithm inserts provider concepts when a missing parameter has a fully-available provider. Transitive dependencies are resolved at execution time.

**Phase 4 — Weighted confidence:** `_compute_confidence()` blends `input_source_quality` (explicit=1.0, inferred=0.85, extracted=0.70) with step success rate via product `avg_quality × success_rate`.

### Supported FM concepts

| Concept | Solver | Output slot | Fallback provider |
|---|---|---|---|
| NPV | `npv.py` | `npv` | — |
| WACC | `wacc.py` | `wacc` | — |
| CAPM | `capm.py` | `cost_equity` | cost_of_equity_dvm |
| DVM | `dvm.py` (via gearing) | `cost_equity` | capm |
| IRR | `irr.py` | `irr` | — |
| Payback | `payback.py` | `payback` | — |
| ARR | `arr.py` | `arr` | — |
| CCC | `ccc.py` | `ccc` | — |
| EOQ | `eoq.py` | `eoq` | — |
| Gearing | `gearing.py` | `gearing` | — |

### Cross-exam support via DomainRegistry

`studyplan/domain_reasoning/domain_registry.py`

The engine now supports any professional exam through a per-exam `DomainRegistry`:

- **Global hub**: `register_domain(DomainRegistry)`, `get_registry("pmp")`, `list_domains()`
- **Each registry** holds its own concept map, template registry, formula mappings, label aliases, detection patterns, and slot groups.
- **`reason_question(domain="pmp")`** routes all internal lookups through the domain's registry instead of the default ACCA FM globals.
- **`detect_concepts(question, domain="pmp")`** uses per-domain pattern-based detection.
- **`evaluate_question(domain="pmp")`** routes template/concept lookups through the domain registry.
- **ACCA FM** is auto-registered at import time via `_build_acca_registry()` in `concepts.py`.
- **PMP PoC** (`domains/pmp.py`) registers CPI, SPI, EAC formulas — auto-registered at import time.

Adding a new exam domain: one `declare_formula(registry=...)` call per formula, then `register_domain(registry)`.

### Entry point

```python
from studyplan.domain_reasoning.reasoning_engine import reason_question

result = reason_question("WACC",
                         template_ref="fm.wacc",
                         template_inputs={"equity": 60, "debt": 40})
# result.confidence  → 0.111
# result.steps       → plan with provenance and quality per step

# Cross-exam usage:
result = reason_question("CPI",
                         domain="pmp",
                         template_inputs={"ev": 200, "ac": 250})
```

### Known fixes (Jun 2026 audit)

1. **Dead code in `_parse_number`** (`step_matcher.py:144-146`): line 146 replaced commas with dots, but line 144 already stripped all commas — dead code since March 2024. Removed.
2. **Tolerance variance documented** (`step_matcher.py:27` vs `evaluator.py:253`): step matcher uses 2% relative tolerance (`_STEP_TOLERANCE`), evaluator uses 0.5% (`abs(ref) * 0.005`). Intentionally different — intermediate steps have more rounding variance than final answers. Comment added to prevent future confusion.
3. **Empty question in multi-path fallback** (`reasoning_engine.py:757`): fallback path passed `""` instead of the original question text to `_build_inputs_with_sources`, depriving alternative concepts of number extraction from the question. Fixed by threading `question` through `_execute_plan`.
4. **Silent `except Exception: pass`** (`evaluator.py:165-168`): `template.solve()` exceptions were swallowed silently, masking bugs in Jinja2 templates (undefined variables, type errors). Now logged via `_logger.warning()` with concept ID.

### Key invariants

- Domain templates override `solve()` with positional args; solver param names do NOT match input dict keys. Candidate-function probing is the primary key-detection method.
- `_plug_input_gaps` does NOT resolve transitive dependencies of newly inserted concepts; relies on multi-path fallback at execution time.
- WACC template applies `(1-tax)` to `cost_debt` internally; `cost_of_debt` solver returns after-tax value — double-tax is existing behaviour, not a regression.

### Practice loop integration

When `DeterministicTutorAssessmentService` has a `domain_reasoner` callable (wrapping `engine.domain_reason_question`), practice items that carry a `template_ref` are evaluated deterministically in `_assess_domain_item()`:

1. The domain solver computes the reference truth from the item's `template_ref` + `template_inputs`
2. The learner's final numeric answer is compared against the truth
3. Execution failures (`failed_steps`) and error tags (`error_patterns`) are extracted from the trace
4. These are merged into the `TutorAssessmentResult` alongside `concept_ids` and `diagnostic_confidence`

The learner profile store tracks concept error patterns across assessments via `concept_error_patterns` and `weak_concept_ids_top` on `TutorLearnerProfileSnapshot`. These fields are surfaced in the tutor context brief as "Weak domain concepts".

### Related test files

- `tests/test_reasoning_engine.py` (76 test functions) — engine integration: fallback, gap analysis, confidence
- `tests/test_domain_reasoning.py` (63 test functions) — concept registry and solver registry
- `tests/test_numerical_solver.py` (81 test functions) — per-solver correctness and edge cases
- `tests/test_tutor_phase1_services.py` — `TestDomainAwareAssessment` (7 tests) + `TestConceptProfileTracking` (3 tests)

---

## CCI Research Protocol & Algebra Ontology

The CCI Research Protocol (`docs/specification/RESEARCH_PROTOCOL.md`, 801 lines, frozen)
investigates the **computational algebra ontology** — a characterisation of cognitive
processes in terms of state topology, dynamics, invariants, conserved quantities,
and completion semantics.

### The ontology: A = (S, M, I, C, Φ)

Every algebra is defined by five axes:

| Axis | Question | Example |
|------|----------|---------|
| **S** — State space | What shape is the state? | Tree, distribution, constraint graph |
| **M** — Operator algebra | What transformations are admissible? | Traverse, reweight, propagate |
| **I** — Logical invariants | What holds at every reachable state? | Exactly one active path, Σp = 1 |
| **C** — Conserved quantities | What is preserved by every M? | Probability mass, justification closure |
| **Φ** — Completion semantics | What is the fixed point? | Most probable path, equilibrium distribution |

### 7 known algebras

| # | Algebra | State | Operator | Conserved quantity |
|---|---------|-------|----------|-------------------|
| 0 | Computation (reference) | Stack frame | Step | Call/return balance |
| 1 | Classification | Distribution | Condition | Probability mass (Σp = 1) |
| 2 | Diagnosis | Bayesian net | Propagation | Total belief (ΣBelief = 1) |
| 3 | Evaluation | Comparison tree | Traversal | Exactly one active path |
| 4 | CSP | Constraint graph | Constraint propagation | Equivalence closure |
| 5 | GrowingGraph | Directed graph | Extend with fidelity | Coherence (maximum minimal) |
| 6 | Justification | Proof tree | support/retract | Justification closure |
| **7** | **Provenance Query** | **ViewState** | **dispatch (project/filter/map/join)** | **Plan fidelity** |

### 8 mutation operators

| # | Operator | Properties | Used by |
|---|----------|-----------|---------|
| 1 | condition | branching | Classification |
| 2 | propagate | non-local, monotonic, value mutation | Diagnosis |
| 3 | traverse | non-local | Evaluation |
| 4 | constraint_propagate | reversible, non-local, monotonic | CSP |
| 5 | extend | generative, branch mutation | GrowingGraph |
| 6 | support / retract | reversible, value mutation | Justification |
| 7 | infer | reversible, value mutation, monotonic | Justification |
| **8** | **dispatch** | **reversible, value mutation, non-local** | **Provenance Query** |

Dispatch is the only meta-operator: it does not transform state directly but
selects and applies sub-operators from a fixed plan.

### 14 architectural principles

Principles I1–I14 govern all algebra implementations. Each has a three-layer
maturity classification (Cross-Domain / Execution-Runtime / CCI-Specific):

| Principle | Verified? | Core statement |
|-----------|-----------|----------------|
| I1 Lifecycle | 2✔ 1✘ | Every algebra has a lifecycle |
| I2 Trace Immutability | 1✔ 1◐ 1✘ | Traces are append-only after creation |
| I3 Causal Provenance | 3✘ | Every state points to its predecessor |
| I4 Agnosticism | 3✔ | Algebra is interpreter-independent |
| I5 Statelessness | 2✔ 1✘ | Each step is a pure function of input |
| I6 Independence | 3✔ | Result encodes answer, not internals |
| I7 Validity | 3✔ | Failure produces `None`/`[]`, not crash |
| I8 Hashing | 3✔ | State identified by hash, not reference |
| I9 Partitioning | 2✔ 1◐ | State split into inputs/control/output |
| I10 Step Return | 3✘ | Each step returns `(result, next_state)` |
| I11 Dual Protocol | 3✘ | Process + Executor protocols |
| I12 Constructor Divergence | 2◐ 1✔ | Constructor and step shapes differ |
| I13 Event Iteration | 3✔ | Event loop delegates step iteration |
| I14 Comparison Envelope | 3✔ | Comparison never reaches into state |

PV03 refutations (I1, I2, I5) are principled: these principles govern
*execution-trace systems* but not *data-integrity systems* (state managers
like the SRS engine).

### Key files

| File | Role |
|------|------|
| `docs/specification/RESEARCH_PROTOCOL.md` | Frozen 801-line protocol |
| `docs/specification/CCI_SPEC.md` | Full specification with 14 principles |
| `docs/algebra_atlas.md` | 795-line algebra ontology with 7 algebras |
| `tools/algebra_observatory.py` | 7-algebra classifier (confidence, coherence) |
| `tools/algebra_experiments.py` | 9 Phase 2 experiments |
| `tools/algebra_residual_analysis.py` | Residual clustering (E1/E2) |
| `tests/test_architectural_invariants.py` | Principle tests + P7 provenance tests |

---

## Provenance Kernel

`studyplan/provenance/kernel/primitives.py`

The provenance kernel provides generic graph reachability and constraint
collection over artifact dependency graphs. It contains zero domain-specific
knowledge — it works identically for FM financial concepts (WACC → CAPM
constraint propagation) and PostgreSQL query plans (GEQO → plan tree
constraint inheritance).

### Core primitives

| Primitive | Signature | Purpose |
|-----------|-----------|---------|
| `collect_inherited_constraints(artifact)` | `Artifact → set[Constraint]` | BFS over output→input edges, unions constraints |
| `ViewState` | dataclass | Immutable algebra snapshot: metadata, state, constraints |
| `serialize(artifact)` | `Artifact → dict` | Recursive JSON-compatible converter |
| `deserialize(data, artifact_type)` | `dict → Artifact` | Structural reconstruction |

### Provenance Completeness (P0, confirmed)

Constraint inheritance reduces to generic BFS — no new ontology needed. Two
kinds of provenance discovered:
- **Execution provenance**: graph reachability ("what does this depend on?")
- **Validity provenance**: constraint collection ("what must be true for this to be valid?")

Both are query strategies over one graph. The same code path serves Tutor,
Debugger, and Lab.

### ArtifactStore Protocol (P1, confirmed)

Minimal persistent store: directory of JSON files, keyed by `content_hash`,
zero in-memory cache, zero indexing, zero schema versioning. All algebra-relevant
state is captured by ViewState serialization. Storage is a pure IO layer —
no kernel changes needed.

### Construction experiments

Every new component follows Phase II protocol: hypothesis → predictions →
experiment → evidence → decision. Nothing bypasses evidence.

### Key files

| File | Role |
|------|------|
| `studyplan/provenance/kernel/primitives.py` | Core: ViewState, collect_inherited_constraints |
| `studyplan/provenance/kernel/test_p0_provenance_completeness.py` | 10 P0 tests |
| `studyplan/provenance/kernel/test_p1_artifact_store.py` | 12 P1 tests (1 pre-existing fail) |

---

## GTK4 Application Architecture

`StudyPlanGUI` (a `Gtk.ApplicationWindow`) is constructed by `StudyApp.do_activate()`. The class is large by necessity — GTK4 requires widget construction and callback wiring in the same scope.

### Startup sequence

1. `_smoke_bootstrap()` — configure process env vars (loky, joblib) before any imports
2. `StudyApp.do_activate()` → `StudyPlanGUI.__init__()` → `StudyPlanEngine.__init__()` with `defer_data_load=True`
3. `_build_main_window()` → `_build_left_panel()`, `_build_dashboard()`, `_build_tutor_workspace()` — **<50 ms to first paint**
4. `load_preferences()` — restore window state, AI settings, user prefs
5. `_run_initial_refresh()` → `GLib.idle_add(engine._do_deferred_data_load())` — data, models, and questions load in the background
6. `_start_background_tasks()` — autopilot tick, semantic warmup, model poll

**Deferred loading** (engine `defer_data_load=True`): the engine initialises with empty defaults in <50 ms. `load_data()`, model loading, `load_questions()`, and `save_data()` are skipped until `_do_deferred_data_load()` fires via `GLib.idle_add` from `_run_initial_refresh()`. Guard method `_ensure_deferred_data_loaded()` is called before any data-dependent operation. This means the UI is interactive from second zero — no splash screen, no spinner.

### Dashboard section reconciliation

The dashboard uses digest-checked section IDs (`_ds_id`, `_ds_digest`) to avoid redundant GTK rebuilds:

1. Each section is tagged with a unique `_ds_id` via `_ds_mark()` at build time.
2. Expensive sections (coach briefing: 7+ engine queries) use `_ds_check(sid, digest)` — if the section exists with a matching digest, the entire rebuild is skipped.
3. `_reconcile_sections()` at the end of every render cycle removes orphan widgets whose `_ds_id` wasn't marked in that cycle — this automatically handles conditional sections (focus mode, tile mode, empty states).
4. The full-clear loop (`while child: remove child`) was **removed** — sections update in place without flash.

**Why this matters**: before reconciliation, every dashboard refresh unconditionally cleared all ~35 children and rebuilt from scratch. Now the coach briefing (most expensive section) skips entirely when data unchanged, and all other sections update in place.

### Dashboard card order (6 new insight cards)

The dashboard render order after the chart block is: Plan View → **Daily Plan** → **Error Patterns** → **Focus Detective** → **Study Guide** → **Progress Predictions** → **Knowledge Graph** → Study Snapshot → Weekly Summary → Mastery Snapshot → Weak vs Strong → Reviews & Pace → Reviews Due Today → Leech Alerts → Study Hub → Data Health → Activity Chart.

New cards use `_ds_mark()` for reconciliation and follow the existing pattern for conditional visibility:
- **Daily Plan** (`daily_plan`): hidden when exam date or module availability is not set.
- **Error Patterns** (`error_patterns`): hidden when no weak outcomes found.
- **Focus Detective** (`focus_detective`): hidden when no per-topic time data available.
- **Study Guide** (`study_guide`): always shown; per-chapter "Generate" buttons call `_generate_ai_chapter_summary()` via `_start_managed_background_thread`.
- **Progress Predictions** (`progress_predictions`): hidden when exam date not set or no study history.
- **Knowledge Graph** (`knowledge_graph`): always shown; Cairo DAG with `engine.CHAPTER_FLOW` edges.

### Common pitfalls

**`_ds_check` guard + variable scope**: if a variable is assigned inside an `if not _ds_check(...):` block and used after it, the variable is **unbound** on cache hit (when `_ds_check` returns True). This caused real crashes (`readiness_tier` UnboundLocalError) and stale-data bugs (`mission_tasks` showing 0/0 on every second render). Fix: hoist the computation before the `_ds_check` guard, leaving only UI construction inside the block.

### Action registry

All menu actions are declared in `studyplan/app/action_registry.py` as `ActionBinding` dataclasses. The registry maps action names to handler method names and is installed via `_install_action_bindings()`. This makes the action surface testable without a live GTK window.

### Status bar / Workbench shell

Three labels in the bottom bar (part of `_build_workbench_shell()`) display live status:

| Label | Method | Content |
|-------|--------|---------|
| `workbench_status_label` | `_refresh_workbench_shell_status` | Page • Topic • Model • Autopilot mode • RAG embeddings • Sidebar state • **Connectivity** (Net on/off) |
| `workbench_model_label` | `_refresh_workbench_model_readiness_line` → `_compute_workbench_model_readiness` | Model source + ready state + **cloud health** (circuit open/ready) |
| `workbench_health_label` | `_refresh_workbench_app_health_line` → `_compute_workbench_app_health` | Sync status, model availability, **offline**, **circuit breaker** state |

States emitted by `_compute_workbench_model_readiness()`: `disabled`, `unavailable`, `recovering`, `not_loaded`, `syncing`, `ready`. When cloud gateway is enabled, appends `" \| Cloud: ready"` or `" \| Cloud: circuit open (Xs)"`.

States emitted by `_compute_workbench_app_health()`: `sync_issue`, `model_unavailable`, `recovery_mode`, `offline`, `offline_with_circuit`, `circuit_open`, `ready`.

All three labels refresh on a 2-second `GLib.timeout_add` timer via `_start_workbench_status_timer()`.

### Visual layout patterns

**Left panel**: `Gtk.Box(VERTICAL, spacing=12)` with `set_size_request(250, -1)`, `hexpand=True`, `halign=FILL`. Key children:

| Widget | hexpand | Notes |
|--------|---------|-------|
| Coach card (`hero_card`) | `True` | Fills panel width |
| Study room card (`feature_card`) | `True` | Fills panel width |
| AI Cockpit card (`hero_card`) | `True` | Fills panel width |
| Quest card | `True` | Fills panel width |
| Activity heatmap | `True` + `halign=FILL` | GitHub-style grid, cells + columns all `hexpand=True` — spans full panel |
| Topic dropdown | `True` | Fills width |

All card containers must set `set_hexpand(True)` to fill the left panel. The panel itself already has `hexpand=True` + `halign=FILL`, but cards without explicit `hexpand` will only use their natural width.

**Activity heatmap**: 12-column × 7-row grid of colored `Gtk.Label` cells (CSS classes: `heatmap-active`, `heatmap-inactive`, `heatmap-future`). The grid_box, each week column, and each cell all have `set_hexpand(True)` so the heatmap spans the full left panel width. Cells have a minimum `set_size_request(10, 10)` and expand horizontally to fill their column.

### Dashboard chart system

All charts are Cairo-based (`Gtk.DrawingArea` with `set_draw_func`). Key patterns:
- `set_size_request(min_width, height)` + `set_hexpand(True)` — charts fill container width
- Bar widths are computed dynamically from allocated width `w_f` in the draw callback
- The hbar kind computes `bar_max_w = max(1.0, w_f - bar_x - val_w)` so bars always fill available space

### GTK4 deprecation warnings

The app targets GTK4 (PyGObject 3.46+, GTK 4.6–4.22). **Zero deprecation warnings** at startup — legacy APIs replaced:
- `Gdk.Texture.new_for_pixbuf` → `Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))` (line 14224)
- `get_style_context()` + `lookup_color()` wrapped in `warnings.catch_warnings()` suppressing `DeprecationWarning` (line 51555) — no non-deprecated GTK4 API exists for resolving `@define-color` CSS values

### GTK4 lint

`tools/gtk4_lint.py` checks for deprecated GTK4 patterns (e.g. `set_markup` without markup safety, deprecated widget methods). Run it as a pre-commit check.

---

## Testing Architecture

### Test surface

| Suite | Where | GTK needed? | Coverage |
|---|---|---|---|---|
| Unit (default) | `tests/` | No | ~1,134 test functions in 40 files |
| Integration | `studyplan/testing/` | No | ~533 test functions in 47 files |
| GTK-dependent | `tests/test_studyplan_app_ollama.py` | Yes | ~322 test functions (parametrized → ~348 items) |
| Full suite | both | Yes | **~2,969 test items** (2,971 tests run, 1 skipped pre-existing, 1 pre-existing fail) |
| Domain reasoning | `tests/test_reasoning_engine.py`, `tests/test_domain_reasoning.py`, `tests/test_numerical_solver.py` | No | ~220 test functions |
| Provenance kernel | `studyplan/provenance/kernel/` | No | 22 test functions (P0 + P1) |
| Architectural invariants | `tests/test_architectural_invariants.py` | No | 17 test functions (I1–I14 + 3 P7) |

Current status: **2969 tests pass, 1 pre-existing fail (falsification tracker), 1 pre-existing skip**. Smoke test runs **32/32 KPI steps** at strict thresholds. **0 pyright errors** across all files. **0 GTK4 deprecation warnings** at startup.

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
