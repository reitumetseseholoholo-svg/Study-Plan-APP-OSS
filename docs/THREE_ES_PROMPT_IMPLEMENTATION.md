# 3Es prompt implementation (Economy, Efficiency, Effectiveness)

How the app implements the 3Es framework for AI prompts **without duplicating** existing prompt design. All generation-style prompts use the same canonical order and shared snippets.

---

## 1. The 3Es framework

| E | Definition | How the app applies it |
|---|------------|-------------------------|
| **Economy** | Minimal tokens; no waste | One system-style block per action; shared snippets (`JSON_ONLY_NO_PROSE`, `JSON_ONLY_NO_MARKDOWN`, `RETRY_SUFFIX_*`); context truncated to what’s needed (syllabus excerpt, payload keys). |
| **Efficiency** | One task per action | One prompt per call; compact one-line schema; rules as a short bullet list (5–8 items); no repeated schema in rules. |
| **Effectiveness** | Output meets the task | Task-specific constraints (ACCA style, command verbs, mark totals); explicit allowed values (e.g. `correct` ∈ {A,B,C,D}); syllabus scope when relevant. |

---

## 2. Canonical prompt structure (no duplication)

Every **generation** prompt (Section C, gap, autopilot, coach) follows this order. There is **one** builder that enforces it.

1. **Role/task** (1–2 sentences): what to generate and in what style (e.g. “ACCA exam-type … as JSON only (no prose)”).
2. **Schema**: exact JSON shape (one line or minimal multi-line). Field names and value types or enums.
3. **Rules**: short bullet list (constraints, do-nots, syllabus note). Prefer 5–8 bullets.
4. **Payload**: “Payload JSON:” + compact JSON (context, topic, counts, hints). Keys sorted for stable caching where useful.

**Retry path**: On parse failure, append a **retry suffix** only (e.g. `RETRY_SUFFIX_ONE_ITEM`, `JUDGE_JSON_ONLY`). Do not rebuild the whole prompt.

---

## 3. Where each action is implemented

| AI action | Builder | Spec source | Payload shape |
|-----------|---------|-------------|---------------|
| **Section C** | `build_generation_prompt()` | `get_task_prompt_spec("section_c")` | topic, chapter, section_c_intelligence, learning_context, etc. |
| **Gap / MCQ** | `build_generation_prompt()` | `get_task_prompt_spec("gap_generation")` | topic, count, module, current_topic, weak_topics_top3, etc. |
| **Autopilot** | `build_generation_prompt()` | `get_task_prompt_spec("autopilot")` | snapshot (runtime_contract, weak_topics, etc.) |
| **Coach** | `build_generation_prompt()` | `get_task_prompt_spec("coach")` | action_topics, recommended_topic, learning_context |
| **Syllabus extraction** | `build_syllabus_extraction_prompt()` | Inline role + `SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE` + rules | Syllabus text + chapters blob (not JSON; context is the excerpt) |
| **Assessment judge** | `build_judge_prompt_3es()` (see below) | `ASSESSMENT_JUDGE_*` in prompt_design | Module, topic, question, learner answer, optional confidence/rubric |

There is **no second** “3Es template” or “build_3es_prompt” alongside these. The 3Es contract is satisfied by:

- **Generation tasks**: `build_generation_prompt(role_and_style, schema_one_line, rules, payload_json, extra_rules)` in `studyplan/ai/prompt_design.py`.
- **Syllabus**: `build_syllabus_extraction_prompt(..., syllabus_text, chapters_blob)` — same order (role → schema → rules → payload), with payload = excerpt + chapter list.
- **Judge**: `build_judge_prompt_3es(role_base, schema_one_line, rules, ...)` in prompt_design so the judge also follows Role → Schema → Rules → Payload; services only supplies the payload content.

---

## 4. Shared snippets (economy)

All live in `studyplan/ai/prompt_design.py`. No duplication across actions.

- `JSON_ONLY_NO_PROSE`, `JSON_ONLY_NO_MARKDOWN` — used in role text and retry.
- `RETRY_SUFFIX_ONE_ITEM`, `RETRY_SUFFIX_ONE_CASE` — appended on relaxed retry for gap and Section C.
- `JUDGE_JSON_ONLY` — retry for assessment judge.
- `SYLLABUS_JSON_ONLY` — syllabus extraction rules.
- Schema one-liners: `GAP_SCHEMA_ONE_LINE`, `SECTION_C_SCHEMA_ONE_LINE`, `ASSESSMENT_JUDGE_SCHEMA_ONE_LINE`, etc. — single source for each task.

Task-specific **rules** and **role** text are in `_TASK_SPECS` (and related constants) so the app and benchmarks share one source of truth via `get_task_prompt_spec(task_id)`.

---

## 5. Implementation checklist

- [x] **Single builder for generation**: `build_generation_prompt()` is the only place that assembles role → schema → rules → payload for Section C, gap, autopilot, coach.
- [x] **Single builder for syllabus**: `build_syllabus_extraction_prompt()` for extraction; reconfig uses the same schema and rules.
- [x] **Judge aligned with 3Es**: Assessment judge prompt built via `build_judge_prompt_3es()` in prompt_design (Role → Schema → Rules → Payload); services only passes payload content.
- [x] **Retry = suffix only**: No full prompt rebuild on retry; append the appropriate `RETRY_SUFFIX_*` or `JUDGE_JSON_ONLY`.
- [x] **Specs in one place**: `get_task_prompt_spec(task_id)` returns role_base, rules, schema_one_line; callers pass these into the builders above.

---

## 6. Validation (optional)

To ensure no drift:

- **Tests**: Existing tests in `studyplan/testing/test_prompt_design.py` and app tests assert that prompts from `build_generation_prompt` contain "Schema:" and "Rules:" and "Payload JSON:" in that order.
- **Manual check**: When adding a new AI action, use `get_task_prompt_spec` (or equivalent constants) and one of the canonical builders; do not add a new ad-hoc prompt assembly path.

---

## 7. Summary

- **Economy**: One block per action; shared snippets; truncated context.
- **Efficiency**: One task per call; one-line schema; 5–8 rule bullets; single builder per prompt type.
- **Effectiveness**: Task-specific rules and allowed values in `_TASK_SPECS` and role text.

The app does **not** introduce a separate “3Es template” or duplicate builder. It documents that `build_generation_prompt`, `build_syllabus_extraction_prompt`, and `build_judge_prompt_3es` are the 3Es implementation and that all generation-style prompts flow through them.
