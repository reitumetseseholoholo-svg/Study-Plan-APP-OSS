# ACCA Study Assistant — Quick Start Cheat Sheet

## 60‑Second Setup

1. **Run the app**
   ```bash
   python studyplan_app.py
   ```
2. **Set exam date** (Ctrl+E)
3. **Set availability** (Coach Briefing → Set Availability)
4. **Import Study Hub PDF** (optional)
5. **Import Questions JSON** (optional)

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

## Data Locations

- Module data: `~/.config/studyplan/<module_id>/data.json`
- Questions: `~/.config/studyplan/<module_id>/questions.json`
- Preferences: `~/.config/studyplan/preferences.json`
- Weekly summary: `~/.config/studyplan/weekly_report.txt`

---

When in doubt: follow the **Coach Pick** and complete today’s mission checklist.
