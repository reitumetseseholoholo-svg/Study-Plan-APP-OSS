# Syllabus ingest and stability plan

Plan to **stabilize syllabus structure mappings, concept graph building, and outcome coverage breadth** so the app reliably ingests all relevant data from PDF or RAG and keeps a single, consistent model of the module.

---

## Goals

1. **Single source of truth**: One coherent `syllabus_structure` (and related fields) regardless of whether data came from **Import Syllabus PDF** or **Reconfigure from RAG**.
2. **Stable mappings**: Outcome ids, chapter ↔ outcome mapping, and subtopics do not flip or fragment across imports or reconfig runs.
3. **Full breadth**: Every learning outcome and section from the syllabus/study guide is represented; coverage metrics reflect the full syllabus.
4. **Concept graph consistency**: The canonical concept graph is built from the same syllabus data and invalidated when that data changes.

---

## Current state (brief)

| Layer | Current behaviour | Gaps |
|-------|-------------------|------|
| **PDF ingest** | Layout-aware extraction → parse sections 2, 4, 5 (generic) or FR-specific parser; section-4 subtopics for FR; merge subtopics on re-import. | Section 4/5 can be missed or mis-bounded; outcome ids from generic parser not stable across runs; no single “canonical outcome id” scheme. |
| **RAG ingest** | `reconfigure_from_rag` uses cached chunks, batched LLM extraction, validation; prefers syllabus PDFs in retrieval. | Outcome ids can change between runs; chapter assignment can drift; no mandatory reconciliation with existing outcome set. |
| **Syllabus structure** | `syllabus_structure[chapter]`: capability, subtopics, learning_outcomes, outcome_count. Loaded/saved with module config. | Id stability, chapter–outcome alignment, and “no drop” of existing outcomes on merge need to be explicit. |
| **Concept graph** | Built from `syllabus_structure` (capability, subtopics, outcomes); signature from `_concept_signature_payload`; outcome→subconcept links by text similarity. | Rebuild when structure changes; ensure subtopics and outcomes from both PDF and RAG are included. |
| **Outcome coverage** | `outcome_stats` updated only when a question resolves to an outcome_id; `resolve_question_outcomes`: explicit outcome_ids → capability/semantic → bucket. | Coverage breadth is limited by (a) how many outcomes exist in structure, (b) how many questions are linked. Unlinked outcomes never get “covered” by questions. |

---

## 1. Stabilize syllabus structure mappings

### 1.1 Canonical outcome ids

- **Rule**: Each learning outcome has a **stable id** that does not change between PDF re-imports or RAG reconfig runs.
- **Options** (choose one or combine):
  - **A** – Id from syllabus position: e.g. `{section_letter}{subsection_num}{bullet_letter}` (FR already does A1a, B2c, …). Generic parser should emit similar (e.g. `1.2.c` or `Ch3.o2`).
  - **B** – Id from content: `hash(normalize(text))` or `chapter_slug + "_" + index`. Good for RAG-extracted outcomes that don’t have section numbers.
  - **C** – On merge: match new outcomes to existing by normalized text; reuse existing id when match found; assign new stable id only for genuinely new outcomes.
- **Implementation**:
  - In **generic parser** (`parse_syllabus_pdf_text` / `_parse_syllabus_generic`): assign ids like `{letter}.{idx}` or `{section_id}.{letter}` so they are deterministic for the same PDF.
  - In **FR parser**: already stable (A1a, B7g, …); keep as-is.
  - In **reconfigure_from_rag**: before merging into `syllabus_structure`, run an **id reconciliation** step: for each extracted outcome, try to find an existing outcome in the same chapter with same or very similar text; if found, keep existing id; otherwise assign new id via (A) or (B) and ensure uniqueness per chapter.

### 1.2 Section boundaries (PDF)

- **Problem**: Sections “4. The syllabus” and “5. Detailed study guide” are found by regex; noisy PDFs or alternate headings can skip or mis-bound content.
- **Improvements**:
  - Use **last occurrence** of the section heading (already in place) to avoid ToC.
  - Optional: allow **configurable heading patterns** per exam (e.g. “4. The syllabus” vs “4. Syllabus”) in module or schema.
  - Log or surface when section 4 or 5 is empty so the user knows to try “Improve with AI” or RAG reconfig.

### 1.3 Merge policy on re-import / reconfig

