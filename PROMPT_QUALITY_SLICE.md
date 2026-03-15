# Slice: Best prompts per in-app AI task

**Rationale**: AI is the core of the app. For best results with local LLMs we should offer **the best possible prompt for each in-app task** — one source of truth, tuned for clarity and structure, so every touchpoint (tutor, coach, autopilot, gap gen, reconfig, etc.) sends prompts that are consistent, schema-first, and effective.

**Status**: Slices 1–4 **implemented**. Slice 1: prompt library + autopilot. Slice 2: tutor quick prompts use quality matrix; Apply and Exam technique buttons. Slice 3: coach, gap_generation, section_c, syllabus extraction, assessment judge, and reconfig all use prompt_design. Slice 4: prompt versioning via `get_prompt_version(task_id)` and `get_task_prompt_spec(task_id, version=None)`; env `STUDYPLAN_PROMPT_VERSION_<task_id>` selects version; `_TASK_SPEC_VERSIONS` for overrides.

---

## Prompt library: task IDs and where used

| task_id   | Where used | Spec keys (role_base, role_suffix, rules, schema_one_line) |
|-----------|------------|------------------------------------------------------------|
| `autopilot` | `studyplan_app.py` `_build_ai_tutor_autopilot_prompt` | All; app injects runtime_contract between role_base and role_suffix. |
| `coach` | `studyplan_app.py` `_build_ai_coach_prompt` | All; app injects runtime_contract and learning_context. |
| `gap_generation` | `studyplan_app.py` `_build_gap_generation_prompt` | role_base, rules, schema_one_line; app may add extra_rules (syllabus_scope). |
| `section_c` | `studyplan_app.py` `_build_section_c_generation_prompt` | role_base, rules, schema_one_line; app may add extra_rules. |

---

## Current state

- **`studyplan/ai/prompt_design.py`**: Shared snippets (e.g. `JSON_ONLY_NO_MARKDOWN`), schema one-liners (gap, section C, syllabus, autopilot, assessment), and helpers (`build_generation_prompt`, `build_syllabus_extraction_prompt`). Used by app and reconfig; **role/instruction text is often inline** in `studyplan_app.py`, `studyplan/services.py`, `module_reconfig/reconfig.py`.
- **Tutor quality matrix** (`tests/tutor_quality/matrix_v1.json`): Curated prompts per **action type** (explain, apply, exam_technique, drill) and module/chapter. **In-app tutor** quick prompts (Explain, Apply, Exam technique, Drill 5) now use `studyplan.ai.tutor_prompts.get_prompt_for_tutor_action()` so when (module_id, chapter, action_type) match the matrix, the same prompt is sent as in the benchmark; otherwise fallback template is used.
- **Per-task prompt builders** (examples):
  - **Tutor chat**: `_build_ai_tutor_context_prompt`, `_build_ai_tutor_rag_prompt_context` — system/context assembled in app.
  - **Autopilot**: `_build_ai_tutor_autopilot_prompt` — role + runtime contract + rules in app; uses `AUTOPILOT_ACTION_SCHEMA_ONE_LINE` from prompt_design.
  - **Coach**: `_build_ai_coach_prompt` — role "You are an ACCA AI study coach" + contract + schema inline in app.
  - **Gap generation**: `_build_gap_generation_prompt` — uses prompt_design helpers; role/rules in app.
  - **Section C**: `_build_section_c_generation_prompt` — same pattern.
  - **Reconfig**: `build_syllabus_extraction_prompt`, `_extract_syllabus_meta`, capabilities/subtopics extraction — long role strings inside `reconfig.py`.
  - **Assessment judge**: `_build_judge_prompt` / `_build_judge_prompt_json_only` in `studyplan/services.py`.

So: prompts are **scattered**; the **best** wording (e.g. from the tutor quality matrix) is not the single source of truth for production; and there is no single place to **tune per task for local LLM effectiveness**.

---

## Goal

- **One prompt library** (or clearly designated place in `prompt_design` + optional JSON) that defines the **canonical role, rules, and schema** for each in-app AI task.
- **App and benchmark use the same prompts** where applicable (e.g. tutor explain/apply/exam_technique/drill so matrix and in-app tutor align).
- **Easy to iterate**: change wording in one place; all call sites (app, benchmark, tests) get the update.
- **Documented**: each task has a short comment or docstring describing intent and any local-LLM tuning notes.

---

## In-app AI tasks (inventory)

