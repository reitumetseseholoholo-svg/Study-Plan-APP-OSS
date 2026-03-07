# Study Assistant — Developer Notes

## Design principle: AI at the core, deterministic guardrails

This app is a **modern AI‑assisted study tutor**. Moving forward:

- **AI at the core** — Use AI/LLMs as the primary path for tutoring, explanations, question generation, gap analysis, syllabus parsing, feedback, and personalization. AI is not an add‑on; it drives the experience.
- **Deterministic guardrails** — Every AI touchpoint is wrapped in deterministic safety and structure:
  - **Schema and validation**: Parse and validate all model output (e.g. JSON schema, allowed fields, types, ranges). Never trust raw model text for critical behaviour.
  - **Fallbacks**: When AI is unavailable, fails, or returns invalid data, fall back to rule‑based or cached behaviour (e.g. F7 built‑in syllabus, deterministic practice service, regex syllabus parse).
  - **Sanity limits**: Enforce max lengths, retry caps, timeouts, and allowed value sets so the app never hangs or corrupts state on bad output.
  - **Stable structure**: Module config, chapters, and learning outcomes are the source of truth; AI augments (e.g. mapping outcomes to chapters, generating items) but does not replace canonical data without validation.

When adding or changing features, prefer an **AI‑first flow with a deterministic fallback**, and keep validation and structure explicit.

**Examples in the codebase:**

- **Tutor / practice**: `AICapableTutorPracticeService` uses AI when available and falls back to `DeterministicTutorPracticeService`; Section C and gap generation use LLM with strict JSON parsing and retries.
- **Syllabus**: Regex/rule-based parser first; "Improve with AI" uses `parse_syllabus_with_ai` with schema-validated JSON and chapter-list constraints; F7 has built-in outcome→chapter mapping when no AI result is used.
- **Assessment**: `_parse_judge_response` / `_extract_first_json_object` extract and validate JSON from model output; fallback prompts and retries if the response is invalid.
- **Recall / difficulty**: Optional ML models with metadata checks and heuristic fallbacks when the model is missing or mismatched.

## Prompt engineering design (3Es + fail-safe)

Major AI actions (Section C generation, MCQ/gap generation, syllabus parsing, tutor assessment, coach) should follow a shared prompt design so they are **economical**, **efficient**, **effective**, and **fail-safe**.

### 3Es

| E | Goal | Practice |
|---|------|----------|
| **Economy** | Minimal tokens; no waste. | One system-style block per action; schema as compact one-line where possible; truncate context (e.g. syllabus, snapshot) to what’s needed; avoid repeating the same rule in different words. |
| **Efficiency** | Fewer calls; less rework. | **Schema first**: show the exact JSON shape before rules or payload so the model can satisfy format in one shot. Single-shot generation where possible; retry only when parse fails. Reuse shared snippets (e.g. “JSON only, no markdown”) from a single module. |
| **Effectiveness** | Output meets the task. | Task-specific constraints (ACCA style, command verbs, mark totals); explicit allowed values (e.g. correct ∈ {A,B,C,D}); syllabus scope when relevant; one or two concrete “do not” rules (e.g. no placeholders, no trick questions). |

### Fail-safe

- **Layered prompts**: Primary prompt = strict schema + full rules. If parse fails, retry with a **relaxed** variant: same task, reduced scope (e.g. one question, shorter scenario) and a **suffix** that forces format: “Return only the JSON object. No markdown, no code block, no explanation.”
- **Validation gates**: Every response is parsed (e.g. extract JSON, strip markdown), then validated (required fields, types, allowed enums). Invalid output is not used; trigger relaxed retry or deterministic fallback.
- **Deterministic fallbacks**: Section C → default case; gap → 0 questions + quarantine; assessment → safe default marks; syllabus → built-in or regex. The app never depends on unvalidated model output for critical state.

### Structure (reusable)

Use a consistent order so the model and maintainers see the same shape every time:

1. **Role/task** (1–2 sentences): what to generate and in what style (e.g. “ACCA exam-type … as JSON only (no prose)”).
2. **Schema**: exact JSON shape (one line or minimal multi-line). Include field names and value types or enums.
3. **Rules**: short bullet list (constraints, do nots, syllabus note). Prefer 5–8 bullets; optional bullets can be appended (e.g. syllabus scope).
4. **Payload**: “Payload JSON:” + compact JSON (context, topic, counts, intelligence hints). Sort keys for stable caching if needed.
5. **Retry suffix** (only on relaxed retry): “Return only the JSON object. No markdown, no code block, no explanation. [Optional: Generate exactly one item.]”

