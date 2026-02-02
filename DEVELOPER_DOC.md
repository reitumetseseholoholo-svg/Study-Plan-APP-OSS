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
- `completed_chapters`: set of chapters completed **today**
- `completed_chapters_date`: ISO date stamp for daily reset

### Key app (preferences) structures

- `action_time_log`: action → {seconds, sessions}
- `action_time_sessions`: list of per‑action sessions with topic + timestamp
- `focus_integrity_log`: verified vs raw minutes per day
- `session_quality_log`: per‑session quality ratings (good/okay/low)
- `last_hub_import_date`: ISO date used to gate quiz‑lag signals
- Daily plan cache: `_last_daily_plan` + `_last_daily_plan_date`

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

### Weekly summary export
- Auto‑writes `~/.config/studyplan/weekly_report.txt` once per ISO week.

### Quizzes and SRS
- `select_srs_questions` prioritizes overdue/low retention
- `update_srs` adjusts intervals and ease factor
- `flag_incorrect` adds must‑review items
- `record_difficulty` tracks repeated misses for “Hardest Concepts”

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
