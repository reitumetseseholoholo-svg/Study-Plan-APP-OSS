# AI-driven outcome building and linking pipeline

This document describes a combined pipeline for:

1. **Automatic outcome building** – extracting and maintaining `learning_outcomes` in `syllabus_structure` using AI + RAG.
2. **Automatic outcome linking** – attaching `outcome_ids` to questions in the question bank with AI assistance.

It builds on:

- `docs/SYLLABUS_INGEST_AND_STABILITY_PLAN.md`
- `docs/CORE_FEATURE_IMPROVEMENT_OUTCOME_LINKING.md`
- `docs/AI_OUTCOME_LINKING_AUTOMATION.md`
- `studyplan/ai/prompt_design.py` (shared prompt contracts)
- `studyplan_engine.py` and `studyplan/module_reconfig/reconfig.py`

The goal is to make **“Refresh syllabus intelligence & link outcomes”** a largely automated, resource-efficient routine with clear guardrails.

---

## 1. High-level flow

For a given module:

1. **Ensure syllabus outcomes are complete and stable**
   - If `syllabus_structure` is empty or clearly incomplete, run **AI-assisted outcome extraction** from the latest syllabus/study-guide PDFs via RAG.
   - Merge extracted outcomes into `syllabus_structure` using stable ID rules.
2. **Build/refresh the canonical concept graph**
   - Use `build_canonical_concept_graph` from `studyplan_engine` so each outcome is attached to a chapter/subconcept node.
3. **Auto-link questions to outcomes**
   - For each question in the bank, generate candidate outcome IDs using cheap heuristics (chapter restriction, lexical overlap, concept graph proximity).
   - For questions with reasonable candidates and no explicit `outcome_ids`, call a **batched LLM linker** to choose the best outcomes per question.
   - Apply high-confidence links directly; stage lower-confidence ones as suggestions.
4. **Update diagnostics and coverage**
   - Recompute `outcome_stats` and surface updated coverage metrics in Module Metadata.

This flow is exposed via a single user-facing action such as:

> Module → **Refresh syllabus intelligence & link outcomes (AI)**

---

## 2. Automatic outcome building (syllabus_structure)

### 2.1 Inputs

- `pdf_text` for syllabus / study guide (from PDF import or existing RAG cache).
- Current module config, including:
  - `chapters`
  - Existing `syllabus_structure`
  - `capabilities`, `aliases`, `semantic_aliases`
- Local LLM endpoint (llama-server or Ollama fallback).

### 2.2 Extraction: parse_syllabus_with_ai + RAG

Implementation is already largely in place via:

- `StudyPlanEngine.parse_syllabus_with_ai`
- `studyplan/ai/prompt_design.build_syllabus_extraction_prompt`
- `SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE`

The extraction process:

1. **Chunk syllabus/study-guide text**
   - Use the internal chunker in `parse_syllabus_with_ai` or the RAG chunker for PDFs (reused from tutor).
2. **Per-chapter retrieval**
   - For each chapter in `chapters`, build a set of queries (chapter title, stripped title, aliases).
   - Retrieve top-k relevant chunks for that chapter.
3. **LLM extraction per batch of chapters**
   - Use `build_syllabus_extraction_prompt` with:
     - Syllabus excerpts (RAG snippets) as `syllabus_text`.
     - The module’s chapter list as `chapters_blob`.
   - Schema: `SYLLABUS_OUTCOMES_SCHEMA_ONE_LINE` ensures:
     - `outcomes[]` with `id`, `text`, `level`, `chapter`.
   - Run over small chapter batches to keep token counts controlled.

### 2.3 Merge into syllabus_structure

After extraction, perform a merge step as per `SYLLABUS_INGEST_AND_STABILITY_PLAN.md`:

- For each extracted outcome:
  - **Match by chapter** using the `chapter` field (must be one of the existing chapter titles).
  - Inside the chapter:
    - If outcome text matches an existing outcome (normalized), **reuse the existing id**.
    - Else generate a **stable id**:
      - From position (`A1a`, `B2c`) when predictable.
      - Or from a hash/slug of normalized text + chapter when not.
- Ensure:
  - No duplicate outcome IDs per chapter.
  - No empty `id` or `text`.

Update:

- `syllabus_structure[chapter].learning_outcomes`
- `syllabus_structure[chapter].outcome_count`
- `syllabus_structure[chapter].subtopics` when RAG provides more granular headings.

### 2.4 Confidence and application

Before applying:

- Validate with the strict module schema (`module_schema.json`).
- Compute `reconfig` confidence (existing `compute_reconfig_confidence`).
- If confidence ≥ threshold (e.g. 0.75), auto-apply; else:
  - Surface the proposal in Module Editor for manual review.
  - Do not overwrite existing config without explicit user action.

On apply:

- Invalidate the concept graph (`concept_graph_meta.signature = None`).
- Rebuild concept graph on next access.

---

## 3. Automatic outcome linking (question bank)

