# Study Assistant — Quick Start Cheat Sheet

For a complete list of capabilities, see `FEATURES.md`.

## 60‑Second Setup

1. **Run the app**
   ```bash
   python studyplan_app.py
   ```
2. **Set exam date** (Ctrl+E)
3. **Set availability** (Coach Briefing → Set Availability)
4. **Import Study Hub PDF** (optional)
5. **Import Questions JSON** (optional)
6. If startup data fails, use **File → Recover from Snapshot…**

## Daily Flow (Recommended)

1) **Coach Pick** → click it (or use Focus Now)
2) **Coach Next** → one‑click next best action
3) **Pomodoro** → Focus 25m
4) **Quick Quiz** → short quiz on coach topic
5) **Clear Must‑Review**

## Coach‑Only Mode

- Hide the daily plan list and lock topic selection to the coach pick.
- Toggle in **Preferences** or from the **Coach‑only** button in the plan header.
- Click the **Coach‑only badge** to exit.

## Most Used Buttons

- **Focus Now** → starts Pomodoro on coach topic
- **Quick Quiz** → short quiz on coach topic
- **Weak Drill** → targets weakest chapter
- **AI tutor (Ollama)** → local LLM explanations and quick drills
- **Run Data Health Check** → normalizes data + shows health summary
- **Train ML Models** → runs recall/difficulty/interval trainers

## Pomodoro Rules

- Credit only if **≥ 10 verified minutes**
- Breaks auto‑start; timer shows **Break ends at HH:MM**

## Shortcuts

- **F5** Start Pomodoro
- **F6** Pause/Resume
- **F7** Stop
- **F8** Quick Quiz
- **F9** Focus Mode
- **Ctrl+E** Exam date
- **Ctrl+,** Preferences
- **Ctrl+Q** Quit

## Outcome coverage

- **Module → View Module Metadata** shows how many questions are linked to syllabus outcomes (e.g. "Questions with resolved outcome: N / M"). Use it to see whether your question bank is driving Outcome Mastery.

## Data Locations

All paths are under config home (default `~/.config/studyplan`; override with `STUDYPLAN_CONFIG_HOME`):

- Module data: `<config_home>/<module_id>/data.json`
- Questions: `<config_home>/<module_id>/questions.json`
- Preferences: `<config_home>/preferences.json`
- **Module → View Module Metadata**: paths plus outcome coverage (questions linked to outcomes).
- Weekly summary: `<config_home>/weekly_report.txt`
- Smoke report: `<config_home>/smoke_last.json`
- Soak report: `<config_home>/soak_last.json`
- Backups: `<config_home>/<module_id>/backups/*.bak`

## Quick Stability Gate

```bash
timeout 40s python studyplan_app.py --dialog-smoke-strict
```

This runs dialog smoke with coach-only stress and fails fast if KPI thresholds are not met. For an isolated run (separate lock and report), use `STUDYPLAN_CONFIG_HOME=$(mktemp -d)` before the command; strict mode reads the report from that config home.

## Quick fixes

- Semantic line says `fallback`:
  ensure your launcher points to Python environment with `sentence-transformers`.
- Startup mentions auto-recovery:
  open **File → Recover from Snapshot…** to choose a specific backup if needed.

---

When in doubt: follow the **Coach Pick** and complete today’s mission checklist.
