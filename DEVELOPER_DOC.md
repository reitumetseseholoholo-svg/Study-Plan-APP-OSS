# ACCA Study Assistant — Developer Notes

## Architecture overview

- **studyplan_app.py** — GTK4 UI and interaction layer
- **studyplan_engine.py** — data model, scheduling, SRS logic, parsing, persistence
- **modules/*.json** — module configs (chapters, weights, flow, questions)

The UI stays responsive and defers planning/scoring logic to the engine.

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
  "title": "ACCA FM",
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
1. Default engine config (FM)
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
- `import_syllabus_from_pdf_text(pdf_text, module_id=None)`

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

### Syllabus cache behavior
- Parse/import results are cached in memory and on disk.
- Cache hit/miss metrics are tracked (`parse_hits`, `parse_misses`, `import_hits`, `import_misses`).
- Metrics are persisted with disk cache payload and restored on load.
- `clear_syllabus_import_cache()` resets cache entries and metrics.

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
```

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
