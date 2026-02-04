# ACCA Study Assistant — User Guide

This guide focuses on day‑to‑day use as a disciplined study coach.

## 1) First run

1. **Choose module** (default is ACCA FM/F9).
2. **Set exam date** and **availability**.
3. (Optional) **Import Study Hub scores** and **question JSON**.
4. Start your mission.

Re‑open the tour anytime via **Help → First‑Run Tour…**

## 2) Daily flow (recommended)

### A. Coach Pick (left panel)
- The Coach Pick is your “do this now” topic.
- It explains *why* (weak area, due reviews, pace, etc.).
- Click it to focus that topic.

### B. Mission checklist (Coach Briefing)
Complete in order:
1) **Focus 1x Pomodoro**
2) **Quiz target questions**
3) **Clear must‑review**

Coach Briefing also shows:
- **Exam Readiness Index** and **retrieval quota**
- **Balance checks** (topic saturation or confidence drift)
- **Focus integrity** (verified vs raw minutes)

### C. Study Room (Now)
- **Focus now (25m)** starts a Pomodoro on the coach topic.
- **Quick quiz** runs a short quiz on the coach topic.
- **Weak drill** focuses your weakest area.
- **Coach Next** auto‑selects the coach pick and starts the best next action.

### D. Daily plan (optional)
- A list of suggested topics for the day.
- **Auto‑completion**: topics are marked done after a counted Pomodoro or completed quiz session.
- If you prefer, enable **Coach‑only view** to hide the plan list entirely.
- Plan is **stable within a day** unless a major import refreshes it.
- If the list is empty, the app shows a short tip (load a module, set an exam date, or import questions).

## 3) Coach‑only view

When coach‑only is enabled:
- The plan list is hidden.
- The topic dropdown is locked to the coach’s pick.
- Any action (Pomodoro/Quiz/Drill) uses the coach topic.

Toggle in **Preferences** or from the **Coach‑only** button in the plan header. The badge is clickable to exit.

## 4) Pomodoro + breaks

- **Start / Pause / Stop** from the left panel.
- Breaks are automatic; the timer shows **“Break ends at HH:MM”**.
- Short vs long breaks are configurable in Preferences.
- Breaks can be skipped up to the configured limit.

### Focus verification
- The app credits Pomodoros based on **verified minutes**, not raw time.
- Verified time uses Hyprland allowlist + idle time.
- After a counted Pomodoro, you may get a **1‑tap session quality prompt** (Good/Okay/Low).

## 5) Quizzes and reviews

- Quizzes use spaced repetition to prioritize weak/overdue questions.
- During a quiz, the app now applies lightweight UI updates per answer and does a full dashboard refresh at quiz end (keeps the dialog responsive on long sessions).
- Incorrect answers create **must‑review** items.
- The **Hardest Concepts** card tracks repeated misses by chapter.

## 6) Reflections + notes

- After a Pomodoro or quiz, you may get a short reflection prompt.
- Add confidence notes per chapter via **Edit → Set Confidence Note…**
- Review all notes via **Application → Review Reflections…**

## 7) Analytics cards

- **Time Analytics**: total minutes per action type
- **Top Topics**: focus vs retrieval leaderboards + today’s top topics
- **Daily Summary**: two‑line recap (most time + biggest gap)
- **Confidence Drift**: chart of top gaps between competence and mastery/quiz

## 8) Importing Study Hub PDFs

Use **Import PDF scores** to parse ACCA Study Hub reports. This updates competence, quiz stats, and analytics.

## 9) Module management

- **Module → Switch Module…**
- **Module → Manage Modules…** (shows module locations)
- **Module → Edit Module…** (GUI editor)

## 10) Keyboard shortcuts

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

## 11) Troubleshooting

- **No notifications** → enable in Preferences
- **Focus tracking unavailable** → install `hyprctl`
- **Charts missing** → install `matplotlib`
- **PDF import missing** → install `PyMuPDF (fitz)`

---