| Task | Current prompt location | Schema / shared bits |
|------|------------------------|----------------------|
| Tutor chat (system + context) | `studyplan_app.py` `_build_ai_tutor_context_prompt`, RAG builder | Contract version, details format |
| Tutor actions: explain, apply, exam_technique, drill | Quick prompts → `get_prompt_for_tutor_action(module_id, topic, action_type)` from `studyplan/ai/tutor_prompts.py`; matrix `tests/tutor_quality/matrix_v1.json` | Same file as benchmark; fallback template if no match |
| Autopilot (one JSON action) | `studyplan_app.py` → `get_task_prompt_spec("autopilot")` + `build_generation_prompt` | `prompt_design`: role_base, role_suffix, rules, schema_one_line |
| Coach (one JSON recommendation) | `studyplan_app.py` → `get_task_prompt_spec("coach")` | `prompt_design`: COACH_* constants |
| Gap generation | `studyplan_app.py` → `get_task_prompt_spec("gap_generation")` + `build_generation_prompt` | `prompt_design`: GAP_GENERATION_* |
| Section C generation | `studyplan_app.py` → `get_task_prompt_spec("section_c")` + `build_generation_prompt` | `prompt_design`: SECTION_C_* |
| Syllabus extraction (import / reconfig) | `prompt_design.build_syllabus_extraction_prompt` (default role `SYLLABUS_EXTRACTION_ROLE_DEFAULT`) | `SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE`, `SYLLABUS_EXTRACTION_ROLE_DEFAULT` |
| Reconfig: capabilities, meta, subtopics | `studyplan/module_reconfig/reconfig.py` → `RECONFIG_*_PROMPT_PREFIX` from prompt_design | `RECONFIG_CAPABILITIES_PROMPT_PREFIX`, `RECONFIG_SYLLABUS_META_PROMPT_PREFIX`, `RECONFIG_SUBTOPICS_PROMPT_PREFIX` |
| Assessment judge | `studyplan/services.py` `_build_judge_prompt` | `prompt_design`: `ASSESSMENT_JUDGE_ROLE_BASE`, `ASSESSMENT_JUDGE_RULES`, `ASSESSMENT_JUDGE_SCHEMA_ONE_LINE` |

---

## Slice 1: Prompt library and task registry (foundation) — DONE

**Goal**: Single module (or extended `prompt_design`) that defines **role + rules + schema** per task, so call sites import and build from it.

**Done**:

1. **Extend `studyplan/ai/prompt_design.py`** (or add `studyplan/ai/task_prompts.py` that re-exports/uses prompt_design):
   - For each in-app task, define:
     - `TASK_ID` (e.g. `autopilot`, `coach`, `gap_generation`, `section_c`, `syllabus_extraction`, `assessment_judge`, `reconfig_capabilities`, …).
     - **Role string** (one place): e.g. “You are an ACCA AI tutor cockpit controller. …”
     - **Rules** (list of strings): same as today but in one place.
     - **Schema** (already have one-liners; keep or reference).
   - Provide a small API, e.g. `get_task_prompt_spec(task_id) -> dict` with `role`, `rules`, `schema_one_line`, and optional `retry_suffix`.
   - Keep backward compatibility: existing `build_generation_prompt(role_and_style=..., rules=..., schema_one_line=...)` still works; new code can pull `role`/`rules`/`schema` from the spec.

2. **Migrate one task end-to-end** (e.g. **autopilot**): Move role and rules from `_build_ai_tutor_autopilot_prompt` into `prompt_design` (or task_prompts). App calls `get_task_prompt_spec("autopilot")` and passes payload; behaviour unchanged. Ensures the pattern works.

3. **Document**: In DEVELOPER_DOC or this file, add “Prompt library: task IDs and where they are used (app vs benchmark vs reconfig).”

**Effort**: Small–medium (2–4 hours). **Risk**: Low.

---

## Slice 2: Align tutor action prompts with quality matrix — DONE

**Goal**: For tutor actions **explain**, **apply**, **exam_technique**, **drill**, the in-app flow should use the **same** prompt templates as the tutor quality matrix when (module_id, chapter, action_type) match.

**Done**:
1. **`studyplan/ai/tutor_prompts.py`**: `get_tutor_matrix_path()`, `load_tutor_matrix()`, `get_prompt_for_tutor_action(module_id, chapter, action_type)`. Matrix path from env `STUDYPLAN_TUTOR_QUALITY_MATRIX` or repo `tests/tutor_quality/matrix_v1.json`. Exact or normalized chapter match; fallback to first case for same module+action_type.
2. **In-app tutor**: Quick prompts are (label, action_type, fallback_template). “Explain topic”, “Apply”, “Exam technique”, “Drill 5” have action_type; on click, `_insert_quick_prompt(template, action_type)` calls `get_prompt_for_tutor_action(module_id, topic, action_type)` and uses matrix prompt when available, else substituted fallback.
3. **Benchmark**: Still uses same matrix file; no change. Tests: `studyplan/testing/test_tutor_prompts.py`.

