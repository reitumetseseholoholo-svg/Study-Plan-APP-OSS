# Module workflow investigation (all modules, focus F7)

Findings from tracing module load, data paths, syllabus, RAG, and outcome flow. One code fix applied.

---

## 1. F7 and other modules – config and paths

- **F7 config**: `modules/acca_f7.json` has `chapters`, `chapter_flow`, `importance_weights`, `semantic_aliases`. It has **no** `syllabus_structure` or `syllabus_meta` (by design after removing built-in F7 outcomes).
- **Path resolution**: For any module other than `acca_f9`, `_resolve_module_paths(module_id)` returns `CONFIG_HOME/<module_id>/data.json` and `.../questions.json`. F7 uses `~/.config/studyplan/acca_f7/data.json` and `.../questions.json`. No special case for F7.
- **Config load order**: Engine loads from (1) repo `dirname(studyplan_engine.__file__)/modules/<id>.json`, then (2) `MODULES_DIR/<id>.json`. App’s `_get_available_modules()` uses (1) repo `dirname(studyplan_app.__file__)/modules`, (2) `engine.MODULES_DIR`. So F7 is found when `modules/acca_f7.json` exists in the same install/repo as the running script.

---

## 2. Issue fixed: startup crash when no config file exists

- **Symptom** (from app.log): `ValueError: Unexpected None value: _last_loaded_module_config_path` during `StudyPlanEngine.__init__`.
- **Cause**: When no module config file is found (e.g. installed app at `/opt/studyplan-app/` with no `modules/` or no `MODULES_DIR` copy), `_load_module_config()` returns `None` and sets `_last_loaded_module_config_path = None`. The engine’s post-init “no None” check then raised.
- **Fix**: `_last_loaded_module_config_path` was added to `none_allowed` in `studyplan_engine.py`, so a missing config file no longer causes a crash. The engine keeps default (FM) chapters when config is missing until the user adds a config (e.g. via Manage Modules / Module Editor).

---

## 3. F7 workflow when syllabus_structure is empty

- **Outcome-based features**: With no `syllabus_structure` in config, `engine.syllabus_structure` stays `{}`. All outcome-based logic is written to handle this:
  - `_chapter_outcome_lookup(chapter)` → `{}`; `resolve_question_outcomes()` returns `outcome_ids=[]` immediately (no crash).
  - `get_chapter_outcome_mastery(chapter)` returns `total_outcomes=0`, `coverage_pct=0.0`, etc.
  - `_compute_exam_readiness_details` uses `mastery_pct` with `max(1, total)` so no divide-by-zero.
  - `get_mastery_stats(chapter)` uses SRS card counts only (no outcome list).
  - `_resolve_interleave_target_outcomes()` returns `[]` when `outcome_lookup` is empty.
  - `get_semantic_drift_kpi_by_chapter` skips chapters with `total_outcomes < min_outcomes` (5), so F7 with 0 outcomes is simply skipped.
- **Implication**: F7 (and any module without syllabus) works for chapters, quizzes, SRS, and competence, but **outcome coverage, readiness from outcomes, and outcome-level routing stay at 0 / empty** until the user runs **Import Syllabus PDF** or **Reconfigure from RAG** and applies a config that includes `syllabus_structure`.

---

## 4. F7-specific logic in engine (no bugs found)

- **Semantic aliases**: F7 defines `semantic_aliases` in config. `_chapter_semantic_alias_map()` uses them and does not add FM-built-in aliases when the module has its own (comment: “e.g. F7”).
- **Study-hub / coach mapping**: “FR (F7) fallbacks” in the engine (e.g. substring match for “conceptual framework”, “ifrs 15”, “consolidat”, etc.) only run when `existing_chapters` already look FR-like (e.g. “conceptual framework”, “ifrs”, “consolidat” in chapter names). So they apply when the loaded config is F7; no wrong-module mapping.

---

## 5. RAG and reconfig for F7

- **RAG paths for reconfig**: `_get_rag_pdf_paths_for_reconfig()` merges app Tutor RAG PDFs with `engine.syllabus_meta.source_pdf` and `syllabus_meta.reference_pdfs`. For F7, `syllabus_meta` is `{}`, so only app-level RAG paths are used until the user adds syllabus PDFs (e.g. via Import Syllabus PDF or preferences).
- **Reconfigure from RAG**: Works for F7 like any module: uses current config (chapters, etc.), RAG chunks, and optional `syllabus_paths` from config `syllabus_meta` (empty for F7 until set). No F7-specific branch.

---

## 6. Question persistence (F7)

- **Path**: Questions are stored in `CONFIG_HOME/acca_f7/questions.json`. Engine uses `QUESTIONS_FILE` set from `_resolve_module_paths("acca_f7")`; no `questions` key is read from module config (removed earlier).
- **Save**: `save_questions()` writes only “added” questions (vs empty default) to that file. So F7 imported questions should persist as long as the process uses the same `CONFIG_HOME` and the engine was created with `module_id=acca_f7`. If persistence still fails, likely causes are different `CONFIG_HOME` between runs or a different `module_id` at load time (see module isolation assertion added earlier).

---

## 7. Recommendations

1. **Done**: Allow `_last_loaded_module_config_path` to be `None` so startup never crashes when no config file exists.
2. **Done (dashboard)**: When the module has chapters but no learning outcomes in `syllabus_structure`, the dashboard shows a card pointing users to **Module → Import Syllabus PDF** / **Reconfigure from RAG**, and mentions **Tools → Add Tutor RAG PDF** for tutor alignment.
3. **Done**: After **Module Editor** save, **Refresh syllabus intelligence** apply, or **Reconfigure from RAG** apply, the app may prompt (Yes/No) to add `syllabus_meta.source_pdf` / `reference_pdfs` to Tutor RAG when those files exist and are not already listed.

No further code defects were found in the F7 or general-module workflow beyond the historical `none_allowed` fix above.
