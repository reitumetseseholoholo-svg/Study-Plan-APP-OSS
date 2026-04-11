# Study Assistant — Feature Inventory

This document is the single reference for the current user-facing feature set.
For setup, use `README.md` and `QUICK_START.md`. For deeper workflows, use `USER_GUIDE.md`.

## 1) Planning and coaching

- Module-aware planning with chapter-weighted priorities
- Coach Pick with rationale (weakness, due reviews, pacing pressure)
- Coach Briefing with mission checklist and pace status
- Exam Readiness Index and retrieval quota tracking
- Coach Next one-click action execution
- Daily plan with stability rules and auto-completion
- Coach-only mode to lock actions to coach guidance
- Study Room quick actions: Focus, Quiz, Drill weak, Interleave

## 2) Focus and time management

- Pomodoro timer with start/pause/stop and break automation
- Verified focus-minute tracking (supports Hyprland active-window + idle checks)
- Focus allowlist editor for verification scope
- Session quality prompts (good/okay/low) for post-session feedback
- Action-level time analytics and per-topic leaderboards

## 3) Quiz, SRS, and mastery

- SRS-driven quiz scheduling and weak-area prioritization
- Must-review queue from incorrect responses
- Weak drill and interleave quiz flows
- Leech remediation for repeatedly-missed questions
- Hardest Concepts tracking by chapter
- Competence, quiz, and outcome mastery synthesis
- Outcome coverage at chapter and capability level

## 4) AI Tutor and practice loop (local Ollama)

- In-app AI Tutor chat (workspace and dialog entry points)
- Streaming responses with Stop/cancel handling
- Model refresh and optional auto-selection
- Prompt UX: quick prompts, outcome prompts, concise mode, exam-technique mode
- Chat controls: new chat, clear prompt, copy transcript, copy last, follow/jump latest
- Gap-question generation from tutor context
- Section C / constructed-response practice integration
- Practice Loop panel with plan/check cycle, retry variant, hints, and “use in prompt”
- Action console execution for suggested tutor actions
- Transfer checks with brittleness/risk feedback
- Helpfulness feedback with follow-up prompt insertion
- Tutor trust details and grounded-feedback messaging

## 5) AI Coach

- AI Coach recommendation generation (model-backed with fallback)
- Recommendation review and one-click apply
- Dedicated Coach workspace plus modal detailed view
- Coach state reflected into dashboard and Study Room

## 6) Semantic routing and retrieval intelligence

- Semantic routing toggle with deterministic fallback
- Canonical concept graph construction and persistence
- Outcome cluster graph (lexical/semantic method)
- Semantic Drift KPI (status, flagged chapters, thresholds)
- Confidence Drift chart (top gap visualization)
- Performance counters for routing/cache behavior

## 7) Tutor RAG (PDF knowledge sources)

- Add Tutor RAG PDF sources from UI/menu
- Per-file size validation and source list management
- Lazy embedding generation on first semantic retrieval
- Runtime cache-backed retrieval and source-mix telemetry
- Diagnostics visibility for coverage, hits/misses, and retrieval mode

## 8) Imports, exports, and recovery

- Study Hub PDF score import
- OCR pipeline with fallbacks (native text, optional Tesseract/skimage, PyMuPDF OCR)
- AI questions JSON import
- Data snapshot import and restore flows
- Auto-recovery from latest snapshot on load failures
- Manual “Recover from Snapshot” and “Restore Latest Snapshot”
- Export data CSV, import template CSV, and question stats CSV
- Weekly report generation and viewer

## 9) Module system and syllabus intelligence

- Switch Module workflow with restart handoff
- Manage Modules view and folder access
- Module Editor for ID/title/chapters/flow/weights/config
- Syllabus PDF import with draft-first review wizard
- Import Syllabus (JSON) to seed syllabus_meta without PDF or AI
- Outcome coverage diagnostics (Module → View Module Metadata: questions with resolved outcome, explicit outcome_ids)
- Low-confidence parse acknowledgement gate
- Preserve-question-bank control during syllabus draft creation
- Cache tooling for syllabus parse/import stats and reset
- Built-in module support for ACCA variants (including F6/F7/F8/F9 patterns)

## 10) Workbench and diagnostics surfaces

- Modern tabbed workspace with Dashboard, Tutor, Coach, Insights, Settings
- Insights workspace diagnostics for study-hub ingestion, concept/cluster counts, drift, cache/perf, and Tutor telemetry
- RAG diagnostics for source count, chunk/doc cache, and embedding coverage
- Settings workspace controls for local AI, auto-select model, semantic routing, tutor autopilot, notifications, modern UI, sidebar, and reduce motion
- Tutor autonomy mode options: `suggest`, `assist`, `cockpit`

## 11) Reliability and maintenance tooling

- Run Data Health Check action
- View health log and app logs
- Stability Repair action (runtime refresh pipeline)
- Close Transient Dialogs utility
- Performance cache view/clear actions
- Backups and snapshot retention in module data directories

## 12) UI and accessibility

- Keyboard shortcuts for core actions
- Focus mode toggle
- Sidebar toggle and adaptive auto-hide policies
- Reduce-motion and high-contrast support
- Notification controls
- Single-line status protections and tooltip guidance across key controls

## 13) Optional ML features

- Train ML models from UI (recall/difficulty/interval)
- Runtime guarded loading with fallback when models are absent/invalid
- Promotion-quality gates in trainer tooling

## 14) Testing and quality gates

- Pytest suite with GTK-independent and full GTK-enabled coverage modes
- Dialog smoke test modes (`--dialog-smoke-test`, `--dialog-smoke-strict`)
- Strict KPI gate checks for coach-related integrity metrics

## Notes

- Some capabilities depend on optional packages or external tools (`matplotlib`, `sentence-transformers`, `PyMuPDF`, `tesseract`, `hyprctl`, Ollama runtime).
- When optional dependencies are unavailable, the app is designed to degrade gracefully with deterministic fallback behavior.

### Fallback behavior (feature → when unavailable)

| Feature | When unavailable / fallback |
|--------|-----------------------------|
| Semantic routing (concept/outcome maps) | Deterministic chapter/alias matching; status shows reason (e.g. "sentence-transformers unavailable", "model load failed", "circuit active"). |
| RAG (Tutor PDF sources) | No snippets injected; tutor uses syllabus/context only. Diagnostics show source count and retrieval mode. |
| Recall ML model | Heuristic recall risk; status shows "blocked" + reason if model missing or metadata mismatch. |
| Difficulty / interval ML models | Heuristic thresholds; no user-facing message unless trainer is run. |
| OCR (PDF import) | Native text extraction first; then optional Tesseract/skimage; then PyMuPDF OCR. |
| Syllabus AI (improve with AI) | Built-in or regex parse per module (e.g. F7/F9). |
| AI Tutor (Ollama) | Dialog and practice loop unavailable; coach and quizzes still work. |
| Focus verification (Hyprland) | Raw minutes only; no verification. |
| Charts (matplotlib) | Chart cards hidden or placeholder. |