- **On Import Syllabus PDF** (or Apply after review):
  - **Chapters**: Preserve existing module chapters (already in place).
  - **Subtopics**: Merge with existing (already in place); dedupe, existing first.
  - **Learning outcomes**: **Merge**, do not replace. For each chapter:
    - Match new outcomes to existing by id or by normalized text.
    - If matched by id: update text/level if changed.
    - If matched by text only: keep existing id.
    - If new (no match): append with a new stable id.
  - **Capabilities / aliases**: Merge; new keys added, existing preserved.
- **On Reconfigure from RAG**:
  - Same merge policy as above so RAG-extracted outcomes **add or update** rather than wipe.
  - Run **id reconciliation** (see 1.1) before merge so RAG outcome ids align with existing when possible.

### 1.4 Chapter–outcome alignment

- After any LLM-based extraction (RAG or “Improve with AI”):
  - **Validation**: For each outcome, check that its assigned chapter is in the module’s `chapters` list.
  - **Reassignment**: If an outcome’s text clearly fits another chapter better (e.g. keyword or embedding similarity), optionally move or flag it; prefer high-confidence moves only so we don’t create noise.

---

## 2. Concept graph stability

### 2.1 Build from one source

- Concept graph is built from **current** `syllabus_structure` (and thus from whatever was last applied: PDF import, RAG reconfig, or manual edit).
- **Signature**: Already based on `_concept_signature_payload()` (chapters, capability, subtopics, outcomes). Keep it so any change to structure invalidates the graph.

### 2.2 Invalidation

- When **syllabus_structure** (or chapters) is updated (after import or reconfig apply):
  - Set `concept_graph_meta.signature = None` or force a rebuild on next `get_canonical_concept_graph()` so the graph is regenerated from the new structure.
- Optionally: **persist** the graph in module config so it survives restart; still rebuild when signature changes.

### 2.3 Subtopics and outcomes from both PDF and RAG

- **Subtopics**: Already populated from section 4 (FR) and merged on re-import. Ensure RAG reconfig can also **add or refine** subtopics per chapter (e.g. from “main syllabus sections” extraction) and that they are merged, not replaced.
- **Outcome→concept links**: Concept graph links each outcome to a subconcept (or chapter) by text similarity. As long as outcomes are stable and complete (see §1), the graph will reflect full syllabus breadth.

---

## 3. Outcome coverage breadth

### 3.1 Ensure full outcome set

- **Coverage** = “how many syllabus outcomes have been touched by at least one correct (or attempted) question”.
- Breadth is only as good as (1) the number of outcomes in `syllabus_structure`, and (2) the number of questions that resolve to those outcomes.
- **Actions**:
  - **Ingest**: Apply §1 so that **all** outcomes from PDF or RAG end up in `syllabus_structure` with stable ids (no silent drop, merge not replace).
  - **Diagnostics**: “Outcome coverage” in View Module Metadata already shows “Questions with resolved outcome: N / M”. Add or expose: “Syllabus outcomes: K” and “Outcomes with at least one linked question: L / K” so the user sees whether the **syllabus** is fully represented and how many outcomes are linkable.

### 3.2 Question–outcome linking

- **Resolution order** (keep): explicit `question.outcome_ids` / `question.outcomes` → capability + semantic match → deterministic bucket.
- **Improvements**:
  - **Schema/docs**: Document in `module_schema.json` and USER_GUIDE that questions should carry `outcome_ids` (or `outcomes`) for accurate coverage; unlinked questions don’t advance outcome coverage.
  - **UI**: In Module Editor or Tools, allow **assigning outcome_ids to questions** (e.g. per-chapter outcome picker) so users can fix unlinked questions and maximize breadth.
  - **RAG / import**: When generating or importing questions, prefer attaching outcome_ids from the current `syllabus_structure` when the question clearly maps to an outcome (e.g. via LLM or keyword match).

### 3.3 Coverage stats consistency

- `outcome_stats` is keyed by chapter and outcome_id. When **syllabus_structure** gains new outcomes (from merge or reconfig):
  - **Coerce** `outcome_stats` so that any outcome_id that no longer exists in structure is dropped (or archived) and new outcome_ids get default (e.g. 0 covered).
  - On load, run a quick **reconcile** so stats only reference current outcome ids; avoid stale ids from old imports.

---

## 4. Ingest pipeline (PDF and RAG)

### 4.1 Single schema, two entry points

- **PDF path**: File → layout-aware extraction → `parse_syllabus_pdf_text` (generic or FR) → `build_module_config_from_syllabus` → **merge** into existing config (chapters preserved, outcomes/subtopics/capabilities merged).
- **RAG path**: Cached chunks (syllabus + study guide) → `reconfigure_from_rag` → LLM extraction (outcomes, capabilities, aliases, etc.) → **id reconciliation** → **merge** into existing config (same merge policy as PDF).
- **Output**: Both paths produce/update the same fields: `syllabus_structure`, `syllabus_meta`, `capabilities`, `aliases`, `importance_weights`. No second-class fields; one schema.

