# Study Assistant (module default)

A focused module-aware study coach built around Pomodoro discipline, SRS‑based quizzes, and a mission‑driven dashboard. It adapts to whichever module you load.

## Documentation map

- Full feature inventory: `FEATURES.md`
- Setup and operations: `README.md`
- Day-to-day usage: `USER_GUIDE.md`
- Fast onboarding: `QUICK_START.md`
- Developer details and architecture notes: `DEVELOPER_DOC.md`
- LLM roadmap (performance, quality, versatility, economy): `docs/LLM_IMPLEMENTATION_ROADMAP.md`
- LLM telemetry fields + golden prompts: `docs/LLM_TELEMETRY_SCHEMA.md`
- GUI monolith performance plan: `docs/GUI_MONOLITH_PERFORMANCE_PLAN.md`
- GUI workflow hardening plan: `docs/GUI_WORKFLOW_HARDENING_PLAN.md`

## Quick start

```bash
python studyplan_app.py
# or with exam date
python studyplan_app.py 2026-12-01
```

Optional module override (env vars):

```bash
STUDYPLAN_MODULE_TITLE="Your Module" python studyplan_app.py
```

## Requirements

- Python 3 with **PyGObject (GTK4)**
- Optional:
  - **PyMuPDF (fitz)** for PDF score import
  - **pytesseract + Pillow + numpy + scikit-image** for enhanced OCR preprocessing
  - **sentence-transformers** for semantic mapping (falls back safely when unavailable)
  - **matplotlib** for charts
  - **hyprctl** (Hyprland) for focus tracking
  - **hypridle** (optional hook for idle file)

## Testing

Run the test suite:

```bash
pytest
# or explicitly
pytest tests/ studyplan/testing/
```

- **Default (no GTK):** **388 tests** run. Path helpers live in `studyplan_app_path_utils.py`, so `tests/test_studyplan_app_paths.py` no longer needs `studyplan_app`. The remaining gap is `tests/test_studyplan_app_ollama.py` (157 tests), which requires `studyplan_app` and thus PyGObject/GTK4.
- **Full suite (500+ tests):** install the optional extra and system GTK4 so the ollama app tests run: `pip install -e ".[test-full]"` (or `poetry install -E test-full`). Requires system libraries (e.g. Debian/Ubuntu: `apt install python3-gi gir1.2-gtk-4.0`). Then `pytest` runs **545 tests**.

## Terminology

- **Coach**: what to do next and mission (Coach Pick, Coach Next, Briefing, daily plan).
- **Tutor**: in-app AI (Ollama) for explanations and practice (AI Tutor chat, Section C, practice loop). UI uses “Coach” for planning and “Tutor” for chat/practice.

## Core features

- **Coach Briefing**: readiness score, mission checklist, pace status, daily target
- **Exam Readiness Index** + retrieval quota bar (exam‑aware pacing)
- **Coach Pick**: single “do this now” topic with reasons + pace tip
- **Outcome Mastery**: covered vs uncovered syllabus outcomes (global + per capability)
- **ML‑assisted coaching**: recall risk, difficulty mix, interval‑aware release (when models available)
- **Coach Next**: one‑click “do the right thing now” action
- **Study Room**: next action, mission progress, quick actions
- **Interleave quiz**: quick rotation to the next chapter in plan
- **Pomodoro**: focus timer, break timer, alerts, streaks
- **Focus verification**: Hyprland allowlist + idle detection for verified minutes
- **Quizzes**: SRS‑weighted questions, streak bonuses, weak‑area drill
- **Leech remediation**: one-click drill for repeatedly-missed questions
- **Responsive quiz flow**: lightweight per‑question updates, full dashboard refresh on quiz completion
- **Gamification**: XP, levels, badges, daily quests
- **Daily plan**: coach‑aligned topic list with **automatic** daily completion
- **Plan stability**: stays consistent for the day unless a major import refreshes it
- **Smart empty states**: Daily plan explains how to populate when no topics are available
- **Insights**: mastery stats, weak/strong areas, reviews & due items
- **Reflections**: quick reflections + confidence notes (Review Reflections…)
- **Local AI Tutor (Ollama)**: run local GGUF models in-app for explanations and revision drills
- **Hardest Concepts**: tracks repeated misses per chapter
- **Time Analytics**: time per action + per‑topic leaderboards
- **Balance checks**: topic saturation + confidence drift (competence vs mastery/quiz)
- **Semantic graph + clusters**: canonical concept graph and outcome cluster graph for stable semantic routing
- **Semantic Drift KPI**: thresholded drift alerts when chapter competence diverges from outcome mastery
- **Confidence Drift chart**: top gap visualization
- **Data Health Check**: one‑click normalization + health summary in Tools
- **Syllabus cache tools**: view cache stats and clear parse/import caches
- **Weekly summary export**: auto writes `weekly_report.txt` under config home (see Data locations)
- **Study Hub import**: parse Study Hub PDFs (practice/quiz reports)
- **Syllabus import (draft-first)**: parse syllabus PDFs into module intelligence
- **Import Syllabus (JSON)**: seed syllabus_meta from JSON to reduce AI work in Reconfigure from RAG (see `docs/CORE_FEATURE_IMPROVEMENT_OUTCOME_LINKING.md`)
- **Modules**: switch or edit modules via JSON configs
- **Snapshot recovery**: auto-recovery on load failure + manual snapshot import/restore

## ML training (optional)

- In-app: **Application → Train ML Models…**
- Models:
  - Recall (sklearn): `~/.config/studyplan/recall_model.pkl`
  - Difficulty (sklearn): `~/.config/studyplan/difficulty_model.pkl`
  - Interval (sklearn): `~/.config/studyplan/interval_model.pkl`
