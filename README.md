# Study Workbench

> **Your personal exam cockpit.** A self-contained desktop study environment for professional exam prep — combining an adaptive coach, AI tutor, FSRS-4.5 spaced repetition, Pomodoro focus timer, and semi-autonomous autopilot into one GTK4 application. Load any professional syllabus and the entire system adapts to it.

**First launch?** This is a native GTK4 app, not a web service — no cloud, no Docker, no database. Install, run `python studyplan_app.py`, and you're in. The app starts in under 50 ms before loading your data in the background, so you can start interacting immediately.

---

## Why this exists

Most exam prep tools are one-size-fits-all web apps that treat you like a passive content consumer. Study Workbench is different:

- **It runs on your machine.** No cloud dependency, no subscription, no data leaving your desk.
- **It learns your weak spots.** ML-assisted coaching identifies recall risk, difficulty gaps, and interval-blind spots — then adjusts the daily plan in real time.
- **It does the boring work for you.** The AI Cockpit (autopilot) can run focus sessions, quizzes, and reviews on a timer while you focus on studying.
- **It adapts to any exam.** Swap module JSON files to switch between ACCA F7, F8, F9, or your own custom syllabus.

---

## At a glance

```bash
python studyplan_app.py                    # launch — <50 ms to first paint
python studyplan_app.py 2026-12-01         # with exam date
python studyplan_app.py --perf-stats       # dump profiler report on close
STUDYPLAN_MODULE_TITLE="Your Module" python studyplan_app.py
```

---

## What's new (June 2026)

This app has been battle-hardened through **11 bug fixes**, **performance surgery**, **UI polish**, **cross-exam domain support**, and **6 new dashboard insight cards** to make it the smoothest exam prep experience on desktop:

- **Daily Recommended Plan** — priority-ordered checklist on the dashboard: must-review due today > overdue SRS > weak chapters (<40% competence) > due within 3 days. Hides when exam date or syllabus is unset.
- **Error Pattern Analysis** — surfaces your 10 weakest syllabus outcomes (accuracy <75%, attempts ≥2) with severity-colored badges. Outcome text resolved from the syllabus for actionable review targeting.
- **Focus Detective** — compares per-topic study time (14-day window) against competence. Flags under-studied weak topics and over-studied strong topics so you can rebalance your effort.
- **Auto-Summarizer** — per-chapter "Generate" button that calls your local LLM to produce a concise chapter summary. Stored per-chapter, refreshes the dashboard card when done.
- **Progress Predictions** — projects your finish date from 14-day daily study average vs. remaining minutes needed. Shows exam countdown and required daily pace.
- **Knowledge Graph** — Cairo-rendered DAG of chapter prerequisites, colored by competence (red <40%, yellow 40–70%, green >70%). Topological layout with curved bezier edges and arrowheads.
- **Cross-exam DomainRegistry** — the domain reasoning layer now supports any professional exam (ACCA, PMP, CFA, CPA, BAR, etc.) via a per-exam ``DomainRegistry``. ``reason_question(domain="pmp")`` works end-to-end with CPI, SPI, and EAC formulas. Adding a new exam is one ``declare_formula()`` call per formula.
- **Blazing fast startup** — deferred loading means the window appears in <50 ms; data, models, and questions load in the background. No more staring at a blank window.
- **Butter-smooth dashboard** — section reconciliation with tagged separators means charts and widgets are cached with digest-based change detection. No flash, no flicker, no redundant rebuilds. Separators no longer accumulate on refresh.
- **Rock-solid coach consistency** — the Coach Pick stays pinned once selected and doesn't flip-flop on every refresh. The coach briefing caches its 7+ engine queries with a digest key and skips them entirely when nothing changed.
- **AI tutor that doesn't lose your conversation** — mid-stream errors now preserve partial responses in your history. No more "where was I?"
- **Silent operation** — zero GTK4 deprecation warnings. Zero pyright errors. Zero flaky tests. **2058 tests** pass, **smoke test** runs 32/32 KPI steps at strict thresholds.
- **CPU-friendly** — the startup semantic warmup no longer spawns a thread per CPU core (capped to 2 workers for TF-IDF). The coach 2× render multiplier is eliminated. No unnecessary CPU bursts at idle.
- **Full-width heatmap** — the GitHub-style activity grid now spans the entire left panel. Every card fills its container.
- **Data integrity** — shared-reference bugs in question stats are fixed. Your data can't be silently corrupted through in-place mutation. The exam date parser no longer reports false-positive format corrections.
- **Domain reasoning durability** — 4 internal fixes: removed dead comma-replace in step matcher, documented intentional tolerance variance between intermediate steps and final answers, threaded original question text through multi-path fallback for better alternative detection, and replaced a silent ``except Exception: pass`` with a logged warning so template bugs no longer vanish silently.
- **Profiler report** — ``--perf-stats`` CLI flag surfaces real-time performance data at shutdown. Per-operation avg/p95/max latencies, error counts, alerts, and optimization recommendations — no more guessing which operations are slow.

