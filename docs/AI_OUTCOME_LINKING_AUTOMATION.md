# AI-automated outcome–question linking (resource-efficient design)

This document proposes a concrete, resource-aware design for **AI-assisted linking of questions to syllabus outcomes**, building on the existing outcome–question linking plan in `docs/CORE_FEATURE_IMPROVEMENT_OUTCOME_LINKING.md`.

The goal is to **maximize accuracy and breadth of outcome coverage** while keeping **CPU/VRAM and token costs low**, and preserving **human control** over low-confidence links.

---

## 1. Objectives

- **Accurate links**: For each question, assign 0–N `outcome_ids` that genuinely match the tested outcomes.
- **Resource efficiency**:
  - Prefer **cheap lexical + concept-graph heuristics** over LLM calls.
  - When LLM is needed, use **small, batched, schema-bound calls**.
- **Human-in-the-loop by default**:
  - High-confidence links can be auto-applied.
  - Low-confidence or ambiguous links are **suggestions** to be reviewed in the Module Editor.
- **Stability**: Re-running the pipeline should be mostly idempotent when syllabus outcomes and question text are unchanged.

---

## 2. Pipeline overview

For a given module (with populated `syllabus_structure` and question bank):

1. **Pre-filter candidates per question (no AI)**  
   For each question in chapter `ch`:
   - Normalize question stem text.
   - Build a small candidate set of outcomes using:
     - **Chapter constraint**: consider only outcomes in `syllabus_structure[ch].learning_outcomes`.
     - **Lexical match**:
       - Compute a simple similarity score between the question text and each outcome text (using normalized token overlap or a cheap BM25-like score).
     - **Concept graph / subtopic proximity**:
       - Use `resolve_question_concepts(chapter, idx)` to get `concept_ids` for the question.
       - Map concept IDs back to the outcomes in those concept’s chapter/subtopic region.
       - Boost outcomes whose subconcept or chapter node matches the question’s `concept_ids`.
   - Keep the **top K candidates** (e.g. K=3–5) with scores; drop questions where the best score is below a cheap safe threshold.

2. **Batch LLM linking over groups of questions**
   - Group questions by **chapter** (and optionally by difficulty or type) and create batches of size `B` (e.g. 5–10 questions per call).
   - For each batch, call a local LLM with:
     - Chapter name and a **small list of candidate outcomes** (id + short text).
     - A list of questions:
       - Question stem text.
       - Optional short metadata (e.g. “multiple choice / gap / Section C short form”) if already present.
       - The pre-filtered candidate outcome IDs for this question.
     - Task: **For each question, choose zero or more outcome_ids from its candidate list.**
   - Prompt is schema-first and JSON-only (see §4).

3. **Post-process with confidence scoring**
   - For each `(question, outcome_id)` link suggested by the model:
     - Compute a **confidence score**, e.g. as a weighted combination of:
       - Lexical score of outcome vs question.
       - Margin between the chosen outcome and the second-best candidate.
       - Whether multiple outcomes were selected (single, clearly focused outcomes can be scored higher than long lists).
       - Optional: agreement between model suggestion and top lexical candidate.
   - Mark links as:
     - **high-confidence**: `confidence >= AUTO_APPLY_THRESHOLD` (e.g. 0.8).
     - **medium / low-confidence**: below threshold.

4. **Apply or stage links**
   - For high-confidence links:
     - Directly update `questions.json`:
       - Prefer setting/merging `question["outcome_ids"]` (array of strings).
       - Optionally sync `question["outcomes"]` for backward compatibility.
   - For medium/low-confidence links:
     - Store them under a **suggested links** structure (e.g. in `preferences` or a separate per-module JSON under config home).
     - Surface them in the Module Editor as **“AI-suggested outcomes”** for each question:
       - One-click “Accept suggestions”.
       - Or per-question toggle for each suggested outcome.

5. **Integration with coverage and diagnostics**
   - After applying links:
     - Recompute `outcome_stats` via existing engine routines.
   - Extend Module Metadata diagnostics to show:
     - **Syllabus outcomes**: K.
     - **Outcomes with ≥1 linked question**: L / K.
     - **Questions with explicit outcome_ids**: N / M.
     - **Questions with AI-suggested links pending review**: P.

---

## 3. Resource-efficiency strategies

### 3.1 Minimize LLM calls

- Prefer pure-Python heuristics for:
  - Chapter restriction.
  - Lexical overlap / similarity scoring.
  - Concept graph-based narrowing.