Shared snippets (e.g. `JSON_ONLY_NO_MARKDOWN`, `RETRY_SUFFIX_ONE_ITEM`) live in `studyplan/ai/prompt_design.py` so all actions stay aligned and changes are one-place.

### Content and prompts (contributor guide)

- **Single source for AI prompts**: All schema-one-liners and JSON-only / retry phrases live in `studyplan/ai/prompt_design.py`. Section C, gap, syllabus, coach/autopilot, and assessment judge use them (or import and build from them) so wording stays consistent and one-place editable.
- **ACCA style**: When writing or editing prompts that generate exam-style content, use command verbs (Calculate, Evaluate, Recommend, Explain, etc.), explicit mark allocations, and syllabus-aligned wording. Learning outcomes and chapter titles should match module config; avoid placeholders in user-facing or model-facing text.
- **User-facing copy**: Error messages should be actionable (e.g. “Add a module (Application → Manage Modules)” not just “No module”). Empty states should suggest the next step (e.g. “Import questions to unlock quizzes”). Labels and tooltips should be concise; prefer “Import Syllabus PDF” over vague “Import data” where the action is syllabus-specific.
- **Validation and fallbacks**: Every AI output that drives behaviour is parsed and validated (schema, types, allowed enums). Invalid or empty responses trigger a relaxed retry (e.g. JSON-only suffix) or a deterministic fallback; see Major actions mapping below.

### Major actions mapping

| Action | Schema-first | Relaxed retry | Fallback |
|--------|--------------|---------------|----------|
| Section C | One case: chapter, scenario, requirements (3 parts), model_answer_outline, time_budget_minutes | Same prompt + retry suffix | Default Section C case |
| MCQ / gap | chapter + questions[] (question, options[4], correct, explanation) | Count=1 + retry suffix | Quarantine; return failure |
| Syllabus AI | outcomes[] (id, text, level, chapter) | — | Built-in F7 map or regex parse |
| Assessment (mark) | `ASSESSMENT_JUDGE_SCHEMA_ONE_LINE` + `JUDGE_JSON_ONLY` in prompt_design | Shorter prompt with `JUDGE_JSON_ONLY` | Safe default marks |

## Architecture overview

