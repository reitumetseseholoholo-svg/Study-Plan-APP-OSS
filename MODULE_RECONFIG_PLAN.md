# Module reconfiguration from RAG (syllabus & study guide)

Plan for updating module structure in a **non-resource-heavy** way using the official syllabus and study guide PDFs already in RAG, so the app accurately understands **aliases**, **importance weights**, **learning outcomes**, and **main syllabus sections**. Includes a dedicated module that AI models can reconfigure using RAG-amplified knowledge, plus schema and question–outcome linking (points 3 & 4).

---

## Goals

1. **Use existing RAG files** (syllabus + study guide PDFs) to refresh module structure without re-uploading or re-parsing the full PDF every time.
2. **Keep cost and latency low**: reuse cached RAG chunks, targeted retrieval, small schema-bound LLM calls, optional diff-and-apply.
3. **Accurate model of the module**: learning outcomes (id, text, level), main syllabus sections (capabilities, chapter list), aliases, importance weights.
4. **AI-reconfigurable module**: a single component that consumes RAG context and produces a valid, schema-validated config delta.
5. **Point 3**: Question–outcome linking — document and surface so coverage is accurate; allow assigning outcome tags.
6. **Point 4**: Strict schema for `syllabus_structure` and related fields so validation catches bad data and AI outputs are well-formed.

---

## Current state

- **RAG PDFs**: Come from `syllabus_meta.reference_pdfs`, env `STUDYPLAN_AI_TUTOR_RAG_PDFS`, and app preference `ai_tutor_rag_pdfs`. Syllabus PDF is often the same as the one used for import; study guide may be separate. Chunks are built with `chunk_text_for_rag` and cached per file (path + size + mtime).
- **Syllabus import**: Full PDF text → deterministic parse (sections 2, 4, 5) or “Improve with AI” (RAG over that PDF in `parse_syllabus_with_ai`). Result is `syllabus_structure` + `syllabus_meta`.
- **Module config**: Loaded from repo `modules/<id>.json` or `MODULES_DIR/<id>.json`; saved from Module Editor to `MODULES_DIR/<id>.json`.
- **Question–outcome**: `resolve_question_outcomes` uses `question.outcome_ids` or `question.outcomes` first; then capability + semantic match; then deterministic bucket. Coverage (`outcome_stats`) only updates when at least one outcome_id is resolved.
- **Schema**: `module_schema.json` has generic `syllabus_structure` (additionalProperties: object) and `syllabus_meta` with a few properties; no strict shape for `learning_outcomes` or for question-level `outcome_ids`.

---

## 1. RAG-amplified module reconfiguration (lightweight)

### 1.1 Data flow

- **Inputs**: `module_id`, current module config (at least `chapters`, `syllabus_structure`, `aliases`, `importance_weights`, `capabilities`), **RAG PDF list** (syllabus + study guide paths already used for tutor), optional `llm_generate` callable.
- **RAG reuse**: Do **not** re-extract PDF to raw text on every run. Use the **same chunked documents** the app already caches for the AI tutor (by path). If a path is “syllabus or study guide” (e.g. from `syllabus_meta.source_pdf` or `syllabus_meta.reference_pdfs`), use its cached chunks for retrieval.
- **Targeted extractions** (each with a small, schema-bound LLM call):
  1. **Learning outcomes**  
     - For each chapter (or batched), run retrieval with chapter title + key terms; get top-k chunks (e.g. 4–8). One prompt per batch (e.g. 4–6 chapters): “From the excerpts below, list every learning outcome: id, text, level (1/2/3), and map to exactly one of these chapters.” Schema: same as `SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE`. Merge into `syllabus_structure[chapter].learning_outcomes`, dedupe by id or normalized text.
  2. **Main syllabus sections**  
     - One retrieval for “main capabilities”, “syllabus”, “section 4”, “section 2” etc. One small LLM call: extract capability letters → titles, and ordered section/chapter titles. Used to refresh `capabilities` and optionally validate/align `chapters`.
  3. **Aliases**  
     - From the same section-4 / study-guide chunks: “alternative names or abbreviations for these chapters” or infer from headings that don’t exactly match `chapters`. Output: `aliases` (and optionally `semantic_aliases`).
  4. **Importance weights**  
     - Option A: From RAG text (“examination weight”, “weighting”) if present. Option B: Derive from existing logic (`_build_importance_weights_from_syllabus`) using the updated `syllabus_structure` (outcome count, level mix). Option C: One short LLM call with retrieved “weighting” excerpts. Prefer B for minimal tokens; add A/C only if needed.

### 1.2 Non-resource-heavy constraints

