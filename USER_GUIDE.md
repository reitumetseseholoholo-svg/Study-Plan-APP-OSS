# User Guide — Study Assistant

This guide walks you through using Study Assistant day-to-day: setting up your module, running study sessions, using the AI tutor, and getting the most out of the adaptive coaching features.

## Table of Contents

1. [First Launch](#first-launch)
2. [Setting Your Exam Date](#setting-your-exam-date)
3. [Understanding the Layout](#understanding-the-layout)
4. [Daily Workflow](#daily-workflow)
5. [The Pomodoro Timer](#the-pomodoro-timer)
6. [Quizzes and Spaced Repetition](#quizzes-and-spaced-repetition)
7. [The AI Coach](#the-ai-coach)
8. [The AI Tutor (Ollama / Cloud)](#the-ai-tutor-ollama--cloud)
9. [AI Cockpit (Autopilot)](#ai-cockpit-autopilot)
10. [Section C Constructed-Response Practice](#section-c-constructed-response-practice)
11. [Importing a Syllabus](#importing-a-syllabus)
12. [Importing PDF Scores (Study Hub)](#importing-pdf-scores-study-hub)
13. [Modules — Switching and Editing](#modules--switching-and-editing)
14. [ML Models — Train Your Own](#ml-models--train-your-own)
15. [Exporting Data](#exporting-data)
16. [Gamification — XP, Levels, Badges, Quests](#gamification--xp-levels-badges-quests)
17. [Keyboard Shortcuts](#keyboard-shortcuts)
18. [Focus Tracking (Hyprland)](#focus-tracking-hyprland)
19. [Data Locations and Backups](#data-locations-and-backups)
20. [Troubleshooting](#troubleshooting)

---

## First Launch

```bash
python studyplan_app.py
# optionally pass your exam date directly
python studyplan_app.py 2026-12-01
```

On first launch the app creates `~/.config/studyplan/` and initialises data files for the default module (`acca_f9` / Financial Management). A single-instance lock prevents two copies from running simultaneously.

> **If the app won't start after a crash**, remove the stale lock:
> ```bash
> rm -f ~/.config/studyplan/app_instance.lock
> ```

---

## Setting Your Exam Date

Go to **Edit → Set Exam Date…** (or press **Ctrl+E**).

The exam date drives almost everything:

- **Pace status** — whether you are ahead, on-track, or behind the required study rate
- **Exam Readiness Index** — weighted score shown on the dashboard
- **Coach urgency** — topics get higher urgency as the exam approaches (2× within 7 days, 1.6× within 21 days)
- **Daily plan** — adapts topic selection and stickiness thresholds to exam proximity
- **SRS scheduling** — the retention-mode window (≤21 days to exam) tightens review intervals

---

## Understanding the Layout

The window is split into three areas:

| Area | Contents |
|---|---|
| **Left panel** | Module + topic selector, Pomodoro timer, streak / XP, daily quests |
| **Main area** | Tabbed dashboard: Coach Briefing, Study Room, Insights, Reflections, AI Cockpit |
| **Right panel / workspace** | Quiz dialogs, AI tutor, Section C practice, module editor |

**Key tabs on the dashboard:**
- **Coach Briefing** — readiness score, mission checklist, pace status, daily target, Coach Pick
- **Study Room** — single "next action" button, mission progress bar, quick-action tiles
- **Insights** — mastery stats, weak/strong chapters, due items, semantic drift chart
- **Reflections** — confidence notes and session reflections
- **AI Cockpit** — autopilot mode selector, last/next action live display

---

## Daily Workflow

A typical session looks like this:

1. Open the app. Check the **Coach Pick** card on the left panel — it shows the single topic the coach recommends with a reason.
2. Check the **Pomodoro** section. Start a 25-minute focus block with **F5** or the Start button.
3. Study the recommended topic; optionally open the **AI Tutor** for explanations.
4. When the timer ends, take the prompted quiz to consolidate the session.
5. The dashboard automatically refreshes: mastery, SRS debt, and tomorrow's plan all update.
6. Repeat for 2–4 Pomodoros then stop for the day.

**Coach Next** (in Study Room or via the toolbar) triggers the single highest-priority action right now — it may launch a quiz, a drill, a review, or an interleave — based on live data.

---

## The Pomodoro Timer

The timer is in the left panel. Use **F5 / F6 / F7** or the on-screen buttons.

### Anti-cheat rules

| Rule | Detail |
|---|---|
| Minimum credit | Session must total **≥ 10 verified minutes** to count toward daily stats |
| Short session cap | At most **2 short credits per day** (sessions that don't reach the minimum) |
| Verified time | Only minutes spent in your focus-allowed apps (Hyprland only) count as verified |

Verified minutes are shown in the badge: **"Verified today: Xm"**. Rewards (XP, streak) are based on verified time, not wall time.

### Break timer

After a Pomodoro the app prompts for a break. Breaks auto-cancel if you start another Pomodoro early.

### Pomodoro length

Default is 25 minutes. You can adjust it in **Preferences → Focus**.

---

## Quizzes and Spaced Repetition

### SRS algorithm

The default algorithm is **FSRS-4.5** (Free Spaced Repetition Scheduler). It models per-card memory stability and adjusts review intervals so each card is reviewed just before you would forget it.

To use the older **SM-2** algorithm instead:
```bash
STUDYPLAN_SRS_ALGORITHM=sm2 python studyplan_app.py
```

### Quiz types

| Mode | How to launch | What it does |
|---|---|---|
| **Quick Quiz** | F8, or Quick Quiz button | 5–10 SRS-weighted questions for the current topic |
| **Drill** | Study Room → Drill | Focused practice on weak chapters |
| **Weak-area Drill** | Study Room | Targets your lowest-competence chapters |
| **Leitner Drill** | Study Room | Questions in Leitner boxes 1–3 only |
| **Error Drill** | Study Room | Repeats recently-answered-wrong questions |
| **Leech Drill** | Study Room | Tackles repeatedly-missed "leech" questions |
| **Interleave Quiz** | Coach Next / Study Room | Rotates to the next chapter in plan |
| **Review** | Study Room | All overdue SRS cards |

### Outcome-gap routing

When the syllabus structure is loaded, the quiz engine boosts questions that are linked to syllabus outcomes you haven't covered yet (`OUTCOME_GAP_QUIZ_RATIO = 0.5`), so your quiz practice also covers exam outcomes.

### Leech remediation

A question becomes a "leech" after repeated misses. The app tracks leeches per chapter and offers a one-click **Leech Drill** in the Study Room and Insights tabs to address them directly.

### Answering questions

- Select your answer and confirm. The app shows whether you were correct, the explanation, and the next SRS due date.
- **Confidence note**: After a quiz you can log how confident you felt (1–5). These feed the confidence calibration chart under Insights.

---

## The AI Coach

The **Coach** is data-driven, not conversational. It analyses your SRS data, competence scores, syllabus outcomes, and ML risk signals to recommend what to do next.

### Coach Pick

The **Coach Pick** card (top of the left panel) shows:
- **Topic**: the single highest-urgency chapter right now
- **Reason**: why this topic was chosen (competence gap, SRS debt, ML risk, semantic drift, exam proximity)
- **Pace tip**: whether you need to speed up

Coach Pick is **sticky for the day** — it won't change unless you complete a major import that refreshes data. This prevents flip-flopping mid-session.

### Coach Briefing tab

The full briefing shows:
- Readiness index and retrieval quota (% of SRS cards answered this period)
- Mission checklist (topics to hit today)
- Pace status (ahead / on-track / behind)
- Daily target hours

### Coach-only mode

**Preferences → Coach-only** (or click the "Coach-only" badge) hides the daily plan list and forces all navigation through the coach's recommendation. Click the badge again to exit.

---

## The AI Tutor (Ollama / Cloud)

The AI tutor gives explanations, worked examples, and revision drills in a chat interface.

### Setting up a local model (Ollama)

1. Install [Ollama](https://ollama.com) and pull a model: `ollama pull llama3.1:8b-instruct-q4_k_m`
2. Start Ollama: `ollama serve`
3. Open the app — it auto-discovers Ollama models
4. Open the tutor: **Tools → AI Tutor…** or press the Tutor button

The app can also launch and manage a **llama.cpp server** directly (without Ollama) if you have a GGUF model on disk. Enable via `STUDYPLAN_LLAMA_CPP_MANAGED_SERVER=1` and set `STUDYPLAN_LLAMA_SERVER_BIN` to your `llama-server` binary path.

### Setting up a cloud model (OpenRouter / any OpenAI-compatible API)

1. Go to **Preferences → Cloud AI**
2. Enter your endpoint URL (e.g. `https://openrouter.ai/api/v1/chat/completions`)
3. Enter your API key
4. Enter a model ID (e.g. `google/gemini-2.5-flash`)
5. Optionally add fallback models (comma-separated)

Or use environment variables:
```bash
STUDYPLAN_LLM_GATEWAY_ENABLED=1 \
STUDYPLAN_LLM_GATEWAY_ENDPOINT=https://openrouter.ai/api/v1/chat/completions \
STUDYPLAN_LLM_GATEWAY_API_KEY=sk-... \
STUDYPLAN_LLM_GATEWAY_MODEL=google/gemini-2.5-flash \
python studyplan_app.py
```

### RAG (Retrieval-Augmented Generation)

When a syllabus PDF or notes PDF is attached, the tutor retrieves relevant chunks and cites them in answers (e.g. `[S2]`). To add a document: **Tools → Add Tutor RAG PDF…**.

### Tutor memory

The tutor maintains a short-term memory of recent activity (up to 14 entries: date, topic, summary). This lets it continue from where you left off across sessions.

### Pedagogical modes

The tutor adapts its style based on your quiz performance and struggle signals:

| Mode | When triggered | Behaviour |
|---|---|---|
| DIAGNOSE | Starting a new topic | Asks one clarifying question first |
| PRODUCTIVE_STRUGGLE | Quiz active or error detected | Socratic — guides without giving answers |
| SCAFFOLD | After initial struggle | Partial hint, then asks what comes next |
| CONSOLIDATE | Mastery 65–85% | Confirms understanding before moving on |
| CHALLENGE | Mastery > 85% | Presents harder variants and edge cases |

---

## AI Cockpit (Autopilot)

The AI Cockpit is a **second AI system** that runs in the background and autonomously manages your session. It is separate from the tutor chat.

### Autonomy modes

| Mode | Behaviour |
|---|---|
| **Cockpit** *(default)* | AI executes safe actions automatically without asking |
| **Assist** | AI executes safe actions but notifies you after |
| **Suggest** | AI proposes actions and waits for your approval |

Change the mode via the **AI Cockpit tab** dropdown or **Preferences → Autopilot**.

### What the autopilot can do

**Safe actions (executed automatically in Cockpit mode):**

`focus_start`, `timer_pause/resume/stop`, `tutor_open`, `coach_open`, `coach_next`, `quick_quiz_start`, `drill_start`, `weak_drill_start`, `leitner_drill_start`, `error_drill_start`, `leech_drill_start`, `interleave_start`, `review_start`

**Actions that always require confirmation:**

`quiz_start` (full quiz), `gap_drill_generate` (AI question generation), `section_c_start`

### Rate limits

- Max **6 actions per 10-minute window**
- **90-second quiet window** after a successful action
- Decision refresh every **120 seconds**

### Pausing the autopilot

Click **Pause** on the AI Cockpit tab, or toggle it off in Preferences. The cockpit live card on the dashboard always shows the current state, last action, and next planned action.

---

## Section C Constructed-Response Practice

**Section C** is the long-answer, scenario-based section of professional exams. The app generates full case scenarios with exhibits (financial statements) and graded requirements.

- Open via **Practice → Section C practice…** or the Sec C button in the Study Room
- Select a chapter and generate a case (45-minute budget by default)
- Write your answer in the text area
- Use **Grade Answer** to receive AI-scored feedback with marks, feedback per requirement, and a model answer outline

Cases are saved in `~/.config/studyplan/<module_id>/section_c_bank.json` and can be browsed via **Practice → Browse section C bank…**.

---

## Importing a Syllabus

Syllabus data gives the coach and tutor precise outcome-level intelligence.

### From PDF

1. **Module → Import Syllabus PDF…**
2. Select the syllabus PDF
3. The import wizard shows: confidence score, warnings, option to preserve the existing question bank
4. If confidence < 75%, you must explicitly acknowledge before the draft opens
5. Click **Improve with AI (RAG)** to run retrieval-assisted outcome extraction (recommended for long PDFs)
6. Review the draft in the JSON editor; save explicitly when satisfied

### From JSON

If you already have a structured JSON file:

1. **Module → Import Syllabus (JSON)…**
2. Select the file — it seeds `syllabus_meta` directly, bypassing PDF parsing
3. Choose **Merge with current** to keep existing `syllabus_meta` keys, or **Replace syllabus meta** to overwrite the current block from the JSON file
4. The same import is also available from **Module Editor → Import Syllabus JSON…**, which shows current `source_pdf` / `reference_pdfs` values in a read-only panel

### Auto-improve on low confidence

Set `STUDYPLAN_AUTO_IMPROVE_SYLLABUS_AI=1` to automatically run RAG improvement when the parse confidence is below 75% and a local LLM is available.

### Refreshing outcome links

After importing a syllabus, run **Module → Refresh syllabus intelligence & link outcomes** to:
1. Rebuild the canonical concept graph
2. Heuristically link existing questions to syllabus outcome IDs using lexical similarity

This improves outcome-gap quiz routing without requiring any AI calls.

---

## Importing PDF Scores (Study Hub)

Use **File → Import PDF Scores…** to ingest Study Hub practice/quiz reports.

The parser tries three methods in order:
1. Native PDF text extraction
2. OCR with skimage/Tesseract preprocessing (enhanced clarity for scanned pages)
3. PyMuPDF OCR fallback

Parsed scores update chapter competence and are visible immediately in the Insights tab.

---

## Modules — Switching and Editing

### Switch module

1. **Module → Switch Module…**
2. Select an existing module or enter a new ID and title
3. Click **Apply → Restart Now**

Each module has its own `data.json` and `questions.json` under `~/.config/studyplan/<module_id>/`.

### Edit module config

**Module → Edit Module…** opens the GUI JSON editor for title, chapters, weights, chapter flow, and syllabus structure. Changes take effect after saving and reloading.

### Module JSON format

See `README.md § Module JSON format` for the full schema. Quick reference:

```json
{
  "title": "Your Module",
  "chapters": ["Topic 1", "Topic 2"],
  "chapter_flow": { "Topic 1": ["Topic 2"] },
  "importance_weights": { "Topic 1": 20, "Topic 2": 10 },
  "target_total_hours": 180
}
```

The schema is validated at save time against `module_schema.json` in the repo root.

### Managing modules

**Module → Manage Modules…** opens the modules folder and a list of all installed modules.

---

## ML Models — Train Your Own

The app ships without pre-trained ML models. Training is optional but improves coach accuracy.

**Application → Train ML Models…** trains three sklearn models on your quiz history:

| Model | What it learns | File |
|---|---|---|
| **Recall** | Probability of recalling a card at review time | `recall_model.pkl` |
| **Difficulty** | Per-question difficulty estimate | `difficulty_model.pkl` |
| **Interval** | Optimal SRS interval for a card | `interval_model.pkl` |

Models are stored in `~/.config/studyplan/`. The recall model requires at least 100 answered questions and passes promotion gates on Brier score, ECE, AUC, and improvement over any existing model before being saved.

When models are available, coach urgency scores include an **ML recall-risk boost** (×30 × exam-proximity weight) which significantly improves recommendation quality.

---

## Exporting Data

| Export | Menu | Output |
|---|---|---|
| Study data (CSV) | File → Export CSV… | Competence + SRS data |
| Flashcards (CSV) | File → Export Flashcards… | Question/answer pairs |
| Anki TSV | File → Export Anki TSV… | Ready to import into Anki |
| Question stats | File → Export Question Stats… | Per-question performance data |
| Weekly report | File → View Weekly Report… | Auto-written to `weekly_report.txt` in config home |

---

## Gamification — XP, Levels, Badges, Quests

| Element | How to earn |
|---|---|
| **XP** | Completing Pomodoros (verified time), correct quiz answers, streak bonuses |
| **Levels** | Accumulate XP thresholds |
| **Badges** | Milestone achievements (streaks, mastery, quiz completions) |
| **Daily quests** | Shown in the left panel; reset each day (e.g. "Complete 3 Pomodoros", "Answer 20 quiz questions") |
| **Streak** | Consecutive days with at least one Pomodoro |

Badge unlocks are celebrated with a brief chip animation. Click the XP/level chip in the left panel to see all badges.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| **F1** | Show all shortcuts |
| **F5** | Start Pomodoro |
| **F6** | Pause / Resume Pomodoro |
| **F7** | Stop Pomodoro |
| **F8** | Quick Quiz |
| **F9** | Toggle Focus Mode |
| **Ctrl+E** | Set exam date |
| **Ctrl+,** | Preferences |
| **Ctrl+M** | Toggle menu bar |
| **Ctrl+Q** | Quit |

---

## Focus Tracking (Hyprland)

The app uses `hyprctl activewindow -j` to verify that focus time was spent in your study tools.

- Configure the window-class allowlist via **Edit → Focus Allowlist…** or Preferences
- Minutes in non-allowed apps are logged as raw time but not credited as verified
- Auto-pause triggers after the idle threshold is exceeded; the timer resumes when you return

If `hyprctl` is not installed, focus tracking is disabled and all Pomodoro time counts as raw (unverified).

---

## Data Locations and Backups

### Per-module data

```
~/.config/studyplan/<module_id>/data.json          # progress, SRS, competence
~/.config/studyplan/<module_id>/questions.json     # AI-generated questions
~/.config/studyplan/<module_id>/section_c_bank.json
~/.config/studyplan/<module_id>/backups/*.bak      # automatic snapshots (20 kept)
```

### Global data

```
~/.config/studyplan/preferences.json
~/.config/studyplan/streak.json
~/.config/studyplan/import_history.jsonl
~/.config/studyplan/app.log
~/.config/studyplan/coach_debug.log     # coach pick audit trail
~/.config/studyplan/smoke_last.json     # latest CI smoke report
~/.config/studyplan/modules/*.json      # module configs
~/.config/studyplan/recall_model.pkl    # sklearn recall model (if trained)
~/.config/studyplan/difficulty_model.pkl
~/.config/studyplan/interval_model.pkl
~/.config/studyplan/weekly_report.txt
```

### Snapshot recovery

The app creates automatic rolling backups (up to 20) every time data is saved. If the data file fails to load:
- The app **auto-recovers** from the latest valid snapshot
- You can also trigger manual recovery via **File → Recover from Snapshot…** or restore a specific backup via **File → Restore Latest Snapshot**

### Data health check

**Tools → Run Data Health Check** normalises data, checks for corruption, and shows a summary. Use it after unexpected crashes or imports.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| App won't start (lock file) | `rm -f ~/.config/studyplan/app_instance.lock` |
| Charts missing | Install `matplotlib` |
| PDF import missing | Install `PyMuPDF`: `pip install pymupdf` |
| Enhanced OCR not active | Install `pytesseract`, `Pillow`, `numpy`, `scikit-image` and the `tesseract` binary |
| AI tutor can't find a model | Check Ollama is running: `ollama serve` |
| Semantic map shows fallback | Install `sentence-transformers`: `pip install sentence-transformers` |
| Focus tracking unavailable | Install `hyprctl` (Hyprland only) |
| Notifications not showing | Enable in **Preferences → Notifications** |
| Data file failed to load | Use **File → Recover from Snapshot…** |
| Slow quiz after answer | Expected: lightweight per-question updates; full refresh only on quiz completion |