- **studyplan_app.py** — GTK4 UI and interaction layer
- **studyplan_engine.py** — data model, scheduling, SRS logic, parsing, persistence
- **modules/*.json** — module configs (chapters, weights, flow, questions)

The UI stays responsive and defers planning/scoring logic to the engine.

## Data and paths (one-page reference)

- **Config home**: All app and user data live under one directory. Default: `~/.config/studyplan`. Override with `STUDYPLAN_CONFIG_HOME`.
- **Module configs (where modules load from)**:
  - When running from source (repo `modules/` directory present), the app loads module JSON from **repo `modules/` first**, then from config `~/.config/studyplan/modules/`.
  - When repo `modules/` is absent (e.g. installed app), only `~/.config/studyplan/modules/` is used.
  - Engine: `_load_module_config()`; UI: `_get_available_modules()` — both use this order.
- **Per-module data** (under config home): `<module_id>/data.json`, `<module_id>/questions.json`.
- **Global app**: `preferences.json`, `streak.json`, `import_history.jsonl`, `app.log`, `syllabus_import_cache.json`, `coach_debug.log`, `smoke_last.json`, etc. (see Data model below).
- **Cache**: Performance cache and AI runtime cache are under config home (e.g. `ai_runtime_cache_v1.sqlite3`). Optional ML models: `recall_model.pkl`, `difficulty_model.pkl`, etc.
- **Backups**: Snapshots and backups use config home; retention and paths are engine constants.
- **First run**: Welcome tour shows config home and suggests Module → Manage Modules and Module → Import Syllabus PDF. Help → About shows the same data/module path summary.

## UX and accessibility

- **Keyboard shortcuts**: F1 opens the shortcuts dialog; F5–F9 and Ctrl+M/B/Q/E/, are wired for Pomodoro, menu, sidebar, quit, exam date, preferences. Help → Keyboard Shortcuts shows the full list.
- **High contrast**: Preferences → High contrast increases text and border contrast (CSS class `high-contrast` on the main window). Persisted in `preferences.json` as `ui_high_contrast`.
- **Reduce motion**: Preferences → Reduce motion/transitions shortens or disables animated transitions. Default can be set with `STUDYPLAN_UI_REDUCE_MOTION=1`. Persisted as `ui_reduce_motion`.
- **Tooltips**: Primary actions, status labels, and controls use `set_tooltip_text()` so hover reveals purpose or state. Keep tooltips short; use a second line only when needed.
- **Focus**: Critical flows (e.g. practice answer input, dialogs) call `grab_focus()` on the main interactive widget so keyboard users can continue without tabbing.
- **Contributors**: When adding buttons or status widgets, add a concise tooltip and ensure the widget has a clear label (GTK uses it for accessibility). Prefer descriptive action labels over icons-only where possible.

## Maintainability baseline

- **Clean caches:** From repo root, `bash scripts/clean.sh` removes `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `build`, `dist` (keeps `.venv` intact).
- **Action wiring is declarative**: GTK window actions are registered via `studyplan/app/action_registry.py`.
- Add new menu/window actions by editing the registry first, then adding handlers on `StudyPlanGUI`.
- Startup should not crash on missing handlers during refactors; missing bindings are tracked in
  `StudyPlanGUI._missing_ui_action_bindings`.
- **Migration rule**: new feature logic should land in `studyplan/` modules first, then be called
  from `studyplan_app.py` adapters.

### How to add a new AI action

1. **Prompt design (3Es + fail-safe)**: Follow the structure in *Prompt engineering design* above: role/task, schema, rules, payload, optional retry suffix. Reuse snippets from `studyplan/ai/prompt_design.py` so all actions stay economical, efficient, and effective with a deterministic fallback.
2. **Implementation**: Add the generation/parsing logic in the appropriate `studyplan/` service (e.g. practice, assessment, syllabus). Use schema validation and a fallback path; never rely on unvalidated model output for critical state.
3. **UI/menu**: Register the action in `studyplan/app/action_registry.py` and implement the handler on `StudyPlanGUI` in `studyplan_app.py`. Use the same prompt_design helpers if the action calls an LLM.

## Data model (engine)

Persisted per module:

- `~/.config/studyplan/<module_id>/data.json`
- `~/.config/studyplan/<module_id>/questions.json`

Global app data:

- `~/.config/studyplan/preferences.json`
- `~/.config/studyplan/streak.json`
- `~/.config/studyplan/import_history.jsonl`
- `~/.config/studyplan/app.log`
- `~/.config/studyplan/coach_debug.log` (coach pick audit)
- `~/.config/studyplan/syllabus_import_cache.json` (syllabus parse/import cache + metrics)
- `~/.config/studyplan/smoke_last.json` (latest smoke report with KPI gates)

### Key engine structures

- `competence`: chapter → score (0–100)
- `srs_data`: chapter → list of spaced‑repetition entries
- `pomodoro_log`: total minutes + per‑chapter minutes
- `study_days`: set of dates for streak tracking
- `must_review`: chapter → question index → due date
- `quiz_results`: chapter → last quiz percent
- `study_hub_stats`: parsed metrics from Study Hub PDFs
- `chapter_notes`: chapter → {note, reflection, updated}
- `difficulty_counts`: chapter → {question_index: count}
- `chapter_miss_streak`: chapter → consecutive misses today
- `chapter_miss_last_date`: chapter → ISO date of last miss update
- `hourly_quiz_stats`: hour → {attempts, correct}
- `completed_chapters`: set of chapters completed **today**
- `completed_chapters_date`: ISO date stamp for daily reset
- `concept_graph_meta` / `concept_nodes` / `concept_edges` / `outcome_concept_links`: persisted canonical concept graph
- `outcome_cluster_meta` / `outcome_clusters` / `outcome_cluster_edges`: persisted outcome cluster graph

### Key app (preferences) structures

- `action_time_log`: action → {seconds, sessions}
- `action_time_sessions`: list of per‑action sessions with topic + timestamp
- `focus_integrity_log`: verified vs raw minutes per day
- `session_quality_log`: per‑session quality ratings (good/okay/low)
- `last_hub_import_date`: ISO date used to gate quiz‑lag signals
- Daily plan cache: `_last_daily_plan` + `_last_daily_plan_date`

### Optional recall model (offline)

- Training script: `tools/train_recall_model.py`
- Scikit-learn trainer: `tools/train_recall_model_sklearn.py`
- Output: `~/.config/studyplan/recall_model.json`
- Output (sklearn): `~/.config/studyplan/recall_model.pkl`
- Runtime: engine loads model if present; otherwise falls back to heuristics.
- Runtime guard: sklearn recall model is rejected if metadata feature count mismatches engine features.
- Model features: `log1p_attempts`, `correct_rate`, `streak`, `log1p_avg_time_sec`, `log1p_days_since_last_seen`
- Recency weighting (sklearn trainer): exponential sample weights with `--recency_half_life_days` and `--recency_min_weight`.
- Trainer robustness: holdout-gated promotion, optional class balancing (`--class_weight`), and auto-`C` selection via `--c_grid`.
- Time-split validation: chronological split (`--time_split on`) and rolling backtest windows (`--time_backtest_windows`) gate promotion.
- Calibration: optional probability calibration (`--calibration`), plus ECE gate (`--max_ece`) before promotion.
- Promotion quality gates: optional AUC floor (`--min_auc`) and required ECE improvement over current model (`--min_improvement_ece`).

### Optional difficulty clustering (offline)

- Trainer: `tools/train_difficulty_model_sklearn.py`
- Output: `~/.config/studyplan/difficulty_model.pkl`
- Runtime: engine uses model if present; otherwise uses heuristic thresholds.
- Features: `miss_rate`, `log1p_avg_time_sec`, `streak_factor`

## Module system

### Config format
```json
{
  "title": "Your Module",
  "chapters": ["Topic 1", "Topic 2"],
  "chapter_flow": {"Topic 1": ["Topic 2"]},
  "importance_weights": {"Topic 1": 20, "Topic 2": 10},
  "target_total_hours": 180,
  "aliases": {"topic one": "Topic 1"},
  "questions": {
    "Topic 1": [
      {"question": "Q?", "options": ["A","B","C","D"], "correct": "A", "explanation": "..."}
    ]
  }
}
```

### Load order
1. Default engine config
2. Optional module JSON override
3. Module‑scoped data paths resolve (legacy fallback if needed)

### Syllabus intelligence schema (optional)

Modules can include:

- `capabilities`: capability letter to title
- `syllabus_structure`: per chapter syllabus details
  - `subtopics`
  - `learning_outcomes` (`id`, `text`, `level`)
  - `intellectual_level_mix` (`level_1`, `level_2`, `level_3`)
  - `outcome_count`
- `syllabus_meta`
  - `source_pdf`
  - `exam_code`
  - `effective_window`
  - `parsed_at`
  - `parse_confidence`

### Syllabus PDF import pipeline

Engine APIs:

- `parse_syllabus_pdf_text(pdf_text)`
- `build_module_config_from_syllabus(parsed, base_config=None)`
- `validate_syllabus_config(config)`
- `import_syllabus_from_pdf_text(pdf_text, module_id=None, *, force_confidence=False)`
  - If `force_confidence=True`, diagnostics and parsed confidence are set to 1.0 (e.g. after user verification).

App flow:

- `Module -> Import Syllabus PDF...`
- PDF text extraction order:
  - native text extraction
  - optional skimage + Tesseract preprocessing OCR
  - PyMuPDF OCR fallback
- Parser produces a draft config plus diagnostics.
- Review wizard opens first (confidence, warnings, preserve question bank toggle).
- Module Editor is prefilled only after explicit review confirmation.
- User must explicitly save; import does not write module files automatically.
- Tools & Data exposes:
  - `View Syllabus Cache Stats`
  - `Clear Syllabus Cache`

Parser rules:

- Main capabilities parsed from section `2. Main capabilities`
- Chapter structure parsed from section `4. The syllabus`
- Learning outcomes parsed from section `5. Detailed study guide`
- Section matching uses the **last** heading occurrence to avoid table-of-contents false starts.
- Confidence is computed from capability/chapter/outcome extraction ratios.
- Low confidence still returns a draft with warnings.

## Key flows

### Pomodoro + focus verification
- `on_pomodoro_start` starts timer + focus tracking
- `hyprctl activewindow -j` is polled; allowlist uses class matching
- Verified minutes control credit + XP
- Minimum credit + short‑session limits prevent gaming

### Daily plan completion
- Daily plan items are marked complete **automatically** on counted Pomodoro or completed quiz session.
- `StudyPlanEngine.mark_completed_today` updates the daily completion set.
- Plan is **stable within a day** unless a Study Hub import triggers a refresh.

### Coach‑only mode
- UI locks topic selection to the coach pick.
- Action handlers call `_ensure_coach_selection()` to enforce coach topic before starting a Pomodoro or quiz.
- “Coach Next” uses the coach pick and chooses the best next action (quiz vs focus).

### Coach Briefing signals
- Retrieval quota bar + exam‑aware penalties
- Confidence drift warning (competence vs mastery/quiz lag)
- Topic saturation warning (over‑focusing)
- Focus integrity warnings (verified vs raw minutes)
- Coach ops notes (miss‑cooldown, off‑peak hours)

### ML‑assisted coach tie‑ins
- Planning and recommendations incorporate ML recall‑risk when models exist.
- Sticky‑coach release uses interval model confidence when available.
- Difficulty mix can tighten caps on long runs for “hard” chapters.
- Syllabus intelligence augments chapter urgency:
  - depth boost from `outcome_count`
  - pressure boost from level mix concentration (L2/L3)

### Outcome-centric planning and routing
- Outcome progress is tracked per chapter in `outcome_stats`.
- Quiz answer confirmation records outcome events via question-to-outcome mapping.
- `select_srs_questions` and `select_due_review_questions` prioritize questions linked to uncovered outcomes.
- `get_daily_plan` enforces at least one chapter from under-covered capabilities when available.

### Semantic graph layer
- `build_canonical_concept_graph` builds a stable concept hierarchy from syllabus outcomes/subtopics.
- `build_outcome_cluster_graph` builds stable cluster IDs (semantic mode with lexical fallback).
- Semantic status is surfaced in UI diagnostics (ready/pending/fallback, model name, threshold, cache size).
- Review-mode isolation remains intact: due review selection is not replaced by semantic interleave.

### Semantic drift KPI
- Engine API:
  - `get_semantic_drift_kpi`
  - `get_semantic_drift_kpi_by_chapter`
  - `get_semantic_drift_alerts`
- Coach consumes drift alerts for intervention text when competence diverges from outcome-level mastery.
- Drift logic is additive and keeps SRS as the timing control system.

### Weekly summary export
- Auto‑writes `~/.config/studyplan/weekly_report.txt` once per ISO week.

### Quizzes and SRS
- `select_srs_questions` prioritizes overdue/low retention
- `update_srs` adjusts intervals and ease factor
- `flag_incorrect` adds must‑review items
- `record_difficulty` tracks repeated misses for “Hardest Concepts”

### Runtime stability guardrails
- Avoid calling `update_dashboard()` inside per-question quiz confirmation paths.
- Keep per-answer refreshes lightweight (`_update_coach_pick_card`, `update_study_room_card`) and refresh full dashboard once at quiz completion.
- In file chooser helpers, prefer `get_file()` first and isolate legacy chooser calls to avoid noisy GTK deprecation warnings.
- Coach UI refreshes are debounced (study room, plan, recommendations) to reduce flicker/jank.
- `Data Health Check` runs `_normalize_loaded_data()` + migrations and appends to `migration.log`.
- Optional OCR preprocessing is guarded so missing dependencies never break imports.
- On primary data load failure, engine attempts automatic recovery from latest backup snapshot.

### Snapshot recovery UX
- File menu includes:
  - `Import Data Snapshot…`
  - `Recover from Snapshot…`
  - `Restore Latest Snapshot…`
- Startup banner is shown when auto-recovery has been applied.

### Syllabus cache behavior
- Parse/import results are cached in memory and on disk.
- Cache hit/miss metrics are tracked (`parse_hits`, `parse_misses`, `import_hits`, `import_misses`).
- Metrics are persisted with disk cache payload and restored on load.
- `clear_syllabus_import_cache()` resets cache entries and metrics.

### In-app question generation (daily cap + tutor discretion)
- **Cap**: `Config.AUTO_QUESTION_GENERATION_CAP` (default 1500) is the total question (card) count per module at which automatic daily generation stops.
- **Daily auto-generation**: While total questions &lt; cap, a one-shot timer (e.g. 90s after startup) runs once per calendar day: it generates one batch of gap questions (e.g. for coach pick or first chapter), updates `last_auto_question_generation_date` in preferences, and does not run again until the next calendar day.
- **Daily budget**: `Config.AUTO_QUESTION_GENERATION_DAILY_BUDGET` (default 30) caps how many questions are generated per day during the auto phase; the first run of the day uses a fraction of that (e.g. 3–10) so the app stays responsive.
- **After cap**: Once total ≥ cap, generation is **on demand only**: (1) **User demand**: the “Generate gaps” button always runs generation. (2) **Tutor discretion**: the autopilot may suggest `gap_drill_generate` only when `gap_generation_recommended` is true—i.e. when the current topic or coach pick has very few questions (&lt; 5). The executor blocks autopilot-triggered generation when at/above cap unless `_tutor_deems_gap_generation_necessary(snapshot)` is true.
- **Snapshot**: Autopilot snapshot includes `total_question_count`, `question_generation_cap`, and `gap_generation_recommended` so the model can prefer gap generation when recommended.

- **Tutor past-days memory**: The tutor has a short “recent activity” log so it can refer to past days (e.g. “5 days ago we were on topic X”). After each tutor exchange, `_update_ai_tutor_working_memory` calls `_append_tutor_recent_activity(topic, summary)` to add or update today’s entry (topic + one-line summary from next_step or intent). Up to 14 days are kept in `tutor_recent_activity` (preferences key `tutor_recent_activity`). The local AI context block includes a “Past days: …” line (e.g. “3d ago: Chapter 5 — do a short quiz”) when building the packet; this section is droppable under context budget (after confidence, before action mix).

### Study Hub import
- PDF parsing updates quiz/practice stats and competence
- Import history logged to `import_history.jsonl`

## UI structure

- Left panel: coach pick, plan list, study room, Pomodoro, tools
- Right panel: Coach Briefing + cards/expanders
- Coach‑only view hides plan list and enforces coach topic

## Testing

```bash
pytest -q
python -m py_compile studyplan_app.py studyplan_engine.py
pyright studyplan_app.py studyplan_engine.py tests/test_studyplan_engine.py
```

Dialog smoke modes:

- **Local:** Run when no other Study Assistant instance is running (or remove `~/.config/studyplan/app_instance.lock` if the window was force-closed). For headless/CI, use a virtual display: `xvfb-run -a python studyplan_app.py --dialog-smoke-strict`.
- **CI:** `.github/workflows/linux-ci.yml` runs strict dialog smoke under `xvfb-run` with a 180s timeout and fails the build on non-zero exit.

```bash
timeout 40s python studyplan_app.py --dialog-smoke-test
timeout 40s python studyplan_app.py --dialog-smoke-strict
```

Strict smoke behavior:

- `--dialog-smoke-test` is exploratory and always exits 0 unless process-level failures occur.
- `--dialog-smoke-strict` exits non-zero when:
  - smoke report status is not `passed`
  - KPI thresholds fail
  - report file is missing/unreadable

Smoke report shape highlights (`~/.config/studyplan/smoke_last.json`):

- `status`, `reason`
- `steps[]` with per-step `ok/error`
- `kpi` (rates + counters)
- `kpi_thresholds`
- `kpi_failures`
- `diagnostics.top_mismatch_sample`
- `diagnostics.coach_sync_retry_count`
- `diagnostics.last_coach_sync_origin`

Current strict KPI thresholds:

- `coach_pick_consistency_rate >= 0.999`
- `coach_only_toggle_integrity_rate == 1.0`
- `coach_next_burst_integrity_rate == 1.0`

## Extending

- Add a module JSON under `~/.config/studyplan/modules/` or `modules/` in repo
- Update the module editor to include question editing if needed
- Keep GTK4 API usage (avoid Gtk3‑only methods)

## Style + UX notes

- System theme respected by default (nwg‑look)
- Carded layout for scanability
- Avoid heavy layout changes unless matching established style

---

If you want a full technical spec or JSON schema validation, add a `tools/` script and document it here.

## Latest Validation Snapshot (2026-03-08)

- `pyright` from repo root: `0 errors, 0 warnings, 0 informations`
- Smoke gate: `pytest -q studyplan/testing/test_dialog_smoke.py` passed
- Tutor/Ollama regression suite: `pytest -q tests/test_studyplan_app_ollama.py` passed
