# RAG reconfiguration streamlining plan (accuracy-first, then efficiency)

This document outlines how to streamline the **RAG-based module reconfiguration pipeline** so that:

1. **Accuracy comes first** – we always maintain a correct, stable `syllabus_structure`.
2. **Time and resource use are minimized** – we avoid unnecessary LLM calls, chunking, and full re-runs.

It builds on:

- `docs/RAG_AND_MODULE_IMPROVEMENTS.md`
- `docs/SYLLABUS_INGEST_AND_STABILITY_PLAN.md`
- `MODULE_RECONFIG_PLAN.md`
- Existing code in `studyplan/module_reconfig/reconfig.py` and `studyplan_ai_tutor.py`.

---

## 1. Goals

- **Accuracy-first**:
  - Preserve or improve the correctness and completeness of:
    - `syllabus_structure[chapter].learning_outcomes` (id, text, level).
    - `capabilities`, `aliases`.
  - Never silently degrade outcome coverage or corrupt chapter mappings.

- **Time/resource efficiency**:
  - Avoid re-parsing or re-chunking PDFs unnecessarily.
  - Avoid re-running LLM extraction for chapters that are already “healthy”.
  - Split reconfig into **fast** and **deep** modes so users (and CI) can choose.

---

## 2. Scope of RAG reconfig (what it must and need not do)

### 2.1 Mandatory responsibilities

- Maintain a **complete, stable syllabus outcome model**:
  - Each chapter in `chapters` has a reasonable set of outcomes.
  - Outcome IDs are stable across runs as per `SYLLABUS_INGEST_AND_STABILITY_PLAN`.
  - Outcome text and levels are accurate enough to support planning and coverage.

### 2.2 Optional / secondary responsibilities

- Enrich:
  - `subtopics` per chapter.
  - `aliases` and `semantic_aliases`.
  - `importance_weights`.
  - Extra syllabus metadata.

These should be treated as **secondary passes** that can be skipped or deferred when time is limited.

---

## 3. Accuracy-first strategies

### 3.1 Treat existing structure as hard constraints

- Always supply the LLM with:
  - The **exact current chapter list** from config.
  - Any existing outcomes (id + text + level) per chapter when available.

Prompt rules:

- “Map each extracted outcome to exactly one of these chapters (copy name verbatim).”
- “When an outcome text matches an existing one, reuse the existing id.”
- “Do not invent new chapter names.”

This keeps chapter mapping and IDs stable.

### 3.2 Restrict fast mode to outcomes-only

Define a **fast outcome-refresh mode** where the LLM is only responsible for:

- Ensuring each chapter has a sensible set of `learning_outcomes` (id, text, level, chapter).
- It does **not** attempt to:
  - Rebuild `aliases`.
  - Recompute `importance_weights`.
  - Rewrite free-form descriptions.

Use `SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE` as the schema and a short rule list:

- Only output `outcomes[]` and minimal `warnings[]`.
- Use allowed chapter names only.
- Levels ∈ {1, 2, 3}.

### 3.3 Hard validation gates before merge

Before applying any RAG reconfig proposal:

- Validate against `module_schema.json`.
- Enforce:
  - No duplicate outcome IDs per chapter.
  - No empty `id` / `text`.
  - Every outcome’s `chapter` is in `chapters`.

Additionally:

- Compare outcome counts per chapter to pre-run counts:
  - If a chapter’s outcome count drops by more than a threshold (e.g. 20–30%), treat this as a hard error or require explicit user confirmation.

### 3.4 Make reconfig idempotent

- When re-running on the same syllabus/study-guide set, the combination of:
  - ID reconciliation by text match.
  - Chapter-constrained assignment.
- Should ensure that unchanged content yields **unchanged outcome IDs** and overall structure.

---

## 4. Time and efficiency improvements

### 4.1 Never re-chunk when you can reuse

- Rely on the existing **RAG chunk cache**:
  - Keys: path + size + mtime (+ parser version).
  - Already used by tutor and reconfig.

Rule:

- Only re-chunk when:
  - The PDF path is new, or
  - File size/mtime changed, or
  - Chunking parameters have changed (version bump).

### 4.2 Incremental chapter targeting

Before any LLM call:

1. Compute an **incremental target set** of chapters:
   - Chapters with `outcome_count == 0`.
   - Chapters with outcome counts far below:
     - The median/mean across chapters, or
     - A known exam baseline, when available.
   - Chapters flagged as problematic in previous diagnostics.
2. Only run RAG+LLM extraction for chapters in this target set.

All other chapters keep their existing outcomes.

### 4.3 Two-tier reconfig modes

Introduce two user-facing modes:

- **Fast syllabus refresh (AI, partial)**:
  - Acts only on the incremental target set from 4.2.
  - Outcomes-only extraction (no aliases/weights).
  - Strict character and token budget per batch.
  - Happens quickly, can be used frequently.

- **Full reconfigure from RAG…**:
  - Current, richer behavior:
    - Outcomes + subtopics + aliases + weights.
  - Still bounded by budgets, but allowed to run longer.
  - User-driven and optional.

### 4.4 Batching and char budgets

For both fast and full modes:

- Use small **per-batch char budgets** (e.g. 2–4k chars from RAG snippets).
- Batch 3–6 chapters per call where possible:
  - Enough context for the model to see patterns.
  - Not so many that it harms accuracy or latency.

Ensure:

- `max_input_chars` and `max_tokens` are enforced per call.
- Exceeding budgets should truncate snippets, not stall the app.

### 4.5 Background execution and resumability

- Run reconfig steps in a **background thread**:
  - UI shows “Syllabus refresh in progress…” with a non-blocking indicator.
- Persist:
  - Per-chapter results and diagnostics.
  - A simple “last completed chapter” or batch identifier to support:
    - “Continue from where you left off” if interrupted.

---

## 5. Diagnostics and user feedback

### 5.1 Pre- and post-run metrics

Before reconfig:

- Snapshot:
  - Outcome counts per chapter.
  - Total syllabus outcome count `K`.

After reconfig:

- Show:
  - New outcome counts per chapter (highlight large deltas).
  - New total `K'`.
  - Chapters updated in this run.

For fast mode, keep the summary short but explicit:

- “Updated outcomes for 3 chapters. Total outcomes: 94 → 102.”

### 5.2 Suggestions instead of silent changes

When confidence or validation is borderline:

- Store proposals as **pending drafts** rather than applying immediately.
- Module Editor or a small “Syllabus intelligence” panel can show:
  - “Chapters with pending AI updates.”
  - Buttons: **Apply** / **Discard**.

---

## 6. Implementation steps

1. **Add incremental targeting helper**  
   - Small engine-level function that computes the “target chapter set” based on outcome counts and diagnostics.

2. **Introduce fast outcome-only reconfig mode**  
   - Wrap `reconfigure_from_rag` or a lighter variant to:
     - Limit to target chapters.
     - Use outcomes-only schema and prompts.

3. **Wire two menu entries**  
   - “Fast syllabus refresh (AI, partial)” → calls fast mode.
   - “Full reconfigure from RAG…” → keeps current behavior.

4. **Add pre/post metrics and safety checks**  
   - Outcome count delta checks.
   - Hard rejection or warnings on large negative deltas.

5. **Optional**: background + resumable execution  
   - Move fast mode into a background job with simple progress tracking.

This plan keeps the **core promise** of RAG reconfig: a high-quality, AI-assisted syllabus model, while making it **incremental, measurable, and much more responsive** in day-to-day use. 