For detailed design, see `docs/AI_OUTCOME_LINKING_AUTOMATION.md`. This section summarises the pipeline and highlights glue points with outcome building.

### 3.1 Candidate generation (no AI)

For each question `q` in chapter `ch`:

1. **Skip if explicitly tagged**
   - If `q.outcome_ids` is a non-empty list → keep as-is (do not overwrite).
2. **Initial candidate pool**
   - Outcomes: `syllabus_structure[ch].learning_outcomes`.
   - Build a small pool (e.g. up to 10) of candidates by:
     - **Lexical score** between question text and outcome text (token overlap / BM25-lite).
     - **Concept graph proximity**:
       - Use `resolve_question_concepts(ch, idx)`:
         - For each outcome id, see which concept/subconcept the concept graph links it to.
         - Boost outcomes in the same subconcept(s) as the question.
3. **Prune**
   - Keep only top K candidates (e.g. 3–5) with non-trivial scores.
   - If no outcome passes a minimal score threshold, mark `q` as “no candidate” and skip AI for that question.

This step is pure Python and runs quickly even for large banks.

### 3.2 Batched LLM linking

Group questions by chapter into batches of size `B` (e.g. 5–10 questions).

For each batch, construct a payload:

```json
{
  "chapter": "C Working capital management",
  "learning_outcomes": [
    {"id": "C1a", "text": "Explain the nature and elements of working capital."},
    {"id": "C1b", "text": "Calculate working capital cycle and identify improvements."}
  ],
  "questions": [
    {
      "id": "q1",
      "text": "A company has the following data... Calculate the working capital cycle and comment on its efficiency.",
      "candidate_outcome_ids": ["C1a", "C1b"]
    },
    {
      "id": "q2",
      "text": "Define working capital and describe its main components.",
      "candidate_outcome_ids": ["C1a"]
    }
  ]
}
```

Prompt contract (built with `build_generation_prompt`):

- **Role/style**: “You link exam questions to syllabus learning outcomes. Use only the provided candidate outcome ids for each question.”
- **Schema** (one line):

```json
{"links":[{"question_id":"...","outcome_ids":["..."]}]}
```

- **Rules**:
  - Only choose from `candidate_outcome_ids` for that question.
  - Choose 0–N outcomes; if none fits, use an empty list.
  - Copy `question_id` exactly.
  - Do not invent new outcome IDs or change texts.
  - `JSON_ONLY_NO_MARKDOWN` / `JSON_ONLY_NO_PROSE`.
- **Payload JSON**: the batch payload above.

The LLM returns:

```json
{
  "links": [
    {"question_id": "q1", "outcome_ids": ["C1b"]},
    {"question_id": "q2", "outcome_ids": ["C1a"]}
  ]
}
```

### 3.3 Confidence and application

For each suggested link `(q_id, outcome_ids[])`:

- Compute a confidence score based on:
  - Lexical match margin between chosen outcomes and runner-ups.
  - Whether chosen outcomes were top-ranked by heuristics.
  - Optional per-question indicators (e.g. very long/very short questions).

Policy:

- If `confidence >= AUTO_LINK_THRESHOLD` (e.g. 0.8):
  - Merge into `q.outcome_ids` (append if not present, avoid duplicates).
- If confidence lower:
  - Store under a **“suggested_links”** structure, e.g.:

```json
{
  "module_id": "acca_f9",
  "chapter": "C Working capital management",
  "question_index": 12,
  "suggested_outcome_ids": ["C1b"],
  "confidence": 0.65
}
```

These suggestions can be surfaced in Module Editor as:

- “AI-suggested outcomes” per question.
- A filter “Show only questions with AI suggestions”.

### 3.4 Caching

To avoid recomputing links when nothing material has changed:

- Cache per `(module_id, chapter, normalized_question_text)`:
  - `outcome_ids`, `confidence`, `source` (`explicit`, `ai_high_conf`, `ai_suggested`).
- On rerun:
  - Reuse links when question text and outcome IDs are still valid.
  - Invalidate cached links whose outcome IDs are no longer present in `syllabus_structure`.

---

## 4. Combined “Refresh & link” action

User-facing flow:

1. User triggers: **Module → Refresh syllabus intelligence & link outcomes (AI)**.
2. Engine:
   - Checks syllabus freshness and completeness (as per `SYLLABUS_INGEST_AND_STABILITY_PLAN`).
   - Optionally runs `parse_syllabus_with_ai` or `reconfigure_from_rag` when needed.
   - Applies valid outcome updates (based on confidence + validation).
   - Rebuilds concept graph if structure changed.
   - Runs automatic outcome linking as in §3.
3. UI displays a summary:
   - New/updated outcomes: X.
   - Syllabus outcomes with ≥1 linked question: L / K.
   - Questions auto-linked (high-confidence): N.
   - Questions with AI suggestions pending review: P.

This keeps the **heavy lifting on AI**, but wraps it in deterministic guardrails and clear diagnostics so users remain in control of their module intelligence. 