- **Chunk source**: Use existing cached RAG docs (same as tutor). No extra PDF read or chunking unless cache miss.
- **Retrieval**: Reuse lexical/semantic ranking (e.g. `lexical_rank_rag_chunks` or engine’s `_retrieve_context`-style term matching) with a small token budget per query (e.g. 2–4k chars per batch).
- **LLM**: Few calls per run (e.g. 1 for sections/aliases, 1–2 for outcomes in batches). Schema-first, JSON-only, no long prose.
- **When to run**: On demand (“Reconfigure from RAG” in Module menu or Editor), or optional background after “Import Syllabus PDF” when RAG paths are set. Not on every app startup.
- **Output**: Proposed **delta** (or full proposed config) plus optional diff for user review; apply only on user confirm. Store last run in `syllabus_meta.reconfigured_at` and optionally `reconfigured_from_rag_paths`.

---

## 2. Module that AI can reconfigure

### 2.1 Component: `studyplan.module_reconfig`

- **Location**: `studyplan/module_reconfig/` (package) or `studyplan/module_reconfig.py`.
- **Public API** (conceptually):
  - `get_rag_chunks_for_module(engine, module_id) -> dict[str, list]`  
    Returns path → list of chunk dicts (text, id, source) for PDFs that are “syllabus/study guide” for this module (from `syllabus_meta.source_pdf`, `syllabus_meta.reference_pdfs`, or app RAG list filtered by module).
  - `reconfigure_from_rag(config: dict, chunks_by_path: dict, chapters: list, llm_generate, *, max_tokens=4096) -> dict`  
    Returns a **proposed** module config (full or delta) with:
    - `syllabus_structure` (per-chapter learning_outcomes, capability, outcome_count)
    - `capabilities`
    - `aliases` (and optionally `semantic_aliases`)
    - `importance_weights`
    - `syllabus_meta` (e.g. `reconfigured_at`, `reconfigured_from_rag_paths`)
  - All outputs validated against the **strict** module schema (see §4).

- **Dependencies**: Reuse `studyplan.ai.prompt_design` (syllabus extraction schema, JSON-only rules). Reuse engine’s retrieval pattern (chunk → term/excerpt scoring) or `studyplan_ai_tutor.lexical_rank_rag_chunks` + `build_rag_context_block` so the package does not depend on the GUI app.

### 2.2 Model setup for accurate reconfiguration

- **Same LLM as tutor**: Reconfigure from RAG and Import Syllabus PDF (Improve with AI) use the same model path: llama-server (if configured) first, then the **Local LLM model** set in **Preferences → AI Tutor** (Ollama).
- **Recommended**: Use a capable instruction-following model (e.g. Llama 3.1 8B or larger) so that learning outcomes, levels, and chapter mapping are accurate. Set the model in Preferences → AI Tutor before running Reconfigure from RAG or Improve with AI.
- **Prompt**: Extraction uses a schema-first prompt with rules to copy outcome text verbatim and map each outcome to exactly one chapter; the same prompt is used in batched retrieval in `reconfigure_from_rag`.

### 2.3 App integration

- **Menu**: Module → “Reconfigure from RAG…” (or inside Module Editor as “Reconfigure from RAG”).
- **Flow**: Resolve RAG PDF paths for current module → load cached chunks (same as tutor) → call `reconfigure_from_rag` → show diff (e.g. outcome count per chapter, aliases added, weights changed) → user applies or edits → save to `MODULES_DIR/<module_id>.json`.
- **Engine**: After apply, reload module config so `syllabus_structure`, `aliases`, `importance_weights` are up to date; no need to restart app.

---

## 3. Question–outcome linking (point 3)

### 3.1 Behaviour (already in place)

- Coverage is driven by `outcome_stats`: only questions that resolve to at least one `outcome_id` (via `resolve_question_outcomes`) update coverage when the user answers.
- Resolution order: explicit `question.outcome_ids` or `question.outcomes` → capability + semantic match → deterministic bucket.

### 3.2 Improvements

- **Schema**: In `module_schema.json`, under `questions` (per-chapter question bank), document that each question object may include:
  - `outcome_ids`: array of strings (exact outcome ids from `syllabus_structure`).
  - `outcomes`: array of objects `{ "id": "...", "text": "..." }` for backward compatibility and semantic matching.
- **Docs**: In USER_GUIDE or DEVELOPER_DOC, add a short section: “Outcome coverage: only questions linked to syllabus outcomes (by `outcome_ids` or semantic match) count toward covered outcomes; unlinked questions do not affect coverage.”
- **UI / diagnostics**: In Module Editor or Tools, optionally show:
  - “Questions with outcome links: N / M” per chapter (or globally).
  - A way to **assign outcome tags** to a question: e.g. dropdown or multi-select of the chapter’s `learning_outcomes` (id + short text), writing back to `question.outcome_ids` or `question.outcomes` when saving the module.

---

## 4. Strict schema for syllabus and outcomes (point 4)

### 4.1 `module_schema.json` changes

- **syllabus_structure**  
  - `additionalProperties`: value = object with:
    - **required**: `learning_outcomes` (array).
    - **items** of `learning_outcomes`: object with **required** `id` (string), `text` (string), `level` (integer 1–3).
    - Optional: `capability` (string), `subtopics` (array of strings), `intellectual_level_mix` (object), `outcome_count` (integer).
  - This makes outcome id/text/level the contract for AI and for validation.