### 4.2 What “all relevant data” means

- From **syllabus PDF**: Sections 2 (capabilities), 4 (syllabus / subtopics), 5 (detailed study guide / outcomes). Optionally exam window, reference PDFs.
- From **study guide / RAG**: Same outcomes and section titles; aliases; optional weighting text. RAG fills gaps when PDF parse is incomplete or when the user hasn’t uploaded a new PDF.
- **Completeness checks** (optional but useful):
  - After parse or reconfig: compare outcome count to a known baseline (e.g. FR has ~95 outcomes) or to previous run; warn if count drops sharply.
  - Surface in View Module Metadata: “Declared outcomes: N (expected range for this exam: …)” when we have a per-exam expectation.

---

## 5. Dynamic compute: when to (re)run intelligence

Treat syllabus structure, concept graph, and outcome coverage as **computed from sources** rather than a one-off import. Re-run when inputs change or when quality signals say so.

### 5.1 Triggers (when to recompute or refresh)

- **Explicit**: User runs **Import Syllabus PDF**, **Reconfigure from RAG**, or a new action e.g. **Refresh syllabus intelligence** (re-run parse/reconfig from current sources without re-uploading).
- **Source change**: When RAG PDFs or syllabus source change (e.g. new file added to RAG, `syllabus_meta.source_pdf` / `reference_pdfs` updated) → optionally prompt or auto-schedule a reconfig so structure stays in sync with docs.
- **Module load**: When switching or loading a module, ensure structure and concept graph are **valid for this module** (reconcile outcome_stats to current outcome ids; rebuild graph if signature mismatch). No full re-parse unless user asks.
- **On low quality**: When diagnostics show low outcome count, empty section 4/5, or coverage far below expectation → suggest “Re-run from RAG” or “Improve with AI” so the user can improve the intelligence in one click.

### 5.2 “Refresh syllabus intelligence” (single action)

- **Idea**: One action that “recomputes syllabus intelligence from current sources” without re-uploading a PDF.
  - If RAG has syllabus/study-guide chunks for this module: run **Reconfigure from RAG** (id reconciliation + merge).
  - If `syllabus_meta.source_pdf` exists and is readable: optionally re-extract text and re-parse (e.g. for layout fix or parser fix), then merge.
  - Always: reconcile outcome_stats to current outcome ids; invalidate concept graph so next use rebuilds.
- **Place**: Module menu or Module Editor, e.g. “Refresh syllabus intelligence from RAG / source PDF”.

### 5.3 Optional: background or on-load freshness

- **On app or module load**: Check “syllabus intelligence freshness” (e.g. hash of source PDF paths + mtime vs last applied); if sources changed and user preference allows, suggest “Syllabus sources updated. Refresh intelligence?” or run a lightweight reconfig in background and show diff.
- **No automatic overwrite**: Any re-run should merge (see §1.3) and, for RAG, require or suggest user confirmation before applying so the user stays in control.

---

## 6. Improving quality of essential intelligence actions

Make each intelligence action (parse, reconfig, merge, graph build, coverage reconcile) **observable and improvable** via validation, confidence, and feedback.

### 6.1 Validation gates (hard quality)

- **After parse**: Validate against schema (outcome id, text, level; chapter in list). Block apply or show hard errors if validation fails.
- **After reconfig**: Same validation; reject or flag proposed config when outcome→chapter assignment is invalid or outcome ids are malformed.
- **After merge**: Ensure no duplicate outcome ids per chapter; no outcome with empty id or empty text in final structure.

### 6.2 Confidence and soft quality

- **Parse confidence**: Already present (ratio of capabilities/chapters/outcomes found). Use it to:
  - Show in review wizard and in View Module Metadata.
  - When low, suggest “Add study guide to RAG and run Reconfigure from RAG” or “Use Improve with AI” to fill gaps.
- **Reconfig confidence**: `compute_reconfig_confidence` (validation, outcome count, chapter coverage). Extend with outcome id stability vs previous config; when confidence is low, show diff and require explicit apply.

### 6.3 Feedback loop (diagnostics → action)

- **View Module Metadata** (and optional dashboard card) as the “syllabus intelligence health” panel:
  - Syllabus outcomes: K. Outcomes with ≥1 linked question: L. Questions with resolved outcome: N / M.
  - When K is 0 or very low → “Import Syllabus PDF or Reconfigure from RAG to add outcomes.”
  - When L ≪ K → “Many outcomes have no linked questions. Link questions to outcomes for accurate coverage (Module Editor or outcome picker).”
  - When section 4/5 was empty on last parse → “Consider Improve with AI or add study guide to RAG.”