---

## Core features

### 🧠 Adaptive Coach
- **Coach Briefing** — readiness score, mission checklist, pace status, daily target
- **Coach Pick** — "do this now" topic with reasoning + pace tip every session
- **Coach Next** — one-click "do the right thing now" action
- **Exam Readiness Index** — exam-aware pacing with retrieval quota bar
- **Outcome Mastery** — covered vs uncovered syllabus outcomes (global + per capability)
- **ML‑assisted decisions** — recall risk, difficulty mix, interval‑aware release
- **Confidence Drift chart** — top gap visualization between competence and mastery

### 📅 Daily Plan
- Coach-aligned topic list with **automatic** daily completion
- Plan stays consistent for the day (stable unless a module import refreshes it)
- Smart empty states that explain how to populate when no topics are available
- Interleave quiz: quick rotation to the next chapter in plan

### 🤖 AI Cockpit (Autopilot)
Runs autonomously in the background. Three modes:
- **Cockpit** — full autonomy, executes safe actions (default)
- **Assist** — notifies you after executing
- **Suggest** — proposes actions, waits for approval

Rate-limited to 6 actions per 10 minutes. Runs focus sessions, quizzes, drills, and reviews on your behalf.

### 🧪 AI Tutor (local)
- Interactive chat for explanations, practice, and Section C constructed-response problems
- Runs via Ollama (local GGUF models) or cloud gateway (OpenAI-compatible)
- RAG retrieval from syllabus outcomes and session history
- Domain-aware assessment with step-level diagnostics for ACCA FM concepts
- Response streaming, sanitization, telemetry

### 🎯 Spaced Repetition (FSRS-4.5)
- Per-card stability/difficulty model (default)
- SM-2 opt-in via `STUDYPLAN_SRS_ALGORITHM=sm2`
- Anti-repeat cooldown to prevent immediate re-asks
- Rust-accelerated question selection (`studyplan/rs/`) for SRS priority scoring

### ⏱ Pomodoro Focus Timer
- Focus timer, break timer, alerts, streaks
- Anti-cheat: credit only if ≥10 verified minutes
- Verified focus time with Hyprland window class tracking
- Auto-pause after idle threshold; resume on return
- At most 2 short credits per day for tiny sessions

### 📊 Dashboard & Insights
- Coach briefing with readiness score, pace, mission checklist
- **Daily Recommended Plan** — priority-ordered checklist: due today > overdue > weak chapters > due this week
- **Error Pattern Analysis** — weakest syllabus outcomes with severity badges
- **Focus Detective** — flags under-studied weak topics and over-studied strong topics
- **Auto-Summarizer** — per-chapter LLM-generated summaries
- **Progress Predictions** — projected finish date vs required daily pace
- **Knowledge Graph** — Cairo-rendered prerequisite DAG colored by competence
- Progress Over Time chart, Per-Topic Snapshot, Study Snapshot stats
- Weak vs Strong areas, Reviews Due Today, Leech Alerts
- Weekly Summary, Study Hub, Data Health
- Confidence Drift bar, Mastery Snapshot, Plan View

### 🎮 Gamification
- XP, levels, badges, daily quests
- Streak tracking
- Balanced reward rates (non-trivial, not inflated)

### 📈 ML Training (optional, in-app)
- **Application → Train ML Models…**
- Recall model (sklearn): recency weighting, class balancing, C search, calibration
- Difficulty model (sklearn): predicts question difficulty from stats
- Interval model (sklearn): predicts optimal review interval
- Promotion gates on Brier, ECE, AUC, and improvement over existing model
- Runtime safety: model load falls back gracefully when missing or invalid

