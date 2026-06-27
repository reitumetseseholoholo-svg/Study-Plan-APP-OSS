# Study Workbench

> **Your personal exam cockpit.** A self-contained desktop study environment for professional exam prep — combining an adaptive coach, AI tutor, FSRS-4.5 spaced repetition, Pomodoro focus timer, and semi-autonomous autopilot into one GTK4 application. Load any professional syllabus and the entire system adapts to it.

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
python studyplan_app.py                    # launch the workbench
python studyplan_app.py 2026-12-01         # with exam date
STUDYPLAN_MODULE_TITLE="Your Module" python studyplan_app.py
```

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
Deterministic concept solver for ACCA FM with **220+ tests**:
- **10 FM concepts**: NPV, WACC, CAPM, IRR, payback, ARR, CCC, EOQ, gearing, and more
- Multi-path fallback: alternative concepts for same output slot
- Input gap analysis: greedy fixed-point provider insertion
- Weighted confidence scoring: `avg_quality × success_rate`
- Step-level diagnostics flow into tutor assessment and learner profile

---

## Performance architecture

Study Workbench is designed to be responsive even on modest hardware:

| Layer | Technology | What it accelerates |
|-------|-----------|-------------------|
| **Rust/PyO3** | `studyplan_rs` (`studyplan/rs/`) | SRS question selection (sorting, diversity enforcement), batch overdue/retention scoring |
| **Cython** | `cosine_fast`, `tfidf_fast` | Cosine similarity, TF-IDF build/query for semantic outcome matching |
| **Python** | GTK4 + Cairo | All UI, charts, dashboard rendering |

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
pytest -q                    # 1903 tests, 0 regressions
python -m py_compile studyplan_app.py studyplan_engine.py
pyright studyplan_app.py studyplan_engine.py tests/
```

**Canonical CI gate** (`.github/workflows/linux-ci.yml`):
```bash
python tools/gtk4_lint.py
pyright studyplan_app.py studyplan_engine.py studyplan tests
pytest -q
xvfb-run -a timeout 300s python studyplan_app.py --dialog-smoke-strict
```

**Strict smoke KPI thresholds**: coach_pick_consistency_rate ≥ 0.999, coach_only/integrity rates = 1.0

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
| `studyplan_app.py` | ~54,700 | GTK4 UI — dashboard, quiz flow, Pomodoro, AI Cockpit, preferences |
| `studyplan_engine.py` | ~20,000 | Data model, SRS, daily plan, coach, ML inference, syllabus parsing |
| `studyplan_ai_tutor.py` | ~10,000 | Tutor session management, RAG retrieval, prompt assembly, streaming |
| `studyplan/rs/` | Rust | PyO3-accelerated SRS selection (`select_srs_from_scored`, `batch_score_srs`) |
| `studyplan/cython/` | Cython | Accelerated cosine similarity + TF-IDF for semantic matching |
| `studyplan/domain_reasoning/` | 1k | Deterministic FM concept solver with multi-path fallback |
| `studyplan/numerical_solver.py` | 1.4k | Formula solver pipeline for numerical quiz answers |
| `studyplan/fsrs.py` | 558 | FSRS-4.5 scheduler with PyO3-ready pure math |
| `studyplan/` | lib | Config, contracts, coach FSM, cognitive state, AI routing, persistence |
| `modules/*.json` | data | Built-in module configs (ACCA F6–F9) + question banks |
| `tools/` | — | ML training scripts, GTK4 linter, tutor quality pipeline |
| `tests/` | — | 1903 tests (including 220 domain-reasoning tests) |

---

## Documentation

- [`USER_GUIDE.md`](USER_GUIDE.md) — end-user manual
- [`DEVELOPER_DOC.md`](DEVELOPER_DOC.md) — architecture, internals, extension guide
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute
- [`AGENTS.md`](AGENTS.md) — AI assistant context (architecture notes, conventions, pitfalls)
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

*Built with GTK4, PyO3, Cython, and a lot of coffee. Module-agnostic, local-first, and free.*
