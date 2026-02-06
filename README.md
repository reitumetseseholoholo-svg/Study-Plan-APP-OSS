# ACCA Study Assistant (FM default)

A focused ACCA study coach built around Pomodoro discipline, SRS‑based quizzes, and a mission‑driven dashboard. Defaults to ACCA FM/F9 unless you switch modules.

## Quick start

```bash
python studyplan_app.py
# or with exam date
python studyplan_app.py 2026-12-01
```

Optional module override (env vars):

```bash
STUDYPLAN_MODULE_ID=acca_f9 STUDYPLAN_MODULE_TITLE="ACCA FM" python studyplan_app.py
```

## Requirements

- Python 3 with **PyGObject (GTK4)**
- Optional:
  - **PyMuPDF (fitz)** for PDF score import
  - **matplotlib** for charts
  - **hyprctl** (Hyprland) for focus tracking
  - **hypridle** (optional hook for idle file)

## Core features

- **Coach Briefing**: readiness score, mission checklist, pace status, daily target
- **Exam Readiness Index** + retrieval quota bar (exam‑aware pacing)
- **Coach Pick**: single “do this now” topic with reasons + pace tip
- **Coach Next**: one‑click “do the right thing now” action
- **Study Room**: next action, mission progress, quick actions
- **Pomodoro**: focus timer, break timer, alerts, streaks
- **Focus verification**: Hyprland allowlist + idle detection for verified minutes
- **Quizzes**: SRS‑weighted questions, streak bonuses, weak‑area drill
- **Responsive quiz flow**: lightweight per‑question updates, full dashboard refresh on quiz completion
- **Gamification**: XP, levels, badges, daily quests
- **Daily plan**: coach‑aligned topic list with **automatic** daily completion
- **Plan stability**: stays consistent for the day unless a major import refreshes it
- **Smart empty states**: Daily plan explains how to populate when no topics are available
- **Insights**: mastery stats, weak/strong areas, reviews & due items
- **Reflections**: quick reflections + confidence notes (Review Reflections…)
- **Hardest Concepts**: tracks repeated misses per chapter
- **Time Analytics**: time per action + per‑topic leaderboards
- **Balance checks**: topic saturation + confidence drift (competence vs mastery/quiz)
- **Confidence Drift chart**: top gap visualization
- **Data Health Check**: one‑click normalization + health summary in Tools
- **Weekly summary export**: auto writes `~/.config/studyplan/weekly_report.txt`
- **Study Hub import**: parse ACCA Study Hub PDFs (practice/quiz reports)
- **Modules**: switch or edit ACCA modules via JSON configs

## Keyboard shortcuts

- **F1** Show shortcuts
- **F5** Start Pomodoro
- **F6** Pause/Resume Pomodoro
- **F7** Stop Pomodoro
- **F8** Quick Quiz
- **F9** Toggle Focus Mode
- **Ctrl+E** Set exam date
- **Ctrl+,** Preferences
- **Ctrl+M** Toggle menu bar
- **Ctrl+Q** Quit

## Coach-only mode

- Toggles in Preferences or the plan header
- Hides the daily plan list and **forces coach topic selection**
- Badge is clickable to exit coach‑only quickly

## Data locations

Data is stored per module (defaults to `acca_f9`):

- `~/.config/studyplan/<module_id>/data.json`
- `~/.config/studyplan/<module_id>/questions.json`

Global app files:

- `~/.config/studyplan/preferences.json`
- `~/.config/studyplan/streak.json`
- `~/.config/studyplan/import_history.jsonl`
- `~/.config/studyplan/app.log`
- `~/.config/studyplan/coach_debug.log` (coach pick audit)
- `~/.config/studyplan/modules/*.json` (module configs)

## Module switching

1. **Module → Switch Module…**
2. Choose a module (or enter a new ID + title)
3. Click **Apply** → **Restart Now**

**Manage modules**: Module → Manage Modules… (opens module folders + list)

**Edit modules**: Module → Edit Module… (GUI editor for title/chapters/weights/flow/JSON)

### Module JSON format

```json
{
  "title": "ACCA FM",
  "chapters": ["Topic 1", "Topic 2"],
  "chapter_flow": {
    "Topic 1": ["Topic 2"]
  },
  "importance_weights": {
    "Topic 1": 20,
    "Topic 2": 10
  },
  "target_total_hours": 180,
  "aliases": {
    "topic one": "Topic 1"
  },
  "questions": {
    "Topic 1": [
      {
        "question": "Example?",
        "options": ["A", "B", "C", "D"],
        "correct": "A",
        "explanation": "Why A"
      }
    ]
  }
}
```

## Focus tracking (Hyprland)

- Uses `hyprctl activewindow -j` and **class matching**
- Configure allowlist via **Edit → Focus Allowlist…** or Preferences
- Auto‑pause after idle threshold off allowed apps; resume on return

## Pomodoro anti‑cheat

- **Credit only if ≥ 10 verified minutes**
- Rewards based on **verified focus time**
- At most **2 short credits/day** for tiny sessions

## Study Hub PDF import

Use **Import PDF Scores** to ingest ACCA Study Hub reports (practice/quiz). The app parses chapter and category performance to update competence and analytics.

## Tests

```bash
pytest -q
```

## Troubleshooting

- **Focus tracking unavailable**: ensure `hyprctl` is installed
- **Notifications not showing**: enable desktop notifications in Preferences
- **Charts missing**: install `matplotlib`
- **PDF import missing**: install `PyMuPDF (fitz)`

## Recent stability updates (Feb 2026)

- Fixed a quiz runtime issue where full dashboard rebuilds could trigger high CPU/jank during answer confirmation.
- Added defensive quiz selection/history handling to reduce repetitive card loops and corrupted history impact.
- Hardened file chooser path handling to avoid noisy GTK deprecation warnings in normal use.

## Files

- `studyplan_app.py` — GTK4 app UI
- `studyplan_engine.py` — engine + data model
- `modules/*.json` — module configs

---

For detailed usage, see `USER_GUIDE.md`. For internals, see `DEVELOPER_DOC.md`.