### 🔬 Domain Reasoning Engine
Deterministic concept solver with **cross-exam support** via ``DomainRegistry``:
- **ACCA FM** — 30+ formulas (NPV, WACC, CAPM, IRR, payback, ARR, CCC, EOQ, gearing, ratios, and more)
- **PMP PoC** — CPI, SPI, EAC (proof of concept, end-to-end working)
- **Multi-path fallback** — alternative concepts for same output slot
- **Input gap analysis** — greedy fixed-point provider insertion
- **Weighted confidence scoring** — `avg_quality × success_rate`
- **Per-exam registry** — ``DomainRegistry`` maps concepts, templates, formulas, label aliases, and detection patterns. Add a new exam by calling ``declare_formula(registry=...)``
- Step-level diagnostics flow into tutor assessment and learner profile

---

## Performance architecture

Study Workbench is designed to be responsive even on modest hardware:

| Layer | Technology | What it accelerates |
|-------|-----------|-------------------|
| **Deferred loading** | `GLib.idle_add` | Engine initialises in <50 ms; data, models, and questions load in the background. No startup delay. |
| **Dashboard reconciliation** | Digest-checked section IDs | Expensive sections (coach briefing: 7+ engine queries) skip entirely when data hasn't changed. No flash or flicker on refresh. |
| **Rust/PyO3** | `studyplan_rs` (`studyplan/rs/`) | SRS question selection (sorting, diversity enforcement), batch overdue/retention scoring |
| **Cython** | `cosine_fast`, `tfidf_fast` | Cosine similarity, TF-IDF build/query for semantic outcome matching |
| **Python** | GTK4 + Cairo | All UI, charts, dashboard rendering |