- Only call the LLM when:
  - A question has **at least one reasonable candidate** outcome, and
  - The question is not already explicitly tagged with `outcome_ids`.
- Avoid “LLM per question”: always **batch multiple questions** per call up to a tight token budget.

### 3.2 Local, schema-bound models

- Use the same **local LLM stack** as tutor/syllabus actions (llama-server + Ollama fallback).
- Ensure prompts are **short and schema-first**:
  - No long natural-language instructions repeated per call.
  - Use shared prompt fragments from `studyplan/ai/prompt_design.py`.

### 3.3 Optional RAG refinement only for hard cases

- Default path should **not use PDF RAG**:
  - It relies only on outcome texts, concept graph, and question text.
- For **ambiguous questions** (e.g. multiple outcomes tie in lexical score):
  - Optionally run a second LLM pass with a small RAG context:
    - Pull 1–2 short snippets from the syllabus/study guide for the top 1–2 candidate outcomes.
    - Ask the model to choose between those candidates only.
- Cap this refinement so that only a small fraction of questions use RAG at all.

### 3.4 Caching and idempotency

- Cache per `(module_id, chapter, normalized_question_text)`:
  - Final `outcome_ids`.
  - Confidence score.
  - Source (`explicit`, `ai_high_conf`, `ai_suggested`).
- When running again:
  - Reuse existing links if:
    - Question text is unchanged, and
    - The outcome id still exists in `syllabus_structure`.
  - Drop or downgrade links if their ids are no longer present after syllabus changes.

---

## 4. Example LLM contract (batched linking)

This is intentionally schematic; final wording should use shared fragments in `studyplan/ai/prompt_design.py`.

### 4.1 JSON schema (conceptual)

- Input (for one batch):

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

- Output:

```json
{
  "links": [
    {"question_id": "q1", "outcome_ids": ["C1b"]},
    {"question_id": "q2", "outcome_ids": ["C1a"]}
  ]
}
```

### 4.2 Prompt outline

1. **Role / task** (1–2 sentences):
   - “You link exam questions to syllabus learning outcomes. Use only the provided candidate outcome ids for each question.”
2. **Schema** (one-line / minimal):
   - Output: `{ "links": [ { "question_id": string, "outcome_ids": string[] } ] }`.
3. **Rules** (short bullets):
   - Only choose from `candidate_outcome_ids` for that question.
   - Choose 0–N outcomes; if none fit, return an empty list for that question.
   - Copy `question_id` exactly.
   - Do not invent new outcome ids or text.
4. **Payload**:
   - The JSON from §4.1 under “Payload JSON:”.
5. **Format requirement**:
   - “Return only the JSON object. No markdown, no code block, no explanation.”

This pattern matches the app’s existing **schema-first, JSON-only** contract style.

---

## 5. Integration points

- **Engine / service layer**:
  - Add a helper (e.g. `auto_link_questions_to_outcomes`) in a new or existing service module under `studyplan/`.
  - It coordinates:
    - Candidate generation (lexical + concept graph).
    - Batch formation.
    - LLM calls via existing AI runtime.
    - Confidence scoring and persistence to `questions.json`.
- **UI / Module Editor**:
  - Add a “Link questions to outcomes (AI-assisted)” action:
    - Shows summary stats before/after.
    - Allows enabling/disabling **auto-apply** for high-confidence links.
  - Provide a filter or view for “questions with AI-suggested links”.

---

## 6. Safety and quality considerations

- **Never trust raw text**:
  - All model outputs are parsed as JSON and validated against the schema.
  - Invalid outputs trigger a retry or fall back to “no links” for that batch.
- **No destructive overwrite**:
  - Existing explicit `question["outcome_ids"]` should not be removed automatically.
  - AI links can **add** outcomes or fill gaps, but must not silently wipe manual tags.
- **Transparency**:
  - Each link should carry a simple `source` label and `confidence` value in diagnostics so advanced users can audit and adjust behaviour over time.

---

## 7. Suggested implementation order

1. **Heuristic candidate narrowing** (chapter + lexical + concept graph).
2. **Batched LLM linking** with schema-first, JSON-only contract.
3. **Confidence scoring + auto-apply threshold** and persistence to `questions.json`.
4. **UI and diagnostics** for viewing AI-suggested links and coverage deltas.
5. **Optional RAG refinement** for ambiguous cases, carefully capped.

This order delivers immediate value (automatic links for easy/clear questions) while containing cost and keeping humans in control for the harder edge cases.