- **syllabus_meta**  
  - Add optional: `reconfigured_at` (string, date-time), `reconfigured_from_rag_paths` (array of strings), `reference_pdfs` (array of strings).
  - Keep `additionalProperties: true` for flexibility but document these.

- **questions**  
  - Document (in description or in a `oneOf` / subschema) that per-question objects may have `outcome_ids` (array of strings) and `outcomes` (array of objects with `id` and optional `text`). No need to force required so existing banks remain valid.

### 4.2 Validation

- On **load** of a module config: validate against the strict schema so malformed `learning_outcomes` or invalid `level` are caught early.
- On **reconfig apply** and on **syllabus import**: validate the merged config (or the proposed delta) with the same schema before saving.

---

## 5. Implementation order

1. **Schema** (point 4): Update `module_schema.json` with strict `syllabus_structure` and extended `syllabus_meta`; document question `outcome_ids`/`outcomes`. Ensure engine load path still accepts current modules (backward compatible).
2. **module_reconfig package**: Add `studyplan/module_reconfig/` with:
   - `__init__.py` exporting `reconfigure_from_rag` and a helper to get RAG chunks (or accept chunks from caller).
   - Retrieval + schema-bound extraction for outcomes (batched), sections/aliases, and importance (derived or one small call).
3. **App**: “Reconfigure from RAG” entry point; resolve RAG paths; load chunks; call reconfig; show diff; apply and save.
4. **Docs**: USER_GUIDE or DEVELOPER_DOC — outcome coverage and question linking; DEVELOPER_DOC — syllabus ingestion + reconfig from RAG.
5. **UI (optional)**: “Questions with/without outcome links” and outcome-tag assignment in Module Editor.

---

## 6. Automatic reconfiguration and accuracy

### 6.1 When automatic reconfig runs

- **Trigger**: If **Auto-reconfigure module from RAG** is enabled (Preferences) or `STUDYPLAN_AUTO_RECONFIGURE_RAG=1`, the app runs a **staleness check** a few seconds after startup (and when appropriate after module load).
- **Staleness**: Reconfig is run only when:
  - RAG PDF paths exist for the current module, and
  - Either there is no prior reconfig (`reconfigured_at` missing), or the module has zero outcomes, or at least one RAG file is **newer** than `reconfigured_at`.
- **Execution**: Reconfig runs in a **background thread** (no UI freeze). When finished, the main thread applies the result or notifies the user.

### 6.2 Ensuring accuracy

1. **Validation**: After every reconfig run, the proposed config is validated with `validate_syllabus_structure`. If there are errors, the proposal is **not** applied (and confidence is treated as 0).
2. **Confidence score**: `compute_reconfig_confidence(proposed, original_config, validation_errors)` returns a value in 0..1 based on:
   - No validation errors (otherwise 0).
   - Chapter coverage (share of chapters with at least one outcome).
   - Outcome density (outcomes per chapter; reasonable expectation).
   - Presence of capabilities and aliases from the LLM.
3. **Auto-apply threshold**: Only if confidence ≥ threshold (default **0.75**, overridable via `STUDYPLAN_AUTO_RECONFIGURE_CONFIDENCE`) is the proposed config **automatically** saved and the engine reloaded. Otherwise the proposal is stored as **pending** and the user is notified to review (e.g. via Module → Reconfigure from RAG to run again or apply manually).
4. **Idempotency**: Only one auto-reconfig runs at a time (`_auto_reconfig_in_progress`); duplicate or overlapping runs are skipped.
5. **Audit**: `syllabus_meta.reconfigured_at` and `reconfigured_from_rag_paths` record when and from which PDFs the last reconfig was produced, so users can see the source of the current structure.

### 6.3 Environment and preferences

- **`STUDYPLAN_AUTO_RECONFIGURE_RAG=1`**: Enables automatic reconfig even if the Preferences checkbox is off (e.g. for headless or scripted use).
- **`STUDYPLAN_AUTO_RECONFIGURE_CONFIDENCE`**: Numeric threshold in 0..1 for auto-apply (default 0.75).
- **Preferences → Auto-reconfigure module from RAG when syllabus is stale**: User-facing toggle; persisted in `preferences.json` as `auto_reconfigure_from_rag`. Env overrides the saved value when set.

---

## 7. Success criteria

- Aliases, importance weights, learning outcomes, and main syllabus sections can be updated from the **existing** RAG files (syllabus + study guide) without heavy re-parsing.
- One clear module (`studyplan.module_reconfig`) that AI/reconfig logic uses, with RAG-amplified extraction and schema-validated output.
- Point 3: Question–outcome linking is documented and optionally visible/editable so coverage is accurate.
- Point 4: Strict schema for `syllabus_structure` and related fields; validation on load and on reconfig/import.
- **Automatic reconfig**: When enabled, runs in the background when the syllabus is stale; applies only when confidence ≥ threshold; otherwise notifies for review so accuracy is guarded by validation, confidence scoring, and optional human review.