**Thread safety**: TF-IDF warmup caps at 2 workers (CPU-bound tasks don't benefit from more). The coach card refresh no longer fires a redundant second render. No unnecessary CPU bursts at idle.

All native modules have pure-Python fallbacks with `try/except ImportError` — no hard dependency on a Rust toolchain or Cython.

---

## Requirements

**Required:**
- Python 3.11+ with **PyGObject (GTK4)** (`python3-gi`, `gir1.2-gtk-4.0`)

**Optional but recommended:**
- **Ollama** — local LLM for AI tutor (app degrades gracefully without it)
- **PyMuPDF (fitz)** — PDF score import (Study Hub reports)
- **sentence-transformers** — enhanced semantic outcome mapping (falls back to TF-IDF + Cython)
- **pytesseract + Pillow + numpy + scikit-image** — OCR preprocessing for noisy PDFs
- **matplotlib** — fallback chart renderer (Cairo charts are built-in)
- **hyprctl** (Hyprland) — focus tracking for Pomodoro verified minutes

---

## Environment variables

| Variable | Default | What it does |
|----------|---------|-------------|
| `STUDYPLAN_SRS_ALGORITHM` | `fsrs` | `sm2` or `legacy` to force SM-2 |
| `STUDYPLAN_LLM_GATEWAY_ENABLED` | `0` | `1` to route tutor through cloud API |
| `STUDYPLAN_LLM_GATEWAY_ENDPOINT` | — | OpenAI-compatible URL, e.g. `https://openrouter.ai/api/v1/...` |
| `STUDYPLAN_LLM_GATEWAY_API_KEY` | — | API key (also `OPENROUTER_API_KEY`) |
| `STUDYPLAN_LLM_GATEWAY_MODEL` | — | Model ID, e.g. `openrouter/google/gemini-2.5-flash` |
| `STUDYPLAN_LLM_GATEWAY_MODEL_FALLBACKS` | — | Comma-separated fallback model IDs |
| `STUDYPLAN_CLOUD_CONNECTIVITY_POLICY` | `auto` | `auto`, `force_online`, `force_offline` |
| `STUDYPLAN_MODULE_TITLE` | — | Override active module title at startup |
| `STUDYPLAN_CONFIG_HOME` | `~/.config/studyplan` | Override config directory |
| `STUDYPLAN_LLAMA_CPP_RAM_BUDGET_MB` | auto | Override RAM budget for model selection |

---

## Testing

```bash
pytest -q                    # 2058 tests, 0 regressions (1 pre-existing skip)
python -m py_compile studyplan_app.py studyplan_ai_tutor.py studyplan_engine.py
pyright studyplan_app.py studyplan_ai_tutor.py studyplan_engine.py studyplan tests
```

**Canonical CI gate** (`.github/workflows/linux-ci.yml`):
```bash
python tools/gtk4_lint.py
pyright studyplan_app.py studyplan_ai_tutor.py studyplan_engine.py studyplan tests
pytest -q
xvfb-run -a timeout 300s python studyplan_app.py --dialog-smoke-strict
```

**Strict smoke KPI thresholds**: 32/32 steps pass at coach_pick_consistency_rate ≥ 0.999, coach_only/integrity rates = 1.0

---

## Data locations

```
~/.config/studyplan/
├── <module_id>/data.json           # SRS state, progress, competence
├── <module_id>/questions.json      # question bank + stats
├── <module_id>/backups/*.bak       # automatic snapshots
├── preferences.json
├── streak.json
├── app.log
├── coach_debug.log
├── smoke_last.json
└── modules/*.json                  # module configs
```

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| **F1** | Show shortcuts |
| **F5** | Start Pomodoro |
| **F6** | Pause/Resume Pomodoro |
| **F7** | Stop Pomodoro |
| **F8** | Quick Quiz |
| **F9** | Toggle Focus Mode |
| **Ctrl+E** | Set exam date |
| **Ctrl+,** | Preferences |
| **Ctrl+M** | Toggle menu bar |
| **Ctrl+Q** | Quit |

---

## Project map

| File/Dir | Lines | Role |
|----------|-------|------|
| `studyplan_app.py` | ~56,700 | GTK4 UI — dashboard, quiz flow, Pomodoro, AI Cockpit, preferences |
| `studyplan_engine.py` | ~14,800 | Data model, SRS, daily plan, coach, ML inference, syllabus parsing |
| `studyplan_ai_tutor.py` | ~10,000 | Tutor session management, RAG retrieval, prompt assembly, streaming |
| `studyplan_app_kpi_routing.py` | ~600 | KPI thresholds and smoke/soak routing (GTK-independent) |
| `studyplan_app_path_utils.py` | ~200 | Path helpers for unit-testability without GTK |
| `studyplan/rs/` | Rust | PyO3-accelerated SRS selection (`select_srs_from_scored`, `batch_score_srs`) |
| `studyplan/cython/` | Cython | Accelerated cosine similarity + TF-IDF for semantic matching |
| `studyplan/domain_reasoning/` | 1.5k | Cross-exam domain reasoning engine — DomainRegistry, declarative formula DSL, evaluator, step matcher, diagnostics |
| `studyplan/numerical_solver.py` | 1.4k | Formula solver pipeline for numerical quiz answers |
| `studyplan/fsrs.py` | 558 | FSRS-4.5 scheduler with PyO3-ready pure math |
| `studyplan/` | lib | Config, contracts, coach FSM, cognitive state, AI routing, persistence |
| `modules/*.json` | data | Built-in module configs (ACCA F6–F9) + question banks |
| `tools/` | — | ML training scripts, GTK4 linter, tutor quality pipeline |
| `tests/` | — | 2058 tests (including 220 domain-reasoning tests) |

---

## Documentation

- [`USER_GUIDE.md`](USER_GUIDE.md) — end-user manual
- [`DEVELOPER_DOC.md`](DEVELOPER_DOC.md) — architecture, internals, extension guide
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute
- [`AGENTS.md`](AGENTS.md) — AI assistant context (architecture notes, conventions, pitfalls) — **essential reading for any developer** touching the dashboard, GTK4 patterns, or coach pipeline
- [`docs/LLM_TELEMETRY_SCHEMA.md`](docs/LLM_TELEMETRY_SCHEMA.md) — LLM telemetry fields + golden prompts
- [`tests/tutor_quality/README.md`](tests/tutor_quality/README.md) — tutor quality tooling
- [`scripts/README_module_chapters.md`](scripts/README_module_chapters.md) — module chapter tooling

---

## Module switching

1. **Module → Switch Module…**
2. Choose a module (or enter a new ID + title)
3. Click **Apply** → **Restart Now**

**Manage modules**: Module → Manage Modules… (opens module folders + list)
**Edit modules**: Module → Edit Module… (GUI editor for title, chapters, weights, flow, JSON)
**Import Syllabus PDF**: Module → Import Syllabus PDF… with RAG-improvement support

---

## Troubleshooting quick reference

| Symptom | Fix |
|---------|-----|
| Focus tracking unavailable | Install `hyprctl` (Hyprland) |
| Notifications not showing | Enable in Preferences |
| Charts missing | Install `matplotlib` (or use built-in Cairo charts) |
| PDF import not working | Install `PyMuPDF (fitz)` |
| Semantic map shows fallback | Install `sentence-transformers` |
| Data file won't load | **File → Recover from Snapshot…** (auto-recovery kicks in first) |
| `studyplan_rs` import error | Rust module not built — pure-Python fallback is active |

---

*Built with GTK4, PyO3, Cython, and a lot of coffee. Module-agnostic, local-first, free, and battle-hardened through 2058 tests, 32-step KPI smoke gates, and zero deprecation warnings.*