- **Actionable hints**: Short, one-line suggestions tied to each metric so the user knows the next step to improve quality.

### 6.4 Quality metrics to expose

| Metric | Where | Use |
|--------|--------|-----|
| Outcome count (syllabus) | Module Metadata, optional dashboard | Compare to expected range; warn if drop. |
| Outcomes with linked questions | Module Metadata | Breadth of linkable coverage. |
| Parse / reconfig confidence | Review wizard, Module Metadata | Decide apply or retry. |
| Concept graph status | Diagnostics / Insights | Built, error, or stale (signature mismatch). |
| outcome_stats reconciled | On load/apply (log or debug) | Ensure no stale ids. |

### 6.5 Optional: automatic quality checks after apply

- After every apply (import or reconfig): run a short **quality check** (outcome count vs previous, validation errors, coverage delta). If outcome count dropped by more than X% or validation failed, show a brief warning and suggest “Re-run from RAG” or “Review and re-import” so the user can correct quickly.

---

## 7. Implementation order

| Phase | Focus | Deliverables |
|-------|--------|---------------|
| **1** | Stable outcome ids and merge policy | (1) Id reconciliation in RAG reconfig and in `build_module_config_from_syllabus` for outcomes. (2) Merge outcomes (by id/text match) instead of replace on import and reconfig. (3) Generic parser emits deterministic ids. |
| **2** | Concept graph invalidation | (1) On apply of syllabus/reconfig, clear or invalidate concept graph so next use rebuilds. (2) Optional: persist graph in module config and reload when signature matches. |
| **3** | Outcome coverage breadth and diagnostics | (1) Reconcile `outcome_stats` to current outcome ids on load/apply. (2) View Module Metadata (or similar) shows “Syllabus outcomes” and “Outcomes with linked questions”. (3) Document outcome_ids in schema and USER_GUIDE; optional UI to assign outcome_ids to questions. |
| **4** | Section boundaries and RAG subtopics | (1) Optional configurable section patterns; log/surface empty section 4/5. (2) RAG reconfig can propose subtopics; merge into syllabus_structure like PDF section-4. **Done:** empty_sections in parse result (generic + FR); last_parse_empty_sections in syllabus_meta; View Module Metadata shows "Sections empty on last PDF parse" with hint. RAG _extract_subtopics_by_chapter + structure[ch].subtopics merged on apply. |
| **5** | Dynamic compute and refresh | (1) “Refresh syllabus intelligence” action: re-run reconfig from RAG / re-parse source PDF, merge, reconcile stats, invalidate graph. (2) On module load: reconcile outcome_stats; rebuild graph if signature mismatch. (3) Optional: suggest refresh when RAG/source PDF changed. **Done:** Menu “Refresh syllabus intelligence…” (Module + Tools→Module); if RAG paths exist runs Reconfigure from RAG; else re-parses syllabus_meta.source_pdf and applies draft. |
| **6** | Quality of intelligence actions | (1) Validation gates after parse/reconfig/merge; block or flag invalid apply. (2) Module Metadata as health panel: metrics + actionable hints (e.g. “Add RAG”, “Link questions”). (3) Optional: post-apply quality check (outcome count delta, validation) with one-click “Re-run from RAG” suggestion. **Done:** View Module Metadata “Suggestions” with hints when K low, L≪K, or section 4/5 empty; validate merged config on Apply (flag in notification); post-apply notification if outcome count dropped >20%. |

This order keeps **mappings and ids** stable first, then **graph and coverage** consistent, then **breadth and diagnostics**, then **niceties**, then **dynamic refresh** and **quality feedback**.

---

## 8. Success criteria

- Re-importing the same syllabus PDF or running Reconfigure from RAG twice does not change outcome ids for unchanged content.
- Concept graph reflects the current syllabus_structure (subtopics + outcomes) and is rebuilt when structure changes.
- Outcome coverage metrics refer only to outcomes that exist in the current syllabus_structure, and the app surfaces how many outcomes are in the syllabus vs how many have at least one linked question.
- All outcomes and subtopics extracted from PDF (sections 2, 4, 5) or from RAG are present in the module config after apply (merge, no silent drop).
- Syllabus intelligence can be refreshed from current sources (RAG / source PDF) via one action; quality metrics and hints in Module Metadata guide the user to improve outcomes, linking, and coverage.