---

## Slice 3: Migrate remaining tasks to prompt library — DONE

**Goal**: Coach, gap generation, section C, syllabus/reconfig roles, assessment judge — all get their role and rules from the central prompt library.

**Done**:
- **Coach**: `COACH_ROLE_BASE`, `COACH_ROLE_SUFFIX`, `COACH_RULES`, `COACH_SCHEMA_ONE_LINE` in prompt_design; `_build_ai_coach_prompt` uses `get_task_prompt_spec("coach")`.
- **Gap generation**: `GAP_GENERATION_ROLE_BASE`, `GAP_GENERATION_RULES` + `GAP_SCHEMA_ONE_LINE`; app uses `get_task_prompt_spec("gap_generation")` and `build_generation_prompt`.
- **Section C**: `SECTION_C_ROLE_BASE`, `SECTION_C_RULES` + `SECTION_C_SCHEMA_ONE_LINE`; app uses `get_task_prompt_spec("section_c")`.
- **Syllabus extraction**: `SYLLABUS_EXTRACTION_ROLE_DEFAULT`; `build_syllabus_extraction_prompt(role_and_style=None)` uses it.
- **Reconfig**: `RECONFIG_CAPABILITIES_PROMPT_PREFIX`, `RECONFIG_SYLLABUS_META_PROMPT_PREFIX`, `RECONFIG_SUBTOPICS_PROMPT_PREFIX`; reconfig.py imports and uses them.
- **Assessment judge**: `ASSESSMENT_JUDGE_ROLE_BASE`, `ASSESSMENT_JUDGE_RULES`; services.py imports and uses with `ASSESSMENT_JUDGE_SCHEMA_ONE_LINE`.

---

## Slice 4 (optional): Prompt versioning and A/B — DONE

**Goal**: Support multiple “versions” of a task prompt so we can A/B test or roll out improved wording without big code changes.

**Done**:
- **`get_prompt_version(task_id)`**: Returns env `STUDYPLAN_PROMPT_VERSION_<TASK_ID>` (uppercased) or `"default"`. Env key e.g. `STUDYPLAN_PROMPT_VERSION_autopilot=v2`.
- **`get_task_prompt_spec(task_id, version=None)`**: When `version` is None, uses `get_prompt_version(task_id)`. If resolved version is not `"default"` and `_TASK_SPEC_VERSIONS[task_id][version]` exists, returns that spec; otherwise returns default from `_TASK_SPECS`. Schema contract unchanged; only role/rules text may differ by version.
- **`_TASK_SPEC_VERSIONS`**: Optional dict `task_id -> version -> spec`; populate to add alternate versions (e.g. `_TASK_SPEC_VERSIONS["autopilot"]["v2"] = {...}`). Call sites continue to call `get_task_prompt_spec("autopilot")` with no second arg; version is selected by env or explicit pass-through.
- Tests: `studyplan/testing/test_prompt_design.py`.

---

## Success criteria

- **Slice 1**: At least one task (e.g. autopilot) builds its prompt from a single spec in `prompt_design` (or task_prompts); existing tests and app behaviour unchanged.
- **Slice 2**: In-app tutor explain/apply/exam_technique/drill use prompts derived from the same source as the tutor quality matrix (or matrix is the source of truth).
- **Slice 3**: All listed in-app AI tasks pull role and rules from the prompt library; no long inline prompt strings in app/reconfig/services for these tasks.
- **Slice 4** (optional): Versioned prompts selectable per task via config/env.

---

## Non-goals

- Changing model choice or context window limits (separate concern).
- Changing RAG retrieval logic (only how we phrase the task in the prompt).
- Adding new AI tasks; this slice only improves prompt quality and centralization for **existing** tasks.

---

## Recommended order

| Order | Slice | Rationale |
|-------|--------|-----------|
| 1 | **Slice 1** (prompt library + one task) | Foundation; validates pattern; low risk. |
| 2 | **Slice 2** (tutor ↔ matrix alignment) | High impact: tutor is core; matrix already has curated prompts. |
| 3 | **Slice 3** (migrate remaining tasks) | Full consistency; one place to tune every task. |
| 4 | **Slice 4** (versioning) | Optional; useful once we want to iterate on wording without code churn. |