- Recall trainer includes:
  - recency weighting
  - class balancing
  - automatic `C` candidate search
  - optional probability calibration
  - promotion gates on Brier, ECE, AUC, and improvement over existing model
- Runtime safety:
  - model load falls back safely when a model is missing/invalid
  - sklearn recall model is rejected if metadata feature count mismatches engine features

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

Data is stored per module (defaults to the active module id):

- `~/.config/studyplan/<module_id>/data.json`
- `~/.config/studyplan/<module_id>/questions.json`

Global app files:

- `~/.config/studyplan/preferences.json`
- `~/.config/studyplan/streak.json`
- `~/.config/studyplan/import_history.jsonl`
- `~/.config/studyplan/app.log`
- `~/.config/studyplan/coach_debug.log` (coach pick audit)
- `~/.config/studyplan/smoke_last.json` (latest dialog smoke/KPI report)
- `~/.config/studyplan/modules/*.json` (module configs)
- `~/.config/studyplan/<module_id>/backups/*.bak` (automatic snapshots)

## Module switching

1. **Module → Switch Module…**
2. Choose a module (or enter a new ID + title)
3. Click **Apply** → **Restart Now**

**Manage modules**: Module → Manage Modules… (opens module folders + list)

**Edit modules**: Module → Edit Module… (GUI editor for title/chapters/weights/flow/JSON)

Use **Tools → More → Module** to view the metadata/paths that the app has loaded for the active module or to reload the configuration after editing the JSON on disk.

**Import syllabus intelligence**:
1. Module → Import Syllabus PDF…
2. Select syllabus PDF
3. Review the draft in the import review wizard (confidence, warnings, preserve question-bank toggle)
4. Optional: use **Improve with AI (RAG)** to run retrieval-assisted outcome extraction against the PDF text (chunked retrieval so long PDFs are not truncated)
5. For automated or low-confidence runs, set `STUDYPLAN_AUTO_IMPROVE_SYLLABUS_AI=1` to auto-run RAG improvement when confidence &lt; 75% and a local LLM is available
6. A low-confidence parse requires explicit acknowledgment before opening the draft
7. Module Editor opens with draft JSON (no automatic save)
8. Save explicitly when ready
9. Optional: use **View Syllabus Cache Stats** in Tools to inspect cache hit rates and disk status

For stable setups, prefer versioned module JSON as the source of truth and use PDF import + RAG to review or update when new syllabi are published (see DEVELOPER_DOC § Syllabus ingestion strategy).

### Module JSON format

```json
{
  "title": "Your Module",
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
  "capabilities": {
    "A": "Financial management function"
  },
  "syllabus_structure": {
    "A. Financial management function": {
      "capability": "A",
      "subtopics": ["The nature and purpose of financial management"],
      "learning_outcomes": [{"id": "A.1", "text": "Explain ...", "level": 2}],
      "intellectual_level_mix": {"level_1": 0, "level_2": 1, "level_3": 0},
      "outcome_count": 1
    }
  },
  "syllabus_meta": {
    "source_pdf": "module syllabus and study guide.pdf",
    "exam_code": "MODULE",
    "effective_window": "Sep 2025 - Jun 2026",
    "parsed_at": "2026-02-06T20:30:00",
    "parse_confidence": 0.83
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

Grab the schema reference from `module_schema.json` in the repo root; the app uses it to surface metadata and validation warnings before saving module edits.

## Focus tracking (Hyprland)

- Uses `hyprctl activewindow -j` and **class matching**
- Configure allowlist via **Edit → Focus Allowlist…** or Preferences
- Auto‑pause after idle threshold off allowed apps; resume on return

## Pomodoro anti‑cheat

- **Credit only if ≥ 10 verified minutes**
- Rewards based on **verified focus time**
- At most **2 short credits/day** for tiny sessions

## Study Hub PDF import

Use **Import PDF Scores** to ingest Study Hub reports (practice/quiz). The app parses chapter and category performance to update competence and analytics.

OCR behavior:
- native text extraction first
- then optional skimage + Tesseract preprocessing for sparse/noisy pages
- then PyMuPDF OCR fallback

## Tests

```bash
pytest -q
python -m py_compile studyplan_app.py studyplan_engine.py
pyright studyplan_app.py studyplan_engine.py tests/test_studyplan_engine.py
```

Dialog smoke (exploratory):

```bash
timeout 40s python studyplan_app.py --dialog-smoke-test
```

Dialog smoke (strict gate, non-zero on KPI/report failure):

```bash
timeout 40s python studyplan_app.py --dialog-smoke-strict
```

**Isolated smoke/soak runs:** Set `STUDYPLAN_CONFIG_HOME` to a separate directory (e.g. a temp dir) so the run uses its own data and lock file. The smoke report is written to `smoke_last.json` under that config home, and `--dialog-smoke-strict` reads the report from the same path. Example:

```bash
STUDYPLAN_CONFIG_HOME=$(mktemp -d) timeout 40s python studyplan_app.py --dialog-smoke-strict
```

Strict smoke KPI thresholds:

- `coach_pick_consistency_rate >= 0.999`
- `coach_only_toggle_integrity_rate == 1.0`
- `coach_next_burst_integrity_rate == 1.0`

## Troubleshooting

- **Focus tracking unavailable**: ensure `hyprctl` is installed
- **Notifications not showing**: enable desktop notifications in Preferences
- **Charts missing**: install `matplotlib`
- **PDF import missing**: install `PyMuPDF (fitz)`
- **Enhanced OCR not active**: install `pytesseract`, `Pillow`, `numpy`, `scikit-image`, and the `tesseract` binary
- **Semantic map shows fallback**: confirm launcher environment has `sentence-transformers`
- **Data file failed to load**: app auto-recovers from latest snapshot; manual options are in **File → Recover from Snapshot…**

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
